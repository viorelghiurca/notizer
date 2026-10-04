"""Spracherkennung und Sprechertrennung.

- Transkription: faster-whisper (CTranslate2). Das Modell lädt beim ersten
  Gebrauch einmalig aus dem Internet (Hugging Face) in ``<daten>/models/whisper``.
- Sprechertrennung: sherpa-onnx mit dem pyannote-Segmentierungsmodell und einem
  Stimm-Embedding-Modell. Beide laden beim ersten Gebrauch von GitHub in
  ``<daten>/models/diarization``. Kein PyTorch, kein Hugging-Face-Konto nötig.

Beide Engines stehen hinter kleinen Schnittstellen (``Transcriber``,
``Diarizer``), damit Tests sie ersetzen und später andere Modelle (oder
Cloud-Dienste) eingebaut werden können.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

ProgressFn = Callable[[float, str], None]  # (0..1 innerhalb der Stufe, Text)
CancelFn = Callable[[], bool]


class Cancelled(Exception):
    """Der Auftrag wurde vom Nutzer abgebrochen."""


class EngineError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


# ---------- Datenformen ----------


@dataclass
class Word:
    start: float
    end: float
    text: str  # inkl. führendem Leerzeichen, wie von Whisper geliefert


@dataclass
class AsrSegment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class AsrResult:
    language: str
    duration: float
    segments: list[AsrSegment]


@dataclass
class Turn:
    start: float
    end: float
    speaker: int


@dataclass
class MergedSegment:
    start: float
    end: float
    text: str
    speaker: str | None
    words: list[Word]


# ---------- Schnittstellen ----------


class Transcriber(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        model: str,
        language: str | None,
        vocabulary: str,
        on_progress: ProgressFn,
        is_cancelled: CancelFn,
    ) -> AsrResult: ...


class Diarizer(Protocol):
    def diarize(
        self,
        audio_path: Path,
        *,
        num_speakers: int | None,
        on_progress: ProgressFn,
        is_cancelled: CancelFn,
    ) -> list[Turn]: ...


# ---------- Modelle ----------

# Ungefähre Downloadgröße, nur für die Anzeige in der Oberfläche.
WHISPER_MODELS: dict[str, dict] = {
    "large-v3-turbo": {"label": "Turbo (empfohlen)", "size_mb": 1600, "hint": "Fast so gut wie large-v3, deutlich schneller"},
    "large-v3": {"label": "Large v3", "size_mb": 3100, "hint": "Beste Qualität, langsam ohne Grafikkarte"},
    "medium": {"label": "Medium", "size_mb": 1500, "hint": "Gute Qualität, mittleres Tempo"},
    "small": {"label": "Small", "size_mb": 480, "hint": "Schnell, für klare Aufnahmen"},
}

GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{GH}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = f"{GH}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx"


def whisper_repo(model: str) -> str:
    from faster_whisper.utils import _MODELS  # noqa: PLC0415 – Import erst bei Bedarf

    return _MODELS.get(model, model)


def whisper_downloaded(models_dir: Path, model: str) -> bool:
    repo = whisper_repo(model)
    snap = models_dir / "whisper" / f"models--{repo.replace('/', '--')}" / "snapshots"
    return snap.is_dir() and any((p / "model.bin").exists() for p in snap.iterdir())


def diarization_paths(models_dir: Path) -> tuple[Path, Path]:
    base = models_dir / "diarization"
    return (
        base / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
        base / "wespeaker_en_voxceleb_resnet34_LM.onnx",
    )


def diarization_downloaded(models_dir: Path) -> bool:
    return all(p.exists() for p in diarization_paths(models_dir))


def _download(url: str, dest: Path, on_progress: ProgressFn, label: str, is_cancelled: CancelFn) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as res, tmp.open("wb") as out:  # noqa: S310 – feste https-URL
            total = int(res.headers.get("Content-Length") or 0)
            done = 0
            while chunk := res.read(1 << 20):
                if is_cancelled():
                    raise Cancelled
                out.write(chunk)
                done += len(chunk)
                if total:
                    on_progress(done / total, f"{label} ({done // 1_000_000} von {total // 1_000_000} MB)")
        tmp.replace(dest)
    except Cancelled:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise EngineError(
            f"{label} fehlgeschlagen. Beim ersten Mal braucht Notizer eine Internetverbindung. ({exc})"
        ) from exc


def ensure_diarization_models(models_dir: Path, on_progress: ProgressFn, is_cancelled: CancelFn) -> tuple[Path, Path]:
    seg, emb = diarization_paths(models_dir)
    if not seg.exists():
        archive = seg.parent.parent / "segmentation.tar.bz2"
        _download(SEGMENTATION_URL, archive, lambda f, t: on_progress(f * 0.3, t), "Lade Segmentierungsmodell", is_cancelled)
        with tarfile.open(archive) as tar:
            tar.extractall(seg.parent.parent, filter="data")
        archive.unlink(missing_ok=True)
    if not emb.exists():
        _download(EMBEDDING_URL, emb, lambda f, t: on_progress(0.3 + f * 0.7, t), "Lade Stimmmodell", is_cancelled)
    return seg, emb


# ---------- faster-whisper ----------


class FasterWhisperTranscriber:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._model = None
        self._model_name: str | None = None
        self._lock = threading.Lock()

    def _load(self, name: str, on_progress: ProgressFn):  # noqa: ANN202
        if self._model is not None and self._model_name == name:
            return self._model
        import ctranslate2  # noqa: PLC0415
        from faster_whisper import WhisperModel  # noqa: PLC0415

        size = WHISPER_MODELS.get(name, {}).get("size_mb")
        if whisper_downloaded(self.models_dir, name):
            on_progress(0.0, "Lade Sprachmodell")
        else:
            hint = f" (einmalig, ca. {size / 1000:.1f} GB)".replace(".", ",") if size else ""
            on_progress(0.0, f"Lade Sprachmodell herunter{hint}")

        root = self.models_dir / "whisper"
        threads = max(1, (os.cpu_count() or 4))
        try:
            if ctranslate2.get_cuda_device_count() > 0:
                try:
                    model = WhisperModel(name, device="cuda", compute_type="float16", download_root=str(root))
                except Exception:  # noqa: BLE001 – CUDA-Bibliotheken fehlen: auf CPU ausweichen
                    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads, download_root=str(root))
            else:
                model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads, download_root=str(root))
        except Exception as exc:  # noqa: BLE001
            raise EngineError(
                f"Sprachmodell „{name}“ konnte nicht geladen werden. Beim ersten Mal braucht "
                f"Notizer eine Internetverbindung. ({exc})"
            ) from exc
        self._model, self._model_name = model, name
        return model

    def transcribe(self, audio_path, *, model, language, vocabulary, on_progress, is_cancelled):  # noqa: ANN001, ANN201
        with self._lock:
            whisper = self._load(model, on_progress)
            on_progress(0.0, "Transkribiere")
            prompt = f"Begriffe: {vocabulary.strip()}." if vocabulary.strip() else None
            segments_iter, info = whisper.transcribe(
                str(audio_path),
                language=language or None,
                word_timestamps=True,
                vad_filter=True,
                beam_size=5,
                initial_prompt=prompt,
            )
            duration = float(info.duration or 0) or 1.0
            out: list[AsrSegment] = []
            for seg in segments_iter:
                if is_cancelled():
                    raise Cancelled
                words = [Word(float(w.start), float(w.end), w.word) for w in (seg.words or [])]
                out.append(AsrSegment(float(seg.start), float(seg.end), seg.text, words))
                on_progress(min(1.0, seg.end / duration), "Transkribiere")
            return AsrResult(language=info.language, duration=float(info.duration or 0), segments=out)


# ---------- sherpa-onnx ----------


class SherpaDiarizer:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir

    def diarize(self, audio_path, *, num_speakers, on_progress, is_cancelled):  # noqa: ANN001, ANN201
        import numpy as np  # noqa: PLC0415
        import sherpa_onnx  # noqa: PLC0415
        from faster_whisper.audio import decode_audio  # noqa: PLC0415

        seg_model, emb_model = ensure_diarization_models(
            self.models_dir, lambda f, t: on_progress(f * 0.2, t), is_cancelled
        )
        on_progress(0.2, "Erkenne Sprecher")
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model)),
                num_threads=max(1, (os.cpu_count() or 2) // 2),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(emb_model), num_threads=max(1, (os.cpu_count() or 2) // 2)
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_speakers if num_speakers else -1,
                threshold=0.45,  # kleiner = mehr Sprecher; per Test an zwei Stimmen eingestellt
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise EngineError("Die Modelle für die Sprechertrennung sind beschädigt. Bitte erneut versuchen.")
        sd = sherpa_onnx.OfflineSpeakerDiarization(config)
        samples = decode_audio(str(audio_path), sampling_rate=sd.sample_rate).astype(np.float32)

        def callback(done: int, total: int) -> int:
            on_progress(0.2 + 0.8 * done / max(total, 1), "Erkenne Sprecher")
            return 1 if is_cancelled() else 0

        result = sd.process(samples, callback=callback).sort_by_start_time()
        if is_cancelled():
            raise Cancelled
        return [Turn(float(r.start), float(r.end), int(r.speaker)) for r in result]


# ---------- Zusammenführen ----------


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speakers(words: list[Word], turns: list[Turn]) -> list[int | None]:
    """Jedem Wort den Sprecher mit der größten zeitlichen Überlappung zuordnen."""
    result: list[int | None] = []
    j = 0
    last: int | None = None
    for w in words:
        while j < len(turns) and turns[j].end < w.start - 1.0:
            j += 1
        best, best_ov, best_dist = None, 0.0, 1e9
        k = j
        while k < len(turns) and turns[k].start <= w.end + 1.0:
            t = turns[k]
            ov = _overlap(w.start, w.end, t.start, t.end)
            dist = 0.0 if ov > 0 else min(abs(t.start - w.end), abs(w.start - t.end))
            if ov > best_ov or (best_ov == 0 and ov == 0 and dist < best_dist):
                best, best_ov, best_dist = t.speaker, ov, dist
            k += 1
        if best is None or (best_ov == 0 and best_dist > 1.0):
            best = last
        result.append(best)
        last = best
    return result


def merge(asr: AsrResult, turns: list[Turn] | None) -> list[MergedSegment]:
    """Whisper-Text und Sprecherwechsel zu lesbaren Abschnitten zusammenführen.

    Ein neuer Abschnitt beginnt, wenn der Sprecher wechselt, nach einer Pause von
    mehr als 2 Sekunden oder nach etwa 40 Sekunden am nächsten Satzende.
    """
    words: list[Word] = []
    for seg in asr.segments:
        if seg.words:
            words.extend(seg.words)
        elif seg.text.strip():
            words.append(Word(seg.start, seg.end, " " + seg.text.strip()))
    if not words:
        return []

    if turns:
        raw = assign_speakers(words, turns)
        order: dict[int, str] = {}
        labels: list[str | None] = []
        for spk in raw:
            if spk is None:
                labels.append(None)
                continue
            if spk not in order:
                order[spk] = f"Sprecher {len(order) + 1}"
            labels.append(order[spk])
    else:
        labels = [None] * len(words)

    out: list[MergedSegment] = []
    cur: list[Word] = []
    cur_label: str | None = None

    def flush() -> None:
        if cur:
            text = "".join(w.text for w in cur).strip()
            if text:
                out.append(MergedSegment(cur[0].start, cur[-1].end, text, cur_label, list(cur)))
            cur.clear()

    for w, label in zip(words, labels):
        if cur:
            gap = w.start - cur[-1].end
            long_enough = cur[-1].end - cur[0].start > 40 and cur[-1].text.rstrip().endswith((".", "?", "!"))
            if label != cur_label or gap > 2.0 or long_enough:
                flush()
        if not cur:
            cur_label = label
        cur.append(w)
    flush()
    return out


def clean_dir(path: Path) -> None:  # pragma: no cover – Hilfsfunktion für "Modelle löschen"
    shutil.rmtree(path, ignore_errors=True)
