# Testing

## Tiers

* **Unit**: config parsing, domain allowlist, approval policy, webhook signature and payload parsing.
* **Component**: the engine tool loop with a faked `acompletion`, and the approval gate with a real broker.
* **Manual end-to-end**: Telegram, WhatsApp, connectors, voice and browser flows against real accounts.

## Running

```bash
pip install -e ".[dev]"
pytest
```

Coverage is reported automatically (`pytest-cov`). Pre-push hooks and CI run the same command.

## Mock strategy

External services (LLM, Composio, Nango, Telegram, WhatsApp, ElevenLabs, Postgres) are never contacted by tests. Fake
the boundary function (for example `omniclaw.engine.acompletion`) with `monkeypatch`.

## CI

`.github/workflows/ci.yml` runs `ruff check`, `ruff format --check` and `pytest` on every push and pull request.