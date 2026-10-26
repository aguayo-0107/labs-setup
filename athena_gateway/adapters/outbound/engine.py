"""SQL engines: any DB-API 2 connection, specialised for HiveServer2."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from ...domain.errors import QueryFailedError
from ...domain.models import Column, QueryResult
from ...domain.policy import athena_type, render_value
from ...ports.outbound import SqlEnginePort


class DbApiSqlEngine(SqlEnginePort):
    """Runs one statement per connection and renders the rows Athena-style."""

    @abstractmethod
    def connect(self, database: str) -> Any:
        """A DB-API 2 connection whose current database is `database`."""

    def execute(self, query: str, database: str) -> QueryResult:
        connection = self.connect(database)
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(query)
                description = tuple(cursor.description or ())
                rows = cursor.fetchall() if description else []
            finally:
                cursor.close()
        finally:
            connection.close()
        return QueryResult(
            columns=tuple(Column(str(item[0]), athena_type(str(item[1]))) for item in description),
            rows=tuple(tuple(render_value(value) for value in row) for row in rows),
        )


class HiveServer2SqlEngine(DbApiSqlEngine):
    """HiveServer2 through PyHive; plain column names, as Athena returns them."""

    SESSION = {"hive.resultset.use.unique.column.names": "false"}

    def __init__(self, host: str, port: int, username: str, connect: Callable[..., Any]) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._connect = connect

    def execute(self, query: str, database: str) -> QueryResult:
        try:
            return super().execute(query, database)
        except Exception as error:
            raise QueryFailedError(self.failure_message(error)) from error

    @staticmethod
    def failure_message(error: Exception) -> str:
        """HiveServer2's own errorMessage when the driver carries one, else the exception text."""
        response = error.args[0] if error.args else None
        message = getattr(getattr(response, "status", None), "errorMessage", None)
        return message if isinstance(message, str) and message else f"{type(error).__name__}: {error}"

    def connect(self, database: str) -> Any:
        return self._connect(
            host=self._host,
            port=self._port,
            username=self._username,
            database=database,
            configuration=dict(self.SESSION),
        )
