"""Predict (and later measure) the API spend of a Claude-backed experiment.

API call count is deterministic; token volume is estimated with transparent,
tunable assumptions. Only LLM controllers cost money — baselines are free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

# (input $/1M, output $/1M)
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Output token volume scales with thinking effort.
_EFFORT_OUTPUT = {"low": 0.6, "medium": 1.0, "high": 1.6, "xhigh": 2.0, "max": 2.6}


@dataclass(frozen=True)
class TokenAssumptions:
    system_tokens: int = 2500     # static system prompt + tool schemas (prompt-cached)
    obs_tokens: int = 1500        # fresh per-call observation
    output_expected: int = 1400   # adaptive thinking + tool calls at effort=medium
    output_low: int = 600
    output_high: int = 3200


def decisions_per_run(ticks: int, decision_interval: int) -> int:
    return math.ceil(ticks / max(1, decision_interval))


def estimate(
    *,
    ticks: int,
    decision_interval: int,
    n_seeds: int = 1,
    n_scenarios: int = 1,
    n_llm_controllers: int = 1,
    model: str = "claude-opus-4-8",
    effort: str = "medium",
    assumptions: Optional[TokenAssumptions] = None,
    calls_override: Optional[int] = None,
    prefixes_override: Optional[int] = None,
) -> dict[str, Any]:
    a = assumptions or TokenAssumptions()
    in_price, out_price = PRICING.get(model, PRICING["claude-opus-4-8"])
    eff = _EFFORT_OUTPUT.get(effort, 1.0)

    per_run = decisions_per_run(ticks, decision_interval)
    # ``calls_override`` lets callers account for controllers that consult the
    # LLM less than once per decision (e.g. the supervised hybrid every 4th).
    api_calls = (calls_override if calls_override is not None
                 else per_run * n_seeds * n_scenarios * n_llm_controllers)

    # input: observation is fresh every call; the system prompt is written once
    # per (scenario x controller x seed) prefix and read at ~0.1x thereafter.
    n_prefixes = (prefixes_override if prefixes_override is not None
                  else n_seeds * n_scenarios * n_llm_controllers)
    cache_writes = n_prefixes
    cache_reads = max(0, api_calls - n_prefixes)
    fresh_input = api_calls * a.obs_tokens
    cached_input_effective = a.system_tokens * (1.25 * cache_writes + 0.10 * cache_reads)
    est_input_tokens = fresh_input + a.system_tokens * api_calls  # nominal (uncached) count

    input_cost = (fresh_input + cached_input_effective) / 1e6 * in_price

    def out_cost(per_call: float) -> float:
        return (api_calls * per_call * eff) / 1e6 * out_price

    low = input_cost + out_cost(a.output_low)
    expected = input_cost + out_cost(a.output_expected)
    high = input_cost + out_cost(a.output_high)

    return {
        "api_calls": api_calls,
        "decisions_per_run": per_run,
        "model": model,
        "effort": effort,
        "est_input_tokens": int(est_input_tokens),
        "est_output_tokens": int(api_calls * a.output_expected * eff),
        "cost_low": round(low, 2),
        "cost_expected": round(expected, 2),
        "cost_high": round(high, 2),
    }


def actual_cost(tokens_in: int, tokens_out: int, tokens_cache_read: int,
                model: str = "claude-opus-4-8") -> float:
    in_price, out_price = PRICING.get(model, PRICING["claude-opus-4-8"])
    fresh_in = max(0, tokens_in - tokens_cache_read)
    cost = (fresh_in / 1e6 * in_price
            + tokens_cache_read / 1e6 * in_price * 0.1
            + tokens_out / 1e6 * out_price)
    return round(cost, 4)


def format_estimate(est: dict[str, Any]) -> str:
    return (
        f"API calls: {est['api_calls']:,}  ({est['decisions_per_run']} decisions/run)\n"
        f"Model: {est['model']}  effort={est['effort']}\n"
        f"Est. tokens: ~{est['est_input_tokens']:,} in / ~{est['est_output_tokens']:,} out\n"
        f"Estimated cost: ${est['cost_low']} (low) / "
        f"${est['cost_expected']} (expected) / ${est['cost_high']} (high)"
    )


if __name__ == "__main__":  # quick standalone estimate
    import argparse

    p = argparse.ArgumentParser(description="Estimate Claude API cost for a run.")
    p.add_argument("--ticks", type=int, default=500)
    p.add_argument("--decision-interval", type=int, default=10)
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--scenarios", type=int, default=1)
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--effort", default="medium")
    args = p.parse_args()
    print(format_estimate(estimate(
        ticks=args.ticks, decision_interval=args.decision_interval,
        n_seeds=args.seeds, n_scenarios=args.scenarios,
        model=args.model, effort=args.effort)))
