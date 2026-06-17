#!/usr/bin/env python3
"""Render a micro-engine run from its per-tick JSONL log — for inspecting edge
cases at the level of individual cars and NEMA phases.

  python visualize.py runs/demo/signals_actuated_seed0.jsonl --tick 120
  python visualize.py runs/demo/signals_actuated_seed0.jsonl --tick 120 --save f.png
  python visualize.py runs/demo/signals_actuated_seed0.jsonl --animate --save out.gif

How to read the picture
-----------------------
- Each road is a one-way lane; the two directions are drawn side by side.
- Blue dots are individual cars at their cell positions (denser line = queue).
- Each intersection is a circle colored by its NEMA signal state
  (green = serving, yellow / red = clearance) and labeled with the active
  dual-ring phase pair "ring1,ring2".
- A black dotted lane is closed.
- An orange ring (★ in the legend) marks a destination hotspot; the number above
  it is how many cars are currently heading there.
The title shows tick, total stopped cars (queue), cars delivered so far,
mean wait, the demand multiplier, any events this tick, and a GRIDLOCK flag.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traffic_llm.grid import parse_seg_key
from traffic_llm.logging_io import read_run

_STATE_COLOR = {"green": "#2ca02c", "yellow": "#e8b400", "allred": "#d62728"}
_CAR = "#1f4fd6"
_HOT = "#ff7f0e"


def _legend_handles():
    from matplotlib.lines import Line2D

    def dot(color, size):
        return Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=size)

    return [
        (dot(_CAR, 6), "car (one per cell)"),
        (dot(_STATE_COLOR["green"], 11), "signal: green (serving)"),
        (dot(_STATE_COLOR["yellow"], 11), "signal: yellow (clearing)"),
        (dot(_STATE_COLOR["allred"], 11), "signal: all-red (clearing)"),
        (Line2D([0], [0], marker="o", color="w", markerfacecolor="#2ca02c",
                markeredgecolor=_HOT, markeredgewidth=2.4, markersize=11),
         "3-way (T) junction"),
        (Line2D([0], [0], color="black", ls=":"), "closed road"),
        (Line2D([0], [0], color="#cccccc", lw=3), "road (thicker = faster)"),
        (Line2D([0], [0], marker="*", color="w", markerfacecolor=_HOT, markersize=14),
         "destination hotspot"),
        (Line2D([0], [0], marker="$5,8$", color="black", linestyle="None", markersize=14),
         "label = active NEMA pair"),
    ]


def _draw(ax, rec):
    ax.clear()
    lanes = rec["lanes"]
    for key, lane in lanes.items():
        frm, to = parse_seg_key(key)
        dr, dc = to[0] - frm[0], to[1] - frm[1]
        ox, oy = (-dr * 0.10, dc * 0.10)          # offset the two directions apart
        x0, y0 = frm[1] + ox, -frm[0] + oy
        x1, y1 = to[1] + ox, -to[0] + oy
        if lane["closed"]:
            ax.plot([x0, x1], [y0, y1], color="black", lw=2, ls=":", zorder=1)
        else:
            # road line width encodes the speed limit (faster road = thicker)
            vmax = lane.get("vmax", 3)
            ax.plot([x0, x1], [y0, y1], color="#cccccc", lw=0.6 + 0.5 * vmax, zorder=1,
                    solid_capstyle="round")
        L = lane["len"]
        for cell in lane["cars"]:
            f = (cell + 0.5) / L
            cx, cy = x0 + f * (x1 - x0), y0 + f * (y1 - y0)
            ax.scatter([cx], [cy], s=12, c=_CAR, zorder=2)

    # destination hotspots (orange halo behind the signal marker)
    for h in rec.get("hotspots", []):
        r, c = (int(x) for x in h["node"].split(","))
        ax.scatter([c], [-r], s=620, c=_HOT, alpha=0.5, zorder=3, edgecolors="none")
        ax.annotate(f"hot:{h['inflow']}", (c, -r + 0.28), ha="center", va="bottom",
                    fontsize=6, color="#b35900", zorder=6)

    # node degree (distinct connected neighbors) — to flag 3-way (T) junctions
    neighbors: dict[str, set] = {}
    for key in lanes:
        frm, to = parse_seg_key(key)
        a, b = f"{frm[0]},{frm[1]}", f"{to[0]},{to[1]}"
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)

    for node_id, sig in rec.get("signals", {}).items():
        r, c = (int(x) for x in node_id.split(","))
        deg = len(neighbors.get(node_id, ()))
        edge = _HOT if deg == 3 else ("white" if deg >= 4 else "#444")  # orange = T-junction
        ax.scatter([c], [-r], s=260, c=[_STATE_COLOR.get(sig["state"], "#888")],
                   zorder=4, edgecolors=edge, linewidths=2.4 if deg == 3 else 1.5)
        ax.annotate(f"{sig['pair'][0]},{sig['pair'][1]}", (c, -r), ha="center",
                    va="center", fontsize=6, color="white", zorder=5, weight="bold")

    ev = "  ".join(e.get("type", "") for e in rec.get("events", []))
    ax.set_title(
        f"tick={rec['tick']}  queue={rec['total_queue']}  arrived={rec['arrived_total']}  "
        f"wait={rec['mean_wait']}  x{rec['demand_multiplier']}"
        + (f"  | {ev}" if ev else "")
        + ("  GRIDLOCK" if rec.get("gridlocked") else "")
    )
    ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    handles = _legend_handles()
    ax.legend([h for h, _ in handles], [t for _, t in handles],
              loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=7,
              frameon=True, title="legend")


def main() -> int:
    import matplotlib
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log")
    p.add_argument("--tick", type=int, default=None)
    p.add_argument("--animate", action="store_true")
    p.add_argument("--save", default=None, help="PNG (with --tick) or .gif/.mp4 (with --animate)")
    p.add_argument("--fps", type=int, default=12)
    args = p.parse_args()

    if args.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run = read_run(args.log)
    ticks = run["ticks"]
    if not ticks:
        print("no tick records", file=sys.stderr)
        return 1
    by_tick = {t["tick"]: t for t in ticks}
    fig, ax = plt.subplots(figsize=(9.5, 7))
    fig.subplots_adjust(right=0.74)

    if args.animate:
        from matplotlib.animation import FuncAnimation, PillowWriter
        order = sorted(by_tick)
        anim = FuncAnimation(fig, lambda i: _draw(ax, by_tick[order[i]]),
                             frames=len(order), interval=1000 // max(1, args.fps), repeat=False)
        if args.save:
            if args.save.endswith(".gif"):
                anim.save(args.save, writer=PillowWriter(fps=args.fps))
            else:
                anim.save(args.save, fps=args.fps)
            print(f"saved animation ({len(order)} frames) to {args.save}")
        else:
            plt.show()
        return 0

    tick = args.tick if args.tick is not None else max(by_tick)
    if tick not in by_tick:
        tick = min(by_tick, key=lambda t: abs(t - tick))
    _draw(ax, by_tick[tick])
    if args.save:
        fig.savefig(args.save, dpi=120, bbox_inches="tight")
        print(f"saved frame to {args.save}")
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
