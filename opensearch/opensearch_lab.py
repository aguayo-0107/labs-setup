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
# # OpenSearch lab — search with opensearch-py
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
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")


# %% [markdown]
# ## 4. Connection constants
#
# - **What:** the three node hosts on ports `9201-9203`, the user `admin` / `OpenSearchP455` and the index name `course-products`.
# - **Why:** they must match what `opensearch_infra` configured.
# - **How:** hosts are `127.0.0.1` (Local) or `opensearch-node-N.<alias>.<domain>` (VPN); `DELETE_INDEX_AT_END=False` keeps the index for exploring.

# %%
OPENSEARCH_NODE_NAMES = [f"opensearch-node-{i}" for i in range(1, 4)]
OPENSEARCH_PORTS = [9201, 9202, 9203]


def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


OPENSEARCH_HOSTS = [
    ("127.0.0.1" if NETWORK_MODE == "local" else vpn_fqdn(name), port)
    for name, port in zip(OPENSEARCH_NODE_NAMES, OPENSEARCH_PORTS)
]
OPENSEARCH_USERNAME = "admin"
OPENSEARCH_PASSWORD = "OpenSearchP455"
OPENSEARCH_INDEX = "course-products"
DELETE_INDEX_AT_END = False


# %% [markdown]
# ## 5. Connect securely to the lab cluster
#
# - **What:** opens an `OpenSearch` client to the three nodes and checks the cluster has 3 nodes and status `yellow` or `green`.
# - **Why:** the cluster uses OpenSearch's demo certificate: TLS stays on, but certificate checks are off because that certificate is self-signed and is only acceptable in this isolated lab.
# - **How:** `use_ssl=True`, `verify_certs=False`, `ssl_assert_hostname=False`, basic auth and gzip (`http_compress=True`); `cluster.health()` and `nodes.info()`.
# - 📄 [opensearch-py 3.0.0 — User guide](https://raw.githubusercontent.com/opensearch-project/opensearch-py/v3.0.0/USER_GUIDE.md) · [Demo security configuration](https://docs.opensearch.org/3.4/security/configuration/demo-configuration/) · [Cluster health API](https://docs.opensearch.org/3.4/api-reference/cluster-api/cluster-health/)

# %%
from opensearchpy import OpenSearch, helpers

client = OpenSearch(
    hosts=[{"host": host, "port": port} for host, port in OPENSEARCH_HOSTS],
    http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
    http_compress=True,
    use_ssl=True,
    verify_certs=False,
    ssl_assert_hostname=False,
    ssl_show_warn=False,
    timeout=30,
)

cluster_health = client.cluster.health()
node_info = client.nodes.info()
node_count = len(node_info["nodes"])
assert node_count == 3, f"Expected 3 nodes, found {node_count}"
assert cluster_health["status"] in {"yellow", "green"}, cluster_health
print(
    f"Cluster {cluster_health['cluster_name']}: "
    f"status={cluster_health['status']}, nodes={node_count}"
)


# %% [markdown]
# ## 6. Create an index with explicit mappings
#
# - **What:** recreates `course-products` with 3 primary shards, 1 replica each, and a fixed type per field.
# - **Why:** three primaries spread the data over the three nodes and a replica protects each one; explicit mappings stop OpenSearch from guessing types.
# - **How:** `name` is `text` (searched word by word) with a `keyword` sub-field (exact value); `category` is `keyword`; `price` `double`, `stock` `integer`, `created_at` `date`.
# - 📄 [Create index](https://docs.opensearch.org/3.4/api-reference/index-apis/create-index/) · [Supported field types](https://docs.opensearch.org/3.4/mappings/supported-field-types/index/) · [Keyword field type](https://docs.opensearch.org/3.4/mappings/supported-field-types/keyword/)

# %%
if client.indices.exists(index=OPENSEARCH_INDEX):
    client.indices.delete(index=OPENSEARCH_INDEX)

index_definition = {
    "settings": {
        "index": {
            "number_of_shards": 3,
            "number_of_replicas": 1,
        }
    },
    "mappings": {
        "properties": {
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "description": {"type": "text"},
            "category": {"type": "keyword"},
            "price": {"type": "double"},
            "stock": {"type": "integer"},
            "created_at": {"type": "date"},
        }
    },
}

