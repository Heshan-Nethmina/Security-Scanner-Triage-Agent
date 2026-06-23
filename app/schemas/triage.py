"""The ``TriageResult`` model: the structured decision the triage step produces
for one finding -- a recommended priority, a false-positive judgment, confidence,
reasoning, and remediation guidance.

``priority`` is intentionally separate from the scanner's ``Severity`` (in
finding.py): it is the *triage's own* judgment, which may differ from the raw label.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Priority(str, Enum):
    """The triage's recommended action priority (its own judgment)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TriageResult(BaseModel):
    """Structured triage decision for a single finding."""

    priority: Priority                       # recommended priority (may differ from severity)
    likely_false_positive: bool              # true if this looks like noise / a false alarm
    confidence: float = Field(ge=0.0, le=1.0)  # 0..1; lets us surface low-confidence calls
    reasoning: str                           # brief justification (explainability)
    recommended_remediation: str            # concise "how to fix" -- never how to attack
