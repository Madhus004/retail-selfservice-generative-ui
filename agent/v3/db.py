# agent/v3/db.py
#
# The single SQLite file V3 uses for everything that needs to survive a
# restart — idempotency records, trace records, and the mock customer
# profile. LangGraph's own checkpoint tables live in the SAME file (see
# get_checkpointer() below) so the whole app's durable state is one file,
# one connection pattern, easy to inspect with any SQLite browser.
#
# Deliberately NOT a connection pool or ORM — this is a low-traffic
# prototype (one demo customer, one browser tab at a time in practice).
# Every helper opens a short-lived connection, does its work, and closes
# it; sqlite3 connections aren't safe to share across threads, and FastAPI
# may serve requests on different threads, so "open fresh every call" is
# the simplest correct choice here, not a shortcut.

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from langgraph.checkpoint.sqlite import SqliteSaver

DB_PATH = Path(__file__).parent / "data" / "app.db"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """
    Idempotent — safe to call on every process start. Only owns the three
    tables below; LangGraph's SqliteSaver manages its own checkpoint
    tables in this same file via its own setup() call (see graph.py).
    """

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                action_id TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                executed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                session_id TEXT,
                ts TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_run_id ON trace_records(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_session_id ON trace_records(session_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_profile (
                customer_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL
            )
            """
        )


def get_checkpointer() -> SqliteSaver:
    """
    A dedicated, long-lived connection (not one of get_connection()'s
    short-lived ones) — SqliteSaver owns this connection for the graph's
    entire process lifetime, same file as everything else in this module.
    check_same_thread=False because FastAPI may serve requests on
    different threads; SqliteSaver serializes access internally.
    """

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return SqliteSaver(conn)
