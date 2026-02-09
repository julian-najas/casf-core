import sys
from pathlib import Path

# Repo root = .../casf-core
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "services" / "verifier" / "src"

if str(SRC) not in sys.path:
	sys.path.insert(0, str(SRC))
