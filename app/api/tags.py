from typing import Any

from fastapi import APIRouter, Depends

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.repositories.knowledge_repository import list_tags


router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
def tags(user_id: int = Depends(require_user_id)) -> list[dict[str, Any]]:
    return serialize_ids(list_tags(user_id))
