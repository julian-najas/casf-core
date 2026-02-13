# Contributing to casf-core

Thank you for your interest in contributing.

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- OPA 0.63.0+ (or use Docker)

## Setup (3 commands)

```bash
cd services/verifier
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
```

## Development workflow

```bash
# Run all checks
make lint          # ruff + mypy
make fmt           # auto-format code (ruff format)
make test          # pytest (requires Postgres + Redis + OPA)
make opa-test      # OPA policy tests via Docker
make smoke         # Full-stack smoke test
make build         # Build Docker image
make check         # All gates: lint + format + test + OPA

# Start/stop the stack
make up            # docker compose up --build -d
make down          # docker compose down -v
```

## Running tests locally

Tests require Postgres, Redis, and OPA. The easiest way:

```bash
make up            # starts the full stack
make test          # runs pytest against local services
make opa-test      # runs OPA policy tests
```

Or run the full stack + smoke test:

```bash
make smoke
```

## Code standards

- **Linter**: ruff (config in `pyproject.toml`)
- **Types**: mypy with `check_untyped_defs = true`
- **Tests**: pytest — new code must include tests
- **OPA**: `opa test` + `opa fmt` — policies in `policies/` only

## Pre-commit

Install the hooks:

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on `git commit`. To run manually:

```bash
pre-commit run --all-files
```

## Pull request process

1. Branch from `main`.
2. All checks must pass (`make lint`, `make test`, `make opa-test`).
3. Update `CHANGELOG.md` under `[Unreleased]`.
4. PRs require review from a CODEOWNER.

## Scope policy

**casf-core is scope-frozen.** Only these changes are accepted:

- Critical bug fixes
- Security patches
- Documentation corrections
- Governance / supply-chain improvements

New features belong to a separate project or layer.

## Reporting security issues

See [SECURITY.md](SECURITY.md).

## Release process

Releases follow **strict SemVer** (`MAJOR.MINOR.PATCH`):

1. Update `CHANGELOG.md`: move `[Unreleased]` items to a new version heading.
2. Commit: `git commit -m "release: vX.Y.Z"`
3. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`
4. Push: `git push origin main --tags`
5. Create a **GitHub Release** from the tag with the changelog section as body.

**Rules:**
- Tags are **immutable** — never delete or re-tag.
- Every release must have CI green before tagging.
- Release notes are the corresponding `CHANGELOG.md` section (copy verbatim).

