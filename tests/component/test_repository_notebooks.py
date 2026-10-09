"""The audit applied to the real notebooks and JARs of this repository."""

from __future__ import annotations

import pytest

from labs_audit.adapters.inbound.cli import build_audit

pytestmark = pytest.mark.component


def test_every_lab_pair_and_jar_passes(labs_root):
    report = build_audit(labs_root).audit()
    assert len(report.notebooks) == 17, report.notebooks
    assert len(report.jars) == 4
    assert report.findings == [], "\n".join(map(str, report.findings))
