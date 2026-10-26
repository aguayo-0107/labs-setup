# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: non-relational-dbs-labs
#     language: python
#     name: non-relational-dbs-labs
# ---

# %% [markdown]
# # OpenSearch — infrastructure
#
# ## 1. Parameters
#
# - **What:** default values for `NETWORK_MODE`, the VPN identity and `START_FROM_SCRATCH`.
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
START_FROM_SCRATCH = False

# %% [markdown]
# ## 2. Validate the parameters
#
# - **What:** lower-cases `NETWORK_MODE` and `VPN_CLIENT_ALIAS` and builds `VPN_CLIENT_DOMAIN = <alias>.<domain>`.
# - **Why:** a wrong value must stop the notebook here, before any container changes.
# - **How:** rejects any mode other than `local`/`vpn` and, in VPN mode, a host IP outside `10.15.20.*`, and an alias that is not lower-case letters, digits and inner hyphens.

# %%
import re

NETWORK_MODE = NETWORK_MODE.strip().lower()
if NETWORK_MODE not in {"local", "vpn"}:
    raise ValueError("NETWORK_MODE must be 'local' or 'vpn'")
if NETWORK_MODE == "vpn" and not VPN_HOST_IP.startswith("10.15.20."):
    raise ValueError("VPN_HOST_IP must be in the 10.15.20.* subnet")
VPN_CLIENT_ALIAS = VPN_CLIENT_ALIAS.strip().lower()
if not VPN_CLIENT_ALIAS:
    raise ValueError("VPN_CLIENT_ALIAS must not be empty")
if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", VPN_CLIENT_ALIAS) is None:
    raise ValueError(
        "VPN_CLIENT_ALIAS must contain only lowercase letters, digits, or hyphens "
        "and must not start or end with a hyphen"
    )
VPN_CLIENT_DOMAIN = f"{VPN_CLIENT_ALIAS}.{VPN_DOMAIN}"

# %% [markdown]
# ## 3. Find the module folder
#
# - **What:** locates the labs-setup root, changes into `opensearch/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "opensearch"
import sys

if str(LABS_ROOT) not in sys.path:
    sys.path.insert(0, str(LABS_ROOT))
from labs_runtime import run_command

os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Cluster settings
#
# - **What:** three nodes `opensearch-node-1..3` with REST ports `9201-9203` and Performance Analyzer ports `16281-16283`, plus Dashboards on `5601`; the admin password is `OpenSearchP455`.
# - **Why:** every node publishes on the same host, so each needs its own ports; clients reach `127.0.0.1` (Local) or `opensearch-node-N.<alias>.<domain>` (VPN).
# - **How:** Dashboards reaches the nodes by container name over HTTPS (`https://opensearch-node-N:<port>`).

# %%
OPENSEARCH_START_FROM_SCRATCH = START_FROM_SCRATCH
DOCKER_INTERNAL_HOST = "host.docker.internal"
DOCKER_DNS = [VPN_DNS_IP] if NETWORK_MODE == "vpn" else []
HOST_BIND_IP = VPN_HOST_IP if NETWORK_MODE == "vpn" else "127.0.0.1"

OPENSEARCH_DASHBOARD_PORT = 5601

OPENSEARCH_CLUSTER_NAME = "opensearch-cluster"
OPENSEARCH_TOTAL_NODES = 3

OPENSEARCH_NODE_NAMES = [
    f"opensearch-node-{i+1}" for i in range(OPENSEARCH_TOTAL_NODES)
]


def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


