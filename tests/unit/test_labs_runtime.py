"""labs_runtime: shell-free command execution used by the notebooks."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from labs_runtime import CommandFailed, CommandResult, run_command
from labs_runtime.adapters.outbound.process import SubprocessRunner
from labs_runtime.adapters.outbound.sink import StdoutSink
from labs_runtime.application.service import RunCommandService
from labs_runtime.ports.inbound import RunCommandUseCase
from labs_runtime.ports.outbound import OutputSinkPort, ProcessRunnerPort

pytestmark = pytest.mark.unit


class ListSink(OutputSinkPort):
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)


class FakeRunner(ProcessRunnerPort):
    def __init__(self, returncode: int, output: str) -> None:
        self.returncode = returncode
        self.output = output
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], sink: OutputSinkPort) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        sink.write(self.output)
        return self.returncode, self.output


def test_result_model():
    assert CommandResult(("a",), 0, "").succeeded
    assert not CommandResult(("a",), 2, "").succeeded


def test_success_returns_result_and_coerces_arguments():
    runner, sink = FakeRunner(0, "ok\n"), ListSink()
    result = RunCommandService(runner, sink)(["docker", Path("x") / "y"])
    assert runner.calls == [("docker", str(Path("x") / "y"))]
    assert result == CommandResult(("docker", str(Path("x") / "y")), 0, "ok\n")
    assert sink.parts == ["ok\n"]


def test_failure_raises_by_default_with_the_output_tail():
    service = RunCommandService(FakeRunner(5, "x" * 5000 + "fin"), ListSink())
    with pytest.raises(CommandFailed) as caught:
        service(["docker", "compose", "up"])
    assert caught.value.result.returncode == 5
    message = str(caught.value)
    assert message.startswith("exit code 5: docker compose up\n")
    assert message.endswith("fin") and len(message) < 4100


def test_failure_is_reported_but_not_raised_without_check():
    sink = ListSink()
    result = RunCommandService(FakeRunner(9, "ya existe\n"), sink)(["groupadd", "hive"], check=False)
    assert result.returncode == 9
    assert sink.parts == ["ya existe\n", "[exit code 9]\n"]


def test_empty_command_is_rejected():
    with pytest.raises(ValueError, match="argv must not be empty"):
        RunCommandService(FakeRunner(0, ""), ListSink())([])


def test_subprocess_runner_streams_stdout_and_stderr_as_utf8():
    sink = ListSink()
    code = "import sys; sys.stdout.buffer.write('año\\n'.encode()); sys.stdout.flush(); sys.stderr.write('err\\n'); sys.exit(3)"
    returncode, output = SubprocessRunner().run([sys.executable, "-c", code], sink)
    assert returncode == 3
    assert "año\n" in output and "err\n" in output
    assert "".join(sink.parts) == output


def test_subprocess_runner_does_not_use_a_shell():
    # A shell would expand the glob and the variable; argv delivers them verbatim.
    sink = ListSink()
    code = "import sys; print(sys.argv[1:])"
    _, output = SubprocessRunner().run([sys.executable, "-c", code, "*", "$HOME", "a | b"], sink)
    assert output.strip() == "['*', '$HOME', 'a | b']"


def test_subprocess_runner_replaces_undecodable_bytes():
    code = "import sys; sys.stdout.buffer.write(b'\\xff\\n')"
    _, output = SubprocessRunner().run([sys.executable, "-c", code], ListSink())
    assert output == "\ufffd\n"


def test_stdout_sink_uses_the_current_stdout(capsys):
    StdoutSink().write("visible\n")
    assert capsys.readouterr().out == "visible\n"


def test_composition_root_exposes_the_use_case():
    assert isinstance(run_command, RunCommandUseCase)
