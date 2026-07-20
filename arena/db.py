"""SQLite-Persistenz: Kern-Entitaeten + Knowledge-Graph in EINER Datei.

Nur stdlib `sqlite3` — der Kern braucht ausser pydantic keine Deps. WAL-Modus
fuer parallele Reads; ein File, triviales Backup.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',   -- JSON-Array
    budget      REAL,
    status      TEXT NOT NULL,
    external_id TEXT,                 -- stabile ID der Quelle (Dedup)
    source      TEXT,                 -- woher der Job kam (feed|dir|webhook|imap|cli)
    created_at  TEXT NOT NULL
);

-- Dedup-Register: welche externen Jobs schon aufgenommen wurden.
CREATE TABLE IF NOT EXISTS seen (
    external_id TEXT PRIMARY KEY,
    source      TEXT,
    job_id      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS builds (
    id            TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES jobs(id),
    spec          TEXT DEFAULT '',
    modules       TEXT DEFAULT '[]',  -- JSON-Array
    artifact_path TEXT,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    id         TEXT PRIMARY KEY,
    build_id   TEXT NOT NULL REFERENCES builds(id),
    job_id     TEXT NOT NULL REFERENCES jobs(id),
    result     TEXT NOT NULL,
    revenue    REAL DEFAULT 0,
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

-- Knowledge-Graph -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id    TEXT PRIMARY KEY,
    type  TEXT NOT NULL,
    label TEXT DEFAULT '',
    props TEXT DEFAULT '{}'   -- JSON-Objekt
);

CREATE TABLE IF NOT EXISTS edges (
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    rel    TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    props  TEXT DEFAULT '{}',
    PRIMARY KEY (src, dst, rel)
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, rel);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, rel);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Verbindung mit WAL + Foreign Keys; legt Verzeichnis bei Bedarf an.

    `:memory:` wird durchgereicht (fuer Tests), ohne Verzeichnis-Anlage.
    """
    if db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotente Leichtmigration: fehlende Spalten an bestehende DBs anfuegen."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "external_id" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN external_id TEXT")
    if "source" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT")


# --- kleine JSON-Helfer, damit Listen/Dicts sauber rein/raus gehen ----------


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: Optional[str], default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
