"""Build-Agent: erzeugt aus einem Job + Graph-Empfehlung eine Build-Spezifikation.

Standard = deterministischer Mock (kein Netz, immer lauffaehig). Ist
`ARENA_USE_OLLAMA=1` gesetzt und Ollama erreichbar, formuliert das lokale LLM
die Spec-Prosa — die *Bausteinwahl* bleibt aber datengetrieben (Graph), das
LLM entscheidet nichts Hartes.
"""

from __future__ import annotations

import json
from typing import List, Tuple

from .config import Settings
from .models import Job, MatchResult

# Kanon der wiederverwendbaren Bausteine (waechst mit dem Oekosystem).
KNOWN_MODULES = [
    "auth-jwt",
    "sqlite-store",
    "rag-grounded",
    "ollama-client",
    "pdf-export",
    "rate-limit",
    "react-dashboard",
    "express-api",
    "langgraph-agents",
    "data-firewall",
]

# Sehr simple Heuristik: welche Bausteine ein Tag nahelegt (Kaltstart, wenn der
# Graph noch nichts "erinnert").
_TAG_HINTS = {
    "api": ["express-api", "rate-limit"],
    "auth": ["auth-jwt"],
    "rag": ["rag-grounded", "ollama-client"],
    "dashboard": ["react-dashboard"],
    "export": ["pdf-export"],
    "agent": ["langgraph-agents"],
    "dsgvo": ["data-firewall"],
    "storage": ["sqlite-store"],
}


def choose_modules(job: Job, match: MatchResult, limit: int = 4) -> List[str]:
    """Bausteinwahl: erst Graph-Evidenz (nur positive Scores), dann Tag-Heuristik."""
    chosen: List[str] = [m.module for m in match.recommended_modules if m.score > 0]

    for tag in job.tags:
        for mod in _TAG_HINTS.get(tag.lower(), []):
            if mod not in chosen:
                chosen.append(mod)

    if "sqlite-store" not in chosen:
        chosen.append("sqlite-store")  # Local-first-Basis immer dabei

    return chosen[:limit]


def _mock_spec(job: Job, modules: List[str]) -> str:
    return (
        f"Build fuer '{job.title}': komponiert aus {', '.join(modules)}. "
        f"Local-first (SQLite), offline-faehig. Tags: {', '.join(job.tags) or '-'}."
    )


def _ollama_spec(job: Job, modules: List[str], settings: Settings) -> str:
    """Optionaler LLM-Call ueber stdlib urllib (lazy, keine harte Dep)."""
    import urllib.error
    import urllib.request

    prompt = (
        "Formuliere in einem deutschen Satz die Spezifikation eines Software-Builds.\n"
        f"Auftrag: {job.title}\nBeschreibung: {job.description}\n"
        f"Zu verwendende Bausteine: {', '.join(modules)}."
    )
    payload = json.dumps(
        {"model": settings.ollama_model, "prompt": prompt, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{settings.ollama_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (lokale URL)
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response", "")).strip() or _mock_spec(job, modules)


def build_spec(job: Job, match: MatchResult, settings: Settings) -> Tuple[str, List[str]]:
    """Liefert (spec, modules). Faellt bei jedem Ollama-Fehler still auf Mock zurueck."""
    modules = choose_modules(job, match)
    if settings.use_ollama:
        try:
            return _ollama_spec(job, modules, settings), modules
        except Exception:  # noqa: BLE001 — Offline-Fallback ist Absicht
            return _mock_spec(job, modules), modules
    return _mock_spec(job, modules), modules
