"""Tool registry: schema export, approval gating, error containment and action logging."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from omniclaw.approvals import ApprovalBroker
from omniclaw.models import Notify

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 8000
LogAction = Callable[[str, str, str, str, bool, str], Awaitable[None]]


def to_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


@dataclass(frozen=True)
class ToolContext:
    channel: str
    chat_id: str
    notify: Notify

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.chat_id}"


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[Any]]


def _never(_args: dict[str, Any]) -> bool:
    return False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    needs_approval: Callable[[dict[str, Any]], bool] = _never
    describe: Callable[[dict[str, Any]], str] | None = None

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self, broker: ApprovalBroker, log_action: LogAction, approval_required: bool
    ) -> None:
        self._broker = broker
        self._log_action = log_action
        self._approval_required = approval_required
        self._tools: dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            self._tools[tool.name] = tool

    def specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    async def call(self, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return to_json({"error": f"Unknown tool: {name}"})

        ok = True
        try:
            if self._approval_required and tool.needs_approval(args):
                description = tool.describe(args) if tool.describe else f"{name} {to_json(args)}"
                approved = await self._broker.request(ctx.key, ctx.notify, description)
                if not approved:
                    ok = False
                    result: Any = {"error": "Owner rejected the action or did not answer in time."}
                else:
                    result = await tool.handler(args, ctx)
            else:
                result = await tool.handler(args, ctx)
        except Exception as exc:
            log.exception("Tool %s failed", name)
            ok = False
            result = {"error": f"{type(exc).__name__}: {exc}"}

        text = to_json(result)[:MAX_RESULT_CHARS]
        try:
            await self._log_action(ctx.channel, ctx.chat_id, name, to_json(args), ok, text[:2000])
        except Exception:
            log.exception("Failed to record action log for %s", name)
        return text
