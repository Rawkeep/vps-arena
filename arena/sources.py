"""Ingest-Quellen (v0.3): woher der Agent autonom Jobs zieht.

Jede Quelle liefert `poll() -> List[Job]`. Jeder Job traegt eine stabile
`external_id` (fuer Dedup) und `source`. Der Autopilot entscheidet dann, was
neu ist und gebaut wird.

Kern (Feed/Verzeichnis) ist dep-frei. IMAP nutzt stdlib `imaplib`, lazy.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import List, Optional

from .models import Job

# --- Tag-Ableitung: aus Freitext grobe Tags erkennen (Kaltstart-Hilfe) ------

_TAG_KEYWORDS = {
    "rag": ["rag", "wissens", "dokument", "q&a", "chatbot", "frage"],
    "dsgvo": ["dsgvo", "datenschutz", "gdpr", "compliance"],
    "api": ["api", "schnittstelle", "rest", "endpoint", "integration"],
    "dashboard": ["dashboard", "auswertung", "report", "visualis", "kpi"],
    "auth": ["login", "auth", "anmeld", "jwt", "benutzer"],
    "export": ["export", "pdf", "rechnung", "beleg"],
    "agent": ["agent", "workflow", "automatis", "orchestr"],
    "storage": ["speicher", "datenbank", "sqlite", "storage"],
}


def derive_tags(text: str) -> List[str]:
    low = text.lower()
    tags = [tag for tag, kws in _TAG_KEYWORDS.items() if any(k in low for k in kws)]
    return tags


def _job_from_fields(
    title: str,
    description: str,
    tags: Optional[List[str]],
    budget: Optional[float],
    external_id: str,
    source: str,
) -> Job:
    return Job(
        id=f"job:{uuid.uuid4().hex[:12]}",
        title=title.strip() or "(ohne Titel)",
        description=description.strip(),
        tags=tags if tags else derive_tags(f"{title} {description}"),
        budget=budget,
        external_id=external_id,
        source=source,
    )


def _stable_id(source: str, natural_key: str) -> str:
    digest = hashlib.sha1(natural_key.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{digest}"


# --- Quellen -----------------------------------------------------------------


class FeedSource:
    """JSON-Datei mit einer Liste von Job-Dicts (oder {"jobs": [...]})."""

    name = "feed"

    def __init__(self, path: str):
        self.path = path

    def poll(self) -> List[Job]:
        if not os.path.isfile(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("jobs", []) if isinstance(data, dict) else data
        jobs: List[Job] = []
        for it in items:
            title = str(it.get("title", ""))
            ext = str(it.get("id") or _stable_id(self.name, title + it.get("description", "")))
            jobs.append(
                _job_from_fields(
                    title=title,
                    description=str(it.get("description", "")),
                    tags=it.get("tags"),
                    budget=it.get("budget"),
                    external_id=ext,
                    source=self.name,
                )
            )
        return jobs


class DirSource:
    """Verzeichnis mit *.json- und *.md-Job-Dateien (Inbox-Muster)."""

    name = "dir"

    def __init__(self, path: str):
        self.path = path

    def poll(self) -> List[Job]:
        if not os.path.isdir(self.path):
            return []
        jobs: List[Job] = []
        for fname in sorted(os.listdir(self.path)):
            full = os.path.join(self.path, fname)
            if not os.path.isfile(full):
                continue
            ext = _stable_id(self.name, fname)
            if fname.endswith(".json"):
                with open(full, encoding="utf-8") as fh:
                    it = json.load(fh)
                jobs.append(
                    _job_from_fields(
                        title=str(it.get("title", fname)),
                        description=str(it.get("description", "")),
                        tags=it.get("tags"),
                        budget=it.get("budget"),
                        external_id=str(it.get("id") or ext),
                        source=self.name,
                    )
                )
            elif fname.endswith((".md", ".txt")):
                with open(full, encoding="utf-8") as fh:
                    body = fh.read()
                # Erste Zeile (ggf. mit '#') = Titel, Rest = Beschreibung.
                first, _, rest = body.partition("\n")
                title = first.lstrip("# ").strip() or fname
                jobs.append(
                    _job_from_fields(
                        title=title,
                        description=rest.strip(),
                        tags=None,
                        budget=None,
                        external_id=ext,
                        source=self.name,
                    )
                )
        return jobs


class ImapSource:
    """IMAP-Postfach: Betreff = Titel, Body = Beschreibung. Lazy stdlib imaplib.

    Bewusst nur ungelesene Mails; Message-Id ist die external_id. Kein Egress
    ausser der explizit konfigurierten Verbindung.
    """

    name = "imap"

    def __init__(
        self, host: str, user: str, password: str, mailbox: str = "INBOX", limit: int = 20
    ):
        self.host = host
        self.user = user
        self.password = password
        self.mailbox = mailbox
        self.limit = limit

    def poll(self) -> List[Job]:  # pragma: no cover - braucht echten Mailserver
        import email
        import imaplib

        jobs: List[Job] = []
        conn = imaplib.IMAP4_SSL(self.host)
        try:
            conn.login(self.user, self.password)
            conn.select(self.mailbox)
            _typ, data = conn.search(None, "UNSEEN")
            ids = data[0].split()[: self.limit]
            for num in ids:
                _typ, raw = conn.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])  # type: ignore[index,arg-type]
                subject = str(
                    email.header.make_header(email.header.decode_header(msg.get("Subject", "")))
                )
                mid = msg.get("Message-Id", subject)
                body = _first_text(msg)
                jobs.append(
                    _job_from_fields(
                        title=subject,
                        description=body,
                        tags=None,
                        budget=None,
                        external_id=_stable_id(self.name, mid),
                        source=self.name,
                    )
                )
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return jobs


def _first_text(msg) -> str:  # pragma: no cover - IMAP-Pfad
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode("utf-8", errors="replace") if payload else str(msg.get_payload())
