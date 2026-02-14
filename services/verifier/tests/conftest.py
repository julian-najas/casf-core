"""conftest.py - pytest auto-loaded configuration.

Adds src/ and tests/ to sys.path so that:
  - `from src.verifier.xxx import ...` works inside tests, and
  - `from helpers import ...` resolves the shared test helpers module.

All reusable helpers live in tests/helpers.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "services" / "verifier" / "src"
TESTS_DIR = Path(__file__).resolve().parent

for _p in (str(SRC), str(TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
