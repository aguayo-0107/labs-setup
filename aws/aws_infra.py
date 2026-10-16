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
# # Setup
#
# Local AWS environment for the AWS lab: no AWS account, no credentials, no cost.
# Moto emulates S3, DynamoDB, IAM, STS and Lambda (running each function in a
# real Lambda runtime container), and an Athena-compatible gateway runs Athena
# queries on its own HiveServer2 engine, which reads the data from Moto's S3.

# %% tags=["parameters"]
# Local mode is the portable default; VPN mode publishes services on this host.
NETWORK_MODE = "local"
VPN_HOST_IP = "10.15.20.100"
VPN_DNS_IP = "10.15.20.1"
VPN_DOMAIN = "vpn.itam.mx"
VPN_CLIENT_ALIAS = "mavasbel"
START_FROM_SCRATCH = False

# %% [markdown]
# Validates the papermill-injected NETWORK_MODE and VPN_CLIENT_ALIAS values and derives VPN_CLIENT_DOMAIN as `<alias>.<VPN_DOMAIN>` for later VPN-mode host naming.

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
# Locates the labs-setup root by walking parent directories for a pyproject.toml alongside the cassandra and mongodb module folders, then changes into the aws module directory.

# %%
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
    raise RuntimeError("Could not find the labs-setup root from the current directory")
MODULE_DIR = LABS_ROOT / "aws"
os.chdir(MODULE_DIR)
print(f"Working directory: {MODULE_DIR}")

# %% [markdown]
# Declares the services: Moto (S3, DynamoDB, IAM with AWS managed policies loaded, STS, Lambda) on host port 5050, the Athena gateway on 5051, and the internal HiveServer2 engine. Images are pinned; the Lambda runtime image is pinned by digest because its tag is rebuilt upstream. Credentials are dummy values: nothing here can reach a real AWS account.

# %%
AWS_START_FROM_SCRATCH = START_FROM_SCRATCH
DOCKER_DNS = [VPN_DNS_IP] if NETWORK_MODE == "vpn" else []
HOST_BIND_IP = VPN_HOST_IP if NETWORK_MODE == "vpn" else "127.0.0.1"


def vpn_fqdn(container_name):
    return f"{container_name}.{VPN_CLIENT_DOMAIN}"


def client_host(container_name):
    return "127.0.0.1" if NETWORK_MODE == "local" else vpn_fqdn(container_name)


AWS_NETWORK_NAME = "aws-network"
AWS_REGION = "us-east-1"
AWS_DUMMY_KEY_ID = "test"
AWS_DUMMY_SECRET = "test"
MOTO_ACCOUNT_ID = "123456789012"

MOTO_CONTAINER_NAME = "motoserver"
MOTO_IMAGE = "motoserver/moto:5.2.4"
MOTO_INTERNAL_PORT = 5000
MOTO_EXTERNAL_PORT = 5050
LAMBDA_RUNTIME_IMAGE = (
    "ghcr.io/shogo82148/lambda-python"
    "@sha256:319b8cf1e9f03a32d89d82acba66a9927edb6cde21910734cc2f0bdd470198e4"
)

ATHENA_ENGINE_CONTAINER_NAME = "athena-engine"
ATHENA_ENGINE_IMAGE = "apache/hive:4.0.1"
ATHENA_ENGINE_PORT = 10000

ATHENA_GATEWAY_CONTAINER_NAME = "athena-gateway"
ATHENA_GATEWAY_IMAGE = "labs-athena-gateway:1"
ATHENA_GATEWAY_INTERNAL_PORT = 8080
ATHENA_GATEWAY_EXTERNAL_PORT = 5051

