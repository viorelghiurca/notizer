"""Tests für M1: Zusammenführen, Aufträge, Transkript-API, Export, WebSocket.

Die echten Modelle werden hier durch Ersatz-Engines ersetzt, damit die Tests
ohne Download und in Sekunden laufen. ``test_real_diarization`` nutzt die echten
Modelle, falls sie bereits im Ordner liegen (Umgebungsvariable NOTIZER_MODELS).
"""

import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notizer_core.api import create_app
from notizer_core.config import Settings
from notizer_core.engines import AsrResult, AsrSegment, Cancelled, EngineError, Turn, Word, merge

from .test_api import TOKEN, H, upload

LINES = [
    (0.0, 5.0, "Guten Morgen zusammen. Erster Punkt ist das Citrix Update."),
    (5.7, 10.0, "Das kann ich übernehmen. Ich prüfe die Anmeldungen am Montag."),
    (10.9, 14.5, "Sehr gut. Bitte auch die Drucker testen."),
    (15.4, 19.0, "Mache ich. Die Tickets sind noch offen."),
]
TRUTH = [Turn(0.0, 5.1, 0), Turn(5.7, 10.2, 1), Turn(10.9, 14.8, 0), Turn(15.4, 19.1, 1)]


def asr_from_lines(lines=LINES) -> AsrResult:
    segs = []
    for start, end, text in lines:
        tokens = text.split()
        step = (end - start) / len(tokens)
        words = [Word(start + i * step, start + (i + 1) * step, " " + t) for i, t in enumerate(tokens)]
        segs.append(AsrSegment(start, end, " " + text, words))
    return AsrResult(language="de", duration=lines[-1][1], segments=segs)


class FakeTranscriber:
    def __init__(self, result=None, error=None, slow=False):
        self.result, self.error, self.slow = result or asr_from_lines(), error, slow
        self.calls = []

    def transcribe(self, audio_path, *, model, language, vocabulary, on_progress, is_cancelled):
        self.calls.append({"model": model, "language": language, "vocabulary": vocabulary})
        assert Path(audio_path).exists()
        if self.error:
            raise self.error
        if self.slow:
            for _ in range(200):
                if is_cancelled():
                    raise Cancelled
                time.sleep(0.02)
        for seg in self.result.segments:
            on_progress(seg.end / self.result.duration, "Transkribiere")
        return self.result


class FakeDiarizer:
    def __init__(self, turns=TRUTH):
        self.turns = turns
        self.calls = []

    def diarize(self, audio_path, *, num_speakers, on_progress, is_cancelled):
        self.calls.append({"num_speakers": num_speakers})
        on_progress(1.0, "Erkenne Sprecher")
        return self.turns


def make_client(tmp_path, transcriber=None, diarizer=None):
    settings = Settings(data_dir=tmp_path, token=TOKEN)
    app = create_app(settings, transcriber or FakeTranscriber(), diarizer or FakeDiarizer())
    return TestClient(app), app


def run_job(client, app, rec_id, **body):
    job = client.post(f"/api/recordings/{rec_id}/transcribe", json=body, headers=H).json()
    assert app.state.jobs.wait_idle(10)
    return job


# ---------- Zusammenführen ----------


def test_merge_assigns_speakers_and_splits_on_change():
    merged = merge(asr_from_lines(), TRUTH)
    assert [m.speaker for m in merged] == ["Sprecher 1", "Sprecher 2", "Sprecher 1", "Sprecher 2"]
    assert merged[0].text.startswith("Guten Morgen")
    assert merged[1].start == pytest.approx(5.7)


def test_merge_numbers_speakers_by_first_appearance():
    turns = [Turn(t.start, t.end, 7 if t.speaker == 0 else 3) for t in TRUTH]
    assert merge(asr_from_lines(), turns)[0].speaker == "Sprecher 1"


def test_merge_without_diarization_splits_on_pauses():
    merged = merge(asr_from_lines(), None)
    assert all(m.speaker is None for m in merged)
    assert len(merged) == 1  # kurze Pausen, unter 40 s: ein Absatz
    merged2 = merge(asr_from_lines([(0, 2, "Eins zwei."), (2.5, 4, "Drei vier."), (7, 9, "Fünf sechs.")]), None)
    assert [m.text for m in merged2] == ["Eins zwei. Drei vier.", "Fünf sechs."]


def test_merge_word_in_gap_takes_nearest_speaker():
    asr = asr_from_lines([(0, 2, "Hallo du."), (2.05, 2.3, "Ja."), (2.4, 4, "Wie geht es?")])
    merged = merge(asr, [Turn(0, 2.0, 0), Turn(2.4, 4, 1)])
    assert [m.speaker for m in merged] == ["Sprecher 1", "Sprecher 2"]


def test_merge_empty():
    assert merge(AsrResult("de", 0, []), None) == []


# ---------- Aufträge & API ----------


