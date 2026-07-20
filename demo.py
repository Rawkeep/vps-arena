"""End-to-End-Demo ohne Ollama: zeigt, wie der Graph ueber mehrere Matches lernt.

python demo.py
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid

from arena.config import Settings
from arena.db import connect, init_schema
from arena.graph import stats
from arena.loop import match, revenue_summary, run_match
from arena.models import Job, Result


def _job(title: str, tags: list, desc: str = "") -> Job:
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title=title, description=desc, tags=tags)


def main() -> None:
    art_root = tempfile.mkdtemp(prefix="arena-demo-")
    settings = Settings(db_path=":memory:", artifacts_dir=art_root)  # fluechtig
    conn = connect(settings.db_path)
    init_schema(conn)

    print("=== VPS-Arena Demo — der Graph lernt aus Matches ===\n")

    # Runde 1: zwei RAG-Jobs gewinnen, ein Dashboard-Job verliert.
    print("[Runde 1] Historie aufbauen ...")
    run_match(
        conn,
        _job("DSGVO-Chatbot fuer Kanzlei", ["rag", "dsgvo"]),
        settings,
        result=Result.WIN,
        revenue=4200.0,
    )
    run_match(
        conn,
        _job("Wissensdatenbank-Suche", ["rag", "api"]),
        settings,
        result=Result.WIN,
        revenue=3100.0,
    )
    run_match(conn, _job("Marketing-Dashboard", ["dashboard"]), settings, result=Result.LOSS)
    print("   3 Matches gefahren.\n")

    # Runde 2: neuer, aehnlicher Job -> Graph empfiehlt die Gewinner-Bausteine.
    print("[Runde 2] Neuer RAG-Job kommt rein — was erinnert der Graph?")
    neu = _job("Internes Q&A-System", ["rag", "dsgvo"])
    from arena.loop import ingest_job

    m = match(conn, ingest_job(conn, neu), settings)
    print(f"   Aehnliche Jobs gefunden: {len(m.similar_jobs)}")
    for ms in m.recommended_modules:
        print(f"     {ms.module:<16} score={ms.score:+.1f}  (W{ms.wins}/L{ms.losses})")

    # Runde 3: aus dem empfohlenen Build wird ein ECHTES, startbares Artefakt.
    print("\n[Runde 3] Deploy: der Build wird zu lauffaehiger Software (v0.2)")
    b = run_match(
        conn,
        _job("RAG-Service fuer Kunde", ["rag", "api"]),
        settings,
        result=Result.WIN,
        revenue=2800.0,
    )
    print(f"   Artefakt: {b.artifact_path}")
    for root, _dirs, files in os.walk(b.artifact_path):
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), b.artifact_path)
            print(f"     - {rel}")
    print(f"   Starten:  python {b.artifact_path}/run.py  ->  http://127.0.0.1:8080")

    # Runde 4: Autopilot pickt Jobs autonom aus einem Feed (v0.3).
    print("\n[Runde 4] Autopilot: der Agent pickt Jobs selbst (v0.3)")
    feed_path = os.path.join(art_root, "jobs.json")
    with open(feed_path, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"id": "ext-a", "title": "DSGVO-Chatbot fuer Kanzlei", "tags": ["rag", "dsgvo"]},
                {"id": "ext-b", "title": "Marktdaten-Dashboard", "tags": ["dashboard", "api"]},
            ],
            fh,
        )
    from arena.autopilot import run_once
    from arena.gateway import deployed_builds
    from arena.sources import FeedSource

    summary = run_once(conn, settings, [FeedSource(feed_path)])
    print(
        f"   Autonom gepickt & gebaut: {len(summary['picked'])}, "
        f"uebersprungen: {summary['skipped']}"
    )
    again = run_once(conn, settings, [FeedSource(feed_path)])  # Dedup zeigen
    print(
        f"   Erneuter Poll -> neu: {len(again['picked'])}, "
        f"bekannt uebersprungen: {again['skipped']}"
    )

    print("\n[Runde 5] Gateway-Lobby: alle Builds unter je einer URL (v0.3)")
    for b in deployed_builds(conn):
        print(f"   /b/{b['url_id']}/  -> {b['title']}  [{', '.join(b['modules'])}]")

    bilanz = revenue_summary(conn)
    print("\n[Survival-Bilanz]")
    print(
        f"   Revenue {bilanz['revenue']:.0f} € · "
        f"W{int(bilanz['wins'])}/L{int(bilanz['losses'])} · "
        f"Winrate {bilanz['win_rate'] * 100:.0f}%"
    )

    print("\n[Kennzahlen]")
    for k, v in stats(conn).items():
        print(f"   {k:<10} {v}")

    print("\nFazit: Der Agent pickt Jobs selbst, baut startbare Software und servt")
    print("sie unter eigenen URLs — ohne Cloud, ohne LLM-Zwang. Das ist die Arena.")


if __name__ == "__main__":
    main()
