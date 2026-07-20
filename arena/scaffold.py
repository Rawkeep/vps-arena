"""Artefakt-Materialisierung (v0.2): aus `modules[]` echte, startbare Dateien.

Ein Build wird kein Stub-Pfad mehr, sondern ein Verzeichnis mit lauffaehigem
Code — ein zero-dependency stdlib-HTTP-Service, der pro Baustein eine echte
Capability unter `/cap/<name>` bereitstellt. Startbar mit `python run.py`.

Bewusst nur stdlib im *generierten* Artefakt: es soll auf jedem VPS ohne
`pip install` sofort laufen (Local-first).
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from .models import ArtifactManifest, Build, Job

# --- Capability-Templates: Baustein -> vollstaendige Python-Modul-Quelle -----
# Jede Cap exponiert NAME, SUMMARY und run() -> dict. run.py laedt sie dynamisch.

CAP_TEMPLATES: Dict[str, str] = {
    "sqlite-store": '''"""Local-first Persistenz via SQLite (stdlib)."""
NAME = "sqlite-store"
SUMMARY = "Local-first Persistenz via SQLite (stdlib)."


def run():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t(x INTEGER)")
    conn.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(3)])
    rows = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    return {"engine": "sqlite", "rows": rows, "ok": True}
''',
    "data-firewall": '''"""DLP-light: redigiert PII (Mail/Telefon) vor Egress."""
import re

NAME = "data-firewall"
SUMMARY = "DLP-light: redigiert PII (Mail/Telefon) vor Egress."

_EMAIL = re.compile(r"[\\w.+-]+@[\\w-]+\\.[\\w.-]+")
_PHONE = re.compile(r"\\+?\\d[\\d /-]{6,}\\d")


def run():
    sample = "Kontakt: max@example.com, +49 221 1234567"
    redacted = _PHONE.sub("[TEL]", _EMAIL.sub("[MAIL]", sample))
    return {"input": sample, "redacted": redacted}
''',
    "rag-grounded": '''"""Quellen-verifizierte Antwort oder Verweigerung (kein Halluzinieren)."""
NAME = "rag-grounded"
SUMMARY = "Quellen-verifizierte Antwort oder Verweigerung."

_CORPUS = [
    "VPS-Arena generiert Software-Builds fuer Jobs und Revenue.",
    "Der Knowledge-Graph lernt aus jedem Match, welche Bausteine gewinnen.",
]


def run(query="Was generiert VPS-Arena?"):
    terms = [w for w in query.lower().replace("?", " ").split() if len(w) > 3]
    for sentence in _CORPUS:
        low = sentence.lower()
        if any(t in low for t in terms):
            return {"query": query, "answer": sentence, "grounded": True}
    return {"query": query, "answer": None, "grounded": False, "status": "REFUSED"}
''',
    "ollama-client": '''"""Bindung an lokales LLM (Ollama); offline-tolerant."""
import json
import os
import urllib.request

NAME = "ollama-client"
SUMMARY = "Bindung an lokales LLM (Ollama); offline-tolerant."


def run():
    url = os.environ.get("ARENA_OLLAMA_URL", "http://localhost:11434")
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", [])]
        return {"online": True, "url": url, "models": models}
    except Exception:
        return {"online": False, "url": url, "note": "offline -> Mock-Fallback"}
''',
    "auth-jwt": '''"""HS256-JWT ausstellen (stdlib hmac, keine Dep)."""
import base64
import hashlib
import hmac
import json

NAME = "auth-jwt"
SUMMARY = "HS256-JWT ausstellen (stdlib hmac)."

_SECRET = b"arena-demo-secret-nur-lokal"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def run(sub="agent"):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload = _b64(json.dumps({"sub": sub, "role": "builder"}).encode("utf-8"))
    signing = header + b"." + payload
    sig = _b64(hmac.new(_SECRET, signing, hashlib.sha256).digest())
    return {"token": (signing + b"." + sig).decode("utf-8"), "sub": sub}
''',
    "rate-limit": '''"""Token-Bucket-Drossel (stdlib)."""
NAME = "rate-limit"
SUMMARY = "Token-Bucket-Drossel (stdlib)."


def run():
    capacity = 5
    tokens = capacity
    allowed = blocked = 0
    for _ in range(8):
        if tokens > 0:
            tokens -= 1
            allowed += 1
        else:
            blocked += 1
    return {"capacity": capacity, "allowed": allowed, "blocked": blocked}
''',
    "pdf-export": '''"""Minimales, valides PDF erzeugen (stdlib, keine Dep)."""
NAME = "pdf-export"
SUMMARY = "Minimales, valides PDF erzeugen."


def run():
    pdf = (
        b"%PDF-1.4\\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]>>endobj\\n"
        b"trailer<</Root 1 0 R>>\\n%%EOF"
    )
    return {"bytes": len(pdf), "format": "application/pdf"}
''',
    "express-api": '''"""HTTP-API-Schicht (im Python-Artefakt via stdlib gespiegelt)."""
NAME = "express-api"
SUMMARY = "HTTP-API-Schicht (stdlib-Spiegel; Node-Port geplant)."


def run():
    return {
        "routes": ["/health", "/manifest", "/cap/<name>"],
        "stack": "stdlib-http",
        "note": "Express/Node-Port fuer JS-Stack geplant (Roadmap)",
    }
''',
    "langgraph-agents": '''"""Multi-Agent-Orchestrierung (Platzhalter fuer LangGraph-Port)."""
NAME = "langgraph-agents"
SUMMARY = "Multi-Agent-Orchestrierung (LangGraph-Port geplant)."


def run():
    return {"agents": ["scout", "builder", "scorer"], "note": "LangGraph-Graph geplant (v0.5)"}
''',
    "react-dashboard": '''"""Statisches Dashboard (CDN-frei) unter / ."""
NAME = "react-dashboard"
SUMMARY = "Statisches Dashboard (CDN-frei) unter / ."


def run():
    return {"ui": "/", "note": "statisches index.html im Artefakt"}
''',
}


def _generic_cap(name: str) -> str:
    safe = name.replace('"', "'")
    return (
        f'"""Platzhalter-Capability fuer {safe} (kein Template)."""\n'
        f'NAME = "{safe}"\n'
        f'SUMMARY = "Platzhalter — noch kein Template."\n\n\n'
        f"def run():\n"
        f'    return {{"module": "{safe}", "note": "kein Template - Platzhalter"}}\n'
    )


# --- Der startbare Service (run.py) -----------------------------------------

RUN_PY = '''#!/usr/bin/env python3
"""Generiertes Artefakt — startbarer, zero-dependency Service (stdlib).

    python run.py            # startet auf MANIFEST.port (env PORT ueberschreibt)

