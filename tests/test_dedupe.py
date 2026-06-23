"""Tests for dedupe/clustering (pure logic -- no LLM, no network)."""

from app.dedupe import dedupe_findings
from app.schemas import Finding


def _f(rule_id: str, location: str, host: str | None = None) -> Finding:
    return Finding(
        source="nuclei",
        rule_id=rule_id,
        title=rule_id,
        severity="info",
        location=location,
        host=host,
    )


def test_dedupe_groups_by_rule_id_preserving_order():
    findings = [
        _f("rule-a", "http://x/1"),
        _f("rule-b", "http://x/2"),
        _f("rule-a", "http://x/3"),
    ]

    clusters = dedupe_findings(findings)

    assert [c.key for c in clusters] == ["rule-a", "rule-b"]  # first-seen order kept
    a = clusters[0]
    assert a.size == 2
    assert a.locations == ["http://x/1", "http://x/3"]        # both locations, sorted
    assert a.representative.rule_id == "rule-a"
    assert clusters[1].size == 1                              # singleton stays size 1


def test_dedupe_accepts_a_custom_key():
    # Same rule, different hosts -> keep them separate by clustering on rule_id + host.
    findings = [_f("rule-a", "u1", host="h1"), _f("rule-a", "u2", host="h2")]

    clusters = dedupe_findings(findings, key=lambda f: f"{f.rule_id}|{f.host}")

    assert len(clusters) == 2
