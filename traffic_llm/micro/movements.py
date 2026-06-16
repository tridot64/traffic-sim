"""NEMA 8-phase movement model and dual-ring/barrier compatibility.

Geometry
--------
A car's *heading* is its travel direction entering an intersection (N/S/E/W).
Its *turn* relative to that heading is Left / Through / Right. A movement is the
pair ``(heading, turn)`` — e.g. ``('E','L')`` is the eastbound left (EBL).

NEMA numbering (standard dual-ring, ring-barrier):

    Ring 1:  φ1 EBL | φ2 WBT | φ3 SBL | φ4 NBT
    Ring 2:  φ5 WBL | φ6 EBT | φ7 NBL | φ8 SBT
    Barrier between the E-W phases {1,2,5,6} and the N-S phases {3,4,7,8}.

A signal state is an active *phase pair* (one phase per ring, both on the same
side of the barrier). The eight compatible (conflict-free) pairs are enumerated
below; protected greens come from the pair, while right-turns (RTOR) and lefts
during the opposing through (permissive) proceed with gap acceptance.
"""

from __future__ import annotations

HEADINGS = ("N", "S", "E", "W")
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
LEFT = {"N": "W", "W": "S", "S": "E", "E": "N"}
RIGHT = {"N": "E", "E": "S", "S": "W", "W": "N"}


def heading_of(frm, to) -> str:
    """Travel direction along segment frm->to."""
    dr, dc = to[0] - frm[0], to[1] - frm[1]
    if dr == 1:
        return "S"
    if dr == -1:
        return "N"
    if dc == 1:
        return "E"
    return "W"


def turn_type(heading_in: str, heading_out: str) -> str:
    """L / T / R for a car traveling ``heading_in`` that leaves ``heading_out``."""
    if heading_out == heading_in:
        return "T"
    if heading_out == LEFT[heading_in]:
        return "L"
    if heading_out == RIGHT[heading_in]:
        return "R"
    return "U"  # U-turn — not used on a 4-grid


# Protected movements served by each NEMA phase.
PHASE_MOVEMENTS: dict[int, tuple[tuple[str, str], ...]] = {
    1: (("E", "L"),),                 # EBL
    2: (("W", "T"), ("W", "R")),      # WBT (+WBR)
    3: (("S", "L"),),                 # SBL
    4: (("N", "T"), ("N", "R")),      # NBT (+NBR)
    5: (("W", "L"),),                 # WBL
    6: (("E", "T"), ("E", "R")),      # EBT (+EBR)
    7: (("N", "L"),),                 # NBL
    8: (("S", "T"), ("S", "R")),      # SBT (+SBR)
}

RING1 = (1, 2, 3, 4)
RING2 = (5, 6, 7, 8)
GROUP_EW = (1, 2, 5, 6)
GROUP_NS = (3, 4, 7, 8)

# The 8 conflict-free phase pairs (ring1, ring2), same barrier side.
COMPATIBLE_PAIRS: tuple[tuple[int, int], ...] = (
    (1, 5), (1, 6), (2, 5), (2, 6),   # E-W barrier side
    (3, 7), (3, 8), (4, 7), (4, 8),   # N-S barrier side
)


def is_compatible_pair(pair: tuple[int, int]) -> bool:
    return tuple(pair) in COMPATIBLE_PAIRS


def pair_movements(pair: tuple[int, int]) -> set[tuple[str, str]]:
    """Protected green movements for an active phase pair."""
    out: set[tuple[str, str]] = set()
    for p in pair:
        out.update(PHASE_MOVEMENTS[p])
    return out


def discharge_kind(movement: tuple[str, str], green: set[tuple[str, str]]) -> str:
    """How (if at all) a movement may discharge given the protected green set.

    Returns 'protected' (free), 'permissive' / 'rtor' (allowed with gap
    acceptance — must yield), or 'blocked'.
    """
    heading, turn = movement
    if movement in green:
        return "protected"
    if turn == "R":
        return "rtor"  # right-on-red, yields
    if turn == "L" and (OPPOSITE[heading], "T") in green:
        return "permissive"  # permissive left during opposing through
    return "blocked"
