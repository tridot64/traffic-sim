"""Controllers decide what actions to take each decision step. Baselines are
white-box references; the LLM controller drives a pluggable backend."""

from .base import Controller
from .baselines import (
    ActuatedController, DoNothingController, FixedController, MaxPressureController,
)
from .llm import LLMController
from .supervised import SupervisedActuatedController

__all__ = [
    "Controller",
    "ActuatedController",
    "DoNothingController",
    "FixedController",
    "MaxPressureController",
    "LLMController",
    "SupervisedActuatedController",
    "make_controller",
]


def make_controller(name: str, *, backend: str = "mock", model: str = "claude-opus-4-8",
                    effort: str = "medium") -> Controller:
    if name == "donothing":
        return DoNothingController()
    if name == "fixed":
        return FixedController()
    if name == "actuated":
        return ActuatedController()
    if name == "maxpressure":
        return MaxPressureController()
    if name == "llm":
        from ..llm import make_backend
        return LLMController(make_backend(backend, model=model, effort=effort))
    if name == "supervised":
        from ..llm import make_backend
        return SupervisedActuatedController(make_backend(backend, model=model, effort=effort))
    raise ValueError(f"unknown controller '{name}'")
