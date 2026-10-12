"""Shared data types."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

Notify = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class Inbound:
    channel: str
    chat_id: str
    text: str | None = None
    audio: bytes | None = None
    audio_mime: str | None = None


@dataclass(frozen=True)
class Outbound:
    text: str
    audio: bytes | None = None


def chunks(text: str, size: int) -> Iterator[str]:
    """Split text into pieces no longer than size (at least one piece)."""
    if not text:
        yield ""
        return
    for start in range(0, len(text), size):
        yield text[start : start + size]
