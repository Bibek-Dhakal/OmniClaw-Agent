"""Persistent state: Postgres (history + action log), Mem0 (semantic memory), R2 (media)."""

import asyncio
import logging
from typing import Any

import asyncpg
import boto3

from omniclaw.config import Settings

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (channel, chat_id, id DESC);
CREATE TABLE IF NOT EXISTS actions (
    id BIGSERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    result TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresStore":
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        await pool.execute(SCHEMA)
        return cls(pool)

    async def add(self, channel: str, chat_id: str, role: str, content: str) -> None:
        await self._pool.execute(
            "INSERT INTO messages (channel, chat_id, role, content) VALUES ($1, $2, $3, $4)",
            channel,
            chat_id,
            role,
            content,
        )

    async def recent(self, channel: str, chat_id: str, limit: int) -> list[dict[str, str]]:
        rows = await self._pool.fetch(
            "SELECT role, content FROM messages WHERE channel = $1 AND chat_id = $2 "
            "ORDER BY id DESC LIMIT $3",
            channel,
            chat_id,
            limit,
        )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def log_action(
        self, channel: str, chat_id: str, tool: str, args: str, ok: bool, result: str
    ) -> None:
        await self._pool.execute(
            "INSERT INTO actions (channel, chat_id, tool, args, ok, result) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            channel,
            chat_id,
            tool,
            args,
            ok,
            result,
        )

    async def recent_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT id, channel, tool, args, ok, result, created_at FROM actions "
            "ORDER BY id DESC LIMIT $1",
            limit,
        )
        return [dict(row) for row in rows]

    async def close(self) -> None:
        await self._pool.close()


class Mem0Store:
    """Semantic long-term memory. Disabled (no-op) when no API key is configured."""

    def __init__(self, api_key: str) -> None:
        self._client: Any = None
        if api_key:
            from mem0 import AsyncMemoryClient

            self._client = AsyncMemoryClient(api_key=api_key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        if self._client is None:
            return []
        try:
            response = await self._client.search(query, filters={"user_id": user_id}, limit=limit)
        except Exception:
            log.warning("Mem0 search failed", exc_info=True)
            return []
        items = response.get("results", []) if isinstance(response, dict) else response
        return [item["memory"] for item in items if isinstance(item, dict) and item.get("memory")]

    async def add(self, user_id: str, user_text: str, assistant_text: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.add(
                [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text},
                ],
                user_id=user_id,
            )
        except Exception:
            log.warning("Mem0 add failed", exc_info=True)


class R2Store:
    """Cloudflare R2 (S3 compatible) blob storage. Disabled when not configured."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.r2_bucket
        self._client: Any = None
        if settings.r2_enabled:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint,
                aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                region_name="auto",
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        if self._client is None:
            raise RuntimeError("R2 is not configured")
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key
