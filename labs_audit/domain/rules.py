"""Pure audit rules. Each rule returns the findings it detects; none means pass.

The rules encode the contracts in AGENTS.md: one papermill parameters cell
with the documented defaults, the dedicated kernel, no committed outputs,
`.ipynb` derived from the canonical `.py`, Spark's four checksum-pinned JARs,
and two Linux portability defects found on 2026-10-08 (an ignored
`compose up --wait` failure and Windows-only path separators).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .models import Finding, Notebook

KERNEL = "non-relational-dbs-labs"

PARAMETER_DEFAULTS = (
    'NETWORK_MODE = "local"',
    'VPN_HOST_IP = "10.15.20.100"',
    'VPN_DNS_IP = "10.15.20.1"',
    'VPN_DOMAIN = "vpn.itam.mx"',
    'VPN_CLIENT_ALIAS = "mavasbel"',
)
INFRA_PARAMETER_DEFAULTS = ("START_FROM_SCRATCH = False",)

SPARK_JARS: Mapping[str, str] = {
    "iceberg-spark-runtime-3.5_2.12-1.6.1.jar": "87e7184f31ef0caac415bbdfcf1bc4943346a58b98d747dc83434f7139e12acb",
    "delta-spark_2.12-3.2.0.jar": "51d473537d1bc10c81f48b03d8e2a6b604e1b421a70835ec12e917a4245a31d5",
    "delta-storage-3.2.0.jar": "58aab63eba7736fea9e03eafb0dde6704a34a70f570c1a69ab8e4012c25a95d4",
    "antlr4-runtime-4.9.3.jar": "131a6594969bc4f321d652ea2a33bc0e378ca312685ef87791b2c60b29d01ea5",
}

_COMPOSE_WAIT = re.compile(r"^!docker compose -f \S+ up -d --wait\s*$", re.M)
_EXIT_CHECK = "assert _exit_code == 0"
_WINDOWS_PATH = re.compile(r"""["']\.\\\\|\\\\mount\\\\""")


def parameters_cell(nb: Notebook) -> list[Finding]:
    cells = [cell for cell in nb.cells if "parameters" in cell.tags]
    if len(cells) != 1:
        return [Finding("parameters", nb.path, f"expected 1 parameters cell, found {len(cells)}")]
    expected = PARAMETER_DEFAULTS + (INFRA_PARAMETER_DEFAULTS if nb.is_infra else ())
    lines = {line.strip() for line in cells[0].source.splitlines()}
    return [
        Finding("parameters", nb.path, f"missing default {value!r}")
        for value in expected
        if value not in lines
    ]


def kernel(nb: Notebook) -> list[Finding]:
    if nb.kernel == KERNEL:
        return []
    return [Finding("kernel", nb.path, f"kernelspec {nb.kernel!r}, expected {KERNEL!r}")]


def no_outputs(nb: Notebook) -> list[Finding]:
    return [
        Finding("outputs", nb.path, f"cell {index} has saved outputs or an execution count")
        for index, cell in enumerate(nb.cells)
        if cell.cell_type == "code" and (cell.outputs or cell.execution_count is not None)
    ]


def _shape(nb: Notebook) -> list[tuple[str, str]]:
    return [(cell.cell_type, cell.source.rstrip()) for cell in nb.cells]


def in_sync(committed: Notebook, canonical: Notebook) -> list[Finding]:
    if _shape(committed) == _shape(canonical):
        return []
    return [Finding("sync", committed.path, "differs from its canonical .py source")]


def compose_wait_checked(nb: Notebook) -> list[Finding]:
    findings: list[Finding] = []
    for index, cell in enumerate(nb.cells):
        match = _COMPOSE_WAIT.search(cell.source) if cell.cell_type == "code" else None
        if match and _EXIT_CHECK not in cell.source[match.end():]:
            findings.append(
                Finding("compose-wait", nb.path, f"cell {index} ignores the exit status of compose --wait")
            )
    return findings


def no_windows_paths(nb: Notebook) -> list[Finding]:
    return [
        Finding("portability", nb.path, f"cell {index} uses a Windows-only path separator")
        for index, cell in enumerate(nb.cells)
        if cell.cell_type == "code" and _WINDOWS_PATH.search(cell.source)
    ]


def jar_checksums(actual: Mapping[str, str | None]) -> list[Finding]:
    findings: list[Finding] = []
    for name, expected in SPARK_JARS.items():
        digest = actual.get(name)
        if digest is None:
            findings.append(Finding("spark-jars", f"spark/jars/{name}", "missing"))
        elif digest != expected:
            findings.append(Finding("spark-jars", f"spark/jars/{name}", f"sha256 {digest} != {expected}"))
    return findings


NOTEBOOK_RULES = (parameters_cell, kernel, no_outputs, compose_wait_checked, no_windows_paths)
