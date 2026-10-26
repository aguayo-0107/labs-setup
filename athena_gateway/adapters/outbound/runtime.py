"""Process-local runtime: execution records, a single worker, time and ids."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ...domain.models import QueryExecution
from ...ports.outbound import ClockPort, ExecutionRepositoryPort, IdGeneratorPort, TaskRunnerPort


class InMemoryExecutionRepository(ExecutionRepositoryPort):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, QueryExecution] = {}

    def put(self, execution: QueryExecution) -> None:
        with self._lock:
            self._records[execution.query_id] = execution

    def get(self, query_id: str) -> QueryExecution | None:
        with self._lock:
            return self._records.get(query_id)


class SingleWorkerTaskRunner(TaskRunnerPort):
    """One worker thread: queries run one at a time, in the order they arrive."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="athena-query")

    def submit(self, task: Callable[[], None]) -> None:
        self._executor.submit(task)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


class SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Uuid4Generator(IdGeneratorPort):
    def new_id(self) -> str:
        return str(uuid.uuid4())
