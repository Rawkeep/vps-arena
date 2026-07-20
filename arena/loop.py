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
from typing import List, Optional

from .agent import build_spec
from .config import Settings
from .db import dumps
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
        "INSERT INTO jobs(id, title, description, tags, budget, status, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            job.id,
            job.title,
            job.description,
            dumps(job.tags),
            job.budget,
            job.status.value,
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


def build(conn: sqlite3.Connection, job: Job, match_result: MatchResult, settings: Settings) -> Build:
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


def deploy(conn: sqlite3.Connection, build_obj: Build, artifact_path: Optional[str] = None) -> Build:
    """Stub: markiert den Build als live. Hier haengt in Prod der echte Deploy."""
    path = artifact_path or f"builds/{build_obj.id.replace(':', '_')}"
    conn.execute(
        "UPDATE builds SET status = ?, artifact_path = ? WHERE id = ?",
        (BuildStatus.DEPLOYED.value, path, build_obj.id),
    )
    _set_job_status(conn, build_obj.job_id, JobStatus.DEPLOYED)
    conn.commit()
    build_obj.status = BuildStatus.DEPLOYED
    build_obj.artifact_path = path
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
    deploy(conn, b)
    if result is not None:
        score(conn, b, result, revenue)
    return b


def _set_job_status(conn: sqlite3.Connection, job_id: str, status: JobStatus) -> None:
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))


def list_jobs(conn: sqlite3.Connection) -> List[Job]:
    from .db import loads

    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
    out: List[Job] = []
    for r in rows:
        out.append(
            Job(
                id=r["id"],
                title=r["title"],
                description=r["description"],
                tags=loads(r["tags"], []),  # type: ignore[arg-type]
                budget=r["budget"],
                status=r["status"],
                created_at=r["created_at"],
            )
        )
    return out
