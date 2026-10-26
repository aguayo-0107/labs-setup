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
# # AWS lab walkthrough (local emulator)
#
# The serverless data architecture of the AWS lab, end to end, against the environment started by `aws_infra`: S3 data lake, DynamoDB table, IAM role, Lambda ingestion job, a client query and an Athena aggregate over S3. No AWS account is used: every request goes to Moto or to the Athena gateway.
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
# ## 2. Validate the parameters and derive the endpoints
#
# - **What:** rejects any `NETWORK_MODE` other than `local` or `vpn` and builds the Moto (`5050`) and Athena gateway (`5051`) URLs.
# - **Why:** a typo must fail here, not as an unreachable endpoint later.
# - **How:** hosts are `127.0.0.1` (Local) or `motoserver` / `athena-gateway` `.<alias>.<domain>` (VPN); the expected account is Moto's `123456789012`.

# %%
import re

NETWORK_MODE = NETWORK_MODE.strip().lower()
if NETWORK_MODE not in {"local", "vpn"}:
    raise ValueError("NETWORK_MODE must be 'local' or 'vpn'")
VPN_CLIENT_ALIAS = VPN_CLIENT_ALIAS.strip().lower()
if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", VPN_CLIENT_ALIAS) is None:
    raise ValueError("VPN_CLIENT_ALIAS must contain only lowercase letters, digits, or hyphens")
VPN_CLIENT_DOMAIN = f"{VPN_CLIENT_ALIAS}.{VPN_DOMAIN}"


def client_host(container_name):
    return "127.0.0.1" if NETWORK_MODE == "local" else f"{container_name}.{VPN_CLIENT_DOMAIN}"


MOTO_CLIENT_URL = f"http://{client_host('motoserver')}:5050"
ATHENA_CLIENT_URL = f"http://{client_host('athena-gateway')}:5051"
MOTO_ACCOUNT_ID = "123456789012"

# %% [markdown]
# ## 3. Point boto3 at the lab
#
# - **What:** finds `labs-setup`, checks `aws_infra` already ran, works in `aws/mount/lab` and sets the AWS variables of this process.
# - **Why:** boto3 must use the lab's dummy keys and endpoints and never a real AWS profile or key.
# - **How:** removes `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN`, then sets `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_ENDPOINT_URL` (Moto) and `AWS_ENDPOINT_URL_ATHENA` (gateway).
# - 📄 [AWS CLI — Environment variables](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html) · [AWS SDKs — Service-specific endpoints](https://docs.aws.amazon.com/sdkref/latest/guide/feature-ss-endpoints.html)

# %%
import os
from pathlib import Path

_start = Path.cwd().resolve()
LABS_ROOT = next(
    candidate for candidate in (_start, *_start.parents)
    if (candidate / "pyproject.toml").is_file() and (candidate / "aws").is_dir()
)
CLIENT_DIR = LABS_ROOT / "aws" / "mount" / "client"
assert (CLIENT_DIR / "credentials").is_file(), "Run aws_infra first"
WORKDIR = LABS_ROOT / "aws" / "mount" / "lab"
WORKDIR.mkdir(parents=True, exist_ok=True)
os.chdir(WORKDIR)

for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    os.environ.pop(name, None)
os.environ.update({
    "AWS_CONFIG_FILE": str(CLIENT_DIR / "config"),
    "AWS_SHARED_CREDENTIALS_FILE": str(CLIENT_DIR / "credentials"),
    "AWS_PROFILE": "default",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ENDPOINT_URL": MOTO_CLIENT_URL,
    "AWS_ENDPOINT_URL_ATHENA": ATHENA_CLIENT_URL,
})

# %% [markdown]
# ## 4. Identity
#
# - **What:** asks STS who is calling and checks the account is `123456789012`.
# - **Why:** it proves every later request goes to Moto, never to a real AWS account.
# - **How:** `sts.get_caller_identity()`.
# - 📄 [STS GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)

# %%
import boto3

PREFIX = "lab-aws-walkthrough"
identity = boto3.client("sts").get_caller_identity()
print({key: identity[key] for key in ("UserId", "Account", "Arn")})
assert identity["Account"] == MOTO_ACCOUNT_ID

# %% [markdown]
# ## 5. Data lake: 10,000 transactions in S3
#
# - **What:** generates 10,000 fake transactions, saves them as CSV and uploads the file to `s3://lab-aws-walkthrough-datalake/raw/`.
# - **Why:** the raw file in S3 is what Athena will query; fixed seeds make every run produce the same data.
# - **How:** `Faker("es_MX")` with `Faker.seed(7)` and `random.seed(7)`; the cell checks no name contains a comma, which would split a CSV row; `create_bucket`, `upload_file`, then `list_objects_v2` must show only that key.
# - 📄 [Faker — Seeding](https://faker.readthedocs.io/en/master/#seeding-the-generator) · [S3 — Uploading objects](https://docs.aws.amazon.com/AmazonS3/latest/userguide/upload-objects.html)

