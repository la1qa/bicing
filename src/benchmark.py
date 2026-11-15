"""Small repeatable ingestion benchmark for batch-size comparisons."""

from pathlib import Path
import tempfile
import time
import tracemalloc

import pandas as pd

from src.database.db import initialize_database
from src.ingestion.import_data import import_files


def create_synthetic_csv(path: Path, rows: int = 10_000) -> None:
    """Create a representative status CSV without using project data."""
    frame = pd.DataFrame({
        "station_id": [str(index % 100) for index in range(rows)],
        "last_updated": [1_700_000_000 + index for index in range(rows)],
        "num_bikes_available_types.mechanical": [index % 10 for index in range(rows)],
        "num_bikes_available_types.ebike": [index % 5 for index in range(rows)],
        "num_docks_available": [20 - index % 10 for index in range(rows)],
    })
    frame.to_csv(path, index=False)


def benchmark(batch_sizes: tuple[int, ...] = (500, 1_000, 5_000, 10_000), rows: int = 10_000) -> list[dict[str, float | int]]:
    """Benchmark each batch size against a fresh temporary database."""
    results = []
    with tempfile.TemporaryDirectory(prefix="bicing-benchmark-") as directory:
        root = Path(directory)
        source = root / "synthetic.csv"
        create_synthetic_csv(source, rows)
        for batch_size in batch_sizes:
            database = root / f"batch-{batch_size}.sqlite"
            tracemalloc.start()
            started = time.perf_counter()
            engine = initialize_database(database)
            report = import_files(engine, root, batch_size=batch_size)
            engine.dispose()
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results.append({
                "batch_size": batch_size,
                "rows": report.records_processed,
                "seconds": round(elapsed, 3),
                "records_per_second": round(rows / elapsed, 1) if elapsed else 0,
                "peak_megabytes": round(peak / 1024 / 1024, 2),
            })
    return results


if __name__ == "__main__":
    for result in benchmark():
        print(result)
