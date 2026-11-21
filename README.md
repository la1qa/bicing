# Bicing historical data pipeline

This project extracts historical Barcelona Bicing archives, normalizes their
CSV or JSON data, validates observations, and stores them in SQLite with
SQLAlchemy 2.

The target deployment is a small Linux server such as the Arduino UNO Q. The
laptop can run the same commands locally or connect to the optional read-only
HTTP API over the local network.

The initial pipeline stores:

- station metadata in `stations`;
- timestamped availability observations in `station_status`;
- metadata changes in `station_metadata_history`.

The importer is deliberately configurable. The inspected Bicing CSV format is
currently mapped for `last_updated`, mechanical bikes, electric bikes, and
empty docks. New source formats should be inspected before adding mappings.

## 1. Install the project

Open PowerShell in the project directory:

```powershell
cd C:\Users\laiaq\Desktop\projects\bicing
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell prevents activation, run the commands using
`.venv\Scripts\python.exe` instead.

## 2. Understand the data directories

- `data/raw/`: original downloaded archives; never modified by extraction.
- `data/raw/historical/`: optional location for historical archives.
- `data/raw/samples/`: small local files used for development.
- `data/processed/extracted/`: extracted archive contents.
- `data/bicing.sqlite`: generated SQLite database.

The paths are defined in [config.py](config.py), so commands do not depend on
the current working directory.

## 3. Initialize the database

This creates the SQLite file and all tables if they do not already exist:

```powershell
python -c "from config import DATABASE_PATH; from src.database.db import initialize_database; initialize_database(DATABASE_PATH); print(DATABASE_PATH)"
```

The import command also initializes the database automatically, so this step
can be skipped when running the complete pipeline.

## 4. Extract `.7z` archives

Put `.7z` files in `data/raw/historical/`, then run:

```powershell
python -c "from config import HISTORICAL_DIR, EXTRACTED_DATA_DIR; from src.ingestion.extract import extract_archives; results=extract_archives(HISTORICAL_DIR, EXTRACTED_DATA_DIR); [print(r) for r in results]"
```

Extraction:

- preserves the original archives;
- writes each archive to its own subdirectory;
- skips archives already marked as extracted;
- does not overwrite existing extracted files;
- reports corrupted or unsupported archives as errors.

For the archives currently stored directly in `data/raw/`, use:

```powershell
python -c "from config import RAW_DATA_DIR, EXTRACTED_DATA_DIR; from src.ingestion.extract import extract_archives; print(extract_archives(RAW_DATA_DIR, EXTRACTED_DATA_DIR))"
```

### Download station metadata archives

Station metadata archives are published in a separate Barcelona open-data
dataset. Discover and download them automatically through its CKAN API:

```powershell
python -m src.cli download-metadata
```

Download only a selected month:

```powershell
python -m src.cli download-metadata --month 2026_01
```

For the normal pipeline, import the latest station metadata directly from the
live GBFS JSON endpoint:

```bash
python -m src.cli import-live-metadata
```

Files are saved under `data/raw/metadata/`, are never overwritten, and are
downloaded through temporary `.part` files so interrupted downloads are not
mistaken for complete archives. Extract them separately:

```powershell
python -m src.cli extract `
  --source data/raw/metadata `
  --destination data/processed/metadata_extracted
