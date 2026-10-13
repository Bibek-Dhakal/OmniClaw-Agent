"""Daemon wiring and command line entry point."""

import argparse
import asyncio
import html
import logging

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from omniclaw.approvals import ApprovalBroker
from omniclaw.browser import BrowserManager, build_browser_tools, interactive_login
from omniclaw.catalog import ToolCatalog
from omniclaw.channels.telegram import TelegramChannel
from omniclaw.channels.whatsapp import WhatsAppChannel
from omniclaw.config import get_settings
from omniclaw.connectors import build_connector_tools, build_providers
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
    catalog = ToolCatalog(
        build_providers(settings, http),
        settings.tool_cache_ttl_seconds,
        settings.tool_route_top_k,
    )

    registry = ToolRegistry(broker, store.log_action, settings.approval_required)
    registry.register(*build_connector_tools(settings, http), *build_browser_tools(browser, r2))
    if catalog.enabled:
        registry.register(catalog.find_tools_tool())

    engine = AgentEngine(settings.engine_profile(), registry, settings.max_agent_steps)
    orchestrator = Orchestrator(
        settings, engine, store, memory, r2, Voice(settings, http), broker, catalog
    )

    app = FastAPI(title="OmniClaw Agent")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/logs", response_class=HTMLResponse)
    async def view_logs() -> HTMLResponse:
        actions = await store.recent_actions(50)
        rows = []
        for a in actions:
            status_color = "green" if a["ok"] else "red"
            rows.append(
                f"<tr>"
                f"<td>{a['id']}</td>"
                f"<td>{html.escape(a['tool'])}</td>"
                f"<td style='color:{status_color}; font-weight:bold;'>{a['ok']}</td>"
                f"<td><pre style='margin:0;max-width:300px;overflow-x:auto'>{html.escape(a['args'])}</pre></td>"
                f"<td><pre style='margin:0;max-width:500px;overflow-x:auto;max-height:200px;overflow-y:auto'>{html.escape(a['result'])}</pre></td>"
                f"</tr>"
            )

        html_content = f"""
        <html>
        <head>
            <title>OmniClaw Execution Logs</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f9f9f9; color: #333; }}
                table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                th, td {{ border: 1px solid #eee; padding: 12px; vertical-align: top; font-size: 14px; }}
                th {{ background-color: #f1f5f9; text-align: left; font-weight: 600; color: #475569; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: "Courier New", Courier, monospace; font-size: 13px; color: #444; background: #f8fafc; padding: 8px; border-radius: 4px; }}
                h2 {{ color: #1e293b; }}
            </style>
        </head>
        <body>
            <h2>Recent Agent Actions (Last 50)</h2>
            <table>
                <tr>
                    <th style="width: 50px;">ID</th>
                    <th style="width: 150px;">Tool</th>
                    <th style="width: 50px;">Status</th>
                    <th>Arguments</th>
                    <th>Result / Error</th>
                </tr>
                {"".join(rows)}
            </table>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

    telegram = TelegramChannel(settings, orchestrator) if settings.telegram_enabled else None
    if settings.whatsapp_enabled:
        app.include_router(WhatsAppChannel(settings, orchestrator, http).router())

    server = uvicorn.Server(
        uvicorn.Config(
            app, host=settings.host, port=settings.port, log_level=settings.log_level.lower()
        )
    )
    try:
        if catalog.enabled:
            log.info("Connected apps: %s", await catalog.connected() or "unknown")
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
