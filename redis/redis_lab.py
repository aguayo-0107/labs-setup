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
# # Redis Cluster lab — redis-py
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
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Cluster constants
#
# - **What:** the six node names, their internal IPs `172.28.0.11-16`, client ports `6381-6386` and the ACL user `redis` / password `redis`.
# - **Why:** they must match what `redis_infra` configured.
# - **How:** client hosts are `127.0.0.1` (Local) or `redis-node-N.<alias>.<domain>` (VPN).

# %%
DOCKER_INTERNAL_HOST = "host.docker.internal"

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
REDIS_NODE_PORTS = [6380 + i + 1 for i in range(REDIS_TOTAL_NODES)]
REDIS_NODE_BUS_PORTS = [16380 + i + 1 for i in range(REDIS_TOTAL_NODES)]

REDIS_WORKDIR = "/data"

REDIS_ADMIN_PASSWORD = "redis"
REDIS_DEFAULT_PASSWORD = "redis"
REDIS_INIT_USER = "redis"
REDIS_INIT_PASSWORD = "redis"

# %% [markdown]
# ## 5. Paths
#
# - **What:** defines and creates `mount/` relative to the module folder.
# - **Why:** kept for symmetry with the infrastructure notebook; the lab does not write there.
# - **How:** `os.path.join` and `Path.mkdir(exist_ok=True)`.

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = f"{os.path.join(os.path.relpath(Path.cwd()))}"
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")

mount_path = Path(DOCKER_MOUNTDIR)
mount_path.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## 6. Connect to the cluster
#
# - **What:** opens a `RedisCluster` client from the six nodes, checks the cluster and writes and reads one test key.
# - **Why:** a cluster client sends each key to the node that owns its hash slot; in Local mode the nodes announce Docker IPs the host cannot reach.
# - **How:** `address_remap` turns each announced `172.28.0.x` into `127.0.0.1` (Local only); with `RANDOM_REPLICA` reads go to a random replica of the key's slot, so the client also learns the 3 replicas; `require_full_coverage=True` refuses a cluster with unassigned slots. The cell asserts state `ok`, 16 384 slots, 6 nodes, 3 primaries, 3 replicas and the expected endpoints.
# - 📄 [redis-py 8.1.0 — Connections (`RedisCluster`)](https://redis.readthedocs.io/en/v8.1.0/connections.html) · [redis-py 8.1.0 — Clustering](https://redis.readthedocs.io/en/v8.1.0/clustering.html) · [Redis — Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)

# %%
import pprint
from redis.cluster import RedisCluster, ClusterNode
from redis.cluster import LoadBalancingStrategy
from redis import Redis

redis_nodes = [
    ClusterNode(REDIS_NODE_CLIENT_HOSTS[i], REDIS_NODE_PORTS[i])
    for i in range(0, REDIS_TOTAL_NODES)
]
pprint.pprint(f"🔗 Connecting to: {redis_nodes}")
redis_endpoints = ",".join(f"{node.host}:{node.port}" for node in redis_nodes)
print(
    f"🔗 Connection String: redis://{REDIS_INIT_USER}:{REDIS_INIT_PASSWORD}:{redis_endpoints}"
)

def redis_address_remap(address):
    host, port = address
    if NETWORK_MODE == "local" and host in REDIS_NODE_INTERNAL_IPS:
        return "127.0.0.1", port
    return address

redis_cluster = RedisCluster(
    startup_nodes=redis_nodes,
    username=REDIS_INIT_USER,
    password=REDIS_INIT_PASSWORD,
    decode_responses=True,
    load_balancing_strategy=LoadBalancingStrategy.RANDOM_REPLICA,
    require_full_coverage=True,
    address_remap=redis_address_remap if NETWORK_MODE == "local" else None,
)
cluster_details = redis_cluster.cluster_info()
cluster_status = cluster_details["cluster_state"]
cluster_nodes = Redis(
    host=redis_nodes[0].host,
    port=redis_nodes[0].port,
    username=REDIS_INIT_USER,
    password=REDIS_INIT_PASSWORD,
    decode_responses=True,
).execute_command("CLUSTER NODES")
nodes_count = len(cluster_nodes)
primaries = list(redis_cluster.get_primaries())
discovered_endpoints = {
    (node.host, node.port) for node in redis_cluster.get_nodes()
}
expected_endpoints = set(zip(REDIS_NODE_CLIENT_HOSTS, REDIS_NODE_PORTS))
assert cluster_status == "ok", cluster_details
assert int(cluster_details["cluster_slots_assigned"]) == 16384, cluster_details
assert nodes_count == REDIS_TOTAL_NODES, nodes_count
assert len(primaries) == 3, primaries
# With a load-balancing strategy configured, redis-py also discovers the
# replicas, so the client knows every node: 3 primaries and 3 replicas.
replicas = [
    node for node in redis_cluster.get_nodes() if node.server_type == "replica"
]
assert len(replicas) == REDIS_TOTAL_NODES - len(primaries), replicas
assert discovered_endpoints == expected_endpoints, discovered_endpoints
validation_key = "network-mode-validation"
validation_value = "ok"
assert redis_cluster.set(validation_key, validation_value)
assert redis_cluster.get(validation_key) == validation_value
print("✅ Cluster connected")
print(f"🟢 Cluster State: {cluster_status.upper()}")
print(f"🌐 Nodes Discovered: {nodes_count}; primaries={len(primaries)}")