def test_transcribe_flow(tmp_path):
    fake_t, fake_d = FakeTranscriber(), FakeDiarizer()
    client, app = make_client(tmp_path, fake_t, fake_d)
    rec = upload(client).json()["imported"][0]

    job = run_job(client, app, rec["id"], language="de", num_speakers=2)
    assert job["status"] == "wartet"
    assert fake_t.calls[0]["model"] == "large-v3-turbo"
    assert fake_t.calls[0]["language"] == "de"
    assert fake_d.calls[0]["num_speakers"] == 2

    rec2 = client.get(f"/api/recordings/{rec['id']}", headers=H).json()
    assert rec2["status"] == "transkribiert"
    assert rec2["language"] == "de"
    assert rec2["transcript_model"] == "large-v3-turbo"

    tr = client.get(f"/api/recordings/{rec['id']}/transcript", headers=H).json()
    assert [s["speaker_label"] for s in tr["segments"]] == ["Sprecher 1", "Sprecher 2"] * 2
    assert [s["label"] for s in tr["speakers"]] == ["Sprecher 1", "Sprecher 2"]
    assert tr["speakers"][0]["talk_ms"] > 0
    assert client.get("/api/jobs", headers=H).json() == []


def test_auto_language_and_no_diarization(tmp_path):
    fake_t, fake_d = FakeTranscriber(), FakeDiarizer()
    client, app = make_client(tmp_path, fake_t, fake_d)
    rec = upload(client).json()["imported"][0]
    run_job(client, app, rec["id"], language="auto", diarize=False)
    assert fake_t.calls[0]["language"] is None
    assert fake_d.calls == []
    tr = client.get(f"/api/recordings/{rec['id']}/transcript", headers=H).json()
    assert tr["speakers"] == [] and all(s["speaker_label"] is None for s in tr["segments"])


def test_edit_rename_export_search(tmp_path):
    client, app = make_client(tmp_path)
    rec = upload(client).json()["imported"][0]
    rid = rec["id"]
    run_job(client, app, rid)
    tr = client.get(f"/api/recordings/{rid}/transcript", headers=H).json()
    seg = tr["segments"][0]

    res = client.patch(f"/api/segments/{seg['id']}", json={"text": "Guten Morgen, Team."}, headers=H)
    assert res.json()["edited"] is True
    assert client.patch(f"/api/segments/{seg['id']}", json={"text": "  "}, headers=H).status_code == 422
    assert client.patch(f"/api/segments/{seg['id']}", json={"speaker_label": "Sprecher 9"}, headers=H).status_code == 422
    client.patch(f"/api/segments/{seg['id']}", json={"speaker_label": "Sprecher 2"}, headers=H)

    spk = client.patch(f"/api/recordings/{rid}/speakers/Sprecher 1", json={"name": "Viorel"}, headers=H).json()
    assert spk["name"] == "Viorel"

    txt = client.get(f"/api/recordings/{rid}/export?format=txt", headers=H)
    assert "attachment" in txt.headers["content-disposition"]
    body = txt.text
    assert "Guten Morgen, Team." in body and "[00:00:10] Viorel:" in body
    assert body.startswith("Teambesprechung IT\nAufgenommen: ") and "\n\n\n" not in body
    srt = client.get(f"/api/recordings/{rid}/export?format=srt", headers=H).text
    assert srt.startswith("1\n00:00:00,000 --> 00:00:05,000\nSprecher 2: Guten Morgen, Team.")
    assert client.get(f"/api/recordings/{rid}/export?format=pdf", headers=H).status_code == 422

    out = tmp_path / "export.txt"
    assert client.post(f"/api/recordings/{rid}/export", json={"format": "txt", "path": str(out)}, headers=H).status_code == 200
    assert out.read_text(encoding="utf-8") == body
    assert client.post(f"/api/recordings/{rid}/export", json={"path": "relativ.txt"}, headers=H).status_code == 422

    # Suche findet Wörter aus dem Transkript
    assert [r["id"] for r in client.get("/api/recordings?q=drucker", headers=H).json()] == [rid]
    assert client.get("/api/recordings?q=zebra", headers=H).json() == []


def test_retranscribe_keeps_speaker_names(tmp_path):
    client, app = make_client(tmp_path)
    rid = upload(client).json()["imported"][0]["id"]
    run_job(client, app, rid)
    client.patch(f"/api/recordings/{rid}/speakers/Sprecher 2", json={"name": "M. Keller"}, headers=H)
    run_job(client, app, rid)
    tr = client.get(f"/api/recordings/{rid}/transcript", headers=H).json()
    assert tr["speakers"][1]["name"] == "M. Keller"
    assert len(tr["segments"]) == 4


def test_export_without_transcript(tmp_path):
    client, _ = make_client(tmp_path)
    rid = upload(client).json()["imported"][0]["id"]
    assert client.get(f"/api/recordings/{rid}/export", headers=H).status_code == 409


def test_error_marks_recording(tmp_path):
    client, app = make_client(tmp_path, FakeTranscriber(error=EngineError("Kein Internet")))
    rid = upload(client).json()["imported"][0]["id"]
    assert client.get(f"/api/recordings/{rid}/job", headers=H).json() is None
    run_job(client, app, rid)
    assert client.get(f"/api/recordings/{rid}", headers=H).json()["status"] == "fehler"
    last = client.get(f"/api/recordings/{rid}/job", headers=H).json()
    assert last["status"] == "fehler" and last["error"] == "Kein Internet"


