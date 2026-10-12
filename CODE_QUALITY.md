# Code Quality

**Header Note:** Automated quality checks (formatting, linting, import sorting, and conventional commit validation) run automatically on `git commit` and `git push` via `pre-commit`. Manual fallback commands are provided below to execute these tools independently.

## Environment Setup

To register and activate the required git hooks and developer tools locally, run:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

The configuration in `.pre-commit-config.yaml` declares `default_install_hook_types`, so running `pre-commit install` automatically sets up the `commit-msg` and `pre-push` hooks as well.

## Manual Execution Commands

You can trigger the quality checks manually without making a commit:

**Run checks repository-wide on ALL files:**
```bash
pre-commit run --all-files
```

**Run checks ONLY on staged files:**
```bash
pre-commit run
```

**Run checks against a target branch or specific files:**
```bash
pre-commit run --from-ref origin/main --to-ref HEAD
pre-commit run --files src/omniclaw/engine.py
```

## Isolated Tool Commands

If you need to run individual code quality tools independently outside of `pre-commit`:

**Linting (Ruff):**
```bash
ruff check .            # lint only, report errors
ruff check . --fix      # lint and automatically fix safe issues
```

**Formatting (Ruff):**
```bash
ruff format .           # format all files
ruff format --check .   # check formatting without applying changes
```

**Testing (Pytest):**
```bash
pytest                  # run the full test suite
```

## Maintenance & Cache

Commands to update hooks/dependencies to their latest versions and clear local tool caches:

```bash
pre-commit autoupdate   # bump hook versions in .pre-commit-config.yaml
pre-commit clean        # clear local pre-commit environments
ruff clean              # clear the local ruff cache
```

## Emergency Bypassing

In the event of a critical hotfix or an emergency where you must bypass the automated checks locally, use the official override flags:

```bash
git commit --no-verify
git push --no-verify
```

*Warning: Use these bypass flags responsibly. CI pipelines will still enforce these checks on all pull requests, and failing code will be blocked from merging into the main branch.*