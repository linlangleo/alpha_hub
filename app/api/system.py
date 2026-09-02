from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import require_user_id
from app.common.codes import SystemCode
from app.common.exception import BusinessException
from app.common.response import R
from app.core.config import SETTINGS
from app.core.database import check_database
from app.core.redis_client import check_redis
from app.services.container import (
    check_storage,
    check_vector_store,
    get_deepseek_service,
    get_embedding_service,
)


router = APIRouter(prefix="/api/system", tags=["system"])


class ServiceTestRequest(BaseModel):
    service_name: str


@router.get("/config")
def public_config(user_id: int = Depends(require_user_id)) -> R[dict[str, Any]]:
    del user_id
    return R.ok({
        "deepseek": {
            "configured": bool(SETTINGS.deepseek_api_key),
            "base_url": SETTINGS.deepseek_base_url,
            "model": SETTINGS.deepseek_model,
            "text_models": SETTINGS.deepseek_text_models,
            "vision_model": SETTINGS.deepseek_vision_model,
            "timeout": SETTINGS.deepseek_timeout,
            "retry": SETTINGS.deepseek_retry,
        },
        "embedding": {
            "model": SETTINGS.embedding_model,
            "dimension": SETTINGS.embedding_dimension,
            "device": SETTINGS.embedding_device,
            "batch_size": SETTINGS.embedding_batch_size,
            "max_length": SETTINGS.embedding_max_length,
        },
        "minio": {
            "endpoint": SETTINGS.minio_endpoint,
            "bucket": SETTINGS.minio_bucket,
            "secure": SETTINGS.minio_secure,
        },
        "qdrant": {
            "url": SETTINGS.qdrant_url,
            "collection": SETTINGS.qdrant_collection,
        },
        "retrieval": {
            "mode": SETTINGS.retrieval_mode,
            "top_k": SETTINGS.top_k,
            "neighbor_window": SETTINGS.neighbor_window,
            "neighbor_expand_top_n": SETTINGS.neighbor_expand_top_n,
            "context_max_chars": SETTINGS.context_max_chars,
            "chunk_analysis_batch_size": SETTINGS.chunk_analysis_batch_size,
        },
    })


@router.post("/services/test")
def test_service(
    payload: ServiceTestRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    del user_id
    service_name = payload.service_name.strip().lower()
    try:
        if service_name == "postgresql":
            return R.ok({"success": check_database()})
        if service_name == "redis":
            return R.ok({"success": check_redis()})
        if service_name == "minio":
            return R.ok({"success": check_storage()})
        if service_name == "qdrant":
            return R.ok({"success": check_vector_store()})
        if service_name == "deepseek":
            reply = get_deepseek_service().chat("只回答 OK。", "连接测试")
            return R.ok({"success": bool(reply), "message": reply[:100]})
        if service_name == "embedding":
            vector = get_embedding_service().encode_query("AlphaHub 向量模型连接测试")
            return R.ok({
                "success": True,
                "dense_dimension": len(vector.dense),
                "sparse_terms": len(vector.sparse.indices),
            })
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            f"{service_name or '指定'}服务测试失败",
        ) from exc
    raise BusinessException(SystemCode.UNKNOWN_SERVICE)
