# Usage

First time here? Follow the [Setup guide](setup.md). Having trouble? See
[Troubleshooting](troubleshooting.md).

## Commands

```bash
omniclaw run                  # start the daemon (channels + webhook server)
omniclaw login <domain>       # headful login that saves a browser session, e.g. instagram.com
docker compose up --build     # run the full stack
pytest                        # run tests
```

`omniclaw login` opens a visible browser, so run it on a machine with a display. The session is saved to
`BROWSER_STATE_DIR` and can be mounted into the container.

## Web Logs Dashboard

You can view real-time logs of the agent's internal tool calls, arguments, and API results without touching a database
terminal.
While the app is running, open your web browser and navigate to:
`http://<host>:<port>/logs` (e.g., `http://localhost:8080/logs`)

## Channels

* Telegram needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_IDS`. Only listed users are served.
* WhatsApp needs all four of `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` and
  `WHATSAPP_APP_SECRET`. Set the Meta webhook callback to `https://<host>/webhook/whatsapp`.

## Tool discovery

The agent does not explore tools inside its loop. For every message the tool catalog does the following first:

1. Finds the connected apps (Composio connected accounts, or Nango connections).
2. Detects which app or apps the message is about (for example GitHub, Gmail, Calendar, Slack, or a mix).
3. Ranks that app's tools against the message and loads the top `TOOL_ROUTE_TOP_K` as real function-calling tools with
   full parameter schemas, so the model can call them directly.
4. Chat-only messages load no tools.

If no loaded tool fits, the model calls `find_tools` once with a plain-language goal. The matches are loaded and become
callable on the next step.

Providers follow your environment. Set `COMPOSIO_API_KEY` to use the Composio tool catalog. Set `NANGO_SECRET_KEY` to
use the curated Nango tools (GitHub, Gmail, Google Calendar, Slack) defined in `src/omniclaw/nango_tools.py`. If both
are set, both are used. Tool lists are cached for `TOOL_CACHE_TTL_SECONDS`.

Ranking prefers read tools unless your message contains a write verb (send, create, delete and
so on), and deprecated Composio tools are skipped. Tool results are compacted (nulls, API-style
`*_url` fields and long strings removed) so lists are not cut off. If a result is still too
long it ends with `[truncated]` and the agent tells you the list may be incomplete.

## Approvals

Tools that send, post or modify are held until the owner replies YES (or NO) in the same chat. The system automatically
translates complex API payloads into human-readable summaries before asking for approval. Composio tools run without
approval only when the slug has a read verb (FETCH, LIST, GET, SEARCH, FIND, READ and similar) and no write verb (SEND,
CREATE, DELETE, UPDATE and similar). Nango GET calls run without approval, other methods are held. Set
`APPROVAL_REQUIRED=false` to disable the gate.

## Environment variables

