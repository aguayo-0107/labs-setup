"""Pure rules: request validation, statement classification, rendering, paging.

Limits come from the Athena API reference: QueryString is 1 to 262144
characters and GetQueryResults accepts MaxResults from 1 to 1000. Only the
first page of a DML (SELECT) result carries the column names as its first row,
which is what clients such as the AWS lab's `Rows[1]` rely on.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .errors import InvalidRequestError
from .models import (
    Column,
    QueryResult,
    ResultPage,
    S3Location,
    StartQueryRequest,
    StatementType,
)

MAX_QUERY_LENGTH = 262144
MAX_RESULTS = 1000
DEFAULT_DATABASE = "default"

_DDL = {"CREATE", "DROP", "ALTER", "MSCK"}
_UTILITY = {"SHOW", "DESCRIBE", "DESC", "EXPLAIN", "USE"}
_LEADING_COMMENTS = re.compile(r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*", re.S)
_S3_URI = re.compile(r"\As3://([a-z0-9][a-z0-9.\-]{1,61}[a-z0-9])/?(.*)\Z")

# HiveServer2 column types (as reported by its driver) -> Athena type names.
_TYPES = {
    "BOOLEAN": "boolean",
    "TINYINT": "tinyint",
    "SMALLINT": "smallint",
    "INT": "integer",
    "BIGINT": "bigint",
    "FLOAT": "float",
    "DOUBLE": "double",
    "DECIMAL": "decimal",
    "STRING": "varchar",
    "VARCHAR": "varchar",
    "CHAR": "char",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
    "BINARY": "varbinary",
    "ARRAY": "array",
    "MAP": "map",
    "STRUCT": "row",
}


def _text(body: Mapping[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        raise InvalidRequestError(f"{name} must be a string")
    return value


def parse_s3_uri(uri: str) -> S3Location:
    match = _S3_URI.match(uri)
    if match is None:
        raise InvalidRequestError(f"{uri!r} is not a valid s3://bucket/prefix location")
    return S3Location(match.group(1), match.group(2))


def validate_start_request(body: Mapping[str, Any]) -> StartQueryRequest:
    query = _text(body, "QueryString")
    if not query or not query.strip():
        raise InvalidRequestError("QueryString is required")
    if len(query) > MAX_QUERY_LENGTH:
        raise InvalidRequestError(f"QueryString exceeds {MAX_QUERY_LENGTH} characters")
    output = _text(body.get("ResultConfiguration") or {}, "OutputLocation")
    if not output:
        raise InvalidRequestError(
            "ResultConfiguration.OutputLocation is required: this gateway has no workgroup "
            "with a default result location"
        )
    parse_s3_uri(output)
    database = _text(body.get("QueryExecutionContext") or {}, "Database") or DEFAULT_DATABASE
    return StartQueryRequest(query=query, output_location=output, database=database)


def classify_statement(query: str) -> StatementType:
    body = query[_LEADING_COMMENTS.match(query).end():]
    keyword = body.split(None, 1)[0].upper() if body.strip() else ""
    if keyword in _DDL:
        return StatementType.DDL
    if keyword in _UTILITY:
        return StatementType.UTILITY
    return StatementType.DML


def athena_type(engine_type: str) -> str:
    base = engine_type.upper().removesuffix("_TYPE").split("(", 1)[0]
    return _TYPES.get(base, "varchar")


def render_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def result_file(output_location: str, query_id: str, statement_type: StatementType) -> S3Location:
    base = parse_s3_uri(output_location)
    prefix = base.key if not base.key or base.key.endswith("/") else f"{base.key}/"
    suffix = "csv" if statement_type is StatementType.DML else "txt"
    return S3Location(base.bucket, f"{prefix}{query_id}.{suffix}")


def render_result_file(result: QueryResult, statement_type: StatementType) -> bytes:
    if statement_type is not StatementType.DML:
        lines = ["\t".join(value or "" for value in row) for row in result.rows]
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow([column.name for column in result.columns])
    writer.writerows([["" if value is None else value for value in row] for row in result.rows])
    return buffer.getvalue().encode("utf-8")


def _offset(next_token: str | None) -> int:
    if next_token is None:
        return 0
    if not next_token.isdigit():
        raise InvalidRequestError("NextToken is not valid")
    return int(next_token)


def page(
    result: QueryResult, statement_type: StatementType, max_results: int | None, next_token: str | None
) -> ResultPage:
    size = MAX_RESULTS if max_results is None else max_results
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_RESULTS:
        raise InvalidRequestError(f"MaxResults must be between 1 and {MAX_RESULTS}")
    header: tuple[tuple[str | None, ...], ...] = ()
    if statement_type is StatementType.DML:
        header = (tuple(column.name for column in result.columns),)
    rows = header + result.rows
    start = _offset(next_token)
    if start > len(rows):
        raise InvalidRequestError("NextToken is not valid")
    end = start + size
    return ResultPage(
        columns=result.columns,
        rows=rows[start:end],
        next_token=str(end) if end < len(rows) else None,
    )


def column_info(columns: tuple[Column, ...]) -> list[dict[str, Any]]:
    return [
        {"CatalogName": "hive", "SchemaName": "", "TableName": "", "Name": c.name, "Label": c.name,
         "Type": c.type, "Nullable": "UNKNOWN", "CaseSensitive": c.type in ("varchar", "char")}
        for c in columns
    ]
