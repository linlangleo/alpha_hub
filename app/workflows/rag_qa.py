from typing import Any

from app.core.config import SETTINGS
from app.repositories import knowledge_repository
from app.services.container import (get_deepseek_service, get_embedding_service,
                                    get_vector_service)


class RagQaWorkflow:
    def retrieve(self, query: str, top_k: int, user_id: int,
                 filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query_embedding = get_embedding_service().encode_query(query)
        effective_filters = dict(filters or {})
        effective_filters["knowledge_base_id"] = user_id
        effective_filters["retrieval_status"] = "active"
        hits = get_vector_service().search(
            query_embedding, top_k, effective_filters, mode=SETTINGS.retrieval_mode
        )
        chunk_ids = [int(hit["chunk_id"]) for hit in hits if hit.get("chunk_id") is not None]
        rows = knowledge_repository.get_chunks_by_ids(chunk_ids, user_id)
        by_id = {int(row["id"]): row for row in rows}
        return [{**by_id[int(hit["chunk_id"])], "score": float(hit["score"])}
                for hit in hits if hit.get("chunk_id") is not None
                and int(hit["chunk_id"]) in by_id]

    def answer(self, question: str, top_k: int, neighbor_window: int, user_id: int,
               filters: dict[str, Any] | None = None) -> dict[str, Any]:
        primary = self.retrieve(question, top_k, user_id, filters)
        expand_count = min(SETTINGS.neighbor_expand_top_n, len(primary))
        anchors = [(int(item["document_id"]), int(item["chunk_index"]))
                   for item in primary[:expand_count]]
        neighbors = knowledge_repository.get_neighbor_chunks(anchors, neighbor_window, user_id)
        neighbor_map = {(int(item["document_id"]), int(item["chunk_index"])): item
                        for item in neighbors}

        contexts: list[dict[str, Any]] = []
        used: set[int] = set()
        for rank, hit in enumerate(primary):
            document_id = int(hit["document_id"])
            chunk_index = int(hit["chunk_index"])
            indexes = ([chunk_index] if rank >= expand_count else
                       list(range(max(0, chunk_index - neighbor_window),
                                  chunk_index + neighbor_window + 1)))
            for index in indexes:
                item = neighbor_map.get((document_id, index)) if rank < expand_count else None
                if item is None and index == chunk_index:
                    item = hit
                if item is None or int(item["id"]) in used:
                    continue
                used.add(int(item["id"]))
                contexts.append({
                    "原始知识": item["content"],
                    "AI生成背景": item.get("context"),
                    "知识元数据": {
                        "document": item["document_name"], "chunk_id": str(item["id"]),
                        "chunk_index": item["chunk_index"], "title": item["title"],
                        "chunk_type": item["chunk_type"], "strategy": item.get("strategy_name"),
                        "tags": item.get("tags", []), "source": item.get("source_name"),
                        "summary": item.get("summary"),
                        "analysis_status": item.get("analysis_status"),
                        "retrieval_score": hit["score"], "is_neighbor": index != chunk_index,
                    },
                })
        answer = get_deepseek_service().answer_knowledge(question, contexts)
        sources = [{
            "chunk_id": str(item["id"]), "document_id": str(item["document_id"]),
            "document_name": item["document_name"], "chunk_index": item["chunk_index"],
            "chunk_title": item["title"], "chunk_type": item["chunk_type"],
            "strategy": item.get("strategy_name"), "score": item["score"],
            "analysis_status": item.get("analysis_status"),
        } for item in primary]
        return {"answer": answer, "sources": sources}


rag_qa_workflow = RagQaWorkflow()
