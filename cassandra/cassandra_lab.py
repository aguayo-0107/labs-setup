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
# # Cassandra lab — CQL and cqlengine from Python
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
# - **What:** locates the labs-setup root, changes into `cassandra/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "cassandra"
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Cluster constants
#
# - **What:** the node names, the CQL ports `9041-9043` and the host the client uses for each node.
# - **Why:** they must match what `cassandra_infra` published, or the driver cannot reach the nodes.
# - **How:** `127.0.0.1` in Local mode, `cassandra-node-N.<alias>.<domain>` in VPN mode; user and password are the defaults `cassandra`/`cassandra`.
# - 📄 [Cassandra 5.0 — Security](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/security.html)

# %%
CASSANDRA_START_FROM_SCRATCH = False
DOCKER_INTERNAL_HOST = "host.docker.internal"

CASSANDRA_CLUSTER_NAME = "cassandra-cluster"
CASSANDRA_TOTAL_NODES = 3

CASSANDRA_NODE_NAMES = [f"cassandra-node-{i+1}" for i in range(CASSANDRA_TOTAL_NODES)]
def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


CASSANDRA_NODE_CLIENT_HOSTS = [
    "127.0.0.1" if NETWORK_MODE == "local" else vpn_fqdn(name)
    for name in CASSANDRA_NODE_NAMES
]
CASSANDRA_NODE_GOSSIP_PORTS = [7000 + (i + 1) for i in range(CASSANDRA_TOTAL_NODES)]
CASSANDRA_NODE_RPC_PORTS = [9040 + (i + 1) for i in range(CASSANDRA_TOTAL_NODES)]
CASSANDRA_NODE_SSL_GOSSIP_PORTS = [7500 + (i + 1) for i in range(CASSANDRA_TOTAL_NODES)]
CASSANDRA_NODE_JMX_PORTS = [7200 + (i + 1) for i in range(0, CASSANDRA_TOTAL_NODES)]

CASSANDRA_CA_CERT_PASSWORD = "cassandra_cluster_ca_cert_passowrd"
CASSANDRA_NODE_CERT_PASSWORD = "cassandra_cluster_cert_passowrd"
CASSANDRA_INIT_USER = "cassandra"
CASSANDRA_INIT_PASSWORD = "cassandra"

CASSANDRA_WORKDIR = "/var/lib/cassandra"

# %% [markdown]
# ## 5. Paths and cqlengine flag
#
# - **What:** defines `mount/` and `cluster_certs/` and sets `CQLENG_ALLOW_SCHEMA_MANAGEMENT`.
# - **Why:** cqlengine warns before `sync_table` changes a schema unless this variable is set; section 17 uses `sync_table`.
# - **How:** `os.environ.setdefault`, so a value already set outside the notebook is kept.
# - 📄 [`cqlengine.management` source](https://github.com/apache/cassandra-python-driver/blob/3.30.1/cassandra/cqlengine/management.py)

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = f"{os.path.join(os.path.relpath(Path.cwd()))}"
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")
CASSANDRA_LOCALHOST_CLUSTER_CA_CERTDIR = os.path.join(LOCALHOST_WORKDIR, "cluster_certs")

mount_path = Path(DOCKER_MOUNTDIR)
mount_path.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CQLENG_ALLOW_SCHEMA_MANAGEMENT", "True")

# %% [markdown]
# ## 6. Connect to the cluster
#
# - **What:** opens a driver `Session` against the three nodes with user and password.
# - **Why:** every later cell sends its CQL through this session.
# - **How:** `PlainTextAuthProvider` logs in; the custom endpoint factory maps each node's CQL port to the client host, because the nodes announce container addresses the host cannot reach. The cell asserts 3 nodes, all up, at the expected endpoints.
# - 📄 [cassandra-driver 3.30.1 — Getting started](https://github.com/apache/cassandra-python-driver/blob/3.30.1/docs/getting_started.rst) · [`DefaultEndPointFactory` source](https://github.com/apache/cassandra-python-driver/blob/3.30.1/cassandra/connection.py)

# %%
from cassandra.cluster import Cluster
from cassandra.connection import DefaultEndPoint, DefaultEndPointFactory
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import dict_factory


