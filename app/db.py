"""Data layer: SQLite (default, zero setup) or PostgreSQL such as Neon (set a postgres:// URL).

The `path` argument every function takes is either a SQLite file path or a PostgreSQL URL;
config.py picks CREDITLENS_DATABASE_URL / DATABASE_URL first, then CREDITLENS_DB.

Privacy by design: the raw statement is NEVER stored, only the 7 derived features and the
computed result. Every query is scoped by user_id. No ORM; SQL is portable between both engines
apart from the schema and the way the new row id is read back.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score         INTEGER NOT NULL,
    band          TEXT NOT NULL,
    features_json TEXT NOT NULL,
    result_json   TEXT NOT NULL,
    consent       INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_user ON scores(user_id, id DESC);
"""

SCHEMA_PG = [
    """CREATE TABLE IF NOT EXISTS users (
        id            BIGSERIAL PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS scores (
        id            BIGSERIAL PRIMARY KEY,
        user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        score         INTEGER NOT NULL,
        band          TEXT NOT NULL,
        features_json TEXT NOT NULL,
        result_json   TEXT NOT NULL,
        consent       INTEGER NOT NULL,
        created_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scores_user ON scores(user_id, id DESC)",
]

GUEST_DOMAIN = "@guest.creditlens.local"


class DuplicateEmail(Exception):
    pass


def is_postgres(path: str) -> bool:
    return str(path).startswith(("postgres://", "postgresql://"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _PgConn:
    """Gives a psycopg connection the tiny sqlite3-style API used below: execute(sql ?, params)."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._c.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


@contextmanager
def connect(path: str):
    if is_postgres(path):
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(path, row_factory=dict_row, connect_timeout=15)
        conn = _PgConn(raw)
    else:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _insert_returning_id(conn, path: str, sql: str, params: tuple) -> int:
    if is_postgres(path):
        return int(conn.execute(sql + " RETURNING id", params).fetchone()["id"])
    return int(conn.execute(sql, params).lastrowid)


def _is_unique_violation(path: str, exc: Exception) -> bool:
    if is_postgres(path):
        import psycopg
        return isinstance(exc, psycopg.errors.UniqueViolation)
    return isinstance(exc, sqlite3.IntegrityError)


def init_db(path: str) -> None:
    with connect(path) as conn:
        if is_postgres(path):
            for stmt in SCHEMA_PG:
                conn.execute(stmt)
        else:
            conn.executescript(SCHEMA_SQLITE)


# ---- users -------------------------------------------------------------
def create_user(path: str, email: str, password_hash: str) -> int:
    try:
        with connect(path) as conn:
            return _insert_returning_id(
                conn, path,
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, _now()),
            )
    except Exception as exc:
        if _is_unique_violation(path, exc):
            raise DuplicateEmail(email) from exc
        raise


def get_user_by_email(path: str, email: str) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user(path: str, user_id: int) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ---- scores ------------------------------------------------------------
def save_score(path: str, user_id: int, result: dict, consent: bool) -> tuple[int, str]:
    created = _now()
    with connect(path) as conn:
        new_id = _insert_returning_id(
            conn, path,
            "INSERT INTO scores (user_id, score, band, features_json, result_json, consent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, result["score"], result["band"], json.dumps(result["features"]),
             json.dumps(result), int(consent), created),
        )
        return new_id, created


def _score_row(row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "features": json.loads(row["features_json"]),
        "result": json.loads(row["result_json"]),
    }


def get_score(path: str, user_id: int, score_id: int) -> dict | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM scores WHERE id = ? AND user_id = ?", (score_id, user_id)
        ).fetchone()
        return _score_row(row) if row else None


def list_scores(path: str, user_id: int, limit: int = 50) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id, score, band, created_at FROM scores WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_user_data(path: str, user_id: int, delete_account: bool = False) -> int:
    """Delete all of a user's stored scores (and optionally the account). Returns scores removed."""
    with connect(path) as conn:
        n = conn.execute("DELETE FROM scores WHERE user_id = ?", (user_id,)).rowcount
        if delete_account:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return int(n)


def purge_old_guests(path: str, max_age_hours: int = 24) -> int:
    """Delete throw-away demo accounts (and their scores) older than max_age_hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    with connect(path) as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM users WHERE email LIKE ? AND created_at < ?", ("%" + GUEST_DOMAIN, cutoff)).fetchall()]
        for uid in ids:
            conn.execute("DELETE FROM scores WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        return len(ids)