MOTO_CLIENT_URL = f"http://{client_host(MOTO_CONTAINER_NAME)}:{MOTO_EXTERNAL_PORT}"
ATHENA_CLIENT_URL = f"http://{client_host(ATHENA_GATEWAY_CONTAINER_NAME)}:{ATHENA_GATEWAY_EXTERNAL_PORT}"
MOTO_INTERNAL_URL = f"http://{MOTO_CONTAINER_NAME}:{MOTO_INTERNAL_PORT}"
print(f"Moto: {MOTO_CLIENT_URL} | Athena: {ATHENA_CLIENT_URL}")

# %% [markdown]
# Creates the bind mount directory that holds the engine's S3 configuration and the client configuration files.

# %%
LOCALHOST_WORKDIR = str(MODULE_DIR.resolve())
DOCKER_MOUNTDIR = os.path.join(LOCALHOST_WORKDIR, "mount")
Path(DOCKER_MOUNTDIR).mkdir(parents=True, exist_ok=True)

# %% [markdown]
# # Stop aws-cluster.docker-compose.yml

# %%
import subprocess

if AWS_START_FROM_SCRATCH:
    subprocess.run(
        ["docker", "compose", "-f", "aws-cluster.docker-compose.yml", "down", "-v"],
        check=False,
    )
else:
    print("Preserving existing containers and volumes")


# %% [markdown]
# Defines clear_bind_directory, which empties the bind mount through a throwaway busybox:1.36 container, and runs it on DOCKER_MOUNTDIR when AWS_START_FROM_SCRATCH is true.

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


if AWS_START_FROM_SCRATCH:
    clear_bind_directory(DOCKER_MOUNTDIR)

# %% [markdown]
# Writes the engine's core-site.xml: the `s3://` scheme Athena uses is served by Hadoop's S3A connector pointed at Moto (path-style addressing, no TLS). The connector ships inside the Hive image and is enabled with HADOOP_OPTIONAL_TOOLS=hadoop-aws; nothing is downloaded.

# %%
ENGINE_CONF_DIR = Path(DOCKER_MOUNTDIR) / ATHENA_ENGINE_CONTAINER_NAME
ENGINE_CONF_DIR.mkdir(parents=True, exist_ok=True)
(ENGINE_CONF_DIR / "core-site.xml").write_text(
    f"""<?xml version="1.0"?>
<configuration>
    <property><name>fs.s3.impl</name><value>org.apache.hadoop.fs.s3a.S3AFileSystem</value></property>
    <property><name>fs.s3a.endpoint</name><value>{MOTO_INTERNAL_URL}</value></property>
    <property><name>fs.s3a.endpoint.region</name><value>{AWS_REGION}</value></property>
    <property><name>fs.s3a.path.style.access</name><value>true</value></property>
    <property><name>fs.s3a.connection.ssl.enabled</name><value>false</value></property>
    <property><name>fs.s3a.access.key</name><value>{AWS_DUMMY_KEY_ID}</value></property>
    <property><name>fs.s3a.secret.key</name><value>{AWS_DUMMY_SECRET}</value></property>
</configuration>
""",
    encoding="utf-8",
)
print(f"Wrote {ENGINE_CONF_DIR / 'core-site.xml'}")

# %% [markdown]
# Writes the client configuration: an AWS config and credentials file with dummy keys, plus `aws-lab.env` (Bash) and `aws-lab.ps1` (PowerShell) that point the AWS CLI and boto3 at these files and at the local endpoints. Pointing AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE at these files keeps any real `~/.aws` profile out of the lab.