class ClientEndPointFactory(DefaultEndPointFactory):
    def __init__(self, hosts_by_port):
        super().__init__()
        self.hosts_by_port = hosts_by_port

    def create(self, row):
        port = row.get("native_port")
        if port not in self.hosts_by_port:
            return super().create(row)
        return DefaultEndPoint(self.hosts_by_port[port], port)


cassandra_nodes = [
    DefaultEndPoint(CASSANDRA_NODE_CLIENT_HOSTS[j], CASSANDRA_NODE_RPC_PORTS[j])
    for j in range(CASSANDRA_TOTAL_NODES)
]
cassandra_endpoints = [
    f"{cassandra_node.address}:{cassandra_node.port}"
    for cassandra_node in cassandra_nodes
]
print(f"🔗 Connecting to: {cassandra_endpoints}")
print(f"JDBC URL: jdbc:cassandra://{','.join(cassandra_endpoints)}")

auth_provider = PlainTextAuthProvider(
    username=CASSANDRA_INIT_USER, password=CASSANDRA_INIT_PASSWORD
)
endpoint_factory = ClientEndPointFactory(
    dict(zip(CASSANDRA_NODE_RPC_PORTS, CASSANDRA_NODE_CLIENT_HOSTS))
)
cluster = Cluster(
    contact_points=cassandra_nodes,
    auth_provider=auth_provider,
    endpoint_factory=endpoint_factory,
)

session = cluster.connect()
session.row_factory = dict_factory
print(f"✅ Connected to cluster: {cluster.metadata.cluster_name}")
print(f"🌐 Nodes found: {len(cluster.metadata.all_hosts())}")
assert cluster.metadata.cluster_name == CASSANDRA_CLUSTER_NAME
assert len(cluster.metadata.all_hosts()) == CASSANDRA_TOTAL_NODES
discovered_endpoints = {
    (host.endpoint.address, host.endpoint.port)
    for host in cluster.metadata.all_hosts()
}
expected_endpoints = set(zip(CASSANDRA_NODE_CLIENT_HOSTS, CASSANDRA_NODE_RPC_PORTS))
assert discovered_endpoints == expected_endpoints, discovered_endpoints
assert all(host.is_up for host in cluster.metadata.all_hosts())

# %% [markdown]
# ## 7. Show the cluster nodes
#
# - **What:** prints a table with the hosts the driver discovered.
# - **Why:** it shows that one connection learns the whole ring, not just the contact points.
# - **How:** `cluster.metadata.all_hosts()` rendered with pandas, all rows and columns visible.
# - 📄 [pandas — Options and settings](https://pandas.pydata.org/docs/user_guide/options.html)

# %%
import pprint
import pandas as pd
from IPython.display import display

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option('display.max_colwidth', None)
pd.options.display.html.use_mathjax = True
pd.options.display.html.border = 1
pd.options.display.html.table_schema = False
pd.options.display.expand_frame_repr = True

display(
    pd.DataFrame(
        [cassandra_host.__dict__ for cassandra_host in cluster.metadata.all_hosts()]
    )
    .sort_index()
    .transpose()
)

# %% [markdown]
# ## 8. System tables (optional)
#
# - **What:** commented queries on `system.peers_v2` and `system.local`.
# - **Why:** these tables are where the driver reads the ring topology.
# - **How:** uncomment to print every column of each row.

# %%
# from cassandra.cluster import ResultSet

# peers_v2: ResultSet = session.execute("SELECT * FROM system.peers_v2")
# locals: ResultSet = session.execute("SELECT * FROM system.local")

# for peer_v2 in peers_v2:
#     print(" | ".join([f"{col}: {peer_v2[col]}" for col in peers_v2.column_names]))
# print("=" * 100)
# for local in locals:
#     print(" | ".join([f"{col}: {local[col]}" for col in locals.column_names]))
# print("=" * 100)

