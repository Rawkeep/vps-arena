"""Autopilot (v0.3): autonomes Job-Picking.

Pollt alle konfigurierten Quellen, ueberspringt bereits gesehene Jobs (Dedup)
und faehrt fuer jeden neuen Job den vollen Loop ingest->match->build->deploy.

Das Scoren (win/loss/revenue) bleibt bewusst aussen vor — das ist ein echtes
Marktsignal, kein Automatismus. Builds landen im Status DEPLOYED und warten auf
ein Outcome (`arena score` / spaeter Webhook).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Sequence

from .config import Settings
from .loop import is_seen, mark_seen, run_match
from .models import Job


class Source:
    """Strukturelle Erwartung an eine Quelle: name + poll()."""

    name: str

    def poll(self) -> List[Job]:  # pragma: no cover - Protokoll
        raise NotImplementedError


def run_once(
    conn: sqlite3.Connection, settings: Settings, sources: Sequence[Any]
) -> Dict[str, Any]:
    """Ein Poll-Durchlauf ueber alle Quellen. Liefert eine Zusammenfassung."""
    picked: List[Dict[str, str]] = []
    skipped = 0

    for src in sources:
        try:
            jobs = src.poll()
        except Exception as exc:  # eine kaputte Quelle darf den Lauf nicht killen
            picked.append({"source": getattr(src, "name", "?"), "error": str(exc)})
            continue

        for job in jobs:
            ext = job.external_id
            if ext and is_seen(conn, ext):
                skipped += 1
                continue
            build_obj = run_match(conn, job, settings)  # ingest->match->build->deploy
            if ext:
                mark_seen(conn, ext, job.source or getattr(src, "name", "?"), job.id)
            picked.append(
                {
                    "source": job.source or getattr(src, "name", "?"),
                    "job": job.title,
                    "build": build_obj.id,
                    "modules": ", ".join(build_obj.modules),
                    "artifact": build_obj.artifact_path or "",
                }
            )

    return {
        "picked": [p for p in picked if "build" in p],
        "errors": [p for p in picked if "error" in p],
        "skipped": skipped,
    }


def run_forever(
    conn: sqlite3.Connection,
    settings: Settings,
    sources: Sequence[Any],
    interval: int = 30,
    on_cycle=None,
) -> None:  # pragma: no cover - Endlosschleife (Daemon)
    """Poll-Schleife fuer den Dauerbetrieb auf dem VPS."""
    while True:
        summary = run_once(conn, settings, sources)
        if on_cycle:
            on_cycle(summary)
        time.sleep(interval)
