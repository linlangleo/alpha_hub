from abc import ABC, abstractmethod
from datetime import timedelta
from io import BytesIO
from typing import BinaryIO

from minio import Minio
from minio.deleteobjects import DeleteObject


class StorageService(ABC):
    @abstractmethod
    def put_stream(
        self,
        object_key: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, object_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def presigned_get_url(self, object_key: str, expires_seconds: int = 3600) -> str:
        raise NotImplementedError

    @abstractmethod
    def check(self) -> bool:
        raise NotImplementedError


class MinioStorageService(StorageService):
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        if not endpoint or not access_key or not secret_key or not bucket:
            raise RuntimeError("MinIO 配置不完整")
        self.bucket = bucket
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put_stream(
        self,
        object_key: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> None:
        self.ensure_bucket()
        stream.seek(0)
        self.client.put_object(
            self.bucket,
            object_key,
            stream,
            size,
            content_type=content_type or "application/octet-stream",
        )

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        self.put_stream(object_key, BytesIO(content), len(content), content_type)

    def get_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, object_key: str) -> None:
        if object_key:
            self.client.remove_object(self.bucket, object_key)

    def delete_prefix(self, prefix: str) -> None:
        normalized = prefix.strip().lstrip("/")
        if not normalized or not normalized.endswith("/"):
            raise ValueError("删除前缀不能为空且必须以 / 结尾")
        delete_objects = (
            DeleteObject(item.object_name)
            for item in self.client.list_objects(self.bucket, prefix=normalized, recursive=True)
        )
        errors = list(self.client.remove_objects(self.bucket, delete_objects))
        if errors:
            details = "; ".join(
                f"{error.name}: {error.code} {error.message}" for error in errors
            )
            raise RuntimeError(f"MinIO 批量删除失败: {details}")

    def presigned_get_url(self, object_key: str, expires_seconds: int = 3600) -> str:
        return self.client.presigned_get_object(
            self.bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )

    def check(self) -> bool:
        try:
            return self.client.bucket_exists(self.bucket)
        except Exception:
            return False
