"""
Kùzu graph database connection management and schema initialization.

Kùzu requires a single Database instance (file-locked) and supports
one concurrent writer. We keep a global singleton + asyncio.Lock for
all write operations.
"""

import asyncio
import logging
from pathlib import Path

import kuzu

logger = logging.getLogger(__name__)

KUZU_DIR = Path.home() / ".engineer_assistant" / "data"
KUZU_PATH = KUZU_DIR / "kuzu.db"

_db: kuzu.Database | None = None
_conn: kuzu.Connection | None = None
_lock = asyncio.Lock()

SCHEMAS = [
    # Node tables
    """CREATE NODE TABLE IF NOT EXISTS Project (
        id STRING,
        name STRING,
        description STRING,
        created_at STRING,
        PRIMARY KEY (id)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Meeting (
        id STRING,
        project_id STRING,
        title STRING,
        date STRING,
        summary STRING,
        source_doc_id STRING,
        raw_text STRING,
        created_at STRING,
        PRIMARY KEY (id)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Resolution (
        id STRING,
        meeting_id STRING,
        project_id STRING,
        content STRING,
        idx INT,
        status STRING DEFAULT 'active',
        source_doc_id STRING,
        created_at STRING,
        embedding FLOAT[512],
        PRIMARY KEY (id)
    )""",
    # Rel tables
    """CREATE REL TABLE IF NOT EXISTS SUPERSEDES (
        FROM Resolution TO Resolution,
        meeting_id STRING,
        reason STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS AMENDS (
        FROM Resolution TO Resolution,
        meeting_id STRING,
        change_summary STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS SUPPLEMENTS (
        FROM Resolution TO Resolution,
        meeting_id STRING,
        supplement_content STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS CONTAINS_MEETING (
        FROM Project TO Meeting
    )""",
    """CREATE REL TABLE IF NOT EXISTS CONTAINS_RESOLUTION (
        FROM Meeting TO Resolution
    )""",
]


def _init_schema(conn: kuzu.Connection) -> None:
    for ddl in SCHEMAS:
        try:
            conn.execute(ddl)
        except Exception:
            pass  # table already exists

    # Migration: add embedding field if missing (Kùzu doesn't support ALTER TABLE,
    # but IF NOT EXISTS on CREATE handles fresh DBs)
    try:
        conn.execute("ALTER TABLE Resolution ADD embedding FLOAT[512] DEFAULT [0.0]*512")
    except Exception:
        pass  # column already exists or Kùzu doesn't support ALTER


def _ensure_db() -> None:
    """Initialize the singleton Database and Connection (idempotent)."""
    global _db, _conn
    if _db is None:
        KUZU_DIR.mkdir(parents=True, exist_ok=True)
        try:
            _db = kuzu.Database(str(KUZU_PATH))
        except RuntimeError as e:
            if "lock" in str(e).lower():
                logger.error("Kùzu database is locked by another process: %s", e)
                raise RuntimeError(
                    "数据库被其他进程占用，请关闭其他实例后重试"
                ) from e
            raise
        _conn = kuzu.Connection(_db)
        _init_schema(_conn)
        logger.info("Kùzu database initialized")


def get_conn() -> kuzu.Connection:
    """Synchronous: return the singleton Connection."""
    _ensure_db()
    return _conn  # type: ignore[return-value]


def get_lock() -> asyncio.Lock:
    return _lock
