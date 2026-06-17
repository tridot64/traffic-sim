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

from .config import MapConfig


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


PRESETS = {
    "arterial": _arterial_grid,
    "oneway_loop": _one_way_loop,
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
