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
# # Hadoop — infrastructure (HDFS + YARN)
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
# - **What:** locates the labs-setup root, changes into `hadoop/` and imports `run_command`.
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
MODULE_DIR = LABS_ROOT / "hadoop"
import sys

if str(LABS_ROOT) not in sys.path:
    sys.path.insert(0, str(LABS_ROOT))
from labs_runtime import run_command

os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# ## 4. Cluster topology
#
# - **What:** names, host names and ports of the NameNode (`8020`, UI `9870`), the ResourceManager (`8088` and `8030-8033`, job history `10020`/`19888`), two DataNodes and two NodeManagers; replication factor `2`; image `apache/hadoop:3.4.3`.
# - **Why:** every daemon publishes on the same host, so each worker gets its own ports (`+10` per worker); clients use `127.0.0.1` (Local) or `<container>.<alias>.<domain>` (VPN).
# - **How:** DataNodes advertise `datanode-N.lvh.me` in Local mode (a public name that resolves to `127.0.0.1`) and their VPN name in VPN mode; the image is declared `linux/amd64`, the only platform it is published for, so Apple Silicon runs it under emulation.
# - 📄 [HDFS architecture (replication)](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html)

# %%
HADOOP_START_FROM_SCRATCH = START_FROM_SCRATCH
HADOOP_IMAGE = "apache/hadoop:3.4.3"
# apache/hadoop is published for linux/amd64 only; declaring it makes Apple
# Silicon hosts run it under Docker Desktop's emulation instead of failing to
# find a matching image.
HADOOP_PLATFORM = "linux/amd64"
DOCKER_INTERNAL_HOST = "host.docker.internal"
DOCKER_DNS = [VPN_DNS_IP] if NETWORK_MODE == "vpn" else []
HOST_BIND_IP = VPN_HOST_IP if NETWORK_MODE == "vpn" else "127.0.0.1"

HADOOP_NAMENODE_HOSTNAME = "namenode"
HADOOP_NAMENODE_COMPOSE_HOST = (
    HADOOP_NAMENODE_HOSTNAME
    if NETWORK_MODE == "local"
    else f"{HADOOP_NAMENODE_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
)
HADOOP_NAMENODE_IP = (
    f"{HADOOP_NAMENODE_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
    if NETWORK_MODE == "vpn"
    else "127.0.0.1"
)
HADOOP_NAMENODE_PORT = 8020
HADOOP_NAMENODE_WEBUI_PORT = 9870
HADOOP_NAMENODE_DISTRIBUTED_HOST = (
    f"{HADOOP_NAMENODE_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
    if NETWORK_MODE == "vpn"
    else f"{HADOOP_NAMENODE_HOSTNAME}.lvh.me"
)

HADOOP_RESOURCEMANAGER_HOSTNAME = "resourcemanager"
HADOOP_RESOURCEMANAGER_COMPOSE_HOST = (
    HADOOP_RESOURCEMANAGER_HOSTNAME
    if NETWORK_MODE == "local"
    else f"{HADOOP_RESOURCEMANAGER_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
)
HADOOP_RESOURCEMANAGER_IP = (
    f"{HADOOP_RESOURCEMANAGER_HOSTNAME}.{VPN_CLIENT_DOMAIN}"
    if NETWORK_MODE == "vpn"
    else "127.0.0.1"
)
HADOOP_RESOURCEMANAGER_WEBUI_PORT = 8088
HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT = 8032
HADOOP_RESOURCEMANAGER_TRACKER_PORT = 8031
HADOOP_RESOURCEMANAGER_SCHEDULER_PORT = 8030
HADOOP_RESOURCEMANAGER_ADMIN_PORT = 8033

HADOOP_MAPRED_JOB_HISTORY_PORT = 10020
HADOOP_MAPRED_LOG_SERVER_PORT = 19888

HADOOP_REPLICATION = 2
HADOOP_NUM_WORKERS = 2

