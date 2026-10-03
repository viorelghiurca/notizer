"""Datenbankmodell (SQLite über SQLAlchemy).

M0 enthält nur die Tabellen, die für Import, Ordner und Papierkorb nötig sind.
Transkript, Sprecher, Vorlagen und KI-Ergebnisse folgen in M1–M3 laut
Architekturdokument.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recordings: Mapped[list["Recording"]] = relationship(back_populates="folder")


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    # Zeitpunkt der Aufnahme (bei Import: Änderungsdatum der Datei, falls bekannt)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="import")  # import | pod
    # nur_audio | wird_transkribiert | transkribiert | fehler
    status: Mapped[str] = mapped_column(String(30), default="nur_audio")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    folder: Mapped[Folder | None] = relationship(back_populates="recordings")
    audio_files: Mapped[list["AudioFile"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(500))  # relativ zum Datenordner
    kind: Mapped[str] = mapped_column(String(20), default="original")  # original | mono_mix
    original_name: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(10))  # mp3 | m4a | wav
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))

    recording: Mapped[Recording] = relationship(back_populates="audio_files")


def make_session_factory(db_path: Path) -> sessionmaker:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
