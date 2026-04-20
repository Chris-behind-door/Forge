"""
Kùzu graph database connection management and schema initialization.
"""

import asyncio
import logging
from pathlib import Path

import kuzu

logger = logging.getLogger(__name__)

KUZU_DIR = Path.home() / ".engineer_assistant" / "data" / "kuzu"

_db: kuzu.Database | None = None
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


def get_db() -> kuzu.Database:
    global _db
    if _db is None:
        KUZU_DIR.mkdir(parents=True, exist_ok=True)
        _db = kuzu.Database(str(KUZU_DIR))
        conn = kuzu.Connection(_db)
        _init_schema(conn)
        logger.info("Kùzu database initialized")
    return _db


def get_conn() -> kuzu.Connection:
    return kuzu.Connection(get_db())


async def get_conn_async() -> kuzu.Connection:
    """Get a connection (schema init is idempotent)."""
    async with _lock:
        db = await asyncio.to_thread(get_db)
    return kuzu.Connection(db)
