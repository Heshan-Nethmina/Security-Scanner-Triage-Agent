"""Collapse duplicate findings into clusters before triage.

The default similarity signal is exact: findings that share a ``rule_id`` are the same
kind of issue (often one rule firing at different locations). Grouping by that key is
deterministic and cheap. A semantic pass -- embedding findings and merging near
duplicates that have *different* rule_ids -- is a possible later extension.
"""

from collections.abc import Callable

from app.schemas import Finding, FindingCluster


def dedupe_findings(
    findings: list[Finding],
    key: Callable[[Finding], str] = lambda f: f.rule_id,
) -> list[FindingCluster]:
    """Group findings into clusters by ``key`` (default: ``rule_id``).

    Insertion order is preserved: clusters appear in the order their first member was
    seen, and members keep their original order within a cluster.
    """
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(key(finding), []).append(finding)
    return [FindingCluster(key=k, findings=fs) for k, fs in groups.items()]
