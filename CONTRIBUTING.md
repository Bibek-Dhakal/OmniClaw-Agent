# Contributing to OmniClaw Agent

## Setup

```bash
python -m venv .venv
pip install -e ".[dev]"
playwright install chromium
pre-commit install
```

`pre-commit install` registers the commit-msg and pre-push hooks too (see [CODE_QUALITY.md](CODE_QUALITY.md)).

## Code style

* Ruff handles linting, import sorting and formatting. Configuration lives in `pyproject.toml`.
* Keep everything async. LLM calls go through LiteLLM `acompletion()` only.
* Configuration has one source of truth: `src/omniclaw/config.py`. Do not repeat constants.
* Never commit `.env`; add new variables to `.env.example` and `docs/usage.md`.

## Testing

```bash
pytest
```

Tests must not need network access. Fake external services.

## Conventional Commits (strictly enforced)

All commit messages and pull request titles must follow `type(scope): message`.
They drive automated versioning and `CHANGELOG.md` generation through `release-please` Release PRs.

| Prefix | Effect |
| --- | --- |
| `feat:` | Minor version bump |
| `fix:` | Patch version bump |
| `feat!:` / `fix!:` or a `BREAKING CHANGE:` footer | Major version bump |
| `docs:`, `chore:`, `style:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:` | No release on their own |

Changes merged into `main` accumulate in a long-running Release PR. A release is cut only when that PR is merged.

## Pull requests

1. Branch from `main`.
2. Keep PRs focused; update docs and tests that your change affects.
3. Ensure `ruff check .`, `ruff format --check .` and `pytest` pass.
4. Use a Conventional Commit style PR title.