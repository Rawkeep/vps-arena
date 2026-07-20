"""Datenmodell (Pydantic) = single source of truth.

Aenderungen hier zuerst, dann db/graph/loop nachziehen. Python-Felder snake_case.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    """ISO-Zeitstempel in UTC (naiv gehalten fuer stabile SQLite-Vergleiche)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


class JobStatus(str, Enum):
    OPEN = "OPEN"  # eingegangen, noch nicht bearbeitet
    MATCHED = "MATCHED"  # Graph befragt, Empfehlung liegt vor
    BUILT = "BUILT"  # Build erzeugt
    DEPLOYED = "DEPLOYED"  # Build ist live
    WON = "WON"  # Match gewonnen (Revenue)
    LOST = "LOST"  # Match verloren


class BuildStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPLOYED = "DEPLOYED"
    SCORED = "SCORED"


class Result(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"


# --- Kern-Entitaeten ---------------------------------------------------------


class Job(BaseModel):
    """Eine Opportunity/ein Auftrag, um den ein Build antritt ("Match")."""

    id: str
    title: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    budget: Optional[float] = None
    status: JobStatus = JobStatus.OPEN
    external_id: Optional[str] = None  # stabile ID der Quelle (Dedup)
    source: Optional[str] = None  # feed | dir | webhook | imap | cli
    created_at: str = Field(default_factory=_now)


class Build(BaseModel):
    """Ein generiertes Artefakt fuer genau einen Job (der "Build")."""

    id: str
    job_id: str
    spec: str = ""  # was gebaut wurde (Agent-Output)
    modules: List[str] = Field(default_factory=list)  # verwendete Bausteine
    artifact_path: Optional[str] = None
    status: BuildStatus = BuildStatus.DRAFT
    created_at: str = Field(default_factory=_now)


class Outcome(BaseModel):
    """Ergebnis eines Builds im Markt — fliesst zurueck in den Graph (XP/Loot)."""

    id: str
    build_id: str
    job_id: str
    result: Result
    revenue: float = 0.0
    notes: str = ""
    created_at: str = Field(default_factory=_now)


# --- Knowledge-Graph (in SQLite) --------------------------------------------


class NodeType(str, Enum):
    JOB = "job"
    BUILD = "build"
    MODULE = "module"
    TAG = "tag"
    OUTCOME = "outcome"


class Edge(BaseModel):
    """Gerichtete Kante: src --rel--> dst."""

    src: str
    dst: str
    rel: str  # tagged | uses | produced | won | lost
    weight: float = 1.0
    props: Dict[str, str] = Field(default_factory=dict)


class Node(BaseModel):
    id: str
    type: NodeType
    label: str = ""
    props: Dict[str, str] = Field(default_factory=dict)


# --- Empfehlung des Match-Schritts ------------------------------------------


class ModuleScore(BaseModel):
    module: str
    score: float  # gewichtete Evidenz aus gewonnenen aehnlichen Jobs
    wins: int = 0
    losses: int = 0


class MatchResult(BaseModel):
    """Was der Graph zu einem neuen Job "erinnert"."""

    job_id: str
    recommended_modules: List[ModuleScore] = Field(default_factory=list)
    similar_jobs: List[str] = Field(default_factory=list)


# --- Artefakt (v0.2: Deploy erzeugt echte, startbare Dateien) ---------------


class ArtifactManifest(BaseModel):
    """Beschreibt das materialisierte, lauffaehige Artefakt eines Builds."""

    build_id: str
    job_id: str
    title: str
    stack: str = "python-service"  # zero-dep stdlib-HTTP-Service
    entrypoint: str = "run.py"
    port: int = 8080
    modules: List[str] = Field(default_factory=list)
    files: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
