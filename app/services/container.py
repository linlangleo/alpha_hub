from functools import lru_cache

from app.core.config import SETTINGS
from app.services.deepseek_service import DeepSeekService
from app.services.embedding_service import BgeM3EmbeddingService, EmbeddingService
from app.services.storage_service import MinioStorageService, StorageService
from app.services.vector_service import QdrantService


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    return MinioStorageService(
        endpoint=SETTINGS.minio_endpoint,
        access_key=SETTINGS.minio_access_key,
        secret_key=SETTINGS.minio_secret_key,
        bucket=SETTINGS.minio_bucket,
        secure=SETTINGS.minio_secure,
    )


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return BgeM3EmbeddingService(
        model_name=SETTINGS.embedding_model,
        dimension=SETTINGS.embedding_dimension,
        device=SETTINGS.embedding_device,
        batch_size=SETTINGS.embedding_batch_size,
        max_length=SETTINGS.embedding_max_length,
    )


@lru_cache(maxsize=1)
def get_vector_service() -> QdrantService:
    return QdrantService(
        url=SETTINGS.qdrant_url,
        api_key=SETTINGS.qdrant_api_key,
        collection_name=SETTINGS.qdrant_collection,
        dimension=SETTINGS.embedding_dimension,
    )


@lru_cache(maxsize=1)
def get_deepseek_service() -> DeepSeekService:
    return DeepSeekService(
        api_key=SETTINGS.deepseek_api_key,
        base_url=SETTINGS.deepseek_base_url,
        model=SETTINGS.deepseek_model,
        timeout=SETTINGS.deepseek_timeout,
        retry=SETTINGS.deepseek_retry,
        max_input_chars=SETTINGS.deepseek_max_input_chars,
        max_output_tokens=SETTINGS.deepseek_max_output_tokens,
    )


def check_storage() -> bool:
    try:
        return get_storage_service().check()
    except Exception:
        return False


def check_vector_store() -> bool:
    try:
        return get_vector_service().check()
    except Exception:
        return False
