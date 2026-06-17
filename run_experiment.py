#!/usr/bin/env python3
"""Run traffic-management experiments: sweep controllers x seeds on a scenario,
write per-tick logs, and print a competence/safety/robustness scorecard.

Examples
--------
  # Free comparison (mock LLM + baselines) on the 'both' scenario:
  python run_experiment.py --scenario both --controllers llm,maxpressure,fixed,donothing \
      --backend mock --seeds 0-4 --ticks 300 --out runs/demo

  # Estimate Claude cost without spending anything:
  python run_experiment.py --scenario dispatcher --controllers llm --backend claude \
      --seeds 0-9 --ticks 500 --estimate-cost

  # Real Claude run with a spend guard:
  python run_experiment.py --scenario dispatcher --controllers llm --backend claude \
      --seeds 0 --ticks 60 --max-cost 5 --out runs/claude
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traffic_llm.config import GridConfig, RunConfig, SimConfig
from traffic_llm.cost_estimator import TokenAssumptions, estimate, format_estimate
from traffic_llm.runner import run_single
from traffic_llm.scenarios import SCENARIOS, get_scenario


def parse_seeds(spec: str) -> list[int]:
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            seeds.extend(range(int(a), int(b) + 1))
        elif part:
            seeds.append(int(part))
    return seeds


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", default="both", choices=sorted(SCENARIOS))
    p.add_argument("--controllers", default="actuated,maxpressure,fixed,donothing",
                   help="comma list: supervised,llm,actuated,maxpressure,fixed,donothing")
    p.add_argument("--backend", default="mock", choices=["mock", "claude"])
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--effort", default="medium")
    p.add_argument("--seeds", default="0-2")
    p.add_argument("--ticks", type=int, default=300)
    p.add_argument("--decision-interval", type=int, default=10)
    p.add_argument("--rows", type=int, default=5)
    p.add_argument("--cols", type=int, default=5)
    p.add_argument("--map", default=None, help="custom map preset (arterial, oneway_loop)")
    p.add_argument("--map-file", default=None, help="path to a custom map JSON")
    p.add_argument("--demand", type=float, default=4.0)
    p.add_argument("--out", default=None, help="output dir for JSONL logs + scorecard")
    p.add_argument("--estimate-cost", action="store_true",
                   help="print the API call count + $ estimate and exit (no API calls)")
    p.add_argument("--max-cost", type=float, default=None,
                   help="abort a real Claude run if the estimate exceeds this $ cap")
    args = p.parse_args()

    controllers = [c.strip() for c in args.controllers.split(",") if c.strip()]
    seeds = parse_seeds(args.seeds)

    # Per-call cadence: 'llm' consults every decision; 'supervised' every Nth.
    SUP_INTERVAL = 4
    import math as _math
    per_run = _math.ceil(args.ticks / max(1, args.decision_interval))
    n_llm = sum(1 for c in controllers if c == "llm")
    n_sup = sum(1 for c in controllers if c == "supervised")
    n_spending = n_llm + n_sup
    calls = len(seeds) * (n_llm * per_run + n_sup * _math.ceil(per_run / SUP_INTERVAL))
    prefixes = len(seeds) * n_spending

    est = estimate(
        ticks=args.ticks, decision_interval=args.decision_interval,
        n_seeds=len(seeds), n_scenarios=1, model=args.model, effort=args.effort,
        assumptions=TokenAssumptions(), calls_override=calls, prefixes_override=prefixes,
    )

    # --- cost gating (only matters for the Claude backend) ---
    if args.backend == "claude" and n_spending:
        print("=== Claude cost estimate ===")
        print(format_estimate(est))
        if n_sup:
            print(f"(supervised consults the LLM every {SUP_INTERVAL}th decision)")
        print("============================")
    if args.estimate_cost:
        if args.backend != "claude" or not n_spending:
            print("(no Claude/LLM runs requested — $0.00)")
        return 0
    if (args.backend == "claude" and n_spending and args.max_cost is not None
            and est["cost_expected"] > args.max_cost):
        print(f"ABORT: estimated ${est['cost_expected']} exceeds --max-cost "
              f"${args.max_cost}. Lower seeds/ticks, raise --decision-interval, "
              f"or use --backend mock.", file=sys.stderr)
        return 2

    grid = GridConfig(rows=args.rows, cols=args.cols)
    sim_cfg = SimConfig(ticks=args.ticks, decision_interval=args.decision_interval,
                        demand_rate=args.demand)
    scenario = get_scenario(args.scenario)
    road_map = None
    if args.map_file:
        from traffic_llm.maps import load_map
        road_map = load_map(args.map_file)
    elif args.map:
        from traffic_llm.maps import get_map
        road_map = get_map(args.map)

    results: dict[str, list[dict]] = {c: [] for c in controllers}
    for controller in controllers:
        for seed in seeds:
            cfg = RunConfig(grid=grid, sim=sim_cfg, scenario=scenario, road_map=road_map,
                            controller=controller, backend=args.backend,
                            model=args.model, effort=args.effort, seed=seed)
            log_path = None
            if args.out:
                log_path = os.path.join(args.out, f"{args.scenario}_{controller}_seed{seed}.jsonl")
            sc = run_single(cfg, log_path=log_path)
            results[controller].append(sc)
            print(f"  ran {controller:<12} seed={seed}  "
                  f"throughput={sc['competence']['throughput_per_tick']}  "
                  f"mean_wait={sc['competence']['mean_wait']}  "
                  f"gridlock={sc['safety']['gridlock_fraction']}  "
                  f"rejected={sc['safety']['rejected_total']}")

    summary = aggregate(results)
    print_table(summary)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        out = {"scenario": args.scenario, "seeds": seeds, "backend": args.backend,
               "estimate": est, "summary": summary}
        with open(os.path.join(args.out, "scorecard.json"), "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nwrote logs + scorecard to {args.out}/")
    return 0


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 3) if xs else None


def aggregate(results: dict[str, list[dict]]) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for controller, runs in results.items():
        if not runs:
            continue
        summary[controller] = {
            "throughput_per_tick": _mean([r["competence"]["throughput_per_tick"] for r in runs]),
            "mean_travel": _mean([r["competence"]["mean_travel"] for r in runs]),
            "mean_wait": _mean([r["competence"]["mean_wait"] for r in runs]),
            "mean_queue": _mean([r["competence"]["mean_queue"] for r in runs]),
            "gridlock_fraction": _mean([r["safety"]["gridlock_fraction"] for r in runs]),
            "rejected_total": _mean([r["safety"]["rejected_total"] for r in runs]),
            "mean_recovery_ticks": _mean([r["robustness"]["mean_recovery_ticks"] for r in runs]),
            "unrecovered_shocks": _mean([r["robustness"]["unrecovered_shocks"] for r in runs]),
            "llm_failures": _mean([r["decisions"]["llm_failures"] for r in runs]),
        }
    return summary


def print_table(summary: dict[str, dict]) -> None:
    cols = [
        ("controller", "controller", 12),
        ("throughput_per_tick", "thru/tick", 10),
        ("mean_travel", "travel", 8),
        ("mean_wait", "wait", 8),
        ("mean_queue", "queue", 8),
        ("gridlock_fraction", "gridlock", 9),
        ("rejected_total", "rejects", 8),
        ("mean_recovery_ticks", "recover", 8),
    ]
    print("\n=== scorecard (means across seeds) ===")
    header = "  ".join(f"{label:<{w}}" for _, label, w in cols)
    print(header)
    print("-" * len(header))
    for controller, m in summary.items():
        row = []
        for key, _, w in cols:
            val = controller if key == "controller" else m.get(key)
            row.append(f"{('' if val is None else val):<{w}}")
        print("  ".join(row))


if __name__ == "__main__":
    raise SystemExit(main())
