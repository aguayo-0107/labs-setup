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
    "iceberg-spark-runtime-4.1_2.13-1.12.0.jar": "3123c3798af642dd537230923548e013ef41cc28b6626e5225808cf5670a0f82",
    "delta-spark_2.13-4.3.1.jar": "ebf35a4383f0a653c3ee3c7882c0edcac2f846be31ac61af4b96ccfaaf36c171",
    "delta-storage-4.3.1.jar": "577c12c7e371be4c041714fb48e88ad86e3c3512beea2bdaffbe7a4debf79718",
    "delta-kernel-api-4.3.1.jar": "b081b818d6f5686c7d6406588af72c9f8baf6765a41ada8197364aef90a260e8",
    "delta-kernel-defaults-4.3.1.jar": "27471cca7dd7a36289af2c8d52d2babb37e9e5a13cdaaea76730120f4c72e62f",
    "delta-kernel-unitycatalog-4.3.1.jar": "a288342b7e53da34a608a1a227c8109aa4681fcb582da499ed19347f2193362b",
    "graphframes-spark4_2.13-0.12.3.jar": "a78958f7ea3ac89ed1ea9dbbd1546f403d94151e969bb0de96e33697a5f49f50",
    "graphframes-graphx-spark4_2.13-0.12.3.jar": "385ea9934bdeedff9cd4591df66ada45ce739148f15fe947a032886997626675",
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
