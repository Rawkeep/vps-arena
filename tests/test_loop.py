"""Der Match-Loop: Statusuebergaenge + Persistenz."""

from __future__ import annotations

import uuid

import pytest

from arena.config import Settings
from arena.db import connect, init_schema
from arena.loop import build, deploy, ingest_job, list_jobs, match, score
from arena.models import BuildStatus, Job, JobStatus, Result


@pytest.fixture()
def ctx():
    c = connect(":memory:")
    init_schema(c)
    return c, Settings(db_path=":memory:")


def _job(tags):
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title="T", tags=tags)


def test_voller_loop_setzt_status(ctx):
    conn, settings = ctx
    job = ingest_job(conn, _job(["rag"]))
    assert list_jobs(conn)[0].status == JobStatus.OPEN

    m = match(conn, job, settings)
    b = build(conn, job, m, settings)
    assert b.status == BuildStatus.DRAFT
    assert "sqlite-store" in b.modules  # Local-first-Basis immer dabei

    b = deploy(conn, b)
    assert b.status == BuildStatus.DEPLOYED and b.artifact_path

    out = score(conn, b, Result.WIN, revenue=999.0)
    assert out.result == Result.WIN
    assert list_jobs(conn)[0].status == JobStatus.WON


def test_ingest_persistiert_tags(ctx):
    conn, _ = ctx
    ingest_job(conn, _job(["rag", "dsgvo"]))
    stored = list_jobs(conn)[0]
    assert stored.tags == ["rag", "dsgvo"]


def test_loss_setzt_job_auf_lost(ctx):
    conn, settings = ctx
    job = ingest_job(conn, _job(["dashboard"]))
    m = match(conn, job, settings)
    b = deploy(conn, build(conn, job, m, settings))
    score(conn, b, Result.LOSS)
    assert list_jobs(conn)[0].status == JobStatus.LOST
