"""Kommandozeile: `arena <command>` (Konsole-Entry aus pyproject).

arena init                              # DB anlegen
arena ingest "<titel>" --tags a,b       # Job aufnehmen
arena run "<titel>" --tags a,b [--win|--loss] [--revenue N]
arena match "<titel>" --tags a,b        # nur Empfehlung zeigen
arena autopilot --feed jobs.json [--dir inbox/] [--once] [--interval 30]
arena gateway [--port 8080]             # Lobby: alle Builds unter einer URL
arena ls                                # deployte Builds + Revenue
arena score <build_id> --win|--loss [--revenue N]
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
from .loop import get_build, ingest_job, match, revenue_summary, run_match, score
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

    p_auto = sub.add_parser("autopilot", help="Autonom Jobs aus Quellen picken & bauen")
    p_auto.add_argument("--feed", help="JSON-Feed-Datei mit Jobs")
    p_auto.add_argument("--dir", help="Verzeichnis mit Job-Dateien (*.json/*.md)")
    p_auto.add_argument("--once", action="store_true", help="nur ein Durchlauf")
    p_auto.add_argument("--interval", type=int, default=30, help="Poll-Intervall (s)")

    p_gw = sub.add_parser("gateway", help="Lobby-Gateway starten (alle Builds unter einer URL)")
    p_gw.add_argument("--port", type=int, default=8080)

    sub.add_parser("ls", help="Deployte Builds + Revenue-Bilanz")

    p_score = sub.add_parser("score", help="Outcome fuer einen Build erfassen")
    p_score.add_argument("build_id")
    p_score.add_argument("--win", action="store_true")
    p_score.add_argument("--loss", action="store_true")
    p_score.add_argument("--revenue", type=float, default=0.0)

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

    if args.cmd == "autopilot":
        from .autopilot import run_forever, run_once
        from .sources import DirSource, FeedSource

        sources: list = []
        if args.feed:
            sources.append(FeedSource(args.feed))
        if args.dir:
            sources.append(DirSource(args.dir))
        if not sources:
            print("Keine Quelle angegeben — nutze --feed und/oder --dir.")
            return 2

        def _report(summary: dict) -> None:
            for p in summary["picked"]:
                print(f"  + gebaut: {p['job']}  [{p['modules']}]")
            for e in summary["errors"]:
                print(f"  ! Quelle {e['source']}: {e['error']}")
            print(f"  ({len(summary['picked'])} neu, {summary['skipped']} bekannt uebersprungen)")

        if args.once:
            _report(run_once(conn, settings, sources))
        else:
            print(f"Autopilot laeuft (alle {args.interval}s). Strg+C zum Stoppen.")
            run_forever(conn, settings, sources, interval=args.interval, on_cycle=_report)
        return 0

    if args.cmd == "gateway":
        from .gateway import serve as gateway_serve

        gateway_serve(settings, port=args.port)
        return 0

    if args.cmd == "ls":
        from .gateway import deployed_builds

        builds = deployed_builds(conn)
        for bd in builds:
            rev = f"{bd['revenue']:.0f} €" if bd["revenue"] else "-"
            state = bd["result"] or "live"
            print(f"  {bd['build_id']}  {state:<5} {rev:>8}  {bd['title']}")
            print(f"      Module: {', '.join(bd['modules'])}")
        summ = revenue_summary(conn)
        print(
            f"  --- {len(builds)} Build(s) · Revenue {summ['revenue']:.0f} € · "
            f"W{int(summ['wins'])}/L{int(summ['losses'])} · "
            f"Winrate {summ['win_rate'] * 100:.0f}%"
        )
        return 0

    if args.cmd == "score":
        bld = get_build(conn, args.build_id)
        if bld is None:
            print(f"Build {args.build_id} nicht gefunden.")
            return 2
        outcome_result = Result.WIN if args.win else Result.LOSS if args.loss else None
        if outcome_result is None:
            print("Bitte --win oder --loss angeben.")
            return 2
        out = score(conn, bld, outcome_result, revenue=args.revenue)
        print(f"Outcome erfasst: {out.result.value}  Revenue {out.revenue:.2f}")
        return 0

    if args.cmd == "stats":
        for k, v in stats(conn).items():
            print(f"  {k:<10} {v}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
