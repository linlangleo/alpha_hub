from pathlib import Path
from typing import Any

from app.services.embedding_service import (
    BgeM3EmbeddingService,
    HybridEmbedding,
    SparseEmbedding,
)
from app.services.deepseek_service import DeepSeekStructuredOutputError
from app.workflows.knowledge_ingestion import KnowledgeIngestionWorkflow


def _complete_model(path: Path) -> Path:
    path.mkdir()
    for filename in (
        "config.json",
        "pytorch_model.bin",
        "tokenizer.json",
        "sparse_linear.pt",
        "colbert_linear.pt",
    ):
        (path / filename).write_bytes(b"test")
    return path


def test_bge_m3_uses_complete_local_cache_without_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_path = _complete_model(tmp_path / "model")
    calls: list[bool] = []

    def snapshot_download(**kwargs: Any) -> str:
        calls.append(bool(kwargs["local_files_only"]))
        return str(model_path)

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    service = BgeM3EmbeddingService("BAAI/bge-m3", 1024)

    assert service._resolve_model_source() == str(model_path.resolve())
    assert calls == [True]


def test_bge_m3_downloads_only_when_local_cache_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_path = _complete_model(tmp_path / "downloaded")
    calls: list[bool] = []

    def snapshot_download(**kwargs: Any) -> str:
        local_only = bool(kwargs["local_files_only"])
        calls.append(local_only)
        if local_only:
            raise RuntimeError("not cached")
        return str(model_path)

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    service = BgeM3EmbeddingService("BAAI/bge-m3", 1024)

    assert service._resolve_model_source() == str(model_path.resolve())
    assert calls == [True, False]


def test_prepare_reprocess_uses_recorded_error_stage(monkeypatch) -> None:
    claimed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.find_document",
        lambda document_id: {
            "id": document_id,
            "create_by": 7,
            "status": "FAILED",
            "minio_object_key": "raw/pdf/example.pdf",
            "metadata": {"error_stage": "EMBEDDING_ENCODE_FAILED"},
        },
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.claim_failed_document",
        lambda document_id, user_id: claimed.append((document_id, user_id)) or True,
    )

    result = KnowledgeIngestionWorkflow().prepare_reprocess(8, 7)

    assert result == {
        "document_id": 8,
        "error_stage": "EMBEDDING_ENCODE_FAILED",
        "retry_mode": "vector",
    }
    assert claimed == [(8, 7)]


def test_vector_stage_reprocess_reuses_saved_chunks(monkeypatch) -> None:
    events: list[Any] = []
    chunks = [
        {
            "id": 10,
            "document_id": 8,
            "knowledge_base_id": 7,
            "chunk_index": 0,
            "content": "正文",
            "context": "背景",
            "title": "标题",
            "chunk_type": "other",
            "source_type": "self",
            "source_name": "",
            "document_name": "文档",
            "analysis_status": "draft",
            "retrieval_status": "active",
            "strategy_id": None,
            "strategy_code": None,
            "tags": [],
        }
    ]

    class FakeEmbedding:
        model_name = "BAAI/bge-m3"
        dimension = 1024

        def prepare(self) -> None:
            events.append("prepare")

        def encode_documents(self, texts: list[str]) -> list[HybridEmbedding]:
            events.append(("encode", texts))
            return [HybridEmbedding([1.0], SparseEmbedding([1], [0.5]))]

    class FakeVector:
        def delete_by_document(self, document_id: int) -> None:
            events.append(("delete", document_id))

        def upsert(self, points: list[Any]) -> None:
            events.append(("upsert", [point.id for point in points]))

    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.get_document",
        lambda document_id, user_id: {
            "id": document_id,
            "name": "文档",
            "source_type": "self",
            "source_name": "",
        },
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.list_document_chunks",
        lambda document_id, user_id: chunks,
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.set_chunks_status",
        lambda ids, status, user_id, qdrant_point_ids=False: events.append(
            ("status", status, qdrant_point_ids)
        ),
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.update_document_status",
        lambda document_id, status, user_id, metadata: events.append(
            ("document", status, metadata.get("error_stage"))
        ),
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.get_embedding_service",
        lambda: FakeEmbedding(),
    )
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.get_vector_service",
        lambda: FakeVector(),
    )

    KnowledgeIngestionWorkflow().reprocess(8, 7, "EMBEDDING_FAILED")

    assert ("encode", ["背景\n正文"]) in events
    assert ("delete", 8) in events
    assert ("upsert", [10]) in events
    assert ("document", "INDEXED", None) in events


def test_chunk_failure_reprocess_requests_document_checkpoint_reuse(monkeypatch) -> None:
    calls: list[tuple[int, int, bool]] = []
    workflow = KnowledgeIngestionWorkflow()
    monkeypatch.setattr(
        workflow,
        "process",
        lambda document_id, user_id, reuse_document_analysis=False: calls.append(
            (document_id, user_id, reuse_document_analysis)
        ),
    )

    workflow.reprocess(8, 7, "CHUNK_ANALYSIS_FAILED")
    workflow.reprocess(9, 7, "DOCUMENT_ANALYSIS_FAILED")

    assert calls == [(8, 7, True), (9, 7, False)]


def test_ingestion_failure_persists_deepseek_error_detail(monkeypatch) -> None:
    updates: list[tuple[int, str, int, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.workflows.knowledge_ingestion.knowledge_repository.update_document_status",
        lambda document_id, status, user_id, metadata: updates.append(
            (document_id, status, user_id, metadata)
        ),
    )
    error = DeepSeekStructuredOutputError(
        "DeepSeek 返回内容不是合法 JSON",
        error_type="INVALID_JSON",
        operation="chunk_analysis",
        model="deepseek-v4-flash",
        attempt=3,
        response_id="response-3",
        finish_reason="stop",
        response_chars=826,
        json_error="Expecting ',' delimiter",
        json_line=12,
        json_column=18,
    )

    KnowledgeIngestionWorkflow._fail(8, 7, "CHUNK_ANALYSIS_FAILED", error)

    metadata = updates[0][3]
    assert updates[0][:3] == (8, "FAILED", 7)
    assert metadata["error_message"] == "DeepSeek 返回内容不是合法 JSON"
    assert metadata["error_detail"]["error_type"] == "INVALID_JSON"
    assert metadata["error_detail"]["json_line"] == 12


def test_document_analysis_checkpoint_keeps_only_reusable_fields() -> None:
    workflow = KnowledgeIngestionWorkflow()
    checkpoint = workflow._build_document_analysis_checkpoint(
        {
            "document_summary": "摘要",
            "document_context": {"topic": "主题"},
            "category": "other",
            "strategy_code": None,
            "strategy_candidate": None,
            "chunks": [{"start_block": 0, "end_block": 2}],
            "unexpected": "不保存",
        }
    )

    assert "unexpected" not in checkpoint
    assert workflow._load_document_analysis_checkpoint(
        {"metadata": {"document_analysis_checkpoint": checkpoint}}
    ) == checkpoint
