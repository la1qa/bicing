"""Command-line entry points for extraction, import, and benchmarking."""

import argparse
import logging

from config import (
    DATABASE_PATH,
    EXTRACTED_DATA_DIR,
    HISTORICAL_DIR,
    METADATA_ARCHIVE_DIR,
    METADATA_EXTRACTED_DIR,
)
from src.database.db import initialize_database
from src.ingestion.extract import extract_archives, extract_metadata_archives
from src.ingestion.download import download_metadata_archives, download_timeline_archives
from src.ingestion.import_data import DEFAULT_BATCH_SIZE, import_files, import_metadata_files


def main() -> None:
    """Run one pipeline command."""
    parser = argparse.ArgumentParser(description="Bicing data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--source", default=str(HISTORICAL_DIR))
    extract.add_argument("--destination", default=str(EXTRACTED_DATA_DIR))
    metadata_extract = subparsers.add_parser("extract-metadata")
    metadata_extract.add_argument("--source", default=str(METADATA_ARCHIVE_DIR))
    metadata_extract.add_argument("--destination", default=str(METADATA_EXTRACTED_DIR))
    download_timeline = subparsers.add_parser("download-timeline")
    download_timeline.add_argument("--destination", default=str(HISTORICAL_DIR))
    download_timeline.add_argument("--month", action="append", help="Month such as 2026_01; repeat for multiple months")
    download_metadata = subparsers.add_parser("download-metadata")
    download_metadata.add_argument("--destination", default=str(METADATA_ARCHIVE_DIR))
    download_metadata.add_argument("--month", action="append", help="Month such as 2026_01; repeat for multiple months")
    download_metadata.add_argument(
        "--latest",
        action="store_true",
        help="Download only the newest metadata month",
    )
    importer = subparsers.add_parser("import")
    importer.add_argument("--source")
    importer.add_argument("--database", default=str(DATABASE_PATH))
    importer.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    importer.add_argument(
        "--metadata",
        action="store_true",
        help="Import station metadata instead of station-status observations",
    )
    metadata_importer = subparsers.add_parser("import-metadata")
    metadata_importer.add_argument("--source", default=str(METADATA_EXTRACTED_DIR))
    metadata_importer.add_argument("--database", default=str(DATABASE_PATH))
    metadata_importer.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    subparsers.add_parser("benchmark")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "extract":
        for result in extract_archives(args.source, args.destination):
            print(result)
    elif args.command == "extract-metadata":
        for result in extract_metadata_archives(args.source, args.destination):
            print(result)
    elif args.command == "download-timeline":
        months = set(args.month) if args.month else None
        for result in download_timeline_archives(args.destination, months):
            print(result)
    elif args.command == "download-metadata":
        months = set(args.month) if args.month else None
        for result in download_metadata_archives(args.destination, months, args.latest):
            print(result)
    elif args.command == "import":
        source = args.source or (
            METADATA_EXTRACTED_DIR if args.metadata else EXTRACTED_DATA_DIR
        )
        importer_function = import_metadata_files if args.metadata else import_files
        report = importer_function(
            initialize_database(args.database), source, batch_size=args.batch_size
        )
        print(report)
    elif args.command == "import-metadata":
        report = import_metadata_files(
            initialize_database(args.database),
            args.source,
            batch_size=args.batch_size,
        )
        print(report)
    else:
        from src.benchmark import benchmark

        for result in benchmark():
            print(result)


if __name__ == "__main__":
    main()
