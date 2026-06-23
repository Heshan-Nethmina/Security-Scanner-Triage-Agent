"""Streamlit dashboard for the Security Scanner Triage Agent.

Run from the project root:

    streamlit run dashboard/app.py

Loads scanner findings, runs the full pipeline (dedupe -> RAG-grounded agent triage
-> assemble), and shows a prioritized, deduplicated report. Triage makes live LLM
calls, so it runs on a button press rather than on every interaction.
"""

import json
import sys
from pathlib import Path

# Make the `app` package importable when launched via `streamlit run`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from app.ingest import parse_nuclei_file, record_to_finding
from app.llm import LLMClient, LLMConfig
from app.report import build_report
from app.schemas import Finding

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "nuclei_sample.jsonl"
PRIORITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}


def load_findings(uploaded) -> list[Finding]:
    """Parse findings from an uploaded JSONL file, or fall back to the bundled sample."""
    if uploaded is not None:
        lines = uploaded.getvalue().decode("utf-8").splitlines()
        return [record_to_finding(json.loads(ln)) for ln in lines if ln.strip()]
    return parse_nuclei_file(SAMPLE)


st.set_page_config(page_title="Scanner Triage Agent", layout="wide")
st.title("🛡️ Security Scanner Triage Agent")
st.caption("Ingest → dedupe → RAG-grounded agent triage → prioritized report")

uploaded = st.file_uploader("Upload a Nuclei JSONL file (or use the bundled sample)", type=["jsonl"])
findings = load_findings(uploaded)
st.write(f"Loaded **{len(findings)}** findings.")

if st.button("Run triage", type="primary"):
    try:
        client = LLMClient(LLMConfig.from_env())
    except Exception as exc:  # missing key / bad config
        st.error(f"LLM not configured: {exc}")
        st.stop()
    with st.spinner("Triaging (dedupe + agent + RAG lookups)…"):
        st.session_state["report"] = build_report(findings, client)

report = st.session_state.get("report")
if report:
    s = report.summary
    col1, col2, col3 = st.columns(3)
    col1.metric("Findings", s.total_findings)
    col2.metric("Clusters", s.total_clusters)
    col3.metric("Likely false positives", s.likely_false_positives)
    st.write("**By priority:** " + ", ".join(f"{k}: {v}" for k, v in s.by_priority.items()))

    st.divider()
    for item in report.items:
        cluster, triage = item.cluster, item.triage
        rep = cluster.representative
        icon = PRIORITY_ICON.get(triage.priority.value, "")
        header = f"{icon} [{triage.priority.value.upper()}] {rep.title}"
        if triage.likely_false_positive:
            header += "  —  likely false positive"
        with st.expander(header):
            st.markdown(
                f"**Rule:** `{cluster.key}`  |  scanner severity: "
                f"`{rep.severity.value}`  |  confidence: {triage.confidence}"
            )
            st.markdown(f"**Locations ({cluster.size}):** " + ", ".join(cluster.locations or ["-"]))
            st.markdown(f"**Reasoning:** {triage.reasoning}")
            st.markdown(f"**Remediation:** {triage.recommended_remediation}")
else:
    st.info("Click **Run triage** to analyze the loaded findings.")