# %%
CLIENT_DIR = Path(DOCKER_MOUNTDIR) / "client"
CLIENT_DIR.mkdir(parents=True, exist_ok=True)
CLIENT_CONFIG = CLIENT_DIR / "config"
CLIENT_CREDENTIALS = CLIENT_DIR / "credentials"
CLIENT_CONFIG.write_text(f"[default]\nregion = {AWS_REGION}\noutput = json\n", encoding="utf-8")
CLIENT_CREDENTIALS.write_text(
    f"[default]\naws_access_key_id = {AWS_DUMMY_KEY_ID}\naws_secret_access_key = {AWS_DUMMY_SECRET}\n",
    encoding="utf-8",
)
CLIENT_ENV = {
    "AWS_CONFIG_FILE": str(CLIENT_CONFIG),
    "AWS_SHARED_CREDENTIALS_FILE": str(CLIENT_CREDENTIALS),
    "AWS_PROFILE": "default",
    "AWS_DEFAULT_REGION": AWS_REGION,
    "AWS_ENDPOINT_URL": MOTO_CLIENT_URL,
    "AWS_ENDPOINT_URL_ATHENA": ATHENA_CLIENT_URL,
}
UNSET = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
(CLIENT_DIR / "aws-lab.env").write_text(
    "".join(f"unset {name}\n" for name in UNSET)
    + "".join(f"export {name}='{value}'\n" for name, value in CLIENT_ENV.items()),
    encoding="utf-8",
)
(CLIENT_DIR / "aws-lab.ps1").write_text(
    "".join(f"Remove-Item Env:{name} -ErrorAction SilentlyContinue\n" for name in UNSET)
    + "".join(f"$env:{name} = '{value}'\n" for name, value in CLIENT_ENV.items()),
    encoding="utf-8",
)
print((CLIENT_DIR / "aws-lab.env").read_text(encoding="utf-8"))

# %% [markdown]
# Pulls the pinned Lambda runtime image now, so that the first `aws lambda invoke` does not stall on a download.

# %%
pull = subprocess.run(["docker", "pull", "-q", LAMBDA_RUNTIME_IMAGE], capture_output=True, text=True)
print(pull.stdout.strip())
assert pull.returncode == 0, pull.stderr

# %% [markdown]
# # Start aws-cluster.docker-compose.yml

# %%
import yaml
from IPython.display import Markdown, display

