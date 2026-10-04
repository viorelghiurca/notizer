"""Baut den Notizer Core und legt ihn für den Tauri-Installer ab.

Aufruf (aus dem Projektordner, mit aktivierter Core-venv):

    python scripts/build_core.py

Ergebnis: app/src-tauri/core-dist/ mit notizer-core[.exe] und _internal/.
Der Installer kopiert diesen Ordner als Ressource "core/" neben die App.
Als Ordner (statt Einzeldatei) startet der Core sofort, weil er sich nicht bei
jedem Start erst entpacken muss.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"
TARGET_DIR = ROOT / "app" / "src-tauri" / "core-dist"


def main() -> None:
    work = CORE / "build"
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onedir",
            "--name", "notizer-core",
            "--distpath", str(work / "dist"),
            "--workpath", str(work / "pyinstaller"),
            "--specpath", str(work),
            "--collect-submodules", "uvicorn",
            "--collect-submodules", "notizer_core",
            # Modell der Sprachpausen-Erkennung (silero_vad) liegt als Datei im Paket.
            # Native Bibliotheken von ctranslate2, onnxruntime, av und sherpa-onnx
            # findet PyInstaller selbst; zusätzliches Einsammeln würde sie doppelt ablegen.
            "--collect-data", "faster_whisper",
            "--copy-metadata", "faster_whisper",
            str(CORE / "run_core.py"),
        ],
        check=True,
        cwd=CORE,
    )
    built = work / "dist" / "notizer-core"
    shutil.rmtree(TARGET_DIR, ignore_errors=True)
    shutil.copytree(built, TARGET_DIR)
    size = sum(f.stat().st_size for f in TARGET_DIR.rglob("*") if f.is_file())
    print(f"Core gebaut: {TARGET_DIR} ({size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
