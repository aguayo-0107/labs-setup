"""Use case with fake ports, filesystem adapters on temporary trees, and the CLI."""

from __future__ import annotations

import hashlib
import runpy

import jupytext
import nbformat
import pytest

from labs_audit.adapters.inbound import cli
from labs_audit.adapters.outbound.filesystem import FileJarStore, FileNotebookSource
from labs_audit.application.service import LabsAuditService
from labs_audit.domain import rules
from labs_audit.domain.models import AuditReport, Cell, Notebook
from labs_audit.ports.inbound import AuditLabsUseCase
from labs_audit.ports.outbound import JarStorePort, NotebookSourcePort

pytestmark = pytest.mark.unit

PARAMS = "\n".join(rules.PARAMETER_DEFAULTS)


class FakeNotebooks(NotebookSourcePort):
    def __init__(self, committed_source=PARAMS):
        self.source = committed_source

    def pairs(self):
        return ("m/m_lab",)

    def committed(self, stem):
        return Notebook(f"{stem}.ipynb", (Cell("code", self.source, ("parameters",)),), rules.KERNEL)

    def canonical(self, stem):
        return Notebook(f"{stem}.py", (Cell("code", PARAMS, ("parameters",)),), rules.KERNEL)


class FakeJars(JarStorePort):
    def __init__(self, digests=None):
        self.values = dict(rules.SPARK_JARS) if digests is None else digests

    def digests(self):
        return self.values


def test_service_passes_and_reports():
    service = LabsAuditService(FakeNotebooks(), FakeJars())
    assert isinstance(service, AuditLabsUseCase)
    report = service.audit()
    assert report.passed and report.notebooks == ["m/m_lab.ipynb"] and len(report.jars) == 6


def test_service_collects_findings():
    report = LabsAuditService(FakeNotebooks(PARAMS + "\nx = 1"), FakeJars({})).audit()
    assert {f.rule for f in report.findings} == {"sync", "spark-jars"}
    assert report.jars == []


def write_pair(folder, stem, source, outputs=False):
    text = (
        "# ---\n# jupyter:\n#   kernelspec:\n#     display_name: labs\n#     language: python\n"
        f"#     name: {rules.KERNEL}\n# ---\n\n# %% tags=[\"parameters\"]\n{source}\n"
    )
    (folder / f"{stem}.py").write_text(text, encoding="utf-8")
    notebook = jupytext.reads(text, fmt="py:percent")
    if outputs:
        notebook.cells[0].outputs = [nbformat.v4.new_output("stream", text="x")]
        notebook.cells[0].execution_count = 1
    nbformat.write(notebook, folder / f"{stem}.ipynb")


def test_filesystem_adapters(tmp_path):
    (tmp_path / "redis").mkdir()
    write_pair(tmp_path / "redis", "redis_lab", PARAMS, outputs=True)
    (tmp_path / "redis" / "helper.py").write_text("x = 1", encoding="utf-8")  # no .ipynb: not a pair
    source = FileNotebookSource(tmp_path)
    assert source.pairs() == ("redis/redis_lab",)
    committed = source.committed("redis/redis_lab")
    assert committed.kernel == rules.KERNEL and committed.cells[0].outputs == 1
    assert committed.cells[0].execution_count == 1 and committed.cells[0].tags == ("parameters",)
    assert source.canonical("redis/redis_lab").path == "redis/redis_lab.py"

    jars = tmp_path / "spark" / "jars"
    jars.mkdir(parents=True)
    (jars / "delta-storage-3.2.0.jar").write_bytes(b"jar")
    digests = FileJarStore(tmp_path).digests()
    assert digests["delta-storage-3.2.0.jar"] == hashlib.sha256(b"jar").hexdigest()
    assert digests["antlr4-runtime-4.9.3.jar"] is None


class FakeAudit(AuditLabsUseCase):
    def __init__(self, report):
        self.report = report

    def audit(self):
        return self.report


def test_cli_main(monkeypatch, capsys, tmp_path):
    from labs_audit.domain.models import Finding

    passing = AuditReport(notebooks=["a"])
    monkeypatch.setattr(cli, "build_audit", lambda root: FakeAudit(passing))
    assert cli.main(tmp_path) == 0
    assert capsys.readouterr().out.strip().endswith("0 findings -> PASS")

    failing = AuditReport(notebooks=["a"], findings=[Finding("r", "p", "d")])
    monkeypatch.setattr(cli, "build_audit", lambda root: FakeAudit(failing))
    assert cli.main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "[r] p: d" in out and out.strip().endswith("FAIL")


def test_build_audit_and_root():
    assert isinstance(cli.build_audit(cli.ROOT), LabsAuditService)
    assert (cli.ROOT / "pyproject.toml").is_file()


def test_module_entrypoint(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda: 0)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("labs_audit", run_name="__main__")
    assert raised.value.code == 0
    runpy.run_module("labs_audit", run_name="imported")