```

Or use the dedicated command with the configured metadata directories:

```powershell
python -m src.cli extract-metadata
```

The metadata archive schema must be inspected before adding its database
mapping. The importer supports the observed station fields (`station_id`,
`name`, `physical_configuration`, `lat`, `lon`, `altitude`, `capacity`, and
`last_updated`) and does not treat metadata as status data.

Import metadata into both the current station table and the versioned history:

```powershell
python -m src.cli import-metadata
```

This updates `stations` with the latest metadata encountered and inserts
non-duplicate versions into `station_metadata_history`.

### Run the complete pipeline

On Linux or the Arduino UNO Q, run:

```bash
chmod +x setup_and_run.sh
./setup_and_run.sh
```

The script downloads station-status archives from the configured start date,
imports live station metadata from JSON, then extracts the archives and starts
the API. If an archive has already been extracted, it is not downloaded again.
Every step is repeatable: completed extractions are skipped and database
uniqueness rules skip already imported records.
Use `BICING_BATCH_SIZE=1000 ./setup_and_run.sh` to change the import batch size.

The metadata archive downloader remains history-capable. To build a metadata
history study later, run `python -m src.cli download-metadata`, then extract
and import the additional archives with `extract-metadata` and
`import-metadata`.

The script also creates `.venv`, installs `requirements.txt`, and starts the
FastAPI server after the database is ready. Configure the server with:

```bash
BICING_API_HOST=0.0.0.0 BICING_API_PORT=8000 ./setup_and_run.sh
```

After setup, start only the API without repeating ingestion:

```bash
sh launchAPI.sh
```

This uses `.venv/bin/python -m uvicorn`, so a system-wide `uvicorn` command is
not required.

The default host is `0.0.0.0`, which allows access from another machine on the
LAN. Stop the API with `Ctrl+C`; rerunning the script skips existing downloads,
completed extractions, and already imported records.

The default historical data window starts at `2024-01-01`, configured as
`DATA_START_DATE` in [config.py](config.py). The setup script converts this to
an inclusive archive month filter (`2024_01`) to avoid downloading older
archives. Override it for a different window with, for example,
`BICING_DATA_START_DATE=2023-01-01 ./setup_and_run.sh`.

Before downloading, the setup script also prunes archives, extracted
directories, status observations, and metadata-history rows older than this
date from the local Arduino dataset. Current station metadata is preserved.
This deletion is intentional; export or back up the database first if older
data may be needed for later analysis.

## 5. Import extracted files

Import all supported CSV and JSON files recursively with the CLI:

```powershell
python -m src.cli import
```

The default batch size is 5,000. It can be changed without changing code:

```powershell
python -m src.cli import --batch-size 1000
```

The report contains:

- `imported`: new observations inserted;
- `skipped`: duplicate or incomplete observations;
- `errors`: unsupported or invalid source details.
- parsing, validation, insertion, total duration, and records/second metrics.

Imports are repeatable. The unique `(station_id, timestamp, source)` constraint
prevents the same source observation from being inserted twice while allowing
historical and live sources to share a timestamp.

CSV files are read in chunks, so a 296 MB source file is not loaded entirely
into memory. Each batch is inserted with SQLAlchemy Core bulk insertion and
committed as one transaction. If an import is interrupted, rerunning it safely
skips already committed observations.

## 6. Benchmark ingestion

The benchmark generates synthetic data in a temporary directory and never
imports the historical dataset repeatedly:

```powershell
python -m src.cli benchmark
```

It compares batch sizes 500, 1,000, 5,000, and 10,000, reporting elapsed time,
throughput, and peak memory. A recent local benchmark of 10,000 rows showed
the 5,000-row batch as the fastest of those tested, at about 1,316 rows/sec.

## 7. Run the API

Start the API locally:

```powershell
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Endpoints:

- `GET /health`
- `GET /stations?limit=100&offset=0`
- `GET /stations/{station_id}`
- `GET /stations/{station_id}/status?limit=100&start=...&end=...`
- `GET /stations/{station_id}/changes?start=...&end=...`
- `GET /snapshots?start=...&end=...`
- `GET /snapshots/{timestamp}` (joins metadata valid at that timestamp)
- `GET /stats`

`/stations` exposes current metadata. `/snapshots/{timestamp}` exposes the
status observations at one UTC timestamp and resolves the matching historical
metadata version when available, falling back to current station metadata.
`/stations/{station_id}/changes` reports net differences from the previous
stored observation; these differences are not exact journey counts.

For access from another computer on the same network, bind to all interfaces:

