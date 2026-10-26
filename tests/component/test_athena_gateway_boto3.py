"""The real HTTP server and protocol, driven by the real boto3 Athena client.

Only the SQL engine and the result store are in-process doubles, so this
proves the wire format boto3 expects: JSON 1.1 targets, timestamps, error
documents, and the header row that the AWS lab reads as `Rows[1]`.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import boto3
import pytest
import urllib.request
from botocore.exceptions import ClientError

from athena_gateway.adapters.inbound.http import HttpGatewayServer, InboundServer
from athena_gateway.adapters.inbound.protocol import AwsJson11Protocol
from athena_gateway.adapters.outbound.runtime import (
    InMemoryExecutionRepository,
    SingleWorkerTaskRunner,
    SystemClock,
    Uuid4Generator,
)
from athena_gateway.application.service import AthenaQueryService
from athena_gateway.domain.errors import QueryFailedError
from athena_gateway.domain.models import Column, QueryResult
from athena_gateway.ports.outbound import ResultStorePort, SqlEnginePort

pytestmark = pytest.mark.component

OUT = "s3://lab-aws-x-datalake/athena-results/"


class TableEngine(SqlEnginePort):
    def execute(self, query, database):
        if query.rstrip().endswith(";"):
            raise QueryFailedError("FAILED: ParseException line 1:20 extraneous input ';' expecting EOF")
        if query.startswith("CREATE"):
            return QueryResult((), ())
        return QueryResult((Column("ingresos_totales", "double"), Column("tx_totales", "bigint")),
                           (("2.4951090849999912E7", "10000"),))


class MemoryStore(ResultStorePort):
    def __init__(self):
        self.saved = {}

    def save(self, location, content):
        self.saved[location.uri] = content


@pytest.fixture
def gateway():
    store = MemoryStore()
    runner = SingleWorkerTaskRunner()
    service = AthenaQueryService(TableEngine(), store, InMemoryExecutionRepository(), runner,
                                 SystemClock(), Uuid4Generator())
    server = HttpGatewayServer(AwsJson11Protocol(service), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.address
    client = boto3.client("athena", endpoint_url=f"http://{host}:{port}", region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    yield client, store, f"http://{host}:{port}", server
    server.shutdown()
    runner.shutdown()
    thread.join(5)


def wait(client, query_id):
    for _ in range(100):
        execution = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        if execution["Status"]["State"] in ("SUCCEEDED", "FAILED"):
            return execution
        time.sleep(0.05)
    raise AssertionError("query never finished")


def test_lab_style_select_through_boto3(gateway):
    client, store, _, server = gateway
    assert isinstance(server, InboundServer)
    query_id = client.start_query_execution(
        QueryString="SELECT SUM(monto) as ingresos_totales, COUNT(*) as tx_totales FROM d.transacciones",
        ResultConfiguration={"OutputLocation": OUT},
    )["QueryExecutionId"]
    execution = wait(client, query_id)
    assert execution["Status"]["State"] == "SUCCEEDED" and execution["StatementType"] == "DML"
    assert isinstance(execution["Status"]["SubmissionDateTime"], datetime)
    assert execution["ResultConfiguration"]["OutputLocation"] == f"{OUT}{query_id}.csv"
    rows = client.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
    data = rows[1]["Data"]  # exactly what the lab's athena_job.py reads
    assert float(data[0]["VarCharValue"]) == pytest.approx(24951090.85) and data[1]["VarCharValue"] == "10000"
    assert [d["VarCharValue"] for d in rows[0]["Data"]] == ["ingresos_totales", "tx_totales"]
    assert store.saved[f"{OUT}{query_id}.csv"].startswith(b'"ingresos_totales","tx_totales"\n')


def test_failed_ddl_reports_the_engine_reason(gateway):
    client = gateway[0]
    query_id = client.start_query_execution(QueryString="CREATE TABLE t (a int);",
                                            ResultConfiguration={"OutputLocation": OUT})["QueryExecutionId"]
    execution = wait(client, query_id)
    assert execution["Status"]["State"] == "FAILED"
    assert "extraneous input ';'" in execution["Status"]["StateChangeReason"]
    with pytest.raises(ClientError) as raised:
        client.get_query_results(QueryExecutionId=query_id)
    assert raised.value.response["Error"]["Code"] == "InvalidRequestException"


def test_boto3_paginator_reads_every_row(gateway):
    client = gateway[0]
    query_id = client.start_query_execution(QueryString="SELECT 1", ResultConfiguration={"OutputLocation": OUT})[
        "QueryExecutionId"]
    wait(client, query_id)
    pages = list(client.get_paginator("get_query_results").paginate(
        QueryExecutionId=query_id, PaginationConfig={"PageSize": 1}))
    assert [len(p["ResultSet"]["Rows"]) for p in pages] == [1, 1]


def test_client_side_errors_surface_as_athena_errors(gateway):
    client = gateway[0]
    with pytest.raises(ClientError) as missing:
        client.start_query_execution(QueryString="SELECT 1")
    assert missing.value.response["Error"]["Code"] == "InvalidRequestException"
    with pytest.raises(ClientError) as unknown:
        client.list_work_groups()
    assert unknown.value.response["Error"]["Code"] == "UnknownOperationException"


def test_health_endpoint_and_unknown_paths(gateway):
    base = gateway[2]
    with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
        assert (response.status, response.read()) == (200, b'{"status": "ok"}')
    with pytest.raises(urllib.error.HTTPError) as missing:
        urllib.request.urlopen(f"{base}/other", timeout=5)
    assert missing.value.code == 404
