from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
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
    def prepare(self) -> None:
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
        download_if_missing: bool = True,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.download_if_missing = download_if_missing
        self._model: Any = None
        self._lock = Lock()
        self._inference_lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def prepare(self) -> None:
        self._get_model()

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
                        self._resolve_model_source(),
                        use_fp16=self.device.lower().startswith("cuda"),
                        devices=self.device,
                    )
        return self._model

    def _resolve_model_source(self) -> str:
        configured_path = Path(self._model_name).expanduser()
        if configured_path.is_dir():
            self._require_complete_model(configured_path)
            return str(configured_path.resolve())

        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "BGE-M3 本地缓存解析需要 huggingface-hub，请安装 requirements.txt"
            ) from exc

        download_options = {
            "repo_id": self._model_name,
            "ignore_patterns": ["onnx/*", "imgs/*", "*.jpg", "*.webp"],
        }
        local_path: Path | None = None
        try:
            local_path = Path(snapshot_download(local_files_only=True, **download_options))
        except Exception:
            local_path = None

        if local_path is not None and self._is_complete_model(local_path):
            return str(local_path.resolve())
        if not self.download_if_missing:
            raise RuntimeError(
                f"本地未找到完整的 Embedding 模型 {self._model_name}，且已禁止自动下载"
            )

        try:
            downloaded_path = Path(snapshot_download(local_files_only=False, **download_options))
        except Exception as exc:
            raise RuntimeError(
                f"本地未找到完整的 Embedding 模型 {self._model_name}，联网下载失败"
            ) from exc
        self._require_complete_model(downloaded_path)
        return str(downloaded_path.resolve())

    @staticmethod
    def _is_complete_model(path: Path) -> bool:
        has_weights = (path / "pytorch_model.bin").is_file() or (
            path / "model.safetensors"
        ).is_file()
        has_tokenizer = (path / "tokenizer.json").is_file() or (
            path / "sentencepiece.bpe.model"
        ).is_file()
        return all(
            [
                (path / "config.json").is_file(),
                has_weights,
                has_tokenizer,
                (path / "sparse_linear.pt").is_file(),
                (path / "colbert_linear.pt").is_file(),
            ]
        )

    @classmethod
    def _require_complete_model(cls, path: Path) -> None:
        if not cls._is_complete_model(path):
            raise RuntimeError(f"Embedding 模型目录不完整: {path}")

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