OPENSEARCH_NODE_REST_API_PORTS = [9200 + (i + 1) for i in range(OPENSEARCH_TOTAL_NODES)]
OPENSEARCH_NODE_PERF_ANA_PORTS = [
    16280 + (i + 1) for i in range(OPENSEARCH_TOTAL_NODES)
]
OPENSEARCH_NODE_HOSTNAMES = [
    name if NETWORK_MODE == "local" else vpn_fqdn(name)
    for name in OPENSEARCH_NODE_NAMES
]
OPENSEARCH_NODE_INTERNAL_ENDPOINTS = [
    f"https://{name}:{port}"
    for name, port in zip(OPENSEARCH_NODE_NAMES, OPENSEARCH_NODE_REST_API_PORTS)
]
OPENSEARCH_DASHBOARDS_NAME = "opensearch-dashboards"
OPENSEARCH_DASHBOARDS_HOSTNAME = (
    OPENSEARCH_DASHBOARDS_NAME
    if NETWORK_MODE == "local"
    else vpn_fqdn(OPENSEARCH_DASHBOARDS_NAME)
)

OPENSEARCH_WORKDIR = "/usr/share/opensearch/data"

OPENSEARCH_INITIAL_ADMIN_PASSWORD = "OpenSearchP455"
# OPENSEARCH_DEFAULT_PASSWORD = "opensearch"
# OPENSEARCH_INIT_USER = "opensearch"
# OPENSEARCH_INIT_PASSWORD = "opensearch"

# %% [markdown]
# ## 5. Host folder
#
# - **What:** creates `mount/`, with one folder per node.
# - **Why:** the indexes survive a container restart.
# - **How:** path built from `MODULE_DIR` with `os.path.join`.
# - 📄 [Docker — Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = str(MODULE_DIR.resolve())
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")

mount_path = Path(DOCKER_MOUNTDIR)
mount_path.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## 6. Stop the previous cluster
#
# - **What:** with `START_FROM_SCRATCH=True`, removes the containers, network and volumes.
# - **Why:** a fresh build must not reuse old nodes; with `False` the running cluster is kept.
# - **How:** `docker compose -f opensearch-cluster.docker-compose.yml down -v` (`check=False`).
# - 📄 [docker compose down](https://docs.docker.com/reference/cli/docker/compose/down/)

# %%
import subprocess

if OPENSEARCH_START_FROM_SCRATCH:
    subprocess.run(
        ["docker", "compose", "-f", "opensearch-cluster.docker-compose.yml", "down", "-v"],
        check=False,
    )
else:
    print("Preserving existing containers and volumes")


# %% [markdown]
# ## 7. Delete the old state
#
# - **What:** with `START_FROM_SCRATCH=True`, empties `mount/`.
# - **Why:** the node data belongs to uid 1000 and the host user cannot always delete it.
# - **How:** `rm -rf` runs as root inside a throwaway `busybox:1.36` container that sees `mount/` as `/target`.
# - 📄 [docker container run](https://docs.docker.com/reference/cli/docker/container/run/)

# %%
def clear_bind_directory(path):
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker", "run", "--rm", "--mount",
            f"type=bind,source={target},target=/target",
            "busybox:1.36", "sh", "-c",
            "find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
        ],
        check=True,
    )

if OPENSEARCH_START_FROM_SCRATCH:
    clear_bind_directory(DOCKER_MOUNTDIR)

# %% [markdown]
# ## 8. Data folders and Compose file
#
# - **What:** prepares each node's `data` folder and `performance-analyzer.properties`, then generates `opensearch-cluster.docker-compose.yml` with three `opensearch:3.4.0` nodes and `opensearch-dashboards:3.4.0` (2 CPUs and 2 GB each, 1 GB Java heap).
# - **Why:** OpenSearch runs as uid 1000 and fails with `AccessDeniedException` if Docker creates the data folder as root; the three nodes must find each other to form one cluster.
# - **How:** a throwaway container runs `chown -R 1000:1000` on each data folder. Nodes get `discovery.seed_hosts` and `cluster.initial_cluster_manager_nodes` with the three names, `bootstrap.memory_lock=true` with an unlimited `memlock`, and `OPENSEARCH_INITIAL_ADMIN_PASSWORD`, which the demo security setup requires; `cluster.routing.allocation.disk.threshold_enabled=false` turns off the disk allocation decider, so a nearly full host disk does not stop shard allocation. The health check accepts any status but `red`; Dashboards starts after the three nodes are healthy.
# - 📄 [OpenSearch 3.4 — Docker](https://docs.opensearch.org/3.4/install-and-configure/install-opensearch/docker/) · [Demo security configuration](https://docs.opensearch.org/3.4/security/configuration/demo-configuration/) · [Cluster settings](https://docs.opensearch.org/3.4/install-and-configure/configuring-opensearch/cluster-settings/) · [Performance Analyzer](https://docs.opensearch.org/3.4/monitoring-your-cluster/pa/index/) · [Cluster health API](https://docs.opensearch.org/3.4/api-reference/cluster-api/cluster-health/)

