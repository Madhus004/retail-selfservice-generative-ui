# agent/v3/confirmation.py
#
# Transactional confirmation — ported from v2/confirmation.py unchanged in
# logic (this machinery was hardened through real bugs and works
# correctly; only its backing store moved, see idempotency.py).
#
# Entry-point invariant, unchanged: validate_confirmation is called from
# exactly one place — execute_confirmed_action_node, reached only when the
# resumed value is a literal {"confirmation": {...}} object, which is only
# ever produced by the frontend's Confirm/Decline button (never by free
# text, never by the classifier — see graph.py's request_confirmation_node
# and router.py's three-way branch).

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from v3 import idempotency
from v3.observability import now_iso
from v3.state import PendingAction


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def deterministic_action_id(thread_id: str, loop_iteration: int, tool_name: str, payload: Dict[str, Any]) -> str:
    """
    Derived, not random — the interrupt() node this feeds re-executes from
    the top on every resume, so the id must be recomputable from stable
    inputs rather than remembered from a prior pass. Same rationale as V2.
    """

    return f"{thread_id}:{loop_iteration}:{tool_name}:{compute_payload_hash(payload)[:16]}"


def create_pending_action(
    action_id: str,
    action_type: str,
    capability: str,
    proposed_payload: Dict[str, Any],
    eligibility_checked: bool,
) -> PendingAction:
    return {
        "actionId": action_id,
        "actionType": action_type,
        "capability": capability,
        "proposedPayload": proposed_payload,
        "payloadHash": compute_payload_hash(proposed_payload),
        "eligibilityChecked": eligibility_checked,
        "createdAt": now_iso(),
        "consumed": False,
        "executed": False,
    }


@dataclass
class ConfirmationValidationResult:
    ok: bool
    reason: Optional[str] = None
    accepted: bool = False


def validate_confirmation(
    pending: Optional[PendingAction], confirmation: Dict[str, Any]
) -> ConfirmationValidationResult:
    """
    Runs all seven checks, in order, each independently rejecting. Only if
    every check passes does the caller learn whether the customer actually
    accepted or declined — accepted=True/False is only meaningful when
    ok=True.
    """

    if not pending:
        return ConfirmationValidationResult(False, "NO_PENDING_ACTION")

    if confirmation.get("actionId") != pending["actionId"]:  # (1)
        return ConfirmationValidationResult(False, "ACTION_ID_MISMATCH")

    if confirmation.get("actionType") != pending["actionType"]:  # (2)
        return ConfirmationValidationResult(False, "ACTION_TYPE_MISMATCH")

    if compute_payload_hash(pending["proposedPayload"]) != pending["payloadHash"]:  # (3)
        return ConfirmationValidationResult(False, "PAYLOAD_CHANGED")

    if not pending.get("eligibilityChecked"):  # (4)
        return ConfirmationValidationResult(False, "ELIGIBILITY_NOT_CONFIRMED")

    if pending.get("consumed"):  # (5)
        return ConfirmationValidationResult(False, "ALREADY_CONSUMED")

    if pending.get("executed"):  # (6)
        return ConfirmationValidationResult(False, "ALREADY_EXECUTED")

    if idempotency.has_executed(pending["actionId"]):  # (7)
        return ConfirmationValidationResult(False, "IDEMPOTENCY_REPLAY")

    return ConfirmationValidationResult(True, None, bool(confirmation.get("accepted")))
