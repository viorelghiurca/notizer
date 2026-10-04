"""Startpunkt des Cores.

Die Desktop-App startet diese Datei (bzw. die daraus gebaute ``notizer-core``-
Binärdatei) als Hintergrundprozess. Der Core sucht sich einen freien Port und
meldet Port und Zugriffstoken in der ersten Ausgabezeile:

    NOTIZER_READY {"port": 51234, "token": "..."}

Die App liest diese Zeile und spricht danach nur noch mit diesem Port.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from .api import create_app
from .config import Settings


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _watch_parent() -> None:
    # Die Desktop-App hält die Standardeingabe offen. Endet oder stürzt die App
    # ab, kommt hier EOF an und der Core beendet sich mit.
    try:
        while sys.stdin.read(1024):
            pass
    finally:
        os._exit(0)


def _selftest(audio: Path, data_dir: Path | None) -> None:
    """Prüft, ob die eingebauten Audio- und KI-Bibliotheken laufen (Fehlersuche)."""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    from .engines import SherpaDiarizer

    samples = decode_audio(str(audio), sampling_rate=16000)
    speech = get_speech_timestamps(samples, VadOptions())
    print(json.dumps({"seconds": round(len(samples) / 16000, 2), "speech_chunks": len(speech)}), flush=True)
    models = (data_dir or Settings().data_dir) / "models"
    turns = SherpaDiarizer(models).diarize(
        audio, num_speakers=None, on_progress=lambda *_: None, is_cancelled=lambda: False
    )
    print(json.dumps({"speakers": sorted({t.speaker for t in turns}), "turns": len(turns)}), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="notizer-core")
    parser.add_argument("--port", type=int, help="fester Port (Standard: frei wählen)")
    parser.add_argument("--data-dir", type=Path, help="Datenordner")
    parser.add_argument("--token", help="Zugriffstoken (Standard: zufällig)")
    parser.add_argument(
        "--exit-on-stdin-close",
        action="store_true",
        help="beenden, sobald die Standardeingabe schließt (die App ist beendet)",
    )
    parser.add_argument(
        "--selftest",
        type=Path,
        metavar="AUDIO",
        help="Audio dekodieren, Sprachpausen und Sprecher erkennen, Ergebnis ausgeben, beenden",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        _selftest(args.selftest, args.data_dir)
        return

    settings = Settings()
    if args.data_dir:
        settings.data_dir = args.data_dir
    if args.token:
        settings.token = args.token
    if args.port is not None:
        settings.port = args.port
    if settings.port == 0:
        settings.port = free_port(settings.host)

    if args.exit_on_stdin_close:
        threading.Thread(target=_watch_parent, daemon=True).start()

    app = create_app(settings)  # erzeugt das Token, falls leer
    print(
        "NOTIZER_READY " + json.dumps({"port": settings.port, "token": settings.token}),
        flush=True,
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
