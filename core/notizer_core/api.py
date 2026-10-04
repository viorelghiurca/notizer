"""REST-API des Cores.

M0: Aufnahmen importieren, Ordner, Papierkorb.
M1: Transkription mit Sprechertrennung, Aufträge mit Fortschritt (WebSocket),
Transkript bearbeiten, Export, Einstellungen.
"""


import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .audio import probe_duration
from .config import Settings
from .db import (
    AudioFile,
    Folder,
    Job,
    Recording,
    RecordingSpeaker,
    Segment,
    Setting,
    make_session_factory,
    new_id,
    utcnow,
)
from .engines import (
    WHISPER_MODELS,
    Diarizer,
    FasterWhisperTranscriber,
    SherpaDiarizer,
    Transcriber,
    diarization_downloaded,
    whisper_downloaded,
)
from .exporting import to_srt, to_txt
from .jobs import EventHub, JobManager, job_dict

# Ursprünge, von denen die Oberfläche lädt: Tauri unter Windows bzw. Linux/macOS,
# und der Vite-Entwicklungsserver.
ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


# ---------- Schemas ----------


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    sort: int
    count: int = 0


class FolderIn(BaseModel):
    name: str


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    folder_id: str | None
    recorded_at: datetime
    created_at: datetime
    duration_s: float | None
    source: str
    status: str
    favorite: bool
    deleted_at: datetime | None
    language: str | None = None
    transcript_model: str | None = None
    transcribed_at: datetime | None = None
    format: str | None = None
    original_name: str | None = None
    size_bytes: int | None = None


class RecordingPatch(BaseModel):
    title: str | None = None
    folder_id: str | None = None
    favorite: bool | None = None


class ImportResult(BaseModel):
    imported: list[RecordingOut]
    skipped: list[dict]


class TranscribeIn(BaseModel):
    language: str | None = None  # "de", "en", … oder "auto"; None = Einstellung
    diarize: bool | None = None
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    model: str | None = None


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    idx: int
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str | None
    edited: bool


class SpeakerOut(BaseModel):
    label: str
    name: str | None
    idx: int
    talk_ms: int


class TranscriptOut(BaseModel):
    recording_id: str
    language: str | None
    model: str | None
    transcribed_at: datetime | None
    speakers: list[SpeakerOut]
    segments: list[SegmentOut]


class SegmentPatch(BaseModel):
    text: str | None = None
    speaker_label: str | None = None


class SpeakerPatch(BaseModel):
    name: str | None = None


class SettingsModel(BaseModel):
    whisper_model: str = "large-v3-turbo"
    language: str = "de"  # "auto" = automatisch erkennen
    diarize: bool = True
    vocabulary: str = ""


class SettingsPatch(BaseModel):
    whisper_model: str | None = None
    language: str | None = None
    diarize: bool | None = None
    vocabulary: str | None = Field(default=None, max_length=2000)


class ExportIn(BaseModel):
    format: str = "txt"  # txt | srt
    path: str


# ---------- App ----------


