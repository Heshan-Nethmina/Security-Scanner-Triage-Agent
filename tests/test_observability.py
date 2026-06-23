"""Test the usage accumulator (pure -- no client/network needed)."""

import pytest

from app.llm.client import LLMResult, UsageStats


def test_usage_stats_accumulates():
    u = UsageStats()
    u.add(LLMResult("a", "groq", "m", 10, 5, 0.5, 0.001))
    u.add(LLMResult("b", "groq", "m", 20, 10, 0.7, None))  # unknown cost counts as 0

    assert u.calls == 2
    assert u.input_tokens == 30
    assert u.output_tokens == 15
    assert u.cost_usd == pytest.approx(0.001)
    assert u.latency_s == pytest.approx(1.2)
