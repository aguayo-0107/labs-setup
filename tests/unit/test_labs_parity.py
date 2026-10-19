"""labs_parity: same package versions in the Spark Driver and Worker images."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from labs_parity import EnvironmentsDiffer, PythonEnvironment, VersionDifference, check_python_parity
from labs_parity.adapters.outbound.docker import DockerImageInventory
from labs_parity.adapters.outbound.sink import DiscardSink
from labs_parity.application.service import CheckParityService
from labs_parity.domain.freeze import canonical_name, compare, parse_freeze
from labs_parity.domain.models import ParityReport
from labs_parity.ports.inbound import CheckParityUseCase
from labs_parity.ports.outbound import PackageInventoryPort
from labs_runtime import CommandFailed
from labs_runtime.ports.outbound import OutputSinkPort, ProcessRunnerPort

pytestmark = pytest.mark.unit

DRIVER = PythonEnvironment("spark-jupyter:test", "python3")
WORKER = PythonEnvironment("spark-job-venv:test", "/opt/spark/venv-build/spark_job_env/bin/python3")


class ListSink(OutputSinkPort):
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)


class FakeInventory(PackageInventoryPort):
    def __init__(self, listings: dict[str, str]) -> None:
        self.listings = listings

    def freeze(self, environment: PythonEnvironment) -> str:
        return self.listings[environment.image]


class FakeRunner(ProcessRunnerPort):
    def __init__(self, returncode: int, output: str) -> None:
        self.returncode, self.output = returncode, output
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], sink: OutputSinkPort) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        sink.write(self.output)
        return self.returncode, self.output


def test_canonical_name_follows_pep_503():
    assert canonical_name(" Faker ") == "faker"
    assert canonical_name("faker_commerce") == canonical_name("Faker.Commerce") == "faker-commerce"


def test_parse_freeze_reads_pins_references_and_skips_noise():
    text = "# comment\n\nFaker==40.43.0\n-e git+https://x/y#egg=y\npkg @ file:///tmp/pkg.whl\nnumpy==2.2.6\n"
    assert parse_freeze(text) == {"faker": "40.43.0", "pkg": "@ file:///tmp/pkg.whl", "numpy": "2.2.6"}


def test_parse_freeze_rejects_an_unknown_line():
    with pytest.raises(ValueError, match="unexpected pip freeze line: 'garbage'"):
        parse_freeze("garbage\n")


def test_compare_only_looks_at_packages_installed_in_both():
    shared, differences = compare({"a": "1", "b": "2", "only-left": "9"}, {"a": "1", "b": "3", "only-right": "9"})
    assert shared == ("a", "b")
    assert differences == (VersionDifference("b", "2", "3"),)


def test_equal_environments_pass_and_list_the_shared_packages():
    sink = ListSink()
    service = CheckParityService(FakeInventory({DRIVER.image: "pandas==2.3.3\nPyArrow==25.0.1\njupyterlab==4.6.4\n", WORKER.image: "pyarrow==25.0.1\npandas==2.3.3\nmimesis==22.2.0\n"}), sink)
    report = service(DRIVER, WORKER)
    assert isinstance(service, CheckParityUseCase)
    assert report == ParityReport(DRIVER, WORKER, ("pandas", "pyarrow"), ())
    assert report.equal
    assert sink.parts == [
        "Same versions in spark-jupyter:test (python3) and spark-job-venv:test "
        "(/opt/spark/venv-build/spark_job_env/bin/python3): 2 shared packages (pandas, pyarrow)\n"
    ]


def test_a_drift_stops_with_every_difference():
    sink = ListSink()
    service = CheckParityService(FakeInventory({DRIVER.image: "Faker==40.36.0\nnumpy==2.2.6\npandas==2.3.3\n", WORKER.image: "faker==40.43.0\nnumpy==2.3.0\npandas==2.3.3\n"}), sink)
    with pytest.raises(EnvironmentsDiffer) as caught:
        service(DRIVER, WORKER)
    assert str(caught.value) == (
        "spark-jupyter:test (python3) and spark-job-venv:test (/opt/spark/venv-build/spark_job_env/bin/python3) "
        "differ in 2 shared package(s): faker: 40.36.0 vs 40.43.0; numpy: 2.2.6 vs 2.3.0"
    )
    assert not caught.value.report.equal
    assert sink.parts == []


def test_docker_inventory_runs_pip_freeze_in_the_image_quietly():
    runner, sink = FakeRunner(0, "pandas==2.3.3\n"), ListSink()
    assert DockerImageInventory(runner, sink).freeze(WORKER) == "pandas==2.3.3\n"
    assert runner.calls == [("docker", "run", "--rm", "--entrypoint", WORKER.python, WORKER.image, "-m", "pip", "freeze")]


def test_docker_inventory_failure_raises_command_failed():
    with pytest.raises(CommandFailed) as caught:
        DockerImageInventory(FakeRunner(125, "Unable to find image\n"), DiscardSink()).freeze(DRIVER)
    assert caught.value.result.returncode == 125


def test_discard_sink_and_composition_root():
    assert DiscardSink().write("anything") is None
    assert isinstance(check_python_parity, CheckParityService)
