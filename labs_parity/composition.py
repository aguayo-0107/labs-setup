"""Composition root: the only place the concrete adapters are named."""

from __future__ import annotations

from labs_runtime.adapters.outbound.process import SubprocessRunner
from labs_runtime.adapters.outbound.sink import StdoutSink

from .adapters.outbound.docker import DockerImageInventory
from .adapters.outbound.sink import DiscardSink
from .application.service import CheckParityService
from .ports.inbound import CheckParityUseCase

check_python_parity: CheckParityUseCase = CheckParityService(
    DockerImageInventory(SubprocessRunner(), DiscardSink()), StdoutSink()
)
