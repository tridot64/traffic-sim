"""Simulator entry point.

The engine is the microscopic CA + NEMA model in ``traffic_llm.micro``. This
module re-exports it under the stable name ``Simulator`` so the rest of the
harness (runner, controllers, tests) is unaffected by the engine swap.
"""

from __future__ import annotations

from .micro.engine import MicroSimulator as Simulator

__all__ = ["Simulator"]
