from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient, models

from app.services.embedding_service import HybridEmbedding


FORBIDDEN_PAYLOAD_FIELDS = {
    "content", "summary", "image_keys", "document_summary", "content_preview"
}


@dataclass(frozen=True)
class VectorPoint:
    id: int
    embedding: HybridEmbedding
    payload: dict[str, Any]


class QdrantService:
    """Qdrant stores named vectors and light retrieval metadata only."""

    def __init__(self, url: str, collection_name: str, dimension: int,
                 api_key: str | None = None) -> None:
        self.collection_name = collection_name
        self.dimension = dimension
        self.client = QdrantClient(url=url, api_key=api_key or None, timeout=30)

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            info = self.client.get_collection(self.collection_name)
            vectors = info.config.params.vectors
            sparse_vectors = info.config.params.sparse_vectors or {}
            if (
                not isinstance(vectors, dict)
                or "dense" not in vectors
                or int(vectors["dense"].size) != self.dimension
                or "sparse" not in sparse_vectors
            ):
                raise RuntimeError(
                    f"Qdrant Collection {self.collection_name} 不是当前 dense+sparse 结构，"
                    "请执行 recreate_collection()"
                )
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": models.VectorParams(size=self.dimension, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )
        schemas = {
            "chunk_id": models.PayloadSchemaType.INTEGER,
            "document_id": models.PayloadSchemaType.INTEGER,
            "knowledge_base_id": models.PayloadSchemaType.INTEGER,
            "chunk_index": models.PayloadSchemaType.INTEGER,
            "strategy_id": models.PayloadSchemaType.INTEGER,
            "strategy_code": models.PayloadSchemaType.KEYWORD,
            "chunk_type": models.PayloadSchemaType.KEYWORD,
            "source_type": models.PayloadSchemaType.KEYWORD,
            "source_name": models.PayloadSchemaType.KEYWORD,
            "tags": models.PayloadSchemaType.KEYWORD,
            "analysis_status": models.PayloadSchemaType.KEYWORD,
            "retrieval_status": models.PayloadSchemaType.KEYWORD,
        }
        for field_name, field_schema in schemas.items():
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=field_schema,
            )

    def recreate_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
        self.ensure_collection()

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        for point in points:
            self._validate_payload(point.payload)
        self.ensure_collection()
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point.id,
                    vector={
                        "dense": point.embedding.dense,
                        "sparse": models.SparseVector(
                            indices=point.embedding.sparse.indices,
                            values=point.embedding.sparse.values,
                        ),
                    },
                    payload=point.payload,
                )
                for point in points
            ],
            wait=True,
        )

    def update_payload(self, point_id: int, payload: dict[str, Any]) -> None:
        self._validate_payload(payload)
        self.ensure_collection()
        self.client.set_payload(
            collection_name=self.collection_name,
            payload=payload,
            points=[point_id],
            wait=True,
        )

    def search(self, query_embedding: HybridEmbedding, top_k: int,
               filters: dict[str, Any] | None = None,
               mode: str = "hybrid") -> list[dict[str, Any]]:
        self.ensure_collection()
        query_filter = self._build_filter(filters)
        if mode == "dense":
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding.dense,
                using="dense",
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        elif mode == "hybrid":
            prefetch_limit = max(top_k * 2, top_k)
            result = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(query=query_embedding.dense, using="dense",
                                    filter=query_filter, limit=prefetch_limit),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=query_embedding.sparse.indices,
                            values=query_embedding.sparse.values,
                        ),
                        using="sparse",
                        filter=query_filter,
                        limit=prefetch_limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        else:
            raise ValueError("检索模式只支持 dense 或 hybrid")
        return [
            {"point_id": point.id, "score": point.score, **dict(point.payload or {})}
            for point in result.points
        ]

    def delete_by_document(self, document_id: int) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(
                    key="document_id", match=models.MatchValue(value=document_id)
                )])
            ),
            wait=True,
        )

    def check(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    @staticmethod
    def _build_filter(filters: dict[str, Any] | None) -> models.Filter | None:
        conditions: list[models.FieldCondition] = []
        for key, value in (filters or {}).items():
            if value in (None, "", []):
                continue
            match = (models.MatchAny(any=value) if isinstance(value, list)
                     else models.MatchValue(value=value))
            conditions.append(models.FieldCondition(key=key, match=match))
        return models.Filter(must=conditions) if conditions else None

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        forbidden = FORBIDDEN_PAYLOAD_FIELDS.intersection(payload)
        if forbidden:
            raise ValueError(f"Qdrant Payload 禁止保存正文类字段: {sorted(forbidden)}")
