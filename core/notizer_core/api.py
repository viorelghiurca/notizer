"""REST-API des Cores (M0: Aufnahmen importieren, Ordner, Papierkorb)."""


import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .audio import probe_duration
from .config import Settings
from .db import AudioFile, Folder, Recording, make_session_factory, new_id, utcnow

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


# ---------- App ----------


def create_app(settings: Settings) -> FastAPI:
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
            stmt = stmt.where(Recording.title.icontains(q))
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

    return app

