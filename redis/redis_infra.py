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
# # Redis Cluster — infrastructure
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
# - **What:** locates the labs-setup root, changes into `redis/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "redis"
import sys

if str(LABS_ROOT) not in sys.path:
    sys.path.insert(0, str(LABS_ROOT))
from labs_runtime import run_command

os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Cluster settings
#
# - **What:** six nodes `redis-node-1..6` with fixed internal IPs `172.28.0.11-16`, client ports `6381-6386`, cluster-bus ports `16381-16386` and the password `redis`.
# - **Why:** a Redis Cluster needs at least three primaries; with one replica each that is six nodes. Each node publishes on the host, so each needs its own ports.
# - **How:** clients reach `127.0.0.1` (Local) or `redis-node-N.<alias>.<domain>` (VPN).
# - 📄 [Redis — Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)

# %%
REDIS_START_FROM_SCRATCH = START_FROM_SCRATCH
DOCKER_INTERNAL_HOST = "host.docker.internal"
DOCKER_DNS = [VPN_DNS_IP] if NETWORK_MODE == "vpn" else []
HOST_BIND_IP = VPN_HOST_IP if NETWORK_MODE == "vpn" else "127.0.0.1"

REDIS_TOTAL_NODES = 6
REDIS_NODE_NAMES = [f"redis-node-{i+1}" for i in range(REDIS_TOTAL_NODES)]
REDIS_NODE_INTERNAL_IPS = [
    f"172.28.0.{i + 11}" for i in range(REDIS_TOTAL_NODES)
]
def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


REDIS_NODE_CLIENT_HOSTS = [
    "127.0.0.1" if NETWORK_MODE == "local" else vpn_fqdn(name)
    for name in REDIS_NODE_NAMES
]
REDIS_NODE_COMPOSE_HOSTS = [
    name if NETWORK_MODE == "local" else vpn_fqdn(name)
    for name in REDIS_NODE_NAMES
]
REDIS_NODE_PORTS = [6380 + i + 1 for i in range(REDIS_TOTAL_NODES)]
REDIS_NODE_BUS_PORTS = [16380 + i + 1 for i in range(REDIS_TOTAL_NODES)]

REDIS_WORKDIR = "/data"

REDIS_ADMIN_PASSWORD = "redis"
REDIS_DEFAULT_PASSWORD = "redis"
REDIS_INIT_USER = "redis"
REDIS_INIT_PASSWORD = "redis"

# %% [markdown]
# ## 5. Host folder
#
# - **What:** creates `mount/`, with one data folder per node.
# - **Why:** the append-only file and `nodes.conf` survive a container restart.
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
# - **How:** `docker compose -f redis-cluster.docker-compose.yml down -v` (`check=False`).
# - 📄 [docker compose down](https://docs.docker.com/reference/cli/docker/compose/down/)

# %%
import subprocess

if REDIS_START_FROM_SCRATCH:
    subprocess.run(
        ["docker", "compose", "-f", "redis-cluster.docker-compose.yml", "down", "-v"],
        check=False,
    )
else:
    print("Preserving existing containers and volumes")


# %% [markdown]
# ## 7. Delete the old state
#
# - **What:** with `START_FROM_SCRATCH=True`, empties `mount/`.
# - **Why:** each node keeps its cluster membership in `nodes.conf`; a new cluster must start without the old one.
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

if REDIS_START_FROM_SCRATCH:
    clear_bind_directory(DOCKER_MOUNTDIR)

# %% [markdown]
# ## 8. Write the Compose file
#
# - **What:** generates `redis-cluster.docker-compose.yml`: six `redis:8.4.0-bookworm` services on the subnet `172.28.0.0/24`, 0.5 CPU and 512 MB each.
# - **Why:** a node tells clients and other nodes where to reach it; inside Docker it announces its fixed IP, and in VPN mode it also announces its VPN name and asks clients to use that name.
# - **How:** `redis-server` runs with `--cluster-enabled yes`, a password (`--requirepass`, `--masterauth`), an ACL user `redis` with `~* +@all`, `--appendonly yes`, `--cluster-replica-validity-factor 0` (a replica always tries to fail over) and `--cluster-announce-ip/port/bus-port`; VPN mode adds `--cluster-announce-hostname` and `--cluster-preferred-endpoint-type hostname`. The health check is `redis-cli ping`.
# - 📄 [redis.conf 8.4.0 (cluster options)](https://raw.githubusercontent.com/redis/redis/8.4.0/redis.conf) · [Redis — ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/) · [Redis — Persistence (AOF)](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [Compose file — services](https://docs.docker.com/reference/compose-file/services/)

