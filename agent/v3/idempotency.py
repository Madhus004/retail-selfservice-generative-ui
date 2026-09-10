# agent/v3/idempotency.py
#
# actionId -> executed-result store. Same 3-function interface V2 proved
# out, now backed by the SQLite idempotency table instead of an in-memory
# dict — the one-file change V2's own docstring predicted would eventually
# be needed ("a durable backing store can replace the dict later with a
# one-file change"). A server restart no longer loses this.

import json
from typing import Any, Dict, Optional

from v3.db import get_connection
from v3.observability import now_iso


def has_executed(action_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM idempotency WHERE action_id = ?", (action_id,)
        ).fetchone()
    return row is not None


def record_executed(action_id: str, result: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO idempotency (action_id, result_json, executed_at) VALUES (?, ?, ?)",
            (action_id, json.dumps(result, default=str), now_iso()),
        )


def get_recorded_result(action_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT result_json FROM idempotency WHERE action_id = ?", (action_id,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def clear_all() -> None:
    """Test-only helper — mirrors V2's `idempotency._EXECUTED_ACTIONS.clear()` fixture pattern."""

    with get_connection() as conn:
        conn.execute("DELETE FROM idempotency")
