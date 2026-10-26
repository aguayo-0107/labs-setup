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
# # Hive lab — tables over HDFS
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
# - **What:** locates the labs-setup root, changes into `hive/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "hive"
import sys

if str(LABS_ROOT) not in sys.path:
    sys.path.insert(0, str(LABS_ROOT))
from labs_runtime import run_command

os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Connection constants
#
# - **What:** the container names, ports (HiveServer2 `10000`) and HDFS paths (`/user/hive/warehouse`) set by `hive_infra`.
# - **Why:** they must match the running stack.
# - **How:** HiveServer2 is reached at `127.0.0.1` (Local) or `hive-server2.<alias>.<domain>` (VPN).

# %%
DOCKER_INTERNAL_HOST = "host.docker.internal"

POSTGRES_USER = "hive"
POSTGRES_PASSWORD = "hive"
POSTGRES_DB = "metastore"

HIVE_DB_CONTAINER_NAME = "hive-metastore-db"
HIVE_METASTORE_CONTAINER_NAME = "hive-metastore"
HIVE_SERVER2_CONTAINER_NAME = "hive-server2"

HIVE_DB_HOSTNAME = HIVE_DB_CONTAINER_NAME
HIVE_METASTORE_HOSTNAME = HIVE_METASTORE_CONTAINER_NAME
HIVE_SERVER2_HOSTNAME = HIVE_SERVER2_CONTAINER_NAME
HIVE_DB_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else f"{HIVE_DB_CONTAINER_NAME}.{VPN_CLIENT_DOMAIN}"
)
HIVE_METASTORE_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else f"{HIVE_METASTORE_CONTAINER_NAME}.{VPN_CLIENT_DOMAIN}"
)
HIVE_SERVER2_CLIENT_HOST = (
    "127.0.0.1"
    if NETWORK_MODE == "local"
    else f"{HIVE_SERVER2_CONTAINER_NAME}.{VPN_CLIENT_DOMAIN}"
)

HIVE_DB_INTERNAL_PORT = 15432
HIVE_METASTORE_INTERNAL_PORT = 9083
HIVE_SERVER2_INTERNAL_PORT = 10000
HIVE_SERVER2_UI_INTERNAL_PORT = 10002

HIVE_DB_EXTERNAL_PORT = 15432
HIVE_METASTORE_EXTERNAL_PORT = 9083
HIVE_SERVER2_EXTERNAL_PORT = 10000
HIVE_SERVER2_UI_EXTERNAL_PORT = 10002

HIVE_USERDIR = "/user/hive"
HIVE_DATADIR = f"{HIVE_USERDIR}/warehouse"

HADOOP_RESOURCEMANAGER_WEBUI_PORT = 8088
HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT = 8032
HADOOP_RESOURCEMANAGER_TRACKER_PORT = 8031
HADOOP_RESOURCEMANAGER_SCHEDULER_PORT = 8030
HADOOP_RESOURCEMANAGER_ADMIN_PORT = 8033

HADOOP_NAMENODE_HOSTNAME = "namenode"
HADOOP_NAMENODE_PORT = 8020

HADOOP_RESOURCEMANAGER_HOSTNAME = "resourcemanager"
HADOOP_RESOURCEMANAGER_PORT = 8032

APACHE_HIVE_IMAGE = "apache/hive:4.0.1"
POSTGRES_IMAGE = "postgres:18"

# %% [markdown]
# ## 5. Generate the dataset
#
# - **What:** writes `sales.csv` with 50,000 rows `id, producto, categoria, monto, pais` and no header.
# - **Why:** a fixed seed makes every run produce the same file; without a header the first table needs no option to skip it.
# - **How:** `random.seed(2026)` and `csv.writer`.

# %%
import csv
import random
import os

