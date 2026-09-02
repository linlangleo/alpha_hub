from typing import Any

import pytest

from app.services.embedding_service import HybridEmbedding, SparseEmbedding
from app.services.knowledge_service import KnowledgeService
from app.services.skill_service import knowledge_skill_service


BASE_CHUNK: dict[str, Any] = {
    "id": 10,
    "knowledge_base_id": 1,
    "document_id": 2,
    "chunk_index": 0,
    "content": "原始正文",
    "context": "旧背景",
    "summary": "摘要",
    "title": "标题",
    "chunk_type": "case",
    "strategy_id": None,
    "strategy_code": None,
    "source_type": "self",
    "source_name": "测试",
    "document_name": "测试文档",
    "analysis_status": "draft",
    "retrieval_status": "active",
    "tags": [],
}


def test_summary_update_never_touches_embedding_or_qdrant(monkeypatch) -> None:
    updates: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.update_chunk_fields",
        lambda chunk_id, user_id, values: updates.append(values),
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.get_chunk",
        lambda chunk_id, user_id: {**BASE_CHUNK, "summary": updates[-1]["summary"]},
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_embedding_service",
        lambda: (_ for _ in ()).throw(AssertionError("summary 不应调用 embedding")),
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_vector_service",
        lambda: (_ for _ in ()).throw(AssertionError("summary 不应调用 Qdrant")),
    )

    result = KnowledgeService().update_summary(10, 1, "新摘要")

    assert updates == [{"summary": "新摘要"}]
    assert result["summary"] == "新摘要"


def test_context_update_reembeds_context_newline_content(monkeypatch) -> None:
    updates: list[dict[str, Any]] = []
    captured_texts: list[str] = []
    upserts: list[Any] = []

    def get_chunk(chunk_id: int, user_id: int) -> dict[str, Any]:
        value = dict(BASE_CHUNK)
        for update in updates:
            value.update(update)
        return value

    class FakeEmbedding:
        model_name = "BAAI/bge-m3"

        def encode_documents(self, texts: list[str]) -> list[HybridEmbedding]:
            captured_texts.extend(texts)
            return [HybridEmbedding([1.0, 0.0], SparseEmbedding([7], [0.8]))]

    class FakeVector:
        def upsert(self, points: list[Any]) -> None:
            upserts.extend(points)

    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.get_chunk", get_chunk
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.update_chunk_fields",
        lambda chunk_id, user_id, values: updates.append(values),
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_embedding_service", lambda: FakeEmbedding()
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_vector_service", lambda: FakeVector()
    )

    result = KnowledgeService().update_chunk_and_reindex(10, 1, context="新背景")

    assert captured_texts == ["新背景\n原始正文"]
    assert len(upserts) == 1
    assert upserts[0].id == 10
    assert result["status"] == "embedded"
    assert result["qdrant_point_id"] == "10"


def test_document_skill_composes_three_rules() -> None:
    prompt = knowledge_skill_service.combine(
        "document_analysis", "chunk_planning", "strategy_judgement"
    )
    assert "document_analysis" in prompt
    assert "chunk_planning" in prompt
    assert "strategy_judgement" in prompt


def test_delete_document_removes_external_data_before_postgresql(monkeypatch) -> None:
    events: list[str] = []

    class FakeVector:
        def delete_by_document(self, document_id: int) -> None:
            assert document_id == 2
            events.append("qdrant")

    class FakeStorage:
        def delete(self, object_key: str) -> None:
            assert object_key == "raw/docx/2/example.docx"
            events.append("minio_raw")

        def delete_prefix(self, prefix: str) -> None:
            assert prefix == "extracted/images/2/"
            events.append("minio_images")

    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.find_document",
        lambda document_id: {
            "id": document_id,
            "create_by": 1,
            "status": "INDEXED",
            "minio_object_key": "raw/docx/2/example.docx",
        },
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.delete_document",
        lambda document_id, user_id: events.append("postgresql") or True,
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_vector_service",
        lambda: FakeVector(),
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_storage_service",
        lambda: FakeStorage(),
    )

    result = KnowledgeService().delete_document(2, 1)

    assert result == {"success": True, "document_id": 2}
    assert events == ["qdrant", "minio_raw", "minio_images", "postgresql"]


def test_delete_document_rejects_non_owner_before_external_calls(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.find_document",
        lambda document_id: {
            "id": document_id,
            "create_by": 99,
            "status": "FAILED",
            "minio_object_key": "raw/docx/2/example.docx",
        },
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_vector_service",
        lambda: (_ for _ in ()).throw(AssertionError("越权请求不能访问 Qdrant")),
    )

    with pytest.raises(PermissionError, match="不是你上传的"):
        KnowledgeService().delete_document(2, 1)


def test_delete_document_rejects_processing_document(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.knowledge_service.knowledge_repository.find_document",
        lambda document_id: {
            "id": document_id,
            "create_by": 1,
            "status": "PROCESSING",
            "minio_object_key": "raw/docx/2/example.docx",
        },
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.get_vector_service",
        lambda: (_ for _ in ()).throw(AssertionError("处理中请求不能访问 Qdrant")),
    )

    with pytest.raises(ValueError, match="暂不允许删除"):
        KnowledgeService().delete_document(2, 1)
