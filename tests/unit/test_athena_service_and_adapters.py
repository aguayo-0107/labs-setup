"""Use case and adapters of the Athena gateway, each against an in-process double."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from athena_gateway.adapters.inbound.protocol import AwsJson11Protocol, ProtocolAdapter
from athena_gateway.adapters.outbound.engine import DbApiSqlEngine, HiveServer2SqlEngine
from athena_gateway.adapters.outbound.runtime import (
    InMemoryExecutionRepository,
    SingleWorkerTaskRunner,
    SystemClock,
    Uuid4Generator,
)
from athena_gateway.adapters.outbound.storage import S3ResultStore
from athena_gateway.application.service import AthenaQueryService
from athena_gateway.domain.errors import InvalidRequestError, QueryFailedError
from athena_gateway.domain.models import (
    Column,
    QueryResult,
    QueryState,
    S3Location,
    StartQueryRequest,
    StatementType,
)
from athena_gateway.ports.inbound import AthenaQueryApiPort
from athena_gateway.ports.outbound import (
    ClockPort,
    IdGeneratorPort,
    ResultStorePort,
    SqlEnginePort,
    TaskRunnerPort,
)

pytestmark = pytest.mark.unit

OUT = "s3://lab-aws-x-datalake/athena-results/"
T0 = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)


class FakeEngine(SqlEnginePort):
    def __init__(self, result=None, error=None):
        self.result = result or QueryResult((Column("n", "bigint"),), (("3",),))
        self.error = error
        self.calls = []

    def execute(self, query, database):
        self.calls.append((query, database))
        if self.error is not None:
            raise self.error
        return self.result


class FakeStore(ResultStorePort):
    def __init__(self, error=None):
        self.saved = {}
        self.error = error

    def save(self, location, content):
        if self.error is not None:
            raise self.error
        self.saved[location.uri] = content


class DeferredRunner(TaskRunnerPort):
    def __init__(self):
        self.tasks = []

    def submit(self, task):
        self.tasks.append(task)

    def drain(self):
        while self.tasks:
            self.tasks.pop(0)()


class StepClock(ClockPort):
    def __init__(self):
        self.ticks = 0

    def now(self):
        self.ticks += 1
        return T0 + timedelta(seconds=self.ticks)


class CountingIds(IdGeneratorPort):
    def __init__(self):
        self.n = 0

    def new_id(self):
        self.n += 1
        return f"q{self.n}"


def service(engine=None, store=None):
    runner = DeferredRunner()
    svc = AthenaQueryService(
        engine=engine or FakeEngine(), store=store or FakeStore(), repository=InMemoryExecutionRepository(),
        runner=runner, clock=StepClock(), ids=CountingIds(),
    )
    return svc, runner


# --- use case ------------------------------------------------------------------

def test_query_is_queued_then_runs_and_succeeds():
    engine, store = FakeEngine(), FakeStore()
    svc, runner = service(engine, store)
    query_id = svc.start_query_execution(StartQueryRequest("SELECT count(*) AS n FROM t", OUT, "ventas_db"))
    assert query_id == "q1" and svc.get_query_execution("q1").state is QueryState.QUEUED
    with pytest.raises(InvalidRequestError, match="Current state: QUEUED"):
        svc.get_query_results("q1", None, None)
    runner.drain()
    done = svc.get_query_execution("q1")
    assert done.state is QueryState.SUCCEEDED and done.completed_at > done.submitted_at
    assert engine.calls == [("SELECT count(*) AS n FROM t", "ventas_db")]
    assert done.result_file == S3Location("lab-aws-x-datalake", "athena-results/q1.csv")
    assert store.saved == {f"{OUT}q1.csv": b'"n"\n"3"\n'}
    assert svc.get_query_results("q1", None, None).rows == (("n",), ("3",))


def test_ddl_writes_a_txt_file_and_returns_no_rows():
    store = FakeStore()
    svc, runner = service(FakeEngine(QueryResult((), ())), store)
    svc.start_query_execution(StartQueryRequest("CREATE DATABASE d", OUT, "default"))
    runner.drain()
    assert store.saved == {f"{OUT}q1.txt": b""}
    assert svc.get_query_results("q1", None, None).rows == ()


def test_engine_failure_keeps_the_engine_message_as_reason():
    svc, runner = service(FakeEngine(error=QueryFailedError("FAILED: ParseException line 1:104")))
    svc.start_query_execution(StartQueryRequest("CREATE TABLE t (a int);", OUT, "default"))
    runner.drain()
    failed = svc.get_query_execution("q1")
    assert (failed.state, failed.reason) == (QueryState.FAILED, "FAILED: ParseException line 1:104")
    with pytest.raises(InvalidRequestError, match="Current state: FAILED"):
        svc.get_query_results("q1", None, None)


def test_store_failure_fails_the_query_with_its_type():
    svc, runner = service(store=FakeStore(error=ConnectionError("S3 down")))
    svc.start_query_execution(StartQueryRequest("SELECT 1", OUT, "default"))
    runner.drain()
    assert svc.get_query_execution("q1").reason == "ConnectionError: S3 down"


def test_unknown_query_id():
    svc, _ = service()
    with pytest.raises(InvalidRequestError, match="QueryExecution nope was not found"):
        svc.get_query_execution("nope")


def test_service_implements_the_inbound_port():
    assert isinstance(service()[0], AthenaQueryApiPort)


# --- outbound adapters ---------------------------------------------------------

class FakeCursor:
    def __init__(self, description, rows, error=None):
        self.description, self.rows, self.error = description, rows, error
        self.executed, self.closed = [], False

    def execute(self, query):
        if self.error:
            raise self.error
        self.executed.append(query)

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor, self.closed = cursor, False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class ScriptedEngine(DbApiSqlEngine):
    def __init__(self, connection):
        self.connection, self.databases = connection, []

    def connect(self, database):
        self.databases.append(database)
        return self.connection


def test_dbapi_engine_renders_rows_and_closes_everything():
    cursor = FakeCursor([("ingresos_totales", "DOUBLE_TYPE"), ("tx_totales", "BIGINT_TYPE")], [(24951090.85, 10000)])
    connection = FakeConnection(cursor)
    engine = ScriptedEngine(connection)
    result = engine.execute("SELECT ...", "d")
    assert result == QueryResult((Column("ingresos_totales", "double"), Column("tx_totales", "bigint")),
                                 (("24951090.85", "10000"),))
    assert engine.databases == ["d"] and cursor.closed and connection.closed


def test_dbapi_engine_does_not_fetch_without_a_description():
    cursor = FakeCursor(None, [("never",)])
    assert ScriptedEngine(FakeConnection(cursor)).execute("CREATE DATABASE d", "default") == QueryResult((), ())


def test_dbapi_engine_closes_on_failure():
    cursor = FakeCursor(None, [], error=RuntimeError("boom"))
    connection = FakeConnection(cursor)
    with pytest.raises(RuntimeError):
        ScriptedEngine(connection).execute("x", "d")
    assert cursor.closed and connection.closed


class _Status:
    errorMessage = "Error while compiling statement: FAILED: ParseException line 1:104 extraneous input ';'"


class _Response:
    status = _Status()


def test_hiveserver2_engine_connects_with_plain_column_names_and_maps_failures():
    seen = {}

    def connect(**kwargs):
        seen.update(kwargs)
        return FakeConnection(FakeCursor(None, [], error=RuntimeError(_Response())))

    engine = HiveServer2SqlEngine("athena-engine", 10000, "hive", connect)
    with pytest.raises(QueryFailedError, match="extraneous input ';'"):
        engine.execute("CREATE TABLE t (a int);", "default")
    assert seen == {"host": "athena-engine", "port": 10000, "username": "hive", "database": "default",
                    "configuration": {"hive.resultset.use.unique.column.names": "false"}}


@pytest.mark.parametrize("error, message", [
    (ConnectionRefusedError("refused"), "ConnectionRefusedError: refused"),
    (RuntimeError(), "RuntimeError: "),
    (RuntimeError(type("R", (), {"status": type("S", (), {"errorMessage": ""})()})()), None),
])
def test_failure_message_falls_back_to_the_exception(error, message):
    rendered = HiveServer2SqlEngine.failure_message(error)
    assert rendered == message if message else rendered.startswith("RuntimeError: ")


def test_s3_result_store_puts_the_object():
    class Client:
        def put_object(self, **kwargs):
            self.kwargs = kwargs

    client = Client()
    S3ResultStore(client).save(S3Location("b", "p/q.csv"), b"x")
    assert client.kwargs == {"Bucket": "b", "Key": "p/q.csv", "Body": b"x"}


def test_runtime_adapters():
    repository = InMemoryExecutionRepository()
    assert repository.get("x") is None
    clock = SystemClock().now()
    assert clock.tzinfo is timezone.utc
    first, second = Uuid4Generator().new_id(), Uuid4Generator().new_id()
    assert first != second and len(first) == 36
    order, done = [], threading.Event()
    runner = SingleWorkerTaskRunner()
    for i in range(3):
        runner.submit(lambda i=i: order.append(i))
    runner.submit(done.set)
    assert done.wait(5)
    runner.shutdown()
    assert order == [0, 1, 2]


# --- inbound protocol ----------------------------------------------------------

def protocol_with_one_success():
    svc, runner = service(FakeEngine(QueryResult((Column("n", "bigint"), Column("x", "varchar")), (("3", None),))))
    return AwsJson11Protocol(svc), runner


def call(protocol, operation, payload):
    return protocol.handle(f"AmazonAthena.{operation}", json.dumps(payload).encode())


def test_protocol_full_cycle_documents():
    protocol, runner = protocol_with_one_success()
    status, started = call(protocol, "StartQueryExecution", {
        "QueryString": "SELECT 3 AS n, NULL AS x", "ResultConfiguration": {"OutputLocation": OUT},
        "QueryExecutionContext": {"Database": "d"}})
    assert (status, started) == (200, {"QueryExecutionId": "q1"})
    status, queued = call(protocol, "GetQueryExecution", {"QueryExecutionId": "q1"})
    assert queued["QueryExecution"]["Status"]["State"] == "QUEUED"
    assert "CompletionDateTime" not in queued["QueryExecution"]["Status"]
    runner.drain()
    _, done = call(protocol, "GetQueryExecution", {"QueryExecutionId": "q1"})
    assert done["QueryExecution"] == {
        "QueryExecutionId": "q1", "Query": "SELECT 3 AS n, NULL AS x", "StatementType": "DML",
        "ResultConfiguration": {"OutputLocation": f"{OUT}q1.csv"}, "QueryExecutionContext": {"Database": "d"},
        "Status": {"State": "SUCCEEDED", "SubmissionDateTime": (T0 + timedelta(seconds=1)).timestamp(),
                   "CompletionDateTime": (T0 + timedelta(seconds=2)).timestamp()},
        "WorkGroup": "primary",
    }
    _, page = call(protocol, "GetQueryResults", {"QueryExecutionId": "q1", "MaxResults": 1})
    assert page["ResultSet"]["Rows"] == [{"Data": [{"VarCharValue": "n"}, {"VarCharValue": "x"}]}]
    assert page["NextToken"] == "1" and page["UpdateCount"] == 0
    assert [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]] == ["n", "x"]
    _, rest = call(protocol, "GetQueryResults", {"QueryExecutionId": "q1", "NextToken": "1"})
    assert rest["ResultSet"]["Rows"] == [{"Data": [{"VarCharValue": "3"}, {}]}] and "NextToken" not in rest


def test_protocol_reports_failure_reason():
    svc, runner = service(FakeEngine(error=QueryFailedError("Table not found")))
    protocol = AwsJson11Protocol(svc)
    call(protocol, "StartQueryExecution", {"QueryString": "SELECT * FROM t", "ResultConfiguration": {"OutputLocation": OUT}})
    runner.drain()
    _, failed = call(protocol, "GetQueryExecution", {"QueryExecutionId": "q1"})
    assert failed["QueryExecution"]["Status"]["StateChangeReason"] == "Table not found"


@pytest.mark.parametrize("target, body, status, code", [
    (None, b"{}", 400, "UnknownOperationException"),
    ("AmazonAthena.ListWorkGroups", b"{}", 400, "UnknownOperationException"),
    ("Other.StartQueryExecution", b"{}", 400, "UnknownOperationException"),
    ("AmazonAthena.GetQueryExecution", b"{not json", 400, "InvalidRequestException"),
    ("AmazonAthena.GetQueryExecution", b"[]", 400, "InvalidRequestException"),
    ("AmazonAthena.GetQueryExecution", b"{}", 400, "InvalidRequestException"),
    ("AmazonAthena.GetQueryExecution", b'{"QueryExecutionId": 5}', 400, "InvalidRequestException"),
    ("AmazonAthena.GetQueryResults", b'{"QueryExecutionId": "nope"}', 400, "InvalidRequestException"),
    ("AmazonAthena.StartQueryExecution", b"", 400, "InvalidRequestException"),
])
def test_protocol_errors(target, body, status, code):
    protocol, _ = protocol_with_one_success()
    got_status, document = protocol.handle(target, body)
    assert (got_status, document["__type"]) == (status, code) and document["Message"]


def test_protocol_turns_a_defect_into_an_internal_error():
    class Broken(AthenaQueryApiPort):
        def start_query_execution(self, request):
            raise KeyError("bug")

        def get_query_execution(self, query_id):
            raise NotImplementedError

        def get_query_results(self, query_id, max_results, next_token):
            raise NotImplementedError

    status, document = call(AwsJson11Protocol(Broken()), "StartQueryExecution",
                            {"QueryString": "SELECT 1", "ResultConfiguration": {"OutputLocation": OUT}})
    assert (status, document["__type"], document["Message"]) == (500, "InternalServerException", "KeyError: 'bug'")
    assert isinstance(AwsJson11Protocol(Broken()), ProtocolAdapter)


def test_statement_type_enum_values():
    assert [t.value for t in StatementType] == ["DDL", "DML", "UTILITY"]


# --- composition root ----------------------------------------------------------

def test_composition_root_wires_the_concrete_adapters():
    from athena_gateway import __main__ as root

    server, runner = root.build({"ATHENA_GATEWAY_BIND": "127.0.0.1", "ATHENA_GATEWAY_PORT": "0",
                                 "S3_ENDPOINT_URL": "http://127.0.0.1:9"})
    try:
        host, port = server.address
        assert host == "127.0.0.1" and port > 0
    finally:
        server.shutdown()
        runner.shutdown()
