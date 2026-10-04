"""Transkript als Text (.txt) oder Untertitel (.srt) ausgeben."""

from __future__ import annotations

from .db import Recording


def _clock(ms: int, *, srt: bool = False) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, msec = divmod(rest, 1000)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def to_txt(rec: Recording, names: dict[str, str]) -> str:
    date = rec.recorded_at.astimezone().strftime("%d.%m.%Y %H:%M")
    lines = [rec.title, f"Aufgenommen: {date}"]
    previous = object()
    for seg in rec.segments:
        speaker = names.get(seg.speaker_label, seg.speaker_label) if seg.speaker_label else None
        if speaker != previous:
            head = f"[{_clock(seg.start_ms)}]" + (f" {speaker}:" if speaker else "")
            lines += ["", head]
            previous = speaker
        lines.append(seg.text)
    return "\n".join(lines).strip() + "\n"


def to_srt(rec: Recording, names: dict[str, str]) -> str:
    blocks = []
    for i, seg in enumerate(rec.segments, start=1):
        speaker = names.get(seg.speaker_label, seg.speaker_label) if seg.speaker_label else None
        text = f"{speaker}: {seg.text}" if speaker else seg.text
        blocks.append(f"{i}\n{_clock(seg.start_ms, srt=True)} --> {_clock(seg.end_ms, srt=True)}\n{text}\n")
    return "\n".join(blocks)
