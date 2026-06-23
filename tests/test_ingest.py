"""Tests for the ingest layer: raw Nuclei records -> normalized Finding objects."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingest import parse_nuclei_file, record_to_finding
from app.schemas import Finding, Severity

# Locate the committed sample relative to THIS file (not the cwd), so the test
# passes no matter what directory pytest is launched from.
SAMPLE = Path(__file__).resolve().parents[1] / "data" / "nuclei_sample.jsonl"


def test_record_to_finding_maps_fields():
    """A fully-populated raw record maps onto the right Finding fields."""
    record = {
        "template-id": "CVE-2021-44228",
        "info": {
            "name": "Apache Log4j2 RCE",
            "severity": "critical",
            "description": "desc",
            "tags": ["cve", "rce"],
            "reference": ["https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],
            "classification": {
                "cve-id": ["CVE-2021-44228"],
                "cwe-id": ["CWE-502"],
                "cvss-score": 10.0,
                "cvss-metrics": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
            },
        },
        "host": "app.acme-lab.internal",
        "matched-at": "https://app.acme-lab.internal/api/search",
        "timestamp": "2026-06-22T09:14:03.512847Z",
    }

    f = record_to_finding(record)

    assert f.source == "nuclei"
    assert f.rule_id == "CVE-2021-44228"
    assert f.title == "Apache Log4j2 RCE"
    assert f.severity is Severity.CRITICAL          # mapped string -> enum member
    assert f.cve_ids == ["CVE-2021-44228"]
    assert f.cwe_ids == ["CWE-502"]
    assert f.cvss_score == 10.0
    assert f.location == "https://app.acme-lab.internal/api/search"
    assert f.host == "app.acme-lab.internal"
    assert isinstance(f.timestamp, datetime)        # ISO string coerced to datetime


def test_missing_classification_yields_empty_lists():
    """An info finding with no classification block must not crash."""
    record = {
        "template-id": "http-missing-security-headers",
        "info": {"name": "Missing headers", "severity": "info"},
        "matched-at": "https://app.acme-lab.internal/",
    }

    f = record_to_finding(record)

    assert f.severity is Severity.INFO
    assert f.cve_ids == []
    assert f.cwe_ids == []
    assert f.cvss_score is None


def test_severity_case_is_normalized():
    """Nuclei's severity word in any case maps onto our lowercase enum."""
    record = {"template-id": "x", "info": {"name": "x", "severity": "HIGH"}}
    assert record_to_finding(record).severity is Severity.HIGH


def test_parse_sample_file_returns_six_findings():
    """The committed sample parses into exactly six Finding objects."""
    findings = parse_nuclei_file(SAMPLE)

    assert len(findings) == 6
    assert all(isinstance(f, Finding) for f in findings)

    # the deliberate duplicate pair: same rule_id, two different locations
    headers = [f for f in findings if f.rule_id == "http-missing-security-headers"]
    assert len(headers) == 2
    assert {f.location for f in headers} == {
        "https://app.acme-lab.internal/",
        "https://app.acme-lab.internal/login",
    }


def test_invalid_severity_is_rejected():
    """A severity outside our five allowed values raises ValidationError."""
    record = {"template-id": "x", "info": {"name": "x", "severity": "sev-1"}}
    with pytest.raises(ValidationError):
        record_to_finding(record)


def test_malformed_json_line_raises_valueerror(tmp_path):
    """A broken JSON line raises ValueError naming the line number."""
    bad = tmp_path / "broken.jsonl"
    bad.write_text(
        '{"template-id": "ok", "info": {"name": "n", "severity": "low"}}\n'
        "{ this is not valid json }\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2"):
        parse_nuclei_file(bad)
