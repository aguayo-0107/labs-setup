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
# # MongoDB lab — documents with PyMongo
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
# - **What:** locates the labs-setup root, changes into `mongodb/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "mongodb"
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Replica set constants
#
# - **What:** the replica set name `replica_set_0`, the member ports `27011-27013`, the client host of each member and the root user `admin`/`admin`.
# - **Why:** they must match what `mongodb_infra` published.
# - **How:** `127.0.0.1` in Local mode, `mongodb-node-N.<alias>.<domain>` in VPN mode.

# %%
DOCKER_INTERNAL_HOST = "host.docker.internal"

MONGODB_REPLICA_SET = "replica_set_0"
MONGODB_TOTAL_NODES = 3

MONGODB_NODE_NAMES = [f"mongodb-node-{i + 1}" for i in range(MONGODB_TOTAL_NODES)]
def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


MONGODB_NODE_CLIENT_HOSTS = [
    "127.0.0.1" if NETWORK_MODE == "local" else vpn_fqdn(name)
    for name in MONGODB_NODE_NAMES
]
MONGODB_NODE_PORTS = [27010 + (i + 1) for i in range(0, MONGODB_TOTAL_NODES)]

MONGODB_WORKDIR = "/data/db"

MONGO_INITDB_ROOT_USERNAME = "admin"
MONGO_INITDB_ROOT_PASSWORD = "admin"
MONGO_INITDB_DATABASE = "admin"

# %% [markdown]
# ## 5. Paths
#
# - **What:** defines `mount/` and the keyfile path, as the infrastructure notebook does.
# - **Why:** the lab only reads them; it never changes the members' files.
# - **How:** paths relative to the module folder, built with `os.path.join`.

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = f"{os.path.join(os.path.relpath(Path.cwd()))}"
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")
MONGODB_LOCAL_CLUSTER_KEY_PATH = os.path.join(DOCKER_MOUNTDIR, "mongo-keyfile")

mount_path = Path(DOCKER_MOUNTDIR)
mount_path.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## 6. Connect
#
# - **What:** opens a `MongoClient`, checks the replica set has 1 `PRIMARY` and 2 `SECONDARY` members and starts from an empty `db.users`.
# - **Why:** in Local mode the members announce container names the host cannot resolve, so the client must talk to the primary directly; in VPN mode those names resolve and the client can follow the whole replica set.
# - **How:** Local: asks each member `hello` and connects with `directConnection=true` to the one that answers `isWritablePrimary`. VPN: a seed list of the three members with `replicaSet=replica_set_0`. Both use `w=majority`, so a write is confirmed once 2 of 3 members have it.
# - 📄 [Connection string options](https://www.mongodb.com/docs/v7.0/reference/connection-string-options/) · [Write concern](https://www.mongodb.com/docs/v7.0/reference/write-concern/) · [hello](https://www.mongodb.com/docs/v7.0/reference/command/hello/) · [replSetGetStatus](https://www.mongodb.com/docs/v7.0/reference/command/replSetGetStatus/) · [PyMongo — MongoClient](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/mongo_client.html)

# %%
from pymongo import MongoClient

nodes_ports = list(zip(MONGODB_NODE_CLIENT_HOSTS, MONGODB_NODE_PORTS))

if NETWORK_MODE == "local":
    primary_endpoint = None
    for host, port in nodes_ports:
        direct_uri = (
            f"mongodb://{MONGO_INITDB_ROOT_USERNAME}:{MONGO_INITDB_ROOT_PASSWORD}"
            f"@{host}:{port}/?authSource=admin"
        )
        try:
            with MongoClient(
                direct_uri,
                directConnection=True,
                serverSelectionTimeoutMS=5000,
            ) as node_client:
                hello = node_client.admin.command("hello")
                if hello.get("isWritablePrimary") or hello.get("ismaster"):
                    primary_endpoint = (host, port)
                    break
        except Exception:
            continue
    if primary_endpoint is None:
        raise TimeoutError("Could not find the MongoDB primary through published ports")
    primary_host, primary_port = primary_endpoint
    connection_string = (
        f"mongodb://{MONGO_INITDB_ROOT_USERNAME}:{MONGO_INITDB_ROOT_PASSWORD}"
        f"@{primary_host}:{primary_port}/"
        "?directConnection=true&authSource=admin&w=majority"
    )
else:
    seed_list = ",".join(f"{host}:{port}" for host, port in nodes_ports)
    connection_string = (
        f"mongodb://{MONGO_INITDB_ROOT_USERNAME}:{MONGO_INITDB_ROOT_PASSWORD}@"
        f"{seed_list}/"
        f"?replicaSet={MONGODB_REPLICA_SET}&authSource=admin&w=majority"
    )
