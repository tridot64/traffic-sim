"""Custom road maps + a JSON loader.

A custom map is a grid subgraph: explicit directed roads between Manhattan-
adjacent integer cells, each with an optional ``vmax`` (speed limit) and
``cells`` (length). Nodes stay on the lattice so the NEMA heading/turn logic
remains valid. Build one inline, pick a preset, or load JSON.

JSON shape:
    {"roads": [{"from": "0,0", "to": "0,1", "vmax": 5, "cells": 14}, ...],
     "default_vmax": 3, "default_cells": 12}
"""

from __future__ import annotations

import json
import random

from .config import MapConfig

# Road hierarchy: speed limit (cells/tick) + length (cells). Freeways are fast
# and long, streets are slow and short — a realistic urban tier structure.
TIERS = {
    "freeway":    {"vmax": 9, "cells": 18},
    "expressway": {"vmax": 5, "cells": 14},
    "street":     {"vmax": 2, "cells": 10},
}


def _bidir(a: str, b: str, **attrs) -> list[dict]:
    return [{"from": a, "to": b, **attrs}, {"from": b, "to": a, **attrs}]


def _full_grid_roads(rows: int, cols: int, **attrs) -> list[dict]:
    roads: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                roads += _bidir(f"{r},{c}", f"{r},{c+1}", **attrs)
            if r + 1 < rows:
                roads += _bidir(f"{r},{c}", f"{r+1},{c}", **attrs)
    return roads


def _arterial_grid() -> MapConfig:
    """5×5 grid where the middle row and column are fast arterials (vmax 6) and
    the rest are slow streets (vmax 2)."""
    roads = _full_grid_roads(5, 5, vmax=2)
    fast = []
    for road in roads:
        fr = tuple(int(x) for x in road["from"].split(","))
        to = tuple(int(x) for x in road["to"].split(","))
        if fr[0] == 2 and to[0] == 2:        # middle row (horizontal arterial)
            fast.append({**road, "vmax": 6})
        elif fr[1] == 2 and to[1] == 2:      # middle col (vertical arterial)
            fast.append({**road, "vmax": 6})
        else:
            fast.append(road)
    return MapConfig(roads=tuple(fast), default_vmax=2, default_cells=12)


def _one_way_loop() -> MapConfig:
    """3×3 grid with a clockwise one-way ring on the perimeter (one direction
    only) and two-way interior streets — exercises asymmetric topology."""
    roads = _full_grid_roads(3, 3)
    perimeter_cw = [
        ("0,0", "0,1"), ("0,1", "0,2"), ("0,2", "1,2"), ("1,2", "2,2"),
        ("2,2", "2,1"), ("2,1", "2,0"), ("2,0", "1,0"), ("1,0", "0,0"),
    ]
    cw = set(perimeter_cw)
    perimeter_nodes = {"0,0", "0,1", "0,2", "1,2", "2,2", "2,1", "2,0", "1,0"}
    kept = []
    for road in roads:
        a, b = road["from"], road["to"]
        # drop the counter-clockwise perimeter direction
        if a in perimeter_nodes and b in perimeter_nodes and (a, b) not in cw \
                and (b, a) in cw:
            continue
        kept.append(road)
    return MapConfig(roads=tuple(kept), default_vmax=3, default_cells=12)


def tiered_map(rows: int = 6, cols: int = 6, seed: int = 0,
               n_freeway: int = 1, n_express: int = 2) -> MapConfig:
    """A seeded random city: a few full rows/cols are FREEWAYS (fast, long), a
    few more are EXPRESSWAYS, and everything else is slow STREETS. A road's tier
    comes from the corridor it runs along, so freeways/expressways form coherent
    high-speed arteries through a street grid."""
    rng = random.Random(seed)
    free_rows = set(rng.sample(range(rows), min(n_freeway, rows)))
    free_cols = set(rng.sample(range(cols), min(n_freeway, cols)))
    exp_rows = set(rng.sample([r for r in range(rows) if r not in free_rows],
                              min(n_express, max(0, rows - n_freeway))))
    exp_cols = set(rng.sample([c for c in range(cols) if c not in free_cols],
                              min(n_express, max(0, cols - n_freeway))))

    def tier(frm, to) -> str:
        if frm[0] == to[0]:                       # horizontal road -> its row
            line, free, exp = frm[0], free_rows, exp_rows
        else:                                     # vertical road -> its column
            line, free, exp = frm[1], free_cols, exp_cols
        if line in free:
            return "freeway"
        if line in exp:
            return "expressway"
        return "street"

    roads: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                roads += _bidir(f"{r},{c}", f"{r},{c+1}", **TIERS[tier((r, c), (r, c + 1))])
            if r + 1 < rows:
                roads += _bidir(f"{r},{c}", f"{r+1},{c}", **TIERS[tier((r, c), (r + 1, c))])
    return MapConfig(roads=tuple(roads), default_vmax=2, default_cells=10)


PRESETS = {
    "arterial": _arterial_grid,
    "oneway_loop": _one_way_loop,
    "tiered": lambda: tiered_map(6, 6, seed=0),
    "tiered_big": lambda: tiered_map(8, 8, seed=1, n_freeway=2, n_express=2),
}


def get_map(name: str) -> MapConfig:
    if name not in PRESETS:
        raise KeyError(f"unknown map '{name}'. presets: {sorted(PRESETS)}")
    return PRESETS[name]()


def load_map(path: str) -> MapConfig:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return MapConfig(
        roads=tuple(d["roads"]),
        default_vmax=int(d.get("default_vmax", 3)),
        default_cells=int(d.get("default_cells", 12)),
    )
