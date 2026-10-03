"""Einstellungen des Cores.

Werte kommen aus Umgebungsvariablen mit dem Präfix ``NOTIZER_`` oder aus den
Startparametern (siehe ``__main__.py``).
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    # Windows: %LOCALAPPDATA%\Notizer, Linux: ~/.local/share/notizer
    return Path(user_data_dir("Notizer", appauthor=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOTIZER_")

    data_dir: Path = default_data_dir()
    host: str = "127.0.0.1"  # nur lokal erreichbar
    port: int = 0  # 0 = freien Port wählen
    token: str = ""  # leer = beim Start zufällig erzeugen
    trash_days: int = 30
    allowed_extensions: tuple[str, ...] = (".mp3", ".m4a", ".wav")

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "notizer.db"

    def ensure_dirs(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
