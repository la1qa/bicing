"""Validation reports for normalized observations."""
from dataclasses import dataclass, field
import pandas as pd
@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
def validate_status_frame(frame: pd.DataFrame, capacities: dict[str, int] | None = None) -> ValidationReport:
    report = ValidationReport(); missing = {"station_id", "timestamp"} - set(frame.columns)
    if missing: report.errors.append(f"Missing required columns: {sorted(missing)}"); return report
    if frame["station_id"].isna().any(): report.errors.append("Missing station IDs")
    if frame["timestamp"].isna().any(): report.errors.append("Missing timestamps")
    duplicates = frame.duplicated(["station_id", "timestamp"]).sum()
    if duplicates: report.warnings.append(f"{duplicates} duplicate observations")
    for column in ("mechanical_bikes_available", "ebikes_available", "docks_available"):
        if column in frame and (pd.to_numeric(frame[column], errors="coerce") < 0).any(): report.errors.append(f"Negative values in {column}")
    if capacities:
        for _, row in frame.iterrows():
            capacity = capacities.get(str(row["station_id"]))
            if capacity is not None and any(pd.notna(row.get(c)) and float(row[c]) > capacity for c in ("mechanical_bikes_available", "ebikes_available", "docks_available")):
                report.warnings.append(f"Availability exceeds capacity for station {row['station_id']}")
    return report