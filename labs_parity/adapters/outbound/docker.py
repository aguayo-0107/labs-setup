"""Inventory read with `docker run --rm <image> <python> -m pip freeze`.

Without `--all`, so each interpreter's own installer (pip, setuptools, wheel) is
left out: it is not imported by the lab code and differs between a venv and the
system Python by design.
"""

from __future__ import annotations

from labs_runtime.domain.errors import CommandFailed
from labs_runtime.domain.models import CommandResult
from labs_runtime.ports.outbound import OutputSinkPort, ProcessRunnerPort

from ...domain.models import PythonEnvironment
from ...ports.outbound import PackageInventoryPort


class DockerImageInventory(PackageInventoryPort):
    def __init__(self, runner: ProcessRunnerPort, sink: OutputSinkPort) -> None:
        self._runner = runner
        self._sink = sink

    def freeze(self, environment: PythonEnvironment) -> str:
        argv = ("docker", "run", "--rm", "--entrypoint", environment.python, environment.image, "-m", "pip", "freeze")
        returncode, output = self._runner.run(argv, self._sink)
        if returncode != 0:
            raise CommandFailed(CommandResult(argv, returncode, output))
        return output
