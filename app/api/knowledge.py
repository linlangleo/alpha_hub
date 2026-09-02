from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import require_user_id
from app.api.utils import serialize_ids
from app.common.codes import KnowledgeCode, SystemCode
from app.common.exception import BusinessException
from app.common.response import R
from app.repositories import knowledge_repository
from app.services.knowledge_service import knowledge_service
from app.workflows.knowledge_ingestion import knowledge_ingestion_workflow


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class DocumentDeleteRequest(BaseModel):
    document_id: int = Field(gt=0)


class DocumentReprocessRequest(BaseModel):
    document_id: int = Field(gt=0)


class ChunkActionRequest(BaseModel):
    chunk_id: int = Field(gt=0)


class ChunkContentUpdate(ChunkActionRequest):
    content: str | None = Field(default=None, max_length=100_000)
    context: str | None = Field(default=None, max_length=200)


class ChunkSummaryUpdate(ChunkActionRequest):
    summary: str = Field(default="", max_length=20_000)


class ChunkMetadataUpdate(ChunkActionRequest):
    title: str | None = Field(default=None, max_length=500)
    chunk_type: str | None = Field(default=None, max_length=100)
    strategy_id: int | None = None
    tags: list[str] | None = None


@router.post("/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_type: str = Form(default="self"),
    source_name: str = Form(default=""),
    category: str = Form(default="other"),
    strategy_id: str = Form(default=""),
    analysis_model: str = Form(default=""),
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
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
            analysis_model=analysis_model.strip(),
            user_id=user_id,
        )
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.INVALID_PARAMETER, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            KnowledgeCode.UPLOAD_FAILED.msg,
        ) from exc
    background_tasks.add_task(knowledge_ingestion_workflow.process, int(document["id"]), user_id)
    return R.ok(serialize_ids(document))


@router.get("/documents/list")
def list_documents(user_id: int = Depends(require_user_id)) -> R[list[dict[str, Any]]]:
    return R.ok(serialize_ids(knowledge_repository.list_documents(user_id)))


@router.get("/documents/detail/{document_id}")
def document_detail(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(knowledge_service.detail(document_id, user_id)))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND, str(exc)) from exc


@router.get("/documents/status/{document_id}")
def document_status(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    document = knowledge_repository.get_document(document_id, user_id)
    if document is None:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND)
    return R.ok(serialize_ids(
        {
            "id": document["id"],
            "status": document["status"],
            "metadata": document["metadata"],
            "chunk_count": document["chunk_count"],
        }
    ))


@router.get("/documents/parsed/{document_id}")
def parsed_document(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        detail = knowledge_service.detail(document_id, user_id)
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND, str(exc)) from exc
    return R.ok(serialize_ids({"document": detail, "chunks": detail["chunks"]}))


@router.get("/documents/raw-url/{document_id}")
def raw_document_url(
    document_id: int,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, str]]:
    try:
        return R.ok({"url": knowledge_service.raw_file_url(document_id, user_id)})
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise BusinessException(KnowledgeCode.RAW_FILE_UNAVAILABLE) from exc


@router.post("/documents/delete")
def delete_document(
    payload: DocumentDeleteRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(
            knowledge_service.delete_document(payload.document_id, user_id)
        ))
    except PermissionError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_STATE_INVALID, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            KnowledgeCode.DOCUMENT_DELETE_FAILED.msg,
        ) from exc


@router.post("/documents/reprocess")
def reprocess_document(
    payload: DocumentReprocessRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        result = knowledge_ingestion_workflow.prepare_reprocess(
            payload.document_id,
            user_id,
        )
    except PermissionError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.DOCUMENT_STATE_INVALID, str(exc)) from exc
    except RuntimeError as exc:
        raise BusinessException(KnowledgeCode.RAW_FILE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "知识文档重新处理请求失败",
        ) from exc
    background_tasks.add_task(
        knowledge_ingestion_workflow.reprocess,
        payload.document_id,
        user_id,
        str(result["error_stage"]),
    )
    return R.ok(serialize_ids(result))


@router.post("/chunks/update-content-context")
def update_chunk_content_context(
    payload: ChunkContentUpdate,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(knowledge_service.update_chunk_and_reindex(
            payload.chunk_id, user_id, content=payload.content, context=payload.context
        )))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.INVALID_PARAMETER, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "Chunk 更新或重新向量化失败",
        ) from exc


@router.post("/chunks/update-summary")
def update_chunk_summary(
    payload: ChunkSummaryUpdate,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(
            knowledge_service.update_summary(payload.chunk_id, user_id, payload.summary)
        ))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc


@router.post("/chunks/update-metadata")
def update_chunk_metadata(
    payload: ChunkMetadataUpdate,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(knowledge_service.update_metadata(
            payload.chunk_id, user_id, title=payload.title, chunk_type=payload.chunk_type,
                strategy_id=payload.strategy_id,
                strategy_provided="strategy_id" in payload.model_fields_set,
                tags=payload.tags,
        )))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.INVALID_PARAMETER, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "Chunk metadata 同步失败",
        ) from exc


@router.post("/chunks/regenerate-context")
def regenerate_chunk_context(
    payload: ChunkActionRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(
            knowledge_service.regenerate_context(payload.chunk_id, user_id)
        ))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.INVALID_PARAMETER, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "Context 重新生成失败",
        ) from exc


@router.post("/chunks/mark-reviewed")
def review_chunk(
    payload: ChunkActionRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(
            knowledge_service.mark_reviewed(payload.chunk_id, user_id)
        ))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "审核状态同步失败",
        ) from exc


def _set_retrieval_status(
    chunk_id: int,
    retrieval_status: str,
    user_id: int,
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(knowledge_service.set_retrieval_status(
            chunk_id, user_id, retrieval_status
        )))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise BusinessException(KnowledgeCode.INVALID_PARAMETER, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "检索状态同步失败",
        ) from exc


@router.post("/chunks/enable-retrieval")
def enable_retrieval(
    payload: ChunkActionRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    return _set_retrieval_status(payload.chunk_id, "active", user_id)


@router.post("/chunks/disable-retrieval")
def disable_retrieval(
    payload: ChunkActionRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    return _set_retrieval_status(payload.chunk_id, "disabled", user_id)


@router.post("/chunks/reindex")
def reindex_chunk(
    payload: ChunkActionRequest,
    user_id: int = Depends(require_user_id),
) -> R[dict[str, Any]]:
    try:
        return R.ok(serialize_ids(
            knowledge_service.reindex_chunk(payload.chunk_id, user_id)
        ))
    except LookupError as exc:
        raise BusinessException(KnowledgeCode.CHUNK_NOT_FOUND, str(exc)) from exc
    except Exception as exc:
        raise BusinessException(
            SystemCode.SERVICE_UNAVAILABLE,
            "重新向量化失败",
        ) from exc
