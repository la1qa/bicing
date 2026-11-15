"""Schema-agnostic source transformations."""
from datetime import datetime, timezone
import re
from typing import Any
import pandas as pd
def normalize_column_name(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())).strip("_")
def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy(); result.columns = [normalize_column_name(c) for c in result.columns]; return result
def normalize_timestamp(value: Any) -> datetime | None:
    if value is None or pd.isna(value): return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = pd.to_datetime(value, unit="s", utc=True, errors="coerce")
    else:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.to_pydatetime(warn=False).astimezone(timezone.utc)