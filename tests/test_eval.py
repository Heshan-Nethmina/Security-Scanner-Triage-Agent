"""Tests for the evaluation metrics (pure function -- no LLM)."""

from eval.evaluate import score


def _row(pred_p, exp_p, pred_fp, exp_fp):
    return {"pred_priority": pred_p, "exp_priority": exp_p, "pred_fp": pred_fp, "exp_fp": exp_fp}


def test_score_perfect_predictions():
    rows = [
        _row("critical", "critical", False, False),
        _row("info", "info", True, True),
    ]
    m = score(rows)
    assert m["priority_exact"] == 1.0
    assert m["priority_within_1"] == 1.0
    assert m["fp_precision"] == 1.0
    assert m["fp_recall"] == 1.0


def test_score_adjacent_priorities_and_missed_fp():
    rows = [
        _row("high", "critical", False, False),  # adjacent (off by one), not exact
        _row("low", "info", False, True),        # adjacent priority; missed false positive
    ]
    m = score(rows)
    assert m["priority_exact"] == 0.0
    assert m["priority_within_1"] == 1.0     # both within one level
    assert m["fp_recall"] == 0.0             # the one real FP was missed
    assert m["fp_precision"] is None         # no positive predictions -> undefined


def test_score_empty():
    m = score([])
    assert m["n"] == 0
    assert m["priority_exact"] is None
