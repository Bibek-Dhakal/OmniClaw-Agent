# Setup guide

Follow these steps in order. Each step ends with a check so you know it worked before moving on.

## 1. Prerequisites

* Docker with Docker Compose.
* A Telegram account (WhatsApp is optional and needs a Meta business app).
* An LLM: a hosted API key, or any OpenAI-compatible server.

```bash
cp .env.example .env
```

Never commit `.env`. After any `.env` change, run `docker compose up -d --force-recreate`
(or `docker compose up --build`). A plain restart does not always reload it.

## 2. Language model

Pick one.

**Hosted (for example Gemini)**

```env
LLM_MODEL=gemini/gemini-3.8-flash
LLM_API_KEY=<your key>
LLM_API_BASE=
```

**Any OpenAI-compatible server** (LM Studio, vLLM, a gateway)

```env
LLM_MODEL=openai/<model-name>
LLM_API_BASE=http://host.docker.internal:<port>/v1
LLM_API_KEY=<key, or any non-empty value if the server ignores it>
```

Inside the container, `localhost` means the container itself. Use `host.docker.internal` to
reach a service on your machine. Your server must listen on `0.0.0.0`, not only `127.0.0.1`,
and your firewall must allow the port from Docker.

Check: from the host, `curl http://localhost:<port>/v1/models` answers. Then, from the
container:

```bash
docker compose exec omniclaw python -c "import httpx; print(httpx.get('http://host.docker.internal:<port>/v1/models').text)"
```

## 3. Telegram

1. Talk to `@BotFather`, send `/newbot`, copy the token.
2. Talk to `@userinfobot` to get your numeric user id.

```env
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_ALLOWED_USER_IDS=<your numeric id>
```

Only listed ids are served. Messages from anyone else are ignored (a warning is logged).
Slash commands such as `/start` are ignored. Just send a normal message.

## 4. Connectors (optional: Composio, Nango, or both)

### Composio

1. Create an API key and connect an app (for example GitHub) in the Composio dashboard.
2. Open **Connected accounts**. The account must be **ACTIVE**. Note its **user id**.
3. Set:

```env
COMPOSIO_API_KEY=<key>
COMPOSIO_USER_ID=<the user id on the connected account>
```

The most common setup error is a user id mismatch. The app asks Composio for accounts owned by
`COMPOSIO_USER_ID`. If the connection was created under a different id, you get
`No connected account found for user ID ...` and the app starts with no connected apps.
Either set `COMPOSIO_USER_ID` to the id the account really uses, or reconnect the app under
your chosen id.

### Nango Cloud

```env
NANGO_SECRET_KEY=<secret key from Environment Settings>
NANGO_BASE_URL=https://api.nango.dev
```

### Nango self-hosted

Follow the official Nango self-hosting guide, then:

```env
NANGO_SECRET_KEY=<secret key from your own Nango instance>
NANGO_BASE_URL=http://host.docker.internal:<port of the Nango server API>
```

Use the port that serves the Nango API in your deployment (check your Nango compose file),
not necessarily the dashboard port. Use `host.docker.internal`, not `localhost`. If Nango runs
in another Docker network, use its service name or host IP instead.

### Nango rules that are easy to miss

* Curated tools exist only for GitHub, Gmail, Google Calendar and Slack
  (`src/omniclaw/nango_tools.py`). Other providers work only through the generic
  `nango_request` tool.
* Your Nango integrations must use these provider ids: `github`, `google-mail`,
  `google-calendar`, `slack`. If you use others, edit `PROVIDERS` in `nango_tools.py`.
* Each integration needs at least one connection (an authorized account) in Nango.
* If you have several connections for one provider, set `NANGO_CONNECTION_ID` to pick one.
* Nango proxies requests, so the scopes granted when you authorized the account decide what the
  agent can read or write.

## 5. Start and verify

```bash
docker compose up --build
```

Expected log lines:

```text
Connected apps: ['github']          <- or whatever you connected
Telegram channel started
OmniClaw started (engine=native)
```

If you see `No connected apps found`, see [Troubleshooting](troubleshooting.md). Chat still
works, but connector tools will not.

Then message your bot: "Hello", then "List my 3 most recently updated GitHub repositories".
Open `http://localhost:8080/logs` to see each tool call and its result.

## 6. Optional features

Voice (ElevenLabs, STT), R2 media storage, Mem0 memory, WhatsApp and browser automation are
configured through the variables in [Usage](usage.md#environment-variables).
Browser automation only visits `BROWSER_ALLOWED_DOMAINS`. Run `omniclaw login <domain>` on a
machine with a display to save a session.