"""Pluggable LLM backends. The controller depends only on the LLMBackend
protocol, so Claude / mock / (future) local models are interchangeable."""

from .backend import LLMBackend
from .mock import MockBackend

__all__ = ["LLMBackend", "MockBackend", "make_backend"]


def make_backend(name: str, model: str = "claude-opus-4-8", effort: str = "medium") -> LLMBackend:
    if name == "mock":
        return MockBackend()
    if name == "claude":
        from .claude import ClaudeBackend  # lazy: avoids importing anthropic for mock runs
        return ClaudeBackend(model=model, effort=effort)
    raise ValueError(f"unknown backend '{name}' (options: mock, claude)")
