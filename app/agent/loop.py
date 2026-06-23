"""The hand-written triage agent: reason -> act -> observe -> decide.

Two phases:
  1. ``_gather_assessment`` runs the reason -> act -> observe loop: the model is
     offered tools, we run any it requests and feed the results back, repeating
     until it writes its free-text assessment (capped by ``max_iterations``).
  2. ``run_triage_agent`` then converts that assessment into a validated
     ``TriageResult`` with ``complete_structured`` (validate + retry).

So the agent's output is the same trustworthy typed object as single-shot triage --
but now grounded in tool lookups. (A more advanced design forces the final answer
to be a ``submit_triage`` tool call whose arguments are the schema; we keep the
clearer gather-then-structure split here.)
"""

import logging

from app.agent.tools import TOOLS, Tool
from app.llm import LLMClient
from app.schemas import Finding, TriageResult

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

AGENT_SYSTEM = """\
You are a security triage assistant. Before judging a finding that has a CVE id,
call the lookup_cve tool to get authoritative details rather than relying on memory.
Once you have what you need, give your assessment: a realistic priority, whether it
is a likely false positive, your reasoning, and concise remediation (how to fix --
never how to attack).
"""

STRUCTURE_SYSTEM = (
    "Convert the security triage assessment you are given into the structured schema, "
    "faithfully preserving its priority, false-positive judgment, reasoning, and "
    "remediation. Remediation is how to fix -- never how to attack."
)


def run_triage_agent(
    finding: Finding,
    client: LLMClient,
    tools: dict[str, Tool] = TOOLS,
    max_iterations: int = MAX_ITERATIONS,
) -> TriageResult:
    """Triage one finding with the tool-using agent; return a validated ``TriageResult``."""
    assessment = _gather_assessment(finding, client, tools, max_iterations)
    return client.complete_structured(
        prompt=f"Convert this triage assessment into the structured result:\n\n{assessment}",
        schema=TriageResult,
        system=STRUCTURE_SYSTEM,
    )


def _gather_assessment(
    finding: Finding,
    client: LLMClient,
    tools: dict[str, Tool],
    max_iterations: int,
) -> str:
    """Run the reason -> act -> observe loop; return the model's final text assessment."""
    messages: list[dict] = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": f"Assess this finding:\n{finding.model_dump_json(indent=2)}"},
    ]
    tool_schemas = [t.to_openai() for t in tools.values()]

    for step in range(1, max_iterations + 1):
        turn = client.chat(messages, tools=tool_schemas)

        # No tool calls -> the model is done reasoning; this is the final assessment.
        if not turn.tool_calls:
            logger.info("Agent finished gathering at step %d", step)
            return turn.text or ""

        # Otherwise: record the model's turn, run each requested tool, feed results back.
        messages.append(turn.assistant_message)
        for call in turn.tool_calls:
            logger.info("Agent step %d: calling %s(%s)", step, call.name, call.arguments)
            tool = tools.get(call.name)
            output = tool.func(**call.arguments) if tool else f"Error: unknown tool {call.name!r}."
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

    logger.warning("Agent hit max_iterations=%d without finishing", max_iterations)
    return "Triage incomplete: the agent reached its step limit."
