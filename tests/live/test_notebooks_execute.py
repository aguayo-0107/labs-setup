"""Execute every infra/lab pair with papermill in local mode (opt-in: LABS_LIVE=1).

Infrastructure always runs before its lab; MongoDB config servers before the
data nodes; Hadoop before Hive and Spark. Executed copies go to a temporary
directory, never next to the committed notebooks. The Spark lab is the Spark
Driver, so it runs inside the spark-jupyter container, which sees labs-setup
read-only; its executed copy stays inside the container.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("LABS_LIVE") != "1", reason="set LABS_LIVE=1 to run the labs"),
]

SEQUENCE = (
    ("cassandra", ("cassandra/cassandra_infra",), "cassandra/cassandra_lab"),
    ("mongodb", ("mongodb/mongodb_infra_configsvr", "mongodb/mongodb_infra"), "mongodb/mongodb_lab"),
    ("redis", ("redis/redis_infra",), "redis/redis_lab"),
    ("neo4j", ("neo4j/neo4j_infra",), "neo4j/neo4j_lab"),
    ("opensearch", ("opensearch/opensearch_infra",), "opensearch/opensearch_lab"),
    ("hadoop", ("hadoop/hadoop_infra",), "hadoop/hadoop_lab"),
    ("hive", ("hadoop/hive_infra",), "hadoop/hive_lab"),
    ("spark", ("spark/spark_infra",), "spark/spark_lab"),
    ("aws", ("aws/aws_infra",), "aws/aws_lab"),
)


IN_CONTAINER = {"spark/spark_lab": ("spark-jupyter", "/opt/spark/work-dir/labs-setup")}


def papermill(labs_root, tmp_path, stem, *extra):
    if stem in IN_CONTAINER:
        container, root = IN_CONTAINER[stem]
        command = [
            "docker", "exec", "-w", root, container, "papermill", f"{stem}.ipynb",
            f"/tmp/{stem.replace('/', '_')}.executed.ipynb", "-k", "python3",
        ]
    else:
        command = [
            sys.executable, "-m", "papermill", f"{stem}.ipynb",
            str(tmp_path / f"{stem.replace('/', '_')}.executed.ipynb"), "-k", "non-relational-dbs-labs",
        ]
    result = subprocess.run(
        [*command, "-p", "NETWORK_MODE", "local", *extra],
        cwd=labs_root, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.parametrize("name, infras, lab", SEQUENCE, ids=[item[0] for item in SEQUENCE])
def test_pair_executes_in_local_mode(labs_root, tmp_path, name, infras, lab):
    for infra in infras:
        papermill(labs_root, tmp_path, infra, "-p", "START_FROM_SCRATCH", "True")
    papermill(labs_root, tmp_path, lab)
