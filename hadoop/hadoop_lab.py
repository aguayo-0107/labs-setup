# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: .venv
#     language: python
#     name: non-relational-dbs-labs
# ---

# %% [markdown]
# # Hadoop lab — HDFS and MapReduce
#
# ## 1. Parameters
#
# - **What:** default values for `NETWORK_MODE`, the VPN identity.
# - **Why:** the same notebook serves Local mode (ports on `127.0.0.1`) and VPN mode (`<container>.<alias>.<domain>`).
# - **How:** the cell is tagged `parameters`; papermill inserts an `injected-parameters` cell right after it with the `-p` values.
# - 📄 [papermill — Parameterize](https://papermill.readthedocs.io/en/latest/usage-parameterize.html)

# %% tags=["parameters"]
# Local mode is the portable default; VPN mode publishes services on this host.
NETWORK_MODE = "local"
VPN_HOST_IP = "10.15.20.100"
VPN_DNS_IP = "10.15.20.1"
VPN_DOMAIN = "vpn.itam.mx"
VPN_CLIENT_ALIAS = "mavasbel"

# %% [markdown]
# ## 2. Validate the parameters
#
# - **What:** lower-cases `NETWORK_MODE` and `VPN_CLIENT_ALIAS` and builds `VPN_CLIENT_DOMAIN = <alias>.<domain>`.
# - **Why:** a wrong value must stop the notebook here, before any container changes.
# - **How:** rejects any mode other than `local`/`vpn` and, in VPN mode, a host IP outside `10.15.20.*`, and an alias that is not lower-case letters, digits and inner hyphens.

# %%
NETWORK_MODE = NETWORK_MODE.strip().lower()
VPN_CLIENT_ALIAS = VPN_CLIENT_ALIAS.strip().lower()
if NETWORK_MODE not in {"local", "vpn"}:
    raise ValueError("NETWORK_MODE must be 'local' or 'vpn'")
if NETWORK_MODE == "vpn" and not VPN_HOST_IP.startswith("10.15.20."):
    raise ValueError("VPN_HOST_IP must be in the 10.15.20.* subnet")
if (
    not VPN_CLIENT_ALIAS
    or VPN_CLIENT_ALIAS.startswith("-")
    or VPN_CLIENT_ALIAS.endswith("-")
    or not VPN_CLIENT_ALIAS.isascii()
    or not VPN_CLIENT_ALIAS.replace("-", "").isalnum()
):
    raise ValueError(
        "VPN_CLIENT_ALIAS must contain only lowercase letters, digits, and internal hyphens"
    )
VPN_CLIENT_DOMAIN = f"{VPN_CLIENT_ALIAS}.{VPN_DOMAIN}"

# %% [markdown]
# ## 3. Find the module folder
#
# - **What:** locates the labs-setup root, changes into `hadoop/` and imports `run_command`.
# - **Why:** relative paths (Compose file, `mount/`) then resolve the same way whether papermill or JupyterLab started the kernel; `run_command` passes an argument list to the program without a shell, so it behaves the same on Windows, macOS and Linux.
# - **How:** walks up from the current folder to the first one holding `pyproject.toml`, `cassandra/` and `mongodb/`.

# %%
# Resolve module assets from the labs-setup root.
import os
from pathlib import Path

_start = Path.cwd().resolve()
LABS_ROOT = next(
    (
        candidate
        for candidate in (_start, *_start.parents)
        if (candidate / "pyproject.toml").is_file()
        and (candidate / "cassandra").is_dir()
        and (candidate / "mongodb").is_dir()
    ),
    None,
)
if LABS_ROOT is None:
    raise RuntimeError(
        "Could not find the labs-setup root from the current directory"
    )
MODULE_DIR = LABS_ROOT / "hadoop"
import sys

if str(LABS_ROOT) not in sys.path:
    sys.path.insert(0, str(LABS_ROOT))
from labs_runtime import run_command

os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Client settings
#
# - **What:** the hosts and ports the notebook uses to reach the cluster, and `HADOOP_DATA_RECORDS = 100_000`.
# - **Why:** they must match what `hadoop_infra` configured.
# - **How:** hosts are `127.0.0.1` (Local) or `namenode` / `resourcemanager` `.<alias>.<domain>` (VPN); `HADOOP_START_FROM_SCRATCH=False` reuses the generated data if it exists.

