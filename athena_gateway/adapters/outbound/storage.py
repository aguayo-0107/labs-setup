"""Result files written to S3 through any boto3-compatible S3 client."""

from __future__ import annotations

from typing import Any

from ...domain.models import S3Location
from ...ports.outbound import ResultStorePort


class S3ResultStore(ResultStorePort):
    def __init__(self, client: Any) -> None:
        self._client = client

    def save(self, location: S3Location, content: bytes) -> None:
        self._client.put_object(Bucket=location.bucket, Key=location.key, Body=content)
