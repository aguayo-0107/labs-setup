"""Pure audit rules. Each rule returns the findings it detects; none means pass.

The rules encode the contracts in AGENTS.md: one papermill parameters cell
with the documented defaults, the dedicated kernel, no committed outputs,
`.ipynb` derived from the canonical `.py`, Spark's six checksum-pinned JARs,
and operating-system portability: no Windows-only path separators, no IPython
shell escapes (a `!` line runs in `cmd.exe` on Windows and `/bin/sh`
elsewhere, so quoting, globs and pipes differ), and text I/O that produces the
same bytes on every system (explicit encoding, explicit newline on writes,
explicit encoding when subprocess output is decoded, never `shell=True`).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator, Mapping

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
    "graphframes-spark3_2.12-0.12.3.jar": "69d7909628caf42bcbe1c7e6e5a5a0901040d00583738d931af41bd72af1d3dc",
    "graphframes-graphx-spark3_2.12-0.12.3.jar": "8bbd2bbb4c7a3b137e51b4f32f49a30a2ccf70eeb07b452cffa20090dd481b96",
}

_SHELL_ESCAPE = re.compile(r"^\s*(!|%%(bash|sh|script|system)\b|%(sx|system)\b)", re.M)
_SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}
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


def no_shell_escapes(nb: Notebook) -> list[Finding]:
    return [
        Finding("shell-escape", nb.path, f"cell {index} runs a command through the OS shell; use run_command([...])")
        for index, cell in enumerate(nb.cells)
        if cell.cell_type == "code" and _SHELL_ESCAPE.search(cell.source)
    ]


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {item.arg: item.value for item in call.keywords if item.arg is not None}


def _constant(node: ast.expr | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _io_problems(call: ast.Call) -> Iterator[str]:
    function = call.func
    name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
    keywords = _keywords(call)
    if isinstance(function, ast.Name) and name == "open":
        mode = _constant(call.args[1] if len(call.args) > 1 else keywords.get("mode")) or "r"
        if isinstance(mode, str) and "b" not in mode:
            if "encoding" not in keywords:
                yield "open() without encoding="
            if set(mode) & set("wax+") and "newline" not in keywords:
                yield "open() for writing without newline="
    elif isinstance(function, ast.Attribute) and name == "write_text":
        for required in ("encoding", "newline"):
            if required not in keywords:
                yield f"write_text() without {required}="
    elif isinstance(function, ast.Attribute) and name == "read_text" and "encoding" not in keywords:
        yield "read_text() without encoding="
    elif (
        isinstance(function, ast.Attribute)
        and name in _SUBPROCESS_CALLS
        and getattr(function.value, "id", None) == "subprocess"
    ):
        if _constant(keywords.get("shell")) is True:
            yield f"subprocess.{name}() with shell=True"
        decodes = any(_constant(keywords.get(key)) is True for key in ("text", "universal_newlines"))
        if decodes and "encoding" not in keywords:
            yield f"subprocess.{name}() decodes output without encoding="


def portable_io(nb: Notebook) -> list[Finding]:
    findings: list[Finding] = []
    for index, cell in enumerate(nb.cells):
        if cell.cell_type != "code" or cell.source.lstrip().startswith("%%"):
            continue
        source = "\n".join("" if line.lstrip().startswith("%") else line for line in cell.source.splitlines())
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            findings.append(Finding("portable-io", nb.path, f"cell {index} is not valid Python: {error.msg}"))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                findings.extend(
                    Finding("portable-io", nb.path, f"cell {index} line {node.lineno}: {problem}")
                    for problem in _io_problems(node)
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


NOTEBOOK_RULES = (parameters_cell, kernel, no_outputs, no_shell_escapes, no_windows_paths, portable_io)