aws_compose_dict = {
    "name": "aws-cluster",
    "services": {
        MOTO_CONTAINER_NAME: {
            "image": MOTO_IMAGE,
            "container_name": MOTO_CONTAINER_NAME,
            "environment": {
                "MOTO_PORT": str(MOTO_INTERNAL_PORT),
                # Lambda containers join this network and reach Moto by its IP on it.
                "MOTO_DOCKER_NETWORK_NAME": AWS_NETWORK_NAME,
                "MOTO_DOCKER_LAMBDA_IMAGE": LAMBDA_RUNTIME_IMAGE,
                # AWS managed policies (e.g. AmazonDynamoDBFullAccess) are bundled
                # with Moto but only loaded on request.
                "MOTO_IAM_LOAD_MANAGED_POLICIES": "true",
            },
            # Moto starts each Lambda invocation as a sibling container.
            "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
            "networks": [AWS_NETWORK_NAME],
            "ports": [f"{HOST_BIND_IP}:{MOTO_EXTERNAL_PORT}:{MOTO_INTERNAL_PORT}"],
            "dns": DOCKER_DNS,
            "healthcheck": {
                "test": ["CMD", "python3", "-c",
                         f"import urllib.request; urllib.request.urlopen('http://localhost:{MOTO_INTERNAL_PORT}/moto-api/')"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 24,
                "start_period": "5s",
            },
        },
        ATHENA_ENGINE_CONTAINER_NAME: {
            "image": ATHENA_ENGINE_IMAGE,
            "container_name": ATHENA_ENGINE_CONTAINER_NAME,
            "environment": {
                "SERVICE_NAME": "hiveserver2",
                "HADOOP_OPTIONAL_TOOLS": "hadoop-aws",
                # Query tasks read S3 through the default provider chain.
                "AWS_ACCESS_KEY_ID": AWS_DUMMY_KEY_ID,
                "AWS_SECRET_ACCESS_KEY": AWS_DUMMY_SECRET,
                "AWS_REGION": AWS_REGION,
            },
            "volumes": [f"{ENGINE_CONF_DIR / 'core-site.xml'}:/opt/hive/conf/core-site.xml:ro"],
            "networks": [AWS_NETWORK_NAME],
            "dns": DOCKER_DNS,
            "depends_on": {MOTO_CONTAINER_NAME: {"condition": "service_healthy"}},
            "healthcheck": {
                "test": ["CMD-SHELL",
                         f"beeline -u jdbc:hive2://localhost:{ATHENA_ENGINE_PORT} -e 'SELECT 1' >/dev/null 2>&1"],
                "interval": "10s",
                "timeout": "60s",
                "retries": 30,
                "start_period": "30s",
            },
        },
        ATHENA_GATEWAY_CONTAINER_NAME: {
            "image": ATHENA_GATEWAY_IMAGE,
            "build": {"context": str(LABS_ROOT), "dockerfile": "aws/dockerfile.athena-gateway"},
            "container_name": ATHENA_GATEWAY_CONTAINER_NAME,
            "environment": {
                "ATHENA_ENGINE_HOST": ATHENA_ENGINE_CONTAINER_NAME,
                "ATHENA_ENGINE_PORT": str(ATHENA_ENGINE_PORT),
                "S3_ENDPOINT_URL": MOTO_INTERNAL_URL,
                "AWS_REGION": AWS_REGION,
                "AWS_ACCESS_KEY_ID": AWS_DUMMY_KEY_ID,
                "AWS_SECRET_ACCESS_KEY": AWS_DUMMY_SECRET,
            },
            "networks": [AWS_NETWORK_NAME],
            "ports": [f"{HOST_BIND_IP}:{ATHENA_GATEWAY_EXTERNAL_PORT}:{ATHENA_GATEWAY_INTERNAL_PORT}"],
            "dns": DOCKER_DNS,
            "depends_on": {ATHENA_ENGINE_CONTAINER_NAME: {"condition": "service_healthy"}},
            "healthcheck": {
                "test": ["CMD", "python", "-c",
                         f"import urllib.request; urllib.request.urlopen('http://localhost:{ATHENA_GATEWAY_INTERNAL_PORT}/health')"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 24,
                "start_period": "5s",
            },
        },
    },
    "networks": {AWS_NETWORK_NAME: {"name": AWS_NETWORK_NAME, "driver": "bridge"}},
}

aws_compose_yaml_path = os.path.join(LOCALHOST_WORKDIR, "aws-cluster.docker-compose.yml")
aws_compose_yaml_contents = yaml.dump(aws_compose_dict, default_flow_style=False, sort_keys=False, indent=4)
with open(aws_compose_yaml_path, "w") as f:
    f.write(aws_compose_yaml_contents)
print(f"Successfully created: '{os.path.relpath(aws_compose_yaml_path)}'")
display(Markdown(f"```yaml\n{aws_compose_yaml_contents}\n```"))

# %% [markdown]
# Builds the Athena gateway image from `aws/dockerfile.athena-gateway` (exact versions from labs-setup's uv.lock).

# %%
build = subprocess.run(
    ["docker", "compose", "-f", "aws-cluster.docker-compose.yml", "build", ATHENA_GATEWAY_CONTAINER_NAME],
    capture_output=True,
    text=True,
)
print(build.stdout[-2000:])
assert build.returncode == 0, build.stderr[-4000:]

# %% [markdown]
# Starts the stack in detached mode with `--wait`: Moto, then the engine (beeline `SELECT 1`), then the gateway (`/health`) must pass their healthchecks.

# %%
# !docker compose -f aws-cluster.docker-compose.yml up -d --wait
assert _exit_code == 0, "docker compose up --wait failed: a service did not become healthy"

# %% [markdown]
# Smoke test through the same endpoints the students use: STS answers with Moto's fixed account (never a real one); a Lambda function writes to DynamoDB from its own runtime container; and an Athena table over an S3 object returns its row count. Everything it creates is deleted.

# %%
import io
import json
import time
import uuid
import zipfile

import boto3

os.environ.update(CLIENT_ENV)
for name in UNSET:
    os.environ.pop(name, None)

identity = boto3.client("sts").get_caller_identity()
assert identity["Account"] == MOTO_ACCOUNT_ID, identity
print(f"STS account: {identity['Account']} (Moto)")

smoke = f"labs-infra-smoke-{uuid.uuid4().hex[:8]}"
s3 = boto3.client("s3")
s3.create_bucket(Bucket=smoke)
s3.put_object(Bucket=smoke, Key="raw/datos.csv", Body=b"id,monto\na,1.5\nb,2.5\n")

dynamodb = boto3.client("dynamodb")
dynamodb.create_table(
    TableName=smoke,
    AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
    KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
    BillingMode="PAY_PER_REQUEST",
)
iam = boto3.client("iam")
role_arn = iam.create_role(
    RoleName=smoke,
    AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}),
)["Role"]["Arn"]
iam.attach_role_policy(RoleName=smoke, PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess")
package = io.BytesIO()
with zipfile.ZipFile(package, "w") as archive:
    archive.writestr("handler.py", (
        "import os, boto3\n"
        "def run(event, context):\n"
        "    boto3.client('dynamodb').put_item(TableName=os.environ['TABLE'], Item={'id': {'S': event['id']}})\n"
        "    return {'ok': event['id']}\n"
    ))
lambda_client = boto3.client("lambda")
lambda_client.create_function(
    FunctionName=smoke, Runtime="python3.12", Role=role_arn, Handler="handler.run",
    Code={"ZipFile": package.getvalue()}, Environment={"Variables": {"TABLE": smoke}},
)
invoked = lambda_client.invoke(FunctionName=smoke, Payload=json.dumps({"id": "desde-lambda"}))
answer = json.loads(invoked["Payload"].read())
assert invoked["StatusCode"] == 200 and answer == {"ok": "desde-lambda"}, answer
assert dynamodb.get_item(TableName=smoke, Key={"id": {"S": "desde-lambda"}}).get("Item"), "Lambda did not reach DynamoDB"
print("Lambda -> DynamoDB: ok")

athena = boto3.client("athena")
output = {"OutputLocation": f"s3://{smoke}/athena-results/"}


def athena_query(sql):
    query_id = athena.start_query_execution(QueryString=sql, ResultConfiguration=output)["QueryExecutionId"]
    for _ in range(240):
        status = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.5)
    assert status["State"] == "SUCCEEDED", status
    return athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]