print(f"Connection URL: {connection_string}")

client = MongoClient(connection_string, serverSelectionTimeoutMS=20000)
assert client.admin.command("ping")["ok"] == 1
replica_status = client.admin.command("replSetGetStatus")
assert len(replica_status["members"]) == MONGODB_TOTAL_NODES
assert sum(member["stateStr"] == "PRIMARY" for member in replica_status["members"]) == 1
assert sum(member["stateStr"] == "SECONDARY" for member in replica_status["members"]) == 2

db = client["db"]
users_collection = db["users"]
users_collection.drop()

# %% [markdown]
# ## 7. Fake data generator
#
# - **What:** creates a `Faker` instance.
# - **Why:** realistic names, companies and coordinates without real personal data.
# - **How:** `fake.unique.name()` never repeats a name within the run.
# - 📄 [Faker](https://faker.readthedocs.io/en/master/)

# %%
from faker import Faker

fake = Faker()

# %% [markdown]
# ## 8. Insert 10 000 documents
#
# - **What:** builds 10 000 user documents with a nested `profile`, a `tags` array and counters, and inserts them in one call.
# - **Why:** documents in one collection do not need a fixed schema and can nest objects and arrays.
# - **How:** one `insert_many` call; the cell asserts the collection then holds exactly 10 000 documents.
# - 📄 [insertMany](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.insertMany/) · [PyMongo — Collection](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/collection.html)

# %%
# # %%timeit -n 2 -r 2
# -n 1: run only 2 loop
# -r 1: repeat only 2 time

import random

print("Generating batch...")

users_batch = [
    {
        "name": (
            fake.unique.name() if random.random() > 0.5 else fake.unique.name().upper()
        ),
        "email": fake.ascii_free_email(),
        "profile": {
            "job": fake.job(),
            "company": fake.company(),
            "location": {
                "lat": float(fake.latitude()),
                "lng": float(fake.longitude()),
            },
        },
        "tags": [fake.word() for _ in range(random.randint(2, 5))],
        "login_count": random.randint(1, 1000),
        "last_login": fake.date_time_this_year().isoformat(),
        "active": fake.boolean(chance_of_getting_true=75),
    }
    for _ in range(10000)
]
print("Inserting batch...")
users_collection.insert_many(users_batch)
assert users_collection.count_documents({}) == len(users_batch)

# %% [markdown]
# ## 9. Filter
#
# - **What:** counts the active users with more than 500 logins.
# - **Why:** a filter document combines conditions with an implicit AND.
# - **How:** `{"active": True, "login_count": {"$gt": 500}}` with `count_documents`.
# - 📄 [PyMongo — Collection](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/collection.html)

# %%
query = {"active": True, "login_count": {"$gt": 500}}
results = users_collection.find(query)
print(f"Found {users_collection.count_documents(query)} highly active users.")

# %% [markdown]
# ## 10. Projection
#
# - **What:** returns name, email and `profile.job` of up to 100 users tagged `work`.
# - **Why:** a projection sends back only the fields you need; matching a value inside an array needs no special operator.
# - **How:** `find({"tags": "work"}, {"name": 1, "email": 1, "profile.job": 1, "_id": 0}).limit(100)`.
# - 📄 [Project fields](https://www.mongodb.com/docs/v7.0/tutorial/project-fields-from-query-results/)

# %%
projection = {"name": 1, "email": 1, "profile.job": 1, "_id": 0}
cursor = users_collection.find({"tags": "work"}, projection).limit(100)
for user in cursor:
    print(user)

# %% [markdown]
# ## 11. Aggregation pipeline
#
# - **What:** averages `login_count` per job for active users and keeps the top 100 jobs.
# - **Why:** the server filters, groups and reshapes the data in one request instead of the client doing it.
# - **How:** stages `$match` → `$group` (`$avg`, `$sum`) → `$sort` → `$project` → `$limit`.
# - 📄 [$group](https://www.mongodb.com/docs/v7.0/reference/operator/aggregation/group/)

# %%
pipeline = [
    {"$match": {"active": True}},  # Stage 1: Filter only active users
    {  # Stage 2: Group by the nested 'job' field
        "$group": {
            "_id": "$profile.job",
            "avg_logins": {"$avg": "$login_count"},
            "user_count": {"$sum": 1},
        }
    },
    {"$sort": {"avg_logins": -1}},  # Stage 3: Sort by average logins descending
    {
        "$project": {
            "_id": 0,  # Hide the original _id
            "job_title": "$_id",  # Rename _id to job_title
            "stats": {  # Create a nested object for stats
                "average": "$avg_logins",
                "total_users": "$user_count",
            },
        }
    },
    {"$limit": 100},  # Stage 4: Limit to top 100 most active professions
]
results = list(users_collection.aggregate(pipeline))
for res in results:
    print(res)

