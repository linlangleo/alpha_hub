from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class HybridEmbedding:
    dense: list[float]
    sparse: SparseEmbedding


def build_embedding_text(context: str | None, content: str) -> str:
    normalized_context = (context or "").strip()
    normalized_content = (content or "").strip()
    if normalized_context:
        return f"{normalized_context}\n{normalized_content}"
    return normalized_content


class EmbeddingService(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def encode_documents(self, texts: list[str]) -> list[HybridEmbedding]:
        raise NotImplementedError

    @abstractmethod
    def encode_query(self, text: str) -> HybridEmbedding:
        raise NotImplementedError


class BgeM3EmbeddingService(EmbeddingService):
    """BGE-M3 boundary returning dense and lexical sparse vectors together."""

    def __init__(
        self,
        model_name: str,
        dimension: int,
        device: str = "cpu",
        batch_size: int = 4,
        max_length: int = 8192,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self._model: Any = None
        self._lock = Lock()
        self._inference_lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from FlagEmbedding import BGEM3FlagModel
                    except ImportError as exc:
                        raise RuntimeError(
                            "BGE-M3 需要 FlagEmbedding，请安装 requirements.txt"
                        ) from exc
                    self._model = BGEM3FlagModel(
                        self._model_name,
                        use_fp16=self.device.lower().startswith("cuda"),
                        devices=self.device,
                    )
        return self._model

    def encode_documents(self, texts: list[str]) -> list[HybridEmbedding]:
        if not texts:
            return []
        return self._encode(texts)

    def encode_query(self, text: str) -> HybridEmbedding:
        if not text.strip():
            raise ValueError("检索问题不能为空")
        return self._encode([text])[0]

    def _encode(self, texts: list[str]) -> list[HybridEmbedding]:
        model = self._get_model()
        with self._inference_lock:
            output = model.encode(
                texts,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
        dense_values = output.get("dense_vecs")
        sparse_values = output.get("lexical_weights")
        if dense_values is None or sparse_values is None:
            raise RuntimeError("BGE-M3 未返回 dense_vecs 或 lexical_weights")

        result: list[HybridEmbedding] = []
        for dense, sparse in zip(dense_values, sparse_values, strict=True):
            dense_list = [float(value) for value in dense.tolist()]
            if len(dense_list) != self.dimension:
                raise RuntimeError(
                    f"Embedding 维度不匹配，配置为 {self.dimension}，实际为 {len(dense_list)}"
                )
            pairs = sorted(
                ((int(index), float(value)) for index, value in dict(sparse).items()),
                key=lambda item: item[0],
            )
            result.append(
                HybridEmbedding(
                    dense=dense_list,
                    sparse=SparseEmbedding(
                        indices=[item[0] for item in pairs],
                        values=[item[1] for item in pairs],
                    ),
                )
            )
        return result
