"""Kommandozeile: `arena <command>` (Konsole-Entry aus pyproject).

    arena init                              # DB anlegen
    arena ingest "<titel>" --tags a,b       # Job aufnehmen
    arena run "<titel>" --tags a,b [--win|--loss] [--revenue N]
    arena match "<titel>" --tags a,b        # nur Empfehlung zeigen
    arena stats                             # Graph-/Tabellen-Kennzahlen
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import List, Optional

from .config import Settings
from .db import connect, init_schema
from .graph import stats
from .loop import ingest_job, match, run_match
from .models import Job, Result


def _tags(value: Optional[str]) -> List[str]:
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def _job(title: str, tags: List[str], description: str = "") -> Job:
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title=title, description=description, tags=tags)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="arena", description="VPS-Arena Match-Loop")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="DB + Schema anlegen")

    p_ing = sub.add_parser("ingest", help="Job aufnehmen")
    p_ing.add_argument("title")
    p_ing.add_argument("--tags", default="")
    p_ing.add_argument("--desc", default="")

    p_match = sub.add_parser("match", help="Empfehlung fuer einen (hypothetischen) Job zeigen")
    p_match.add_argument("title")
    p_match.add_argument("--tags", default="")

    p_run = sub.add_parser("run", help="Voller Match: ingest->match->build->deploy[->score]")
    p_run.add_argument("title")
    p_run.add_argument("--tags", default="")
    p_run.add_argument("--desc", default="")
    p_run.add_argument("--win", action="store_true")
    p_run.add_argument("--loss", action="store_true")
    p_run.add_argument("--revenue", type=float, default=0.0)

    sub.add_parser("stats", help="Kennzahlen ausgeben")

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    conn = connect(settings.db_path)
    init_schema(conn)

    if args.cmd == "init":
        print(f"DB bereit: {settings.db_path}")
        return 0

    if args.cmd == "ingest":
        job = ingest_job(conn, _job(args.title, _tags(args.tags), args.desc))
        print(f"Job aufgenommen: {job.id} ({job.title})")
        return 0

    if args.cmd == "match":
        job = _job(args.title, _tags(args.tags))
        res = match(conn, ingest_job(conn, job), settings)
        if not res.recommended_modules:
            print("Noch keine Evidenz im Graph — Kaltstart. Fahr ein paar Matches.")
        for m in res.recommended_modules:
            print(f"  {m.module:<20} score={m.score:+.1f}  (W{m.wins}/L{m.losses})")
        return 0

    if args.cmd == "run":
        result: Optional[Result] = None
        if args.win:
            result = Result.WIN
        elif args.loss:
            result = Result.LOSS
        job = _job(args.title, _tags(args.tags), args.desc)
        b = run_match(conn, job, settings, result=result, revenue=args.revenue)
        print(f"Build {b.id}\n  Spec:     {b.spec}\n  Module:   {', '.join(b.modules)}")
        print(f"  Artefakt: {b.artifact_path}")
        print(f"  Starten:  python {b.artifact_path}/run.py   (dann http://127.0.0.1:8080)")
        if result:
            print(f"  Ergebnis: {result.value}  Revenue: {args.revenue:.2f}")
        return 0

    if args.cmd == "stats":
        for k, v in stats(conn).items():
            print(f"  {k:<10} {v}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
