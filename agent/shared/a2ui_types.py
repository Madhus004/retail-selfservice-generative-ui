# agent/shared/a2ui_types.py
#
# Shared A2UI validation *pattern*, not shared state. V1's own
# ALLOWED_A2UI_COMPONENTS/validate_a2ui_components in agent/graph.py are not
# touched and do not import this — this module exists so V2 (and any future
# consumer) can reuse the same "never trust the proposal, always allow-list
# filter, always have a deterministic fallback" strategy without duplicating
# the filtering logic itself.

from typing import Any, Dict, List, Tuple


def filter_to_allowlist(
    raw_components: List[Dict[str, Any]],
    allowed_types: set,
) -> List[Dict[str, Any]]:
    """
    Drops any proposed component whose type is not in allowed_types. Never
    raises on an invalid type — silently excludes it, consistent with the
    "LLM proposes, code disposes" principle.
    """

    filtered = []

    for component in raw_components:
        if not isinstance(component, dict):
            continue

        component_type = component.get("type")

        if component_type not in allowed_types:
            continue

        filtered.append(
            {
                "type": component_type,
                "props": component.get("props") if isinstance(component.get("props"), dict) else {},
                "dataKey": component.get("dataKey"),
            }
        )

    return filtered


def validate_or_fallback(
    raw_components: List[Dict[str, Any]],
    allowed_types: set,
    fallback_components: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Returns (components, origin) where origin is "AGENT_PROPOSED" if at
    least one proposed component survived allow-list filtering, else
    "DETERMINISTIC_FALLBACK" and fallback_components is returned unchanged.
    """

    filtered = filter_to_allowlist(raw_components or [], allowed_types)

    if not filtered:
        return fallback_components, "DETERMINISTIC_FALLBACK"

    return filtered, "AGENT_PROPOSED"
