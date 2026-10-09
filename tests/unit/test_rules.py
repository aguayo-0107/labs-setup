"""Audit rules and models on synthetic notebooks."""

from __future__ import annotations

import pytest

from labs_audit.domain import rules
from labs_audit.domain.models import AuditReport, Cell, Finding, Notebook

pytestmark = pytest.mark.unit

PARAMS = "\n".join(rules.PARAMETER_DEFAULTS)


def nb(*cells, path="x/x_lab.ipynb", kernel=rules.KERNEL):
    return Notebook(path, tuple(cells), kernel)


def code(source="", tags=(), outputs=0, count=None):
    return Cell("code", source, tuple(tags), outputs, count)


def test_models():
    assert nb(path="a/a_infra.ipynb").is_infra and not nb().is_infra
    assert str(Finding("r", "p", "d")) == "[r] p: d"
    report = AuditReport()
    assert not report.passed  # nothing audited is not a pass
    report.notebooks.append("n")
    assert report.passed
    report.findings.append(Finding("r", "p", "d"))
    assert not report.passed


class TestParameters:
    def test_lab_ok(self):
        assert rules.parameters_cell(nb(code(PARAMS, ["parameters"]))) == []

    def test_infra_requires_start_from_scratch(self):
        found = rules.parameters_cell(nb(code(PARAMS, ["parameters"]), path="a/a_infra.ipynb"))
        assert [f.detail for f in found] == ["missing default 'START_FROM_SCRATCH = False'"]
        ok = code(PARAMS + "\nSTART_FROM_SCRATCH = False", ["parameters"])
        assert rules.parameters_cell(nb(ok, path="a/a_infra.ipynb")) == []

    def test_quoted_boolean_is_rejected(self):
        bad = code(PARAMS + '\nSTART_FROM_SCRATCH = "False"', ["parameters"])
        assert rules.parameters_cell(nb(bad, path="a/a_infra.ipynb"))

    def test_wrong_default(self):
        found = rules.parameters_cell(nb(code(PARAMS.replace('"local"', '"vpn"'), ["parameters"])))
        assert found[0].detail == "missing default 'NETWORK_MODE = \"local\"'"

    @pytest.mark.parametrize("count", [0, 2])
    def test_exactly_one_cell(self, count):
        cells = [code(PARAMS, ["parameters"])] * count
        assert rules.parameters_cell(nb(*cells))[0].detail == f"expected 1 parameters cell, found {count}"


def test_kernel():
    assert rules.kernel(nb()) == []
    assert rules.kernel(nb(kernel="python3"))[0].rule == "kernel"


def test_no_outputs():
    cells = [code(), code(outputs=1), code(count=3), Cell("markdown", "x")]
    assert [f.detail for f in rules.no_outputs(nb(*cells))] == [
        "cell 1 has saved outputs or an execution count",
        "cell 2 has saved outputs or an execution count",
    ]


def test_in_sync_ignores_trailing_whitespace():
    assert rules.in_sync(nb(code("a\n")), nb(code("a"))) == []
    assert rules.in_sync(nb(code("a")), nb(code("b")))[0].rule == "sync"


def test_compose_wait_checked():
    wait = "!docker compose -f x.yml up -d --wait"
    cells = [
        code(f"{wait}\nassert _exit_code == 0, 'x'"),
        code(wait),
        code(f"assert _exit_code == 0\n{wait}"),
        code("!docker compose -f x.yml up -d"),
        Cell("markdown", wait),
    ]
    assert [f.detail for f in rules.compose_wait_checked(nb(*cells))] == [
        "cell 1 ignores the exit status of compose --wait",
        "cell 2 ignores the exit status of compose --wait",
    ]


def test_no_windows_paths():
    cells = [
        code('volumes = [f".\\\\mount\\\\{name}:/data"]'),
        code("p = os.path.join(DOCKER_MOUNTDIR, name)"),
        Cell("markdown", '".\\\\mount"'),
    ]
    assert [f.detail for f in rules.no_windows_paths(nb(*cells))] == [
        "cell 0 uses a Windows-only path separator"
    ]


def test_jar_checksums():
    good = dict(rules.SPARK_JARS)
    assert rules.jar_checksums(good) == []
    bad = dict(good)
    bad["delta-storage-3.2.0.jar"] = None
    bad["antlr4-runtime-4.9.3.jar"] = "0" * 64
    details = {f.path: f.detail for f in rules.jar_checksums(bad)}
    assert details["spark/jars/delta-storage-3.2.0.jar"] == "missing"
    assert details["spark/jars/antlr4-runtime-4.9.3.jar"].startswith("sha256 000")