# %% [markdown]
# ## 7. Table display settings
#
# - **What:** sets pandas to show every row, column and full cell text.
# - **Why:** the next cells print wide tables of cluster details.
# - **How:** `pd.set_option(...)` for rows, columns and column width.
# - 📄 [pandas — Options and settings](https://pandas.pydata.org/docs/user_guide/options.html)

# %%
import pandas as pd
from IPython.display import display

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option('display.max_colwidth', None)
pd.options.display.html.use_mathjax = True
pd.options.display.html.border = 1
pd.options.display.html.table_schema = False
pd.options.display.expand_frame_repr = True

# %% [markdown]
# ## 8. Per-node information
#
# - **What:** connects to each node on its own and shows its `CLUSTER INFO` and its full configuration side by side.
# - **Why:** every node reports its own view, so the six columns can be compared.
# - **How:** a plain `Redis` client per node, `CLUSTER INFO` and `CONFIG GET`, each list shown as a transposed DataFrame.
# - 📄 [CLUSTER INFO](https://redis.io/docs/latest/commands/cluster-info/)

# %%
from redis import Redis
import pandas as pd

cluster_info = []
config_get = []
for i in range(REDIS_TOTAL_NODES):
    redis = Redis(
        host=REDIS_NODE_CLIENT_HOSTS[i],
        port=REDIS_NODE_PORTS[i],
        username=REDIS_INIT_USER,
        password=REDIS_INIT_PASSWORD,
        decode_responses=True,
    )
    cluster_info.append(redis.execute_command("CLUSTER INFO"))
    config_get.append(redis.config_get())

display(pd.DataFrame(cluster_info).transpose())
display(pd.DataFrame(config_get).transpose())

# %% [markdown]
# ## 9. Cluster topology
#
# - **What:** shows `CLUSTER NODES`: every node's id, role, primary and slot ranges.
# - **Why:** it is the cluster's own description of which node owns which slots.
# - **How:** `redis_cluster.execute_command("CLUSTER NODES")` rendered as a table.
# - 📄 [CLUSTER NODES](https://redis.io/docs/latest/commands/cluster-nodes/)

# %%
import pprint
import pandas as pd
from IPython.display import display

try:
    print("🛰️ Cluster Nodes View")
    display(
        pd.DataFrame(redis_cluster.execute_command("CLUSTER NODES"))
        .transpose()
        .sort_index()
        .transpose()
        .sort_index()
    )
except Exception as e:
    pprint.pprint(f"Error checking survivors: {e}")

# %% [markdown]
# ## 10. Where the reads go
#
# - **What:** resets the command counters, writes 10 keys, runs 1 000 `GET`s and prints how many `GET`s each node served.
# - **Why:** writes go to the primary that owns the key; with `RANDOM_REPLICA` reads go to a replica of that primary (each has one), so the replicas should show the `GET`s.
# - **How:** `CONFIG RESETSTAT` on every node, then `INFO commandstats` → `cmdstat_get.calls`. The loop reads `test_keys[i % REDIS_TOTAL_NODES]`, so only the first 6 of the 10 keys are read.
# - 📄 [CONFIG RESETSTAT](https://redis.io/docs/latest/commands/config-resetstat/) · [INFO (`commandstats`)](https://redis.io/docs/latest/commands/info/) · [redis-py 8.1.0 — Clustering](https://redis.readthedocs.io/en/v8.1.0/clustering.html)

# %%
import uuid
from typing import cast
from redis import Redis

# 1. Reset statistics on all nodes
print("Emptying stats on all nodes...")
# for node in redis_cluster.get_nodes():
for node in redis_nodes:
    redis = Redis(
        host=node.host,
        port=node.port,
        username=REDIS_INIT_USER,
        password=REDIS_INIT_PASSWORD,
        decode_responses=True,
    )
    redis.config_resetstat()

