"""Pure rules of the Athena gateway: validation, classification, rendering, paging."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from athena_gateway.domain.errors import AthenaError, InvalidRequestError, UnknownOperationError
from athena_gateway.domain.models import (
    Column,
    QueryExecution,
    QueryResult,
    QueryState,
    S3Location,
    StatementType,
)
from athena_gateway.domain import policy

pytestmark = pytest.mark.unit

OUT = "s3://lab-aws-x-datalake/athena-results/"


def start(**overrides):
    body = {"QueryString": "SELECT 1", "ResultConfiguration": {"OutputLocation": OUT}}
    body.update(overrides)
    return body


# --- request validation --------------------------------------------------------

def test_valid_request_defaults_to_the_default_database():
    request = policy.validate_start_request(start())
    assert (request.query, request.output_location, request.database) == ("SELECT 1", OUT, "default")


def test_database_from_the_execution_context():
    request = policy.validate_start_request(start(QueryExecutionContext={"Database": "ventas_db"}))
    assert request.database == "ventas_db"


@pytest.mark.parametrize("query", [None, "", "   "])
def test_query_string_is_required(query):
    with pytest.raises(InvalidRequestError, match="QueryString is required"):
        policy.validate_start_request(start(QueryString=query))


def test_query_string_length_limit_is_inclusive():
    policy.validate_start_request(start(QueryString="x" * policy.MAX_QUERY_LENGTH))
    with pytest.raises(InvalidRequestError, match="exceeds 262144"):
        policy.validate_start_request(start(QueryString="x" * (policy.MAX_QUERY_LENGTH + 1)))


def test_non_string_fields_are_rejected():
    with pytest.raises(InvalidRequestError, match="QueryString must be a string"):
        policy.validate_start_request(start(QueryString=7))


@pytest.mark.parametrize("config", [None, {}, {"OutputLocation": ""}])
def test_output_location_is_required(config):
    body = start()
    body["ResultConfiguration"] = config
    with pytest.raises(InvalidRequestError, match="OutputLocation is required"):
        policy.validate_start_request(body)


@pytest.mark.parametrize("uri", ["/tmp/x", "s3:/bucket", "s3://B/upper", "s3://a/x", "https://bucket/x"])
def test_output_location_must_be_an_s3_uri(uri):
    with pytest.raises(InvalidRequestError, match="not a valid s3://bucket/prefix"):
        policy.validate_start_request(start(ResultConfiguration={"OutputLocation": uri}))


def test_parse_s3_uri_with_and_without_prefix():
    assert policy.parse_s3_uri("s3://my-bucket/a/b/") == S3Location("my-bucket", "a/b/")
    assert policy.parse_s3_uri("s3://my-bucket") == S3Location("my-bucket", "")
    assert S3Location("b", "k/x.csv").uri == "s3://b/k/x.csv"


# --- statement classification --------------------------------------------------

@pytest.mark.parametrize(
    "query, kind",
    [
        ("CREATE DATABASE IF NOT EXISTS d", StatementType.DDL),
        ("\n  create external table t (a string)", StatementType.DDL),
        ("DROP DATABASE d CASCADE", StatementType.DDL),
        ("ALTER TABLE t ADD COLUMNS (b int)", StatementType.DDL),
        ("MSCK REPAIR TABLE t", StatementType.DDL),
        ("SELECT SUM(monto) FROM t", StatementType.DML),
        ("WITH x AS (SELECT 1) SELECT * FROM x", StatementType.DML),
        ("INSERT INTO t VALUES (1)", StatementType.DML),
        ("SHOW TABLES", StatementType.UTILITY),
        ("DESCRIBE t", StatementType.UTILITY),
        ("EXPLAIN SELECT 1", StatementType.UTILITY),
        ("-- comentario\nSELECT 1", StatementType.DML),
        ("/* bloque\n */ DROP TABLE t", StatementType.DDL),
        ("-- solo un comentario", StatementType.DML),
    ],
)
def test_classify_statement(query, kind):
    assert policy.classify_statement(query) is kind


# --- types and values ----------------------------------------------------------

@pytest.mark.parametrize(
    "engine, athena",
    [
        ("DOUBLE_TYPE", "double"), ("BIGINT_TYPE", "bigint"), ("STRING_TYPE", "varchar"),
        ("INT_TYPE", "integer"), ("BOOLEAN_TYPE", "boolean"), ("decimal(10,2)", "decimal"),
        ("STRUCT_TYPE", "row"), ("BINARY_TYPE", "varbinary"), ("INTERVAL_DAY_TIME_TYPE", "varchar"),
    ],
)
def test_athena_type(engine, athena):
    assert policy.athena_type(engine) == athena


@pytest.mark.parametrize(
    "value, rendered",
    [
        (None, None), (True, "true"), (False, "false"), (b"\x01\xff", "01ff"),
        (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02 03:04:05"), (date(2026, 1, 2), "2026-01-02"),
        (Decimal("1E+2"), "100"), (24951090.849999912, "24951090.849999912"), (10000, "10000"), ("txt", "txt"),
    ],
)
def test_render_value(value, rendered):
    assert policy.render_value(value) == rendered


# --- result files --------------------------------------------------------------

@pytest.mark.parametrize(
    "location, kind, expected",
    [
        (OUT, StatementType.DML, S3Location("lab-aws-x-datalake", "athena-results/q1.csv")),
        ("s3://lab-aws-x-datalake/athena-results", StatementType.DDL, S3Location("lab-aws-x-datalake", "athena-results/q1.txt")),
        ("s3://lab-aws-x-datalake", StatementType.UTILITY, S3Location("lab-aws-x-datalake", "q1.txt")),
    ],
)
def test_result_file_naming(location, kind, expected):
    assert policy.result_file(location, "q1", kind) == expected


RESULT = QueryResult(
    columns=(Column("ingresos_totales", "double"), Column("tx_totales", "bigint")),
    rows=(("24951090.85", "10000"), (None, "1")),
)


def test_dml_result_file_is_csv_with_header():
    assert policy.render_result_file(RESULT, StatementType.DML) == (
        b'"ingresos_totales","tx_totales"\n"24951090.85","10000"\n"","1"\n'
    )


def test_ddl_result_file_is_plain_text():
    shown = QueryResult(columns=(Column("tab_name", "varchar"),), rows=(("a",), (None,)))
    assert policy.render_result_file(shown, StatementType.UTILITY) == b"a\n\n"
    assert policy.render_result_file(QueryResult((), ()), StatementType.DDL) == b""


# --- paging --------------------------------------------------------------------

def test_dml_first_page_starts_with_the_column_names():
    page = policy.page(RESULT, StatementType.DML, None, None)
    assert page.rows == (("ingresos_totales", "tx_totales"), ("24951090.85", "10000"), (None, "1"))
    assert page.next_token is None and page.columns == RESULT.columns


def test_utility_results_carry_no_header_row():
    assert policy.page(RESULT, StatementType.UTILITY, None, None).rows == RESULT.rows


def test_pages_follow_next_token_to_the_end():
    first = policy.page(RESULT, StatementType.DML, 2, None)
    second = policy.page(RESULT, StatementType.DML, 2, first.next_token)
    assert (first.rows[0][0], first.next_token) == ("ingresos_totales", "2")
    assert (second.rows, second.next_token) == (((None, "1"),), None)


@pytest.mark.parametrize("size", [0, 1001, True, "5"])
def test_max_results_range(size):
    with pytest.raises(InvalidRequestError, match="between 1 and 1000"):
        policy.page(RESULT, StatementType.DML, size, None)


@pytest.mark.parametrize("token", ["abc", "-1", "99"])
def test_invalid_next_token(token):
    with pytest.raises(InvalidRequestError, match="NextToken is not valid"):
        policy.page(RESULT, StatementType.DML, None, token)


def test_column_info_shape():
    info = policy.column_info(RESULT.columns + (Column("nombre", "varchar"),))
    assert info[0] == {
        "CatalogName": "hive", "SchemaName": "", "TableName": "", "Name": "ingresos_totales",
        "Label": "ingresos_totales", "Type": "double", "Nullable": "UNKNOWN", "CaseSensitive": False,
    }
    assert info[2]["CaseSensitive"] is True


# --- models and errors ---------------------------------------------------------

def test_execution_transitions_keep_identity():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    queued = QueryExecution("q", "SELECT 1", StatementType.DML, "default", OUT, QueryState.QUEUED, t0)
    running = queued.running()
    done = running.succeeded(RESULT, S3Location("b", "k"), t0)
    failed = running.failed("boom", t0)
    assert (queued.state, running.state, done.state, failed.state) == (
        QueryState.QUEUED, QueryState.RUNNING, QueryState.SUCCEEDED, QueryState.FAILED)
    assert done.result is RESULT and failed.reason == "boom" and running.query_id == "q"
    assert [s.finished for s in QueryState] == [False, False, True, True]


def test_error_codes_and_statuses():
    assert (AthenaError("x").code, AthenaError("x").status) == ("InternalServerException", 500)
    assert (InvalidRequestError("m").code, InvalidRequestError("m").status, InvalidRequestError("m").message) == (
        "InvalidRequestException", 400, "m")
    assert UnknownOperationError("m").code == "UnknownOperationException"