def test_cancel_running_job(tmp_path):
    client, app = make_client(tmp_path, FakeTranscriber(slow=True))
    rid = upload(client).json()["imported"][0]["id"]
    job = client.post(f"/api/recordings/{rid}/transcribe", json={}, headers=H).json()
    # doppelter Start liefert denselben Auftrag
    assert client.post(f"/api/recordings/{rid}/transcribe", json={}, headers=H).json()["id"] == job["id"]
    for _ in range(100):
        if client.get("/api/jobs", headers=H).json()[0]["status"] == "laeuft":
            break
        time.sleep(0.02)
    client.post(f"/api/jobs/{job['id']}/cancel", headers=H)
    assert app.state.jobs.wait_idle(10)
    assert client.get(f"/api/recordings/{rid}", headers=H).json()["status"] == "nur_audio"


def test_recover_after_restart(tmp_path):
    client, app = make_client(tmp_path, FakeTranscriber(slow=True))
    rid = upload(client).json()["imported"][0]["id"]
    client.post(f"/api/recordings/{rid}/transcribe", json={}, headers=H)
    client2, _ = make_client(tmp_path)  # Neustart, alter Worker läuft noch im Hintergrund
    assert client2.get(f"/api/recordings/{rid}", headers=H).json()["status"] == "nur_audio"
    assert client2.get("/api/jobs", headers=H).json() == []
    app.state.jobs._cancel.update(j["id"] for j in app.state.jobs.active_jobs())


def test_trashed_recording_cannot_be_transcribed(tmp_path):
    client, _ = make_client(tmp_path)
    rid = upload(client).json()["imported"][0]["id"]
    client.delete(f"/api/recordings/{rid}", headers=H)
    assert client.post(f"/api/recordings/{rid}/transcribe", json={}, headers=H).status_code == 409


def test_settings_and_models(tmp_path):
    fake_t = FakeTranscriber()
    client, app = make_client(tmp_path, fake_t)
    assert client.get("/api/settings", headers=H).json() == {
        "whisper_model": "large-v3-turbo", "language": "de", "diarize": True, "vocabulary": ""
    }
    s = client.patch("/api/settings", json={"whisper_model": "small", "vocabulary": "Citrix, OSPlus"}, headers=H).json()
    assert s["whisper_model"] == "small"
    assert client.patch("/api/settings", json={"whisper_model": "riesig"}, headers=H).status_code == 422
    models = client.get("/api/models", headers=H).json()
    assert [m["name"] for m in models["whisper"]][0] == "large-v3-turbo"
    assert models["whisper"][0]["downloaded"] is False

    rid = upload(client).json()["imported"][0]["id"]
    run_job(client, app, rid)
    assert fake_t.calls[0]["model"] == "small"
    assert fake_t.calls[0]["vocabulary"] == "Citrix, OSPlus"


def test_websocket_events(tmp_path):
    client, app = make_client(tmp_path)
    rid = upload(client).json()["imported"][0]["id"]
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=falsch") as ws:
            ws.receive_json()
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "hello"
        threading.Thread(target=lambda: client.post(f"/api/recordings/{rid}/transcribe", json={}, headers=H)).start()
        statuses = []
        for _ in range(50):
            ev = ws.receive_json()
            if ev["type"] == "job":
                statuses.append(ev["job"]["status"])
                if ev["job"]["status"] == "fertig":
                    break
        assert statuses[0] == "wartet" and statuses[-1] == "fertig" and "laeuft" in statuses


def test_migration_from_m0_database(tmp_path):
    db = sqlite3.connect(tmp_path / "notizer.db")
    db.executescript(
        """
        CREATE TABLE recordings (id VARCHAR(32) PRIMARY KEY, title VARCHAR(300), folder_id VARCHAR(32),
          recorded_at DATETIME, created_at DATETIME, duration_s FLOAT, source VARCHAR(20), status VARCHAR(30),
          favorite BOOLEAN, deleted_at DATETIME);
        INSERT INTO recordings VALUES ('abc', 'Alt', NULL, '2026-10-01 10:00:00', '2026-10-01 10:00:00', 5.0,
          'import', 'nur_audio', 0, NULL);
        """
    )
    db.close()
    client, _ = make_client(tmp_path)
    recs = client.get("/api/recordings", headers=H).json()
    assert recs[0]["title"] == "Alt" and recs[0]["language"] is None


@pytest.mark.skipif(not os.environ.get("NOTIZER_MODELS"), reason="echte Modelle nicht vorhanden")
def test_real_diarization():
    from notizer_core.engines import SherpaDiarizer

    audio = Path(os.environ["NOTIZER_TEST_AUDIO"])
    turns = SherpaDiarizer(Path(os.environ["NOTIZER_MODELS"])).diarize(
        audio, num_speakers=None, on_progress=lambda *_: None, is_cancelled=lambda: False
    )
    assert [t.speaker for t in turns] == [0, 1, 0, 1, 0, 1]
