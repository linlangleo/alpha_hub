from typing import Any

from fastapi import APIRouter, Depends

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.repositories.strategy_repository import list_strategies


router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
def strategies(user_id: int = Depends(require_user_id)) -> list[dict[str, Any]]:
    del user_id
    return serialize_ids(list_strategies(active_only=False))
