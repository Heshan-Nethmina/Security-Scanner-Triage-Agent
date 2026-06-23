"""``FindingCluster``: a group of duplicate/related findings collapsed into one unit.

Triage runs once per cluster instead of once per finding -- saving repeated LLM calls
and de-cluttering the report -- while the cluster keeps every member so the report can
still list all affected locations.
"""

from pydantic import BaseModel

from app.schemas.finding import Finding


class FindingCluster(BaseModel):
    """One cluster of findings considered "the same issue"."""

    key: str                 # the dedup key shared by all members (e.g. the rule_id)
    findings: list[Finding]  # all findings in the cluster (at least one)

    @property
    def representative(self) -> Finding:
        """The single finding used to triage the whole cluster."""
        return self.findings[0]

    @property
    def size(self) -> int:
        """How many raw findings this cluster collapsed."""
        return len(self.findings)

    @property
    def locations(self) -> list[str]:
        """Every distinct location the issue was found at."""
        return sorted({f.location for f in self.findings if f.location})