HADOOP_DATANODE_NAMES = [f"datanode-{i+1}" for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_HOSTNAMES = [
    f"{name}.{VPN_CLIENT_DOMAIN}" if NETWORK_MODE == "vpn" else f"{name}.lvh.me"
    for name in HADOOP_DATANODE_NAMES
]
HADOOP_DATANODE_COMPOSE_HOSTS = [
    name if NETWORK_MODE == "local" else f"{name}.{VPN_CLIENT_DOMAIN}"
    for name in HADOOP_DATANODE_NAMES
]
HADOOP_DATANODE_IPS = [
    f"{name}.{VPN_CLIENT_DOMAIN}" if NETWORK_MODE == "vpn" else "127.0.0.1"
    for name in HADOOP_DATANODE_NAMES
]
HADOOP_DATANODE_WEBUI_PORTS = [9864 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_TRANSFER_PORTS = [9866 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_DATANODE_IPC_PORTS = [6867 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]

HADOOP_NODEMANAGER_NAMES = [f"nodemanager-{i+1}" for i in range(HADOOP_NUM_WORKERS)]
HADOOP_NODEMANAGER_HOSTNAMES = [
    HADOOP_NODEMANAGER_NAMES[i] for i in range(HADOOP_NUM_WORKERS)
]
HADOOP_NODEMANAGER_COMPOSE_HOSTS = [
    name if NETWORK_MODE == "local" else f"{name}.{VPN_CLIENT_DOMAIN}"
    for name in HADOOP_NODEMANAGER_NAMES
]
HADOOP_NODEMANAGER_IPS = [
    f"{name}.{VPN_CLIENT_DOMAIN}" if NETWORK_MODE == "vpn" else "127.0.0.1"
    for name in HADOOP_NODEMANAGER_NAMES
]
HADOOP_NODEMANAGER_WEBUI_PORTS = [8050 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_NODEMANAGER_RPC_PORTS = [8051 + (i * 10) for i in range(HADOOP_NUM_WORKERS)]
HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS = [
    41000 + (i * 100) for i in range(HADOOP_NUM_WORKERS)
]
HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS = [
    41000 + ((i + 1) * 100) - 1 for i in range(HADOOP_NUM_WORKERS)
]
HADOOP_NODEMANAGER_JOB_LOCALIZER_PORTS = [8040 + i for i in range(HADOOP_NUM_WORKERS)]

HADOOP_WORKDIR = "/opt/hadoop/work-dir"
HADOOP_NAMENODE_NAMEDIR = "/opt/hadoop/dfs/name"
HADOOP_DATANODE_DATADIR = "/opt/hadoop/dfs/data"

HADOOP_HDFS_DATADIR = "/opt/hadoop/work-dir"

# %% [markdown]
# ## 5. Host folder
#
# - **What:** creates `mount/`, which will hold every daemon's state.
# - **Why:** HDFS metadata and blocks survive a container restart.
# - **How:** path built from `MODULE_DIR`.
# - 📄 [Docker — Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

# %%
import os
from pathlib import Path

LOCALHOST_WORKDIR = str(MODULE_DIR.resolve())
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")

Path(DOCKER_MOUNTDIR).mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## 6. Stop the previous cluster
#
# - **What:** with `START_FROM_SCRATCH=True`, removes the containers, network and volumes.
# - **Why:** a fresh build must not reuse an old NameNode; with `False` the running cluster is kept.
# - **How:** `docker compose -f hadoop-cluster.docker-compose.yml down -v` (`check=False`).
# - 📄 [docker compose down](https://docs.docker.com/reference/cli/docker/compose/down/)

# %%
import subprocess

if HADOOP_START_FROM_SCRATCH:
    subprocess.run(
        ["docker", "compose", "-f", "hadoop-cluster.docker-compose.yml", "down", "-v"],
        check=False,
    )
else:
    print("Preserving existing containers and volumes")


# %% [markdown]
# ## 7. Delete the old state and create the mount folders
#
# - **What:** with `START_FROM_SCRATCH=True`, empties `mount/`; then creates every daemon's `work-dir` / `name-dir` / `data-dir`.
# - **Why:** files written by the containers may not be deletable by the host user, and Docker would create a missing bind source as root, which the next reset could not remove.
# - **How:** `rm -rf` runs as root inside a throwaway `busybox:1.36` container; the folders are then created by the notebook itself.
# - 📄 [docker container run](https://docs.docker.com/reference/cli/docker/container/run/) · [Docker — Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

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

if HADOOP_START_FROM_SCRATCH:
    clear_bind_directory(DOCKER_MOUNTDIR)

# Docker otherwise creates a missing bind-mount source directory as root.  Create
# each source ourselves so the next scratch reset can remove the state without a
# host-side ownership repair.
HADOOP_BIND_MOUNT_DIRECTORIES = (
    "namenode/work-dir",
    "namenode/name-dir",
    "resourcemanager/work-dir",
    *(f"{name}/work-dir" for name in HADOOP_DATANODE_NAMES),
    *(f"{name}/data-dir" for name in HADOOP_DATANODE_NAMES),
    *(f"{name}/work-dir" for name in HADOOP_NODEMANAGER_NAMES),
)
for relative_path in HADOOP_BIND_MOUNT_DIRECTORIES:
    (Path(DOCKER_MOUNTDIR) / relative_path).mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## 8. Memory helper
#
# - **What:** defines `extract_mb`, which turns values such as `512`, `2G` or `-Xmx512m` into megabytes.
# - **Why:** the container memory limits are computed from the heap settings in the next cell.
# - **How:** a regular expression reads the number and its `K`/`M`/`G` unit; no unit means megabytes.

# %%
import re


def extract_mb(val_str):
    """
    Extrae el valor numérico de un string de memoria y lo convierte siempre a Megabytes (MB).
    Soporta formatos mezclados como '512', '256M', '2G', '-Xmx2g', '-Xms512000k', etc.
    """
    if not val_str:
        return 0

    # Convierte a string por seguridad y busca un número seguido opcionalmente por una letra (K, M, G)
    # Ejemplo en "-Xmx2g": match.group(1) será "2" y match.group(2) será "g"
    match = re.search(r"(\d+)\s*([kKmMgG]?)", str(val_str))

    if not match:
        return 0

    value = int(match.group(1))
    unit = match.group(2).upper()  # Pasamos a mayúscula para simplificar

    # Hacemos la conversión a Megabytes según la unidad detectada
    if unit == "G":
        return value * 1024  # De Gigabytes a Megabytes
    elif unit == "K":
        return value // 1024  # De Kilobytes a Megabytes (división entera)
    else:
        # Si la unidad es 'M' o no tiene unidad (string vacío),
        # Hadoop y Docker asumen Megabytes por defecto.
        return value


# %% [markdown]
# ## 9. Hadoop configuration and Compose file
#
# - **What:** builds the Hadoop settings and generates `hadoop-cluster.docker-compose.yml` with the NameNode, the ResourceManager (plus the job history server) and the two DataNode / NodeManager pairs.
# - **Why:** one set of settings is shared by every daemon; the memory limits leave room for each JVM so the kernel does not kill a daemon (the ResourceManager also hosts the `hadoop jar` client JVMs).
# - **How:** the image turns variables named `CORE-SITE.XML_<key>`, `HDFS-SITE.XML_<key>`, `YARN-SITE.XML_<key>` and `MAPRED-SITE.XML_<key>` into those XML files. Key settings: `fs.defaultFS=hdfs://namenode:8020`, `dfs.replication=2`, `dfs.datanode.use.datanode.hostname` and `dfs.client.use.datanode.hostname` set to `true` (clients reach each DataNode by its name, not by its internal Docker IP), YARN with 1792 MB and 2 vcores per NodeManager, MapReduce on YARN. The NameNode formats its folder only the first time.
# - 📄 [apache/hadoop image — envtoconf.py](https://raw.githubusercontent.com/apache/hadoop/docker-hadoop-runner-latest/scripts/envtoconf.py) · [core-default.xml](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/core-default.xml) · [hdfs-default.xml](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-hdfs/hdfs-default.xml) · [HDFS — Multihomed networks](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-hdfs/HdfsMultihoming.html) · [yarn-default.xml](https://hadoop.apache.org/docs/r3.4.3/hadoop-yarn/hadoop-yarn-common/yarn-default.xml) · [mapred-default.xml](https://hadoop.apache.org/docs/r3.4.3/hadoop-mapreduce-client/hadoop-mapreduce-client-core/mapred-default.xml)

# %%
import os
import yaml
from IPython.display import Markdown, display

# Configs can be valited in the running containers with
# hdfs getconf -confKey {key}
# or printing
# Four principal servicios
# # cat $HADOOP_HOME/etc/hadoop/core-site.xml       # fs.defaultFS, trash, security, proxyuser
# # cat $HADOOP_HOME/etc/hadoop/hdfs-site.xml       # replication, block size, permissions, namenode dirs
# # cat $HADOOP_HOME/etc/hadoop/yarn-site.xml       # resourcemanager, nodemanager, memory
# # cat $HADOOP_HOME/etc/hadoop/mapred-site.xml     # framework, classpath, JVM opts
# Daemons env vars
# # cat $HADOOP_HOME/etc/hadoop/hadoop-env.sh       # JAVA_HOME, HADOOP_HEAPSIZE, HADOOP_LOG_DIR
# # cat $HADOOP_HOME/etc/hadoop/yarn-env.sh         # YARN_HEAPSIZE, YARN_LOG_DIR
# # cat $HADOOP_HOME/etc/hadoop/mapred-env.sh       # HADOOP_JOB_HISTORYSERVER_HEAPSIZE
# Workers / topology
# # cat $HADOOP_HOME/etc/hadoop/workers             # DataNodes/NodeManagers
# # cat $HADOOP_HOME/etc/hadoop/masters             # SecondaryNameNode
# Logging
# # cat $HADOOP_HOME/etc/hadoop/log4j.properties    # Log levels per component
# Scheduler capacity
# # cat $HADOOP_HOME/etc/hadoop/capacity-scheduler.xml
# All of them
# for f in $HADOOP_HOME/etc/hadoop/*.xml; do
#     echo ""; echo "════════ $f ════════"; cat $f
# done

env_content = {
    # ==========================================
    # VARIABLES DE ENTORNO Y HEAP (MEMORIA DEMONIOS)
    # ==========================================
    "HADOOP_HOME": "/opt/hadoop",
    "HADOOP_WORKDIR": HADOOP_WORKDIR,
    "HADOOP_HEAPSIZE_MAX": "512",
    "HDFS_NAMENODE_OPTS": "-Xmx512m",
    "HDFS_DATANODE_OPTS": "-Xmx512m",  # Heap estricto para el DataNode
    "YARN_HEAPSIZE": "512",
    # ==========================================
    # CORE-SITE.XML (CONFIGURACIONES GENERALES)
    # ==========================================
    "CORE-SITE.XML_fs.defaultFS": f"hdfs://{HADOOP_NAMENODE_HOSTNAME}:{HADOOP_NAMENODE_PORT}",
    "CORE-SITE.XML_fs.trash.interval": "1440",  # Tiempo de vida de la papelera en minutos (1440 = 24h)
    "CORE-SITE.XML_fs.trash.checkpoint.interval": "60",  # Cada 60 minutos crea un nuevo checkpoint en .Trash
    "CORE-SITE.XML_hadoop.proxyuser.hive.hosts": "*",
    "CORE-SITE.XML_hadoop.proxyuser.hive.groups": "*",
    "CORE-SITE.XML_hadoop.security.authentication": "simple",  # Sin Kerberos
    # [NUEVOS PARÁMETROS CORE]
    "CORE-SITE.XML_hadoop.tmp.dir": "/opt/hadoop/tmp",  # Directorio temporal seguro (evita /tmp del SO)
    "CORE-SITE.XML_io.file.buffer.size": "131072",  # Búfer de I/O aumentado a 128KB para mejor rendimiento
    # ==========================================
    # HDFS-SITE.XML (NAMENODE Y DATANODES)
    # ==========================================
    "HDFS-SITE.XML_dfs.replication": HADOOP_REPLICATION,
    "HDFS-SITE.XML_dfs.permissions.enabled": "true",  # Aplica permisos POSIX
    "HDFS-SITE.XML_dfs.namenode.name.dir": HADOOP_NAMENODE_NAMEDIR,
    "HDFS-SITE.XML_dfs.namenode.name.dir.perm": "775",
    "HDFS-SITE.XML_dfs.namenode.datanode.registration.ip-hostname-check": "false",  # Para que no intente resolucion DNS inversa
    "HDFS-SITE.XML_dfs.datanode.data.dir": HADOOP_DATANODE_DATADIR,
    "HDFS-SITE.XML_dfs.datanode.use.datanode.hostname": "true",
    "HDFS-SITE.XML_dfs.client.use.datanode.hostname": "true",  # El cliente escribe a cada DataNode por su nombre (alias de la red o, en VPN, el publicado), no por su IP interna de Docker
    # [NUEVOS PARÁMETROS HDFS]
    "HDFS-SITE.XML_dfs.blocksize": "134217728",  # Tamaño de bloque en bytes (134217728 = 128 MB)
    "HDFS-SITE.XML_dfs.namenode.handler.count": "20",  # Número de hilos del NameNode para peticiones
    "HDFS-SITE.XML_dfs.datanode.failed.volumes.tolerated": "0",  # Discos que pueden fallar antes de apagar el nodo (0 es ideal para 1 solo disco)
    # ==========================================
    # YARN-SITE.XML (RESOURCEMANAGER Y NODEMANAGER)
    # ==========================================
    "YARN-SITE.XML_yarn.resourcemanager.hostname": HADOOP_RESOURCEMANAGER_HOSTNAME,
    "YARN-SITE.XML_yarn.resourcemanager.resource-tracker.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}",
    "YARN-SITE.XML_yarn.nodemanager.aux-services": "mapreduce_shuffle",
    "YARN-SITE.XML_yarn.nodemanager.vmem-check-enabled": "true",
    "YARN-SITE.XML_yarn.nodemanager.resource.memory-mb": "1792",  # Memoria total que YARN puede repartir en un nodo
    "YARN-SITE.XML_yarn.scheduler.maximum-allocation-mb": "1536",  # Tamaño máximo de un solo contenedor
    "YARN-SITE.XML_yarn.scheduler.minimum-allocation-mb": "128",  # Tamaño mínimo de asignación
    "YARN-SITE.XML_yarn.log-aggregation-enable": "true",
    "YARN-SITE.XML_yarn.log.server.url": f"http://{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_MAPRED_LOG_SERVER_PORT}/jobhistory/logs",
    # [NUEVOS PARÁMETROS YARN]
    "YARN-SITE.XML_yarn.resourcemanager.scheduler.class": "org.apache.hadoop.yarn.server.resourcemanager.scheduler.capacity.CapacityScheduler",  # Programador de colas
    "YARN-SITE.XML_yarn.nodemanager.resource.cpu-vcores": "2",  # Número de vCores que el nodo puede prestar (Ajustar según tu CPU)
    "YARN-SITE.XML_yarn.nodemanager.local-dirs": "/opt/hadoop/data/yarn/local",  # Dónde guardan los contenedores sus temporales
    # "YARN-SITE.XML_yarn.resourcemanager.nodes.include-path": "/opt/hadoop/etc/hadoop/includes.txt", # (Descomentar si usas archivos de allowlist)
    # "YARN-SITE.XML_yarn.resourcemanager.nodes.exclude-path": "/opt/hadoop/etc/hadoop/excludes.txt", # (Descomentar si usas archivos de blocklist)
    # ==========================================
    # MAPRED-SITE.XML (MAPREDUCE)
    # ==========================================
    "MAPRED-SITE.XML_mapreduce.framework.name": "yarn",
    "MAPRED-SITE.XML_mapreduce.jobhistory.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_MAPRED_JOB_HISTORY_PORT}",
    "MAPRED-SITE.XML_mapreduce.jobhistory.webapp.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_MAPRED_LOG_SERVER_PORT}",
    "MAPRED-SITE.XML_mapreduce.application.classpath": ":".join(
        [
            "/opt/hadoop/share/hadoop/mapreduce/*",
            "/opt/hadoop/share/hadoop/common/*",
            "/opt/hadoop/share/hadoop/common/lib/*",
            "/opt/hadoop/share/hadoop/hdfs/*",
            "/opt/hadoop/share/hadoop/hdfs/lib/*",
            "/opt/hadoop/share/hadoop/yarn/*",
            "/opt/hadoop/share/hadoop/yarn/lib/*",
        ]
    ),
}
# Path("envs").mkdir(parents=True, exist_ok=True)
# with open("envs/common.env", "w") as f:
#     for key, value in env_content.items():
#         f.write(f"{key}={value}\n")

# Definimos el margen de seguridad para Docker y SO (Overhead)
DOCKER_OVERHEAD_MB = 128

# Extraemos las variables del env_content
global_heap = extract_mb(env_content.get("HADOOP_HEAPSIZE_MAX", "512"))
namenode_heap = extract_mb(env_content.get("HDFS_NAMENODE_OPTS")) or global_heap
datanode_heap = extract_mb(env_content.get("HDFS_DATANODE_OPTS")) or global_heap
yarn_heap = extract_mb(env_content.get("YARN_HEAPSIZE", "512"))
# Memoria extra exclusiva del NodeManager (los contenedores)
yarn_nodemanager_vault = extract_mb(
    env_content.get("YARN-SITE.XML_yarn.nodemanager.resource.memory-mb", "2048")
)

# Calculamos los límites reales de Docker (como strings listos para el Compose)
# Limit = Memoria del Demonio + Overhead
NAMENODE_DOCKER_LIMIT = f"{namenode_heap + DOCKER_OVERHEAD_MB}M"
DATANODE_DOCKER_LIMIT = f"{datanode_heap + DOCKER_OVERHEAD_MB}M"
# Jobs are submitted with `docker exec resourcemanager hadoop jar ...`, so each
# client JVM (heap up to HADOOP_HEAPSIZE_MAX) shares the container with the
# ResourceManager. Without that allowance the kernel OOM-killed the
# ResourceManager after 22 streaming jobs (measured 2026-10-09).
RESOURCEMANAGER_DOCKER_LIMIT = f"{yarn_heap + global_heap + 2 * DOCKER_OVERHEAD_MB}M"
NODEMANAGER_DOCKER_LIMIT = f"{yarn_heap + yarn_nodemanager_vault + DOCKER_OVERHEAD_MB}M"  # El NodeManager es la suma (Memoria del Demonio + Memoria para Trabajos + Overhead)

hadoop_compose_file_name = "hadoop-cluster.docker-compose.yml"
namenode_ports = [
    f"{HOST_BIND_IP}:{HADOOP_NAMENODE_PORT}:{HADOOP_NAMENODE_PORT}",
    f"{HOST_BIND_IP}:{HADOOP_NAMENODE_WEBUI_PORT}:{HADOOP_NAMENODE_WEBUI_PORT}",
]

hadoop_compose_dict = {
    "name": "hadoop-cluster",
    "networks": {
        "hadoop-cluster": {"name": "hadoop-network", "driver": "bridge"},
        # "hadoop-namenode": {"driver": "bridge"},
        # "hadoop-datanodes": {"driver": "bridge"},
        # "hadoop-resourcemanager": {"driver": "bridge"},
        # "hadoop-nodemanagers": {"driver": "bridge"},
    },
    "services": {
        "namenode": {
            "image": HADOOP_IMAGE,
            "platform": HADOOP_PLATFORM,
            "container_name": "namenode",
            "command": [
                "bash",
                "-c",
                " ".join(
                    [
                        f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_WORKDIR} &&",
                        f"sudo mkdir -p {HADOOP_NAMENODE_NAMEDIR} &&",
                        f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_NAMENODE_NAMEDIR} &&",
                        f"if [ ! -d {HADOOP_NAMENODE_NAMEDIR}/current ]; then hdfs namenode -Ddfs.namenode.name.dir={HADOOP_NAMENODE_NAMEDIR} -format -force; fi &&",
                        "hdfs",
                        "namenode",
                        f"-Dfs.defaultFS=hdfs://{HADOOP_NAMENODE_HOSTNAME}:{HADOOP_NAMENODE_PORT}",
                        # f"-Ddfs.replication={HADOOP_REPLICATION}",
                        # f"-Ddfs.namenode.name.dir={HADOOP_NAMENODE_NAMEDIR}",
                        # "-Ddfs.namenode.name.dir.perm=775",
                        # "-Ddfs.permissions.enabled=false",
                        # f"-Ddfs.namenode.rpc-address=0.0.0.0:{HADOOP_NAMENODE_PORT}",
                        # f"-Ddfs.namenode.http-address=0.0.0.0:{HADOOP_NAMENODE_WEBUI_PORT}",
                    ]
                ),
            ],
            # "env_file": ["envs/common.env"],
            "environment": env_content.copy()
            | {
                "HDFS-SITE.XML_dfs.namenode.rpc-address": f"0.0.0.0:{HADOOP_NAMENODE_PORT}",
                "HDFS-SITE.XML_dfs.namenode.http-address": f"0.0.0.0:{HADOOP_NAMENODE_WEBUI_PORT}",
            },
            "volumes": [
                f"{os.path.join(DOCKER_MOUNTDIR, 'namenode', 'work-dir')}:{HADOOP_WORKDIR}",
                f"{os.path.join(DOCKER_MOUNTDIR, 'namenode', 'name-dir')}:{HADOOP_NAMENODE_NAMEDIR}",
            ],
            "networks": {
                "hadoop-cluster": {"aliases": [HADOOP_NAMENODE_DISTRIBUTED_HOST]}
            },
            "hostname": HADOOP_NAMENODE_COMPOSE_HOST,
            "ports": namenode_ports,
            "extra_hosts": [
                f"{DOCKER_INTERNAL_HOST}:host-gateway",
            ],
            "dns": DOCKER_DNS,
            "deploy": {
                "resources": {
                    "limits": {"cpus": "1.0", "memory": NAMENODE_DOCKER_LIMIT}
                }
            },
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    f"bash -c '</dev/tcp/127.0.0.1/{HADOOP_NAMENODE_WEBUI_PORT}' 2>/dev/null || exit 1",
                ],
                "interval": "5s",  # Docker hará la prueba cada 5 segundos
                "timeout": "5s",  # Si el NameNode tarda más de 5s en responder, cuenta como fallo
                "retries": 30,  # Si falla 3 veces seguidas, el contenedor se marca como "unhealthy"
                "start_period": "5s",  # Tiempo de gracia inicial (Hadoop necesita tiempo para formatear y arrancar la JVM)
            },
        },
        "resourcemanager": {
            "image": HADOOP_IMAGE,
            "platform": HADOOP_PLATFORM,
            "container_name": "resourcemanager",
            "command": [
                "bash",
                "-c",
                " ".join(
                    [
                        f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_WORKDIR} &&",
                        f"mapred --daemon start historyserver &&",
                        "yarn",
                        "resourcemanager",
                        # f"-Dfs.defaultFS=hdfs://{HADOOP_NAMENODE_HOSTNAME}:{HADOOP_NAMENODE_PORT}",
                        # f"-Dyarn.resourcemanager.hostname={HADOOP_RESOURCEMANAGER_HOSTNAME}",
                        # f"-Dyarn.resourcemanager.webapp.address=0.0.0.0:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}",
                        # f"-Dyarn.resourcemanager.address=0.0.0.0:{HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT}",
                        # f"-Dyarn.resourcemanager.scheduler.address=0.0.0.0:{HADOOP_RESOURCEMANAGER_SCHEDULER_PORT}",
                        # f"-Dyarn.resourcemanager.resource-tracker.address=0.0.0.0:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}",
                        # f"-Dyarn.resourcemanager.admin.address=0.0.0.0:{HADOOP_RESOURCEMANAGER_ADMIN_PORT}",
                    ]
                ),
            ],
            # "env_file": ["envs/common.env"],
            "environment": env_content.copy()
            | {
                "YARN-SITE.XML_yarn.resourcemanager.bind-host": "0.0.0.0",
                "YARN-SITE.XML_yarn.resourcemanager.webapp.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}",
                "YARN-SITE.XML_yarn.resourcemanager.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT}",
                "YARN-SITE.XML_yarn.resourcemanager.scheduler.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_SCHEDULER_PORT}",
                "YARN-SITE.XML_yarn.resourcemanager.resource-tracker.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}",
                "YARN-SITE.XML_yarn.resourcemanager.admin.address": f"{HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_ADMIN_PORT}",
            },
            "volumes": [
                f"{os.path.join(DOCKER_MOUNTDIR, 'resourcemanager', 'work-dir')}:{HADOOP_WORKDIR}",
            ],
            "networks": ["hadoop-cluster"],
            "hostname": HADOOP_RESOURCEMANAGER_COMPOSE_HOST,
            "ports": [
                f"{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT}:{HADOOP_RESOURCEMANAGER_RPC_APP_MANAGER_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_SCHEDULER_PORT}:{HADOOP_RESOURCEMANAGER_SCHEDULER_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_ADMIN_PORT}:{HADOOP_RESOURCEMANAGER_ADMIN_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_MAPRED_JOB_HISTORY_PORT}:{HADOOP_MAPRED_JOB_HISTORY_PORT}",
                f"{HOST_BIND_IP}:{HADOOP_MAPRED_LOG_SERVER_PORT}:{HADOOP_MAPRED_LOG_SERVER_PORT}",
            ],
            "extra_hosts": [
                f"{DOCKER_INTERNAL_HOST}:host-gateway",
            ],
            "dns": DOCKER_DNS,
            "depends_on": {"namenode": {"condition": "service_healthy"}},
            "deploy": {
                "resources": {
                    "limits": {"cpus": "2.0", "memory": RESOURCEMANAGER_DOCKER_LIMIT}
                }
            },
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    f"bash -c '</dev/tcp/127.0.0.1/{HADOOP_RESOURCEMANAGER_WEBUI_PORT}' 2>/dev/null || exit 1",
                ],
                "interval": "5s",
                "timeout": "5s",
                "retries": 30,
                "start_period": "5s",  # Un poco menos que el NN porque no tiene que formatear discos
            },
        },
    },
}


