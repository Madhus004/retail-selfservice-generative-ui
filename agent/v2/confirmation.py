# agent/v2/confirmation.py
#
# Transactional confirmation (plan sections 18a correction 1, 20-21).
#
# Entry-point invariant: validate_confirmation is called from exactly one
# place — execute_confirmed_action_node, reached only when the resumed
# value is a literal {"confirmation": {...}} object, which is only ever
# produced by the frontend's Confirm/Decline button (never by free text,
# never by the classifier — see graph.py's request_confirmation_node and
# router.py's three-way branch).

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from v2 import idempotency
from v2.observability import now_iso
from v2.state import PendingAction


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def deterministic_action_id(thread_id: str, loop_iteration: int, tool_name: str, payload: Dict[str, Any]) -> str:
    """
    Derived, not random — request_confirmation_node's LangGraph interrupt()
    node re-executes from the top on every resume (confirmed empirically:
    state mutations made before interrupt() never persist across a resume,
    so the node cannot just "remember" a randomly-minted id from a prior
    pass). Deriving the id from inputs that are themselves stable across
    reruns (same thread, same loop iteration, same proposed call) means the
    SAME actionId is recomputed every time without needing anything to
    persist — the customer's original confirmation click always matches.
    A genuinely new proposal always has a different loopIteration, so this
    never collides with an unrelated pending action.
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

    # (3) payload unchanged since the preview was shown. proposedPayload is
    # frozen at creation and nothing else in this design re-derives it
    # independently, so today this re-checks the pending action's own
    # internal consistency (catching a corrupted/tampered dict) rather than
    # an organically reachable drift — kept as real, running code rather
    # than a no-op, since a future capability with a longer gap between
    # preview and confirm could make this reachable in practice.
    if compute_payload_hash(pending["proposedPayload"]) != pending["payloadHash"]:
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
