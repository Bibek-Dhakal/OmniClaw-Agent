# OmniClaw Agent

An always-on agent daemon that unifies messaging, voice, email, calendar, professional and social networks into one
agentic runtime.

```text
Telegram / WhatsApp (text or voice)
  -> Agent engine (LiteLLM: native, Hermes or OpenClaw endpoints)
  -> Memory (Mem0, Postgres, R2)
  -> Tool router (Composio, Nango, Playwright browser)
  -> Owner approval for outbound actions (Human-readable prompts)
  -> Text + ElevenLabs voice reply
```

## Features

* Telegram (polling) and WhatsApp Cloud API (webhook) channels, with voice-note transcription and voice replies.
* Composio and Nango connectors for Gmail, Calendar, LinkedIn, Instagram and any API they cover.
* Headless Playwright automation for apps without clean APIs, restricted to an allowlist of domains.
* Persistent memory: Mem0 (semantic, cross-channel), Postgres (history and action log), R2 (media).
* Approval gate: sends, posts and other risky actions wait for an explicit YES from the owner. Prompts are translated
  into human-readable text rather than raw JSON.
* Web Logs Dashboard & Execution Log: every tool call is recorded in the `actions` table and viewable via a clean web UI
  at `/logs`.

## Quick start

```bash
cp .env.example .env     # fill in the values you need
docker compose up --build
```

Health check: `http://localhost:8080/healthz`
Web Logs Dashboard: `http://localhost:8080/logs`

## Documentation

* [Usage and configuration](docs/usage.md)
* [Architecture](docs/architecture.md)
* [Testing](docs/testing.md)
* [Code quality](CODE_QUALITY.md)
* [Roadmap](docs/roadmap.md)
* [Contributing](CONTRIBUTING.md)

## License

MIT. See [LICENSE](LICENSE).