"""Small read-only FastAPI service for remote queries."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from src.database.db import (
    Station,
    StationMetadataHistory,
    StationStatus,
    create_engine_for,
)
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

    @app.get("/stations/{station_id}")
    def station(station_id: str) -> dict[str, object]:
        with engine.connect() as connection:
            row = connection.execute(
                select(
                    Station.station_id, Station.name, Station.latitude, Station.longitude,
                    Station.altitude, Station.capacity, Station.physical_configuration,
                    Station.last_updated,
                ).where(Station.station_id == station_id)
            ).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown station: {station_id}")
        return dict(row)

    @app.get("/snapshots")
    def snapshots(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        statement = select(StationStatus.timestamp).distinct().order_by(
            StationStatus.timestamp
        ).limit(limit).offset(offset)
        statement = _apply_time_filters(statement, start, end)
        with engine.connect() as connection:
            timestamps = connection.execute(statement).scalars().all()
        return {
            "items": [{"timestamp": timestamp} for timestamp in timestamps],
            "limit": limit,
            "offset": offset,
        }

    @app.get("/snapshots/{timestamp}")
    def snapshot(
        timestamp: str,
        limit: int = Query(500, ge=1, le=5000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, object]:
        snapshot_time = _parse_timestamp(timestamp)
        history = aliased(StationMetadataHistory)
        newer_history = aliased(StationMetadataHistory)
        latest_history = and_(
            history.station_id == StationStatus.station_id,
            history.valid_from <= snapshot_time,
            or_(history.valid_to.is_(None), history.valid_to > snapshot_time),
            ~exists(
                select(1).where(
                    newer_history.station_id == history.station_id,
                    newer_history.valid_from <= snapshot_time,
                    newer_history.valid_from > history.valid_from,
                )
            ),
        )
        statement = (
            select(
                StationStatus.id,
                StationStatus.station_id,
                StationStatus.timestamp,
                StationStatus.mechanical_bikes_available,
                StationStatus.ebikes_available,
                StationStatus.docks_available,
                StationStatus.is_installed,
                StationStatus.is_renting,
                StationStatus.is_returning,
                StationStatus.source,
                StationStatus.source_file,
                func.coalesce(history.name, Station.name).label("name"),
                func.coalesce(history.latitude, Station.latitude).label("latitude"),
                func.coalesce(history.longitude, Station.longitude).label("longitude"),
                func.coalesce(history.capacity, Station.capacity).label("capacity"),
                func.coalesce(
                    history.physical_configuration,
                    Station.physical_configuration,
                ).label("physical_configuration"),
                Station.altitude,
            )
            .join(Station, Station.station_id == StationStatus.station_id)
            .outerjoin(history, latest_history)
            .where(StationStatus.timestamp == snapshot_time)
            .order_by(StationStatus.station_id)
            .limit(limit)
            .offset(offset)
        )
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return {
            "timestamp": snapshot_time,
            "items": [dict(row) for row in rows],
            "limit": limit,
            "offset": offset,
        }

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
                StationStatus.is_renting, StationStatus.is_returning,
                StationStatus.source, StationStatus.source_file,
            )
            .where(StationStatus.station_id == station_id)
            .order_by(StationStatus.timestamp)
            .limit(limit)
            .offset(offset)
        )
        statement = _apply_time_filters(statement, start, end)
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset}

    @app.get("/stations/{station_id}/changes")
    def station_changes(
        station_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        start_timestamp = _parse_timestamp(start) if start is not None else None
        end_timestamp = _parse_timestamp(end) if end is not None else None
        base_statement = select(
            StationStatus.timestamp,
            StationStatus.mechanical_bikes_available,
            StationStatus.ebikes_available,
            StationStatus.docks_available,
        ).where(
            StationStatus.station_id == station_id
        )
        statement = base_statement.order_by(StationStatus.timestamp)
        if end_timestamp is not None:
            statement = statement.where(StationStatus.timestamp <= end_timestamp)
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
            if start_timestamp is not None:
                previous_statement = base_statement.where(
                    StationStatus.timestamp < start_timestamp
                ).order_by(StationStatus.timestamp.desc()).limit(1)
                previous_rows = connection.execute(previous_statement).mappings().all()
                rows = previous_rows + rows
        previous = None
        items = []
        for row in rows:
            if start_timestamp is not None and row["timestamp"] < start_timestamp:
                previous = row
                continue
            item = {
                "timestamp": row["timestamp"],
                "mechanical_bikes_change": _difference(
                    previous, row, "mechanical_bikes_available"
                ),
                "ebikes_change": _difference(previous, row, "ebikes_available"),
                "docks_change": _difference(previous, row, "docks_available"),
            }
            items.append(item)
            previous = row
        return {
            "station_id": station_id,
            "items": items[offset:offset + limit],
            "limit": limit,
            "offset": offset,
        }

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


def _parse_timestamp(value: str):
    timestamp = normalize_timestamp(value)
    if timestamp is None:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {value}")
    return timestamp


def _apply_time_filters(statement, start: str | None, end: str | None):
    if start is not None:
        statement = statement.where(
            StationStatus.timestamp >= _parse_timestamp(start)
        )
    if end is not None:
        statement = statement.where(
            StationStatus.timestamp <= _parse_timestamp(end)
        )
    return statement


def _difference(previous, current, field: str):
    if previous is None or previous[field] is None or current[field] is None:
        return None
    return current[field] - previous[field]


def build_app() -> FastAPI:
    """Build the default application from project configuration."""
    from config import DATABASE_PATH

    return create_app(DATABASE_PATH)


app = build_app()
