"""Download Bicing archives from the Barcelona open-data CKAN API."""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import urllib.request

LOGGER = logging.getLogger(__name__)
METADATA_PACKAGE_API = (
    "https://opendata-ajuntament.barcelona.cat/data/api/3/action/"
    "package_show?id=informacio-estacions-bicing"
)
TIMELINE_PACKAGE_API = (
    "https://opendata-ajuntament.barcelona.cat/data/api/3/action/"
    "package_show?id=estat-estacions-bicing"
)


@dataclass(frozen=True)
class DownloadResult:
    """Outcome for one remote archive."""

    name: str
    destination: Path | None
    downloaded: bool
    error: str | None = None


def download_metadata_archives(
    destination: str | Path,
    months: set[str] | None = None,
    latest_only: bool = False,
) -> list[DownloadResult]:
    """Download metadata archives without overwriting existing files.

    ``latest_only`` selects the newest ``YYYY_MM`` resource while retaining
    the full-resource behavior for historical metadata studies.
    """
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    resources = _metadata_resources()
    if latest_only and resources:
        latest_month = max(resource["name"][:7] for resource in resources)
        resources = [
            resource for resource in resources
            if resource["name"][:7] == latest_month
        ]
    results: list[DownloadResult] = []
    for resource in resources:
        name = resource["name"]
        month = name[:7]
        if months and month not in months:
            continue
        destination_file = target / name
        if destination_file.exists():
            results.append(DownloadResult(name, destination_file, False))
            continue
        temporary_file = destination_file.with_suffix(destination_file.suffix + ".part")
        try:
            request = urllib.request.Request(
                resource["url"],
                headers={"User-Agent": "bicing-project/0.1"},
            )
            with urllib.request.urlopen(request) as response, temporary_file.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temporary_file.replace(destination_file)
            results.append(DownloadResult(name, destination_file, True))
            LOGGER.info("Downloaded %s", name)
        except (OSError, ValueError) as exc:
            temporary_file.unlink(missing_ok=True)
            LOGGER.error("Could not download %s: %s", name, exc)
            results.append(DownloadResult(name, None, False, str(exc)))
    return results


def _metadata_resources() -> list[dict[str, str]]:
    """Return CKAN resources matching the monthly metadata archive naming convention."""
    request = urllib.request.Request(
        METADATA_PACKAGE_API,
        headers={"User-Agent": "bicing-project/0.1"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    if not payload.get("success"):
        raise ValueError("CKAN metadata request was unsuccessful")
    resources = []
    for resource in payload["result"]["resources"]:
        name = resource.get("name", "")
        url = resource.get("url")
        if name.endswith("_INFORMACIO.7z") and url:
            resources.append({"name": name, "url": url})
    return resources




def download_timeline_archives(
    destination: str | Path,
    months: set[str] | None = None,
    start_month: str | None = None,
) -> list[DownloadResult]:
    """Download timeline archives from an optional inclusive starting month."""
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    resources = _timeline_resources()
    results: list[DownloadResult] = []
    for resource in resources:
        name = resource["name"]
        month = name[:7]
        if months and month not in months:
            continue
        if start_month and month < start_month:
            continue
        destination_file = target / name
        if destination_file.exists():
            results.append(DownloadResult(name, destination_file, False))
            continue
        temporary_file = destination_file.with_suffix(destination_file.suffix + ".part")
        try:
            request = urllib.request.Request(
                resource["url"],
                headers={"User-Agent": "bicing-project/0.1"},
            )
            with urllib.request.urlopen(request) as response, temporary_file.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temporary_file.replace(destination_file)
            results.append(DownloadResult(name, destination_file, True))
            LOGGER.info("Downloaded %s", name)
        except (OSError, ValueError) as exc:
            temporary_file.unlink(missing_ok=True)
            LOGGER.error("Could not download %s: %s", name, exc)
            results.append(DownloadResult(name, None, False, str(exc)))
    return results



def _timeline_resources() -> list[dict[str, str]]:
    """Return CKAN resources matching monthly station-status archive names."""
    request = urllib.request.Request(
        TIMELINE_PACKAGE_API,
        headers={"User-Agent": "bicing-project/0.1"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    if not payload.get("success"):
        raise ValueError("CKAN timeline request was unsuccessful")
    resources = []
    for resource in payload["result"]["resources"]:
        name = resource.get("name", "")
        url = resource.get("url")
        if name.endswith("_ESTACIONS.7z") and url:
            resources.append({"name": name, "url": url})
    return resources