| Name                      | Type                     | Default                                                | Description                                         |
|---------------------------|--------------------------|--------------------------------------------------------|-----------------------------------------------------|
| LOG_LEVEL                 | string                   | INFO                                                   | Python logging level                                |
| HOST                      | string                   | 127.0.0.1                                              | Webhook server bind address                         |
| PORT                      | int                      | 8080                                                   | Webhook server port                                 |
| OWNER_NAME                | string                   | Owner                                                  | Name used in the system prompt                      |
| MEMORY_USER_ID            | string                   | owner                                                  | Mem0 user id, shared across channels                |
| MAX_AGENT_STEPS           | int                      | 12                                                     | Maximum tool-call rounds per request                |
| HISTORY_TURNS             | int                      | 12                                                     | Conversation turns loaded from Postgres             |
| APPROVAL_REQUIRED         | bool                     | true                                                   | Require owner approval for risky tools              |
| APPROVAL_TIMEOUT_SECONDS  | int                      | 300                                                    | Approval wait time before rejection                 |
| AGENT_ENGINE              | native, hermes, openclaw | native                                                 | Which engine profile is used                        |
| LLM_MODEL                 | string                   | gemini/gemini-3.8-flash                                | LiteLLM model, for example gemini/..., or openai/<name> for an OpenAI-compatible server |
| LLM_API_BASE              | string                   | empty                                                  | Custom endpoint, for example http://host.docker.internal:8000/v1 (never localhost inside Docker) |
| LLM_API_KEY               | secret                   | empty                                                  | API key for the native engine                       |
| HERMES_MODEL              | string                   | openai/hermes                                          | LiteLLM model name for a Hermes endpoint            |
| HERMES_API_BASE           | string                   | empty                                                  | OpenAI-compatible Hermes endpoint                   |
| HERMES_API_KEY            | secret                   | empty                                                  | Hermes endpoint key                                 |
| OPENCLAW_MODEL            | string                   | openai/openclaw                                        | LiteLLM model name for an OpenClaw endpoint         |
| OPENCLAW_API_BASE         | string                   | empty                                                  | OpenAI-compatible OpenClaw endpoint                 |
| OPENCLAW_API_KEY          | secret                   | empty                                                  | OpenClaw endpoint key                               |
| TOOL_ROUTE_TOP_K          | int                      | 8                                                      | Tools loaded per detected app for each message      |
| TOOL_CACHE_TTL_SECONDS    | int                      | 3600                                                   | How long fetched tool lists are cached              |
| DATABASE_URL              | string                   | postgresql://omniclaw:omniclaw@localhost:5432/omniclaw | Postgres DSN                                        |
| POSTGRES_PASSWORD         | secret                   | change-me                                              | Used by docker compose for Postgres and the app DSN |
| MEM0_API_KEY              | secret                   | empty                                                  | Enables Mem0 semantic memory                        |
| R2_ACCOUNT_ID             | string                   | empty                                                  | Cloudflare account id                               |
| R2_ACCESS_KEY_ID          | secret                   | empty                                                  | R2 access key                                       |
| R2_SECRET_ACCESS_KEY      | secret                   | empty                                                  | R2 secret key                                       |
| R2_BUCKET                 | string                   | empty                                                  | R2 bucket for audio and screenshots                 |
| COMPOSIO_API_KEY          | secret                   | empty                                                  | Enables Composio tools                              |
| COMPOSIO_BASE_URL         | string                   | https://backend.composio.dev                           | Composio API base                                   |
| COMPOSIO_USER_ID          | string                   | default                                                | Must equal the user id on your ACTIVE Composio connected accounts |
| NANGO_SECRET_KEY          | secret                   | empty                                                  | Enables the curated Nango tools and proxy tool      |
| NANGO_BASE_URL            | string                   | https://api.nango.dev                                  | Nango API base. Self-hosted from Docker: http://host.docker.internal:<port> |
| NANGO_CONNECTION_ID       | string                   | empty                                                  | Preferred Nango connection id when several exist for a provider |
| TELEGRAM_BOT_TOKEN        | secret                   | empty                                                  | Enables the Telegram channel                        |
| TELEGRAM_ALLOWED_USER_IDS | csv                      | empty                                                  | Allowed Telegram user ids                           |
| WHATSAPP_TOKEN            | secret                   | empty                                                  | WhatsApp Cloud API access token                     |
| WHATSAPP_PHONE_NUMBER_ID  | string                   | empty                                                  | Business phone number id                            |
| WHATSAPP_VERIFY_TOKEN     | secret                   | empty                                                  | Webhook verification token                          |
| WHATSAPP_APP_SECRET       | secret                   | empty                                                  | Used to verify webhook signatures                   |
| WHATSAPP_ALLOWED_NUMBERS  | csv                      | empty                                                  | Allowed sender numbers                              |
| WHATSAPP_GRAPH_VERSION    | string                   | v23.0                                                  | Graph API version                                   |
| ELEVENLABS_API_KEY        | secret                   | empty                                                  | Enables voice synthesis                             |
| ELEVENLABS_VOICE_ID       | string                   | empty                                                  | Voice used for replies                              |
| ELEVENLABS_MODEL_ID       | string                   | eleven_multilingual_v2                                 | TTS model                                           |
| VOICE_REPLIES_ALWAYS      | bool                     | false                                                  | Reply with voice even to text messages              |
| STT_MODEL                 | string                   | whisper-1                                              | LiteLLM transcription model                         |
| STT_API_KEY               | secret                   | empty                                                  | Transcription provider key                          |
| BROWSER_HEADLESS          | bool                     | true                                                   | Run Chromium headless                               |
| BROWSER_STATE_DIR         | path                     | ./.browser_state                                       | Saved login sessions                                |
| BROWSER_ALLOWED_DOMAINS   | csv                      | instagram.com,tinder.com,linkedin.com,github.com       | Domains the browser may visit                       |