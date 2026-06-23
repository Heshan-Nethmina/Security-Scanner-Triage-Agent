"""Ingest: parse + normalize raw scanner output into ``Finding`` objects."""

from app.ingest.nuclei import parse_nuclei_file, record_to_finding

__all__ = ["parse_nuclei_file", "record_to_finding"]
