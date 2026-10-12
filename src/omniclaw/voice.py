"""Speech-to-text (LiteLLM) and text-to-speech (ElevenLabs)."""

import io
import logging

import httpx
from litellm import atranscription

from omniclaw.config import Settings

log = logging.getLogger(__name__)

MAX_TTS_CHARS = 1500
_EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/webm": "webm",
}


def audio_extension(mime: str | None) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    return _EXTENSIONS.get(base, "ogg")


class Voice:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http

    @property
    def tts_enabled(self) -> bool:
        return bool(self._s.elevenlabs_api_key.get_secret_value() and self._s.elevenlabs_voice_id)

    async def transcribe(self, audio: bytes, mime: str | None) -> str:
        buffer = io.BytesIO(audio)
        buffer.name = f"voice.{audio_extension(mime)}"
        response = await atranscription(
            model=self._s.stt_model,
            file=buffer,
            api_key=self._s.stt_api_key.get_secret_value() or None,
        )
        return (response.text or "").strip()

    async def synthesize(self, text: str) -> bytes | None:
        if not self.tts_enabled or not text.strip():
            return None
        try:
            response = await self._http.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{self._s.elevenlabs_voice_id}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": self._s.elevenlabs_api_key.get_secret_value()},
                json={"text": text[:MAX_TTS_CHARS], "model_id": self._s.elevenlabs_model_id},
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            log.warning("Voice synthesis failed", exc_info=True)
            return None
