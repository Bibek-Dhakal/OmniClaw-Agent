# Architecture

## Request flow

```mermaid
sequenceDiagram
    participant U as Owner
    participant C as Channel (Telegram/WhatsApp)
    participant O as Orchestrator
    participant M as Memory (Mem0, Postgres, R2)
    participant E as Engine (LiteLLM)
    participant T as Tool registry
    participant X as Connectors / Browser

    U->>C: text or voice
    C->>O: Inbound
    O->>O: transcribe voice, check pending approval
    O->>M: recall memories and history
    O->>E: messages + tool specs
    loop up to MAX_AGENT_STEPS
        E->>T: tool call
        T->>U: approval request (if risky)
        U-->>T: YES / NO
        T->>X: execute
        T->>M: log action (Postgres)
        T-->>E: result
    end
    E-->>O: final answer
    O->>M: store turn
    O-->>C: text + optional voice
    C-->>U: reply
```

## Components

| Module | Responsibility |
| --- | --- |
| `config.py` | Single source of truth for settings |
| `main.py` | Daemon wiring and CLI |
| `channels/telegram.py` | Telegram polling channel |
| `channels/whatsapp.py` | WhatsApp webhook channel |
| `orchestrator.py` | Per-message pipeline |
| `engine.py` | Async tool-calling loop over LiteLLM `acompletion` |
| `tools.py` | Tool registry, approval gate, action logging |
| `approvals.py` | YES/NO approval broker |
| `connectors.py` | Composio and Nango tools |
| `browser.py` | Playwright session manager and browser tools |
| `memory.py` | Postgres, Mem0 and R2 stores |
| `voice.py` | Transcription and ElevenLabs synthesis |

## Design decisions

* Hermes and OpenClaw are reached as OpenAI-compatible endpoints through LiteLLM, so one code path serves every engine.
* Structured platforms go through connectors (Composio, Nango). Only apps without usable APIs go through the browser.
* The browser can only visit allowlisted domains and re-checks the final URL after redirects.
* Outbound or irreversible actions pass through the approval broker before the handler runs.
* A per-chat lock serializes turns. Approval replies bypass the lock so they can resolve a waiting tool call.
* Memory failures degrade gracefully and never block a reply.

## Data model

```mermaid
erDiagram
    messages {
        bigint id PK
        text channel
        text chat_id
        text role
        text content
        timestamptz created_at
    }
    actions {
        bigint id PK
        text channel
        text chat_id
        text tool
        text args
        boolean ok
        text result
        timestamptz created_at
    }
```