# %%
import os
import yaml
from IPython.display import Markdown, display

node_cpus = "2.0"
node_memory = "2G"
node_start_heap = "1G"
node_max_heap = "1G"

opensearch_compose_dict = {
    "name": "opensearch-cluster",
    "services": {},
    "networks": {
        "opensearch-cluster": {"name": "opensearch-network", "driver": "bridge"}
    },
}
opensearch_hosts_json = '["' + '","'.join(OPENSEARCH_NODE_INTERNAL_ENDPOINTS) + '"]'

for i in range(OPENSEARCH_TOTAL_NODES):

    node_mount_dir = os.path.join(
        DOCKER_MOUNTDIR,
        OPENSEARCH_NODE_NAMES[i],
    )
    Path(node_mount_dir).mkdir(parents=True, exist_ok=True)
    # Create the data directory before Compose does: a missing bind source is
    # created by the Docker daemon as root, and OpenSearch (uid 1000 in the
    # image) then fails with AccessDeniedException on Linux hosts. The
    # throwaway container hands it to uid 1000 whatever the host user is.
    node_data_dir = Path(node_mount_dir, "data").resolve()
    node_data_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            "docker", "run", "--rm", "--mount",
            f"type=bind,source={node_data_dir},target=/target",
            "busybox:1.36", "chown", "-R", "1000:1000", "/target",
        ],
        check=True,
    )
    with open(
        os.path.join(node_mount_dir, "performance-analyzer.properties"), "w",
        encoding="utf-8", newline="\n",
    ) as f:
        f.write(
            f"""# Performance Analyzer Configuration for {OPENSEARCH_NODE_NAMES[i]}
webservice-bind-host = 0.0.0.0
webservice-listener-port = {OPENSEARCH_NODE_PERF_ANA_PORTS[i]}
metrics-location = /dev/shm/performanceanalyzer/
cleanup-metrics-db-files = true
https-enabled = false
"""
        )

    opensearch_compose_dict["services"][OPENSEARCH_NODE_NAMES[i]] = {
        "image": "opensearchproject/opensearch:3.4.0",
        "container_name": OPENSEARCH_NODE_NAMES[i],
        "environment": [
            f"cluster.name={OPENSEARCH_CLUSTER_NAME}",
            f"node.name={OPENSEARCH_NODE_NAMES[i]}",
            f"discovery.seed_hosts={','.join(OPENSEARCH_NODE_NAMES)}",
            f"cluster.initial_cluster_manager_nodes={','.join(OPENSEARCH_NODE_NAMES)}",
            "cluster.routing.allocation.disk.threshold_enabled=false",
            f"http.port={OPENSEARCH_NODE_REST_API_PORTS[i]}",
            "bootstrap.memory_lock=true",
            f"OPENSEARCH_JAVA_OPTS=-Xms{node_start_heap} -Xmx{node_max_heap}",
            f"OPENSEARCH_INITIAL_ADMIN_PASSWORD={OPENSEARCH_INITIAL_ADMIN_PASSWORD}",
            f"OPENSEARCH_HOSTS={opensearch_hosts_json}",
        ],
        "ulimits": {
            "memlock": {"soft": -1, "hard": -1},
            "nofile": {"soft": 65536, "hard": 65536},
        },
        "volumes": [
            f"{os.path.join(node_mount_dir, 'data')}:{OPENSEARCH_WORKDIR}",
            f"{os.path.join(node_mount_dir, 'performance-analyzer.properties')}:/usr/share/opensearch/config/opensearch-performance-analyzer/performance-analyzer.properties",
        ],
        "networks": ["opensearch-cluster"],
        "hostname": OPENSEARCH_NODE_HOSTNAMES[i],
        "ports": [
            f"{HOST_BIND_IP}:{OPENSEARCH_NODE_REST_API_PORTS[i]}:{OPENSEARCH_NODE_REST_API_PORTS[i]}",
            f"{HOST_BIND_IP}:{OPENSEARCH_NODE_PERF_ANA_PORTS[i]}:{OPENSEARCH_NODE_PERF_ANA_PORTS[i]}",
        ],
        "extra_hosts": [
            f"{DOCKER_INTERNAL_HOST}:host-gateway",
        ],
        "dns": DOCKER_DNS,
        "deploy": {"resources": {"limits": {"cpus": node_cpus, "memory": node_memory}}},
        "depends_on": {
            OPENSEARCH_NODE_NAMES[j]: {"condition": "service_started"}
            for j in range(0, i)
        },
        "healthcheck": {
            "test": [
                "CMD-SHELL",
                f"curl -sf -k -u admin:{OPENSEARCH_INITIAL_ADMIN_PASSWORD} "
                f'https://localhost:{OPENSEARCH_NODE_REST_API_PORTS[i]}/_cluster/health | grep -qv \'"status":"red"\'',
            ],
            "interval": "10s",
            "timeout": "10s",
            "retries": 10,
            "start_period": "30s",
        },
    }