def create_app(
    settings: Settings,
    transcriber: Transcriber | None = None,
    diarizer: Diarizer | None = None,
) -> FastAPI:
    settings.ensure_dirs()
    if not settings.token:
        settings.token = secrets.token_urlsafe(24)
    SessionLocal = make_session_factory(settings.db_path)

    app = FastAPI(title="Notizer Core", version=__version__)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_token(request: Request, call_next):  # noqa: ANN001, ANN202
        # Nur die eigene App darf zugreifen, auch wenn andere Programme auf dem PC
        # den Port finden. Audio-Links tragen das Token als Query-Parameter, weil
        # das <audio>-Element keine Header senden kann.
        path = request.url.path
        if request.method == "OPTIONS" or path == "/api/health" or not path.startswith("/api"):
            return await call_next(request)
        sent = request.headers.get("x-notizer-token") or request.query_params.get("token")
        if not sent or not secrets.compare_digest(sent, settings.token):
            return JSONResponse({"detail": "Ungültiges Token"}, status_code=401)
        return await call_next(request)

    def get_db():  # noqa: ANN202
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    Db = Annotated[Session, Depends(get_db)]

    def to_out(rec: Recording) -> RecordingOut:
        out = RecordingOut.model_validate(rec)
        original = next((a for a in rec.audio_files if a.kind == "original"), None)
        if original:
            out.format = original.format
            out.original_name = original.original_name
            out.size_bytes = original.size_bytes
        return out

    def get_recording(db: Session, rec_id: str) -> Recording:
        rec = db.get(Recording, rec_id, options=[selectinload(Recording.audio_files)])
        if rec is None:
            raise HTTPException(404, "Aufnahme nicht gefunden")
        return rec

    def delete_files(rec: Recording) -> None:
        for audio in rec.audio_files:
            (settings.data_dir / audio.path).unlink(missing_ok=True)

    def purge_trash(db: Session) -> int:
        limit = utcnow() - timedelta(days=settings.trash_days)
        old = db.scalars(
            select(Recording)
            .options(selectinload(Recording.audio_files))
            .where(Recording.deleted_at.is_not(None), Recording.deleted_at < limit)
        ).all()
        for rec in old:
            delete_files(rec)
            db.delete(rec)
        db.commit()
        return len(old)

    with SessionLocal() as db:
        purge_trash(db)

    # ----- Einstellungen (in der Datenbank) -----

    def load_settings() -> dict:
        with SessionLocal() as db:
            stored = {row.key: row.value for row in db.scalars(select(Setting)).all()}
        return SettingsModel(**{k: v for k, v in stored.items() if k in SettingsModel.model_fields}).model_dump()

    hub = EventHub()
    models_dir = settings.data_dir / "models"
    jobs = JobManager(
        SessionLocal,
        settings.data_dir,
        transcriber or FasterWhisperTranscriber(models_dir),
        diarizer or SherpaDiarizer(models_dir),
        load_settings,
        hub,
    )
    jobs.recover()
    app.state.jobs = jobs
    app.state.hub = hub

    # ----- Status -----

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/info")
    def info() -> dict:
        return {
            "version": __version__,
            "data_dir": str(settings.data_dir),
            "allowed_extensions": list(settings.allowed_extensions),
            "trash_days": settings.trash_days,
        }

    # ----- Aufnahmen -----

    @app.get("/api/recordings", response_model=list[RecordingOut])
    def list_recordings(
        db: Db,
        folder_id: str | None = None,
        unfiled: bool = False,
        trash: bool = False,
        q: str | None = Query(default=None, max_length=200),
    ) -> list[RecordingOut]:
        stmt = select(Recording).options(selectinload(Recording.audio_files))
        stmt = stmt.where(
            Recording.deleted_at.is_not(None) if trash else Recording.deleted_at.is_(None)
        )
        if folder_id:
            stmt = stmt.where(Recording.folder_id == folder_id)
        if unfiled:
            stmt = stmt.where(Recording.folder_id.is_(None))
        if q:
            in_text = select(Segment.recording_id).where(Segment.text.icontains(q))
            stmt = stmt.where(or_(Recording.title.icontains(q), Recording.id.in_(in_text)))
        order = Recording.deleted_at.desc() if trash else Recording.recorded_at.desc()
        return [to_out(r) for r in db.scalars(stmt.order_by(order)).all()]

    @app.post("/api/recordings/import", response_model=ImportResult)
    async def import_recordings(
        db: Db,
        files: Annotated[list[UploadFile], File(description="MP3, M4A oder WAV")],
        last_modified: Annotated[list[int] | None, Form()] = None,
        folder_id: Annotated[str | None, Form()] = None,
    ) -> ImportResult:
        if folder_id and db.get(Folder, folder_id) is None:
            raise HTTPException(404, "Ordner nicht gefunden")
        imported: list[RecordingOut] = []
        skipped: list[dict] = []
        for index, upload in enumerate(files):
            name = Path(upload.filename or "aufnahme").name
            ext = Path(name).suffix.lower()
            if ext not in settings.allowed_extensions:
                skipped.append({"name": name, "reason": "Format nicht unterstützt (nur MP3, M4A, WAV)"})
                continue

            rec_id = new_id()
            rel_path = Path("audio") / f"{rec_id}{ext}"
            target = settings.data_dir / rel_path
            digest = hashlib.sha256()
            size = 0
            with target.open("wb") as out:
                while chunk := await upload.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            if size == 0:
                target.unlink(missing_ok=True)
                skipped.append({"name": name, "reason": "Datei ist leer"})
                continue

            recorded_at = utcnow()
            if last_modified and index < len(last_modified) and last_modified[index] > 0:
                recorded_at = datetime.fromtimestamp(last_modified[index] / 1000, tz=timezone.utc)

            rec = Recording(
                id=rec_id,
                title=Path(name).stem.replace("_", " ").strip() or "Aufnahme",
                folder_id=folder_id,
                recorded_at=recorded_at,
                duration_s=probe_duration(target),
                source="import",
            )
            rec.audio_files.append(
                AudioFile(
                    path=rel_path.as_posix(),
                    original_name=name,
                    format=ext.lstrip("."),
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                )
            )
            db.add(rec)
            db.commit()
            imported.append(to_out(rec))
        return ImportResult(imported=imported, skipped=skipped)

    @app.get("/api/recordings/{rec_id}", response_model=RecordingOut)
    def read_recording(rec_id: str, db: Db) -> RecordingOut:
        return to_out(get_recording(db, rec_id))

    @app.patch("/api/recordings/{rec_id}", response_model=RecordingOut)
    def update_recording(rec_id: str, patch: RecordingPatch, db: Db) -> RecordingOut:
        rec = get_recording(db, rec_id)
        data = patch.model_dump(exclude_unset=True)
        if "title" in data:
            title = (data["title"] or "").strip()
            if not title:
                raise HTTPException(422, "Titel darf nicht leer sein")
            rec.title = title
        if "folder_id" in data:
            if data["folder_id"] and db.get(Folder, data["folder_id"]) is None:
                raise HTTPException(404, "Ordner nicht gefunden")
            rec.folder_id = data["folder_id"]
        if "favorite" in data and data["favorite"] is not None:
            rec.favorite = data["favorite"]
        db.commit()
        return to_out(rec)

    @app.delete("/api/recordings/{rec_id}", response_model=RecordingOut)
    def trash_recording(rec_id: str, db: Db) -> RecordingOut:
        rec = get_recording(db, rec_id)
        rec.deleted_at = utcnow()
        db.commit()
        return to_out(rec)

    @app.post("/api/recordings/{rec_id}/restore", response_model=RecordingOut)
    def restore_recording(rec_id: str, db: Db) -> RecordingOut:
        rec = get_recording(db, rec_id)
        rec.deleted_at = None
        db.commit()
        return to_out(rec)

    @app.delete("/api/recordings/{rec_id}/permanent", status_code=204)
    def delete_recording(rec_id: str, db: Db) -> None:
        rec = get_recording(db, rec_id)
        if rec.deleted_at is None:
            raise HTTPException(409, "Erst in den Papierkorb verschieben")
        delete_files(rec)
        db.delete(rec)
        db.commit()

    @app.delete("/api/trash", status_code=204)
    def empty_trash(db: Db) -> None:
        recs = db.scalars(
            select(Recording)
            .options(selectinload(Recording.audio_files))
            .where(Recording.deleted_at.is_not(None))
        ).all()
        for rec in recs:
            delete_files(rec)
            db.delete(rec)
        db.commit()

    @app.get("/api/recordings/{rec_id}/audio")
    def recording_audio(rec_id: str, db: Db) -> FileResponse:
        rec = get_recording(db, rec_id)
        original = next((a for a in rec.audio_files if a.kind == "original"), None)
        if original is None:
            raise HTTPException(404, "Keine Audiodatei")
        media = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav"}.get(original.format)
        return FileResponse(settings.data_dir / original.path, media_type=media)

    # ----- Ordner -----

    def folder_out(db: Session, folder: Folder) -> FolderOut:
        out = FolderOut.model_validate(folder)
        out.count = sum(1 for r in folder.recordings if r.deleted_at is None)
        return out

    @app.get("/api/folders", response_model=list[FolderOut])
    def list_folders(db: Db) -> list[FolderOut]:
        folders = db.scalars(
            select(Folder).options(selectinload(Folder.recordings)).order_by(Folder.sort, Folder.name)
        ).all()
        return [folder_out(db, f) for f in folders]

    @app.get("/api/counts")
    def counts(db: Db) -> dict:
        recs = db.scalars(select(Recording)).all()
        active = [r for r in recs if r.deleted_at is None]
        return {
            "all": len(active),
            "unfiled": sum(1 for r in active if r.folder_id is None),
            "trash": len(recs) - len(active),
        }

    @app.post("/api/folders", response_model=FolderOut, status_code=201)
    def create_folder(body: FolderIn, db: Db) -> FolderOut:
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "Name darf nicht leer sein")
        folder = Folder(name=name, sort=len(db.scalars(select(Folder)).all()))
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return folder_out(db, folder)

    @app.patch("/api/folders/{folder_id}", response_model=FolderOut)
    def rename_folder(folder_id: str, body: FolderIn, db: Db) -> FolderOut:
        folder = db.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(404, "Ordner nicht gefunden")
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "Name darf nicht leer sein")
        folder.name = name
        db.commit()
        return folder_out(db, folder)

    @app.delete("/api/folders/{folder_id}", status_code=204)
    def delete_folder(folder_id: str, db: Db) -> None:
        # Aufnahmen bleiben erhalten und landen in "Nicht zugeordnet".
        folder = db.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(404, "Ordner nicht gefunden")
        for rec in folder.recordings:
            rec.folder_id = None
        db.delete(folder)
        db.commit()

    # ----- Transkription -----

    def transcript_out(rec: Recording) -> TranscriptOut:
        talk: dict[str, int] = {}
        for seg in rec.segments:
            if seg.speaker_label:
                talk[seg.speaker_label] = talk.get(seg.speaker_label, 0) + (seg.end_ms - seg.start_ms)
        return TranscriptOut(
            recording_id=rec.id,
            language=rec.language,
            model=rec.transcript_model,
            transcribed_at=rec.transcribed_at,
            speakers=[
                SpeakerOut(label=s.label, name=s.name, idx=s.idx, talk_ms=talk.get(s.label, 0))
                for s in rec.speakers
            ],
            segments=[SegmentOut.model_validate(seg) for seg in rec.segments],
        )

    @app.post("/api/recordings/{rec_id}/transcribe")
    def transcribe(rec_id: str, body: TranscribeIn, db: Db) -> dict:
        rec = get_recording(db, rec_id)
        if rec.deleted_at is not None:
            raise HTTPException(409, "Aufnahme liegt im Papierkorb")
        if body.model and body.model not in WHISPER_MODELS:
            raise HTTPException(422, "Unbekanntes Modell")
        options = body.model_dump(exclude_none=True)
        return jobs.submit(rec.id, options)

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return jobs.active_jobs()

    @app.get("/api/recordings/{rec_id}/job")
    def last_job(rec_id: str, db: Db) -> dict | None:
        """Letzter Auftrag einer Aufnahme, z. B. um eine Fehlermeldung anzuzeigen."""
        job = db.scalars(select(Job).where(Job.recording_id == rec_id).order_by(Job.created_at.desc())).first()
        return job_dict(job) if job else None

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        result = jobs.cancel(job_id)
        if result is None:
            raise HTTPException(404, "Auftrag nicht gefunden")
        return result

    @app.get("/api/recordings/{rec_id}/transcript", response_model=TranscriptOut)
    def read_transcript(rec_id: str, db: Db) -> TranscriptOut:
        return transcript_out(get_recording(db, rec_id))

    @app.patch("/api/segments/{seg_id}", response_model=SegmentOut)
    def update_segment(seg_id: str, patch: SegmentPatch, db: Db) -> SegmentOut:
        seg = db.get(Segment, seg_id)
        if seg is None:
            raise HTTPException(404, "Abschnitt nicht gefunden")
        data = patch.model_dump(exclude_unset=True)
        if "text" in data:
            text = (data["text"] or "").strip()
            if not text:
                raise HTTPException(422, "Text darf nicht leer sein")
            seg.text, seg.edited = text, True
        if "speaker_label" in data:
            label = data["speaker_label"]
            if label:
                known = db.scalars(
                    select(RecordingSpeaker).where(
                        RecordingSpeaker.recording_id == seg.recording_id, RecordingSpeaker.label == label
                    )
                ).first()
                if known is None:
                    raise HTTPException(422, "Unbekannter Sprecher")
            seg.speaker_label = label
        db.commit()
        return SegmentOut.model_validate(seg)

    @app.patch("/api/recordings/{rec_id}/speakers/{label}", response_model=SpeakerOut)
    def rename_speaker(rec_id: str, label: str, patch: SpeakerPatch, db: Db) -> SpeakerOut:
        spk = db.scalars(
            select(RecordingSpeaker).where(RecordingSpeaker.recording_id == rec_id, RecordingSpeaker.label == label)
        ).first()
        if spk is None:
            raise HTTPException(404, "Sprecher nicht gefunden")
        spk.name = (patch.name or "").strip() or None
        db.commit()
        rec = get_recording(db, rec_id)
        return next(s for s in transcript_out(rec).speakers if s.label == label)

    def export_text(rec: Recording, fmt: str) -> str:
        if not rec.segments:
            raise HTTPException(409, "Noch kein Transkript vorhanden")
        names = {s.label: (s.name or s.label) for s in rec.speakers}
        if fmt == "srt":
            return to_srt(rec, names)
        if fmt == "txt":
            return to_txt(rec, names)
        raise HTTPException(422, "Format nicht unterstützt (txt oder srt)")

    @app.get("/api/recordings/{rec_id}/export")
    def export_download(rec_id: str, db: Db, format: str = "txt") -> PlainTextResponse:  # noqa: A002
        rec = get_recording(db, rec_id)
        text = export_text(rec, format)
        safe = "".join(c for c in rec.title if c.isalnum() or c in " -_").strip() or "transkript"
        return PlainTextResponse(
            text,
            headers={"Content-Disposition": f'attachment; filename="{safe}.{format}"'},
        )

    @app.post("/api/recordings/{rec_id}/export")
    def export_to_file(rec_id: str, body: ExportIn, db: Db) -> dict:
        # Den Pfad wählt der Nutzer im Speichern-Dialog der Desktop-App.
        rec = get_recording(db, rec_id)
        text = export_text(rec, body.format)
        target = Path(body.path).expanduser()
        if not target.is_absolute() or not target.parent.is_dir():
            raise HTTPException(422, "Ungültiger Speicherort")
        target.write_text(text, encoding="utf-8")
        return {"path": str(target)}

    # ----- Einstellungen & Modelle -----

    @app.get("/api/settings", response_model=SettingsModel)
    def read_settings() -> dict:
        return load_settings()

    @app.patch("/api/settings", response_model=SettingsModel)
    def update_settings(patch: SettingsPatch, db: Db) -> dict:
        data = patch.model_dump(exclude_none=True)
        if "whisper_model" in data and data["whisper_model"] not in WHISPER_MODELS:
            raise HTTPException(422, "Unbekanntes Modell")
        for key, value in data.items():
            row = db.get(Setting, key)
            if row is None:
                db.add(Setting(key=key, value=value))
            else:
                row.value = value
        db.commit()
        return load_settings()

    @app.get("/api/models")
    def list_models() -> dict:
        return {
            "whisper": [
                {"name": name, **meta, "downloaded": whisper_downloaded(models_dir, name)}
                for name, meta in WHISPER_MODELS.items()
            ],
            "diarization": {"downloaded": diarization_downloaded(models_dir), "size_mb": 33},
            "models_dir": str(models_dir),
        }

    # ----- Ereignisse -----

    @app.websocket("/ws")
    async def events(ws: WebSocket) -> None:
        token = ws.query_params.get("token", "")
        if not secrets.compare_digest(token, settings.token):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = hub.subscribe()
        try:
            await ws.send_json({"type": "hello", "jobs": jobs.active_jobs()})
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20)
                    await ws.send_json(event)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(q)

    return app
