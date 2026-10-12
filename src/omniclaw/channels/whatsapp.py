"""WhatsApp Cloud API channel (webhook in, Graph API out)."""

import asyncio
import hashlib
import hmac
import json
import logging
from collections import deque
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from omniclaw.config import Settings
from omniclaw.models import Inbound, chunks
from omniclaw.orchestrator import Orchestrator

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com"
MAX_MESSAGE_CHARS = 4000


def valid_signature(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def extract_messages(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            yield from change.get("value", {}).get("messages", [])


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(
        self, settings: Settings, orchestrator: Orchestrator, http: httpx.AsyncClient
    ) -> None:
        self._s = settings
        self._orchestrator = orchestrator
        self._http = http
        self._tasks: set[asyncio.Task[None]] = set()
        self._seen: deque[str] = deque(maxlen=500)

    @property
    def _base(self) -> str:
        return f"{GRAPH}/{self._s.whatsapp_graph_version}"

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._s.whatsapp_token.get_secret_value()}"}

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/webhook/whatsapp")
        async def verify(request: Request) -> PlainTextResponse:
            params = request.query_params
            token = self._s.whatsapp_verify_token.get_secret_value()
            if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
                params.get("hub.verify_token", ""), token
            ):
                return PlainTextResponse(params.get("hub.challenge", ""))
            raise HTTPException(status_code=403, detail="Verification failed")

        @router.post("/webhook/whatsapp")
        async def receive(request: Request) -> dict[str, str]:
            body = await request.body()
            secret = self._s.whatsapp_app_secret.get_secret_value()
            if not valid_signature(secret, body, request.headers.get("x-hub-signature-256", "")):
                raise HTTPException(status_code=401, detail="Invalid signature")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON") from exc
            for message in extract_messages(payload):
                task = asyncio.create_task(self._process(message))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return {"status": "ok"}

        return router

    async def _process(self, message: dict[str, Any]) -> None:
        try:
            message_id = message.get("id", "")
            if message_id in self._seen:
                return
            self._seen.append(message_id)

            sender = str(message.get("from", ""))
            if sender not in self._s.whatsapp_allowed_set:
                log.warning("Ignoring WhatsApp message from unauthorized number")
                return

            text: str | None = None
            audio: bytes | None = None
            mime: str | None = None
            kind = message.get("type")
            if kind == "text":
                text = message["text"]["body"]
            elif kind == "audio":
                audio, mime = await self._download(message["audio"]["id"])
            else:
                return

            async def notify(content: str) -> None:
                await self._send_text(sender, content)

            outbound = await self._orchestrator.handle(
                Inbound("whatsapp", sender, text, audio, mime), notify
            )
            if outbound is None:
                return
            await self._send_text(sender, outbound.text)
            if outbound.audio:
                await self._send_audio(sender, outbound.audio)
        except Exception:
            log.exception("Failed to process WhatsApp message")

    async def _download(self, media_id: str) -> tuple[bytes, str | None]:
        meta = await self._http.get(f"{self._base}/{media_id}", headers=self._auth)
        meta.raise_for_status()
        info = meta.json()
        data = await self._http.get(info["url"], headers=self._auth)
        data.raise_for_status()
        return data.content, info.get("mime_type")

    async def _send_text(self, to: str, text: str) -> None:
        for part in chunks(text, MAX_MESSAGE_CHARS):
            response = await self._http.post(
                f"{self._base}/{self._s.whatsapp_phone_number_id}/messages",
                headers=self._auth,
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": part},
                },
            )
            response.raise_for_status()

    async def _send_audio(self, to: str, audio: bytes) -> None:
        upload = await self._http.post(
            f"{self._base}/{self._s.whatsapp_phone_number_id}/media",
            headers=self._auth,
            data={"messaging_product": "whatsapp", "type": "audio/mpeg"},
            files={"file": ("reply.mp3", audio, "audio/mpeg")},
        )
        upload.raise_for_status()
        response = await self._http.post(
            f"{self._base}/{self._s.whatsapp_phone_number_id}/messages",
            headers=self._auth,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "audio",
                "audio": {"id": upload.json()["id"]},
            },
        )
        response.raise_for_status()
