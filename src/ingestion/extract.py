"""Safe extraction of historical 7z archives."""
from dataclasses import dataclass
import logging
from pathlib import Path
import py7zr
LOGGER = logging.getLogger(__name__)
@dataclass(frozen=True)
class ExtractionResult:
    archive: Path
    destination: Path
    extracted: bool
    error: str | None = None
def extract_archives(dir: str | Path, destination: str | Path) -> list[ExtractionResult]:
    """Extract each archive once without overwriting existing extracted files."""
    target = Path(destination); target.mkdir(parents=True, exist_ok=True)
    results = []
    for archive in sorted(Path(dir).glob("*.7z")):
        out = target / archive.stem; marker = out / ".extracted"
        if marker.exists():
            results.append(ExtractionResult(archive, out, False)); continue
        try:
            out.mkdir(parents=True, exist_ok=True)
            with py7zr.SevenZipFile(archive) as seven_zip: seven_zip.extractall(path=out)
            marker.touch(); results.append(ExtractionResult(archive, out, True))
        except (OSError, py7zr.exceptions.Bad7zFile, py7zr.exceptions.UnsupportedCompressionMethodError) as exc:
            LOGGER.error("Could not extract %s: %s", archive, exc)
            results.append(ExtractionResult(archive, out, False, str(exc)))
    return results


def extract_metadata_archives(
    source: str | Path | None = None,
    destination: str | Path | None = None,
) -> list[ExtractionResult]:
    """Extract station-information archives into a separate output directory."""
    from config import METADATA_ARCHIVE_DIR, METADATA_EXTRACTED_DIR

    return extract_archives(
        source or METADATA_ARCHIVE_DIR,
        destination or METADATA_EXTRACTED_DIR,
    )