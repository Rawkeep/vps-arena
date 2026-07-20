"""v0.2: Der Deploy-Schritt erzeugt ein echtes, startbares Artefakt."""

from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import threading
import urllib.request
import uuid

import pytest

from arena.models import Build, BuildStatus, Job
from arena.scaffold import CAP_TEMPLATES, materialize


def _job(tags):
    return Job(id=f"job:{uuid.uuid4().hex[:12]}", title="Test-Auftrag", tags=tags)


def _build(job, modules):
    return Build(id=f"build:{uuid.uuid4().hex[:12]}", job_id=job.id, modules=modules, spec="spec")


def test_materialize_legt_dateien_an(tmp_path):
    job = _job(["rag"])
    b = _build(job, ["sqlite-store", "rag-grounded"])
    art_dir, manifest = materialize(b, job, str(tmp_path))

    assert os.path.isfile(os.path.join(art_dir, "run.py"))
    assert os.path.isfile(os.path.join(art_dir, "manifest.json"))
    assert os.path.isfile(os.path.join(art_dir, "caps", "sqlite-store.py"))
    assert os.path.isfile(os.path.join(art_dir, "caps", "rag-grounded.py"))
    assert manifest.build_id == b.id
    assert set(manifest.modules) == {"sqlite-store", "rag-grounded"}


def test_manifest_ist_valides_json(tmp_path):
    job = _job(["api"])
    b = _build(job, ["express-api"])
    art_dir, _ = materialize(b, job, str(tmp_path))
    data = json.loads(open(os.path.join(art_dir, "manifest.json"), encoding="utf-8").read())
    assert data["stack"] == "python-service"
    assert data["entrypoint"] == "run.py"


def test_generierter_code_kompiliert(tmp_path):
    job = _job(["rag", "dashboard"])
    b = _build(job, list(CAP_TEMPLATES.keys()))  # alle Bausteine auf einmal
    art_dir, _ = materialize(b, job, str(tmp_path))
    for root, _dirs, files in os.walk(art_dir):
        for f in files:
            if f.endswith(".py"):
                py_compile.compile(os.path.join(root, f), doraise=True)


def test_dashboard_nur_mit_frontend_baustein(tmp_path):
    job = _job(["storage"])
    b = _build(job, ["sqlite-store"])
    art_dir, _ = materialize(b, job, str(tmp_path))
    assert not os.path.exists(os.path.join(art_dir, "static", "index.html"))

    b2 = _build(job, ["react-dashboard"])
    art_dir2, _ = materialize(b2, job, str(tmp_path))
    assert os.path.isfile(os.path.join(art_dir2, "static", "index.html"))


def _load_run(art_dir):
    spec = importlib.util.spec_from_file_location("gen_run", os.path.join(art_dir, "run.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_artefakt_startet_und_antwortet(tmp_path):
    """Der generierte Service bootet wirklich und liefert echte Cap-Ergebnisse."""
    job = _job(["storage"])
    b = _build(job, ["sqlite-store", "data-firewall"])
    art_dir, _ = materialize(b, job, str(tmp_path))

    run = _load_run(art_dir)
    httpd, port = run.create_server(0)  # ephemerer Port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        health = json.loads(urllib.request.urlopen(base + "/health", timeout=3).read())
        assert health["status"] == "ok"

        cap = json.loads(urllib.request.urlopen(base + "/cap/sqlite-store", timeout=3).read())
        assert cap["result"]["rows"] == 3 and cap["result"]["ok"] is True

        fw = json.loads(urllib.request.urlopen(base + "/cap/data-firewall", timeout=3).read())
        assert "[MAIL]" in fw["result"]["redacted"]
    finally:
        httpd.shutdown()


def test_unbekannter_baustein_bekommt_platzhalter(tmp_path):
    job = _job(["x"])
    b = _build(job, ["voellig-neuer-baustein"])
    art_dir, _ = materialize(b, job, str(tmp_path))
    assert os.path.isfile(os.path.join(art_dir, "caps", "voellig-neuer-baustein.py"))
    py_compile.compile(
        os.path.join(art_dir, "caps", "voellig-neuer-baustein.py"), doraise=True
    )
