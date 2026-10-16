"""`python -m athena_gateway` as a real process, driven by the AWS CLI's library.

No engine or S3 is running here, so a query must end FAILED with the
connection error as its reason (never hang, never crash the server), and
SIGTERM must stop the process cleanly. The full stack is the live tier.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time

import boto3
import pytest

pytestmark = pytest.mark.e2e


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def process(labs_root):
    port, dead = free_port(), free_port()
    env = dict(os.environ, ATHENA_GATEWAY_BIND="127.0.0.1", ATHENA_GATEWAY_PORT=str(port),
               ATHENA_ENGINE_HOST="127.0.0.1", ATHENA_ENGINE_PORT=str(dead),
               S3_ENDPOINT_URL=f"http://127.0.0.1:{dead}")
    proc = subprocess.Popen([sys.executable, "-m", "athena_gateway"], cwd=labs_root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == f"athena-gateway listening on 127.0.0.1:{port}"
    yield proc, port
    if proc.poll() is None:
        proc.kill()
        proc.wait(10)


def test_query_against_a_missing_engine_fails_with_the_reason(process):
    proc, port = process
    client = boto3.client("athena", endpoint_url=f"http://127.0.0.1:{port}", region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    query_id = client.start_query_execution(QueryString="SELECT 1",
                                            ResultConfiguration={"OutputLocation": "s3://bucket-x/out/"})[
        "QueryExecutionId"]
    for _ in range(200):
        status = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.05)
    assert status["State"] == "FAILED"
    assert "Could not connect" in status["StateChangeReason"] or "refused" in status["StateChangeReason"]
    assert proc.poll() is None  # the server keeps serving


def test_sigterm_stops_the_process_cleanly(process):
    proc, _ = process
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0, err
    assert out.strip().endswith("athena-gateway stopped")