# %%
import random

import pandas as pd
from faker import Faker

faker = Faker("es_MX")
Faker.seed(7)
random.seed(7)
rows = [
    {
        "id": faker.uuid4(),
        "nombre": faker.name(),
        "monto": round(random.uniform(10.0, 5000.0), 2),
        "fecha": str(faker.date_between(start_date="-1y", end_date="today")),
    }
    for _ in range(10000)
]
transactions = pd.DataFrame(rows)
transactions.to_csv("transacciones_masivas.csv", index=False)
assert not transactions["nombre"].str.contains(",").any(), "a comma would split the CSV row"

s3 = boto3.client("s3")
bucket = f"{PREFIX}-datalake"
s3.create_bucket(Bucket=bucket)
s3.upload_file("transacciones_masivas.csv", bucket, "raw/transacciones_masivas.csv")
keys = [item["Key"] for item in s3.list_objects_v2(Bucket=bucket)["Contents"]]
print(keys)
assert keys == ["raw/transacciones_masivas.csv"]

# %% [markdown]
# ## 6. DynamoDB table
#
# - **What:** creates `lab-aws-walkthrough-Transacciones` with partition key `user_id` and sort key `tx_id`.
# - **Why:** the partition key groups a user's transactions; the sort key tells them apart and orders them.
# - **How:** `create_table` with `HASH` + `RANGE` keys and `PAY_PER_REQUEST` (no capacity to plan); `describe_table` must return that key schema.
# - 📄 [DynamoDB — Partition and sort keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html) · [DynamoDB — On-demand mode](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html)

# %%
dynamodb = boto3.client("dynamodb")
table_name = f"{PREFIX}-Transacciones"
dynamodb.create_table(
    TableName=table_name,
    AttributeDefinitions=[
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "tx_id", "AttributeType": "S"},
    ],
    KeySchema=[
        {"AttributeName": "user_id", "KeyType": "HASH"},
        {"AttributeName": "tx_id", "KeyType": "RANGE"},
    ],
    BillingMode="PAY_PER_REQUEST",
)
schema = dynamodb.describe_table(TableName=table_name)["Table"]["KeySchema"]
print(schema)
assert schema == [{"AttributeName": "user_id", "KeyType": "HASH"}, {"AttributeName": "tx_id", "KeyType": "RANGE"}]

# %% [markdown]
# ## 7. Lambda ingestion job
#
# - **What:** creates an IAM role, packages a Python handler, creates the function and invokes it three times.
# - **Why:** a Lambda needs an execution role that DynamoDB accepts; the handler labels each transaction `ALTO_VALOR` (≥ 1000) or `NORMAL`.
# - **How:** the role trusts `lambda.amazonaws.com` and gets `AmazonDynamoDBFullAccess`; the code is zipped in memory; the table name arrives as the environment variable `TABLE_NAME`; each `invoke` must return 200 without `FunctionError`.
# - 📄 [Lambda execution role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html) · [Lambda — Python handler](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html) · [Lambda — Environment variables](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html)

# %%
import io
import json
import zipfile

