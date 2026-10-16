"""Composition root: the only module that names concrete classes.

Configuration comes from the environment (defaults are the Compose service
names of `aws/aws_infra`):

- ATHENA_GATEWAY_BIND / ATHENA_GATEWAY_PORT: listen address (0.0.0.0:8080)
- ATHENA_ENGINE_HOST / ATHENA_ENGINE_PORT / ATHENA_ENGINE_USER: HiveServer2
- S3_ENDPOINT_URL: emulated S3 where result files are written (required)
- AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY: passed to the S3 client
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Mapping

import boto3
from pyhive import hive

from .adapters.inbound.http import HttpGatewayServer, InboundServer
from .adapters.inbound.protocol import AwsJson11Protocol
from .adapters.outbound.engine import HiveServer2SqlEngine
from .adapters.outbound.runtime import (
    InMemoryExecutionRepository,
    SingleWorkerTaskRunner,
    SystemClock,
    Uuid4Generator,
)
from .adapters.outbound.storage import S3ResultStore
from .application.service import AthenaQueryService


def build(env: Mapping[str, str]) -> tuple[InboundServer, SingleWorkerTaskRunner]:
    engine = HiveServer2SqlEngine(
        host=env.get("ATHENA_ENGINE_HOST", "athena-engine"),
        port=int(env.get("ATHENA_ENGINE_PORT", "10000")),
        username=env.get("ATHENA_ENGINE_USER", "hive"),
        connect=hive.Connection,
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=env["S3_ENDPOINT_URL"],
        region_name=env.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=env.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=env.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    runner = SingleWorkerTaskRunner()
    service = AthenaQueryService(
        engine=engine,
        store=S3ResultStore(s3),
        repository=InMemoryExecutionRepository(),
        runner=runner,
        clock=SystemClock(),
        ids=Uuid4Generator(),
    )
    server = HttpGatewayServer(
        AwsJson11Protocol(service),
        env.get("ATHENA_GATEWAY_BIND", "0.0.0.0"),
        int(env.get("ATHENA_GATEWAY_PORT", "8080")),
    )
    return server, runner


def main(env: Mapping[str, str] = os.environ) -> int:
    server, runner = build(env)
    stop = lambda *_: threading.Thread(target=server.shutdown).start()  # noqa: E731
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    host, port = server.address
    print(f"athena-gateway listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        runner.shutdown()
    print("athena-gateway stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
