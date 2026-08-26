import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import SETTINGS
from app.core.snowflake import generate_id
from app.repositories import knowledge_repository, strategy_repository
from app.services.container import (get_deepseek_service, get_embedding_service,
                                    get_storage_service, get_vector_service)
from app.services.docx_parser import DocumentBlock, DocxParser
from app.services.embedding_service import build_embedding_text
from app.services.vector_service import VectorPoint


logger = logging.getLogger(__name__)
CHUNK_TYPES = {"principle", "market_environment", "stock_selection", "entry_rule",
               "exit_rule", "position_management", "risk_management", "intraday",
               "case", "review", "asset_allocation", "fund", "futures", "macro",
               "industry", "other"}


class KnowledgeIngestionWorkflow:
    def create_upload(self, filename: str, content_type: str, content: bytes,
                      source_type: str, source_name: str, category: str,
                      strategy_id: int | None, user_id: int) -> dict[str, Any]:
        safe_name = self._safe_filename(filename)
        if Path(safe_name).suffix.lower() != ".docx":
            raise ValueError("第一阶段只支持 DOCX 智能入库")
        if not content:
            raise ValueError("不能上传空文件")
        if len(content) > SETTINGS.max_upload_size_mb * 1024 * 1024:
            raise ValueError(f"文件不能超过 {SETTINGS.max_upload_size_mb} MB")
        if strategy_id is not None and strategy_repository.get_strategy(strategy_id) is None:
            raise ValueError("指定的正式策略不存在")

        document_id = generate_id()
        document = knowledge_repository.create_document(
            document_id=document_id, name=Path(safe_name).stem,
            original_filename=safe_name, source_type=source_type,
            source_name=source_name, category=category, strategy_id=strategy_id,
            metadata={"mime_type": content_type, "file_size": len(content),
                      "content_hash": hashlib.sha256(content).hexdigest(),
                      "progress": 0, "processing_stage": "UPLOAD", "stage_label": "上传中"},
            user_id=user_id,
        )
        now = datetime.now()
        object_key = f"raw/docx/{now:%Y}/{now:%m}/{document_id}/{safe_name}"
        try:
            get_storage_service().put_bytes(
                object_key, content,
                content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            knowledge_repository.update_document_storage(
                document_id, SETTINGS.minio_bucket, object_key,
                {"progress": 10, "processing_stage": None, "stage_label": "等待解析"}, user_id,
            )
        except Exception as exc:
            self._fail(document_id, user_id, "MINIO_UPLOAD_FAILED", exc)
            raise
        document["minio_bucket"] = SETTINGS.minio_bucket
        document["minio_object_key"] = object_key
        return document

    def process(self, document_id: int, user_id: int) -> None:
        saved_chunk_ids: list[int] = []
        stage = "DOCX_PARSE_FAILED"
        try:
            document = knowledge_repository.get_document(document_id, user_id)
            if document is None:
                raise LookupError("知识文档不存在")
            self._progress(document_id, user_id, "PARSING", 20, "解析中")
            content = get_storage_service().get_bytes(document["minio_object_key"])
            parsed = DocxParser().parse(content)
            stage = "MINIO_UPLOAD_FAILED"
            self._store_images(document_id, parsed.blocks, parsed.images)

            stage = "DOCUMENT_ANALYSIS_FAILED"
            self._progress(document_id, user_id, "DOCUMENT_ANALYSIS", 35, "文档理解中")
            strategies = strategy_repository.list_strategies()
            document_analysis = get_deepseek_service().analyze_document(
                {"name": document["name"], "original_filename": document["original_filename"],
                 "source_type": document["source_type"], "source_name": document["source_name"],
                 "category": document["category"]},
                [block.analysis_dict() for block in parsed.blocks], strategies,
            )
            base_chunks = self._rebuild_chunks(parsed.blocks, document_analysis)
            if not base_chunks:
                raise RuntimeError("文档分析后没有生成有效 Chunk")

            requested_strategy = (strategy_repository.get_strategy(int(document["strategy_id"]))
                                  if document.get("strategy_id") else None)
            by_code = {str(item["code"]): item for item in strategies}
            document_strategy = requested_strategy or by_code.get(document_analysis.get("strategy_code"))
            document_context = document_analysis.get("document_context")
            if not isinstance(document_context, dict):
                raise RuntimeError("文档级分析缺少 document_context")

            stage = "CHUNK_ANALYSIS_FAILED"
            self._progress(document_id, user_id, "CHUNK_ANALYSIS", 50, "Chunk 批量分析中")
            chunks = self._analyze_chunks(
                base_chunks, document_context,
                str(document_strategy["code"]) if document_strategy else None,
                strategies, knowledge_repository.list_tag_names(user_id),
            )

            stage = "DATABASE_SAVE_FAILED"
            self._progress(document_id, user_id, "CHUNK_ANALYSIS", 65, "知识入库中")
            saved = knowledge_repository.save_analysis(
                document_id=document_id, user_id=user_id,
                summary=str(document_analysis.get("document_summary") or ""),
                category=str(document_analysis.get("category") or document["category"] or "other")[:100],
                strategy_id=int(document_strategy["id"]) if document_strategy else None,
                document_metadata={"document_context": document_context,
                                   "strategy_candidate": document_analysis.get("strategy_candidate"),
                                   "parser_version": "docx-order-1.0",
                                   "llm_model": SETTINGS.deepseek_model,
                                   "block_count": len(parsed.blocks)},
                chunks=chunks,
            )
            saved_chunk_ids = [int(item["id"]) for item in saved]

            stage = "EMBEDDING_FAILED"
            self._progress(document_id, user_id, "EMBEDDING", 75, "BGE-M3 向量化中")
            knowledge_repository.set_chunks_status(saved_chunk_ids, "embedding", user_id)
            embedding_service = get_embedding_service()
            embeddings = embedding_service.encode_documents([
                build_embedding_text(item.get("context"), str(item["content"])) for item in saved
            ])

            stage = "QDRANT_UPSERT_FAILED"
            self._progress(document_id, user_id, "QDRANT_INDEXING", 90, "Qdrant 索引中")
            vector_service = get_vector_service()
            vector_service.delete_by_document(document_id)
            vector_service.upsert([
                VectorPoint(id=int(chunk["id"]), embedding=embedding,
                            payload=self._payload(document, chunk, chunks[index],
                                                  embedding_service.model_name))
                for index, (chunk, embedding) in enumerate(zip(saved, embeddings, strict=True))
            ])
            knowledge_repository.set_chunks_status(saved_chunk_ids, "embedded", user_id, True)
            knowledge_repository.update_document_status(
                document_id, "INDEXED", user_id,
                {"progress": 100, "processing_stage": None, "stage_label": "完成",
                 "embedding_model": embedding_service.model_name,
                 "embedding_dimension": embedding_service.dimension,
                 "error_stage": None, "error_message": None},
            )
        except Exception as exc:
            logger.exception("Knowledge ingestion failed document_id=%s chunk_ids=%s stage=%s",
                             document_id, saved_chunk_ids, stage)
            if saved_chunk_ids:
                knowledge_repository.set_chunks_status(saved_chunk_ids, "pending_retry", user_id)
            self._fail(document_id, user_id, stage, exc)

    def _analyze_chunks(self, chunks: list[dict[str, Any]], document_context: dict[str, Any],
                        document_strategy_code: str | None,
                        strategies: list[dict[str, Any]], existing_tags: list[str]) -> list[dict[str, Any]]:
        by_code = {str(item["code"]): item for item in strategies}
        result: list[dict[str, Any]] = []
        size = max(5, min(8, SETTINGS.chunk_analysis_batch_size))
        for start in range(0, len(chunks), size):
            batch = chunks[start:start + size]
            inputs = []
            for item in batch:
                index = int(item["chunk_index"])
                inputs.append({"chunk_index": index, "content": item["content"],
                               "previous_content": chunks[index - 1]["content"] if index > 0 else None,
                               "next_content": chunks[index + 1]["content"]
                               if index + 1 < len(chunks) else None})
            response = get_deepseek_service().analyze_chunk_batch(
                document_context, document_strategy_code, inputs, strategies, existing_tags
            )
            values = response.get("chunks")
            if not isinstance(values, list):
                raise RuntimeError("Chunk 批量分析未返回 chunks 数组")
            mapped = {int(item["chunk_index"]): item for item in values if isinstance(item, dict)
                      and "chunk_index" in item}
            if set(mapped) != {int(item["chunk_index"]) for item in batch}:
                raise RuntimeError("Chunk 批量分析返回的 chunk_index 不完整或重复")
            for base in batch:
                meta = mapped[int(base["chunk_index"])]
                context = self._validate_context(str(meta.get("context") or ""),
                                                 document_context,
                                                 meta.get("strategy_code") or document_strategy_code,
                                                 str(base["content"]))
                chunk_type = str(meta.get("chunk_type") or "other")
                if chunk_type not in CHUNK_TYPES:
                    chunk_type = "other"
                if "strategy_code" in meta:
                    code = meta.get("strategy_code")
                    selected = by_code.get(str(code)) if code else None
                else:
                    selected = by_code.get(document_strategy_code or "")
                tags = self._clean_tags(meta.get("existing_tags"), meta.get("new_tags"))
                result.append({**base, "title": str(meta.get("title") or
                                                    f"知识片段 {base['chunk_index'] + 1}")[:500],
                               "context": context, "summary": str(meta.get("summary") or ""),
                               "chunk_type": chunk_type,
                               "strategy_id": int(selected["id"]) if selected else None,
                               "strategy_code": str(selected["code"]) if selected else None,
                               "tags": tags,
                               "metadata": {**base.get("metadata", {}),
                                            "strategy_candidate": meta.get("strategy_candidate")}})
        return result

    def _validate_context(self, context: str, document_context: dict[str, Any],
                          strategy_code: str | None, content: str) -> str:
        current = context.strip()
        attempts = 0
        while len(current) > SETTINGS.context_max_chars and attempts < 2:
            current = get_deepseek_service().regenerate_context(
                document_context, strategy_code, content, current, compress=True
            ).strip()
            attempts += 1
        if len(current) > SETTINGS.context_max_chars:
            raise RuntimeError(f"Context 经重新压缩后仍超过 {SETTINGS.context_max_chars} 字符")
        return current

    def _rebuild_chunks(self, blocks: list[DocumentBlock],
                        analysis: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = analysis.get("chunks")
        ranges = self._normalize_ranges(candidates if isinstance(candidates, list) else [], len(blocks))
        result: list[dict[str, Any]] = []
        for boundary in ranges:
            for group in self._protect_max_length(blocks[boundary["start_block"]:
                                                         boundary["end_block"] + 1]):
                content = "\n\n".join(block.content() for block in group if block.content())
                if not content:
                    continue
                result.append({"content": content, "chunk_index": len(result),
                               "image_keys": [{"image_id": block.image_id,
                                               "object_key": block.object_key}
                                              for block in group if block.type == "image"
                                              and block.image_id and block.object_key],
                               "metadata": {"block_start": group[0].index,
                                            "block_end": group[-1].index,
                                            "semantic_boundary": True}})
        return result

    @staticmethod
    def _normalize_ranges(candidates: list[Any], block_count: int) -> list[dict[str, int]]:
        if block_count <= 0:
            return []
        valid = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            try:
                start, end = int(item["start_block"]), int(item["end_block"])
            except (KeyError, TypeError, ValueError):
                continue
            if end < start:
                continue
            valid.append({"start_block": max(0, min(start, block_count - 1)),
                          "end_block": max(0, min(end, block_count - 1))})
        valid.sort(key=lambda item: (item["start_block"], item["end_block"]))
        result: list[dict[str, int]] = []
        cursor = 0
        for item in valid:
            start = max(cursor, item["start_block"])
            if start > cursor:
                result.append({"start_block": cursor, "end_block": start - 1})
            if item["end_block"] >= start:
                result.append({"start_block": start, "end_block": item["end_block"]})
                cursor = item["end_block"] + 1
            if cursor >= block_count:
                break
        if cursor < block_count:
            result.append({"start_block": cursor, "end_block": block_count - 1})
        return result

    @staticmethod
    def _protect_max_length(blocks: list[DocumentBlock]) -> list[list[DocumentBlock]]:
        groups: list[list[DocumentBlock]] = []
        current: list[DocumentBlock] = []
        length = 0
        for block in blocks:
            value = block.content()
            if len(value) > SETTINGS.max_chunk_chars and block.type != "image":
                if current:
                    groups.append(current)
                    current, length = [], 0
                for offset in range(0, len(value), SETTINGS.max_chunk_chars):
                    groups.append([DocumentBlock(type=block.type, index=block.index,
                                                 text=value[offset:offset + SETTINGS.max_chunk_chars])])
                continue
            extra = len(value) + (2 if current else 0)
            if current and length + extra > SETTINGS.max_chunk_chars:
                groups.append(current)
                current, length = [], 0
            current.append(block)
            length += len(value) + (2 if length else 0)
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _clean_tags(existing: Any, new: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        existing_values = existing if isinstance(existing, list) else []
        new_values = new if isinstance(new, list) else []
        for value in [*existing_values, *new_values]:
            tag = str(value).strip()[:100]
            if tag and tag.casefold() not in seen:
                seen.add(tag.casefold())
                result.append(tag)
        return result[:20]

    @staticmethod
    def _store_images(document_id: int, blocks: list[DocumentBlock], images: list[Any]) -> None:
        for image in images:
            object_key = f"extracted/images/{document_id}/{image.filename}"
            get_storage_service().put_bytes(object_key, image.data, image.content_type)
            for block in blocks:
                if block.image_id == image.image_id:
                    block.object_key = object_key

    @staticmethod
    def _payload(document: dict[str, Any], saved: dict[str, Any], analyzed: dict[str, Any],
                 model_name: str) -> dict[str, Any]:
        return {"chunk_id": int(saved["id"]), "document_id": int(saved["document_id"]),
                "knowledge_base_id": int(saved["knowledge_base_id"]),
                "chunk_index": int(saved["chunk_index"]), "title": saved.get("title"),
                "context": saved.get("context"), "strategy_id": saved.get("strategy_id"),
                "strategy_code": analyzed.get("strategy_code"),
                "chunk_type": saved.get("chunk_type"), "source_type": document.get("source_type"),
                "source_name": document.get("source_name"), "document_name": document.get("name"),
                "tags": saved.get("tags", []), "analysis_status": "draft",
                "retrieval_status": "active", "embedding_model": model_name}

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = Path(filename).name.strip() or "unnamed.docx"
        return "".join(char if char.isalnum() or char in "._- " else "_" for char in safe)[:240]

    @staticmethod
    def _progress(document_id: int, user_id: int, processing_stage: str,
                  progress: int, label: str) -> None:
        knowledge_repository.update_document_status(
            document_id, "PROCESSING", user_id,
            {"processing_stage": processing_stage, "progress": progress, "stage_label": label},
        )

    @staticmethod
    def _fail(document_id: int, user_id: int, stage: str, exc: Exception) -> None:
        knowledge_repository.update_document_status(
            document_id, "FAILED", user_id,
            {"processing_stage": None, "progress": 100, "stage_label": "失败",
             "error_stage": stage, "error_message": str(exc)[:2000]},
        )


knowledge_ingestion_workflow = KnowledgeIngestionWorkflow()
