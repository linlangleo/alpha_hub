from typing import Any

from fastapi import APIRouter, Depends

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.core.database import check_database
from app.core.redis_client import check_redis
from app.repositories.knowledge_repository import dashboard_data
from app.services.container import check_storage, check_vector_store


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def dashboard_stats(user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    result = dashboard_data(user_id)
    result["services"] = {
        "postgresql": check_database(),
        "redis": check_redis(),
        "minio": check_storage(),
        "qdrant": check_vector_store(),
    }
    return serialize_ids(result)
