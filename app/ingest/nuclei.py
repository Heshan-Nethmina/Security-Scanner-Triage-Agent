"""Parse raw Nuclei JSONL output into normalized ``Finding`` objects.

Nuclei emits JSON Lines -- one finding object per line. This module reads that
file and maps each scanner-specific record onto the scanner-agnostic ``Finding``
schema. All Nuclei-specific field knowledge lives here, nowhere else.
"""

import json
from pathlib import Path

from app.schemas import Finding


def record_to_finding(record: dict) -> Finding:
    """Map one raw Nuclei record (a parsed JSON object) onto a ``Finding``.

    Nuclei nests most data under ``info`` (and under ``info.classification`` for
    the security ids) and uses kebab-case keys like ``template-id``. We pull those
    out with ``.get()`` so an absent *optional* key becomes ``None``/``[]`` rather
    than crashing, then hand the result to ``Finding`` for validation.
    """
    info = record.get("info", {})
    classification = info.get("classification") or {}  # absent on info-level findings

    return Finding(
        source="nuclei",
        rule_id=record.get("template-id"),
        title=info.get("name"),
        # Nuclei already uses our info..critical words; just normalize the case.
        # (A scanner with different words -- e.g. Semgrep's ERROR/WARNING -- would
        #  do its own mapping in its own parser.)
        severity=str(info.get("severity", "info")).lower(),
        description=info.get("description"),
        location=record.get("matched-at"),
        host=record.get("host"),
        cve_ids=classification.get("cve-id", []),
        cwe_ids=classification.get("cwe-id", []),
        cvss_score=classification.get("cvss-score"),
        cvss_vector=classification.get("cvss-metrics"),
        tags=info.get("tags", []),
        references=info.get("reference", []),
        extracted_results=record.get("extracted-results", []),
        timestamp=record.get("timestamp"),
    )


def parse_nuclei_file(path: str | Path) -> list[Finding]:
    """Read a Nuclei JSONL file and return a list of normalized ``Finding``s.

    Reads one line at a time (the JSONL format), tolerating blank lines. A
    malformed JSON line raises ``ValueError`` naming the line number; a record
    that violates the schema raises Pydantic's ``ValidationError``.
    """
    path = Path(path)
    findings: list[Finding] = []

    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue  # skip blank lines (common at end of file)
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} line {line_number}: invalid JSON ({exc})") from exc
            findings.append(record_to_finding(record))

    return findings
