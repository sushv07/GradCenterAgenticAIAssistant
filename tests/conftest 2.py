"""conftest.py — adds the project root to sys.path so root-level shims resolve correctly.

This file is loaded automatically by pytest when running tests in this directory.
It also enables direct execution:  python tests/test_router.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
