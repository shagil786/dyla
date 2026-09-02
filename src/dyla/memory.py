"""SQLite-backed application memory for durable research-agent state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import string
import unicodedata
import uuid
from pathlib import Path

from .domain import AuditVerdict, Claim, MemoryRecord

_NAMESPACE = uuid.UUID("9f3e5b95-7c47-4c73-a2e7-6ddf5d6d64f8")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.strip(string.punctuation)
    return " ".join(value.split())


class MemoryStore:
    def __init__(self, database: str | Path = "dyla.db") -> None:
        self.database = str(database)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aliases (
                entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                normalized_alias TEXT NOT NULL,
                alias TEXT NOT NULL,
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                PRIMARY KEY (entity_id, normalized_alias)
            );
            CREATE INDEX IF NOT EXISTS aliases_by_normalized_name
                ON aliases(normalized_alias);
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                confidence TEXT NOT NULL,
                citations_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_verdicts (
                claim_id TEXT PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                explanation TEXT NOT NULL,
                citations_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warning TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memory_records (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                entity_ids_json TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS memory_records_text ON memory_records(text);
            """
        )
        self.connection.commit()

    def upsert_entity(self, canonical_name: str, entity_type: str) -> str:
        normalized = normalize_text(canonical_name)
        if not normalized:
            raise ValueError("canonical_name must not be empty")
        entity_id = str(uuid.uuid5(_NAMESPACE, f"entity:{normalized}"))
        self.connection.execute(
            """
            INSERT INTO entities (id, canonical_name, normalized_name, entity_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                entity_type = excluded.entity_type
            """,
            (entity_id, canonical_name.strip(), normalized, entity_type),
        )
        self.connection.commit()
        return entity_id

    def add_alias(self, entity_id: str, alias: str, confidence: float) -> None:
        normalized = normalize_text(alias)
        if not normalized:
            raise ValueError("alias must not be empty")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        self.connection.execute(
            """
            INSERT INTO aliases (entity_id, normalized_alias, alias, confidence)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                alias = excluded.alias, confidence = excluded.confidence
            """,
            (entity_id, normalized, alias.strip(), confidence),
        )
        self.connection.commit()

    def find_entities(self, query: str) -> list[sqlite3.Row]:
        normalized = normalize_text(query)
        rows = self.connection.execute(
            """
            SELECT DISTINCT e.id, e.canonical_name, e.entity_type
            FROM entities e
            LEFT JOIN aliases a ON a.entity_id = e.id
            WHERE e.normalized_name = ? OR a.normalized_alias = ?
            ORDER BY e.canonical_name COLLATE NOCASE, e.id
            """,
            (normalized, normalized),
        ).fetchall()
        return rows

    def entity_candidates(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT e.id, e.canonical_name, e.normalized_name,
                   a.normalized_alias, COALESCE(a.confidence, 1.0) AS alias_confidence
            FROM entities e
            LEFT JOIN aliases a ON a.entity_id = e.id
            ORDER BY e.id, a.normalized_alias
            """
        ).fetchall()

    def add_memory(
        self,
        text: str,
        *,
        kind: str,
        entity_ids: list[str] | None = None,
        source_ids: list[str] | None = None,
        verified: bool = False,
        record_id: str | None = None,
    ) -> None:
        record_id = record_id or hashlib.sha256(
            f"{kind}\0{text}".encode()
        ).hexdigest()
        self.connection.execute(
            """
            INSERT INTO memory_records
              (id, kind, text, entity_ids_json, source_ids_json, verified)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind, text=excluded.text,
              entity_ids_json=excluded.entity_ids_json,
              source_ids_json=excluded.source_ids_json,
              verified=excluded.verified
            """,
            (
                record_id,
                kind,
                text,
                json.dumps(entity_ids or []),
                json.dumps(source_ids or []),
                int(verified),
            ),
        )
        self.connection.commit()

    def search_memory(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        if limit < 1:
            return []
        terms = [term for term in normalize_text(query).split() if term]
        if not terms:
            return []
        clauses = " AND ".join("text LIKE ? COLLATE NOCASE" for _ in terms)
        rows = self.connection.execute(
            f"SELECT * FROM memory_records WHERE {clauses} ORDER BY rowid LIMIT ?",
            tuple(f"%{term}%" for term in terms) + (limit,),
        ).fetchall()
        return [
            MemoryRecord(
                id=row["id"],
                kind=row["kind"],
                text=row["text"],
                entity_ids=json.loads(row["entity_ids_json"]),
                source_ids=json.loads(row["source_ids_json"]),
                verified=bool(row["verified"]),
            )
            for row in rows
        ]

    def save_claim(self, claim: Claim, verdict: AuditVerdict | None) -> None:
        citations = [citation.model_dump(mode="json") for citation in claim.citations]
        with self.connection:
            for citation in claim.citations:
                self.connection.execute(
                    "INSERT OR IGNORE INTO sources (id, url, title) VALUES (?, ?, ?)",
                    (citation.source_id, citation.url, citation.title),
                )
            self.connection.execute(
                """
                INSERT INTO claims (id, text, confidence, citations_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET text=excluded.text,
                  confidence=excluded.confidence, citations_json=excluded.citations_json
                """,
                (claim.id, claim.text, claim.confidence, json.dumps(citations)),
            )
            if verdict is not None:
                self.connection.execute(
                    """
                    INSERT INTO audit_verdicts
                      (claim_id, status, explanation, citations_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(claim_id) DO UPDATE SET status=excluded.status,
                      explanation=excluded.explanation,
                      citations_json=excluded.citations_json
                    """,
                    (
                        verdict.claim_id,
                        verdict.status,
                        verdict.explanation,
                        json.dumps([c.model_dump(mode="json") for c in verdict.citations_checked]),
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO memory_records
                  (id, kind, text, entity_ids_json, source_ids_json, verified)
                VALUES (?, 'claim', ?, '[]', ?, ?)
                ON CONFLICT(id) DO UPDATE SET text=excluded.text,
                  source_ids_json=excluded.source_ids_json, verified=excluded.verified
                """,
                (
                    claim.id,
                    claim.text,
                    json.dumps([citation.source_id for citation in claim.citations]),
                    int(verdict is not None and verdict.status == "supported"),
                ),
            )