dataset_filename = "sales.csv"
random.seed(2026)
with open(dataset_filename, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    # Hive puede ignorar headers fácilmente, pero para simplificar la primera tabla, lo generaremos sin cabecera.
    # Formato esperado: id, producto, categoria, monto, pais
    for i in range(1, 50001):
        writer.writerow(
            [
                i,
                f"Producto_{random.randint(1, 20)}",
                random.choice(["Electronica", "Hogar", "Deportes"]),
                round(random.uniform(10.0, 500.0), 2),
                random.choice(["MX", "US", "CO", "ES"]),
            ]
        )
print(f"¡Dataset '{dataset_filename}' generado localmente con 50,000 filas!")

# %% [markdown]
# ## 6. Put the file in HDFS
#
# - **What:** creates `/user/hive/warehouse/external/lab_db/sales` and uploads `sales.csv` there.
# - **Why:** an external table reads files that already exist in HDFS.
# - **How:** `docker cp` into `namenode:/tmp`, then `hdfs dfs -mkdir -p` and `hdfs dfs -put -f`.
# - 📄 [docker container cp](https://docs.docker.com/reference/cli/docker/container/cp/) · [FileSystem shell](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/FileSystemShell.html)

# %%
# Pasamos el archivo del host al contenedor del namenode temporalmente, y luego lo consagramos en HDFS
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-mkdir", "-p", f"{HIVE_DATADIR}/external/lab_db/sales"], check=False)
run_command(["docker", "cp", "sales.csv", "namenode:/tmp/sales.csv"], check=False)
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-put", "-f", "/tmp/sales.csv", f"{HIVE_DATADIR}/external/lab_db/sales"], check=False)

# %% [markdown]
# ## 7. Connection test
#
# - **What:** connects to HiveServer2 as `hive` and lists the databases.
# - **Why:** it fails early if HiveServer2 is not reachable.
# - **How:** `pyhive.hive.Connection` and `pandas.read_sql("SHOW DATABASES", connection)`; the result must not be empty.
# - 📄 [PyHive README (DB-API)](https://raw.githubusercontent.com/dropbox/PyHive/master/README.rst) · [pandas.read_sql](https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html)

# %%
from pyhive import hive
import pandas as pd

# 1. Establecer la conexión (aquí no especificamos database porque queremos verlas todas)
connection = hive.Connection(
    host=HIVE_SERVER2_CLIENT_HOST, port=HIVE_SERVER2_EXTERNAL_PORT, username="hive"
)

# 2. Ejecutar la consulta para listar bases de datos
df_databases = pd.read_sql("SHOW DATABASES", connection)

# 3. Mostrar el resultado
display(df_databases)
assert not df_databases.empty

# 4. Cerrar la conexión
connection.close()

# %% [markdown]
# ## 8. External table
#
# - **What:** recreates `lab_db` and defines `sales` over the CSV folder.
# - **Why:** an `EXTERNAL` table only describes the files: dropping it leaves the data in HDFS.
# - **How:** `CREATE EXTERNAL TABLE ... ROW FORMAT DELIMITED FIELDS TERMINATED BY ',' STORED AS TEXTFILE LOCATION 'hdfs://namenode:8020/...'`; `SHOW TABLES` must list `sales`.
# - 📄 [Hive DDL (external tables, partitions, SHOW)](https://hive.apache.org/docs/latest/language/languagemanual-ddl/)

# %%
from pyhive import hive
import pandas as pd

# 1. Establecemos la conexión al servidor (sin especificar base de datos inicialmente)
# El usuario "hive" es el estándar, lo agregamos para emular el '-n hive' de beeline
connection = hive.Connection(
    host=HIVE_SERVER2_CLIENT_HOST, port=HIVE_SERVER2_EXTERNAL_PORT, username="hive"
)
cursor = connection.cursor()

# 2. Borrar y crear la base de datos
print("Recreando la base de datos 'lab_db'...")
cursor.execute("DROP DATABASE IF EXISTS lab_db CASCADE")
cursor.execute("CREATE DATABASE IF NOT EXISTS lab_db")

# 3. Le indicamos a la sesión que use 'lab_db' (equivale a conectarse a /lab_db)
cursor.execute("USE lab_db")

# 4. Crear la tabla externa (Aprovechamos las triples comillas de Python para que sea más legible)
# Asumo que HIVE_DATADIR ya lo tienes definido como variable en tu libreta
create_table_sql = f"""
CREATE EXTERNAL TABLE IF NOT EXISTS sales (
    id INT, 
    producto STRING, 
    categoria STRING, 
    monto DOUBLE, 
    pais STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'hdfs://namenode:8020{HIVE_DATADIR}/external/lab_db/sales'
"""

print("Creando la tabla externa 'sales'...")
cursor.execute(create_table_sql)

# 5. Mostrar las tablas creadas
print("Tablas disponibles en lab_db:")
# Usamos pandas aquí para que la tabla de resultados se vea bonita en tu Jupyter Notebook
df_tables = pd.read_sql("SHOW TABLES", connection)
display(df_tables)
assert "sales" in df_tables.astype(str).values

# 6. Cerramos la conexión
connection.close()

# %% [markdown]
# ## 9. First rows
#
# - **What:** reads 5 rows of `sales`.
# - **Why:** it checks Hive parses the CSV into the declared columns.
# - **How:** `SELECT * FROM sales LIMIT 5` must return exactly 5 rows.
# - 📄 [pandas.read_sql](https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html)

# %%
from pyhive import hive
import pandas as pd

# 1. Establecemos la conexión apuntando directamente a 'lab_db'
connection = hive.Connection(
    host=HIVE_SERVER2_CLIENT_HOST,
    port=HIVE_SERVER2_EXTERNAL_PORT,
    username="hive",
    database="lab_db",
)

# 2. Definimos la consulta
query = "SELECT * FROM sales LIMIT 5"

# 3. Ejecutamos la consulta y la guardamos en un DataFrame
df_sample = pd.read_sql(query, connection)

# 4. Mostramos los 5 registros
display(df_sample)
assert len(df_sample) == 5

# 5. Cerramos la conexión
connection.close()

# %% [markdown]
# ## 10. Aggregation
#
# - **What:** counts sales, average ticket and maximum sale per category and country.
# - **Why:** a `GROUP BY` over all the files; the counts must add up to the 50,000 rows.
# - **How:** `COUNT(*)`, `ROUND(AVG(monto), 2)` and `MAX(monto)` grouped by `categoria, pais`.

# %%
from pyhive import hive
import pandas as pd

# 1. Establecer la conexión a la base de datos 'lab_db'
connection = hive.Connection(
    host=HIVE_SERVER2_CLIENT_HOST,
    port=HIVE_SERVER2_EXTERNAL_PORT,
    username="hive",
    database="lab_db",
)

# 2. Definir tu consulta de agregación (usamos triples comillas para que se vea ordenada)
query_agg = """
SELECT 
    categoria, 
    pais, 
    COUNT(*) AS total_ventas, 
    ROUND(AVG(monto), 2) AS ticket_promedio, 
    MAX(monto) as venta_maxima 
FROM sales 
GROUP BY categoria, pais 
ORDER BY total_ventas DESC
"""

# 3. Ejecutar la consulta y guardar el resultado en un DataFrame
df_summary = pd.read_sql(query_agg, connection)

# 4. Mostrar el DataFrame resultante
display(df_summary)
assert not df_summary.empty
assert int(df_summary["total_ventas"].sum()) == 50_000

# 5. Cerrar la conexión
connection.close()

# %% [markdown]
# ## 11. Partitioned table
#
# - **What:** creates `sales_partitioned` (partitioned by `pais`, stored as `SEQUENCEFILE`) and fills it from `sales`.
# - **Why:** each country gets its own folder, so a query filtered by country reads only that folder.
# - **How:** `hive.exec.dynamic.partition=true` and `hive.exec.dynamic.partition.mode=nonstrict` let Hive create the partitions from the last `SELECT` column; `SHOW PARTITIONS` must return `pais=CO`, `ES`, `MX`, `US`.
# - 📄 [Hive DDL (external tables, partitions, SHOW)](https://hive.apache.org/docs/latest/language/languagemanual-ddl/) · [Hive DML (dynamic partition inserts)](https://hive.apache.org/docs/latest/language/languagemanual-dml/)

# %%
from pyhive import hive

# 1. Conectar a la base de datos lab_db
connection = hive.Connection(
    host=HIVE_SERVER2_CLIENT_HOST,
    port=HIVE_SERVER2_EXTERNAL_PORT,
    username="hive",
    database="lab_db",
)
cursor = connection.cursor()

# 2. Habilitar particionado dinámico (esto es CRUCIAL para el INSERT que vas a hacer)
# Sin esto, Hive te pedirá especificar cada partición manualmente.
print("Configurando entorno para particiones dinámicas...")
cursor.execute("SET hive.exec.dynamic.partition = true")
cursor.execute("SET hive.exec.dynamic.partition.mode = nonstrict")

# 3. Crear la tabla particionada como SEQUENCEFILE
create_partitioned_sql = """
CREATE TABLE IF NOT EXISTS sales_partitioned (
    id INT, 
    producto STRING, 
    categoria STRING, 
    monto DOUBLE
) 
PARTITIONED BY (pais STRING) 
STORED AS SEQUENCEFILE
"""
print("Creando tabla 'sales_partitioned'...")
cursor.execute(create_partitioned_sql)

# 4. Insertar los datos desde la tabla original
# Hive tomará la última columna del SELECT (pais) para crear las carpetas de partición
insert_sql = """
INSERT OVERWRITE TABLE sales_partitioned 
PARTITION(pais) 
SELECT id, producto, categoria, monto, pais 
FROM sales
"""
print("Insertando datos y creando particiones por país... (esto puede tardar un poco)")
cursor.execute(insert_sql)

print("¡Proceso completado con éxito!")

cursor.execute("SHOW PARTITIONS sales_partitioned")
partitions = {row[0] for row in cursor.fetchall()}
assert partitions == {"pais=CO", "pais=ES", "pais=MX", "pais=US"}, partitions

# 5. Cerrar conexión
connection.close()

# %% [markdown]
# ## 12. Look at HDFS
#
# - **What:** lists the external table's folder and the partition folders of `sales_partitioned`.
# - **Why:** it shows where each kind of table keeps its data: the external one where we put it, the managed one under the warehouse (`/user/hive/warehouse/managed/lab_db.db/`).
# - **How:** `hdfs dfs -ls`, run with `docker exec namenode`.
# - 📄 [FileSystem shell](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/FileSystemShell.html)

# %%
# Se guarda por defecto en el 'warehouse directory' configurado en {HIVE_DATADIR}
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-ls", f"{HIVE_DATADIR}/external/lab_db/sales"], check=False)
run_command(["docker", "exec", "namenode", "hdfs", "dfs", "-ls", f"{HIVE_DATADIR}/managed/lab_db.db/sales_partitioned/"], check=False)
