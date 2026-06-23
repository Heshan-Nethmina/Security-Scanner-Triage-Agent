"""The normalized ``Finding`` model: the clean, scanner-agnostic shape that every
security finding is converted into.

This is the *target* shape. Mapping a specific scanner's messy output onto it
(e.g. Nuclei's nested JSON) is the job of the parsers in ``app/ingest`` -- this
module only defines the schema and its validation rules.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """Normalized severity scale, shared by all scanners.

    Subclassing ``str`` means each member *is* a string (it serializes to e.g.
    ``"critical"`` in JSON) while remaining a restricted, validated set: any
    value outside these five is rejected by Pydantic.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    """One normalized security finding.

    Build it with keyword arguments; Pydantic validates and coerces every field,
    or raises ``ValidationError`` describing exactly what was wrong.
    """

    # Reject unknown field names instead of silently ignoring them, so a typo
    # such as ``cve_id=`` (missing the 's') fails loudly at construction.
    model_config = ConfigDict(extra="forbid")

    # --- always present ---
    source: str          # which scanner produced this, e.g. "nuclei"
    rule_id: str         # detection rule id; the "kind of finding" -> key for dedup
    title: str           # human-readable name
    severity: Severity   # normalized info -> critical

    # --- optional context (None when the scanner didn't provide it) ---
    description: str | None = None
    location: str | None = None   # where it was found: a URL, or "file:line" for Semgrep
    host: str | None = None

    # --- security identifiers (frequently partial or missing) ---
    # Lists use default_factory=list so each instance gets its OWN fresh empty
    # list. (Sharing one mutable default object across instances is a classic
    # Python bug; the factory sidesteps it.)
    cve_ids: list[str] = Field(default_factory=list)
    cwe_ids: list[str] = Field(default_factory=list)
    cvss_score: float | None = None
    cvss_vector: str | None = None

    # --- extras ---
    tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    extracted_results: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None  # an ISO-8601 string is coerced to a datetime
