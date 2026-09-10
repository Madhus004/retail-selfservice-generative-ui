# agent/test_v3_evals.py
#
# Wraps agent/v3/evals/*_scenarios.py's scripted scenarios as individual
# pytest tests, so they run as part of the normal suite (and show up
# individually in CI output) as well as being runnable standalone via
# `python -m v3.evals.<module>` for a human-readable pass/fail report.
#
# order_status/cancellation scenarios run on the deterministic path
# (OPENAI_API_KEY cleared); general_assistance scenarios specifically
# exercise the real LLM + search_policies_tool path, so they restore
# whatever key this dev environment actually has instead.

import os

import pytest

from v3 import idempotency
from v3.evals.cancellation_scenarios import SCENARIOS as CANCELLATION_SCENARIOS
from v3.evals.general_assistance_scenarios import SCENARIOS as GENERAL_ASSISTANCE_SCENARIOS
from v3.evals.order_status_scenarios import SCENARIOS as ORDER_STATUS_SCENARIOS
from v3.evals.returns_scenarios import SCENARIOS as RETURNS_SCENARIOS

_REAL_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


@pytest.mark.parametrize("scenario", ORDER_STATUS_SCENARIOS, ids=[s.name for s in ORDER_STATUS_SCENARIOS])
def test_order_status_eval_scenario(scenario, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    scenario.run()


@pytest.mark.parametrize("scenario", CANCELLATION_SCENARIOS, ids=[s.name for s in CANCELLATION_SCENARIOS])
def test_cancellation_eval_scenario(scenario, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    idempotency.clear_all()
    scenario.run()
    idempotency.clear_all()


@pytest.mark.parametrize("scenario", RETURNS_SCENARIOS, ids=[s.name for s in RETURNS_SCENARIOS])
def test_returns_eval_scenario(scenario, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    idempotency.clear_all()
    scenario.run()
    idempotency.clear_all()


@pytest.mark.parametrize(
    "scenario", GENERAL_ASSISTANCE_SCENARIOS, ids=[s.name for s in GENERAL_ASSISTANCE_SCENARIOS]
)
def test_general_assistance_eval_scenario(scenario, monkeypatch):
    if not _REAL_OPENAI_API_KEY:
        pytest.skip("no OPENAI_API_KEY available in this environment")
    monkeypatch.setenv("OPENAI_API_KEY", _REAL_OPENAI_API_KEY)
    scenario.run()
