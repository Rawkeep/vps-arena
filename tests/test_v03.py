"""v0.3: Ingest-Quellen + Autopilot (autonomes Picking) + Gateway + Container."""

from __future__ import annotations

import json
import os
import threading
import urllib.request

import pytest

from arena.autopilot import run_once
from arena.config import Settings
from arena.db import connect, init_schema
from arena.gateway import create_server, deployed_builds
from arena.loop import list_jobs, run_match
from arena.scaffold import materialize
from arena.sources import DirSource, FeedSource, derive_tags
from arena.models import Build, Job


# --- Quellen -----------------------------------------------------------------


def test_derive_tags_aus_freitext():
    tags = derive_tags("DSGVO-konformer Chatbot fuer die Wissensdatenbank per API")
    assert "rag" in tags and "dsgvo" in tags and "api" in tags


def test_feed_source_parst_jobs(tmp_path):
    feed = tmp_path / "jobs.json"
    feed.write_text(
        json.dumps(
            [
                {"id": "ext-1", "title": "RAG-Bot", "tags": ["rag"], "budget": 3000},
                {"title": "Dashboard bauen", "description": "KPI Auswertung"},
            ]
        ),
        encoding="utf-8",
    )
    jobs = FeedSource(str(feed)).poll()
    assert len(jobs) == 2
    assert jobs[0].external_id == "ext-1" and jobs[0].source == "feed"
    # zweiter Job ohne Tags -> aus Text abgeleitet
    assert "dashboard" in jobs[1].tags


def test_dir_source_json_und_md(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"title": "A", "tags": ["api"]}), encoding="utf-8")
    (d / "b.md").write_text("# Export-Tool\nRechnungen als PDF exportieren", encoding="utf-8")
    jobs = DirSource(str(d)).poll()
    titles = sorted(j.title for j in jobs)
    assert titles == ["A", "Export-Tool"]
    md = [j for j in jobs if j.title == "Export-Tool"][0]
    assert "export" in md.tags


def test_feed_source_fehlende_datei_leer(tmp_path):
    assert FeedSource(str(tmp_path / "nope.json")).poll() == []


# --- Autopilot (Dedup) -------------------------------------------------------


@pytest.fixture()
def ctx(tmp_path):
    conn = connect(":memory:")
    init_schema(conn)
    settings = Settings(db_path=":memory:", artifacts_dir=str(tmp_path / "builds"))
    return conn, settings


def test_autopilot_pickt_und_baut(ctx, tmp_path):
    conn, settings = ctx
    feed = tmp_path / "jobs.json"
    feed.write_text(
        json.dumps(
            [
                {"id": "j1", "title": "RAG-Service", "tags": ["rag"]},
                {"id": "j2", "title": "API-Gateway", "tags": ["api"]},
            ]
        ),
        encoding="utf-8",
    )

    summary = run_once(conn, settings, [FeedSource(str(feed))])
    assert len(summary["picked"]) == 2 and summary["skipped"] == 0
    assert len(list_jobs(conn)) == 2
    # Artefakte real erzeugt
    for p in summary["picked"]:
        assert os.path.isfile(os.path.join(p["artifact"], "run.py"))


def test_autopilot_dedupliziert(ctx, tmp_path):
    conn, settings = ctx
    feed = tmp_path / "jobs.json"
    feed.write_text(json.dumps([{"id": "j1", "title": "RAG", "tags": ["rag"]}]), encoding="utf-8")
    src = FeedSource(str(feed))

    first = run_once(conn, settings, [src])
    second = run_once(conn, settings, [src])  # gleiche Quelle erneut
    assert len(first["picked"]) == 1
    assert second["picked"] == [] and second["skipped"] == 1
    assert len(list_jobs(conn)) == 1  # kein Doppel-Ingest


def test_autopilot_ueberlebt_kaputte_quelle(ctx):
    conn, settings = ctx

    class Broken:
        name = "broken"

        def poll(self):
            raise RuntimeError("Quelle down")

    summary = run_once(conn, settings, [Broken()])
    assert summary["errors"] and summary["errors"][0]["source"] == "broken"


# --- Container-Ziel ----------------------------------------------------------


def test_artefakt_ist_container_ready(tmp_path):
    job = Job(id="job:x", title="T", tags=["rag"])
    b = Build(id="build:abc", job_id=job.id, modules=["rag-grounded", "sqlite-store"])
    art_dir, _ = materialize(b, job, str(tmp_path))
    assert os.path.isfile(os.path.join(art_dir, "Dockerfile"))
    assert os.path.isfile(os.path.join(art_dir, "fly.toml"))
    fly = open(os.path.join(art_dir, "fly.toml"), encoding="utf-8").read()
    assert "arena-build-abc" in fly and "/health" in fly


# --- Gateway (echter Boot, Multi-Build-Routing) ------------------------------


def test_gateway_routet_zu_builds(tmp_path):
    db = str(tmp_path / "arena.db")
    settings = Settings(db_path=db, artifacts_dir=str(tmp_path / "builds"))
    conn = connect(db)
    init_schema(conn)
    from arena.models import Result

    run_match(
        conn,
        Job(id="job:1", title="RAG-Service", tags=["rag"]),
        settings,
        result=Result.WIN,
        revenue=1500,
    )
    run_match(conn, Job(id="job:2", title="API-Tool", tags=["api"]), settings)

    builds = deployed_builds(conn)
    assert len(builds) == 2

    httpd, port = create_server(settings, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        api = json.loads(urllib.request.urlopen(base + "/api/builds", timeout=3).read())
        assert len(api) == 2
        target = api[0]["url_id"]

        health = json.loads(urllib.request.urlopen(f"{base}/b/{target}/health", timeout=3).read())
        assert health["status"] == "ok"

        # eine echte Capability dieses Builds ausfuehren
        man = json.loads(urllib.request.urlopen(f"{base}/b/{target}/manifest", timeout=3).read())
        some_cap = man["modules"][0]
        cap = json.loads(
            urllib.request.urlopen(f"{base}/b/{target}/cap/{some_cap}", timeout=3).read()
        )
        assert cap["cap"] == some_cap and "result" in cap

        lobby = urllib.request.urlopen(base + "/", timeout=3).read().decode("utf-8")
        assert "Lobby" in lobby and "1500" in lobby  # Revenue in der Lobby
    finally:
        httpd.shutdown()
