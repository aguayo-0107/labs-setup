"""Shared test configuration: make `labs_audit` importable and expose the repo root."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def labs_root() -> Path:
    return ROOT