iam = boto3.client("iam")
role_arn = iam.create_role(
    RoleName=f"{PREFIX}-LambdaRole",
    AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}),
)["Role"]["Arn"]
iam.attach_role_policy(RoleName=f"{PREFIX}-LambdaRole",
                       PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess")

HANDLER = '''import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    table = dynamodb.Table(os.environ['TABLE_NAME'])
    user_id = event.get('user_id', 'u999')
    tx_id = event.get('tx_id', 'tx000')
    monto = float(event.get('monto', 0))
    categoria = "ALTO_VALOR" if monto >= 1000 else "NORMAL"
    table.put_item(Item={'user_id': user_id, 'tx_id': tx_id, 'monto': str(monto),
                         'categoria': categoria, 'origen': 'LambdaJob'})
    return {'statusCode': 200, 'body': json.dumps(f'Transaccion de categoria {categoria} guardada exitosamente!')}
'''
package = io.BytesIO()
with zipfile.ZipFile(package, "w") as archive:
    archive.writestr("lambda_function.py", HANDLER)
lambda_client = boto3.client("lambda")
lambda_client.create_function(
    FunctionName=f"{PREFIX}-IngestaJob", Runtime="python3.12", Role=role_arn,
    Handler="lambda_function.lambda_handler", Code={"ZipFile": package.getvalue()},
    Environment={"Variables": {"TABLE_NAME": table_name}},
)
for tx_id, monto in (("tx999", 1500), ("tx500", 500), ("tx1000", 1000)):
    response = lambda_client.invoke(FunctionName=f"{PREFIX}-IngestaJob",
                                    Payload=json.dumps({"user_id": "u007", "tx_id": tx_id, "monto": monto}))
    print(tx_id, json.loads(response["Payload"].read()))
    assert response["StatusCode"] == 200 and "FunctionError" not in response

# %% [markdown]
# ## 8. Query by partition key vs. full scan
#
# - **What:** reads user `u007`'s transactions with a key query and compares with a scan of the whole table.
# - **Why:** a query reads only one partition; a scan reads every item, so it costs more as the table grows.
# - **How:** `table.query(KeyConditionExpression=Key("user_id").eq("u007"))`; both must return the same 3 items, with the expected categories.
# - 📄 [DynamoDB — Query](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.html) · [DynamoDB — Scan](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Scan.html) · [boto3 — DynamoDB](https://docs.aws.amazon.com/boto3/latest/guide/dynamodb.html)

# %%
from boto3.dynamodb.conditions import Key

table = boto3.resource("dynamodb").Table(table_name)
by_key = table.query(KeyConditionExpression=Key("user_id").eq("u007"))
categories = {item["tx_id"]: item["categoria"] for item in by_key["Items"]}
print(by_key["Count"], categories)
assert categories == {"tx999": "ALTO_VALOR", "tx500": "NORMAL", "tx1000": "ALTO_VALOR"}
assert table.scan()["Count"] == by_key["Count"] == 3

# %% [markdown]
# ## 9. Athena aggregate over S3
#
# - **What:** creates a database and an external table over the CSV in S3, sums `monto` and counts rows, and checks both against pandas.
# - **Why:** an external table only describes files already in S3; Athena reads them where they are.
# - **How:** `start_query_execution` with an S3 `OutputLocation`, polling `get_query_execution` until `SUCCEEDED`, `FAILED` or `CANCELLED`; `skip.header.line.count=1` skips the CSV header.
# - 📄 [Athena — CREATE TABLE](https://docs.aws.amazon.com/athena/latest/ug/create-table.html) · [Athena — LazySimpleSerDe (`skip.header.line.count`)](https://docs.aws.amazon.com/athena/latest/ug/lazy-simple-serde.html) · [Athena StartQueryExecution](https://docs.aws.amazon.com/athena/latest/APIReference/API_StartQueryExecution.html) · [Athena QueryExecutionStatus](https://docs.aws.amazon.com/athena/latest/APIReference/API_QueryExecutionStatus.html)

# %%
import time

athena = boto3.client("athena")
output = {"OutputLocation": f"s3://{bucket}/athena-results/"}
database = PREFIX.replace("-", "_") + "_db"


def run(sql):
    query_id = athena.start_query_execution(QueryString=sql, ResultConfiguration=output)["QueryExecutionId"]
    while True:
        status = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    assert status["State"] == "SUCCEEDED", status
    return athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]


run(f"CREATE DATABASE IF NOT EXISTS {database}")
run(f"""CREATE EXTERNAL TABLE IF NOT EXISTS {database}.transacciones (
  `id` string, `nombre` string, `monto` double, `fecha` string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://{bucket}/raw/'
TBLPROPERTIES ('skip.header.line.count'='1')""")
result = run(f"SELECT SUM(monto) as ingresos_totales, COUNT(*) as tx_totales FROM {database}.transacciones")
header, values = ([d["VarCharValue"] for d in row["Data"]] for row in result)
print(header, values)
assert header == ["ingresos_totales", "tx_totales"]
assert int(values[1]) == len(transactions)
assert abs(float(values[0]) - transactions["monto"].sum()) < 0.01

# %% [markdown]
# ## 10. Teardown
#
# - **What:** deletes the Athena database, the function, the role, the table, the bucket and the local CSV.
# - **Why:** the emulator is shared by later runs; the cell checks the bucket and the table are gone.
# - **How:** delete in reverse order of creation; a bucket must be empty before `delete_bucket`.

# %%
run(f"DROP DATABASE IF EXISTS {database} CASCADE")
lambda_client.delete_function(FunctionName=f"{PREFIX}-IngestaJob")
iam.detach_role_policy(RoleName=f"{PREFIX}-LambdaRole", PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess")
iam.delete_role(RoleName=f"{PREFIX}-LambdaRole")
dynamodb.delete_table(TableName=table_name)
for item in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
    s3.delete_object(Bucket=bucket, Key=item["Key"])
s3.delete_bucket(Bucket=bucket)
os.remove("transacciones_masivas.csv")
assert bucket not in [b["Name"] for b in s3.list_buckets()["Buckets"]]
assert table_name not in dynamodb.list_tables()["TableNames"]
print("Walkthrough complete; emulator left empty.")
