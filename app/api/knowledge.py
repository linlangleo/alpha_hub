from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.repositories import knowledge_repository
from app.services.knowledge_service import knowledge_service
from app.workflows.knowledge_ingestion import knowledge_ingestion_workflow


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ChunkContentUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=100_000)
    context: str | None = Field(default=None, max_length=200)


class ChunkSummaryUpdate(BaseModel):
    summary: str = Field(default="", max_length=20_000)


class ChunkMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    chunk_type: str | None = Field(default=None, max_length=100)
    strategy_id: int | None = None
    tags: list[str] | None = None


class RetrievalStatusUpdate(BaseModel):
    retrieval_status: str


@router.post("/documents")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_type: str = Form(default="self"),
    source_name: str = Form(default=""),
    category: str = Form(default="other"),
    strategy_id: str = Form(default=""),
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        selected_strategy_id = int(strategy_id) if strategy_id.strip() else None
        content = await file.read()
        document = knowledge_ingestion_workflow.create_upload(
            filename=file.filename or "unnamed.docx",
            content_type=file.content_type or "",
            content=content,
            source_type=source_type.strip()[:100] or "self",
            source_name=source_name.strip()[:255],
            category=category.strip()[:100] or "other",
            strategy_id=selected_strategy_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"上传失败: {exc}") from exc
    background_tasks.add_task(knowledge_ingestion_workflow.process, int(document["id"]), user_id)
    return serialize_ids(document)


@router.get("/documents")
def list_documents(user_id: int = Depends(require_user_id)) -> list[dict[str, Any]]:
    return serialize_ids(knowledge_repository.list_documents(user_id))


@router.get("/documents/{document_id}")
def document_detail(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.detail(document_id, user_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/{document_id}/status")
def document_status(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    document = knowledge_repository.get_document(document_id, user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return serialize_ids(
        {
            "id": document["id"],
            "status": document["status"],
            "metadata": document["metadata"],
            "chunk_count": document["chunk_count"],
        }
    )


@router.get("/documents/{document_id}/parsed")
def parsed_document(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        detail = knowledge_service.detail(document_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_ids({"document": detail, "chunks": detail["chunks"]})


@router.get("/documents/{document_id}/raw-url")
def raw_document_url(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> dict[str, str]:
    try:
        return {"url": knowledge_service.raw_file_url(document_id, user_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/chunks/{chunk_id}/content-context")
def update_chunk_content_context(chunk_id: int, payload: ChunkContentUpdate,
                                 user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.update_chunk_and_reindex(
            chunk_id, user_id, content=payload.content, context=payload.context
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Chunk 更新或重新向量化失败: {exc}") from exc


@router.patch("/chunks/{chunk_id}/summary")
def update_chunk_summary(chunk_id: int, payload: ChunkSummaryUpdate,
                         user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.update_summary(chunk_id, user_id, payload.summary))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/chunks/{chunk_id}/metadata")
def update_chunk_metadata(chunk_id: int, payload: ChunkMetadataUpdate,
                          user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.update_metadata(
            chunk_id, user_id, title=payload.title, chunk_type=payload.chunk_type,
                strategy_id=payload.strategy_id,
                strategy_provided="strategy_id" in payload.model_fields_set,
                tags=payload.tags,
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Chunk metadata 同步失败: {exc}") from exc


@router.post("/chunks/{chunk_id}/regenerate-context")
def regenerate_chunk_context(chunk_id: int,
                             user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.regenerate_context(chunk_id, user_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Context 重新生成失败: {exc}") from exc


@router.post("/chunks/{chunk_id}/review")
def review_chunk(chunk_id: int,
                 user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.mark_reviewed(chunk_id, user_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"审核状态同步失败: {exc}") from exc


@router.patch("/chunks/{chunk_id}/retrieval-status")
def update_retrieval_status(chunk_id: int, payload: RetrievalStatusUpdate,
                            user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.set_retrieval_status(
            chunk_id, user_id, payload.retrieval_status
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索状态同步失败: {exc}") from exc


@router.post("/chunks/{chunk_id}/reindex")
def reindex_chunk(chunk_id: int,
                  user_id: int = Depends(require_user_id)) -> dict[str, Any]:
    try:
        return serialize_ids(knowledge_service.reindex_chunk(chunk_id, user_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"重新向量化失败: {exc}") from exc
