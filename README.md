# traffic_llm — can an LLM run a critical, real-time control loop?

A research harness that puts an LLM in charge of traffic management on a
seeded, deterministic road-grid simulator, and measures whether it is
trustworthy on three lenses:

- **Competence** — does traffic flow well, vs. simple baselines?
- **Safety** — does it attempt unsafe actions (conflicting greens, isolating an
  intersection), and does the network gridlock?
- **Robustness** — after a sudden road closure or demand surge, does it recover
  gracefully or catastrophically?

The simulator is a **microsimulation**: a cellular-automaton (Nagel-Schreckenberg)
car-following model where **individual cars** move cell-by-cell with
**aggressiveness** (gap acceptance, dawdling, self-rerouting), crossing
intersections governed by **full NEMA 8-phase dual-ring signals** (protected
lefts, permissive-left/right-on-red via gap acceptance, yellow/all-red
clearance, min/max green). A seeded stream of **road closures and demand surges**
provides the shocks.

## Install

The core simulator is pure-Python stdlib — no install needed to run with the
free mock backend. For the optional Claude backend, visualizer, and tests:

```bash
pip install -r requirements.txt
```

## Quick start (no API key, free)

```bash
# Compare signal-control baselines (incl. the actuated controller) on signals mode:
python run_experiment.py --scenario signals \
    --controllers actuated,maxpressure,fixed,donothing \
    --seeds 0-4 --ticks 250 --decision-interval 5 --demand 1.6 --out runs/demo
```

This prints a scorecard and writes one replayable JSONL per (controller, seed)
plus `runs/demo/scorecard.json`.

### Inspect an edge case

```bash
python visualize.py runs/demo/signals_actuated_seed0.jsonl --tick 120
python visualize.py runs/demo/signals_actuated_seed0.jsonl --animate
```

Each road is a lane with individual cars drawn as dots along its cells; each
intersection is colored by its NEMA signal state (green / yellow / all-red) and
labeled with the active dual-ring phase pair; black dotted = closed. Scrub to
the tick of a shock to see how the controller responded.

## Control modes (scenarios)

Selected with `--scenario`. Each mode changes which actions the controller may
emit (see `traffic_llm/config.py::CONTROL_MODES`):

| scenario             | controller may…                                            |
|----------------------|------------------------------------------------------------|
| `signals`            | call NEMA phase pairs only (`call_phase`)                  |
| `routing`            | issue rerouting/detours only                               |
| `both`               | signals **and** routing                                    |
| `dispatcher`         | full operator: signals, routing, close/open roads, advisories |
| `both_calm`          | `both`, no random shocks (isolates baseline competence)    |
| `dispatcher_stress`  | scripted closure + surge for reproducible robustness demos |

**Baselines** (`--controllers`): `actuated` (vehicle-actuated / "pressure-plate":
hold a phase while it has waiting cars, switch to the heaviest demand, cycle on a
timer when every approach is loaded), `maxpressure` (greedy max-pressure),
`fixed` (fixed-time NEMA cycle), `donothing`. Signals are controlled by calling a
conflict-free NEMA phase pair; the intersection enforces clearance + min-green.

## Using the real Claude backend

```bash
export ANTHROPIC_API_KEY=...
python run_experiment.py --scenario dispatcher --controllers llm \
    --backend claude --seeds 0 --ticks 60 --max-cost 5 --out runs/claude
```

The controller calls Claude (Opus 4.8, adaptive thinking) once per decision
step and gets back **structured actions via tool use** — one tool per allowed
action type with a strict schema, so the model can't emit free-form garbage.
Actions are then validated; unsafe ones are rejected and counted as safety
violations rather than applied (the same boundary a real system would enforce).

### Cost: estimate before you spend

API call count is deterministic:

```
api_calls = n_seeds × ceil(ticks / decision_interval) × n_llm_controllers × n_scenarios
```

Estimate (and exit without any API call):

```bash
python run_experiment.py --scenario dispatcher --controllers llm --backend claude \
    --seeds 0-9 --ticks 500 --estimate-cost
```

`--max-cost <dollars>` aborts a real run if the estimate exceeds the cap. After
a run, actual token usage is recorded per call in the JSONL and surfaced in the
scorecard so estimates self-calibrate. At defaults (~50 decisions/run,
~$0.045/call on Opus 4.8): a 3-seed dev run ≈ $7, a 4-scenario × 10-seed sweep
≈ $90. Levers to cut cost: raise `--decision-interval`, fewer seeds/ticks,
smaller grid, lower `--effort`, or stay on `--backend mock`.

## Plugging in a local model (future)

Backends implement one method (`traffic_llm/llm/backend.py`):

```python
def decide(self, system_prompt, observation, tool_schemas) -> (raw_actions, meta)
```

`MockBackend` (obs-only heuristic, no key) is the template. Add
`traffic_llm/llm/local.py` with a `LocalBackend` (Ollama/etc.) implementing the
same signature and register it in `traffic_llm/llm/__init__.py::make_backend`.
Everything else — metrics, logging, visualization, cost guard — is unchanged, so
you can study how parameter reduction shifts the controller's decisions.

## Layout

```
traffic_llm/
  config.py        grid/sim/signal/scenario/run dataclasses + CONTROL_MODES
  grid.py          road network + BFS routing
  vehicle.py       Car (aggressiveness, route, CA motion state)
  events.py        seeded closures + demand surges
  actions.py       action schemas + safety validation (call_phase, reroute, …)
  micro/           the microsimulation engine:
    movements.py     NEMA 8 movements + dual-ring/barrier compatibility
    cells.py         Nagel-Schreckenberg lane (cells, speed rule)
    signal.py        per-intersection NEMA clearance state machine
    engine.py        MicroSimulator: CA motion + intersection transfers
  simulation.py    re-exports micro.MicroSimulator as Simulator
  metrics.py       competence / safety / robustness scorecard
  logging_io.py    per-tick JSONL (replayable)
  scenarios.py     the 4 control modes + stress presets
  prompts.py       system prompt + observation renderer
  controllers/     baselines (actuated/maxpressure/fixed/donothing) + LLM controller
  llm/             backend protocol + Claude + Mock
  runner.py        run one episode -> scorecard
  cost_estimator.py
run_experiment.py  CLI sweep + scorecard table
visualize.py       lane/car + NEMA-phase renderer / animator
tests/             pytest suite
```

## Tests

```bash
pytest -q
```

Covers grid routing, NEMA movement/phase tables, CA car-following (collision-free
single-lane flow), the full-engine invariants (car conservation, no duplication,
NEMA clearance actually occurring), action validation (incompatible-phase and
node-isolation rejection), seeded determinism, scorecard shape, and the cost math.
