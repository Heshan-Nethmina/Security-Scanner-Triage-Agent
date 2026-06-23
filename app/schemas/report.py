"""Report models: the assembled, prioritized output of the whole pipeline."""

from pydantic import BaseModel

from app.schemas.cluster import FindingCluster
from app.schemas.triage import TriageResult


class TriagedCluster(BaseModel):
    """One deduplicated cluster together with its triage decision."""

    cluster: FindingCluster
    triage: TriageResult


class ReportSummary(BaseModel):
    """Headline counts for the report."""

    total_findings: int
    total_clusters: int
    by_priority: dict[str, int]      # priority value -> number of clusters
    likely_false_positives: int


class Report(BaseModel):
    """The final assembled report: a summary plus prioritized triaged clusters."""

    summary: ReportSummary
    items: list[TriagedCluster]      # highest priority first
