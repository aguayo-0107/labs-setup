# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: non-relational-dbs-labs
# ---

# %% [markdown]
# # Spark lab — runs inside `spark-jupyter`
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
# ## 3. Cluster names inside the Docker network
#
# - **What:** the master (`spark-master-internal:6077`), the Driver's own name and ports (`spark-jupyter`, `4050`/`4051`), HDFS (`hdfs://namenode:8020`) and the folders mounted by `spark_infra`.
# - **Why:** this notebook runs in the `spark-jupyter` container, so every name is a container on the same network and is identical in Local and VPN mode; the cell stops if it is run anywhere else.
# - **How:** it checks that `/opt/spark/course-jars` exists. Hive support is left off on purpose: it would create a local Derby metastore whose lock survives an interrupted kernel.

# %%
import os
from pathlib import Path

SPARK_EXECUTOR_ENV_DIR = "/opt/spark/executor-env"

SPARK_MASTER_HOST = "spark-master-internal"
SPARK_MASTER_PORT = 6077

# Workers reach the Driver by this container name.
SPARK_DRIVER_HOST = "spark-jupyter"
SPARK_DRIVER_PORT = 4050
SPARK_BLOCK_MANAGER_PORT = 4051

HADOOP_NAMENODE_HOSTNAME = "namenode"
HADOOP_NAMENODE_PORT = 8020
SPARK_HDFS_URI = f"hdfs://{HADOOP_NAMENODE_HOSTNAME}:{HADOOP_NAMENODE_PORT}"
SPARK_DATADIR = f"{SPARK_HDFS_URI}/spark-lab/data"

# Mounted into every Spark container by spark_infra.
SPARK_SHARED_WORKSPACE_DIR = Path("/opt/spark/shared-workspace")
SPARK_JARS_DIR = Path("/opt/spark/course-jars")
if not SPARK_JARS_DIR.is_dir():
    raise RuntimeError("Run this notebook inside the spark-jupyter container (JupyterLab on port 6888)")
# The lab uses only the explicit Iceberg `local` catalog and Delta paths.  It
# deliberately does not enable Hive support: that would create a local Derby
# metastore, whose lock state survives an interrupted notebook kernel.

# %% [markdown]
# ## 4. Stop a leftover SparkContext
#
# - **What:** stops any SparkContext still alive in this kernel.
# - **Why:** only one SparkContext can run per process, and `getOrCreate()` would otherwise reuse the old one with its old settings.
# - **How:** `SparkContext._active_spark_context.stop()` if it is not `None`.
# - 📄 [RDD programming guide](https://spark.apache.org/docs/4.1.2/rdd-programming-guide.html)

# %%
import pyspark
from pyspark import SparkContext

sc = SparkContext._active_spark_context
print(f"    PySpark Version: {pyspark.__version__}")

if sc is not None:
    sc.stop()
    print("🧹 Ghost SparkContext cleaned up.")
else:
    print("✨ No existing SparkContext to clean.")

# %% [markdown]
# ## 5. Create the SparkSession
#
# - **What:** checks the six Iceberg and Delta JARs, then connects to the Standalone master with the lab's settings.
# - **Why:** Spark downloads nothing, so the JARs must already be there and unchanged; the session also tells the Executors which Python to use and where the Iceberg and Delta tables live.
# - **How:** SHA-256 of each JAR in `/opt/spark/course-jars`; Driver reachable at `spark-jupyter:4050`; 512 MB Driver, 1 GB per Executor; Executors use `/opt/spark/executor-env/bin/python3`; `dfs.client.use.datanode.hostname=true`; Iceberg catalog `local` (type `hadoop`) under `/spark-lab/iceberg-warehouse` and Delta's SQL extension and catalog.
# - 📄 [Spark — Configuration](https://spark.apache.org/docs/4.1.2/configuration.html) · [PySpark — Python package management](https://spark.apache.org/docs/4.1.2/api/python/tutorial/python_packaging.html) · [Iceberg — Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/) · [Delta Lake — Quick start](https://docs.delta.io/latest/quick-start.html)

# %%
import sys
import hashlib
from pyspark.sql import SparkSession
from datetime import datetime

os.environ["HADOOP_USER_NAME"] = "hadoop"