# 2. Perform a burst of reads on multiple keys
print("Performing 1000 reads across 10 keys...")
test_keys = [f"{uuid.uuid4()}" for i in range(10)]
for k in test_keys:
    redis_cluster.set(k, str(uuid.uuid4()))  # Ensure keys exist
for i in range(1000):
    redis_cluster.get(test_keys[i % REDIS_TOTAL_NODES])

# 3. Check who actually processed the 'GET' command
print("\n📊 ACTUAL Execution Stats (From Redis Engines)")
for node in redis_cluster.get_nodes():
    node = cast(ClusterNode, node)
    redis = Redis(
        host=node.host,
        port=node.port,
        username=REDIS_INIT_USER,
        password=REDIS_INIT_PASSWORD,
        decode_responses=True,
    )
    role = redis.info("replication")["role"]
    stats = redis.info("commandstats")
    get_calls = stats.get("cmdstat_get", {}).get("calls", 0)

    if get_calls > 0:
        print(f"✅ Node {node.port} ({role.upper()}): {get_calls} GETs handled")
    else:
        print(f"❌ Node {node.port} ({role.upper()}): 0 GETs handled")

# %% [markdown]
# ## 11. Clean up
#
# - **What:** deletes every key on the three primaries and closes the cluster client.
# - **Why:** replicas copy their primary, so flushing the primaries empties the whole cluster.
# - **How:** `FLUSHALL` on each node returned by `get_primaries()`, then `redis_cluster.close()`.
# - 📄 [FLUSHALL](https://redis.io/docs/latest/commands/flushall/)

# %%
# Flushes all in every primary node
for node in redis_cluster.get_primaries():
    node = cast(ClusterNode, node)
    redis = Redis(
        host=node.host,
        port=node.port,
        username=REDIS_INIT_USER,
        password=REDIS_INIT_PASSWORD,
        decode_responses=True,
    )
    redis.flushall()

redis_cluster.close()

# %% [markdown]
# ## 12. Watch a failover (optional)
#
# - **What:** commented loop that prints any `CLUSTER NODES` line marked `fail` or `handshake` every 2 s.
# - **Why:** stop a primary container by hand and watch its replica take over.
# - **How:** uncomment and run; stop it with the notebook's interrupt button.
# - 📄 [CLUSTER NODES](https://redis.io/docs/latest/commands/cluster-nodes/)

# %%
# import time
# from redis import Redis

# idx = 4

# master_node = Redis(
#     host=REDIS_NODE_CLIENT_HOSTS[idx],
#     port=REDIS_NODE_PORTS[idx],
#     username=REDIS_INIT_USER,
#     password=REDIS_INIT_PASSWORD,
#     decode_responses=True,
# )

# print("👀 Monitoring Cluster for Failover Events... (Kill your master now)")
# while True:
#     nodes = master_node.execute_command("CLUSTER NODES")
#     # Look for the 'fail' flag or 'failover' state
#     for line in str(nodes).split("\n"):
#         if "fail" in line or "handshake" in line:
#             print(f"⏰ {time.strftime('%H:%M:%S')} | Event Detected: {line}...")
#             break
#     time.sleep(2)

# %% [markdown]
# ## 13. Force a failover (optional)
#
# - **What:** commented `CLUSTER FAILOVER TAKEOVER` on a replica, then a client refresh.
# - **Why:** `TAKEOVER` promotes the replica without the agreement of its primary or of the other primaries.
# - **How:** uncomment and run; `nodes_manager.initialize()` makes the client reload the topology.
# - 📄 [CLUSTER FAILOVER](https://redis.io/docs/latest/commands/cluster-failover/)

# %%
# from redis import Redis

# idx = 4

# replica = Redis(
#     host=REDIS_NODE_CLIENT_HOSTS[idx],
#     port=REDIS_NODE_PORTS[idx],
#     username=REDIS_INIT_USER,
#     password=REDIS_INIT_PASSWORD,
#     decode_responses=True,
# )

# try:
#     print(
#         f"🚀 Attempting foredis_clustered takeover on port {REDIS_NODE_PORTS[idx]}..."
#     )
#     # 'TAKEOVER' is the aggressive version of failover
#     replica.execute_command("CLUSTER FAILOVER TAKEOVER")
#     print("✅ Success! The replica has promoted itself to MASTER.")
#     redis_cluster.nodes_manager.initialize()
#     print("✅ Success! The cluster has been initialized.")
# except Exception as e:
#     print(f"❌ Manual takeover failed: {e}")
#     print("Check if the Replica can actually 'see' the other Masters.")