```powershell
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Then replace `127.0.0.1` with the server's LAN address, for example
`http://192.168.1.50:8000/docs`. Only expose the API on a trusted network;
authentication is intentionally not implemented yet.

## 8. Preliminary UNO Q deployment

On the UNO Q Linux environment, install Python and copy the project and
archives to a storage location with enough capacity:

```bash
cd ~/bicing
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

# Historical station-status data
python -m src.cli extract \
  --source /home/arduino/bicing/data/raw/historical \
  --destination /home/arduino/bicing/data/processed/extracted
python -m src.cli import \
  --source /home/arduino/bicing/data/processed/extracted \
  --database /home/arduino/bicing/data/bicing.sqlite

# Or import station metadata through the same command
python -m src.cli import \
  --metadata \
  --source /home/arduino/bicing/data/processed/metadata_extracted \
  --database /home/arduino/bicing/data/bicing.sqlite

# Station metadata, if it has also been copied to the device
python -m src.cli extract-metadata \
  --source /home/arduino/bicing/data/raw/metadata \
  --destination /home/arduino/bicing/data/processed/metadata_extracted
python -m src.cli import-metadata \
  --source /home/arduino/bicing/data/processed/metadata_extracted \
  --database /home/arduino/bicing/data/bicing.sqlite

uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Deployment is not performed by this project. Configure storage paths through
CLI arguments or `config.py`, keep archives outside the database directory,
and avoid running multiple import processes against the same SQLite file.

## 9. Run the tests

```powershell
python -m pytest -q
```

Tests use temporary directories and temporary SQLite databases, so they do not
modify project data.

## 10. Run the geographical heatmap

The heatmap is a laptop-side client. It queries the Arduino API and never
opens the SQLite database directly. Install its separate visualization
dependencies and launch it with:

```bash
sh run_heatmap.sh
```

Set the API address when the API is running on the UNO Q:

```bash
BICING_API_URL=http://<UNO-Q-IP>:8000 sh run_heatmap.sh
```

In PowerShell, set the environment variable separately:

```powershell
$env:BICING_API_URL = "http://10.209.202.240:8000"
sh .\run_heatmap.sh
```

In the sidebar, select a date, then one of the actual snapshot times returned
for that date. Choose either `Gaussian spatial intensity` or
`Straight-line distance accessibility`.

Gaussian mode supports `Available bikes` or `Available docks` and an editable
bandwidth in metres. Distance mode supports mechanical bikes, e-bikes, total
bikes, and docks, with 100, 250, 500, and 1,000-metre thresholds. The client
makes one request for the selected snapshot and renders a continuous surface
over OpenStreetMap; it does not draw station markers.

The KDE projects WGS84 station coordinates into EPSG:25831 (ETRS89 / UTM zone
31N), so bandwidths represent metres. Each grid cell receives the sum of
station availability weighted by a Gaussian distance-decay kernel. Missing
coordinates or missing metric values are excluded, and the first version uses
a fixed Barcelona bounding box rather than computing a city boundary.

Distance mode projects station coordinates into EPSG:25831 and includes each
station in a raster cell when its direct projected distance is within the
selected threshold. Overlapping circles are additive: the value means the sum
of available units at all included stations, not a journey count or a
probability of service.

## Performance and integrity considerations

SQLite uses WAL mode, a 60-second busy timeout, and foreign-key enforcement.
WAL improves concurrent reads during imports, while the timeout handles short
writer contention. These settings do not make SQLite a multi-writer server;
run only one ingestion process at a time. `synchronous` remains at SQLite's
default for safer durability on a small device.

## Current limitations

- Station metadata files have not yet been confirmed from a historical archive,
  so metadata mappings remain extensible rather than source-specific.
- Timestamps are stored as UTC. Convert them to `Europe/Madrid` only for local
  time analysis.
- Analysis notebooks, dashboards, machine learning, and Arduino integration
  are intentionally out of scope for this initial implementation.

Raw archives, extracted files, and SQLite databases are excluded by
[.gitignore](.gitignore).