SPARK_JOB_ARCHIVE = SPARK_SHARED_WORKSPACE_DIR / "spark_job_env.tar.gz"
SPARK_JARS = {
    "iceberg-spark-runtime-4.1_2.13-1.12.0.jar": "3123c3798af642dd537230923548e013ef41cc28b6626e5225808cf5670a0f82",
    "delta-spark_2.13-4.3.1.jar": "ebf35a4383f0a653c3ee3c7882c0edcac2f846be31ac61af4b96ccfaaf36c171",
    "delta-storage-4.3.1.jar": "577c12c7e371be4c041714fb48e88ad86e3c3512beea2bdaffbe7a4debf79718",
    "delta-kernel-api-4.3.1.jar": "b081b818d6f5686c7d6406588af72c9f8baf6765a41ada8197364aef90a260e8",
    "delta-kernel-defaults-4.3.1.jar": "27471cca7dd7a36289af2c8d52d2babb37e9e5a13cdaaea76730120f4c72e62f",
    "delta-kernel-unitycatalog-4.3.1.jar": "a288342b7e53da34a608a1a227c8109aa4681fcb582da499ed19347f2193362b",
}
for jar_name, expected_sha256 in SPARK_JARS.items():
    jar_path = SPARK_JARS_DIR / jar_name
    if not jar_path.is_file():
        raise FileNotFoundError(f"Required versioned Spark JAR is missing: {jar_path}")
    actual_sha256 = hashlib.sha256(jar_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"Spark JAR checksum mismatch for {jar_path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

# Driver and executors read the same mounted JARs.
SPARK_CLASSPATH = ":".join(str(SPARK_JARS_DIR / jar_name) for jar_name in SPARK_JARS)
SPARK_ICEBERG_WAREHOUSE = f"{SPARK_HDFS_URI}/spark-lab/iceberg-warehouse"
assert SPARK_JOB_ARCHIVE.is_file(), SPARK_JOB_ARCHIVE
builder = (
    SparkSession.builder.master(f"spark://{SPARK_MASTER_HOST}:{SPARK_MASTER_PORT}")
    .appName(f"SparkLab_{datetime.now().strftime('%Y-%m-%d_%H:%M:%S.%f')}")
    .config("spark.driver.host", SPARK_DRIVER_HOST)
    .config("spark.driver.bindAddress", "0.0.0.0")
    .config("spark.driver.port", SPARK_DRIVER_PORT)
    .config("spark.blockManager.port", SPARK_BLOCK_MANAGER_PORT)
    .config("spark.driver.memory", "512m")
    .config("spark.driver.maxResultSize", "256m")
    .config("spark.sql.session.timeZone", "UTC")
    .config("spark.hadoop.dfs.client.use.datanode.hostname", "true")
    .config("spark.driver.extraClassPath", SPARK_CLASSPATH)
    .config("spark.executor.extraClassPath", SPARK_CLASSPATH)
    .config(
        "spark.executorEnv.PYSPARK_PYTHON",
        f"{SPARK_EXECUTOR_ENV_DIR}/bin/python3",
    )
    .config("spark.executor.memory", "1G")
    .config(
        "spark.executorEnv.PYTHONPATH",
        f"{SPARK_EXECUTOR_ENV_DIR}/lib/python{'.'.join(str(n) for n in sys.version_info[:2])}/site-packages",
    )
    .config(
        "spark.sql.catalog.local.warehouse",
        SPARK_ICEBERG_WAREHOUSE,
    )
    .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.local.type", "hadoop")
    .config(
        "spark.sql.warehouse.dir",
        f"{SPARK_HDFS_URI}/spark-lab/spark-warehouse",
    )
    .config(
        "spark.sql.extensions",
        "io.delta.sql.DeltaSparkSessionExtension,"
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    .config(
        "spark.sql.catalog.spark_catalog",
        "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    )
    .config("spark.sql.catalogImplementation", "in-memory")
)
spark = builder.getOrCreate()

print(f"Spark Version: {spark.version}")
print(f"Scala Version: {spark._jvm.scala.util.Properties.versionString()}")
print("✅ Spark Session is now active.")

# %% [markdown]
# ## 6. Row generator
#
# - **What:** defines `batch_generator`, which yields fake rows (`id, worker, timestamp, first_name, last_name, email, phone, amount`) and records the host that produced each one; then derives the schema from one row.
# - **Why:** the `worker` column shows where each row was created, and the schema is reused by the vectorized generator.
# - **How:** imports happen inside the function because it is sent to the Executors; `socket.gethostname()` gives the container name.
# - 📄 [Faker](https://faker.readthedocs.io/en/master/)

# %%
total_rows = 10000
partitions = 10


def batch_generator(ids):
    import socket
    import random
    from faker import Faker

    node_name = socket.gethostname()
    faker = Faker()
    for _ in ids:
        yield (
            faker.uuid4(),
            node_name,
            faker.date_time(),
            faker.first_name(),
            faker.last_name(),
            faker.email(),
            faker.basic_phone_number(),
            random.random() * 1000.0,
        )

df_column_names = [
    "id",
    "worker",
    "timestamp",
    "first_name",
    "last_name",
    "email",
    "phone",
    "amount",
]
df_column_types = spark.createDataFrame(
    list(batch_generator(range(1))), schema=df_column_names
).schema
print(f"✅ batch_generator schema: {df_column_types}")

# %% [markdown]
# ## 7. Rows built on the Driver, written as CSV
#
# - **What:** builds 10,000 rows in the notebook, spreads them over 10 partitions and writes `faker.csv` to HDFS.
# - **Why:** this is the baseline: `list(batch_generator(...))` runs on the Driver, so every row says `spark-jupyter`; only the write is distributed.
# - **How:** `spark.createDataFrame(...).repartition(10)`, then `write.csv`; the table counts rows per `worker` and `spark_partition_id()`.
# - 📄 [spark_partition_id](https://spark.apache.org/docs/4.1.2/api/python/reference/pyspark.sql/api/pyspark.sql.functions.spark_partition_id.html)

# %%
from pyspark.sql import functions as F
from IPython.display import Markdown, display

df = spark.createDataFrame(
    list(batch_generator(range(total_rows))), df_column_names
).repartition(partitions)
df.write.mode("overwrite").csv(f"{SPARK_DATADIR}/faker.csv")
print(f"✅ Created {SPARK_DATADIR}/faker.csv")

partition_stats = (
    df.withColumn("partition_id", F.spark_partition_id())
    .groupBy("worker", "partition_id")
    .count()
    .orderBy("worker", "partition_id")
)
# partition_stats.show()
display(partition_stats.toPandas())


# %% [markdown]
# ## 8. Rows built on the Executors (RDD), written as Parquet
#
# - **What:** creates the 10,000 rows on the workers and writes `faker.parquet`.
# - **Why:** with `mapPartitions` the generator runs once per partition on the Executors, so the `worker` column now shows `spark-worker-1`, `-2` and `-3`.
# - **How:** `sparkContext.parallelize(range(10000), 10).mapPartitions(batch_generator).toDF(...)`.
# - 📄 [RDD.mapPartitions](https://spark.apache.org/docs/4.1.2/api/python/reference/api/pyspark.RDD.mapPartitions.html) · [Parquet files](https://spark.apache.org/docs/4.1.2/sql-data-sources-parquet.html)

# %%
from IPython.display import Markdown, display

rdd = spark.sparkContext.parallelize(range(total_rows), partitions).mapPartitions(
    batch_generator
)
df = rdd.toDF(df_column_names)
df.write.mode("overwrite").parquet(f"{SPARK_DATADIR}/faker.parquet")
print(f"✅ Created {SPARK_DATADIR}/faker.parquet")

partition_stats = (
    df.withColumn("partition_id", F.spark_partition_id())
    .groupBy("worker", "partition_id")
    .count()
    .orderBy("worker", "partition_id")
)
# partition_stats.show()
display(partition_stats.toPandas())

# %% [markdown]
# ## 9. Rows built on the Executors (pandas UDF)
#
# - **What:** creates the rows a third way and writes them to `/tmp/faker_vectorized.parquet` in HDFS.
# - **Why:** a pandas UDF receives whole batches as pandas objects through Apache Arrow instead of one row at a time.
# - **How:** `spark.range(10000, numPartitions=10)` plus a `@pandas_udf` that returns a struct, expanded with `select("data.*")`.
# - 📄 [pandas_udf](https://spark.apache.org/docs/4.1.2/api/python/reference/pyspark.sql/api/pyspark.sql.functions.pandas_udf.html)

# %%
from pyspark.sql import DataFrame
from pyspark.sql.functions import pandas_udf
import pandas as pd

@pandas_udf(df_column_types)
def generate_batch_vectorized(batch_ser: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(list(batch_generator(batch_ser)))


df: DataFrame = (
    spark.range(total_rows, numPartitions=partitions)
    .withColumn("data", generate_batch_vectorized("id"))
    .select("data.*")
)
# df.write.mode("overwrite").parquet(f"{SPARK_DATADIR}/faker_vectorized.parquet")
# df.coalesce(1).write.mode("overwrite").parquet(f"{SPARK_DATADIR}/faker_vectorized.parquet")
# pdf = df.toPandas()
# pdf.to_parquet(f"{SPARK_DATADIR}/faker_vectorized.parquet", index=False)
df.write.mode("overwrite").parquet(f"{SPARK_HDFS_URI}/tmp/faker_vectorized.parquet")
print(f"✅ Created {SPARK_HDFS_URI}/tmp/faker_vectorized.parquet")


partition_stats = (
    df.withColumn("partition_id", F.spark_partition_id())
    .groupBy("worker", "partition_id")
    .count()
    .orderBy("worker", "partition_id")
)
# partition_stats.show()
display(partition_stats.toPandas())

# %% [markdown]
# ## 10. Read back and check
#
# - **What:** reads the vectorized Parquet file, checks it has exactly 10,000 rows, and shows the latest rows and the most common first names.
# - **Why:** it proves the write succeeded and gives a first DataFrame query.
# - **How:** `spark.read.parquet`, `count()`, `sort(...desc())`, `groupBy("first_name").count()`.
# - 📄 [Parquet files](https://spark.apache.org/docs/4.1.2/sql-data-sources-parquet.html)

# %%
from IPython.display import Markdown, display
from pyspark.sql import functions as F

# Read it back and check the schema/count

# df_verify = spark.read.parquet(f"{SPARK_DATADIR}/faker_vectorized.parquet").repartition(partitions)
# pdf_verify = pd.read_parquet(f"{SPARK_DATADIR}/faker_vectorized.parquet")
# df_verify = spark.createDataFrame(pdf_verify).repartition(partitions)
df_verify = spark.read.parquet(f"{SPARK_HDFS_URI}/tmp/faker_vectorized.parquet").repartition(partitions)
verified_rows = df_verify.count()
assert verified_rows == total_rows, verified_rows
print(f"Generated rows: {verified_rows}")

print("\nFirst 10 by timestamp desc:")
# df_verify.sort(F.col("timestamp").desc()).show(10)
display(df_verify.sort(F.col("timestamp").desc()).limit(10).toPandas())

print("\nFirst 10 by count(first_name) desc:")
# df_verify.groupBy("first_name").count().sort(F.col("count").desc()).show(10)
display(
    df_verify.groupBy("first_name")
    .count()
    .sort(F.col("count").desc())
    .limit(10)
    .toPandas()
)

# %% [markdown]
# ## 11. The same query in SQL
#
# - **What:** registers the DataFrame as the view `df_verify` and sums `amount` per first name with Spark SQL.
# - **Why:** SQL and the DataFrame API run on the same engine; a temporary view lives only in this session.
# - **How:** `createOrReplaceTempView` then `spark.sql("SELECT first_name, SUM(amount) ... GROUP BY first_name")`.
# - 📄 [Spark SQL — Getting started (temporary views)](https://spark.apache.org/docs/4.1.2/sql-getting-started.html)

# %%
from IPython.display import Markdown, display

df_verify.createOrReplaceTempView("df_verify")
df_sparkql = spark.sql("""
    SELECT 
        first_name, 
        SUM(amount) as total_amount,
        COUNT(*) as first_name_count
    FROM df_verify
    GROUP BY first_name
    ORDER BY first_name_count DESC
""")
display(df_sparkql.toPandas())

# %% [markdown]
# ## 12. Delta Lake and Iceberg
#
# - **What:** writes 100 rows as a Delta table at `/tmp/delta-products` and as the Iceberg table `local.default.course_products`, and checks both read back 100 rows.
# - **Why:** it confirms the bundled connectors work end to end against HDFS.
# - **How:** `write.format("delta").save(...)` and `CREATE TABLE ... USING iceberg AS SELECT ...`.
# - 📄 [Delta Lake — Quick start](https://docs.delta.io/latest/quick-start.html) · [Iceberg — Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/)

# %%
delta_path = f"{SPARK_HDFS_URI}/tmp/delta-products"
df_verify.limit(100).write.format("delta").mode("overwrite").save(delta_path)
assert spark.read.format("delta").load(delta_path).count() == 100

spark.sql("DROP TABLE IF EXISTS local.default.course_products")
spark.sql(
    "CREATE TABLE local.default.course_products "
    "USING iceberg AS SELECT * FROM df_verify LIMIT 100"
)
assert spark.table("local.default.course_products").count() == 100
print("✅ Delta Lake and Iceberg writes validated")

# %% [markdown]
# ## 13. SQL directly on a file, then stop
#
# - **What:** runs the same aggregation on the Parquet file without creating a view, then stops the session.
# - **Why:** Spark SQL can query a file path directly; stopping the session frees the workers' cores and memory for the next notebook.
# - **How:** ``SELECT ... FROM parquet.`hdfs://namenode:8020/tmp/faker_vectorized.parquet` `` and `spark.stop()`.
# - 📄 [Run SQL on files directly](https://spark.apache.org/docs/4.1.2/sql-data-sources-load-save-functions.html)

# %%
from IPython.display import Markdown, display

df_sparkql = spark.sql(f"""
    SELECT 
        first_name, 
        SUM(amount) as total_amount,
        COUNT(*) as first_name_count
    FROM parquet.`{SPARK_HDFS_URI}/tmp/faker_vectorized.parquet`
    GROUP BY first_name
    ORDER BY first_name_count DESC
""")
display(df_sparkql.toPandas())

spark.stop()