# %% [markdown]
# ## 12. Query a nested field
#
# - **What:** counts users with a positive latitude (northern hemisphere).
# - **Why:** fields inside embedded documents are queried with dot notation.
# - **How:** `{"profile.location.lat": {"$gt": 0}}`.
# - 📄 [Documents — dot notation](https://www.mongodb.com/docs/v7.0/core/document/)

# %%
northern_users = users_collection.count_documents({"profile.location.lat": {"$gt": 0}})
print(f"Users in Northern Hemisphere: {northern_users}")

# %% [markdown]
# ## 13. Case-insensitive sort
#
# - **What:** sorts names with an English collation of strength 2.
# - **Why:** without a collation the sort compares bytes, so the upper-case names (about half, see section 8) come before every mixed-case name; strength 2 compares base letters and accents but not case.
# - **How:** `.sort("name", 1).collation({"locale": "en", "strength": 2})`.
# - 📄 [Collation](https://www.mongodb.com/docs/v7.0/reference/collation/) · [PyMongo — Cursor](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/cursor.html)

# %%
# Standard Sort (Z-A-a-z) vs. Collation Sort (A-a-B-b...)
cursor = (
    users_collection.find({})
    .sort("name", 1)
    .collation({"locale": "en", "strength": 2})
    .limit(100)
)

for user in cursor:
    print(user["name"])

# %% [markdown]
# ## 14. Update one document
#
# - **What:** adds 1 to `login_count` of one user and checks the new value.
# - **Why:** an update operator changes one field on the server without rewriting the document.
# - **How:** `update_one({"_id": ...}, {"$inc": {"login_count": 1}})`, then `find_one` and an assertion.
# - 📄 [$inc](https://www.mongodb.com/docs/v7.0/reference/operator/update/inc/)

# %%
# 1. Get a single user to test with
target_user = users_collection.find_one({"active": True})
user_id = target_user["_id"]
initial_logins = target_user.get("login_count", 0)

print(f"User: {target_user['name']}")
print(f"Initial login count: {initial_logins}")

# 2. Increment the login counter for JUST this user
users_collection.update_one({"_id": user_id}, {"$inc": {"login_count": 1}})

# 3. Query again to see the change
updated_user = users_collection.find_one({"_id": user_id})
new_logins = updated_user.get("login_count", 0)

print(f"Updated login count: {new_logins}")
print(f"Change confirmed: {new_logins == initial_logins + 1}")
assert new_logins == initial_logins + 1

# %% [markdown]
# ## 15. Update and read in one step
#
# - **What:** increments the counter again and gets the updated document back.
# - **Why:** one round trip instead of an update followed by a read.
# - **How:** `find_one_and_update(..., return_document=ReturnDocument.AFTER)`.
# - 📄 [findOneAndUpdate](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.findOneAndUpdate/) · [PyMongo — Collection](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/collection.html)

# %%
from pymongo import ReturnDocument

# This performs the update and returns the NEW version of the document immediately
updated_doc = users_collection.find_one_and_update(
    {"_id": user_id}, {"$inc": {"login_count": 1}}, return_document=ReturnDocument.AFTER
)

print(f"New count from single-step operation: {updated_doc['login_count']}")

# %% [markdown]
# ## 16. Update many documents
#
# - **What:** marks every user whose job contains "engineer" with `is_technical: true`.
# - **Why:** `update_many` applies the same change to every match; documents gain the new field only where it is set.
# - **How:** `$regex` with option `i` (case-insensitive) and `$set`; prints `modified_count`.
# - 📄 [$regex](https://www.mongodb.com/docs/v7.0/reference/operator/query/regex/)

# %%
query = {"profile.job": {"$regex": ".*engineer.*", "$options": "i"}}
update = {"$set": {"is_technical": True}}
result = users_collection.update_many(query, update)
print(f"Updated {result.modified_count} engineers.")

# %% [markdown]
# ## 17. Update a missing document
#
# - **What:** tries to deactivate `example@user.com`.
# - **Why:** when no document matches, `update_one` changes nothing and raises no error.
# - **How:** `update_one` with `$set` and the default `upsert=False`.
# - 📄 [updateOne](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.updateOne/)

# %%
query = {"email": "example@user.com"}
new_values = {"$set": {"active": False}}
users_collection.update_one(query, new_values)

