"""Baut den Notizer Core als einzelne Datei und legt sie für Tauri ab.

Aufruf (aus dem Projektordner, mit aktivierter Core-venv):

    python scripts/build_core.py

Ergebnis: app/src-tauri/binaries/notizer-core-<ziel-triple>[.exe]
Tauri erwartet den Namen mit dem Rust-Ziel-Triple, z. B.
notizer-core-x86_64-pc-windows-msvc.exe oder notizer-core-x86_64-unknown-linux-gnu.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"
TARGET_DIR = ROOT / "app" / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("Rust-Ziel-Triple nicht gefunden (ist rustc installiert?)")


def main() -> None:
    work = CORE / "build"
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onefile",
            "--name", "notizer-core",
            "--distpath", str(work / "dist"),
            "--workpath", str(work / "pyinstaller"),
            "--specpath", str(work),
            "--collect-submodules", "uvicorn",
            "--collect-submodules", "notizer_core",
            str(CORE / "run_core.py"),
        ],
        check=True,
        cwd=CORE,
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    built = work / "dist" / f"notizer-core{suffix}"
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    dest = TARGET_DIR / f"notizer-core-{target_triple()}{suffix}"
    shutil.copy2(built, dest)
    print(f"Core gebaut: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
