"""Claude backend — calls the Anthropic Messages API once per decision step and
returns structured actions via tool use.

Uses Opus 4.8 with adaptive thinking and the effort parameter (per the
claude-api guidance). The static system prompt + tool schemas are prompt-cached
so only the per-tick observation is paid fresh each call. API errors are caught
and surfaced as ``failed`` so a flaky network never crashes a run — the
simulator simply holds the previous plan (itself a robustness signal).
"""

from __future__ import annotations

import time
from typing import Any

from ..prompts import render_observation


class ClaudeBackend:
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-8", effort: str = "medium",
                 max_tokens: int = 4000):
        import anthropic  # lazy; only required for --backend claude
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def decide(self, system_prompt, observation, tool_schemas):
        obs_text = render_observation(observation)
        t0 = time.time()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                system=[{"type": "text", "text": system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                tools=tool_schemas,
                messages=[{"role": "user", "content": obs_text}],
            )
        except self._anthropic.APIError as exc:
            return [], {"failed": True, "error": str(exc),
                        "backend_ms": (time.time() - t0) * 1000}

        actions: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "tool_use":
                actions.append({"action": block.name, **dict(block.input)})

        usage = getattr(resp, "usage", None)
        meta = {
            "failed": False,
            "backend_ms": (time.time() - t0) * 1000,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            } if usage else {},
        }
        return actions, meta
