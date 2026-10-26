"""labs_parity as the Spark infrastructure notebook uses it: imported from the
labs-setup root in a fresh interpreter, reading `pip freeze` through a real
`docker` process (a stand-in executable on PATH), plus the drift that must stop
the notebook (negative control)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

FAKE_DOCKER = """#!{python}
import sys
image = sys.argv[sys.argv.index("--entrypoint") + 2]
listings = {{
    "driver:1": "Faker==40.36.0\\npandas==2.3.3\\njupyterlab==4.6.4\\n",
    "worker-same:1": "faker==40.36.0\\npandas==2.3.3\\nmimesis==22.2.0\\n",
    "worker-drift:1": "faker==40.43.0\\npandas==2.3.3\\n",
}}
if image not in listings:
    sys.stderr.write("Unable to find image\\n")
    sys.exit(125)
sys.stdout.write(listings[image])
"""

CELL = """
from labs_parity import PythonEnvironment, check_python_parity
check_python_parity(PythonEnvironment("driver:1", "python3"), PythonEnvironment("{worker}", "/venv/bin/python3"))
"""


@pytest.fixture()
def fake_docker_path(tmp_path):
    executable = tmp_path / "docker"
    executable.write_text(FAKE_DOCKER.format(python=sys.executable), encoding="utf-8")
    executable.chmod(0o755)
    return f"{tmp_path}{os.pathsep}{os.environ['PATH']}"


def run_cell(labs_root, path, worker):
    return subprocess.run(
        [sys.executable, "-c", CELL.format(worker=worker)],
        cwd=labs_root,
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_equal_images_pass(labs_root, fake_docker_path):
    completed = run_cell(labs_root, fake_docker_path, "worker-same:1")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "Same versions in driver:1 (python3) and worker-same:1 (/venv/bin/python3): 2 shared packages (faker, pandas)\n"


def test_a_drifted_worker_stops_the_cell(labs_root, fake_docker_path):
    completed = run_cell(labs_root, fake_docker_path, "worker-drift:1")
    assert completed.returncode == 1
    assert "labs_parity.domain.errors.EnvironmentsDiffer:" in completed.stderr
    assert "differ in 1 shared package(s): faker: 40.36.0 vs 40.43.0" in completed.stderr


def test_a_missing_image_stops_the_cell(labs_root, fake_docker_path):
    completed = run_cell(labs_root, fake_docker_path, "missing:1")
    assert completed.returncode == 1
    assert "CommandFailed: exit code 125" in completed.stderr
