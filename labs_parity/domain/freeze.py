"""Pure rules: read `pip freeze` output and compare two inventories."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .models import VersionDifference

_SEPARATORS = re.compile(r"[-_.]+")


def canonical_name(name: str) -> str:
    """PEP 503 normalized name: `Faker` and `faker`, `a_b` and `a-b` are one package."""
    return _SEPARATORS.sub("-", name.strip()).lower()


def parse_freeze(text: str) -> dict[str, str]:
    """Map each installed distribution to its version (or its direct reference)."""
    inventory: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
        elif " @ " in line:
            name, reference = line.split(" @ ", 1)
            version = "@ " + reference.strip()
        else:
            raise ValueError(f"unexpected pip freeze line: {raw!r}")
        inventory[canonical_name(name)] = version.strip()
    return inventory


def compare(left: Mapping[str, str], right: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[VersionDifference, ...]]:
    """Packages installed in both, and those whose versions differ."""
    shared = tuple(sorted(set(left) & set(right)))
    differences = tuple(VersionDifference(name, left[name], right[name]) for name in shared if left[name] != right[name])
    return shared, differences