database = smoke.replace("-", "_")
athena_query(f"CREATE DATABASE {database}")
athena_query(
    f"CREATE EXTERNAL TABLE {database}.datos (id string, monto double) ROW FORMAT DELIMITED "
    f"FIELDS TERMINATED BY ',' LOCATION 's3://{smoke}/raw/' TBLPROPERTIES ('skip.header.line.count'='1')"
)
rows = athena_query(f"SELECT COUNT(*) AS n, SUM(monto) AS total FROM {database}.datos")
assert [d["VarCharValue"] for d in rows[1]["Data"]] == ["2", "4.0"], rows
print("Athena over S3: ok")

athena_query(f"DROP DATABASE {database} CASCADE")
lambda_client.delete_function(FunctionName=smoke)
iam.detach_role_policy(RoleName=smoke, PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess")
iam.delete_role(RoleName=smoke)
dynamodb.delete_table(TableName=smoke)
for item in s3.list_objects_v2(Bucket=smoke).get("Contents", []):
    s3.delete_object(Bucket=smoke, Key=item["Key"])
s3.delete_bucket(Bucket=smoke)
print("AWS lab environment ready. Before the lab, run in your terminal:")
print(f"  source {CLIENT_DIR / 'aws-lab.env'}      # Bash")
print(f"  . {CLIENT_DIR / 'aws-lab.ps1'}           # PowerShell")
