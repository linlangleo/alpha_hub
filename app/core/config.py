import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
load_dotenv(PROJECT_ROOT / ".env")


def load_config() -> dict[str, Any]:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"配置文件不存在: {CONFIG_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"配置文件 JSON 格式错误: {exc}") from exc

    required = ("database", "redis", "minio", "qdrant", "deepseek", "embedding", "knowledge")
    for section in required:
        if section not in config:
            raise RuntimeError(f"配置文件缺少 {section} 节点")
    return config


def _env(name: str, default: Any) -> Any:
    value = os.getenv(name)
    return default if value is None else value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout: float
    deepseek_retry: int
    deepseek_max_input_chars: int
    deepseek_max_output_tokens: int
    embedding_model: str
    embedding_dimension: int
    embedding_device: str
    embedding_batch_size: int
    embedding_max_length: int
    retrieval_mode: str
    top_k: int
    neighbor_window: int
    neighbor_expand_top_n: int
    context_max_chars: int
    chunk_analysis_batch_size: int
    max_chunk_chars: int
    max_upload_size_mb: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Settings":
        minio = config["minio"]
        qdrant = config["qdrant"]
        deepseek = config["deepseek"]
        embedding = config["embedding"]
        knowledge = config["knowledge"]
        return cls(
            minio_endpoint=str(_env("MINIO_ENDPOINT", minio["endpoint"])),
            minio_access_key=str(_env("MINIO_ACCESS_KEY", minio["access_key"])),
            minio_secret_key=str(_env("MINIO_SECRET_KEY", minio["secret_key"])),
            minio_bucket=str(_env("MINIO_BUCKET", minio["bucket"])),
            minio_secure=_env_bool("MINIO_SECURE", bool(minio.get("secure", False))),
            qdrant_url=str(_env("QDRANT_URL", qdrant["url"])),
            qdrant_api_key=str(_env("QDRANT_API_KEY", qdrant.get("api_key", ""))),
            qdrant_collection=str(_env("QDRANT_COLLECTION", qdrant["collection"])),
            deepseek_api_key=str(_env("DEEPSEEK_API_KEY", deepseek.get("api_key", ""))),
            deepseek_base_url=str(_env("DEEPSEEK_BASE_URL", deepseek["base_url"])),
            deepseek_model=str(_env("DEEPSEEK_MODEL", deepseek["model"])),
            deepseek_timeout=float(_env("DEEPSEEK_TIMEOUT", deepseek.get("timeout", 60))),
            deepseek_retry=int(_env("DEEPSEEK_RETRY", deepseek.get("retry", 3))),
            deepseek_max_input_chars=int(
                _env("DEEPSEEK_MAX_INPUT_CHARS", deepseek.get("max_input_chars", 80_000))
            ),
            deepseek_max_output_tokens=int(
                _env("DEEPSEEK_MAX_OUTPUT_TOKENS", deepseek.get("max_output_tokens", 8192))
            ),
            embedding_model=str(_env("EMBEDDING_MODEL", embedding["model"])),
            embedding_dimension=int(_env("EMBEDDING_DIMENSION", embedding["dimension"])),
            embedding_device=str(_env("EMBEDDING_DEVICE", embedding.get("device", "cpu"))),
            embedding_batch_size=int(_env("EMBEDDING_BATCH_SIZE", embedding.get("batch_size", 4))),
            embedding_max_length=int(
                _env("EMBEDDING_MAX_LENGTH", embedding.get("max_length", 8192))
            ),
            retrieval_mode=str(_env("RETRIEVAL_MODE", knowledge.get("mode", "hybrid"))),
            top_k=int(_env("RETRIEVAL_TOP_K", knowledge.get("top_k", 8))),
            neighbor_window=int(
                _env("RETRIEVAL_NEIGHBOR_WINDOW", knowledge.get("neighbor_window", 1))
            ),
            neighbor_expand_top_n=int(
                _env(
                    "RETRIEVAL_NEIGHBOR_EXPAND_TOP_N",
                    knowledge.get("neighbor_expand_top_n", 3),
                )
            ),
            context_max_chars=int(
                _env("KNOWLEDGE_CONTEXT_MAX_CHARS", knowledge.get("context_max_chars", 100))
            ),
            chunk_analysis_batch_size=int(
                _env("KNOWLEDGE_CHUNK_ANALYSIS_BATCH_SIZE",
                     knowledge.get("chunk_analysis_batch_size", 6))
            ),
            max_chunk_chars=int(
                _env("KNOWLEDGE_MAX_CHUNK_CHARS", knowledge.get("max_chunk_chars", 6000))
            ),
            max_upload_size_mb=int(
                _env("KNOWLEDGE_MAX_UPLOAD_SIZE_MB", knowledge.get("max_upload_size_mb", 50))
            ),
        )


CONFIG = load_config()
SETTINGS = Settings.from_config(CONFIG)
