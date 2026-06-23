"""Dedupe: collapse duplicate findings into clusters before triage."""

from app.dedupe.dedupe import dedupe_findings

__all__ = ["dedupe_findings"]
