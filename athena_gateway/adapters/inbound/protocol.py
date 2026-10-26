"""Wire protocols that drive the Athena use case."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ...domain.errors import AthenaError, InvalidRequestError, UnknownOperationError
from ...domain.models import QueryExecution, ResultPage
from ...domain.policy import column_info, result_file, validate_start_request
from ...ports.inbound import AthenaQueryApiPort


class ProtocolAdapter(ABC):
    """Maps one request (operation name + raw body) to a status and a JSON document."""

    @abstractmethod
    def handle(self, target: str | None, body: bytes) -> tuple[int, dict[str, Any]]:
        """Never raises: errors become an error document with their status."""


class AwsJson11Protocol(ProtocolAdapter):
    """`X-Amz-Target: AmazonAthena.<Operation>` with a JSON body, as boto3 sends it."""

    PREFIX = "AmazonAthena."

    def __init__(self, api: AthenaQueryApiPort) -> None:
        self._api = api
        self._operations = {
            "StartQueryExecution": self._start,
            "GetQueryExecution": self._execution,
            "GetQueryResults": self._results,
        }

    def handle(self, target: str | None, body: bytes) -> tuple[int, dict[str, Any]]:
        try:
            operation = (target or "").removeprefix(self.PREFIX)
            if not (target or "").startswith(self.PREFIX) or operation not in self._operations:
                raise UnknownOperationError(f"Operation {target!r} is not supported by this gateway")
            try:
                payload = json.loads(body or b"{}")
            except ValueError as error:
                raise InvalidRequestError(f"Request body is not valid JSON: {error}") from error
            if not isinstance(payload, dict):
                raise InvalidRequestError("Request body must be a JSON object")
            return 200, self._operations[operation](payload)
        except AthenaError as error:
            return error.status, {"__type": error.code, "Message": error.message}
        except Exception as error:  # a defect must still reach the client as an error document
            return 500, {"__type": "InternalServerException", "Message": f"{type(error).__name__}: {error}"}

    @staticmethod
    def _query_id(payload: dict[str, Any]) -> str:
        query_id = payload.get("QueryExecutionId")
        if not isinstance(query_id, str) or not query_id:
            raise InvalidRequestError("QueryExecutionId is required")
        return query_id

    def _start(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"QueryExecutionId": self._api.start_query_execution(validate_start_request(payload))}

    def _execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"QueryExecution": self.render_execution(self._api.get_query_execution(self._query_id(payload)))}

    def _results(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._api.get_query_results(
            self._query_id(payload), payload.get("MaxResults"), payload.get("NextToken")
        )
        return self.render_page(result)

    @staticmethod
    def render_execution(execution: QueryExecution) -> dict[str, Any]:
        status: dict[str, Any] = {
            "State": execution.state.value,
            "SubmissionDateTime": execution.submitted_at.timestamp(),
        }
        if execution.completed_at is not None:
            status["CompletionDateTime"] = execution.completed_at.timestamp()
        if execution.reason is not None:
            status["StateChangeReason"] = execution.reason
        location = result_file(execution.output_location, execution.query_id, execution.statement_type)
        return {
            "QueryExecutionId": execution.query_id,
            "Query": execution.query,
            "StatementType": execution.statement_type.value,
            "ResultConfiguration": {"OutputLocation": location.uri},
            "QueryExecutionContext": {"Database": execution.database},
            "Status": status,
            "WorkGroup": "primary",
        }

    @staticmethod
    def render_page(result: ResultPage) -> dict[str, Any]:
        document: dict[str, Any] = {
            "UpdateCount": 0,
            "ResultSet": {
                "Rows": [
                    {"Data": [{} if value is None else {"VarCharValue": value} for value in row]}
                    for row in result.rows
                ],
                "ResultSetMetadata": {"ColumnInfo": column_info(result.columns)},
            },
        }
        if result.next_token is not None:
            document["NextToken"] = result.next_token
        return document
