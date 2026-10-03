"""Hilfsfunktionen rund um Audiodateien."""

from __future__ import annotations

from pathlib import Path

import mutagen


def probe_duration(path: Path) -> float | None:
    """Dauer in Sekunden, ohne ffmpeg. ``None``, wenn die Datei nicht lesbar ist."""
    try:
        info = mutagen.File(path)
    except Exception:  # noqa: BLE001 – kaputte Dateien sollen den Import nicht abbrechen
        return None
    if info is None or info.info is None:
        return None
    length = getattr(info.info, "length", None)
    return float(length) if length else None