# %%
import os
import yaml
from IPython.display import Markdown, display


REDIS_MEMORY_LIMIT = "512mb"
REDIS_CPU_LIMIT = "0.5"

redis_compose_dict = {
    "name": "redis-cluster",
    "services": {},
    "networks": {
        "redis-cluster": {
            "name": "redis-network",
            "driver": "bridge",
            "ipam": {"config": [{"subnet": "172.28.0.0/24"}]},
        }
    },
}

for i in range(REDIS_TOTAL_NODES):
    cluster_announcement = [
        "--cluster-announce-ip",
        REDIS_NODE_INTERNAL_IPS[i],
    ]
    if NETWORK_MODE == "vpn":
        cluster_announcement.extend(
            [
                "--cluster-announce-hostname",
                vpn_fqdn(REDIS_NODE_NAMES[i]),
                "--cluster-preferred-endpoint-type",
                "hostname",
            ]
        )

    redis_compose_dict["services"][REDIS_NODE_NAMES[i]] = {
        "image": "redis:8.4.0-bookworm",
        "container_name": REDIS_NODE_NAMES[i],
        "hostname": REDIS_NODE_COMPOSE_HOSTS[i],
        "command": [
            "redis-server",
            *["--cluster-enabled", "yes"],
            *["--requirepass", f"{REDIS_DEFAULT_PASSWORD}"],
            *["--masterauth", f"{REDIS_ADMIN_PASSWORD}"],
            *[
                "--user",
                f"{REDIS_INIT_USER}",
                "on",
                f">{REDIS_INIT_PASSWORD}",
                "~*",
                "+@all",
            ],
            *["--cluster-node-timeout", "15000"],
            *["--cluster-config-file", "nodes.conf"],
            *["--cluster-node-timeout", "5000"],
            *["--appendonly", "yes"],
            *["--cluster-replica-validity-factor", "0"],
            *["--port", f"{REDIS_NODE_PORTS[i]}"],
            *["--bind", "0.0.0.0"],
            *["--protected-mode", "no"],
            *cluster_announcement,
            *["--cluster-announce-port", f"{REDIS_NODE_PORTS[i]}"],
            *["--cluster-announce-bus-port", f"{REDIS_NODE_BUS_PORTS[i]}"],
        ],
        "volumes": [
            f"{os.path.join(DOCKER_MOUNTDIR, REDIS_NODE_NAMES[i])}:{REDIS_WORKDIR}"
        ],
        "networks": {
            "redis-cluster": {"ipv4_address": REDIS_NODE_INTERNAL_IPS[i]}
        },
        "ports": [
            f"{HOST_BIND_IP}:{REDIS_NODE_PORTS[i]}:{REDIS_NODE_PORTS[i]}",
            f"{HOST_BIND_IP}:{REDIS_NODE_BUS_PORTS[i]}:{REDIS_NODE_BUS_PORTS[i]}",
        ],
        "dns": DOCKER_DNS,
        "deploy": {
            "resources": {
                "limits": {"cpus": REDIS_CPU_LIMIT, "memory": REDIS_MEMORY_LIMIT}
            }
        },
        "depends_on": {
            REDIS_NODE_NAMES[j]: {"condition": "service_started"} for j in range(0, i)
        },
        "healthcheck": {
            "test": [
                "CMD",
                "redis-cli",
                "-a",
                REDIS_ADMIN_PASSWORD,
                "-p",
                f"{REDIS_NODE_PORTS[i]}",
                "ping",
            ],
            "interval": "10s",
            "timeout": "10s",
            "retries": 10,
            "start_period": "20s",
        },
    }

