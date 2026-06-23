"""Evaluate triage quality against a small labeled answer key.

Runs the pipeline on the sample findings and compares the agent's priority and
false-positive judgments to hand-labeled ground truth, reporting accuracy and
precision/recall. The labels are expert judgment calls on a tiny set, so the numbers
illustrate the *methodology*; they are not statistically robust.

``score()`` is pure (no LLM) so it can be unit-tested; ``evaluate()`` builds the rows
by running the real pipeline, then scores them.
"""

import json
from pathlib import Path

from app.agent import run_triage_agent
from app.dedupe import dedupe_findings
from app.ingest import parse_nuclei_file
from app.llm import LLMClient
from app.schemas.triage import Priority

_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = _ROOT / "eval" / "labels.jsonl"
SAMPLE_PATH = _ROOT / "data" / "nuclei_sample.jsonl"

# Ordinal index for priorities (critical=0 .. info=4) for the "within one level" metric.
_PRIORITY_INDEX = {p.value: i for i, p in enumerate(Priority)}


def load_labels(path: Path = LABELS_PATH) -> dict[str, dict]:
    """Load ground-truth labels keyed by rule_id."""
    labels: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                row = json.loads(line)
                labels[row["rule_id"]] = row
    return labels


def score(rows: list[dict]) -> dict:
    """Compute metrics from prediction/label rows (pure: no LLM, no I/O).

    Each row has: pred_priority, exp_priority, pred_fp, exp_fp.
    False-positive metrics use the positive class = "is a false positive".
    """
    n = len(rows)
    if n == 0:
        return {"n": 0, "priority_exact": None, "priority_within_1": None,
                "fp_precision": None, "fp_recall": None}

    exact = sum(r["pred_priority"] == r["exp_priority"] for r in rows) / n
    within_1 = sum(
        abs(_PRIORITY_INDEX[r["pred_priority"]] - _PRIORITY_INDEX[r["exp_priority"]]) <= 1
        for r in rows
    ) / n

    tp = sum(1 for r in rows if r["pred_fp"] and r["exp_fp"])
    fp = sum(1 for r in rows if r["pred_fp"] and not r["exp_fp"])
    fn = sum(1 for r in rows if not r["pred_fp"] and r["exp_fp"])
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    return {
        "n": n,
        "priority_exact": exact,
        "priority_within_1": within_1,
        "fp_precision": precision,
        "fp_recall": recall,
    }


def evaluate(client: LLMClient) -> tuple[dict, list[dict]]:
    """Run the pipeline on the sample, compare to labels, and return (metrics, rows)."""
    labels = load_labels()
    clusters = dedupe_findings(parse_nuclei_file(SAMPLE_PATH))

    rows: list[dict] = []
    for cluster in clusters:
        label = labels.get(cluster.key)
        if label is None:
            continue
        result = run_triage_agent(cluster.representative, client)
        rows.append({
            "rule_id": cluster.key,
            "pred_priority": result.priority.value,
            "exp_priority": label["expected_priority"],
            "pred_fp": result.likely_false_positive,
            "exp_fp": label["expected_false_positive"],
        })

    return score(rows), rows


if __name__ == "__main__":
    import logging
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)

    from app.llm import LLMConfig

    metrics, rows = evaluate(LLMClient(LLMConfig.from_env()))

    print(f"Evaluated {metrics['n']} clusters\n")
    print(f"{'RULE':32} {'PRED':9} {'EXP':9} FP pred/exp")
    print("-" * 68)
    for r in rows:
        print(f"{r['rule_id']:32} {r['pred_priority']:9} {r['exp_priority']:9} "
              f"{str(r['pred_fp']):5} / {r['exp_fp']}")

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    print()
    print(f"Priority exact-match accuracy : {pct(metrics['priority_exact'])}")
    print(f"Priority within-one-level     : {pct(metrics['priority_within_1'])}")
    print(f"False-positive precision      : {pct(metrics['fp_precision'])}")
    print(f"False-positive recall         : {pct(metrics['fp_recall'])}")
