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
# # Setup

# %% tags=["parameters"]
# Local mode is the portable default; VPN mode publishes services on this host.
NETWORK_MODE = "local"
VPN_HOST_IP = "10.15.20.100"
VPN_DNS_IP = "10.15.20.1"
VPN_DOMAIN = "vpn.itam.mx"
VPN_CLIENT_ALIAS = "mavasbel"

# %% [markdown]
# Validates the injected network parameters and derives `VPN_CLIENT_DOMAIN`: `NETWORK_MODE` must be lowercase `local` or `vpn`, VPN values must stay in the `10.15.20.*` subnet, and the client alias must be a valid single DNS label.

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
# Declares the Spark cluster topology. This notebook runs inside the `spark-jupyter` container (open it in JupyterLab at port 6888, or execute it there with papermill), so the Driver lives on the same Docker network as the master, the workers and HDFS: every address below is a container name on that network, identical in Local and VPN mode, and no connection ever goes back to the host computer.

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
# ##### Cleaning Spark context

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
# # Spark session

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
# # Data generation

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
# Generates 10,000 rows distributed over 10 partitions with a Faker-based batch generator executed on the workers, writes them as CSV to HDFS, and displays per-worker/per-partition row counts to prove the work was truly distributed.

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
# Regenerates the same dataset through the RDD API (`parallelize` + `mapPartitions`) and writes it as Parquet to HDFS, again displaying per-partition statistics for comparison with the DataFrame path.

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
# Demonstrates a vectorized pandas UDF: the generator runs as Arrow-batched Pandas DataFrames inside `spark.range`, producing the dataset in a third way, which is then written to Parquet under `/tmp` in HDFS with partition stats displayed.

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
# Reads the vectorized Parquet output back from HDFS, asserts the row count matches, and displays the 10 most recent records plus the 10 most frequent first names as verification tables.

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
# Registers the verified DataFrame as a temporary view and runs a Spark SQL aggregation computing total amount and record count per first name, ordered by frequency.

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
# # Delta Lake and Iceberg validation

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
# Queries the Parquet file directly with Spark SQL (no temporary view) using the same aggregation, then stops the Spark session to release the cluster.

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
