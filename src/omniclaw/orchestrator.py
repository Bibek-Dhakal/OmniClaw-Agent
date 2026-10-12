"""Per-message pipeline: transcribe, approve, recall, run engine, persist, voice."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from omniclaw.approvals import ApprovalBroker
from omniclaw.config import Settings
from omniclaw.engine import AgentEngine
from omniclaw.memory import Mem0Store, PostgresStore, R2Store
from omniclaw.models import Inbound, Notify, Outbound
from omniclaw.tools import ToolContext
from omniclaw.voice import Voice, audio_extension

log = logging.getLogger(__name__)

ERROR_REPLY = "Something went wrong while handling that. Check the logs and try again."
VOICE_ERROR_REPLY = "I could not process that voice message."


def build_system_prompt(owner: str, memories: list[str]) -> str:
    memory_block = "\n".join(f"- {m}" for m in memories) if memories else "- (none)"
    return (
        f"You are OmniClaw, the executive assistant of {owner}. "
        f"Current UTC time: {datetime.now(UTC).isoformat(timespec='minutes')}.\n"
        "Use tools to read mail, calendar and social platforms and to take actions. "
        "Never claim an action succeeded unless a tool result confirms it. "
        "CRITICAL TOOL RULES: "
        "1. If using Composio, NEVER guess tool slugs. ALWAYS call composio_list_tools with a query to find the exact slug before calling composio_execute. "
        "2. Assume the user is already authenticated to all platforms. NEVER call INITIATE_CONNECTION tools. "
        "Prefer connector tools (Composio, Nango) over the browser; use the browser only for "
        "apps without usable APIs. Messages sent to third parties go out under the owner's "
        "name: draft them in the owner's tone and keep them honest. "
        "Sending and posting require owner approval; if an action is rejected, do not retry it. "
        "Keep answers concise and easy to hear when read aloud.\n"
        f"Relevant long-term memories:\n{memory_block}"
    )


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        engine: AgentEngine,
        store: PostgresStore,
        memory: Mem0Store,
        r2: R2Store,
        voice: Voice,
        broker: ApprovalBroker,
    ) -> None:
        self._s = settings
        self._engine = engine
        self._store = store
        self._memory = memory
        self._r2 = r2
        self._voice = voice
        self._broker = broker
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._background: set[asyncio.Task[Any]] = set()

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def handle(self, inbound: Inbound, notify: Notify) -> Outbound | None:
        key = f"{inbound.channel}:{inbound.chat_id}"
        try:
            text = await self._resolve_text(inbound)
        except Exception:
            log.exception("Voice handling failed")
            return Outbound(text=VOICE_ERROR_REPLY)
        if not text:
            return None

        acknowledgement = self._broker.resolve(key, text)
        if acknowledgement is not None:
            return Outbound(text=acknowledgement)

        async with self._locks[key]:
            try:
                return await self._respond(inbound, text, notify)
            except Exception:
                log.exception("Failed to handle message on %s", key)
                return Outbound(text=ERROR_REPLY)

    async def _resolve_text(self, inbound: Inbound) -> str | None:
        if inbound.audio is None:
            return (inbound.text or "").strip() or None
        if self._r2.enabled:
            key = (
                f"audio/in/{inbound.channel}/{inbound.chat_id}/{uuid4().hex}."
                f"{audio_extension(inbound.audio_mime)}"
            )
            self._spawn(self._archive(key, inbound.audio, inbound.audio_mime or "audio/ogg"))
        return await self._voice.transcribe(inbound.audio, inbound.audio_mime)

    async def _archive(self, key: str, data: bytes, content_type: str) -> None:
        try:
            await self._r2.put(key, data, content_type)
        except Exception:
            log.warning("Failed to archive %s", key, exc_info=True)

    async def _respond(self, inbound: Inbound, text: str, notify: Notify) -> Outbound:
        user_id = self._s.memory_user_id
        memories = await self._memory.search(user_id, text)
        history = await self._store.recent(
            inbound.channel, inbound.chat_id, self._s.history_turns * 2
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self._s.owner_name, memories)},
            *history,
            {"role": "user", "content": text},
        ]
        ctx = ToolContext(inbound.channel, inbound.chat_id, notify)
        reply = await self._engine.run(messages, ctx) or "Done."

        await self._store.add(inbound.channel, inbound.chat_id, "user", text)
        await self._store.add(inbound.channel, inbound.chat_id, "assistant", reply)
        self._spawn(self._memory.add(user_id, text, reply))

        audio = None
        if inbound.audio is not None or self._s.voice_replies_always:
            audio = await self._voice.synthesize(reply)
        return Outbound(text=reply, audio=audio)
