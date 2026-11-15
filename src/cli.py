"""Command-line entry points for extraction, import, and benchmarking."""

import argparse
import logging

from config import DATABASE_PATH, EXTRACTED_DATA_DIR, HISTORICAL_DIR
from src.database.db import initialize_database
from src.ingestion.extract import extract_archives
from src.ingestion.import_data import DEFAULT_BATCH_SIZE, import_files


def main() -> None:
    """Run one pipeline command."""
    parser = argparse.ArgumentParser(description="Bicing data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--source", default=str(HISTORICAL_DIR))
    extract.add_argument("--destination", default=str(EXTRACTED_DATA_DIR))
    importer = subparsers.add_parser("import")
    importer.add_argument("--source", default=str(EXTRACTED_DATA_DIR))
    importer.add_argument("--database", default=str(DATABASE_PATH))
    importer.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    subparsers.add_parser("benchmark")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "extract":
        for result in extract_archives(args.source, args.destination):
            print(result)
    elif args.command == "import":
        report = import_files(
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
