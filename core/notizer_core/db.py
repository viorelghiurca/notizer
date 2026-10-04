"""Datenbankmodell (SQLite über SQLAlchemy).

M0: Aufnahmen, Audiodateien, Ordner. M1: Transkript-Abschnitte, Sprecher,
Jobs und Einstellungen. Vorlagen und KI-Ergebnisse folgen in M3.

Neue Spalten in bestehenden Tabellen ergänzt ``_migrate`` beim Start, damit
Datenbanken aus älteren Versionen weiter funktionieren.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Zeitpunkte immer in UTC speichern und mit Zeitzone zurückgeben.

    SQLite kennt keine Zeitzonen; ohne diese Hülle kämen Zeiten ohne Zone zurück
    und die Oberfläche würde sie als Ortszeit lesen (2 Stunden Versatz im Sommer).
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    recordings: Mapped[list["Recording"]] = relationship(back_populates="folder")


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    # Zeitpunkt der Aufnahme (bei Import: Änderungsdatum der Datei, falls bekannt)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="import")  # import | pod
    # nur_audio | wird_transkribiert | transkribiert | fehler
    status: Mapped[str] = mapped_column(String(30), default="nur_audio")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # M1: Ergebnis der Transkription
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    folder: Mapped[Folder | None] = relationship(back_populates="recordings")
    audio_files: Mapped[list["AudioFile"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    segments: Mapped[list["Segment"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan", order_by="Segment.idx"
    )
    speakers: Mapped[list["RecordingSpeaker"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan", order_by="RecordingSpeaker.idx"
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


class RecordingSpeaker(Base):
    """Ein Sprecher innerhalb einer Aufnahme ("Sprecher 1" oder ein Name)."""

    __tablename__ = "recording_speakers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)  # Reihenfolge des ersten Auftretens, bestimmt die Farbe
    label: Mapped[str] = mapped_column(String(30))  # "Sprecher 1"
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    recording: Mapped[Recording] = relationship(back_populates="speakers")


class Segment(Base):
    """Ein Abschnitt des Transkripts: ein Sprecher, ein Zeitraum, ein Text."""

    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speaker_label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wort-Zeitstempel: [[start_s, end_s, "wort"], ...]
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)

    recording: Mapped[Recording] = relationship(back_populates="segments")


class Job(Base):
    """Hintergrundauftrag, z. B. eine Transkription."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="transcribe")
    # wartet | laeuft | fertig | fehler | abgebrochen
    status: Mapped[str] = mapped_column(String(20), default="wartet")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(200), default="Wartet")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


def _migrate(engine) -> None:  # noqa: ANN001
    """Fehlende Spalten in bestehenden Tabellen ergänzen (nur additive Änderungen)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'))


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
    _migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
