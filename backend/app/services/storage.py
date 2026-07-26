from __future__ import annotations

import aioboto3
from botocore.config import Config as BotoConfig

from app.core.config import Settings


class StorageService:
    """Async S3/MinIO wrapper. Created once in lifespan. """

    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.minio_endpoint
        self._key = settings.minio_access_key
        self._secret = settings.minio_secret_key.get_secret_value()
        self._bucket = settings.minio_bucket
        self._session = aioboto3.Session()

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._key,
            aws_secret_access_key=self._secret,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

    async def get(self, key: str) -> bytes:
        """Fetch an object's bytes. Used by the ingest worker to read uploads back."""
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                object = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if object:
                    await s3.delete_objects(Bucket=self._bucket, Delete={"Objects": object})
