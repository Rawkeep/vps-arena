"""Regressionsschutz fuer das Kern-IP: der Graph empfiehlt Gewinner-Bausteine."""

from __future__ import annotations

import uuid

import pytest

from arena.config import Settings
from arena.db import connect, init_schema
from arena.graph import recommend_modules, similar_jobs, stats
from arena.loop import ingest_job, run_match
from arena.models import Job, Result


@pytest.fixture()
def conn():
    c = connect(":memory:")
    init_schema(c)
    return c


@pytest.fixture()
def settings():
    return Settings(db_path=":memory:")


def _job(title, tags):
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title=title, tags=tags)


def test_leerer_graph_empfiehlt_nichts(conn, settings):
    res = recommend_modules(conn, ["rag"], settings)
    assert res.recommended_modules == []
    assert res.similar_jobs == []


def test_sieg_hebt_baustein_score(conn, settings):
    run_match(conn, _job("RAG A", ["rag"]), settings, result=Result.WIN, revenue=1000)
    res = recommend_modules(conn, ["rag"], settings)
    names = [m.module for m in res.recommended_modules]
    assert "rag-grounded" in names
    top = res.recommended_modules[0]
    assert top.score > 0 and top.wins >= 1


def test_niederlage_senkt_score(conn, settings):
    run_match(conn, _job("Dash A", ["dashboard"]), settings, result=Result.LOSS)
    res = recommend_modules(conn, ["dashboard"], settings)
    dash = [m for m in res.recommended_modules if m.module == "react-dashboard"]
    assert dash and dash[0].score < 0 and dash[0].losses >= 1


def test_similar_jobs_ueber_tag_ueberlappung(conn, settings):
    ingest_job(conn, _job("J1", ["rag", "dsgvo"]))
    ingest_job(conn, _job("J2", ["api"]))
    sims = similar_jobs(conn, ["rag"], settings)
    assert len(sims) == 1  # nur J1 teilt einen Tag


def test_akkumulierte_evidenz_ranking(conn, settings):
    # rag gewinnt zweimal -> jeder beteiligte Baustein traegt 2 Siege,
    # rag-grounded ist unter den Top-Scores (Ties sind bewusst gleichwertig).
    run_match(conn, _job("R1", ["rag"]), settings, result=Result.WIN, revenue=500)
    run_match(conn, _job("R2", ["rag"]), settings, result=Result.WIN, revenue=500)
    res = recommend_modules(conn, ["rag"], settings)
    top_score = res.recommended_modules[0].score
    assert top_score >= 2 * settings.win_weight - 1e-9
    rag = [m for m in res.recommended_modules if m.module == "rag-grounded"][0]
    assert rag.score == top_score and rag.wins == 2


def test_stats_zaehlt_entitaeten(conn, settings):
    run_match(conn, _job("R1", ["rag"]), settings, result=Result.WIN)
    s = stats(conn)
    assert s["jobs"] == 1 and s["builds"] == 1 and s["outcomes"] == 1
    assert s["nodes"] > 0 and s["edges"] > 0
