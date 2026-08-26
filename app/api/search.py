from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.core.config import SETTINGS
from app.workflows.rag_qa import rag_qa_workflow


router = APIRouter(prefix="/api", tags=["search"])


class RetrievalFilters(BaseModel):
    strategy_code: str | None = None
    chunk_type: str | None = None
    source_name: str | None = None
    tags: list[str] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=30)
    filters: RetrievalFilters | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    neighbor_window: int | None = Field(default=None, ge=0, le=3)
    filters: RetrievalFilters | None = None


@router.post("/knowledge/search")
def search(
    payload: SearchRequest,
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        items = rag_qa_workflow.retrieve(
            payload.query.strip(),
            payload.top_k or SETTINGS.top_k,
            user_id,
            payload.filters.model_dump(exclude_none=True) if payload.filters else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"知识检索失败: {exc}") from exc
    return serialize_ids({"items": items})


@router.post("/knowledge/ask")
def ask(
    payload: AskRequest,
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        result = rag_qa_workflow.answer(
            payload.question.strip(),
            payload.top_k or SETTINGS.top_k,
            SETTINGS.neighbor_window if payload.neighbor_window is None else payload.neighbor_window,
            user_id,
            payload.filters.model_dump(exclude_none=True) if payload.filters else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI 知识问答失败: {exc}") from exc
    return serialize_ids(result)
