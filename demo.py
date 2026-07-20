"""End-to-End-Demo ohne Ollama: zeigt, wie der Graph ueber mehrere Matches lernt.

    python demo.py
"""

from __future__ import annotations

import uuid

from arena.config import Settings
from arena.db import connect, init_schema
from arena.graph import stats
from arena.loop import match, run_match
from arena.models import Job, Result


def _job(title: str, tags: list, desc: str = "") -> Job:
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title=title, description=desc, tags=tags)


def main() -> None:
    settings = Settings(db_path=":memory:")  # fluechtige DB fuer die Demo
    conn = connect(settings.db_path)
    init_schema(conn)

    print("=== VPS-Arena Demo — der Graph lernt aus Matches ===\n")

    # Runde 1: zwei RAG-Jobs gewinnen, ein Dashboard-Job verliert.
    print("[Runde 1] Historie aufbauen ...")
    run_match(conn, _job("DSGVO-Chatbot fuer Kanzlei", ["rag", "dsgvo"]),
              settings, result=Result.WIN, revenue=4200.0)
    run_match(conn, _job("Wissensdatenbank-Suche", ["rag", "api"]),
              settings, result=Result.WIN, revenue=3100.0)
    run_match(conn, _job("Marketing-Dashboard", ["dashboard"]),
              settings, result=Result.LOSS)
    print("   3 Matches gefahren.\n")

    # Runde 2: neuer, aehnlicher Job -> Graph empfiehlt die Gewinner-Bausteine.
    print("[Runde 2] Neuer RAG-Job kommt rein — was erinnert der Graph?")
    neu = _job("Internes Q&A-System", ["rag", "dsgvo"])
    from arena.loop import ingest_job

    m = match(conn, ingest_job(conn, neu), settings)
    print(f"   Aehnliche Jobs gefunden: {len(m.similar_jobs)}")
    for ms in m.recommended_modules:
        print(f"     {ms.module:<16} score={ms.score:+.1f}  (W{ms.wins}/L{ms.losses})")

    print("\n[Kennzahlen]")
    for k, v in stats(conn).items():
        print(f"   {k:<10} {v}")

    print("\nFazit: Ohne jede Cloud, ohne LLM-Zwang — der Graph macht den naechsten")
    print("Build datengetrieben besser. Genau das ist der 'XP/Loot'-Mechanismus.")


if __name__ == "__main__":
    main()
