"""Telegram channel (long polling) with voice-note support."""

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from omniclaw.config import Settings
from omniclaw.models import Inbound, chunks
from omniclaw.orchestrator import Orchestrator

log = logging.getLogger(__name__)
MAX_MESSAGE_CHARS = 4000


class TelegramChannel:
    name = "telegram"

    def __init__(self, settings: Settings, orchestrator: Orchestrator) -> None:
        self._s = settings
        self._orchestrator = orchestrator
        self._app: Application | None = None

    async def start(self) -> None:
        app = (
            Application.builder()
            .token(self._s.telegram_bot_token.get_secret_value())
            .concurrent_updates(True)
            .build()
        )
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND) | filters.VOICE | filters.AUDIO,
                self._on_message,
            )
        )
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        self._app = app
        log.info("Telegram channel started")

    async def stop(self) -> None:
        if self._app is None:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        if str(user.id) not in self._s.telegram_allowed_ids:
            log.warning("Ignoring Telegram message from unauthorized user %s", user.id)
            return

        audio: bytes | None = None
        mime: str | None = None
        media = message.voice or message.audio
        if media is not None:
            telegram_file = await media.get_file()
            audio = bytes(await telegram_file.download_as_bytearray())
            mime = media.mime_type or "audio/ogg"

        chat_id = message.chat_id

        async def notify(text: str) -> None:
            await context.bot.send_message(chat_id=chat_id, text=text)

        outbound = await self._orchestrator.handle(
            Inbound("telegram", str(chat_id), message.text, audio, mime), notify
        )
        if outbound is None:
            return
        for part in chunks(outbound.text, MAX_MESSAGE_CHARS):
            await message.reply_text(part)
        if outbound.audio:
            await message.reply_voice(outbound.audio)