# %% [markdown]
# ## 9. Drop the keyspace (only when starting over)
#
# - **What:** drops `generic_analytics` if `CASSANDRA_START_FROM_SCRATCH` is `True`.
# - **Why:** the lab runs on top of earlier data; the default `False` keeps it.
# - **How:** `DROP KEYSPACE IF EXISTS`.
# - 📄 [CQL 5.0 — Data definition](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/ddl.html)

# %%
keyspace_name = "generic_analytics"
if CASSANDRA_START_FROM_SCRATCH:
    session.execute(f"DROP KEYSPACE IF EXISTS {keyspace_name}")

# %% [markdown]
# ## 10. Keyspace and table
#
# - **What:** creates the `generic_analytics` keyspace with 3 replicas and the `user_metrics` table.
# - **Why:** the partition key `city` decides which nodes store a row; the clustering column `user_id` orders rows inside a city.
# - **How:** `NetworkTopologyStrategy` with `'dc1': 3`, so every node holds a copy; `PRIMARY KEY (city, user_id)`.
# - 📄 [CQL 5.0 — Data definition](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/ddl.html)

# %%
keyspace_name = "generic_analytics"
session.execute(
    f"""
CREATE KEYSPACE IF NOT EXISTS {keyspace_name} 
WITH replication = {{
    'class': 'NetworkTopologyStrategy', 
    'dc1': {CASSANDRA_TOTAL_NODES}
}}
"""
)
session.set_keyspace(keyspace_name)

# Create Table
# Partition Key: city (distributes data)
# Clustering Column: user_id (sorts data within city)
session.execute(
    """
CREATE TABLE IF NOT EXISTS user_metrics (
    city text,
    user_id uuid,
    username text,
    session_duration int,
    last_access timestamp,
    PRIMARY KEY (city, user_id)
);
"""
)

# %% [markdown]
# ## 11. Fake data generator
#
# - **What:** creates a `Faker` instance.
# - **Why:** realistic cities, user names and numbers without real personal data.
# - **How:** `Faker()` with the default locale.
# - 📄 [Faker](https://faker.readthedocs.io/en/master/)

# %%
from faker import Faker

fake = Faker()

# %% [markdown]
# ## 12. Batch insert
#
# - **What:** inserts 200 rows in one `LOGGED` batch at consistency `QUORUM`.
# - **Why:** a prepared statement is parsed once and reused; a logged batch is applied completely or not at all; `QUORUM` needs 2 of 3 replicas.
# - **How:** `session.prepare` with `?` markers, `BatchStatement(batch_type=BatchType.LOGGED)`, then one `session.execute(batch)`.
# - 📄 [`BatchStatement` API](https://github.com/apache/cassandra-python-driver/blob/3.30.1/docs/api/cassandra/query.rst) · [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html) · [Cassandra 5.0 — Consistency levels](https://cassandra.apache.org/doc/5.0/cassandra/architecture/dynamo.html)

# %%
import uuid
from datetime import datetime
from cassandra.query import SimpleStatement
from cassandra import ConsistencyLevel
from cassandra.query import BatchStatement, BatchType

# 1. Prepare your statement outside the loop
query = """
INSERT INTO user_metrics (city, user_id, username, session_duration, last_access)
VALUES (?, ?, ?, ?, ?)
"""
prepared = session.prepare(query)
# prepared.consistency_level = ConsistencyLevel.QUORUM
# statement = SimpleStatement(query, consistency_level=ConsistencyLevel.QUORUM)

# 2. Create the Batch object
# LOGGED ensures atomicity but adds disk overhead, UNLOGGED is faster
batch_records = 200
batch = BatchStatement(batch_type=BatchType.LOGGED)
batch.consistency_level = ConsistencyLevel.QUORUM
print(f"Preparing batch of {batch_records} records...")
for _ in range(batch_records):
    batch.add(
        prepared,
        (
            fake.city(),
            uuid.uuid4(),
            fake.user_name(),
            fake.random_int(min=1, max=3600),
            datetime.now(),
        ),
    )

# 3. Execute the entire batch at once
session.execute(batch)
print("Batch successfully committed to the cluster.")

# %% [markdown]
# ## 13. Count the rows
#
# - **What:** counts the rows of `user_metrics` and checks there are at least 200.
# - **Why:** it confirms the batch was written.
# - **How:** `SELECT count(*)`; the assertion stops the notebook if rows are missing.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
from cassandra.cluster import ResultSet
from typing import cast

