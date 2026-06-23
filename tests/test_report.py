"""Tests for report assembly (offline: triage is faked, so no LLM/network)."""

from app.report import build_report, render_markdown
from app.schemas import Finding, Priority, TriageResult


def _f(rule_id: str, location: str) -> Finding:
    return Finding(source="nuclei", rule_id=rule_id, title=rule_id, severity="info", location=location)


def _fake_triage(finding: Finding, client=None) -> TriageResult:
    """Deterministic triage keyed on rule_id, so assembly is testable without an LLM."""
    table = {
        "a-low": (Priority.LOW, False),
        "b-crit": (Priority.CRITICAL, False),
        "c-noise": (Priority.INFO, True),
    }
    priority, fp = table[finding.rule_id]
    return TriageResult(
        priority=priority,
        likely_false_positive=fp,
        confidence=0.9,
        reasoning="r",
        recommended_remediation="fix",
    )


def test_build_report_dedupes_sorts_and_summarizes():
    findings = [
        _f("a-low", "u1"),
        _f("b-crit", "u2"),
        _f("a-low", "u3"),    # duplicate of a-low
        _f("c-noise", "u4"),
    ]

    report = build_report(findings, client=None, triage=_fake_triage)

    assert report.summary.total_findings == 4
    assert report.summary.total_clusters == 3
    # sorted most-urgent first: critical, then low, then info
    assert [it.triage.priority for it in report.items] == [
        Priority.CRITICAL, Priority.LOW, Priority.INFO,
    ]
    low = next(it for it in report.items if it.cluster.key == "a-low")
    assert low.cluster.size == 2
    assert report.summary.by_priority == {"critical": 1, "low": 1, "info": 1}
    assert report.summary.likely_false_positives == 1


def test_render_markdown_has_headline_and_priority_tags():
    report = build_report([_f("b-crit", "u1")], client=None, triage=_fake_triage)
    md = render_markdown(report)
    assert "# Security Triage Report" in md
    assert "[CRITICAL]" in md
