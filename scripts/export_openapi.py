#!/usr/bin/env python3
"""
export_openapi.py — Export the Verifier's OpenAPI schema to contracts/openapi.json.

Usage:
    python scripts/export_openapi.py              # write to contracts/openapi.json
    python scripts/export_openapi.py --check      # exit 1 if file diverges (CI gate)

Requires the verifier package to be importable (pip install -e services/verifier).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Stub env vars so settings.py doesn't raise on import
os.environ.setdefault("PG_DSN", "postgresql://stub:stub@localhost/stub")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPA_URL", "http://localhost:8181")

from verifier.main import app  # noqa: E402

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
OUTPUT_PATH = CONTRACTS_DIR / "openapi.json"


def _canonical(schema: dict[str, object]) -> str:
    """Deterministic JSON output for reproducible diffs."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    schema = app.openapi()
    rendered = _canonical(schema)

    check_mode = "--check" in sys.argv

    if check_mode:
        if not OUTPUT_PATH.exists():
            print(f"FAIL: {OUTPUT_PATH} does not exist. Run: make openapi")
            raise SystemExit(1)
        existing = OUTPUT_PATH.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"FAIL: {OUTPUT_PATH} is out of date. Run: make openapi")
            raise SystemExit(1)
        print(f"OK: {OUTPUT_PATH} is up to date.")
        return

    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(rendered)} bytes)")


if __name__ == "__main__":
    main()