# %%
HADOOP_START_FROM_SCRATCH = False
HADOOP_DATA_RECORDS = 100_000
DOCKER_INTERNAL_HOST = "host.docker.internal"

HADOOP_NAMENODE_HOSTNAME = "namenode"
HADOOP_NAMENODE_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else f"{HADOOP_NAMENODE_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
)
HADOOP_NAMENODE_IP = HADOOP_NAMENODE_CLIENT_HOST
HADOOP_NAMENODE_PORT = 8020
HADOOP_NAMENODE_WEBUI_PORT = 9870

HADOOP_RESOURCEMANAGER_HOSTNAME = "resourcemanager"
HADOOP_RESOURCEMANAGER_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else f"{HADOOP_RESOURCEMANAGER_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
)
HADOOP_RESOURCEMANAGER_IP = HADOOP_RESOURCEMANAGER_CLIENT_HOST
HADOOP_RESOURCEMANAGER_WEBUI_PORT = 8088
HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT = 8032
HADOOP_RESOURCEMANAGER_TRACKER_PORT = 8031
HADOOP_RESOURCEMANAGER_SCHEDULER_PORT = 8030
HADOOP_RESOURCEMANAGER_ADMIN_PORT = 8033

HADOOP_MAPRED_JOB_HISTORY_PORT = 10020
HADOOP_MAPRED_LOG_SERVER_PORT = 19888

HADOOP_REPLICATION = 2
HADOOP_NUM_WORKERS = 2

