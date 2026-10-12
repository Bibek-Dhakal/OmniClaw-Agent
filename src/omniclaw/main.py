"""Daemon wiring and command line entry point."""

import argparse
import asyncio
import logging

import httpx
import uvicorn
from fastapi import FastAPI

from omniclaw.approvals import ApprovalBroker
from omniclaw.browser import BrowserManager, build_browser_tools, interactive_login
from omniclaw.channels.telegram import TelegramChannel
from omniclaw.channels.whatsapp import WhatsAppChannel
from omniclaw.config import get_settings
from omniclaw.connectors import build_connector_tools
from omniclaw.engine import AgentEngine
from omniclaw.memory import Mem0Store, PostgresStore, R2Store
from omniclaw.orchestrator import Orchestrator
from omniclaw.tools import ToolRegistry
from omniclaw.voice import Voice

log = logging.getLogger("omniclaw")


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not (settings.telegram_enabled or settings.whatsapp_enabled):
        raise SystemExit(
            "No channel configured. Set Telegram (token + allowed ids) or WhatsApp "
            "(token, phone id, verify token, app secret, allowed numbers)."
        )

    http = httpx.AsyncClient(timeout=60)
    store = await PostgresStore.connect(settings.database_url)
    memory = Mem0Store(settings.mem0_api_key.get_secret_value())
    r2 = R2Store(settings)
    broker = ApprovalBroker(settings.approval_timeout_seconds)
    browser = BrowserManager(settings)

    registry = ToolRegistry(broker, store.log_action, settings.approval_required)
    registry.register(*build_connector_tools(settings, http), *build_browser_tools(browser, r2))

    engine = AgentEngine(settings.engine_profile(), registry, settings.max_agent_steps)
    orchestrator = Orchestrator(settings, engine, store, memory, r2, Voice(settings, http), broker)

    app = FastAPI(title="OmniClaw Agent")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    telegram = TelegramChannel(settings, orchestrator) if settings.telegram_enabled else None
    if settings.whatsapp_enabled:
        app.include_router(WhatsAppChannel(settings, orchestrator, http).router())

    server = uvicorn.Server(
        uvicorn.Config(
            app, host=settings.host, port=settings.port, log_level=settings.log_level.lower()
        )
    )
    try:
        if telegram is not None:
            await telegram.start()
        log.info("OmniClaw started (engine=%s)", settings.agent_engine)
        await server.serve()
    finally:
        if telegram is not None:
            await telegram.stop()
        await browser.close()
        await store.close()
        await http.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniclaw")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run", help="start the daemon")
    login = subcommands.add_parser("login", help="save a browser session for a domain")
    login.add_argument("domain")
    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run())
    else:
        asyncio.run(interactive_login(get_settings(), args.domain))


if __name__ == "__main__":
    main()