# %% [markdown]
# ## 18. Delete the documents
#
# - **What:** deletes every document in `users` and checks 10 000 were deleted.
# - **Why:** it completes the create, read, update and delete cycle.
# - **How:** `delete_many({})` with an empty filter; the assertion compares `deleted_count`.
# - 📄 [deleteMany](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.deleteMany/)

# %%
delete_result = users_collection.delete_many({})
assert delete_result.deleted_count == len(users_batch)
print(f"Deleted {delete_result.deleted_count} documents.")

# %% [markdown]
# ## 19. Drop the collection
#
# - **What:** removes the `users` collection itself.
# - **Why:** `delete_many` empties a collection but keeps it and its indexes; dropping removes both.
# - **How:** `db.drop_collection(users_collection)`.
# - 📄 [PyMongo — Collection](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/collection.html)

# %%
db.drop_collection(users_collection)
print("Deleted users collection.")

# %% [markdown]
# ## 20. Query plan with and without an index
#
# - **What:** inserts 100 000 students, explains the same query before and after creating an index on `promedio`.
# - **Why:** without an index the server reads every document (`COLLSCAN`); with it, only the matching index entries (`IXSCAN`).
# - **How:** `find(...).explain()`, then `create_index([("promedio", 1)])`; the cell asserts `COLLSCAN` before and `IXSCAN` after.
# - 📄 [Explain results](https://www.mongodb.com/docs/v7.0/reference/explain-results/) · [PyMongo — Collection](https://pymongo.readthedocs.io/en/4.17.0/api/pymongo/collection.html)

# %%
import random
import pprint

db = client["universidad"]
students_collection = db["estudiantes"]

# 1. Limpiar y Poblar
print("Generando datos...")
students_collection.drop()
students = [
    {"nombre": f"{fake.name()}", "promedio": round(random.uniform(5, 10), 2)}
    for i in range(100000)
]
students_collection.insert_many(students)

# 2. Análisis sin índice
print("\n--- Find sin índice ---")
explain_find_no_idx = students_collection.find({"promedio": {"$gt": 9.9}}).explain()
pprint.pprint(explain_find_no_idx)
# stats_no_idx = explain_find_no_idx.get("executionStats", {})
# pprint.pprint(
#     {
#         "Stage": stats_no_idx.get("executionStages", {}).get("stage"),
#         "Docs Examinados": stats_no_idx.get("totalDocsExamined"),
#         "Execution Millis": stats_no_idx.get("executionTimeMillis"),
#     }
# )

# 3. Crear Índice
students_collection.create_index([("promedio", 1)])

# 4. Análisis con índice
print("\n--- Find con índice ---")
explain_find_idx = students_collection.find({"promedio": {"$gt": 9.9}}).explain()
pprint.pprint(explain_find_idx)

def contains_stage(value, stage):
    if isinstance(value, dict):
        return value.get("stage") == stage or any(
            contains_stage(item, stage) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_stage(item, stage) for item in value)
    return False

assert contains_stage(explain_find_no_idx["queryPlanner"]["winningPlan"], "COLLSCAN")
assert contains_stage(explain_find_idx["queryPlanner"]["winningPlan"], "IXSCAN")
# stats_idx = explain_find_idx.get("executionStats", {})
# Nota: Cuando hay índice, el 'stage' suele estar dentro de 'inputStage'
# input_stage = stats_idx.get("executionStages", {}).get("inputStage", {})
# pprint.pprint(
#     {
#         "Stage": "IXSCAN + FETCH",
#         "Docs Examinados": stats_idx.get("totalDocsExamined"),
#         "Execution Millis": stats_idx.get("executionTimeMillis"),
#     }
# )

# %% [markdown]
# ## 21. Explain as a command and clean up
#
# - **What:** runs the `explain` command with verbosity `executionStats`, then drops the `universidad` database and closes the client.
# - **Why:** `executionStats` adds the documents and keys examined and the time taken, which the default explain omits.
# - **How:** `db.command({"explain": {"find": ...}, "verbosity": "executionStats"})`.
# - 📄 [explain command](https://www.mongodb.com/docs/v7.0/reference/command/explain/)

# %%
# Otra forma es definiendo un comando con explain que envuelve al find
query_explain = {
    "explain": {"find": "estudiantes", "filter": {"promedio": {"$gt": 9.5}}},
    "verbosity": "executionStats",
}

# Ejecutamos el comando directamente en la base de datos
stats = db.command(query_explain)

pprint.pprint(stats.get("executionStats", {}))
client.drop_database("universidad")
client.close()
