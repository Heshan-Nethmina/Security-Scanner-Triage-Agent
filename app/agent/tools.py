"""Tools the triage agent can call, and a tiny abstraction describing them.

A "tool" here is a plain Python function plus a JSON-Schema description of its
arguments. The description is what we advertise to the model; the function is what
*we* run when the model asks for it. In Phase 5 these are stubs (canned data) so we
can learn the agent loop; Phase 6 swaps their insides for real CVE/CWE lookups via
RAG -- without changing the agent loop or the tool's signature.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    """A callable the model may invoke, plus the schema we advertise to it."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments object
    func: Callable[..., str]

    def to_openai(self) -> dict:
        """Render the tool in the OpenAI/Groq ``tools`` format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def lookup_cve(cve_id: str) -> str:
    """STUB: return canned reference text for a CVE id.

    Phase 6 replaces the body with real retrieval over NVD/CWE data; the signature
    and return type stay identical, so the agent loop never has to change.
    """
    canned = {
        "CVE-2021-44228": (
            "CVE-2021-44228 (Log4Shell): Apache Log4j2 JNDI lookup leading to remote "
            "code execution. CVSS 10.0 (critical). Affects Log4j2 2.0-beta9 through "
            "2.15.0. Fixed in 2.17.1 -- note 2.15.0 and 2.16.0 had follow-up issues. "
            "Weakness: CWE-502 (deserialization of untrusted data). Widely exploited."
        ),
    }
    return canned.get(
        cve_id,
        f"No reference data found for {cve_id} (the stub only knows a few CVEs so far).",
    )


# The stub tool the agent will be offered.
LOOKUP_CVE_TOOL = Tool(
    name="lookup_cve",
    description=(
        "Look up authoritative reference details (description, CVSS score, affected "
        "versions, and the fixed version) for a specific CVE id. Call this before "
        "judging any finding that has a CVE id, rather than relying on memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cve_id": {
                "type": "string",
                "description": "The CVE identifier, e.g. CVE-2021-44228.",
            }
        },
        "required": ["cve_id"],
    },
    func=lookup_cve,
)

# Name -> Tool registry the loop will dispatch through.
TOOLS: dict[str, Tool] = {LOOKUP_CVE_TOOL.name: LOOKUP_CVE_TOOL}
