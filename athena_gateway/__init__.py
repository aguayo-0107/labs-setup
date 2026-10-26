"""Local stand-in for the three Amazon Athena calls the AWS lab makes.

StartQueryExecution, GetQueryExecution and GetQueryResults are answered over
the AWS JSON 1.1 protocol, so boto3 and the AWS CLI reach it through
`AWS_ENDPOINT_URL_ATHENA` with no change to the lab's code. The SQL runs on a
HiveServer2 engine (Athena's DDL is based in part on HiveQL DDL) that reads
the data from the emulated S3, and result files are written to the query's
S3 output location as `<QueryExecutionId>.csv` (DML) or `.txt` (DDL).
"""
