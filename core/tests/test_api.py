import io
import struct
import wave
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from notizer_core.api import create_app
from notizer_core.config import Settings
from notizer_core.db import Recording, make_session_factory, utcnow

TOKEN = "test-token"
H = {"X-Notizer-Token": TOKEN}


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture()
def settings(tmp_path):
    return Settings(data_dir=tmp_path, token=TOKEN)


@pytest.fixture()
def client(settings):
    return TestClient(create_app(settings))


def upload(client, name="Teambesprechung_IT.wav", data=None, **form):
    files = [("files", (name, data if data is not None else wav_bytes(2.0), "audio/wav"))]
    return client.post("/api/recordings/import", files=files, data=form, headers=H)


def test_health_needs_no_token(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_token_required(client):
    assert client.get("/api/recordings").status_code == 401
    assert client.get("/api/recordings", headers={"X-Notizer-Token": "falsch"}).status_code == 401
    assert client.get("/api/recordings", headers=H).status_code == 200


def test_import_wav(client, settings):
    res = upload(client, last_modified=1759312920000)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["skipped"] == []
    rec = body["imported"][0]
    assert rec["title"] == "Teambesprechung IT"
    assert rec["format"] == "wav"
    assert rec["status"] == "nur_audio"
    assert rec["duration_s"] == pytest.approx(2.0, abs=0.01)
    assert rec["recorded_at"].startswith("2025-10-01")
    assert len(list((settings.data_dir / "audio").iterdir())) == 1

    listed = client.get("/api/recordings", headers=H).json()
    assert [r["id"] for r in listed] == [rec["id"]]

    audio = client.get(f"/api/recordings/{rec['id']}/audio?token={TOKEN}")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"


def test_import_rejects_other_formats_and_empty(client):
    body = upload(client, name="notiz.ogg", data=b"xyz").json()
    assert body["imported"] == []
    assert "nicht unterstützt" in body["skipped"][0]["reason"]
    body = upload(client, name="leer.mp3", data=b"").json()
    assert body["skipped"][0]["reason"] == "Datei ist leer"


def test_unreadable_audio_still_imports_without_duration(client):
    rec = upload(client, name="kaputt.mp3", data=b"keine echte mp3").json()["imported"][0]
    assert rec["duration_s"] is None
    assert rec["format"] == "mp3"


def test_folders_and_filters(client):
    folder = client.post("/api/folders", json={"name": "Teambesprechungen"}, headers=H).json()
    a = upload(client, name="a.wav", folder_id=folder["id"]).json()["imported"][0]
    b = upload(client, name="b.wav").json()["imported"][0]

    in_folder = client.get(f"/api/recordings?folder_id={folder['id']}", headers=H).json()
    assert [r["id"] for r in in_folder] == [a["id"]]
    unfiled = client.get("/api/recordings?unfiled=true", headers=H).json()
    assert [r["id"] for r in unfiled] == [b["id"]]
    assert client.get("/api/folders", headers=H).json()[0]["count"] == 1

    client.patch(f"/api/recordings/{b['id']}", json={"folder_id": folder["id"], "title": "Neu"}, headers=H)
    assert client.get("/api/folders", headers=H).json()[0]["count"] == 2
    assert client.get("/api/recordings?q=neu", headers=H).json()[0]["title"] == "Neu"

    assert client.delete(f"/api/folders/{folder['id']}", headers=H).status_code == 204
    assert len(client.get("/api/recordings?unfiled=true", headers=H).json()) == 2


def test_trash_restore_and_permanent_delete(client, settings):
    rec = upload(client).json()["imported"][0]
    rid = rec["id"]
    assert client.delete(f"/api/recordings/{rid}/permanent", headers=H).status_code == 409

    client.delete(f"/api/recordings/{rid}", headers=H)
    assert client.get("/api/recordings", headers=H).json() == []
    assert client.get("/api/recordings?trash=true", headers=H).json()[0]["id"] == rid
    assert client.get("/api/counts", headers=H).json() == {"all": 0, "unfiled": 0, "trash": 1}

    client.post(f"/api/recordings/{rid}/restore", headers=H)
    assert len(client.get("/api/recordings", headers=H).json()) == 1

    client.delete(f"/api/recordings/{rid}", headers=H)
    assert client.delete(f"/api/recordings/{rid}/permanent", headers=H).status_code == 204
    assert list((settings.data_dir / "audio").iterdir()) == []


def test_old_trash_is_purged_on_start(settings):
    client = TestClient(create_app(settings))
    rid = upload(client).json()["imported"][0]["id"]
    client.delete(f"/api/recordings/{rid}", headers=H)

    SessionLocal = make_session_factory(settings.db_path)
    with SessionLocal() as db:
        db.get(Recording, rid).deleted_at = utcnow() - timedelta(days=31)
        db.commit()

    client = TestClient(create_app(settings))  # Neustart
    assert client.get("/api/recordings?trash=true", headers=H).json() == []
    assert list((settings.data_dir / "audio").iterdir()) == []
