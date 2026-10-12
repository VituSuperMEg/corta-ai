"""Biblioteca local de áudio: faixas de música e SFX que o usuário coloca em assets/."""
from __future__ import annotations

import os
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
SFX_KINDS = ("impact", "whoosh", "riser")


def assets_dir() -> Path:
    override = os.environ.get("CORTA_AI_ASSETS_DIR")
    return Path(override).resolve() if override else Path(__file__).resolve().parent / "assets"


def music_dir() -> Path:
    return assets_dir() / "music"


def sfx_dir() -> Path:
    return assets_dir() / "sfx"


def list_music() -> list[str]:
    folder = music_dir()
    if not folder.is_dir():
        return []
    return sorted(item.name for item in folder.iterdir()
                  if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS)


def resolve_music(name: str) -> Path | None:
    if not name or Path(name).name != name:
        return None
    candidate = music_dir() / name
    return candidate if candidate.is_file() and candidate.suffix.lower() in AUDIO_EXTENSIONS else None


def list_sfx(kind: str) -> list[Path]:
    if kind not in SFX_KINDS:
        return []
    folder = sfx_dir() / kind
    if not folder.is_dir():
        return []
    return sorted(item for item in folder.iterdir()
                  if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS)


def resolve_sfx(kind: str) -> Path | None:
    """Arquivo real do usuário para a categoria; None cai na síntese local."""
    files = list_sfx(kind)
    return files[0] if files else None