Routen:
    GET /health        -> {"status":"ok", ...}
    GET /manifest      -> das Artefakt-Manifest
    GET /              -> Dashboard (static/index.html) oder Info-Seite
    GET /cap/<name>    -> fuehrt die Capability <name> aus, liefert deren Ergebnis
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = pathlib.Path(__file__).resolve().parent
MANIFEST = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))


def _load_caps():
    caps = {}
    capdir = BASE / "caps"
    if not capdir.is_dir():
        return caps
    for f in sorted(capdir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location("cap_" + f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        caps[getattr(mod, "NAME", f.stem)] = mod
    return caps


CAPS = _load_caps()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, json.dumps({"status": "ok", "build": MANIFEST["build_id"]}))
        if path == "/manifest":
            return self._send(200, json.dumps(MANIFEST, ensure_ascii=False))
        if path.startswith("/cap/"):
            name = path[len("/cap/"):]
            mod = CAPS.get(name)
            if mod is None:
                return self._send(404, json.dumps({"error": "unknown cap", "cap": name}))
            try:
                result = mod.run()
            except Exception as exc:  # Capability-Fehler nie den Service killen
                return self._send(500, json.dumps({"cap": name, "error": str(exc)}))
            return self._send(200, json.dumps({"cap": name, "result": result}, ensure_ascii=False))
        if path == "/":
            idx = BASE / "static" / "index.html"
            if idx.exists():
                return self._send(200, idx.read_bytes(), "text/html; charset=utf-8")
            caps = ", ".join(sorted(CAPS)) or "(keine)"
            html = (
                "<h1>" + MANIFEST["title"] + "</h1>"
                "<p>Build " + MANIFEST["build_id"] + "</p>"
                "<p>Capabilities: " + caps + "</p>"
                "<p>Probiere <code>/cap/&lt;name&gt;</code> oder <code>/manifest</code>.</p>"
            )
            return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found", "path": path}))

    def log_message(self, *args):
        pass  # ruhig halten


def create_server(port=None):
    resolved = os.environ.get("PORT", port if port is not None else MANIFEST.get("port", 8080))
    httpd = ThreadingHTTPServer(("127.0.0.1", int(resolved)), Handler)
    return httpd, httpd.server_address[1]


def serve():
    httpd, port = create_server()
    print("[arena-build " + MANIFEST["build_id"] + "] laeuft auf http://127.0.0.1:" + str(port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve()
'''

INDEX_HTML = """<!doctype html>
<meta charset="utf-8">
<title>VPS-Arena Build</title>
<style>
  body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;background:#0f1117;color:#e6e6e6}
  h1{font-size:1.4rem} code{background:#1c2030;padding:.1rem .3rem;border-radius:4px}
  .cap{border:1px solid #263;border-radius:8px;padding:.6rem .8rem;margin:.5rem 0;background:#151a24}
  button{cursor:pointer;background:#2b6;color:#04120a;border:0;border-radius:6px;padding:.3rem .7rem}
  pre{white-space:pre-wrap;word-break:break-word;color:#9fd}
</style>
<h1>🎮 VPS-Arena Build</h1>
<p id="meta">lade Manifest ...</p>
<div id="caps"></div>
<script>
async function j(u){const r=await fetch(u);return r.json()}
(async()=>{
  const m=await j("/manifest");
  document.getElementById("meta").innerHTML =
    "<b>"+m.title+"</b><br>Build "+m.build_id+" &middot; Stack "+m.stack+
    " &middot; Module: "+m.modules.join(", ");
  const box=document.getElementById("caps");
  for(const name of m.modules){
    const d=document.createElement("div");d.className="cap";
    d.innerHTML="<code>/cap/"+name+"</code> <button>run</button><pre></pre>";
    const pre=d.querySelector("pre");
    d.querySelector("button").onclick=async()=>{
      pre.textContent="...";
      try{pre.textContent=JSON.stringify((await j("/cap/"+name)).result,null,2)}
      catch(e){pre.textContent="Fehler: "+e}
    };
    box.appendChild(d);
  }
})();
</script>
"""


DOCKERFILE = """# Generiertes Artefakt — zero-dependency stdlib-Service.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV PORT=8080
EXPOSE 8080
CMD ["python", "run.py"]
"""

FLY_TOML = """# Fly.io-Deploy des Build-Artefakts (eine Subdomain je Build).
app = "{app}"
primary_region = "fra"

[build]

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[http_service.checks]]
  path = "/health"
  interval = "30s"
  timeout = "5s"
"""


def materialize(build: Build, job: Job, out_root: str) -> Tuple[str, ArtifactManifest]:
    """Schreibt ein startbares Artefakt-Verzeichnis und liefert (pfad, manifest)."""
    art_dir = os.path.join(out_root, build.id.replace(":", "_"))
    caps_dir = os.path.join(art_dir, "caps")
    os.makedirs(caps_dir, exist_ok=True)

    files: List[str] = []

    # Capabilities pro Baustein
    for mod in build.modules:
        code = CAP_TEMPLATES.get(mod, _generic_cap(mod))
        rel = os.path.join("caps", mod + ".py")
        _write(art_dir, rel, code)
        files.append(rel)
    _write(art_dir, os.path.join("caps", "__init__.py"), "")
    files.append(os.path.join("caps", "__init__.py"))

    # Dashboard nur, wenn ein Frontend-Baustein dabei ist
    if "react-dashboard" in build.modules:
        _write(art_dir, os.path.join("static", "index.html"), INDEX_HTML)
        files.append(os.path.join("static", "index.html"))

    # Service-Entrypoint
    _write(art_dir, "run.py", RUN_PY)
    files.append("run.py")

    # Container-/Deploy-Ziel (v0.3): zero-dep Artefakt -> winziges Image.
    _write(art_dir, "Dockerfile", DOCKERFILE)
    _write(art_dir, ".dockerignore", "__pycache__/\n*.pyc\n*.db*\n")
    fly_app = "arena-" + build.id.replace(":", "-").replace("_", "-").lower()
    _write(art_dir, "fly.toml", FLY_TOML.format(app=fly_app))
    files.extend(["Dockerfile", ".dockerignore", "fly.toml"])

    manifest = ArtifactManifest(
        build_id=build.id,
        job_id=job.id,
        title=job.title,
        modules=list(build.modules),
        files=sorted(files),
    )
    _write(
        art_dir, "manifest.json", json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2)
    )

    readme = (
        f"# Build-Artefakt: {job.title}\n\n"
        f"Generiert von VPS-Arena (Build `{build.id}`). Zero-dependency stdlib-Service.\n\n"
        f"## Start\n\n```bash\npython run.py        # oder: PORT=9000 python run.py\n```\n\n"
        f"## Bausteine\n\n" + "".join(f"- `{m}`\n" for m in build.modules) + "\n"
        f"## Spec\n\n{build.spec}\n"
    )
    _write(art_dir, "README.md", readme)

    return art_dir, manifest


def _write(base: str, rel: str, content: str) -> None:
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
