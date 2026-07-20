# BLUEPRINT — VPS-Arena

Architektonische Wahrheit dieses Repos. Bei Konflikt gilt dieses Dokument.

## 1. Idee in einem Satz

Ein autonomer Agent auf einem VPS generiert Software-Builds, die um Jobs und
Revenue antreten; ein Knowledge-Graph sammelt, was gewinnt, und macht jeden
nächsten Build besser. **Local-first, offline-fähig, kein Cloud-LLM-Zwang.**

## 2. Das Fortnite-Mentalmodell

| Fortnite | VPS-Arena | Im Code |
|---|---|---|
| Build | generiertes/deploytes Artefakt | `models.Build` |
| Arena / Match | Job-Markt, Opportunity | `models.Job` |
| Loot & XP | Knowledge-Graph (Evidenz) | `graph.py`, `nodes`/`edges` |
| Survival | Revenue > Kosten | `models.Outcome.revenue` |
| Storm | Zeit-/Marktdruck | (Roadmap: Scheduler) |

## 3. Datenmodell (Pydantic = Vertrag)

`models.py` ist die single source of truth. Änderungen dort **zuerst**, dann
`db`/`graph`/`loop` nachziehen.

- **Job** `{id, title, description, tags[], budget?, status, created_at}`
- **Build** `{id, job_id, spec, modules[], artifact_path?, status, created_at}`
- **Outcome** `{id, build_id, job_id, result(WIN|LOSS), revenue, notes}`
- **Node** `{id, type(job|build|module|tag|outcome), label, props}`
- **Edge** `{src, dst, rel, weight, props}`

## 4. Der Graph (in SQLite)

Kein separater Graph-Server — Knoten/Kanten liegen als zwei Tabellen in derselben
SQLite-DB. Eine DB, ein Backup, null Ops.

**Kantentypen:**

```
job  --tagged-->   tag
job  --produced--> build
build --uses-->    module
build --won-->     outcome        (bzw. --lost-->)
```

**Kern-Query** (`graph.recommend_modules`): Für einen neuen Job mit Tags T findet
der Graph ähnliche alte Jobs (Tag-Überlappung ≥ `min_tag_overlap`), verfolgt
`job → build → module` und gewichtet jeden Baustein mit den `won`/`lost`-Kanten
seiner Builds. Ergebnis: gerankte Bausteinliste. **Deterministisch, testbar,
kein LLM.**

Kanten akkumulieren Gewicht (`ON CONFLICT … weight = weight + …`) — je öfter eine
Evidenz auftritt, desto stärker.

## 5. Invarianten — nicht brechen

1. **Der Graph/Code entscheidet, das LLM schlägt nur vor.** Bausteinwahl und
   Scoring sind regelbasiert (`graph.py`, `agent.choose_modules`). Das LLM
   (`agent._ollama_spec`) formuliert **nur die Spec-Prosa**, nie die Entscheidung.
2. **Immer offline lauffähig.** Ohne Ollama → deterministischer Mock. Jeder
   LLM-Fehler fällt still auf den Mock zurück. Kern-Deps = nur `pydantic`.
3. **Eine SQLite-DB für alles** (Entitäten + Graph). Kein externer Store in v1.
4. **Tuning zentral** in `config.py` (Präfix `ARENA_`) — keine Magic Numbers
   verstreuen.
5. **Laufzeitdaten nie committen** — `data/`, `builds/`, `*.db`, `.env` sind in
   `.gitignore`.

## 6. Module & Herkunft (Wiederverwendung statt Neuerfindung)

Der Baustein-Kanon (`agent.KNOWN_MODULES`) spiegelt bewährte Teile des
Rawkeep-Ökosystems — hier sollen echte Portierungen andocken:

| Baustein | Quelle |
|---|---|
| `rag-grounded` | `grounded-rag` (Halluzinations-Abwehr, Gates) |
| `sqlite-store` | `grounded-rag` / `RAQ` (better-sqlite3 / aiosqlite) |
| `ollama-client` | `orgmind` / `formulation-ai` |
| `auth-jwt`, `rate-limit` | `RAQ` (`api/server.js`) |
| `react-dashboard` | `RAQ` (`react/`), `BrokerPilot` |
| `langgraph-agents` | `BrokerPilot` |
| `data-firewall` | `RAQ` (DLP-light) |
| `pdf-export` | `sap-agent` / `orgmind` |

## 7. Roadmap

- **v0.1 (jetzt)** — Datenmodell, Graph, Match-Loop, CLI, Demo, Tests. ✅
- **v0.2** — echter Deploy-Schritt (Container/Fly-Subdomain je Build);
  Artefakt-Templating aus `modules[]`.
- **v0.3** — Ingest-Quellen (IMAP/Webhook/Formular) → autonomes Job-Picking.
- **v0.4** — Scheduler/„Storm" (Zeitdruck-Loop), Revenue-Ledger + Kosten
  (VPS + Token) → echte Survival-Bilanz.
- **v0.5** — HTTP-API + kleines Dashboard (CDN-frei, vanilla), Multi-Agent
  (LangGraph) für parallele Builds.

## 8. VPS-Deployment (Zielbild)

Ein Prozess, eine SQLite-Datei auf persistentem Volume. Systemd-Service +
Ollama daneben. Kein externer Egress außer bewusst konfigurierten Job-Quellen.
Backup = Kopie der `.db`. Details folgen mit v0.2/v0.4.
