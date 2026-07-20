"""Zentrale Konfiguration (Praefix ARENA_) — keine Magic Numbers verstreuen."""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel


class Settings(BaseModel):
    # Speicher
    db_path: str = "data/arena.db"
    # Wurzelverzeichnis, in das Deploy die startbaren Artefakte schreibt.
    artifacts_dir: str = "builds"

    # Local-LLM (Ollama). Ohne erreichbares Ollama faellt der Agent auf den
    # deterministischen Mock zurueck — nichts blockiert den lokalen Lauf.
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    use_ollama: bool = False

    # Match-Tuning: wie stark ein Sieg/eine Niederlage einen Baustein bewertet.
    win_weight: float = 1.0
    loss_penalty: float = 0.5
    # Mindest-Tag-Ueberlappung, damit ein alter Job als "aehnlich" zaehlt.
    min_tag_overlap: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        def _get(key: str, default: Optional[str] = None) -> Optional[str]:
            return os.environ.get(f"ARENA_{key}", default)

        return cls(
            db_path=_get("DB_PATH", "data/arena.db") or "data/arena.db",
            artifacts_dir=_get("ARTIFACTS_DIR", "builds") or "builds",
            ollama_url=_get("OLLAMA_URL", "http://localhost:11434") or "http://localhost:11434",
            ollama_model=_get("OLLAMA_MODEL", "llama3.2:3b") or "llama3.2:3b",
            use_ollama=(_get("USE_OLLAMA", "0") or "0").lower() in {"1", "true", "yes"},
        )
