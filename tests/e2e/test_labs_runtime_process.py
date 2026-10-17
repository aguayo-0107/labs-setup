"""labs_runtime as a notebook uses it: imported from the labs-setup root in a
fresh interpreter, running a real child process with arguments a shell would
have rewritten, plus the failure path (negative control)."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

NOTEBOOK_CELL = """
import sys
from labs_runtime import run_command
result = run_command([sys.executable, "-c", "import sys; print(sys.argv[1:])", "*.csv", "$HOME", "a | b > c"])
print("returncode", result.returncode)
"""


def run_cell(labs_root, source):
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=labs_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_arguments_reach_the_program_verbatim(labs_root):
    completed = run_cell(labs_root, NOTEBOOK_CELL)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == ["['*.csv', '$HOME', 'a | b > c']", "returncode 0"]


def test_a_failing_command_stops_the_cell(labs_root):
    completed = run_cell(
        labs_root,
        "import sys\nfrom labs_runtime import run_command\n"
        "run_command([sys.executable, '-c', 'print(\"boom\"); raise SystemExit(7)'])\nprint('not reached')",
    )
    assert completed.returncode == 1
    assert completed.stdout == "boom\n"
    assert "labs_runtime.domain.errors.CommandFailed: exit code 7:" in completed.stderr


def test_check_false_reports_and_continues(labs_root):
    completed = run_cell(
        labs_root,
        "import sys\nfrom labs_runtime import run_command\n"
        "run_command([sys.executable, '-c', 'raise SystemExit(9)'], check=False)\nprint('continued')",
    )
    assert completed.returncode == 0
    assert completed.stdout == "[exit code 9]\ncontinued\n"
