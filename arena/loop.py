"""Der Match-Loop: die Kern-Schleife des Systems.

    ingest(job) -> match(job) -> build(job) -> deploy(build) -> score(...)
       ^                                                            |
       |____________ naechster Match, schlauer als vorher __________|

Jeder Schritt schreibt sowohl in die Kern-Tabellen als auch in den Graph, damit
das Ergebnis in die naechste Empfehlung einfliesst (XP/Loot).
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Dict, List, Optional

from .agent import build_spec
from .config import Settings
from .db import dumps, loads
from .graph import recommend_modules, upsert_edge, upsert_node
from .models import (
    Build,
    BuildStatus,
    Edge,
    Job,
    JobStatus,
    MatchResult,
    Node,
    NodeType,
    Outcome,
    Result,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


# --- 1. INGEST ---------------------------------------------------------------


def ingest_job(conn: sqlite3.Connection, job: Job) -> Job:
    """Job speichern + als Knoten samt Tag-Kanten in den Graph legen."""
    conn.execute(
        "INSERT INTO jobs(id, title, description, tags, budget, status, "
        "external_id, source, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            job.id,
            job.title,
            job.description,
            dumps(job.tags),
            job.budget,
            job.status.value,
            job.external_id,
            job.source,
            job.created_at,
        ),
    )
    upsert_node(conn, Node(id=job.id, type=NodeType.JOB, label=job.title))
    for tag in job.tags:
        tag_id = f"tag:{tag.lower()}"
        upsert_node(conn, Node(id=tag_id, type=NodeType.TAG, label=tag))
        upsert_edge(conn, Edge(src=job.id, dst=tag_id, rel="tagged"))
    conn.commit()
    return job


# --- 2. MATCH ----------------------------------------------------------------


def match(conn: sqlite3.Connection, job: Job, settings: Settings) -> MatchResult:
    """Graph befragen: was hat bei aehnlichen Jobs gewonnen?"""
    result = recommend_modules(conn, job.tags, settings)
    result.job_id = job.id
    _set_job_status(conn, job.id, JobStatus.MATCHED)
    return result


# --- 3. BUILD ----------------------------------------------------------------


def build(
    conn: sqlite3.Connection, job: Job, match_result: MatchResult, settings: Settings
) -> Build:
    """Agent erzeugt Spec + Bausteinwahl; Build + uses/produced-Kanten anlegen."""
    spec, modules = build_spec(job, match_result, settings)
    build_obj = Build(
        id=_new_id("build"),
        job_id=job.id,
        spec=spec,
        modules=modules,
        status=BuildStatus.DRAFT,
    )
    conn.execute(
        "INSERT INTO builds(id, job_id, spec, modules, artifact_path, status, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            build_obj.id,
            build_obj.job_id,
            build_obj.spec,
            dumps(build_obj.modules),
            build_obj.artifact_path,
            build_obj.status.value,
            build_obj.created_at,
        ),
    )
    upsert_node(conn, Node(id=build_obj.id, type=NodeType.BUILD, label=job.title))
    upsert_edge(conn, Edge(src=job.id, dst=build_obj.id, rel="produced"))
    for mod in modules:
        mod_id = f"module:{mod}"
        upsert_node(conn, Node(id=mod_id, type=NodeType.MODULE, label=mod))
        upsert_edge(conn, Edge(src=build_obj.id, dst=mod_id, rel="uses"))
    _set_job_status(conn, job.id, JobStatus.BUILT)
    conn.commit()
    return build_obj


# --- 4. DEPLOY ---------------------------------------------------------------


def deploy(
    conn: sqlite3.Connection,
    build_obj: Build,
    settings: Settings,
    out_root: Optional[str] = None,
) -> Build:
    """Materialisiert ein echtes, startbares Artefakt (v0.2) und markiert live.

    Aus `build_obj.modules` entsteht ein Verzeichnis mit lauffaehigem Code
    (`run.py` + Capabilities). Der Artefakt-Pfad wird persistiert.
    """
    from .scaffold import materialize

    job = get_job(conn, build_obj.job_id)
    if job is None:
        raise ValueError(f"Job {build_obj.job_id} nicht gefunden")
    root = out_root or settings.artifacts_dir
    art_dir, _manifest = materialize(build_obj, job, root)

    conn.execute(
        "UPDATE builds SET status = ?, artifact_path = ? WHERE id = ?",
        (BuildStatus.DEPLOYED.value, art_dir, build_obj.id),
    )
    _set_job_status(conn, build_obj.job_id, JobStatus.DEPLOYED)
    conn.commit()
    build_obj.status = BuildStatus.DEPLOYED
    build_obj.artifact_path = art_dir
    return build_obj


# --- 5. SCORE ----------------------------------------------------------------


def score(
    conn: sqlite3.Connection,
    build_obj: Build,
    result: Result,
    revenue: float = 0.0,
    notes: str = "",
) -> Outcome:
    """Ergebnis festhalten + won/lost-Kante ziehen -> naechste Empfehlung lernt daraus."""
    outcome = Outcome(
        id=_new_id("outcome"),
        build_id=build_obj.id,
        job_id=build_obj.job_id,
        result=result,
        revenue=revenue,
        notes=notes,
    )
    conn.execute(
        "INSERT INTO outcomes(id, build_id, job_id, result, revenue, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            outcome.id,
            outcome.build_id,
            outcome.job_id,
            outcome.result.value,
            outcome.revenue,
            outcome.notes,
            outcome.created_at,
        ),
    )
    upsert_node(conn, Node(id=outcome.id, type=NodeType.OUTCOME, label=result.value))
    rel = "won" if result == Result.WIN else "lost"
    upsert_edge(conn, Edge(src=build_obj.id, dst=outcome.id, rel=rel))
    conn.execute(
        "UPDATE builds SET status = ? WHERE id = ?",
        (BuildStatus.SCORED.value, build_obj.id),
    )
    _set_job_status(
        conn,
        build_obj.job_id,
        JobStatus.WON if result == Result.WIN else JobStatus.LOST,
    )
    conn.commit()
    return outcome


# --- Voller Durchlauf (Happy Path) ------------------------------------------


def run_match(
    conn: sqlite3.Connection,
    job: Job,
    settings: Settings,
    result: Optional[Result] = None,
    revenue: float = 0.0,
) -> Build:
    """ingest -> match -> build -> deploy (und optional score) in einem Rutsch."""
    ingest_job(conn, job)
    m = match(conn, job, settings)
    b = build(conn, job, m, settings)
    deploy(conn, b, settings)
    if result is not None:
        score(conn, b, result, revenue)
    return b


def _set_job_status(conn: sqlite3.Connection, job_id: str, status: JobStatus) -> None:
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))


def _row_to_job(r: sqlite3.Row) -> Job:
    keys = r.keys()
    return Job(
        id=r["id"],
        title=r["title"],
        description=r["description"],
        tags=loads(r["tags"], []),  # type: ignore[arg-type]
        budget=r["budget"],
        status=r["status"],
        external_id=r["external_id"] if "external_id" in keys else None,
        source=r["source"] if "source" in keys else None,
        created_at=r["created_at"],
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> Optional[Job]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row is not None else None


def get_build(conn: sqlite3.Connection, build_id: str) -> Optional[Build]:
    row = conn.execute("SELECT * FROM builds WHERE id = ?", (build_id,)).fetchone()
    if row is None:
        return None
    return Build(
        id=row["id"],
        job_id=row["job_id"],
        spec=row["spec"],
        modules=loads(row["modules"], []),  # type: ignore[arg-type]
        artifact_path=row["artifact_path"],
        status=row["status"],
        created_at=row["created_at"],
    )


def list_jobs(conn: sqlite3.Connection) -> List[Job]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
    return [_row_to_job(r) for r in rows]


# --- Dedup (fuer autonomes Job-Picking) -------------------------------------


def is_seen(conn: sqlite3.Connection, external_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM seen WHERE external_id = ?", (external_id,)).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, external_id: str, source: str, job_id: str) -> None:
    from .models import _now

    conn.execute(
        "INSERT OR IGNORE INTO seen(external_id, source, job_id, created_at) VALUES (?,?,?,?)",
        (external_id, source, job_id, _now()),
    )
    conn.commit()


# --- Revenue-/Survival-Uebersicht -------------------------------------------


def revenue_summary(conn: sqlite3.Connection) -> Dict[str, float]:
    """Aggregierte Bilanz ueber alle Outcomes (Vorstufe der Survival-Bilanz)."""
    row = conn.execute(
        "SELECT "
        "COALESCE(SUM(revenue), 0) AS revenue, "
        "SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins, "
        "SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses, "
        "COUNT(*) AS scored "
        "FROM outcomes"
    ).fetchone()
    wins = int(row["wins"] or 0)
    losses = int(row["losses"] or 0)
    scored = int(row["scored"] or 0)
    return {
        "revenue": float(row["revenue"] or 0.0),
        "wins": float(wins),
        "losses": float(losses),
        "scored": float(scored),
        "win_rate": float(wins / scored) if scored else 0.0,
    }
