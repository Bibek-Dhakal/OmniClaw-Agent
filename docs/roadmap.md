# Roadmap

## Current

* Telegram and WhatsApp channels with voice in and out.
* Composio and Nango connector tools, Playwright browser tools, approval gate, action log.
* Postgres history, Mem0 memory, R2 media storage.

## Next

* Direct MCP client support alongside Composio tool execution.
* Native Hermes and OpenClaw adapters if their SDKs offer more than OpenAI-compatible endpoints.
* Mobile-app automation (Android emulator with Appium) for apps without a web client.
* Voice-note formatted WhatsApp replies (Opus/OGG transcoding).
* Proactive scheduled tasks (reminders, inbox digests).
* Metrics for tool success rate and browser automation reliability.

## Known challenges

* Browser selectors on social sites change often; playbooks need regression checks.
* Third-party terms of service may restrict automation of some platforms.
* Mem0 client API differences between versions.
* Telegram currently receives plain text only. Rich formatting (parse_mode) is not enabled.
* Connector setup errors are the most common support issue. A `doctor` command that checks LLM, database and connector reachability is planned.