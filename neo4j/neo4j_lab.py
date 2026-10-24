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
# # Neo4j lab — Cypher from Python
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
# - **What:** locates the labs-setup root, changes into `neo4j/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "neo4j"
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Connection constants
#
# - **What:** the Bolt port `7687`, the browser port `7474` and the user `neo4j` / password `password`.
# - **Why:** they must match what `neo4j_infra` configured.
# - **How:** plain constants; the host is chosen in section 6.

# %%
# NEO4J_WORKDIR = "/var/lib/neo4j"
NEO4J_PORT = 7687
NEO4J_WEBUI_PORT = 7474

NEO4J_INIT_USER = "neo4j"
NEO4J_INIT_PASSWORD = "password"

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
# ## 6. Connect
#
# - **What:** creates a driver for `bolt://<host>:7687`, checks the server answers and opens a session.
# - **Why:** every later cell sends Cypher through this session.
# - **How:** the host is `127.0.0.1` (Local) or `neo4j-instance.<alias>.<domain>` (VPN); `verify_connectivity()` fails fast if the server or the password is wrong.
# - 📄 [Neo4j Python driver 6.2 — API](https://neo4j.com/docs/api/python-driver/6.2/api.html)

# %%
from neo4j import GraphDatabase


def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


NEO4J_CONTAINER_NAME = "neo4j-instance"
NEO4J_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else vpn_fqdn(NEO4J_CONTAINER_NAME)
)
n4j_uri = f"bolt://{NEO4J_CLIENT_HOST}:{NEO4J_PORT}"
n4j_auth = (NEO4J_INIT_USER, NEO4J_INIT_PASSWORD)

driver = GraphDatabase.driver(n4j_uri, auth=n4j_auth)
driver.verify_connectivity()
session = driver.session()

# %% [markdown]
# ## 7. Fake data generator
#
# - **What:** creates a `Faker` instance.
# - **Why:** realistic names, jobs and cities without real personal data.
# - **How:** `fake.unique.first_name()` never repeats a name within the run.
# - 📄 [Faker](https://faker.readthedocs.io/en/master/)

# %%
from faker import Faker

fake = Faker()

# %% [markdown]
# ## 8. Create the people
#
# - **What:** inserts 10 `:Person` nodes in one transaction and checks there are exactly 10.
# - **Why:** sending the whole list as one parameter is one round trip instead of ten.
# - **How:** `UNWIND $batch AS user` turns the list into rows; `MERGE` on `id` creates a node only if none has that id; `date(...)` stores `joined` as a Cypher date. The `with begin_transaction()` block commits at the end, or rolls back on an error.
# - 📄 [UNWIND](https://neo4j.com/docs/cypher-manual/current/clauses/unwind/) · [MERGE](https://neo4j.com/docs/cypher-manual/current/clauses/merge/) · [Cypher — Parameters](https://neo4j.com/docs/cypher-manual/current/syntax/parameters/) · [Temporal values](https://neo4j.com/docs/cypher-manual/current/values-and-types/temporal/) · [Neo4j Python driver 6.2 — API](https://neo4j.com/docs/api/python-driver/6.2/api.html)

# %%
total_persons = 10

with session.begin_transaction() as transaction:
    transaction.run(
        """
        UNWIND $batch AS user
        MERGE (p:Person {id: user.id})
        SET p.name = user.name, 
            p.email = user.email, 
            p.job = user.job, 
            p.city = user.city,
            p.joined = date(user.joined)
        """,
        batch=[
            {
                "id": i,
                "name": fake.unique.first_name(),
                "email": fake.email(),
                "job": fake.job(),
                "city": fake.city(),
                "joined": fake.date_this_decade().isoformat(),
            }
            for i in range(total_persons)
        ],
    )
    print("Successfully inserted nodes")

person_count = session.run("MATCH (p:Person) RETURN count(p) AS total").single()["total"]
assert person_count == total_persons, person_count

# %% [markdown]
# ## 9. Create the friendships and check the plugins
#
# - **What:** links up to 14 random pairs with a `:knows` relationship in each direction, then checks APOC and Graph Data Science answer.
# - **Why:** Neo4j relationships always have a direction, so a mutual friendship is two relationships, each with its own `strength`.
# - **How:** pairs are sorted and kept in a set, so duplicates collapse; `MATCH` finds both nodes and `MERGE` creates each direction once; the count must be twice the number of pairs. `apoc.version()` and `gds.version()` prove the plugins loaded.
# - 📄 [MERGE](https://neo4j.com/docs/cypher-manual/current/clauses/merge/) · [APOC](https://neo4j.com/docs/apoc/current/) · [Graph Data Science](https://neo4j.com/docs/graph-data-science/current/)

# %%
import random

total_relationships = 14

with session.begin_transaction() as transaction:
    user_ids = [
        record["id"] for record in transaction.run("MATCH (p:Person) RETURN p.id AS id")
    ]
    if len(user_ids) < 2:
        print("Not enough users to create friendships.")
    else:
        relationships = set()
        relationships_data = []
        for _ in range(total_relationships):
            ids = tuple(sorted(random.sample(user_ids, 2)))
            relationships.add(ids)
        for relationship in relationships:
            relationships_data.append(
                {
                    "id_a": relationship[0],
                    "id_b": relationship[1],
                    "since": random.randint(2010, 2026),
                    "str_ab": round(random.uniform(0.1, 1.0), 2),
                    "str_ba": round(random.uniform(0.1, 1.0), 2),
                }
            )
        transaction.run(
            """
            UNWIND $data AS row
            MATCH (a:Person {id: row.id_a})
            MATCH (b:Person {id: row.id_b})
            MERGE (a)-[r1:knows]->(b)
            SET r1.since = row.since,
                r1.strength = row.str_ab
            MERGE (b)-[r2:knows]->(a)
            SET r2.since = row.since,
                r2.strength = row.str_ba
            """,
            data=relationships_data,
        )
        print("Successfully added relationships")

relationship_count = session.run(
    "MATCH (:Person)-[r:knows]->(:Person) RETURN count(r) AS total"
).single()["total"]
assert relationship_count == len(relationships_data) * 2, relationship_count

apoc_version = session.run("RETURN apoc.version() AS version").single()["version"]
gds_version = session.run("RETURN gds.version() AS version").single()["version"]
assert apoc_version and gds_version
print(f"APOC {apoc_version}; GDS {gds_version}")

# %% [markdown]
# ## 10. Delete and close
#
# - **What:** deletes every `:Person` with its relationships, checks none remain and closes the session and driver.
# - **Why:** a node that still has relationships cannot be deleted with plain `DELETE`.
# - **How:** `MATCH (p:Person) DETACH DELETE p`.
# - 📄 [DELETE](https://neo4j.com/docs/cypher-manual/current/clauses/delete/)

# %%
with session.begin_transaction() as transaction:

    # transaction.run("MATCH (a:Person)<-[r:knows]-(b:Person) DELETE r")
    transaction.run("MATCH (p:Person) DETACH DELETE p")

    print("Successfully deleted persons")

remaining = session.run("MATCH (p:Person) RETURN count(p) AS total").single()["total"]
assert remaining == 0, remaining
session.close()
driver.close()