for i in range(0, HADOOP_NUM_WORKERS):

    # Programmatically add DataNodes
    hadoop_compose_dict["services"][HADOOP_DATANODE_NAMES[i]] = {
        "image": HADOOP_IMAGE,
        "platform": HADOOP_PLATFORM,
        "container_name": HADOOP_DATANODE_NAMES[i],
        "command": [
            "bash",
            "-c",
            " ".join(
                [
                    f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_WORKDIR} &&",
                    f"sudo mkdir -p {HADOOP_DATANODE_DATADIR} &&",
                    f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_DATANODE_DATADIR} &&",
                    "hdfs",
                    "datanode",
                    # f"-Dfs.defaultFS=hdfs://{HADOOP_NAMENODE_HOSTNAME}:{HADOOP_NAMENODE_PORT}",
                    # f"-Ddfs.datanode.data.dir={HADOOP_DATANODE_DATADIR}",
                    # "-Ddfs.datanode.data.dir.perm=775",
                    # "-Ddfs.permissions.enabled=false",
                    # f"-Ddfs.datanode.address=0.0.0.0:{HADOOP_DATANODE_TRANSFER_PORTS[i]}",
                    # f"-Ddfs.datanode.http.address=0.0.0.0:{HADOOP_DATANODE_WEBUI_PORTS[i]}",
                    # f"-Ddfs.datanode.ipc.address=0.0.0.0:{HADOOP_DATANODE_IPC_PORTS[i]}",
                    # "-Ddfs.datanode.use.datanode.hostname=true",
                ]
            ),
        ],
        # "env_file": ["envs/common.env"],
        "environment": env_content.copy()
        | {
            "HDFS-SITE.XML_dfs.datanode.address": f"0.0.0.0:{HADOOP_DATANODE_TRANSFER_PORTS[i]}",
            "HDFS-SITE.XML_dfs.datanode.http.address": f"0.0.0.0:{HADOOP_DATANODE_WEBUI_PORTS[i]}",
            "HDFS-SITE.XML_dfs.datanode.ipc.address": f"0.0.0.0:{HADOOP_DATANODE_IPC_PORTS[i]}",
            "HDFS-SITE.XML_dfs.datanode.hostname": HADOOP_DATANODE_HOSTNAMES[i],
        },
        "volumes": [
            f"{os.path.join(DOCKER_MOUNTDIR, HADOOP_DATANODE_NAMES[i], 'work-dir')}:{HADOOP_WORKDIR}",
            f"{os.path.join(DOCKER_MOUNTDIR, HADOOP_DATANODE_NAMES[i], 'data-dir')}:{HADOOP_DATANODE_DATADIR}",
        ],
        "networks": {
            "hadoop-cluster": {"aliases": [HADOOP_DATANODE_HOSTNAMES[i]]}
        },
        "hostname": HADOOP_DATANODE_COMPOSE_HOSTS[i],
        "ports": [
            f"{HOST_BIND_IP}:{HADOOP_DATANODE_WEBUI_PORTS[i]}:{HADOOP_DATANODE_WEBUI_PORTS[i]}",
            f"{HOST_BIND_IP}:{HADOOP_DATANODE_TRANSFER_PORTS[i]}:{HADOOP_DATANODE_TRANSFER_PORTS[i]}",
            f"{HOST_BIND_IP}:{HADOOP_DATANODE_IPC_PORTS[i]}:{HADOOP_DATANODE_IPC_PORTS[i]}",
        ],
        "extra_hosts": [
            f"{DOCKER_INTERNAL_HOST}:host-gateway",
        ],
        "dns": DOCKER_DNS,
        "deploy": {
            "resources": {"limits": {"cpus": "1.0", "memory": DATANODE_DOCKER_LIMIT}}
        },
        "depends_on": {
            "namenode": {"condition": "service_healthy"},
            # "resourcemanager": {"condition": "service_healthy"},
        }
        | {
            HADOOP_DATANODE_NAMES[j]: {"condition": "service_started"}
            for j in range(0, i)
        },
    }

    # Programmatically add NodeManagers
    hadoop_compose_dict["services"][HADOOP_NODEMANAGER_NAMES[i]] = {
        "image": HADOOP_IMAGE,
        "platform": HADOOP_PLATFORM,
        "container_name": HADOOP_NODEMANAGER_NAMES[i],
        "command": [
            "bash",
            "-c",
            " ".join(
                [
                    f"sudo chown -R $(id -u hadoop):$(id -g hadoop) {HADOOP_WORKDIR} &&",
                    "yarn",
                    "nodemanager",
                    # f"-Dyarn.resourcemanager.hostname={HADOOP_RESOURCEMANAGER_HOSTNAME}",
                    # f"-Dyarn.nodemanager.aux-services=mapreduce_shuffle",
                    # f"-Dyarn.resourcemanager.resource-tracker.address={HADOOP_RESOURCEMANAGER_HOSTNAME}:{HADOOP_RESOURCEMANAGER_TRACKER_PORT}",
                    # f"-Dyarn.nodemanager.address=0.0.0.0:{HADOOP_NODEMANAGER_RPC_PORTS[i]}",
                    # f"-Dyarn.nodemanager.webapp.address=0.0.0.0:{HADOOP_NODEMANAGER_WEBUI_PORTS[i]}",
                ]
            ),
        ],
        # "env_file": ["envs/common.env"],
        "environment": env_content.copy()
        | {
            "YARN-SITE.XML_yarn.nodemanager.hostname": HADOOP_NODEMANAGER_HOSTNAMES[i],
            "YARN-SITE.XML_yarn.nodemanager.address": f"0.0.0.0:{HADOOP_NODEMANAGER_RPC_PORTS[i]}",
            "YARN-SITE.XML_yarn.nodemanager.webapp.address": f"0.0.0.0:{HADOOP_NODEMANAGER_WEBUI_PORTS[i]}",
            # "YARN-SITE.XML_yarn.nodemanager.localizer.port": f"{HADOOP_NODEMANAGER_JOB_LOCALIZER_PORTS[i]}",
            # "YARN-SITE.XML_yarn.app.mapreduce.am.job.client.port-range": f"{HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}",
            # "TEZ-SITE.XML_tez.am.client.am.port-range": f"{HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}",
            # "TEZ-SITE.XML_tez.am.hostname": "0.0.0.0",
            # "TEZ-SITE.XML_tez.am.hostname": HADOOP_NODEMANAGER_HOSTNAMES[i],
            # "TEZ-SITE.XML_tez.am.launch.cmd-opts": " ".join(
            #     [
            #         f"-Djava.net.preferIPv4Stack=true",
            #         f"-Dtez.am.client.am.port-range={HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}",
            #         f"-Dhadoop.rpc.protection=authentication",
            #     ]
            # ),
            # "HADOOP_OPTS": " ".join(
            #     [
            #         f"-Dyarn.app.mapreduce.am.job.client.port-range={HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}",
            #         f"-Dtez.am.client.am.port-range={HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}",
            #     ]
            # ),
        },
        "volumes": [
            f"{os.path.join(DOCKER_MOUNTDIR, HADOOP_NODEMANAGER_NAMES[i], 'work-dir')}:{HADOOP_WORKDIR}",
        ],
        "networks": ["hadoop-cluster"],
        "hostname": HADOOP_NODEMANAGER_COMPOSE_HOSTS[i],
        "ports": [
            f"{HOST_BIND_IP}:{HADOOP_NODEMANAGER_WEBUI_PORTS[i]}:{HADOOP_NODEMANAGER_WEBUI_PORTS[i]}",
            f"{HOST_BIND_IP}:{HADOOP_NODEMANAGER_RPC_PORTS[i]}:{HADOOP_NODEMANAGER_RPC_PORTS[i]}",
            # (
            #     f"{HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}"
            #     f":"
            #     f"{HADOOP_NODEMANAGER_JOB_CLIENT_START_PORTS[i]}-{HADOOP_NODEMANAGER_JOB_CLIENT_END_PORTS[i]}"
            # ),
            # f"{HADOOP_NODEMANAGER_JOB_LOCALIZER_PORTS[i]}:{HADOOP_NODEMANAGER_JOB_LOCALIZER_PORTS[i]}",
            # "50000-50005:50000-50005",
        ],
        "extra_hosts": [
            f"{DOCKER_INTERNAL_HOST}:host-gateway",
        ],
        "dns": DOCKER_DNS,
        "deploy": {
            "resources": {"limits": {"cpus": "2.0", "memory": NODEMANAGER_DOCKER_LIMIT}}
        },
        "depends_on": {
            "namenode": {"condition": "service_healthy"},
            "resourcemanager": {"condition": "service_healthy"},
        }
        | {
            HADOOP_DATANODE_NAMES[j]: {"condition": "service_started"}
            for j in range(HADOOP_NUM_WORKERS)
        }
        | {
            HADOOP_NODEMANAGER_NAMES[j]: {"condition": "service_started"}
            for j in range(0, i)
        },
    }


