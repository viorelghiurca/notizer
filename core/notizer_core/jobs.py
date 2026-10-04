"""Hintergrundaufträge (Transkription) mit Fortschritt.

Ein einzelner Worker-Thread arbeitet die Warteschlange der Reihe nach ab, damit
nie zwei große Modelle gleichzeitig Speicher belegen. Jede Änderung an einem
Auftrag geht als Ereignis an alle verbundenen WebSocket-Clients.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from .db import AudioFile, Job, Recording, RecordingSpeaker, Segment, utcnow
from .engines import Cancelled, Diarizer, EngineError, Transcriber, merge

log = logging.getLogger("notizer.jobs")

ACTIVE = ("wartet", "laeuft")


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "recording_id": job.recording_id,
        "kind": job.kind,
        "status": job.status,
        "progress": round(job.progress, 4),
        "stage": job.stage,
        "error": job.error,
        "options": job.options,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


class EventHub:
    """Verteilt Ereignisse aus dem Worker-Thread an WebSocket-Clients."""

    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subs.add((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {s for s in self._subs if s[1] is not q}

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(self._put, q, event)
            except RuntimeError:  # Loop bereits geschlossen
                self.unsubscribe(q)

    @staticmethod
    def _put(q: asyncio.Queue, event: dict) -> None:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)


class JobManager:
    def __init__(
        self,
        session_factory: sessionmaker,
        data_dir: Path,
        transcriber: Transcriber,
        diarizer: Diarizer,
        settings_getter: Callable[[], dict],
        hub: EventHub,
    ) -> None:
        self.SessionLocal = session_factory
        self.data_dir = data_dir
        self.transcriber = transcriber
        self.diarizer = diarizer
        self.get_settings = settings_getter
        self.hub = hub
        self._queue: queue.Queue[str] = queue.Queue()
        self._cancel: set[str] = set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ----- Lebenszyklus -----

    def recover(self) -> None:
        """Nach einem Neustart: unterbrochene Aufträge als abgebrochen markieren."""
        with self.SessionLocal() as db:
            for job in db.scalars(select(Job).where(Job.status.in_(ACTIVE))).all():
                job.status = "abgebrochen"
                job.stage = "Durch Neustart unterbrochen"
                job.finished_at = utcnow()
                rec = db.get(Recording, job.recording_id)
                if rec and rec.status == "wird_transkribiert":
                    rec.status = "transkribiert" if rec.segments else "nur_audio"
            db.commit()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="notizer-worker", daemon=True)
                self._thread.start()

    # ----- Öffentliche Methoden -----

    def submit(self, recording_id: str, options: dict) -> dict:
        with self.SessionLocal() as db:
            running = db.scalars(
                select(Job).where(Job.recording_id == recording_id, Job.status.in_(ACTIVE))
            ).first()
            if running:
                return job_dict(running)
            job = Job(recording_id=recording_id, kind="transcribe", options=options)
            db.add(job)
            rec = db.get(Recording, recording_id)
            rec.status = "wird_transkribiert"
            db.commit()
            data = job_dict(job)
        self.hub.publish({"type": "job", "job": data})
        self.hub.publish({"type": "recording", "id": recording_id, "status": "wird_transkribiert"})
        self._ensure_worker()
        self._queue.put(data["id"])
        return data

    def cancel(self, job_id: str) -> dict | None:
        with self.SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return None
            if job.status == "wartet":
                job.status = "abgebrochen"
                job.stage = "Abgebrochen"
                job.finished_at = utcnow()
                self._reset_recording(db, job.recording_id)
                db.commit()
                data = job_dict(job)
                self.hub.publish({"type": "job", "job": data})
                return data
            if job.status == "laeuft":
                self._cancel.add(job_id)
            return job_dict(job)

    def active_jobs(self) -> list[dict]:
        with self.SessionLocal() as db:
            jobs = db.scalars(select(Job).where(Job.status.in_(ACTIVE)).order_by(Job.created_at)).all()
            return [job_dict(j) for j in jobs]

    def wait_idle(self, timeout: float = 30) -> bool:
        """Für Tests: warten, bis keine Aufträge mehr laufen."""
        end = time.time() + timeout
        while time.time() < end:
            if self._queue.empty() and not self.active_jobs():
                return True
            time.sleep(0.05)
        return False

    # ----- Worker -----

    def _reset_recording(self, db, recording_id: str) -> None:  # noqa: ANN001
        rec = db.get(Recording, recording_id)
        if rec:
            rec.status = "transkribiert" if rec.segments else "nur_audio"
            self.hub.publish({"type": "recording", "id": rec.id, "status": rec.status})

    def _update(self, job_id: str, **fields) -> None:  # noqa: ANN003
        with self.SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            db.commit()
            self.hub.publish({"type": "job", "job": job_dict(job)})

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._process(job_id)
            except Exception:  # noqa: BLE001 – Worker darf nie sterben
                log.exception("Auftrag %s fehlgeschlagen", job_id)

    def _process(self, job_id: str) -> None:
        with self.SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "wartet":
                return
            rec = db.get(Recording, job.recording_id)
            audio = db.scalars(
                select(AudioFile).where(AudioFile.recording_id == job.recording_id, AudioFile.kind == "original")
            ).first()
            if rec is None or audio is None:
                job.status, job.error, job.finished_at = "fehler", "Audiodatei fehlt", utcnow()
                db.commit()
                return
            options = dict(job.options or {})
            audio_path = self.data_dir / audio.path
            job.status, job.started_at, job.stage = "laeuft", utcnow(), "Startet"
            db.commit()
            self.hub.publish({"type": "job", "job": job_dict(job)})

        settings = self.get_settings()
        model = options.get("model") or settings["whisper_model"]
        language = options.get("language", settings["language"])
        language = None if language in (None, "", "auto") else language
        diarize = options.get("diarize", settings["diarize"])
        num_speakers = options.get("num_speakers") or None

        is_cancelled = lambda: job_id in self._cancel  # noqa: E731
        last = {"t": 0.0, "p": -1.0, "s": ""}

        def progress(lo: float, hi: float) -> Callable[[float, str], None]:
            def report(frac: float, stage: str) -> None:
                p = lo + (hi - lo) * max(0.0, min(1.0, frac))
                now = time.monotonic()
                # höchstens ~4 Updates pro Sekunde, außer die Stufe wechselt
                if stage != last["s"] or now - last["t"] > 0.25:
                    last.update(t=now, p=p, s=stage)
                    self._update(job_id, progress=p, stage=stage)

            return report

        try:
            asr_hi = 0.8 if diarize else 0.98
            asr = self.transcriber.transcribe(
                audio_path,
                model=model,
                language=language,
                vocabulary=settings.get("vocabulary", ""),
                on_progress=progress(0.0, asr_hi),
                is_cancelled=is_cancelled,
            )
            turns = None
            if diarize and asr.segments:
                turns = self.diarizer.diarize(
                    audio_path,
                    num_speakers=num_speakers,
                    on_progress=progress(asr_hi, 0.98),
                    is_cancelled=is_cancelled,
                )
            merged = merge(asr, turns)
            self._save(job_id, model, asr.language, merged)
        except Cancelled:
            self._finish(job_id, "abgebrochen", "Abgebrochen")
        except EngineError as exc:
            self._finish(job_id, "fehler", "Fehler", str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Transkription fehlgeschlagen")
            self._finish(job_id, "fehler", "Fehler", f"Unerwarteter Fehler: {exc}")
        finally:
            self._cancel.discard(job_id)

    def _finish(self, job_id: str, status: str, stage: str, error: str | None = None) -> None:
        with self.SessionLocal() as db:
            job = db.get(Job, job_id)
            job.status, job.stage, job.error, job.finished_at = status, stage, error, utcnow()
            rec = db.get(Recording, job.recording_id)
            if rec:
                if status == "fehler" and not rec.segments:
                    rec.status = "fehler"
                else:
                    rec.status = "transkribiert" if rec.segments else "nur_audio"
            db.commit()
            self.hub.publish({"type": "job", "job": job_dict(job)})
            if rec:
                self.hub.publish({"type": "recording", "id": rec.id, "status": rec.status})

    def _save(self, job_id: str, model: str, language: str, merged) -> None:  # noqa: ANN001
        with self.SessionLocal() as db:
            job = db.get(Job, job_id)
            rec = db.get(Recording, job.recording_id)
            old_names = {s.label: s.name for s in rec.speakers if s.name}
            db.execute(delete(Segment).where(Segment.recording_id == rec.id))
            db.execute(delete(RecordingSpeaker).where(RecordingSpeaker.recording_id == rec.id))
            labels: list[str] = []
            for i, m in enumerate(merged):
                if m.speaker and m.speaker not in labels:
                    labels.append(m.speaker)
                db.add(
                    Segment(
                        recording_id=rec.id,
                        idx=i,
                        start_ms=int(m.start * 1000),
                        end_ms=int(m.end * 1000),
                        text=m.text,
                        speaker_label=m.speaker,
                        words=[[round(w.start, 2), round(w.end, 2), w.text] for w in m.words],
                    )
                )
            for i, label in enumerate(labels):
                db.add(RecordingSpeaker(recording_id=rec.id, idx=i, label=label, name=old_names.get(label)))
            rec.status = "transkribiert"
            rec.language = language
            rec.transcript_model = model
            rec.transcribed_at = utcnow()
            job.status, job.progress, job.stage, job.finished_at = "fertig", 1.0, "Fertig", utcnow()
            db.commit()
            self.hub.publish({"type": "job", "job": job_dict(job)})
            self.hub.publish({"type": "recording", "id": rec.id, "status": "transkribiert"})
