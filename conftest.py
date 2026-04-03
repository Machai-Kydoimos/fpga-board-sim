"""Add src/ to sys.path so the fpga_sim package is importable under pytest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