hadoop_compose_yaml_contents = yaml.dump(
    hadoop_compose_dict, default_flow_style=False, sort_keys=False, indent=4
)
with open(
    os.path.join(LOCALHOST_WORKDIR, hadoop_compose_file_name), "w",
    encoding="utf-8", newline="\n",
) as hadoop_compose_file:
    hadoop_compose_file.write(hadoop_compose_yaml_contents)
print(
    f"Successfully created: {os.path.relpath(os.path.join(LOCALHOST_WORKDIR,hadoop_compose_file_name))}"
)
display(Markdown(f"```yaml\n{hadoop_compose_yaml_contents}\n```"))

# %% [markdown]
# ## 10. Start Hadoop
#
# - **What:** starts the cluster and waits until the NameNode and ResourceManager health checks pass.
# - **Why:** the DataNodes and NodeManagers start only after the NameNode (and ResourceManager) are healthy.
# - **How:** `docker compose up -d --wait`; the health checks open the web UI ports `9870` and `8088`.
# - 📄 [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/) · [Hadoop cluster setup](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/ClusterSetup.html)

# %%
run_command(["docker", "compose", "-f", "hadoop-cluster.docker-compose.yml", "up", "-d", "--wait"])

# %% [markdown]
# ## 11. Wait for the NodeManagers
#
# - **What:** waits up to 300 s until YARN reports 2 active NodeManagers.
# - **Why:** NodeManagers have no health check, so `--wait` can return before they register; a job submitted then would wait for capacity.
# - **How:** polls `GET /ws/v1/cluster/metrics` every 5 s and reads `activeNodes`.
# - 📄 [ResourceManager REST API](https://hadoop.apache.org/docs/r3.4.3/hadoop-yarn/hadoop-yarn-site/ResourceManagerRest.html)

# %%
import time

import requests

yarn_metrics_url = f"http://{HOST_BIND_IP}:{HADOOP_RESOURCEMANAGER_WEBUI_PORT}/ws/v1/cluster/metrics"
deadline = time.monotonic() + 300
active_nodes = None
while time.monotonic() < deadline:
    try:
        active_nodes = requests.get(yarn_metrics_url, timeout=10).json()["clusterMetrics"]["activeNodes"]
    except (requests.RequestException, KeyError, ValueError):
        active_nodes = None
    if active_nodes == HADOOP_NUM_WORKERS:
        break
    time.sleep(5)
assert active_nodes == HADOOP_NUM_WORKERS, f"YARN active NodeManagers: {active_nodes}, expected {HADOOP_NUM_WORKERS}"
print(f"✅ YARN reports {active_nodes} active NodeManagers")
