"""Assemble the end-to-end report: ingest -> dedupe -> triage each cluster -> sort.

This wires the pipeline into a single prioritized artifact (plus a Markdown renderer).
Triage runs once per cluster (dedupe already collapsed duplicates), most urgent first.
"""

from collections import Counter
from collections.abc import Callable

from app.agent import run_triage_agent
from app.dedupe import dedupe_findings
from app.llm import LLMClient
from app.schemas import Finding, Report, ReportSummary, TriageResult, TriagedCluster
from app.schemas.triage import Priority

# Sort order for priorities (most urgent first).
_PRIORITY_RANK = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
    Priority.INFO: 4,
}


def build_report(
    findings: list[Finding],
    client: LLMClient,
    triage: Callable[[Finding, LLMClient], TriageResult] = run_triage_agent,
) -> Report:
    """Dedupe findings, triage each cluster once, and assemble a prioritized report."""
    clusters = dedupe_findings(findings)
    items = [
        TriagedCluster(cluster=c, triage=triage(c.representative, client))
        for c in clusters
    ]
    items.sort(key=lambda it: _PRIORITY_RANK[it.triage.priority])

    summary = ReportSummary(
        total_findings=sum(c.size for c in clusters),
        total_clusters=len(clusters),
        by_priority=dict(Counter(it.triage.priority.value for it in items)),
        likely_false_positives=sum(1 for it in items if it.triage.likely_false_positive),
    )
    return Report(summary=summary, items=items)


def render_markdown(report: Report) -> str:
    """Render a Report as a human-readable Markdown document."""
    s = report.summary
    order = [p.value for p in Priority]
    by_pri = ", ".join(f"{p}: {s.by_priority[p]}" for p in order if p in s.by_priority)

    lines = [
        "# Security Triage Report",
        "",
        f"- **Findings:** {s.total_findings} -> **clusters:** {s.total_clusters}",
        f"- **Likely false positives:** {s.likely_false_positives}",
        f"- **By priority:** {by_pri}",
        "",
        "---",
        "",
    ]
    for it in report.items:
        c, t = it.cluster, it.triage
        rep = c.representative
        fp = " _(likely false positive)_" if t.likely_false_positive else ""
        lines += [
            f"## [{t.priority.value.upper()}] {rep.title}{fp}",
            f"- **Rule:** `{c.key}` | scanner severity: `{rep.severity.value}` "
            f"| confidence: {t.confidence}",
            f"- **Locations ({c.size}):** " + ", ".join(c.locations or ["-"]),
            f"- **Reasoning:** {t.reasoning}",
            f"- **Remediation:** {t.recommended_remediation}",
            "",
        ]
    return "\n".join(lines)
