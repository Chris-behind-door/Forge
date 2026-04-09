"""Session and message storage backed by SQLite."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DB_DIR / "sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content     TEXT NOT NULL DEFAULT '',
    rounds      INTEGER,
    citations   TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


from contextlib import contextmanager

@contextmanager
def _get_conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


# ---- Session CRUD ----


def create_session(title: str = "") -> dict[str, Any]:
    sid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
            (sid, title, now),
        )
        conn.commit()
    return {"id": sid, "title": title, "created_at": now}


def list_sessions() -> list[dict[str, Any]]:
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.created_at,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, created_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        msgs = conn.execute(
            "SELECT id, role, content, rounds, citations, created_at "
            "FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    session = dict(row)
    session["messages"] = [dict(m) for m in msgs]
    return session


def delete_session(session_id: str) -> bool:
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0


def update_session_title(session_id: str, title: str) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
        conn.commit()


def get_session_title(session_id: str) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT title FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return row["title"] if row else None


# ---- Message helpers ----


def save_message(
    session_id: str,
    role: str,
    content: str,
    rounds: int | None = None,
    citations: list[dict] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, rounds, citations, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                rounds,
                json.dumps(citations, ensure_ascii=False) if citations else None,
                now,
            ),
        )
        conn.commit()


def get_context_messages(
    session_id: str,
    max_rounds: int = 10,
) -> list[dict[str, str]]:
    """Return the last *max_rounds* user/assistant pairs as chat messages.

    Each "round" is one user + one assistant message.  We fetch enough
    rows from the tail and pair them up.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = ? AND role IN ('user','assistant') "
            "ORDER BY id DESC LIMIT ?",
            (session_id, max_rounds * 2),
        ).fetchall()
    # Reverse so oldest is first, then pair user+assistant.
    # Drop dangling messages (user without assistant at tail).
    rows = list(reversed(rows))
    paired: list[dict[str, str]] = []
    i = 0
    while i < len(rows) - 1:
        if rows[i]["role"] == "user" and rows[i + 1]["role"] == "assistant":
            paired.append({"role": rows[i]["role"], "content": rows[i]["content"]})
            paired.append({"role": rows[i + 1]["role"], "content": rows[i + 1]["content"]})
            i += 2
        else:
            # Skip unpaired message and try to recover
            i += 1
    return paired
