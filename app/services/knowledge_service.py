from typing import Any

from app.core.config import SETTINGS
from app.repositories import knowledge_repository, strategy_repository
from app.services.container import (get_deepseek_service, get_embedding_service,
                                    get_storage_service, get_vector_service)
from app.services.embedding_service import build_embedding_text
from app.services.vector_service import VectorPoint


CHUNK_TYPES = {
    "principle", "market_environment", "stock_selection", "entry_rule", "exit_rule",
    "position_management", "risk_management", "intraday", "case", "review",
    "asset_allocation", "fund", "futures", "macro", "industry", "other",
}


class KnowledgeService:
    def detail(self, document_id: int, user_id: int) -> dict[str, Any]:
        document = knowledge_repository.get_document(document_id, user_id)
        if document is None:
            raise LookupError("知识文档不存在")
        chunks = knowledge_repository.list_document_chunks(document_id, user_id)
        for chunk in chunks:
            chunk["images"] = self._image_urls(chunk.get("image_keys", []))
        document["chunks"] = chunks
        return document

    def raw_file_url(self, document_id: int, user_id: int) -> str:
        document = knowledge_repository.get_document(document_id, user_id)
        if document is None:
            raise LookupError("知识文档不存在")
        if not document.get("minio_object_key"):
            raise RuntimeError("文档尚未保存原始文件")
        return get_storage_service().presigned_get_url(document["minio_object_key"])

    def update_chunk_and_reindex(self, chunk_id: int, user_id: int,
                                 content: str | None = None,
                                 context: str | None = None) -> dict[str, Any]:
        current = self._get_chunk(chunk_id, user_id)
        updates: dict[str, Any] = {}
        if content is not None:
            normalized_content = content.strip()
            if not normalized_content:
                raise ValueError("Chunk content 不能为空")
            updates["content"] = normalized_content
        if context is not None:
            updates["context"] = self._validate_context(context)
        if not updates:
            raise ValueError("没有需要更新的 content 或 context")

        final_content = str(updates.get("content", current["content"]))
        final_context = updates.get("context", current.get("context"))
        embedding_service = get_embedding_service()
        embedding = embedding_service.encode_documents(
            [build_embedding_text(final_context, final_content)]
        )[0]
        updates["status"] = "embedding"
        knowledge_repository.update_chunk_fields(chunk_id, user_id, updates)
        refreshed = self._get_chunk(chunk_id, user_id)
        try:
            get_vector_service().upsert([
                VectorPoint(id=chunk_id, embedding=embedding,
                            payload=self._vector_payload(refreshed, embedding_service.model_name))
            ])
        except Exception:
            knowledge_repository.update_chunk_fields(
                chunk_id, user_id, {"status": "pending_retry"}
            )
            raise
        knowledge_repository.update_chunk_fields(
            chunk_id, user_id, {"status": "embedded", "qdrant_point_id": str(chunk_id)}
        )
        return self._get_chunk(chunk_id, user_id)

    def regenerate_context(self, chunk_id: int, user_id: int) -> dict[str, Any]:
        chunk = self._get_chunk(chunk_id, user_id)
        document_context = (chunk.get("document_metadata") or {}).get("document_context") or {}
        context = get_deepseek_service().regenerate_context(
            document_context, chunk.get("strategy_code"), str(chunk["content"])
        )
        attempts = 0
        while len(context.strip()) > SETTINGS.context_max_chars and attempts < 2:
            context = get_deepseek_service().regenerate_context(
                document_context, chunk.get("strategy_code"), str(chunk["content"]),
                previous_context=context, compress=True,
            )
            attempts += 1
        context = self._validate_context(context)
        return self.update_chunk_and_reindex(chunk_id, user_id, context=context)

    def reindex_chunk(self, chunk_id: int, user_id: int) -> dict[str, Any]:
        chunk = self._get_chunk(chunk_id, user_id)
        return self.update_chunk_and_reindex(
            chunk_id, user_id, content=str(chunk["content"]),
            context=str(chunk.get("context") or ""),
        )

    def update_summary(self, chunk_id: int, user_id: int, summary: str) -> dict[str, Any]:
        knowledge_repository.update_chunk_fields(chunk_id, user_id, {"summary": summary.strip()})
        return self._get_chunk(chunk_id, user_id)

    def update_metadata(self, chunk_id: int, user_id: int, *, title: str | None = None,
                        chunk_type: str | None = None, strategy_id: int | None = None,
                        strategy_provided: bool = False,
                        tags: list[str] | None = None) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title.strip()[:500]
        if chunk_type is not None:
            if chunk_type not in CHUNK_TYPES:
                raise ValueError("无效的 chunk_type")
            updates["chunk_type"] = chunk_type
        if strategy_provided:
            if strategy_id is not None and strategy_repository.get_strategy(strategy_id) is None:
                raise ValueError("正式 Strategy 不存在或未启用")
            updates["strategy_id"] = strategy_id
        if updates:
            knowledge_repository.update_chunk_fields(chunk_id, user_id, updates)
        if tags is not None:
            knowledge_repository.replace_chunk_tags(chunk_id, tags, user_id)
        refreshed = self._get_chunk(chunk_id, user_id)
        self._sync_payload(chunk_id, user_id, self._payload_updates(refreshed))
        return refreshed

    def mark_reviewed(self, chunk_id: int, user_id: int) -> dict[str, Any]:
        knowledge_repository.update_chunk_fields(
            chunk_id, user_id, {"analysis_status": "reviewed"}
        )
        refreshed = self._get_chunk(chunk_id, user_id)
        self._sync_payload(chunk_id, user_id, {"analysis_status": "reviewed"})
        return refreshed

    def set_retrieval_status(self, chunk_id: int, user_id: int,
                             retrieval_status: str) -> dict[str, Any]:
        if retrieval_status not in {"active", "disabled"}:
            raise ValueError("retrieval_status 只支持 active 或 disabled")
        knowledge_repository.update_chunk_fields(
            chunk_id, user_id, {"retrieval_status": retrieval_status}
        )
        refreshed = self._get_chunk(chunk_id, user_id)
        self._sync_payload(chunk_id, user_id, {"retrieval_status": retrieval_status})
        return refreshed

    @staticmethod
    def _sync_payload(chunk_id: int, user_id: int, payload: dict[str, Any]) -> None:
        try:
            get_vector_service().update_payload(chunk_id, payload)
        except Exception:
            knowledge_repository.update_chunk_fields(
                chunk_id, user_id, {"status": "pending_retry"}
            )
            raise

    def _get_chunk(self, chunk_id: int, user_id: int) -> dict[str, Any]:
        chunk = knowledge_repository.get_chunk(chunk_id, user_id)
        if chunk is None:
            raise LookupError("知识 Chunk 不存在")
        return chunk

    @staticmethod
    def _validate_context(context: str) -> str:
        normalized = context.strip()
        if len(normalized) > SETTINGS.context_max_chars:
            raise ValueError(f"Context 不能超过 {SETTINGS.context_max_chars} 个字符")
        return normalized

    @staticmethod
    def _payload_updates(chunk: dict[str, Any]) -> dict[str, Any]:
        return {"title": chunk.get("title"), "context": chunk.get("context"),
                "strategy_id": chunk.get("strategy_id"),
                "strategy_code": chunk.get("strategy_code"),
                "chunk_type": chunk.get("chunk_type"), "tags": chunk.get("tags", []),
                "analysis_status": chunk.get("analysis_status"),
                "retrieval_status": chunk.get("retrieval_status")}

    @classmethod
    def _vector_payload(cls, chunk: dict[str, Any], model_name: str) -> dict[str, Any]:
        return {"chunk_id": int(chunk["id"]), "document_id": int(chunk["document_id"]),
                "knowledge_base_id": int(chunk["knowledge_base_id"]),
                "chunk_index": int(chunk["chunk_index"]),
                "source_type": chunk.get("source_type"), "source_name": chunk.get("source_name"),
                "document_name": chunk.get("document_name"), "embedding_model": model_name,
                **cls._payload_updates(chunk)}

    @staticmethod
    def _image_urls(image_keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in image_keys or []:
            object_key = item.get("object_key")
            if object_key:
                result.append({"image_id": item.get("image_id"), "object_key": object_key,
                               "url": get_storage_service().presigned_get_url(object_key)})
        return result


knowledge_service = KnowledgeService()