count_row = cast(
    ResultSet, session.execute("SELECT count(*) FROM user_metrics")
).one()
row_count = next(iter(count_row.values()))
assert row_count >= batch_records, row_count
print(f"Rows stored: {row_count}")

# %% [markdown]
# ## 14. Read rows
#
# - **What:** prints up to 100 rows.
# - **Why:** a `SELECT` without a `WHERE` reads from every partition.
# - **How:** `SELECT * FROM user_metrics LIMIT 100`.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
from cassandra.cluster import ResultSet

rows: ResultSet = session.execute("SELECT * FROM user_metrics LIMIT 100")
for row in rows.current_rows:
    print(row)

# %% [markdown]
# ## 15. Distinct partition keys
#
# - **What:** lists the distinct `city` values.
# - **Why:** each city is one partition, the unit Cassandra distributes across the nodes.
# - **How:** `SELECT DISTINCT city`, allowed because `city` is the partition key.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
from cassandra.cluster import ResultSet

rows: ResultSet = session.execute("SELECT DISTINCT city FROM user_metrics", [])
for row in rows.current_rows:
    print(row)

# %% [markdown]
# ## 16. Which nodes store a row
#
# - **What:** picks a row from a random token and asks the driver which nodes hold its replicas.
# - **Why:** with replication factor 3 on 3 nodes, every node must hold it; the cell asserts that.
# - **How:** `token(city) >= <random>` finds a row, `prepare(...).bind(...)` gives its routing key, `cluster.metadata.get_replicas` returns the nodes.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html) · [`Metadata.get_replicas` source](https://github.com/apache/cassandra-python-driver/blob/3.30.1/cassandra/metadata.py)

# %%
import random
import pprint

random_token = random.randint(-9223372036854775808, 9223372036854775807)
query = "SELECT * FROM user_metrics WHERE token(city) >= %s LIMIT 1"
row: dict = cast(ResultSet, session.execute(query, [random_token])).one()
print(f"Random user_metric: {pprint.pformat(row)}")

prepared = session.prepare("SELECT * FROM user_metrics WHERE city=? AND user_id=?")
bound = prepared.bind([row['city'], row['user_id']])
routing_key = bound.routing_key
nodes = cluster.metadata.get_replicas(keyspace_name, routing_key)
assert len(nodes) == CASSANDRA_TOTAL_NODES, nodes

print(f"Nodes storing '{row['city']}':")
for node in nodes:
    print(f" - Host: {node.address}, Gossip Port: {node.broadcast_port}")

# %% [markdown]
# ## 17. cqlengine model
#
# - **What:** maps `user_metrics` to the Python class `UserMetrics` and syncs the table.
# - **Why:** an object mapper writes and reads rows as objects instead of CQL strings.
# - **How:** `city` is the partition key, `user_id` the clustering key; `index=True` on `username` adds a secondary index; `create_keyspace_network_topology` and `sync_table` create what is missing.
# - 📄 [cqlengine — Models](https://github.com/apache/cassandra-python-driver/blob/3.30.1/docs/cqlengine/models.rst)

# %%
from typing import cast
from cassandra.cqlengine import columns
from cassandra.cqlengine.query import ModelQuerySet
from cassandra.cqlengine.models import Model
from cassandra.cqlengine.management import sync_table, create_keyspace_network_topology
from cassandra.cqlengine import connection

# 1. Connect the engine
connection.set_session(session)


# 2. Define your "Generic" Model
class UserMetrics(Model):
    __table_name__ = "user_metrics"

    # FIRST primary_key=True is the Partition Key
    # city = columns.Text(primary_key=True)
    city = columns.Text(primary_key=True, partition_key=True)

    # SECOND primary_key=True is the Clustering Key
    user_id = columns.UUID(primary_key=True, default=uuid.uuid4)

    # Attributes (Data)
    username = columns.Text(index=True)
    session_duration = columns.Integer()
    last_access = columns.DateTime()


