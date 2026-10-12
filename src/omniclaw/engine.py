"""Tool-calling agent loop. All LLM traffic goes through LiteLLM acompletion."""

import json
import logging
from typing import Any

import litellm
from litellm import acompletion

from omniclaw.config import EngineProfile
from omniclaw.tools import ToolContext, ToolRegistry, to_json

litellm.drop_params = True
log = logging.getLogger(__name__)

STEP_LIMIT_REPLY = "I reached my step limit before finishing. Tell me how you want to continue."


class AgentEngine:
    def __init__(self, profile: EngineProfile, registry: ToolRegistry, max_steps: int) -> None:
        self._profile = profile
        self._registry = registry
        self._max_steps = max_steps

    async def run(self, messages: list[dict[str, Any]], ctx: ToolContext) -> str:
        """Run the loop. The messages list is extended in place with assistant and tool turns."""
        specs = self._registry.specs() or None
        for _ in range(self._max_steps):
            response = await acompletion(
                model=self._profile.model,
                messages=messages,
                tools=specs,
                api_base=self._profile.api_base,
                api_key=self._profile.api_key,
                num_retries=3,  # Automatically retry on temporary API errors (like 503s or rate limits)
            )
            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None)
            if not calls:
                return (message.content or "").strip()

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    result = to_json({"error": "Tool arguments were not valid JSON."})
                else:
                    result = await self._registry.call(call.function.name, args, ctx)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        log.warning("Agent hit step limit (%s)", self._max_steps)
        return STEP_LIMIT_REPLY
