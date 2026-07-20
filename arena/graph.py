"""Knowledge-Graph-Operationen ueber der SQLite-Ablage.

Kern-IP: `recommend_modules` — "welche Bausteine haben bei aehnlichen Jobs
gewonnen?". Deterministisch, regelbasiert, testbar. Kein LLM in dieser Datei.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List

from .config import Settings
from .db import dumps, loads
from .models import Edge, MatchResult, ModuleScore, Node


def upsert_node(conn: sqlite3.Connection, node: Node) -> None:
    conn.execute(
        "INSERT INTO nodes(id, type, label, props) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET label=excluded.label, props=excluded.props",
        (node.id, node.type.value, node.label, dumps(node.props)),
    )


def upsert_edge(conn: sqlite3.Connection, edge: Edge) -> None:
    """Kante einfuegen; bei Wiederholung Gewicht akkumulieren (Evidenz waechst)."""
    conn.execute(
        "INSERT INTO edges(src, dst, rel, weight, props) VALUES (?,?,?,?,?) "
        "ON CONFLICT(src, dst, rel) DO UPDATE SET weight = weight + excluded.weight",
        (edge.src, edge.dst, edge.rel, edge.weight, dumps(edge.props)),
    )


def neighbors(
    conn: sqlite3.Connection, node_id: str, rel: str, outgoing: bool = True
) -> List[str]:
    if outgoing:
        rows = conn.execute(
            "SELECT dst FROM edges WHERE src = ? AND rel = ?", (node_id, rel)
        ).fetchall()
        return [r[0] for r in rows]
    rows = conn.execute(
        "SELECT src FROM edges WHERE dst = ? AND rel = ?", (node_id, rel)
    ).fetchall()
    return [r[0] for r in rows]


def similar_jobs(conn: sqlite3.Connection, tags: List[str], settings: Settings) -> List[str]:
    """Alte Jobs mit ausreichender Tag-Ueberlappung zu den gegebenen Tags."""
    if not tags:
        return []
    tag_nodes = [f"tag:{t.lower()}" for t in tags]
    counts: Dict[str, int] = {}
    for tag_id in tag_nodes:
        # tag <--tagged-- job  (Kante: job --tagged--> tag)
        for job_id in neighbors(conn, tag_id, "tagged", outgoing=False):
            counts[job_id] = counts.get(job_id, 0) + 1
    return [j for j, c in counts.items() if c >= settings.min_tag_overlap]


def recommend_modules(
    conn: sqlite3.Connection, tags: List[str], settings: Settings
) -> MatchResult:
    """Aus gewonnenen aehnlichen Jobs die erfolgreichsten Bausteine ableiten.

    Pfad im Graph:  job --produced--> build --uses--> module
                    build --won/lost--> outcome
    Sieg erhoeht den Score (win_weight), Niederlage senkt ihn (loss_penalty).
    """
    sims = similar_jobs(conn, tags, settings)
    agg: Dict[str, ModuleScore] = {}

    for job_id in sims:
        for build_id in neighbors(conn, job_id, "produced", outgoing=True):
            modules = neighbors(conn, build_id, "uses", outgoing=True)
            won = bool(neighbors(conn, build_id, "won", outgoing=True))
            lost = bool(neighbors(conn, build_id, "lost", outgoing=True))
            for mod in modules:
                name = mod[len("module:"):] if mod.startswith("module:") else mod
                sc = agg.setdefault(name, ModuleScore(module=name, score=0.0))
                if won:
                    sc.score += settings.win_weight
                    sc.wins += 1
                elif lost:
                    sc.score -= settings.loss_penalty
                    sc.losses += 1

    ranked = sorted(agg.values(), key=lambda m: m.score, reverse=True)
    return MatchResult(job_id="", recommended_modules=ranked, similar_jobs=sims)


def stats(conn: sqlite3.Connection) -> Dict[str, int]:
    def _count(table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    return {
        "nodes": _count("nodes"),
        "edges": _count("edges"),
        "jobs": _count("jobs"),
        "builds": _count("builds"),
        "outcomes": _count("outcomes"),
    }


def get_node(conn: sqlite3.Connection, node_id: str) -> Node | None:
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    props = loads(row["props"], {})
    return Node(id=row["id"], type=row["type"], label=row["label"], props=props)  # type: ignore[arg-type]