# 3. Create Keyspace and Sync Table (Equivalent to CREATE TABLE)
create_keyspace_network_topology(keyspace_name, {"dc1": CASSANDRA_TOTAL_NODES})
sync_table(UserMetrics)

# %% [markdown]
# ## 18. Create and filter with the model
#
# - **What:** saves one object and reads the rows with `session_duration >= 120`.
# - **Why:** it is the object-mapper version of `INSERT` and `SELECT ... WHERE`.
# - **How:** `UserMetrics.create(...)`; the filter is on a non-key column, so it needs `allow_filtering()`, which scans every partition.
# - 📄 [cqlengine — Models](https://github.com/apache/cassandra-python-driver/blob/3.30.1/docs/cqlengine/models.rst) · [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
# 4. Use it like an ORM
# Create UserMetrics
new_metric: UserMetrics = UserMetrics.create(
    city=fake.city(),
    username=fake.name(),
    session_duration=120,
    last_access=datetime.now(),
)
new_metric.save()
print(f"Saved user_metris: {new_metric}")


# 5. Query UserMetrics
user_metrics = (
    cast(ModelQuerySet, UserMetrics.objects())
    .filter(session_duration__gte=120)
    .allow_filtering() # Non-recommended, used for non-primary key queries
)
for user_metric in user_metrics:
    print(f"Query user_metris: {user_metric}")

# %% [markdown]
# ## 19. Insert with a time to live
#
# - **What:** inserts one row that expires after 86 400 seconds (one day).
# - **Why:** Cassandra deletes expired data by itself.
# - **How:** `UserMetrics.ttl(86400).create(...)`, which sends `INSERT ... USING TTL 86400`.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
from typing import cast

cast(ModelQuerySet, UserMetrics.ttl(86400)).create(
    city=fake.city(),
    username=fake.user_name(),
    session_duration=fake.random_int(10, 1000),
    last_access=fake.date_time(),
)

# %% [markdown]
# ## 20. Batch with the model
#
# - **What:** inserts 100 objects in one batch.
# - **Why:** it groups the inserts into one request, like section 12.
# - **How:** the `with BatchQuery() as b:` block sends the batch when it ends.
# - 📄 [cqlengine — Batch queries](https://github.com/apache/cassandra-python-driver/blob/3.30.1/docs/cqlengine/batches.rst)

# %%
from typing import cast
from cassandra.cqlengine.query import BatchQuery
from cassandra.cqlengine.query import ModelQuerySet

with BatchQuery() as b:
    for _ in range(100):
        cast(ModelQuerySet, UserMetrics.batch(b)).create(
            city=fake.city(),
            username=fake.user_name(),
            session_duration=fake.random_int(10, 1000),
            last_access=fake.date_time(),
        )

# %% [markdown]
# ## 21. Delete and close
#
# - **What:** deletes the rows with `session_duration >= 120` and closes the connection.
# - **Why:** it completes create, read and delete; closing frees the driver's connections and threads.
# - **How:** `delete()` on each object found by the filter, then `session.shutdown()` and `cluster.shutdown()`.
# - 📄 [CQL 5.0 — Data manipulation](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)

# %%
user_metrics = (
    cast(ModelQuerySet, UserMetrics.objects())
    .filter(session_duration__gte=120)
    .allow_filtering() # Non-recommended, used for non-primary key queries
)
for user_metric in user_metrics:
    user_metric.delete()
    print(f"Delete user_metris: {user_metric}")

session.shutdown()
cluster.shutdown()

# %% [markdown]
# ## 22. Tombstones (optional)
#
# - **What:** a commented `ALTER TABLE ... WITH gc_grace_seconds = 10`.
# - **Why:** a delete writes a tombstone that compaction only removes after `gc_grace_seconds` (default 10 days).
# - **How:** uncomment to shorten that wait on this table only.
# - 📄 [CQL 5.0 — Data definition](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/ddl.html)

# %%
# from cassandra.cqlengine import connection

# # This isn't a compaction, but it forces RAM data to disk so the background compaction process can see it.
# connection.execute(f"ALTER TABLE {keyspace_name}.user_metrics WITH gc_grace_seconds = 10")