created = client.indices.create(index=OPENSEARCH_INDEX, body=index_definition)
assert created["acknowledged"] is True
print(f"Created index: {OPENSEARCH_INDEX}")


# %% [markdown]
# ## 7. Bulk-index a product catalog
#
# - **What:** indexes six products in one request and checks all six are searchable.
# - **Why:** one bulk request instead of six; `refresh` makes the documents visible to search immediately.
# - **How:** `helpers.bulk` with one `index` action per product, using its `id` as `_id`; then `count()` must be 6.
# - 📄 [Bulk API](https://docs.opensearch.org/3.4/api-reference/document-apis/bulk/) · [opensearch-py 3.0.0 — User guide](https://raw.githubusercontent.com/opensearch-project/opensearch-py/v3.0.0/USER_GUIDE.md)

# %%
products = [
    {
        "id": "p-001",
        "name": "Mechanical Keyboard",
        "description": "Compact keyboard with tactile switches",
        "category": "peripherals",
        "price": 129.90,
        "stock": 18,
        "created_at": "2026-08-01T09:00:00Z",
    },
    {
        "id": "p-002",
        "name": "Wireless Mouse",
        "description": "Ergonomic mouse for long work sessions",
        "category": "peripherals",
        "price": 59.50,
        "stock": 42,
        "created_at": "2026-08-02T09:00:00Z",
    },
    {
        "id": "p-003",
        "name": "USB-C Dock",
        "description": "Dock with display, network, and charging ports",
        "category": "connectivity",
        "price": 189.00,
        "stock": 10,
        "created_at": "2026-08-03T09:00:00Z",
    },
    {
        "id": "p-004",
        "name": "27-inch Monitor",
        "description": "High resolution monitor for data analysis",
        "category": "displays",
        "price": 349.99,
        "stock": 7,
        "created_at": "2026-08-04T09:00:00Z",
    },
    {
        "id": "p-005",
        "name": "Portable Monitor",
        "description": "Lightweight secondary monitor with USB-C",
        "category": "displays",
        "price": 229.00,
        "stock": 13,
        "created_at": "2026-08-05T09:00:00Z",
    },
    {
        "id": "p-006",
        "name": "Network Adapter",
        "description": "USB-C adapter for wired gigabit networks",
        "category": "connectivity",
        "price": 39.90,
        "stock": 30,
        "created_at": "2026-08-06T09:00:00Z",
    },
]

actions = [
    {
        "_op_type": "index",
        "_index": OPENSEARCH_INDEX,
        "_id": product["id"],
        "_source": {key: value for key, value in product.items() if key != "id"},
    }
    for product in products
]
indexed_count, errors = helpers.bulk(client, actions, refresh=True)
assert not errors
assert indexed_count == len(products)
assert client.count(index=OPENSEARCH_INDEX)["count"] == len(products)
print(f"Indexed and refreshed {indexed_count} products")


# %% [markdown]
# ## 8. Full-text search
#
# - **What:** searches "monitor data" in `name` and `description` and checks exactly 2 hits.
# - **Why:** full-text fields are split into words, so a query matches documents that contain any of its words.
# - **How:** `multi_match` with `name^2` (a match in the name counts twice); results sorted by score, then by price.
# - 📄 [Multi-match query](https://docs.opensearch.org/3.4/query-dsl/full-text/multi-match/)

# %%
search_response = client.search(
    index=OPENSEARCH_INDEX,
    body={
        "query": {
            "multi_match": {
                "query": "monitor data",
                "fields": ["name^2", "description"],
            }
        },
        "sort": [{"_score": "desc"}, {"price": "asc"}],
    },
)

hits = search_response["hits"]["hits"]
assert len(hits) == 2, hits
for hit in hits:
    print(f"{hit['_id']}: score={hit['_score']:.3f} | {hit['_source']['name']}")


# %% [markdown]
# ## 9. Aggregate by category and average price
#
# - **What:** counts the products per category and averages their price.
# - **Why:** aggregations summarise the data on the server; `size: 0` returns no documents, only the summary.
# - **How:** a `terms` bucket on `category` with an `avg` of `price` inside; the cell checks 2 products per category.
# - 📄 [Terms aggregation](https://docs.opensearch.org/3.4/aggregations/bucket/terms/) · [Average aggregation](https://docs.opensearch.org/3.4/aggregations/metric/average/)

