"""Use case: queue a query, run it on the engine, keep its record and result file."""

from __future__ import annotations

from ..domain.errors import InvalidRequestError, QueryFailedError
from ..domain.models import QueryExecution, QueryState, ResultPage, StartQueryRequest
from ..domain.policy import classify_statement, page, render_result_file, result_file
from ..ports.inbound import AthenaQueryApiPort
from ..ports.outbound import (
    ClockPort,
    ExecutionRepositoryPort,
    IdGeneratorPort,
    ResultStorePort,
    SqlEnginePort,
    TaskRunnerPort,
)


class AthenaQueryService(AthenaQueryApiPort):
    def __init__(
        self,
        engine: SqlEnginePort,
        store: ResultStorePort,
        repository: ExecutionRepositoryPort,
        runner: TaskRunnerPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._engine = engine
        self._store = store
        self._repository = repository
        self._runner = runner
        self._clock = clock
        self._ids = ids

    def start_query_execution(self, request: StartQueryRequest) -> str:
        execution = QueryExecution(
            query_id=self._ids.new_id(),
            query=request.query,
            statement_type=classify_statement(request.query),
            database=request.database,
            output_location=request.output_location,
            state=QueryState.QUEUED,
            submitted_at=self._clock.now(),
        )
        self._repository.put(execution)
        self._runner.submit(lambda: self._run(execution.query_id))
        return execution.query_id

    def _run(self, query_id: str) -> None:
        execution = self._require(query_id).running()
        self._repository.put(execution)
        try:
            result = self._engine.execute(execution.query, execution.database)
            location = result_file(execution.output_location, query_id, execution.statement_type)
            self._store.save(location, render_result_file(result, execution.statement_type))
        except QueryFailedError as error:
            self._repository.put(execution.failed(str(error), self._clock.now()))
            return
        except Exception as error:  # e.g. the result store is unreachable
            self._repository.put(execution.failed(f"{type(error).__name__}: {error}", self._clock.now()))
            return
        self._repository.put(execution.succeeded(result, location, self._clock.now()))

    def _require(self, query_id: str) -> QueryExecution:
        execution = self._repository.get(query_id)
        if execution is None:
            raise InvalidRequestError(f"QueryExecution {query_id} was not found")
        return execution

    def get_query_execution(self, query_id: str) -> QueryExecution:
        return self._require(query_id)

    def get_query_results(self, query_id: str, max_results: int | None, next_token: str | None) -> ResultPage:
        execution = self._require(query_id)
        if execution.state is not QueryState.SUCCEEDED:
            raise InvalidRequestError(f"Query has not succeeded. Current state: {execution.state.value}")
        return page(execution.result, execution.statement_type, max_results, next_token)
