"""Repository-only tests: python -m unittest discover -s tests -t ."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "skills" / "debug-agent" / "scripts")]
