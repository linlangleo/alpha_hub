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
from app.services.image_parser import ImageParser
from app.services.pdf_parser import PdfParser
from app.services.text_parser import TextParser
from app.services.vector_service import VectorPoint


logger = logging.getLogger(__name__)
FILE_TYPES = {
    ".docx": "docx",
    ".pdf": "pdf",
    ".txt": "text",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".webp": "image",
}
DEFAULT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "text": "text/plain",
}
MAX_INLINE_IMAGE_BYTES = 32 * 1024 * 1024
CHUNK_TYPES = {"principle", "market_environment", "stock_selection", "entry_rule",
               "exit_rule", "position_management", "risk_management", "intraday",
               "case", "review", "asset_allocation", "fund", "futures", "macro",
               "industry", "other"}
VECTOR_RETRY_STAGES = {
    "EMBEDDING_FAILED",
    "EMBEDDING_MODEL_PREPARE_FAILED",
    "EMBEDDING_ENCODE_FAILED",
    "QDRANT_UPSERT_FAILED",
}


class KnowledgeIngestionWorkflow:
    def create_upload(self, filename: str, content_type: str, content: bytes,
                      source_type: str, source_name: str, category: str,
                      strategy_id: int | None, analysis_model: str,
                      user_id: int) -> dict[str, Any]:
        safe_name = self._safe_filename(filename)
        file_type = FILE_TYPES.get(Path(safe_name).suffix.lower())
        if file_type is None:
            raise ValueError("仅支持 DOCX、PDF、TXT、JPEG、PNG、GIF、WebP")
        if not content:
            raise ValueError("不能上传空文件")
        if len(content) > SETTINGS.max_upload_size_mb * 1024 * 1024:
            raise ValueError(f"文件不能超过 {SETTINGS.max_upload_size_mb} MB")
        if file_type == "image" and len(content) > MAX_INLINE_IMAGE_BYTES:
            raise ValueError("图片不能超过 32 MB")
        if strategy_id is not None and strategy_repository.get_strategy(strategy_id) is None:
            raise ValueError("指定的正式策略不存在")
        selected_model = self._select_model(file_type, analysis_model)
        actual_content_type = content_type or DEFAULT_CONTENT_TYPES.get(
            file_type,
            "application/octet-stream",
        )
        if file_type == "image":
            actual_content_type = ImageParser().validate(content)

        document_id = generate_id()
        document = knowledge_repository.create_document(
            document_id=document_id, name=Path(safe_name).stem,
            original_filename=safe_name, source_type=source_type,
            source_name=source_name, category=category, strategy_id=strategy_id,
            file_type=file_type,
            metadata={"mime_type": actual_content_type, "file_size": len(content),
                      "content_hash": hashlib.sha256(content).hexdigest(),
                      "analysis_model": selected_model,
                      "progress": 0, "processing_stage": "UPLOAD", "stage_label": "上传中"},
            user_id=user_id,
        )
        now = datetime.now()
        object_key = f"raw/{file_type}/{now:%Y}/{now:%m}/{document_id}/{safe_name}"
        try:
            get_storage_service().put_bytes(
                object_key, content,
                actual_content_type,
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
        stage = "PARSE_FAILED"
        try:
            document = knowledge_repository.get_document(document_id, user_id)
            if document is None:
                raise LookupError("知识文档不存在")
            file_type = str(document["file_type"])
            analysis_model = self._select_model(
                file_type,
                str((document.get("metadata") or {}).get("analysis_model") or ""),
            )
            parsing_label = "图片视觉识别中" if file_type == "image" else "解析中"
            self._progress(document_id, user_id, "PARSING", 20, parsing_label)
            content = get_storage_service().get_bytes(document["minio_object_key"])
            if file_type == "image":
                stage = "IMAGE_ANALYSIS_FAILED"
            parsed = self._parse_document(
                document,
                content,
                analysis_model,
            )
            stage = "EXTRACTED_IMAGE_SAVE_FAILED"
            self._store_images(document_id, parsed.blocks, parsed.images)

            stage = "DOCUMENT_ANALYSIS_FAILED"
            self._progress(document_id, user_id, "DOCUMENT_ANALYSIS", 35, "文档理解中")
            strategies = strategy_repository.list_strategies()
            document_analysis = get_deepseek_service().analyze_document(
                {"name": document["name"], "original_filename": document["original_filename"],
                 "source_type": document["source_type"], "source_name": document["source_name"],
                 "category": document["category"]},
                [block.analysis_dict() for block in parsed.blocks],
                strategies,
                model=analysis_model,
            )
            requested_strategy = (strategy_repository.get_strategy(int(document["strategy_id"]))
                                  if document.get("strategy_id") else None)
            by_code = {str(item["code"]): item for item in strategies}
            document_strategy = requested_strategy or by_code.get(document_analysis.get("strategy_code"))
            document_context = document_analysis.get("document_context")
            if not isinstance(document_context, dict):
                raise RuntimeError("文档级分析缺少 document_context")

            stage = "CHUNK_BUILD_FAILED"
            base_chunks = self._rebuild_chunks(parsed.blocks, document_analysis)
            if not base_chunks:
                raise RuntimeError("文档分析后没有生成有效 Chunk")

            stage = "CHUNK_ANALYSIS_FAILED"
            self._progress(document_id, user_id, "CHUNK_ANALYSIS", 50, "Chunk 批量分析中")
            chunks = self._analyze_chunks(
                base_chunks, document_context,
                str(document_strategy["code"]) if document_strategy else None,
                strategies, knowledge_repository.list_tag_names(user_id),
                analysis_model,
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
                                   "parser_version": f"{file_type}-order-1.0",
                                   "llm_model": analysis_model,
                                   "block_count": len(parsed.blocks)},
                chunks=chunks,
            )
            saved_chunk_ids = [int(item["id"]) for item in saved]

            stage = "EMBEDDING_MODEL_PREPARE_FAILED"
            self._progress(document_id, user_id, "EMBEDDING_MODEL_PREPARE", 70,
                           "BGE-M3 本地模型检查 / 加载中")
            embedding_service = get_embedding_service()
            embedding_service.prepare()

            stage = "EMBEDDING_ENCODE_FAILED"
            self._progress(document_id, user_id, "EMBEDDING", 75, "BGE-M3 向量化中")
            knowledge_repository.set_chunks_status(saved_chunk_ids, "embedding", user_id)
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

    def prepare_reprocess(self, document_id: int, user_id: int) -> dict[str, Any]:
        document = knowledge_repository.find_document(document_id)
        if document is None:
            raise LookupError("知识文档不存在")
        if int(document["create_by"]) != user_id:
            raise PermissionError("该文档不是你上传的，无重新处理权限")
        if str(document["status"]) != "FAILED":
            raise ValueError("只有 FAILED 状态的文档允许重新处理")

        error_stage = str((document.get("metadata") or {}).get("error_stage") or "UNKNOWN_FAILED")
        retry_mode = "vector" if error_stage in VECTOR_RETRY_STAGES else "full"
        if retry_mode == "full" and not document.get("minio_object_key"):
            raise RuntimeError("原文件不存在，请重新上传")
        if not knowledge_repository.claim_failed_document(document_id, user_id):
            raise ValueError("文档状态已变化，请刷新后重试")
        return {
            "document_id": document_id,
            "error_stage": error_stage,
            "retry_mode": retry_mode,
        }

    def reprocess(
        self,
        document_id: int,
        user_id: int,
        error_stage: str,
    ) -> None:
        if error_stage in VECTOR_RETRY_STAGES:
            self._resume_indexing(document_id, user_id)
            return
        self.process(document_id, user_id)

    def _resume_indexing(self, document_id: int, user_id: int) -> None:
        saved_chunk_ids: list[int] = []
        stage = "EMBEDDING_MODEL_PREPARE_FAILED"
        try:
            document = knowledge_repository.get_document(document_id, user_id)
            if document is None:
                raise LookupError("知识文档不存在")
            chunks = knowledge_repository.list_document_chunks(document_id, user_id)
            if not chunks:
                self.process(document_id, user_id)
                return
            saved_chunk_ids = [int(item["id"]) for item in chunks]

            self._progress(document_id, user_id, "EMBEDDING_MODEL_PREPARE", 70,
                           "BGE-M3 本地模型检查 / 加载中")
            embedding_service = get_embedding_service()
            embedding_service.prepare()

            stage = "EMBEDDING_ENCODE_FAILED"
            self._progress(document_id, user_id, "EMBEDDING", 75, "BGE-M3 向量化中")
            knowledge_repository.set_chunks_status(saved_chunk_ids, "embedding", user_id)
            embeddings = embedding_service.encode_documents([
                build_embedding_text(item.get("context"), str(item["content"])) for item in chunks
            ])

            stage = "QDRANT_UPSERT_FAILED"
            self._progress(document_id, user_id, "QDRANT_INDEXING", 90, "Qdrant 索引中")
            vector_service = get_vector_service()
            vector_service.delete_by_document(document_id)
            vector_service.upsert([
                VectorPoint(
                    id=int(chunk["id"]),
                    embedding=embedding,
                    payload=self._payload(
                        document,
                        chunk,
                        chunk,
                        embedding_service.model_name,
                    ),
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ])
            knowledge_repository.set_chunks_status(saved_chunk_ids, "embedded", user_id, True)
            knowledge_repository.update_document_status(
                document_id,
                "INDEXED",
                user_id,
                {
                    "progress": 100,
                    "processing_stage": None,
                    "stage_label": "完成",
                    "embedding_model": embedding_service.model_name,
                    "embedding_dimension": embedding_service.dimension,
                    "error_stage": None,
                    "error_message": None,
                },
            )
        except Exception as exc:
            logger.exception(
                "Knowledge reprocess failed document_id=%s chunk_ids=%s stage=%s",
                document_id,
                saved_chunk_ids,
                stage,
            )
            if saved_chunk_ids:
                knowledge_repository.set_chunks_status(
                    saved_chunk_ids,
                    "pending_retry",
                    user_id,
                )
            self._fail(document_id, user_id, stage, exc)

    @staticmethod
    def _select_model(file_type: str, requested_model: str) -> str:
        if file_type == "image":
            if requested_model and requested_model != SETTINGS.deepseek_vision_model:
                raise ValueError("图片只能使用配置的 DeepSeek Vision 模型")
            return SETTINGS.deepseek_vision_model
        selected = requested_model or SETTINGS.deepseek_model
        if selected not in SETTINGS.deepseek_text_models:
            raise ValueError("文档分析模型不在允许的文本模型列表中")
        return selected

    @staticmethod
    def _parse_document(
        document: dict[str, Any],
        content: bytes,
        analysis_model: str,
    ) -> Any:
        file_type = str(document["file_type"])
        if file_type == "docx":
            return DocxParser().parse(content)
        if file_type == "pdf":
            return PdfParser().parse(content)
        if file_type == "text":
            return TextParser().parse(content)
        if file_type == "image":
            content_type = ImageParser().validate(content)
            analysis = get_deepseek_service().analyze_image(
                content,
                content_type,
                str(document["original_filename"]),
                analysis_model,
            )
            return ImageParser.from_analysis(
                str(document["minio_object_key"]),
                analysis,
            )
        raise ValueError(f"不支持的文档类型: {file_type}")

    def _analyze_chunks(self, chunks: list[dict[str, Any]], document_context: dict[str, Any],
                        document_strategy_code: str | None,
                        strategies: list[dict[str, Any]], existing_tags: list[str],
                        analysis_model: str) -> list[dict[str, Any]]:
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
                document_context,
                document_strategy_code,
                inputs,
                strategies,
                existing_tags,
                model=analysis_model,
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
                                                 str(base["content"]),
                                                 analysis_model)
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
                          strategy_code: str | None, content: str,
                          analysis_model: str) -> str:
        current = context.strip()
        attempts = 0
        while len(current) > SETTINGS.context_max_chars and attempts < 2:
            current = get_deepseek_service().regenerate_context(
                document_context,
                strategy_code,
                content,
                current,
                compress=True,
                model=analysis_model,
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
            if len(value) > SETTINGS.max_chunk_chars:
                if current:
                    groups.append(current)
                    current, length = [], 0
                if block.type == "image" and block.image_id and block.text:
                    marker_length = len(f"[[IMAGE:{block.image_id}]]\n\n")
                    first_size = max(1, SETTINGS.max_chunk_chars - marker_length)
                    groups.append([
                        DocumentBlock(
                            type="image",
                            index=block.index,
                            text=block.text[:first_size],
                            image_id=block.image_id,
                            object_key=block.object_key,
                        )
                    ])
                    for offset in range(
                        first_size,
                        len(block.text),
                        SETTINGS.max_chunk_chars,
                    ):
                        groups.append([
                            DocumentBlock(
                                type="paragraph",
                                index=block.index,
                                text=block.text[
                                    offset:offset + SETTINGS.max_chunk_chars
                                ],
                            )
                        ])
                    continue
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
