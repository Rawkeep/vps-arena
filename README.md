# VPS-Arena 🎮

**Always-on AI-Agent auf einem VPS, der Software on-demand generiert — jeder
generierte Build tritt um echte Jobs & Revenue an.** SQLite hält den Zustand,
ein Knowledge-Graph ist das Gedächtnis, das aus jedem „Match" lernt. Local-first,
DSGVO-bewusst, Ollama statt Cloud-LLM.

> **Das Fortnite-Modell, ernst genommen:** ein *Build* ist ein generiertes
> Artefakt, die *Arena* ist der Job-Markt, *Loot & XP* ist der Graph (was hat
> gewonnen?), *Survival* heißt Revenue > Kosten. Der Agent wird mit jedem Match
> besser, statt bei jedem Auftrag bei null anzufangen.

## Warum VPS + SQLite + Graph

- **VPS** — 24/7 erreichbar, besitzt seine eigenen Daten, kann autonom Jobs
  picken und Builds fahren. Passt zur Local-first-/DSGVO-Linie (kein
  Cloud-LLM-Zwang).
- **SQLite** — ein File, WAL-Modus, triviales Backup. Jobs, Builds, Revenue und
  der komplette Graph liegen in **einer** DB. Kein Server-Overhead.
- **Knowledge-Graph (in SQLite)** — `Job → Build → Modul → Outcome`. Das
  Gedächtnis, das den nächsten Build datengetrieben besser macht.

## Der Match-Loop

```
1. INGEST   Job/Opportunity rein            (Mail, Formular, API)
2. MATCH    Graph fragen: was hat gewonnen? (bei ähnlichen Jobs)
3. BUILD    Agent generiert die Lösung      (Ollama, sonst Mock)
4. DEPLOY   Build geht live                 (Stub → echter Deploy)
5. SCORE    Outcome zurück in den Graph     (Revenue, win/loss)
   ↑______________ nächster Match, schlauer als vorher ______________|
```

## Quickstart

```bash
pip install -e ".[dev]"     # Kern braucht nur pydantic

python demo.py              # End-to-End ohne Ollama — zeigt das Lernen
python -m pytest -q         # Testsuite (Regressionsschutz fürs Kern-IP)

# CLI
arena init
arena run "RAG-Auftrag Kanzlei" --tags rag,dsgvo --win --revenue 4200
arena match "Neuer RAG-Job" --tags rag       # Empfehlung aus dem Graph
arena stats
```

### Deploy erzeugt echte Software (v0.2)

`arena run` deployt den Build zu einem **startbaren, zero-dependency Artefakt**
unter `builds/<id>/`. Jeder Baustein wird zu einer echten stdlib-Capability:

```bash
python builds/<id>/run.py          # startet den Service (http://127.0.0.1:8080)
curl localhost:8080/health
curl localhost:8080/cap/sqlite-store    # -> {"engine":"sqlite","rows":3,"ok":true}
curl localhost:8080/manifest
```

Ist ein Frontend-Baustein dabei, liegt unter `/` ein CDN-freies Dashboard.
Läuft auf jedem VPS ohne `pip install` — Local-first bis ins Artefakt. Jedes
Artefakt bringt außerdem `Dockerfile` + `fly.toml` mit (container-/Fly-ready).

### Autonom Jobs picken + alle Builds unter einer URL (v0.3)

Der Agent zieht Jobs selbst aus Quellen und baut sie ohne CLI-Eingabe:

```bash
# Feed (JSON-Liste) und/oder Inbox-Verzeichnis (*.json/*.md) pollen
arena autopilot --feed jobs.json --dir inbox/ --once     # ein Durchlauf
arena autopilot --feed jobs.json --interval 30           # Dauerbetrieb (VPS)
```

Bereits gesehene Jobs werden dedupliziert (stabile `external_id`). Quellen:
`FeedSource`, `DirSource`, `ImapSource` (stdlib `imaplib`, lazy). Gebaute Builds
landen im Status `DEPLOYED` und warten auf ein Outcome — Scoren ist ein echtes
Marktsignal, kein Automatismus:

```bash
arena ls                                  # deployte Builds + Survival-Bilanz
arena score build:<id> --win --revenue 4200
```

Das **Gateway** serviert alle deployten Builds aus **einem** Prozess, jeder unter
eigener URL — die Local-first-Antwort auf „eine Subdomain je Build":

```bash
arena gateway --port 8080
#  GET /                     -> Lobby (alle Builds + Revenue-Bilanz)
#  GET /api/builds           -> JSON
#  GET /b/<build>/health     -> pro-Build Health
#  GET /b/<build>/cap/<name> -> Capability dieses Builds ausführen
#  GET /b/<build>/           -> Dashboard/Info des Builds
```

### Lokales LLM (optional)

Standard ist ein deterministischer Mock — **nichts** braucht ein LLM zum Laufen.
Für echte LLM-Specs Ollama anschalten:

```bash
export ARENA_USE_OLLAMA=1
export ARENA_OLLAMA_MODEL=llama3.2:3b
```

Bei jedem Ollama-Fehler fällt der Agent still auf den Mock zurück. Die
**Bausteinwahl** bleibt immer datengetrieben (Graph) — das LLM formuliert nur
Prosa, es entscheidet nichts Hartes.

## Konfiguration (Präfix `ARENA_`)

| Variable | Default | Zweck |
|---|---|---|
| `ARENA_DB_PATH` | `data/arena.db` | Ablage der SQLite-DB |
| `ARENA_USE_OLLAMA` | `0` | LLM an/aus |
| `ARENA_OLLAMA_URL` | `http://localhost:11434` | Ollama-Endpunkt |
| `ARENA_OLLAMA_MODEL` | `llama3.2:3b` | Modell |

Tuning-Gewichte (`win_weight`, `loss_penalty`, `min_tag_overlap`) zentral in
`arena/config.py`.

## Auf einem eigenen VPS betreiben

Schritt-für-Schritt vom leeren Server bis zur laufenden Arena (Hetzner-Beispiel,
systemd-Dienste, optional Ollama/HTTPS/Backup): **[`SETUP.md`](./SETUP.md)**.

## Status

**v0.3** — Match-Loop + Knowledge-Graph + echter Deploy (startbare Artefakte) +
autonomes Job-Picking (Autopilot/Quellen) + Multi-Build-Gateway + Container-ready
+ Survival-Bilanz. 25 Tests grün, `demo.py` läuft ohne Ollama. Architektur und
Roadmap in [`BLUEPRINT.md`](./BLUEPRINT.md).
