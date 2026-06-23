"""Tests for the single-shot triage step.

No network here: we fake the LLM client so the test is fast, free, and
deterministic. This is the standard way to test code that calls an LLM -- assert
on how you *use* the model (prompt, schema), not on the model's actual output.
"""

import pytest
from pydantic import ValidationError

from app.agent import triage_finding
from app.agent.triage import TRIAGE_SYSTEM
from app.schemas import Finding, Priority, TriageResult


class _FakeClient:
    """Stand-in for LLMClient: records the call and returns a canned result."""

    def __init__(self, result: TriageResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def complete_structured(self, prompt, schema, system=None, max_retries=2):
        self.calls.append({"prompt": prompt, "schema": schema, "system": system})
        return self.result


def _finding() -> Finding:
    return Finding(
        source="nuclei",
        rule_id="CVE-2021-44228",
        title="Apache Log4j2 RCE",
        severity="critical",
    )


def test_triage_finding_passes_finding_and_returns_result():
    canned = TriageResult(
        priority=Priority.CRITICAL,
        likely_false_positive=False,
        confidence=0.99,
        reasoning="known RCE",
        recommended_remediation="upgrade log4j",
    )
    fake = _FakeClient(canned)

    out = triage_finding(_finding(), fake)  # type: ignore[arg-type]

    assert out is canned                       # returns the model's decision unchanged
    call = fake.calls[0]
    assert call["schema"] is TriageResult      # asked for the right schema
    assert call["system"] == TRIAGE_SYSTEM     # used the triage system prompt
    assert "CVE-2021-44228" in call["prompt"]  # the finding was serialized into the prompt
    assert "critical" in call["prompt"]        # scanner severity is visible to the model


def test_triageresult_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        TriageResult(
            priority=Priority.LOW,
            likely_false_positive=False,
            confidence=1.5,  # must be within 0..1
            reasoning="r",
            recommended_remediation="x",
        )
