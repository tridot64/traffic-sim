# CLAUDE.md — traffic_llm

Project context for Claude Code. Auto-loaded each session so work resumes where
it left off. Keep the **Current status** section updated as the source of truth.

## What this is
A research harness asking: **can an LLM be trusted in a critical, real-time
control loop?** Testbed = traffic management. We score controllers on
**competence / safety / robustness**.

## Engine (microscopic)
- Cellular-automaton (Nagel-Schreckenberg) car-following on a grid of one-way
  lanes (cells). Cars have `aggressiveness` (gap acceptance / dawdle / reroute).
- **Full NEMA 8-phase dual-ring signals**: protected lefts, permissive-left +
  right-on-red via gap acceptance, green→yellow→all-red clearance, min/max green
  with **max-out** (forced switch so an approach can't starve).
- Seeded events: random + scripted **road closures** and **demand surges**.
- **Destination hotspots**: time-varying attractors that pull disproportionate
  trips; surfaced in the observation.
- **Per-road speed limits + length** (`Segment.vmax/length`, drawn as line width
  in the visualizer). Set via `GridConfig.speed_limits` overrides or a custom map.
- **Custom road maps** (`maps.py`, `MapConfig`): grid-subgraph topologies — pick
  which roads exist, direction (one-way), speed, length. Presets `arterial`,
  `oneway_loop`, `tiered`/`tiered_big` (seeded random freeway/expressway/street
  hierarchy via `tiered_map()`); JSON via `load_map`; CLI `--map`/`--map-file`.
  Nodes stay on the integer lattice so NEMA headings remain valid.
- Fully deterministic from `(RunConfig + seed)`.

## Code map
- `traffic_llm/micro/` — engine: `movements.py` (NEMA tables), `cells.py` (CA
  lane), `signal.py` (clearance state machine), `engine.py` (MicroSimulator).
- `simulation.py` re-exports `MicroSimulator as Simulator`.
- `controllers/` — `baselines.py` (actuated / maxpressure / fixed / donothing;
  `actuated_choice()` is the shared vehicle-actuated rule), `supervised.py`
  (LLM-tunes-actuated hybrid: `bias_phase` nudge / `pin_phase` strongarm; null
  supervisor == actuated), `llm.py` (per-tick LLM controller).
- `actions.py` — action schemas + safety validation (`call_phase`, reroute,
  close/open, advisory). `prompts.py` — system prompts + observation renderer +
  supervisor schemas. `llm/` — backend protocol + Claude + Mock.
- `runner.py` (one episode → scorecard), `metrics.py`, `logging_io.py` (per-tick
  JSONL), `cost_estimator.py`, `run_experiment.py` (CLI), `visualize.py`.

## How to run (python3, not python)
```bash
python3 -m pytest -q                              # 36 tests
# free baselines + animation:
python3 run_experiment.py --scenario dispatcher_hotspots \
  --controllers actuated,maxpressure,fixed,donothing \
  --rows 5 --cols 5 --seeds 0-1 --ticks 250 --decision-interval 5 --demand 2.0 --out runs/algos
python3 visualize.py runs/algos/dispatcher_hotspots_actuated_seed0.jsonl --animate --save out.gif
# LLM (costs money): add --controllers llm  or  supervised  + --backend claude --max-cost N
python3 run_experiment.py ... --backend claude --estimate-cost   # dry-run cost, no API calls
```
- Anthropic key lives in `.secret_key` (gitignored): `export ANTHROPIC_API_KEY=$(cat .secret_key)`.
- Always run `--estimate-cost` and confirm before any `--backend claude` run.

## Current status (update me)
- Engine, NEMA signals, 4 baselines, hotspots, cost guard, visualizer: DONE, 36
  tests green.
- Actuated **starvation/"locked cells" bug FIXED** (added max-out). Closures are
  modelled; rerouting is reactive (1-hop at stop line) + spawn-time avoidance.
- **Supervised hybrid built + RUN live, 3 iterations.** Engine fixes landed:
  advisory now DECAYS (TTL 40, no accumulation), proactive rerouting added
  (divert when any remaining-route segment is closed), supervised base now ==
  actuated exactly (incl. worst-jam routing), and bias/pin directives are logged.
  Those fixes also lifted all baselines ~25% (actuated 1.22 -> 1.52).
- **Clean supervised result** (`runs/sup_claude3/`): LLM issued 69 bias_phase +
  71 advisories, 0 rejected, biasing through-phases toward the hotspot corridors
  (sensible intent). Still DEGRADED actuated: thru 1.21 vs 1.52 (-20%). Coarse
  global biases disrupt the local per-intersection optimum.
- Consistent across 3 experiments: with a proper interface the LLM is SAFE
  (0 invalid/unsafe actions) but NOT net-positive for this real-time control
  task. A good local feedback algorithm (actuated) is a strong baseline.
  See `runs/micro_llm/FINDINGS.md` (per-tick).

## Likely next steps
- Optional supervisor tuning: smaller bias weights, fewer interventions, or
  pin_phase only during surges — to see if a lighter touch ever helps.
- GitHub: push the latest (engine fixes + findings). Repo: tridot64/traffic-sim.
