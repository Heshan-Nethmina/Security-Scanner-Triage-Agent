"""Single-shot triage: turn one ``Finding`` into a structured ``TriageResult``.

This is the pre-agent version (Phase 4): exactly one LLM call, no tools, no loop.
Phase 5 will wrap this reasoning in an agent that can look things up (e.g. CVE
details) before deciding. Keeping it a plain function now keeps the mechanics clear.
"""

from app.llm import LLMClient
from app.schemas import Finding, TriageResult

# The system prompt carries behaviour + the safety boundary. The output *structure*
# is enforced separately by complete_structured() (which appends the JSON Schema).
TRIAGE_SYSTEM = """\
You are a security triage assistant. For each scanner finding you receive, decide:

- priority: the real-world action priority (critical/high/medium/low/info), based on
  exploitability and impact -- NOT just the scanner's label. You may disagree with
  the scanner's severity; if you do, say why in your reasoning.
- likely_false_positive: true if the finding is probably noise or a false alarm
  (for example, informational technology-detection, or a check that rarely indicates
  real risk).
- confidence: your confidence from 0 to 1.
- reasoning: a brief, specific justification.
- recommended_remediation: concise guidance on HOW TO FIX or mitigate the issue.

Safety: only ever explain how to fix or mitigate. Never produce exploit code,
payloads, or step-by-step attack instructions.
"""


def triage_finding(
    finding: Finding,
    client: LLMClient,
    max_retries: int = 2,
) -> TriageResult:
    """Run one LLM call to triage a single finding into a ``TriageResult``.

    The finding is handed to the model as JSON so it can see the scanner's own
    severity, CVE/CWE ids, and location, and decide its own priority accordingly.
    """
    prompt = (
        "Triage this security scanner finding and return your decision:\n\n"
        f"{finding.model_dump_json(indent=2)}"
    )
    return client.complete_structured(
        prompt=prompt,
        schema=TriageResult,
        system=TRIAGE_SYSTEM,
        max_retries=max_retries,
    )
