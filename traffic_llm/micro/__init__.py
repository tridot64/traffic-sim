"""Microscopic engine: cellular-automaton car-following + full NEMA 8-phase
dual-ring signals. Replaces the mesoscopic model while keeping the harness
interfaces (RunConfig, scenarios, metrics, logging, visualizer)."""

__all__ = ["MicroSimulator"]


def __getattr__(name):  # lazy so movements/cells import without engine present
    if name == "MicroSimulator":
        from .engine import MicroSimulator
        return MicroSimulator
    raise AttributeError(name)
