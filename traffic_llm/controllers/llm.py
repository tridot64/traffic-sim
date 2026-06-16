"""LLM controller: render the observation, ask the backend for actions, return
them. All model specifics live behind the LLMBackend; this class only assembles
the prompt and forwards the structured result."""

from __future__ import annotations

from ..actions import tool_schemas
from ..prompts import build_system_prompt


class LLMController:
    name = "llm"

    def __init__(self, backend) -> None:
        self.backend = backend
        self._system_cache: dict[tuple, str] = {}
        self._schema_cache: dict[tuple, list] = {}

    def decide(self, sim):
        allowed = sim.cfg.scenario.allowed_actions
        if allowed not in self._system_cache:
            self._system_cache[allowed] = build_system_prompt(allowed)
            self._schema_cache[allowed] = tool_schemas(allowed)
        system = self._system_cache[allowed]
        schemas = self._schema_cache[allowed]
        obs = sim.observation()
        actions, meta = self.backend.decide(system, obs, schemas)
        return actions, meta
