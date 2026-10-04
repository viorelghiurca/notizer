"""Startet den Core mit einer Ersatz-Transkription (für Oberflächentests ohne Whisper-Modell).

    python -m tests.demo_server --port 8765 --token dev --data-dir /tmp/notizer-demo

Die Sprechertrennung ist echt (sherpa-onnx), die Transkription liefert einen
festen Beispieltext, verteilt über die Länge der Aufnahme.
"""

import argparse
import time
from pathlib import Path

import uvicorn

from notizer_core.api import create_app
from notizer_core.audio import probe_duration
from notizer_core.config import Settings
from notizer_core.engines import AsrResult, AsrSegment, Cancelled, SherpaDiarizer, Word

TEXT = [
    "Guten Morgen zusammen. Erster Punkt ist das Citrix Update am Wochenende.",
    "Das kann ich übernehmen. Ich prüfe die Anmeldungen am Montag ab sieben Uhr.",
    "Sehr gut. Bitte auch die Drucker im zweiten Stock testen.",
    "Mache ich. Die Tickets beim Dienstleister sind leider noch offen.",
    "Dann treffen wir uns am Donnerstag um zehn Uhr zur Abstimmung.",
    "Einverstanden. Ich schicke danach eine kurze Zusammenfassung an alle.",
]
TIMES = [(0.0, 5.15), (5.75, 10.31), (10.91, 14.88), (15.48, 19.16), (19.76, 23.95), (24.55, 28.63)]


class DemoTranscriber:
    def transcribe(self, audio_path, *, model, language, vocabulary, on_progress, is_cancelled):
        duration = probe_duration(Path(audio_path)) or 29.2
        scale = duration / 29.2
        segs = []
        for (start, end), text in zip(TIMES, TEXT):
            start, end = start * scale, end * scale
            tokens = text.split()
            step = (end - start) / len(tokens)
            words = [Word(start + i * step, start + (i + 1) * step, " " + t) for i, t in enumerate(tokens)]
            segs.append(AsrSegment(start, end, " " + text, words))
        for i, seg in enumerate(segs):
            for _ in range(5):
                if is_cancelled():
                    raise Cancelled
                time.sleep(0.1)
            on_progress((i + 1) / len(segs), "Transkribiere")
        return AsrResult(language=language or "de", duration=duration, segments=segs)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", default="dev")
    p.add_argument("--data-dir", type=Path, required=True)
    a = p.parse_args()
    s = Settings(data_dir=a.data_dir, token=a.token, port=a.port)
    app = create_app(s, DemoTranscriber(), SherpaDiarizer(s.data_dir / "models"))
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
