"""SQLAlchemy models and SQLite session management for the Bicing database.

SQLite stores ``DateTime`` values without timezone metadata.  ``UTCDateTime``
therefore stores naive UTC values and restores the UTC timezone on reads.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware or naive datetimes as naive UTC and return aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).replace(tzinfo=None)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    """Base class for future migration-compatible declarative models."""


class Station(Base):
    """Current/latest known metadata for one station."""

    __tablename__ = "stations"

    station_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    altitude: Mapped[Optional[float]] = mapped_column(Float)
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    physical_configuration: Mapped[Optional[str]] = mapped_column(String)
    last_updated: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    statuses: Mapped[list["StationStatus"]] = relationship(
        back_populates="station",
        passive_deletes=True,
    )
    metadata_history: Mapped[list["StationMetadataHistory"]] = relationship(
        back_populates="station",
        passive_deletes=True,
    )


class StationStatus(Base):
    """Immutable station availability observation at a UTC instant."""

    __tablename__ = "station_status"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "timestamp", "source",
            name="uq_station_status_observation",
        ),
        Index("ix_station_status_station_timestamp", "station_id", "timestamp"),
        Index("ix_station_status_timestamp_source", "timestamp", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.station_id", ondelete="RESTRICT"),
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    source: Mapped[str] = mapped_column(String, default="unknown", server_default="unknown")
    mechanical_bikes_available: Mapped[Optional[int]] = mapped_column(Integer)
    ebikes_available: Mapped[Optional[int]] = mapped_column(Integer)
    docks_available: Mapped[Optional[int]] = mapped_column(Integer)
    is_installed: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_renting: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_returning: Mapped[Optional[bool]] = mapped_column(Boolean)
    source_file: Mapped[Optional[str]] = mapped_column(String)

    station: Mapped[Station] = relationship(back_populates="statuses")


class StationMetadataHistory(Base):
    """A version of station metadata valid from ``valid_from`` to ``valid_to``."""

    __tablename__ = "station_metadata_history"
    __table_args__ = (
        UniqueConstraint("station_id", "valid_from", name="uq_station_metadata_valid_from"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_station_metadata_valid_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.station_id", ondelete="RESTRICT"),
        index=True,
    )
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime)
    valid_to: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    name: Mapped[Optional[str]] = mapped_column(String)
    physical_configuration: Mapped[Optional[str]] = mapped_column(String)

    station: Mapped[Station] = relationship(back_populates="metadata_history")


def create_engine_for(path: str | Path) -> Engine:
    """Create a SQLite engine and enable foreign-key enforcement."""
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
        connect_args={"timeout": 60},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("PRAGMA journal_mode=WAL")

    return engine


def initialize_database(path: str | Path) -> Engine:
    """Create the database and current schema if they do not exist."""
    engine = create_engine_for(path)
    Base.metadata.create_all(engine)
    _migrate_existing_schema(engine)
    return engine


def _migrate_existing_schema(engine: Engine) -> None:
    """Apply additive changes needed by databases created before source support."""
    from sqlalchemy import inspect, text

    columns = {column["name"] for column in inspect(engine).get_columns("station_status")}
    if "source" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE station_status ADD COLUMN source VARCHAR DEFAULT 'unknown'")
            )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit a unit of work, roll it back on any exception, then close it."""
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
