# agent/v2/idempotency.py
#
# actionId -> executed-result store (plan sections 20-21). A 3-function
# abstraction over an in-memory dict, deliberately isolated behind these
# three functions so a durable backing store (Redis/DB) can replace the
# dict later with a one-file change.
#
# NOTE: in-memory only. A server restart loses all idempotency history,
# pending confirmations, and checkpoints. Acceptable for this prototype;
# would need durable storage before any real deployment.

from typing import Any, Dict, Optional

from v2.observability import now_iso

_EXECUTED_ACTIONS: Dict[str, Dict[str, Any]] = {}


def has_executed(action_id: str) -> bool:
    return action_id in _EXECUTED_ACTIONS


def record_executed(action_id: str, result: Dict[str, Any]) -> None:
    _EXECUTED_ACTIONS[action_id] = {"result": result, "recordedAt": now_iso()}


def get_recorded_result(action_id: str) -> Optional[Dict[str, Any]]:
    entry = _EXECUTED_ACTIONS.get(action_id)
    return entry["result"] if entry else None
