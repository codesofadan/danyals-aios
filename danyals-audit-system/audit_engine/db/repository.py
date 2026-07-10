"""SQLite repository.

One connection per audit. Tables are defined in schema.sql; we apply that on
first use. No SQLAlchemy ORM for v1 - keep the surface minimal and explicit.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

from audit_engine.config import DB_PATH, SCHEMA_PATH, ensure_dirs

PKT = timezone(timedelta(hours=5), name="PKT")


def _now_pkt() -> str:
    return datetime.now(PKT).isoformat(timespec="seconds")


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_dirs()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    schema_sql = schema_path.read_text(encoding="utf-8")
    with _connect(db_path) as conn:
        conn.executescript(schema_sql)


@contextmanager
def connection(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    if not db_path.exists():
        initialize(db_path)
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@dataclass
class AuditRun:
    id: int | None = None
    run_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain: str = ""
    profile: str = "general"
    command: str = "/audit-quick"
    args_json: str = "{}"
    status: str = "pending"
    started_at: str = field(default_factory=_now_pkt)
    finished_at: str | None = None
    duration_sec: float | None = None
    pages_crawled: int = 0
    overall_score: float | None = None
    on_page_score: float | None = None
    technical_score: float | None = None
    off_page_score: float | None = None
    local_score: float | None = None
    api_cost_usd: float = 0.0
    artifact_dir: str = ""
    error_message: str | None = None


@dataclass
class Finding:
    run_id: int
    check_id: str
    check_name: str
    category: str
    subcategory: str | None
    owner_agent: str
    status: str            # pass | warn | fail | n_a
    severity: str          # critical | major | minor | info
    score: float | None
    confidence: float | None
    evidence_json: str | None
    remediation: str | None
    references_json: str | None
    impact_usd: float | None
    page_id: int | None = None


class AuditRunRepository:
    """CRUD for the audit_runs table."""

    @staticmethod
    def create(conn: sqlite3.Connection, run: AuditRun) -> AuditRun:
        cur = conn.execute(
            """
            INSERT INTO audit_runs
                (run_uuid, domain, profile, command, args_json, status,
                 started_at, artifact_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_uuid,
                run.domain,
                run.profile,
                run.command,
                run.args_json,
                run.status,
                run.started_at,
                run.artifact_dir,
            ),
        )
        run.id = cur.lastrowid
        return run

    @staticmethod
    def finalize(
        conn: sqlite3.Connection,
        run_id: int,
        *,
        status: str,
        duration_sec: float,
        pages_crawled: int,
        scores: dict[str, float | None],
        api_cost_usd: float = 0.0,
        error_message: str | None = None,
    ) -> None:
        conn.execute(
            """
            UPDATE audit_runs
            SET status = ?, finished_at = ?, duration_sec = ?, pages_crawled = ?,
                overall_score = ?, on_page_score = ?, technical_score = ?,
                off_page_score = ?, local_score = ?, api_cost_usd = ?, error_message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                _now_pkt(),
                duration_sec,
                pages_crawled,
                scores.get("overall"),
                scores.get("on_page"),
                scores.get("technical"),
                scores.get("off_page"),
                scores.get("local"),
                api_cost_usd,
                error_message,
                _now_pkt(),
                run_id,
            ),
        )


class PageRepository:
    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        run_id: int,
        *,
        url: str,
        canonical_url: str | None = None,
        page_type: str | None = None,
        http_status: int | None = None,
        response_ms: int | None = None,
        title: str | None = None,
        meta_description: str | None = None,
        h1: str | None = None,
        word_count: int | None = None,
        indexable: bool | None = None,
        crawl_depth: int | None = None,
        is_orphan: bool = False,
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO pages
                (run_id, url, canonical_url, page_type, http_status, response_ms,
                 title, meta_description, h1, word_count, indexable, crawl_depth, is_orphan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, url) DO UPDATE SET
                canonical_url = excluded.canonical_url,
                http_status = excluded.http_status,
                response_ms = excluded.response_ms,
                title = excluded.title,
                meta_description = excluded.meta_description,
                h1 = excluded.h1,
                word_count = excluded.word_count,
                indexable = excluded.indexable
            """,
            (
                run_id,
                url,
                canonical_url,
                page_type,
                http_status,
                response_ms,
                title,
                meta_description,
                h1,
                word_count,
                int(indexable) if indexable is not None else None,
                crawl_depth,
                int(is_orphan),
            ),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM pages WHERE run_id = ? AND url = ?", (run_id, url)
        ).fetchone()
        return row["id"]


class FindingRepository:
    @staticmethod
    def insert_many(conn: sqlite3.Connection, findings: list[Finding]) -> None:
        if not findings:
            return
        conn.executemany(
            """
            INSERT INTO findings
                (run_id, page_id, check_id, check_name, category, subcategory,
                 owner_agent, status, severity, score, confidence, evidence_json,
                 remediation, references_json, impact_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f.run_id,
                    f.page_id,
                    f.check_id,
                    f.check_name,
                    f.category,
                    f.subcategory,
                    f.owner_agent,
                    f.status,
                    f.severity,
                    f.score,
                    f.confidence,
                    f.evidence_json,
                    f.remediation,
                    f.references_json,
                    f.impact_usd,
                )
                for f in findings
            ],
        )

    @staticmethod
    def by_run(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM findings WHERE run_id = ? ORDER BY severity, score", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def encode_evidence(evidence: Any) -> str | None:
    if evidence is None:
        return None
    if isinstance(evidence, str):
        return evidence
    return json.dumps(evidence, ensure_ascii=False, default=str)


def encode_refs(refs: list[str] | None) -> str | None:
    if not refs:
        return None
    return json.dumps(refs, ensure_ascii=False)