# %%
aggregation_response = client.search(
    index=OPENSEARCH_INDEX,
    body={
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category"},
                "aggs": {"average_price": {"avg": {"field": "price"}}},
            }
        },
    },
)

buckets = aggregation_response["aggregations"]["by_category"]["buckets"]
category_counts = {bucket["key"]: bucket["doc_count"] for bucket in buckets}
assert category_counts == {"connectivity": 2, "displays": 2, "peripherals": 2}
for bucket in buckets:
    print(
        f"{bucket['key']}: count={bucket['doc_count']}, "
        f"average_price={bucket['average_price']['value']:.2f}"
    )


# %% [markdown]
# ## 10. Update and verify one document
#
# - **What:** sets the stock of `p-004` to 5 and reads it back.
# - **Why:** a partial update changes only the given fields.
# - **How:** `update(..., body={"doc": {"stock": 5}}, refresh=True)`, then `get`.
# - 📄 [Update document](https://docs.opensearch.org/3.4/api-reference/document-apis/update-document/)

# %%
client.update(
    index=OPENSEARCH_INDEX,
    id="p-004",
    body={"doc": {"stock": 5}},
    refresh=True,
)
updated = client.get(index=OPENSEARCH_INDEX, id="p-004")
assert updated["_source"]["stock"] == 5
print(f"Updated p-004 stock to {updated['_source']['stock']}")


# %% [markdown]
# ## 11. Inspect shard distribution
#
# - **What:** waits until the index is `green` with 6 started shards, then prints where each shard lives.
# - **Why:** it shows the 3 primaries and 3 replicas spread over at least two nodes; requests go to different nodes, and a node can briefly report an older cluster state, so the cell waits until both checks agree.
# - **How:** up to 30 rounds of `cluster.health(index=...)` and `cat.shards(format="json")`, 2 s apart.
# - 📄 [Cluster health API](https://docs.opensearch.org/3.4/api-reference/cluster-api/cluster-health/) · [CAT shards](https://docs.opensearch.org/3.4/api-reference/cat/cat-shards/)

# %%
import time

# The client spreads requests across nodes, and a node can briefly lag the
# cluster state, so wait until both health and the shard listing agree.
for _ in range(30):
    index_health = client.cluster.health(index=OPENSEARCH_INDEX)
    shards = client.cat.shards(index=OPENSEARCH_INDEX, format="json")
    started_count = sum(shard["state"] == "STARTED" for shard in shards)
    if (
        index_health["status"] == "green"
        and index_health["active_shards"] == 6
        and started_count == 6
    ):
        break
    time.sleep(2)
assert index_health["status"] == "green", index_health
assert index_health["active_shards"] == 6, index_health

started = [shard for shard in shards if shard["state"] == "STARTED"]
started_primaries = [shard for shard in started if shard["prirep"] == "p"]
nodes = {shard["node"] for shard in started}
assert len(started_primaries) == 3, started_primaries
assert len(started) == 6, started
assert len(nodes) >= 2, nodes
for shard in shards:
    print(
        f"shard={shard['shard']} type={shard['prirep']} "
        f"state={shard['state']} node={shard['node']}"
    )


# %% [markdown]
# ## 12. Optional cleanup
#
# - **What:** deletes the index only if `DELETE_INDEX_AT_END=True`, then closes the client.
# - **Why:** by default the index stays so it can be explored in Dashboards (`5601`).
# - **How:** `indices.delete(index=...)`.
# - 📄 [opensearch-py 3.0.0 — User guide](https://raw.githubusercontent.com/opensearch-project/opensearch-py/v3.0.0/USER_GUIDE.md)

# %%
if DELETE_INDEX_AT_END:
    deleted = client.indices.delete(index=OPENSEARCH_INDEX)
    assert deleted["acknowledged"] is True
    print(f"Deleted index: {OPENSEARCH_INDEX}")
else:
    print(f"Index retained for exploration: {OPENSEARCH_INDEX}")

client.close()

