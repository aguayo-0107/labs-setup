"""The command-line audit end to end, with a negative control on a mutated copy."""

from __future__ import annotations

import shutil
import subprocess
import sys

import nbformat
import pytest

from labs_audit.adapters.inbound.cli import main

pytestmark = pytest.mark.e2e


def test_cli_passes_on_the_repository(labs_root, capsys):
    assert main(labs_root) == 0
    assert capsys.readouterr().out.strip() == "19 notebooks, 4 Spark JARs, 0 findings -> PASS"


def test_cli_module_runs_as_a_process(labs_root):
    result = subprocess.run(
        [sys.executable, "-m", "labs_audit"], cwd=labs_root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("-> PASS")


def test_negative_control_detects_each_injected_defect(labs_root, tmp_path, capsys):
    copy = tmp_path / "labs"
    for module in ("redis", "spark"):
        shutil.copytree(
            labs_root / module, copy / module,
            ignore=shutil.ignore_patterns("mount", "*.executed.ipynb", "__pycache__", "*.docker-compose.yml"),
        )
    # 1. a saved output in a committed notebook
    lab = copy / "redis" / "redis_lab.ipynb"
    notebook = nbformat.read(lab, as_version=4)
    first_code = next(cell for cell in notebook.cells if cell.cell_type == "code")
    first_code.outputs = [nbformat.v4.new_output("stream", text="leaked")]
    nbformat.write(notebook, lab)
    # 2. a tampered Spark JAR
    jar = copy / "spark" / "jars" / "antlr4-runtime-4.9.3.jar"
    jar.write_bytes(jar.read_bytes() + b"x")

    assert main(copy) == 1
    out = capsys.readouterr().out
    assert "[outputs] redis/redis_lab.ipynb" in out
    assert "[spark-jars] spark/jars/antlr4-runtime-4.9.3.jar: sha256" in out
    assert out.strip().endswith("-> FAIL")
