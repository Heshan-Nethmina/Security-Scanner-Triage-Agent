"""Tests for the agent loop (reason -> act -> observe -> decide).

We fake the model turns (``chat``) and the structuring step (``complete_structured``)
so there is no network, but we let the loop run the *real* tool dispatch through the
stub ``lookup_cve``. That checks the mechanics we care about: the loop runs a
requested tool, feeds the result back, terminates, and returns a TriageResult.
"""

from app.agent import run_triage_agent
from app.llm.client import ChatTurn, LLMResult, ToolCall
from app.schemas import Finding, Priority, TriageResult

_DUMMY_USAGE = LLMResult("", "fake", "fake", 0, 0, 0.0, 0.0)


class _FakeAgentClient:
    """Returns scripted chat turns, then a canned structured result."""

    def __init__(self, turns: list[ChatTurn], structured: TriageResult) -> None:
        self._turns = turns
        self._structured = structured
        self.chat_calls = 0
        self.structuring_prompt = ""

    def chat(self, messages, tools=None, **kwargs) -> ChatTurn:
        turn = self._turns[self.chat_calls]
        self.chat_calls += 1
        return turn

    def complete_structured(self, prompt, schema, system=None, max_retries=2):
        self.structuring_prompt = prompt
        return self._structured


def _finding() -> Finding:
    return Finding(
        source="nuclei",
        rule_id="CVE-2021-44228",
        title="Apache Log4j2 RCE",
        severity="critical",
        cve_ids=["CVE-2021-44228"],
    )


def test_agent_runs_tool_then_returns_structured_result():
    # Turn 1: the model asks to call lookup_cve. Turn 2: it gives a final assessment.
    turn1 = ChatTurn(
        text=None,
        tool_calls=[ToolCall(id="t1", name="lookup_cve", arguments={"cve_id": "CVE-2021-44228"})],
        assistant_message={"role": "assistant", "content": None},
        usage=_DUMMY_USAGE,
    )
    turn2 = ChatTurn(
        text="Priority: critical. Not a false positive. Fix: upgrade Log4j2 to 2.17.1.",
        tool_calls=[],
        assistant_message={"role": "assistant", "content": "..."},
        usage=_DUMMY_USAGE,
    )
    canned = TriageResult(
        priority=Priority.CRITICAL,
        likely_false_positive=False,
        confidence=1.0,
        reasoning="known RCE",
        recommended_remediation="upgrade to 2.17.1",
    )
    fake = _FakeAgentClient([turn1, turn2], canned)

    result = run_triage_agent(_finding(), fake)  # type: ignore[arg-type]

    assert result is canned              # returns the validated TriageResult
    assert fake.chat_calls == 2          # looped: tool turn, then final turn
    # The model's free-text assessment was carried into the structuring step.
    assert "2.17.1" in fake.structuring_prompt