opensearch_compose_dict["services"][OPENSEARCH_DASHBOARDS_NAME] = {
    "image": "opensearchproject/opensearch-dashboards:3.4.0",
    "container_name": OPENSEARCH_DASHBOARDS_NAME,
    "hostname": OPENSEARCH_DASHBOARDS_HOSTNAME,
    "environment": [
        f"OPENSEARCH_HOSTS={opensearch_hosts_json}",
        f"OPENSEARCH_JAVA_OPTS=-Xms{node_start_heap} -Xmx{node_max_heap}",
    ],
    "networks": ["opensearch-cluster"],
    "ports": [
        f"{HOST_BIND_IP}:{OPENSEARCH_DASHBOARD_PORT}:{OPENSEARCH_DASHBOARD_PORT}",
    ],
    "dns": DOCKER_DNS,
    "deploy": {"resources": {"limits": {"cpus": node_cpus, "memory": node_memory}}},
    "depends_on": {
        OPENSEARCH_NODE_NAMES[j]: {"condition": "service_healthy"}
        for j in range(OPENSEARCH_TOTAL_NODES)
    },
}


opensearch_compose_yaml_path = os.path.join(
    LOCALHOST_WORKDIR, "opensearch-cluster.docker-compose.yml"
)
opensearch_compose_yaml_contents = yaml.dump(
    opensearch_compose_dict, default_flow_style=False, sort_keys=False, indent=4
)

with open(opensearch_compose_yaml_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(opensearch_compose_yaml_contents)

print(f"Successfully created: '{os.path.relpath(opensearch_compose_yaml_path)}'")
display(Markdown(f"```yaml\n{opensearch_compose_yaml_contents}\n```"))

# %% [markdown]
# ## 9. Start OpenSearch
#
# - **What:** starts the nodes and Dashboards and waits until the health checks pass.
# - **Why:** the lab notebook needs a cluster that already answers on its REST ports.
# - **How:** `docker compose up -d --wait`.
# - 📄 [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/)

# %%
run_command(["docker", "compose", "-f", "opensearch-cluster.docker-compose.yml", "up", "-d", "--wait"])
