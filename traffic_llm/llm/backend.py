"""The backend contract: given a system prompt, an observation, and the tool
schemas for the allowed actions, return raw action dicts plus call metadata.

A raw action dict is ``{"action": <tool name>, **tool_input}`` — the exact
shape ``actions.validate`` expects.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMBackend(Protocol):
    name: str

    def decide(
        self,
        system_prompt: str,
        observation: dict[str, Any],
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return (raw_actions, meta). ``meta`` may include ``backend_ms``,
        ``usage``, and ``failed`` (True if the call errored — the simulator then
        simply holds the previous plan)."""
        ...
