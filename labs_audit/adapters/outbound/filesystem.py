"""Filesystem adapters: notebooks through nbformat/jupytext, JARs through hashlib."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import jupytext
import nbformat

from ...domain.models import Cell, Notebook
from ...domain.rules import SPARK_JARS
from ...ports.outbound import JarStorePort, NotebookSourcePort

MODULES = ("cassandra", "hadoop", "mongodb", "neo4j", "opensearch", "redis", "spark")


def _notebook(path: str, node: nbformat.NotebookNode) -> Notebook:
    cells = tuple(
        Cell(
            cell_type=cell.cell_type,
            source=cell.source,
            tags=tuple(cell.metadata.get("tags", [])),
            outputs=len(cell.get("outputs", [])),
            execution_count=cell.get("execution_count"),
        )
        for cell in node.cells
    )
    return Notebook(path, cells, node.metadata.get("kernelspec", {}).get("name"))


class FileNotebookSource(NotebookSourcePort):
    def __init__(self, root: Path) -> None:
        self._root = root

    def pairs(self) -> tuple[str, ...]:
        stems = []
        for module in MODULES:
            for script in sorted((self._root / module).glob("*.py")):
                if script.with_suffix(".ipynb").is_file():
                    stems.append(f"{module}/{script.stem}")
        return tuple(stems)

    def committed(self, stem: str) -> Notebook:
        path = self._root / f"{stem}.ipynb"
        return _notebook(f"{stem}.ipynb", nbformat.read(path, as_version=4))

    def canonical(self, stem: str) -> Notebook:
        return _notebook(f"{stem}.py", jupytext.read(self._root / f"{stem}.py"))


class FileJarStore(JarStorePort):
    def __init__(self, root: Path) -> None:
        self._jars = root / "spark" / "jars"

    def digests(self) -> Mapping[str, str | None]:
        result: dict[str, str | None] = {}
        for name in SPARK_JARS:
            path = self._jars / name
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return result
