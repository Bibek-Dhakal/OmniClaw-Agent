# Usage

## Commands

```bash
omniclaw run                  # start the daemon (channels + webhook server)
omniclaw login <domain>       # headful login that saves a browser session, e.g. instagram.com
docker compose up --build     # run the full stack
pytest                        # run tests
```

`omniclaw login` opens a visible browser, so run it on a machine with a display. The session is saved to
`BROWSER_STATE_DIR` and can be mounted into the container.

## Channels

* Telegram needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_IDS`. Only listed users are served.
* WhatsApp needs all four of `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` and
  `WHATSAPP_APP_SECRET`. Set the Meta webhook callback to `https://<host>/webhook/whatsapp`.

## Approvals

Tools that send, post or modify are held until the owner replies YES (or NO) in the same chat. Read-only Composio tools
(slug contains FETCH, LIST, GET, SEARCH, FIND or READ) and GET Nango calls run without approval. Set
`APPROVAL_REQUIRED=false` to disable the gate.

## Environment variables

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| LOG_LEVEL | string | INFO | Python logging level |
| HOST | string | 127.0.0.1 | Webhook server bind address |
| PORT | int | 8080 | Webhook server port |
| OWNER_NAME | string | Owner | Name used in the system prompt |
| MEMORY_USER_ID | string | owner | Mem0 user id, shared across channels |
| MAX_AGENT_STEPS | int | 8 | Maximum tool-call rounds per request |
| HISTORY_TURNS | int | 12 | Conversation turns loaded from Postgres |
| APPROVAL_REQUIRED | bool | true | Require owner approval for risky tools |
| APPROVAL_TIMEOUT_SECONDS | int | 300 | Approval wait time before rejection |
| AGENT_ENGINE | native, hermes, openclaw | native | Which engine profile is used |
| LLM_MODEL | string | gemini/gemini-3.8-flash | LiteLLM model for the native engine |
| LLM_API_BASE | string | empty | Optional API base for the native engine |
| LLM_API_KEY | secret | empty | API key for the native engine |
| HERMES_MODEL | string | openai/hermes | LiteLLM model name for a Hermes endpoint |
| HERMES_API_BASE | string | empty | OpenAI-compatible Hermes endpoint |
| HERMES_API_KEY | secret | empty | Hermes endpoint key |
| OPENCLAW_MODEL | string | openai/openclaw | LiteLLM model name for an OpenClaw endpoint |
| OPENCLAW_API_BASE | string | empty | OpenAI-compatible OpenClaw endpoint |
| OPENCLAW_API_KEY | secret | empty | OpenClaw endpoint key |
| DATABASE_URL | string | postgresql://omniclaw:omniclaw@localhost:5432/omniclaw | Postgres DSN |
| POSTGRES_PASSWORD | secret | change-me | Used by docker compose for Postgres and the app DSN |
| MEM0_API_KEY | secret | empty | Enables Mem0 semantic memory |
| R2_ACCOUNT_ID | string | empty | Cloudflare account id |
| R2_ACCESS_KEY_ID | secret | empty | R2 access key |
| R2_SECRET_ACCESS_KEY | secret | empty | R2 secret key |
| R2_BUCKET | string | empty | R2 bucket for audio and screenshots |
| COMPOSIO_API_KEY | secret | empty | Enables Composio tools |
| COMPOSIO_BASE_URL | string | https://backend.composio.dev | Composio API base |
| COMPOSIO_USER_ID | string | default | Composio entity or user id |
| NANGO_SECRET_KEY | secret | empty | Enables Nango proxy tool |
| NANGO_BASE_URL | string | https://api.nango.dev | Nango API base (change if self-hosting Nango) |
| NANGO_CONNECTION_ID | string | empty | Default Nango connection id |
| TELEGRAM_BOT_TOKEN | secret | empty | Enables the Telegram channel |
| TELEGRAM_ALLOWED_USER_IDS | csv | empty | Allowed Telegram user ids |
| WHATSAPP_TOKEN | secret | empty | WhatsApp Cloud API access token |
| WHATSAPP_PHONE_NUMBER_ID | string | empty | Business phone number id |
| WHATSAPP_VERIFY_TOKEN | secret | empty | Webhook verification token |
| WHATSAPP_APP_SECRET | secret | empty | Used to verify webhook signatures |
| WHATSAPP_ALLOWED_NUMBERS | csv | empty | Allowed sender numbers |
| WHATSAPP_GRAPH_VERSION | string | v23.0 | Graph API version |
| ELEVENLABS_API_KEY | secret | empty | Enables voice synthesis |
| ELEVENLABS_VOICE_ID | string | empty | Voice used for replies |
| ELEVENLABS_MODEL_ID | string | eleven_multilingual_v2 | TTS model |
| VOICE_REPLIES_ALWAYS | bool | false | Reply with voice even to text messages |
| STT_MODEL | string | whisper-1 | LiteLLM transcription model |
| STT_API_KEY | secret | empty | Transcription provider key |
| BROWSER_HEADLESS | bool | true | Run Chromium headless |
| BROWSER_STATE_DIR | path | ./.browser_state | Saved login sessions |
| BROWSER_ALLOWED_DOMAINS | csv | instagram.com,tinder.com,linkedin.com | Domains the browser may visit |