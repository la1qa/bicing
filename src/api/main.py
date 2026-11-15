"""Small read-only FastAPI service for remote queries."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import func, select

from src.database.db import Station, StationStatus, create_engine_for
from src.processing.transformations import normalize_timestamp


def create_app(database_path: str | Path) -> FastAPI:
    """Create an API application connected to an existing SQLite database."""
    engine = create_engine_for(database_path)
    app = FastAPI(title="Bicing API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return {"status": "ok", "database": "connected"}
        except Exception as exc:
            return {"status": "error", "database": str(exc)}

    @app.get("/stations")
    def stations(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, object]:
        with engine.connect() as connection:
            rows = connection.execute(
                select(
                    Station.station_id, Station.name, Station.latitude, Station.longitude,
                    Station.altitude, Station.capacity, Station.physical_configuration,
                    Station.last_updated,
                ).order_by(Station.station_id).limit(limit).offset(offset)
            ).mappings().all()
        return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset}

    @app.get("/stations/{station_id}/status")
    def station_status(
        station_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        statement = (
            select(
                StationStatus.id, StationStatus.station_id, StationStatus.timestamp,
                StationStatus.mechanical_bikes_available, StationStatus.ebikes_available,
                StationStatus.docks_available, StationStatus.is_installed,
                StationStatus.is_renting, StationStatus.is_returning, StationStatus.source_file,
            )
            .where(StationStatus.station_id == station_id)
            .order_by(StationStatus.timestamp)
            .limit(limit)
            .offset(offset)
        )
        for value, operator in ((start, ">="), (end, "<=")):
            if value is not None:
                timestamp = normalize_timestamp(value)
                if timestamp is None:
                    raise HTTPException(status_code=400, detail=f"Invalid timestamp: {value}")
                statement = statement.where(
                    StationStatus.timestamp >= timestamp
                    if operator == ">="
                    else StationStatus.timestamp <= timestamp
                )
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset}

    @app.get("/stats")
    def stats() -> dict[str, object]:
        with engine.connect() as connection:
            station_count = connection.scalar(select(func.count()).select_from(Station))
            observation_count = connection.scalar(select(func.count()).select_from(StationStatus))
            first = connection.scalar(select(func.min(StationStatus.timestamp)))
            last = connection.scalar(select(func.max(StationStatus.timestamp)))
        return {
            "station_count": station_count,
            "observation_count": observation_count,
            "first_timestamp": first,
            "last_timestamp": last,
        }

    return app


def build_app() -> FastAPI:
    """Build the default application from project configuration."""
    from config import DATABASE_PATH

    return create_app(DATABASE_PATH)


app = build_app()