HADOOP_DATANODE_NAMES = [f"datanode-{i+1}" for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_HOSTNAMES = HADOOP_DATANODE_NAMES
HADOOP_DATANODE_IPS = [
    f"{name}.{VPN_CLIENT_DOMAIN}" if NETWORK_MODE == "vpn" else "127.0.0.1"
    for name in HADOOP_DATANODE_NAMES
]
HADOOP_DATANODE_WEBUI_PORTS = [9864 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_TRANSFER_PORTS = [9866 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_IPC_PORTS = [6867 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]

HADOOP_NODEMANAGER_NAMES = [f"nodemanager-{i+1}" for i in range(HADOOP_NUM_WORKERS)]
HADOOP_NODEMANAGER_HOSTNAMES = HADOOP_NODEMANAGER_NAMES
HADOOP_NODEMANAGER_IPS = [
    f"{name}.{VPN_CLIENT_DOMAIN}" if NETWORK_MODE == "vpn" else "127.0.0.1"
    for name in HADOOP_NODEMANAGER_NAMES
]
HADOOP_NODEMANAGER_WEBUI_PORTS = [8050 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_NODEMANAGER_RPC_PORTS = [8051 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]

HADOOP_WORKDIR = "/opt/hadoop/work-dir"
HADOOP_NAMENODE_NAMEDIR = "/opt/hadoop/dfs/name"
HADOOP_DATANODE_DATADIR = "/opt/hadoop/dfs/data"

HADOOP_HDFS_DATADIR = "/opt/hadoop/work-dir"

# %% [markdown]
# ## 5. Check the cluster answers
#
# - **What:** asks the NameNode for its JMX `NameNodeInfo` and the ResourceManager for its cluster state.
# - **Why:** it fails early, with a clear message, if the cluster is down or unreachable.
# - **How:** `GET :9870/jmx?qry=Hadoop:service=NameNode,name=NameNodeInfo` must return beans; `GET :8088/ws/v1/cluster/info` must say `STARTED`.
# - 📄 [ResourceManager REST API](https://hadoop.apache.org/docs/r3.4.3/hadoop-yarn/hadoop-yarn-site/ResourceManagerRest.html)

# %%
import json
from urllib.request import urlopen

with urlopen(
    f"http://{HADOOP_NAMENODE_CLIENT_HOST}:{HADOOP_NAMENODE_WEBUI_PORT}/jmx"
    "?qry=Hadoop:service=NameNode,name=NameNodeInfo",
    timeout=15,
) as response:
    namenode_jmx = json.load(response)
assert namenode_jmx["beans"], namenode_jmx

with urlopen(
    f"http://{HADOOP_RESOURCEMANAGER_CLIENT_HOST}:8088/ws/v1/cluster/info",
    timeout=15,
) as response:
    yarn_info = json.load(response)["clusterInfo"]
assert yarn_info["state"] == "STARTED", yarn_info
print(
    f"Validated {NETWORK_MODE} data path to NameNode and ResourceManager at "
    f"{HADOOP_NAMENODE_CLIENT_HOST}"
)

# %% [markdown]
# ## 6. Folders and YARN capacity
#
# - **What:** creates the local `mount/` folder and checks YARN has 2 active NodeManagers.
# - **Why:** a MapReduce job needs NodeManagers to run its tasks.
# - **How:** `GET :8088/ws/v1/cluster/metrics` → `activeNodes == 2`.
# - 📄 [ResourceManager REST API](https://hadoop.apache.org/docs/r3.4.3/hadoop-yarn/hadoop-yarn-site/ResourceManagerRest.html)

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = f"{os.path.join(os.path.relpath(Path.cwd()))}"
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")

Path(DOCKER_MOUNTDIR).mkdir(parents=True, exist_ok=True)

import requests

namenode_jmx = requests.get(
    f"http://{HADOOP_NAMENODE_CLIENT_HOST}:{HADOOP_NAMENODE_WEBUI_PORT}/jmx?qry=Hadoop:service=NameNode,name=NameNodeInfo",
    timeout=30,
)
namenode_jmx.raise_for_status()
assert namenode_jmx.json()["beans"], namenode_jmx.text
yarn_metrics = requests.get(
    f"http://{HADOOP_RESOURCEMANAGER_CLIENT_HOST}:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}/ws/v1/cluster/metrics",
    timeout=30,
)
yarn_metrics.raise_for_status()
metrics = yarn_metrics.json()["clusterMetrics"]
assert metrics["activeNodes"] == HADOOP_NUM_WORKERS, metrics

# %% [markdown]
# ## 7. Generate the dataset
#
# - **What:** writes `data.csv` with 100,000 fake sales (`ts, id, user, amount, category, country`).
# - **Why:** fixed seeds make every run produce the same file, so results can be compared.
# - **How:** `Faker.seed(2026)` and `random.seed(2026)`; the file is only regenerated if missing or with `HADOOP_START_FROM_SCRATCH=True`.
# - 📄 [Faker — Seeding](https://faker.readthedocs.io/en/master/#seeding-the-generator)

# %%
import csv
import random

from faker import Faker
from tqdm import tqdm


def generate_data(path, records):
    Faker.seed(2026)
    random.seed(2026)
    fake = Faker()
    print(f"Generating {records:,} deterministic records...")
    with open(path, "w", newline="", encoding="utf-8") as data_file:
        writer = csv.writer(data_file)
        writer.writerow(["ts", "id", "user", "amount", "category", "country"])
        for _ in tqdm(range(records), desc="Progress", unit="rows"):
            writer.writerow(
                [
                    fake.date_time_this_year().strftime("%Y-%m-%d %H:%M:%S"),
                    fake.uuid4(),
                    fake.name(),
                    round(random.uniform(10.50, 10_000.00), 2),
                    fake.bs(),
                    fake.country(),
                ]
            )


dataset_source_path = os.path.join(LOCALHOST_WORKDIR, "data.csv")
if HADOOP_START_FROM_SCRATCH or not os.path.exists(dataset_source_path):
    generate_data(dataset_source_path, HADOOP_DATA_RECORDS)
    print(f"Created {dataset_source_path}")


# %% [markdown]
# ## 8. Hand the file to the NameNode container
#
# - **What:** copies `data.csv` into `mount/namenode/work-dir`.
# - **Why:** that folder is `/opt/hadoop/work-dir` inside `namenode`, where the `hdfs` commands run.
# - **How:** `shutil.copy` on the host.
# - 📄 [Docker — Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

# %%
import shutil

dataset_source_path = os.path.join(LOCALHOST_WORKDIR, "data.csv")
dataset_dest_path = os.path.join(DOCKER_MOUNTDIR, "namenode", "work-dir", "data.csv")
if HADOOP_START_FROM_SCRATCH or not os.path.exists(dataset_dest_path):
    shutil.copy(dataset_source_path, dataset_dest_path)

# %% [markdown]
# ## 9. Prepare the HDFS folders
#
# - **What:** creates the HDFS `input` folder and removes a previous `output`.
# - **Why:** MapReduce refuses to write into an output folder that already exists.
# - **How:** `hdfs dfs -mkdir -p` and `hdfs dfs -rm -r -f`, run with `docker exec namenode`.
# - 📄 [FileSystem shell](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/FileSystemShell.html)

# %%
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-mkdir", "-p", f"{HADOOP_HDFS_DATADIR}/input"], check=False)
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-rm", "-r", "-f", f"{HADOOP_HDFS_DATADIR}/output"], check=False)
print("HDFS environment initialized.")

# %% [markdown]
# ## 10. Upload to HDFS
#
# - **What:** copies `data.csv` from the container's disk into HDFS and lists it.
# - **Why:** MapReduce reads its input from HDFS, where the file is split into blocks spread over the DataNodes.
# - **How:** `hdfs dfs -put -f` and `hdfs dfs -ls`.
# - 📄 [FileSystem shell](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/FileSystemShell.html)

# %%
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-put", "-f", f"{HADOOP_WORKDIR}/data.csv", f"{HADOOP_HDFS_DATADIR}/input/"], check=False)
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-ls", f"{HADOOP_HDFS_DATADIR}/input"], check=False)

# %% [markdown]
# ## 11. Blocks and replicas
#
# - **What:** shows the file's blocks and on which DataNodes each copy lives.
# - **Why:** with replication `2`, every block must appear on both DataNodes.
# - **How:** `hdfs fsck <file> -files -blocks -locations`.
# - 📄 [HDFS commands (fsck)](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-hdfs/HDFSCommands.html) · [HDFS architecture (blocks and replication)](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html)

# %%
run_command(["docker", "exec", "namenode", "hdfs", "fsck", f"{HADOOP_HDFS_DATADIR}/input/data.csv", "-files", "-blocks", "-locations"], check=False)

# %% [markdown]
# ## 12. Mapper and reducer
#
# - **What:** writes `mapper.py` (emits `category<TAB>amount` per row) and `reducer.py` (adds the amounts of each category).
# - **Why:** Hadoop Streaming runs any program that reads standard input and writes standard output; between the two phases Hadoop sorts by key, so the reducer sees each category's lines together.
# - **How:** files are written into `mount/resourcemanager/work-dir`, where the job is submitted.
# - 📄 [Hadoop Streaming](https://hadoop.apache.org/docs/r3.4.3/hadoop-streaming/HadoopStreaming.html) · [MapReduce tutorial](https://hadoop.apache.org/docs/r3.4.3/hadoop-mapreduce-client/hadoop-mapreduce-client-core/MapReduceTutorial.html)

# %%
import os

mapper_file_contents = """#!/usr/bin/env python
import sys

# Standard for Hadoop Streaming: read from STDIN
for line in sys.stdin:
    line = line.strip()
    # Split the CSV line
    parts = line.split(',')
    
    # Check if we have enough columns and skip the header
    if len(parts) >= 4 and parts[0] != "ts":
        category = parts[4]
        amount = parts[3]
        
        # Output: category [TAB] amount
        # Hadoop will sort these by the key (category) before the Reducer sees them
        print("%s\\t%s" % (category, amount))
"""

with open(os.path.join(DOCKER_MOUNTDIR,"resourcemanager", "work-dir",'mapper.py'), 'w', encoding="utf-8", newline="\n") as mapper_file:
    mapper_file.write(mapper_file_contents)
print("Mapper script created")


reducer_file_contents = """#!/usr/bin/env python
import sys

current_category = None
current_sum = 0.0

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
        
    try:
        category, amount = line.split('\\t')
        amount = float(amount)
    except ValueError:
        continue

    # Logic: If the category changes, print the total for the previous one
    if current_category == category:
        current_sum += amount
    else:
        if current_category:
            print("%s\\t%.2f" % (current_category, current_sum))
        current_category = category
        current_sum = amount

# Don't forget the last category!
if current_category:
    print("%s\\t%.2f" % (current_category, current_sum))
"""

with open(os.path.join(DOCKER_MOUNTDIR,"resourcemanager", "work-dir",'reducer.py'), 'w', encoding="utf-8", newline="\n") as reducer_file:
    reducer_file.write(reducer_file_contents)
print("Reducer script created")

run_command(["docker", "exec", "resourcemanager", "ls", "-l", f"{HADOOP_WORKDIR}"], check=False)

# %% [markdown]
# ## 13. The same computation without Hadoop
#
# - **What:** runs `cat data.csv | mapper | sort | reducer` inside `namenode`.
# - **Why:** it shows what MapReduce does on one machine and gives a result to compare with the cluster's.
# - **How:** the scripts are copied into the NameNode's work folder; `sort` stands in for Hadoop's shuffle.
# - 📄 [Hadoop Streaming](https://hadoop.apache.org/docs/r3.4.3/hadoop-streaming/HadoopStreaming.html)

# %%
shutil.copy(
    os.path.join(DOCKER_MOUNTDIR, "resourcemanager", "work-dir", "mapper.py"),
    os.path.join(DOCKER_MOUNTDIR, "namenode", "work-dir", "mapper.py"),
)
shutil.copy(
    os.path.join(
        DOCKER_MOUNTDIR, "resourcemanager", "work-dir", "reducer.py"
    ),
    os.path.join(DOCKER_MOUNTDIR, "namenode", "work-dir", "reducer.py"),
)
run_command(["docker", "exec", "namenode", "bash", "-c", f"cat {HADOOP_WORKDIR}/data.csv | python {HADOOP_WORKDIR}/mapper.py | sort | python {HADOOP_WORKDIR}/reducer.py"], check=False)

# %% [markdown]
# ## 14. Run the MapReduce job
#
# - **What:** submits the streaming job to YARN with 2 reducers and 1024 MB per map and reduce task, then lists `output`.
# - **Why:** the work is split into map tasks over the HDFS blocks and run on the NodeManagers.
# - **How:** `yarn jar hadoop-streaming-3.4.3.jar` with `-files` (ships the scripts to every task), `-mapper`, `-reducer`, `-input`, `-output`; the cell fails if the job's exit code is not 0.
# - 📄 [Hadoop Streaming](https://hadoop.apache.org/docs/r3.4.3/hadoop-streaming/HadoopStreaming.html) · [mapred-default.xml](https://hadoop.apache.org/docs/r3.4.3/hadoop-mapreduce-client/hadoop-mapreduce-client-core/mapred-default.xml)

# %%
# 1. Ensure the output directory is clean
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-rm", "-r", "-f", f"{HADOOP_HDFS_DATADIR}/output"], check=False)

# 2. Submit the job from the ResourceManager to Nodemanagers
import subprocess

mapreduce_job = subprocess.run(
    [
        "docker", "exec", "resourcemanager", "yarn", "jar",
        "/opt/hadoop/share/hadoop/tools/lib/hadoop-streaming-3.4.3.jar",
        "-D", "mapred.reduce.tasks=2",
        "-D", "mapreduce.map.memory.mb=1024",
        "-D", "mapreduce.reduce.memory.mb=1024",
        "-files", f"{HADOOP_WORKDIR}/mapper.py,{HADOOP_WORKDIR}/reducer.py",
        "-mapper", "python mapper.py",
        "-reducer", "python reducer.py",
        "-input", f"{HADOOP_HDFS_DATADIR}/input/data.csv",
        "-output", f"{HADOOP_HDFS_DATADIR}/output",
    ],
    capture_output=True,
    text=True,
    timeout=300,
    encoding="utf-8",
)
print(mapreduce_job.stdout)
assert mapreduce_job.returncode == 0, mapreduce_job.stderr[-4000:]

# 3. Show output file
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-ls", f"{HADOOP_HDFS_DATADIR}/output"], check=False)

# %% [markdown]
# ## 15. Merge and sort the result
#
# - **What:** joins the reducers' `part-*` files into `output.csv` and sorts it into `output_sorted.csv`.
# - **Why:** with 2 reducers the result is split in two files, each covering part of the categories.
# - **How:** `hdfs dfs -getmerge` then `sort`.
# - 📄 [FileSystem shell](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/FileSystemShell.html)

# %%
# 4. Merge and sort output
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-getmerge", f"{HADOOP_HDFS_DATADIR}/output", f"{HADOOP_WORKDIR}/output.csv"], check=False)
run_command(["docker", "exec", "namenode", "bash", "-c", f"cat {HADOOP_WORKDIR}/output.csv | sort > {HADOOP_WORKDIR}/output_sorted.csv"], check=False)

# %% [markdown]
# ## 16. Check the result
#
# - **What:** reads `output_sorted.csv` and checks it is not empty and has `category<TAB>total` lines.
# - **Why:** it turns the job into a check that fails if MapReduce produced nothing.
# - **How:** `docker exec namenode cat ...`.

# %%
import subprocess

output = subprocess.run(
    ["docker", "exec", "namenode", "cat", f"{HADOOP_WORKDIR}/output_sorted.csv"],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
).stdout.strip()
assert output, "MapReduce output is empty"
assert "\t" in output, output[:200]
print(f"Validated MapReduce output with {len(output.splitlines())} categories")
