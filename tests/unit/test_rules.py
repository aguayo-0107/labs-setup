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


def test_no_shell_escapes():
    cells = [
        code("!docker compose -f x.yml up -d --wait"),
        code("x = 1\n  !ls"),
        code("%%bash\nls"),
        code("%sx ls"),
        code("%system ls"),
        code('run_command(["docker", "ps"])\n# !docker ps is only a comment'),
        code("%%sql\nSELECT 1"),
        code("y = a != b"),
        Cell("markdown", "!docker ps"),
    ]
    assert [f.detail for f in rules.no_shell_escapes(nb(*cells))] == [
        f"cell {i} runs a command through the OS shell; use run_command([...])" for i in range(5)
    ]


class TestPortableIo:
    def details(self, *sources):
        return [f.detail for f in rules.portable_io(nb(*(code(s) for s in sources)))]

    def test_compliant_calls_pass(self):
        assert self.details(
            'open(p, encoding="utf-8")',
            'open(p, "w", encoding="utf-8", newline="\\n")',
            'open(p, mode="a", encoding="utf-8", newline="")',
            'open(p, "rb")',
            'open(p, "wb")',
            'Path(p).write_text(t, encoding="utf-8", newline="\\n")',
            'Path(p).read_text(encoding="utf-8")',
            'subprocess.run(["ls"], capture_output=True, text=True, encoding="utf-8")',
            'subprocess.run(["ls"], capture_output=True)',
            'other.run(["ls"], text=True)',
            'print(open)',
            "%%sql\nSELECT 1",
            "%matplotlib inline\nx = 1",
        ) == []

    def test_each_problem_is_reported(self):
        assert self.details(
            "open(p)",
            'open(p, "w", encoding="utf-8")',
            'open(p, mode="x+")',
            'Path(p).write_text(t)',
            'Path(p).read_text()',
            'subprocess.check_output(["ls"], universal_newlines=True)',
            'subprocess.Popen("ls", shell=True)',
            'subprocess.run(\n  ["ls"],\n  text=True,\n)',
            "open(p, mode)",
        ) == [
            "cell 0 line 1: open() without encoding=",
            "cell 1 line 1: open() for writing without newline=",
            "cell 2 line 1: open() without encoding=",
            "cell 2 line 1: open() for writing without newline=",
            "cell 3 line 1: write_text() without encoding=",
            "cell 3 line 1: write_text() without newline=",
            "cell 4 line 1: read_text() without encoding=",
            "cell 5 line 1: subprocess.check_output() decodes output without encoding=",
            "cell 6 line 1: subprocess.Popen() with shell=True",
            "cell 7 line 1: subprocess.run() decodes output without encoding=",
            "cell 8 line 1: open() without encoding=",
        ]

    def test_unparseable_cell(self):
        assert self.details("def (") == ["cell 0 is not valid Python: invalid syntax"]

    def test_markdown_is_ignored(self):
        assert rules.portable_io(nb(Cell("markdown", "open(p)"))) == []


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
    bad["delta-storage-4.3.1.jar"] = None
    bad["delta-kernel-api-4.3.1.jar"] = "0" * 64
    details = {f.path: f.detail for f in rules.jar_checksums(bad)}
    assert details["spark/jars/delta-storage-4.3.1.jar"] == "missing"
    assert details["spark/jars/delta-kernel-api-4.3.1.jar"].startswith("sha256 000")
