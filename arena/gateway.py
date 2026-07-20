"""Arena-Gateway (v0.3): ein Prozess serviert ALLE deployten Builds.

Jeder Build bekommt eine eigene URL — `/b/<build>/...` — routet in dessen
Capabilities. `/` ist die Lobby (Uebersicht aller Builds + Revenue-Bilanz).
Das ist die Local-first-Antwort auf "eine Subdomain je Build", ohne dass man
je Build einen eigenen Prozess/Container braucht.

Liest den Zustand bei jeder Anfrage frisch aus der DB — neu deployte Builds
tauchen sofort auf. Caps werden pro Artefakt-Verzeichnis gecacht.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

from .config import Settings
from .db import connect, init_schema, loads

_CAP_CACHE: Dict[str, Dict[str, Any]] = {}


def deployed_builds(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Alle live/gescoreten Builds mit Jobtitel, Modulen und (falls) Revenue."""
    rows = conn.execute(
        "SELECT b.id AS build_id, b.artifact_path, b.modules, b.status, "
        "j.title AS title, "
        "(SELECT o.result FROM outcomes o WHERE o.build_id = b.id ORDER BY o.created_at DESC LIMIT 1) AS result, "
        "(SELECT COALESCE(SUM(o.revenue),0) FROM outcomes o WHERE o.build_id = b.id) AS revenue "
        "FROM builds b JOIN jobs j ON j.id = b.job_id "
        "WHERE b.artifact_path IS NOT NULL AND b.status IN ('DEPLOYED','SCORED') "
        "ORDER BY b.created_at DESC"
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        art = r["artifact_path"]
        out.append(
            {
                "build_id": r["build_id"],
                "url_id": os.path.basename(art.rstrip("/")) if art else "",
                "artifact_path": art,
                "title": r["title"],
                "modules": loads(r["modules"], []),
                "status": r["status"],
                "result": r["result"],
                "revenue": float(r["revenue"] or 0.0),
            }
        )
    return out


def _load_caps(artifact_path: str) -> Dict[str, Any]:
    if artifact_path in _CAP_CACHE:
        return _CAP_CACHE[artifact_path]
    caps: Dict[str, Any] = {}
    capdir = os.path.join(artifact_path, "caps")
    if os.path.isdir(capdir):
        for fname in sorted(os.listdir(capdir)):
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            path = os.path.join(capdir, fname)
            spec = importlib.util.spec_from_file_location(
                f"gw_{os.path.basename(artifact_path)}_{fname[:-3]}", path
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            caps[getattr(mod, "NAME", fname[:-3])] = mod
    _CAP_CACHE[artifact_path] = caps
    return caps


def _find(builds: List[Dict[str, Any]], url_id: str) -> Dict[str, Any] | None:
    for b in builds:
        if b["url_id"] == url_id or b["build_id"] == url_id:
            return b
    return None


def _lobby_html(builds: List[Dict[str, Any]], revenue: float) -> str:
    cards = []
    for b in builds:
        badge = {"WIN": "🟢 WIN", "LOSS": "🔴 LOSS"}.get(b["result"] or "", "🟡 live")
        rev = f" · {b['revenue']:.0f} €" if b["revenue"] else ""
        mods = ", ".join(b["modules"])
        cards.append(
            f'<div class="card"><div class="row"><b>{b["title"]}</b>'
            f'<span class="badge">{badge}{rev}</span></div>'
            f'<div class="mods">{mods}</div>'
            f'<div class="links"><a href="/b/{b["url_id"]}/">öffnen</a> · '
            f'<a href="/b/{b["url_id"]}/manifest">manifest</a> · '
            f'<a href="/b/{b["url_id"]}/health">health</a></div></div>'
        )
    body = "".join(cards) or '<p class="empty">Noch keine Builds deployt.</p>'
    return f"""<!doctype html><meta charset="utf-8"><title>VPS-Arena Lobby</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;background:#0f1117;color:#e6e6e6}}
 h1{{font-size:1.5rem;margin-bottom:.2rem}} .sub{{color:#8aa;margin-top:0}}
 .card{{border:1px solid #223;border-radius:10px;padding:.8rem 1rem;margin:.6rem 0;background:#151a24}}
 .row{{display:flex;justify-content:space-between;align-items:center;gap:1rem}}
 .badge{{font-size:.85rem;color:#bcd;white-space:nowrap}} .mods{{color:#7fb;font-size:.85rem;margin:.3rem 0}}
 .links a{{color:#6cf;text-decoration:none;font-size:.85rem}} .empty{{color:#889}}
 a{{color:#6cf}}
</style>
<h1>🎮 VPS-Arena — Lobby</h1>
<p class="sub">{len(builds)} Build(s) live · Gesamt-Revenue <b>{revenue:.0f} €</b></p>
{body}
"""


class _Handler(BaseHTTPRequestHandler):
    settings: Settings  # gesetzt in create_server

    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _conn(self) -> sqlite3.Connection:
        conn = connect(self.settings.db_path)
        init_schema(conn)
        return conn

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler-API)
        path = self.path.split("?")[0]
        conn = self._conn()
        try:
            builds = deployed_builds(conn)
            from .loop import revenue_summary

            total = revenue_summary(conn)["revenue"]
        finally:
            conn.close()

        if path == "/":
            return self._send(200, _lobby_html(builds, total), "text/html; charset=utf-8")
        if path == "/api/builds":
            return self._send(200, json.dumps(builds, ensure_ascii=False))

        if path.startswith("/b/"):
            rest = path[len("/b/") :]
            url_id, _, tail = rest.partition("/")
            b = _find(builds, url_id)
            if b is None:
                return self._send(404, json.dumps({"error": "unknown build", "id": url_id}))
            return self._serve_build(b, "/" + tail)

        return self._send(404, json.dumps({"error": "not found", "path": path}))

    def _serve_build(self, b: Dict[str, Any], tail: str) -> None:
        art = b["artifact_path"]
        if tail == "/health":
            return self._send(200, json.dumps({"status": "ok", "build": b["build_id"]}))
        if tail == "/manifest":
            mpath = os.path.join(art, "manifest.json")
            if os.path.isfile(mpath):
                with open(mpath, encoding="utf-8") as fh:
                    return self._send(200, fh.read())
            return self._send(404, json.dumps({"error": "no manifest"}))
        if tail.startswith("/cap/"):
            name = tail[len("/cap/") :]
            mod = _load_caps(art).get(name)
            if mod is None:
                return self._send(404, json.dumps({"error": "unknown cap", "cap": name}))
            try:
                result = mod.run()
            except Exception as exc:
                return self._send(500, json.dumps({"cap": name, "error": str(exc)}))
            return self._send(200, json.dumps({"cap": name, "result": result}, ensure_ascii=False))
        if tail in ("/", ""):
            idx = os.path.join(art, "static", "index.html")
            if os.path.isfile(idx):
                with open(idx, "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            caps = ", ".join(sorted(_load_caps(art))) or "(keine)"
            html = f"<h1>{b['title']}</h1><p>Build {b['build_id']}</p><p>Caps: {caps}</p>"
            return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found", "path": tail}))

    def log_message(self, *args: Any) -> None:
        pass


def create_server(settings: Settings, port: int = 0):
    """Baut den Gateway-Server. Rueckgabe (httpd, port). Port 0 = ephemer."""
    resolved = int(os.environ.get("PORT", port))
    handler = type("BoundHandler", (_Handler,), {"settings": settings})
    httpd = ThreadingHTTPServer(("127.0.0.1", resolved), handler)
    return httpd, httpd.server_address[1]


def serve(settings: Settings, port: int = 8080) -> None:  # pragma: no cover - CLI-Pfad
    httpd, bound = create_server(settings, port)
    print(f"[arena-gateway] Lobby auf http://127.0.0.1:{bound}  (DB: {settings.db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