redis_compose_yaml_path = os.path.join(
    LOCALHOST_WORKDIR, "redis-cluster.docker-compose.yml"
)
redis_compose_yaml_contents = yaml.dump(
    redis_compose_dict, default_flow_style=False, sort_keys=False, indent=4
)

with open(redis_compose_yaml_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(redis_compose_yaml_contents)

print(f"Successfully created: '{os.path.relpath(redis_compose_yaml_path)}'")
display(Markdown(f"```yaml\n{redis_compose_yaml_contents}\n```"))

# %% [markdown]
# ## 9. Start the nodes
#
# - **What:** starts the six nodes and waits until every health check passes.
# - **Why:** the cluster can only be created once every node answers.
# - **How:** `docker compose up -d --wait`.
# - 📄 [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/)

# %%
run_command(["docker", "compose", "-f", "redis-cluster.docker-compose.yml", "up", "-d", "--wait"])

# %% [markdown]
# ## 10. Create the cluster and wait for the replicas
#
# - **What:** joins the six nodes into one cluster with 3 primaries and 3 replicas, then waits until it is healthy and every replica has synchronized.
# - **Why:** clients learn the replicas from `CLUSTER SLOTS`, which lists a replica only after its first sync; the lab expects all six nodes.
# - **How:** `redis-cli --cluster create <6 nodes> --cluster-replicas 1 --cluster-yes` inside `redis-node-1`; then `CLUSTER INFO` must show `cluster_state:ok` and 6 known nodes, and `CLUSTER SLOTS` 3 slot ranges with a primary and a replica each.
# - 📄 [Redis — Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/) · [CLUSTER INFO](https://redis.io/docs/latest/commands/cluster-info/) · [CLUSTER SLOTS](https://redis.io/docs/latest/commands/cluster-slots/)

# %%
nodes_ports = " ".join(
    f"{REDIS_NODE_INTERNAL_IPS[i]}:{REDIS_NODE_PORTS[i]}"
    for i in range(REDIS_TOTAL_NODES)
)

cluster_bootstrap = subprocess.run(
    [
        "docker", "exec", "redis-node-1", "redis-cli",
        "-a", REDIS_ADMIN_PASSWORD,
        "--cluster", "create", *nodes_ports.split(),
        "--cluster-replicas", "1", "--cluster-yes",
    ],
    capture_output=True,
    text=True,
    timeout=120,
    encoding="utf-8",
)
print(cluster_bootstrap.stdout)
assert cluster_bootstrap.returncode == 0, cluster_bootstrap.stderr

import time

cluster_info_command = [
    "docker", "exec", "redis-node-1", "redis-cli",
    "-a", REDIS_ADMIN_PASSWORD, "-p", str(REDIS_NODE_PORTS[0]),
    "cluster", "info",
]
for _ in range(30):
    cluster_info = subprocess.run(
        cluster_info_command,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout
    if "cluster_state:ok" in cluster_info:
        break
    time.sleep(2)
assert "cluster_state:ok" in cluster_info, cluster_info
assert "cluster_known_nodes:6" in cluster_info, cluster_info
print(cluster_info)

# CLUSTER SLOTS lists a replica only after its initial sync finishes, and
# clients discover replicas from that reply, so wait until every slot range
# reports its primary and one replica.
import json

cluster_slots_command = [
    "docker", "exec", "redis-node-1", "redis-cli",
    "-a", REDIS_ADMIN_PASSWORD, "-p", str(REDIS_NODE_PORTS[0]),
    "--no-auth-warning", "--json", "cluster", "slots",
]
for _ in range(60):
    cluster_slots = json.loads(
        subprocess.run(
            cluster_slots_command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        ).stdout
    )
    if len(cluster_slots) == 3 and all(len(r) == 4 for r in cluster_slots):
        break
    time.sleep(2)
assert len(cluster_slots) == 3, cluster_slots
assert all(len(r) == 4 for r in cluster_slots), cluster_slots
print("Replicas synchronized:", [(r[0], r[1], r[3][1]) for r in cluster_slots])
