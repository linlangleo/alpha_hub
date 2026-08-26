import logging
import os
import secrets
import time

import redis

from app.core.config import CONFIG


logger = logging.getLogger(__name__)
REDIS_CONFIG = CONFIG["redis"]
SESSION_PREFIX = "alpha_hub:session:"

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", REDIS_CONFIG["host"]),
    port=int(os.getenv("REDIS_PORT", REDIS_CONFIG["port"])),
    password=os.getenv("REDIS_PASSWORD", REDIS_CONFIG.get("password") or "") or None,
    db=int(os.getenv("REDIS_DB", REDIS_CONFIG.get("db", 0))),
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)


def init_redis(max_retries: int = 5) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            redis_client.ping()
            return
        except redis.RedisError as exc:
            last_error = exc
            logger.warning("Redis 连接失败 (%s/%s): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(1)
    raise RuntimeError("无法连接 Redis") from last_error


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.setex(
        f"{SESSION_PREFIX}{token}",
        REDIS_CONFIG.get("session_expire_seconds", 28_800),
        str(user_id),
    )
    return token


def get_session_user_id(token: str) -> int | None:
    value = redis_client.get(f"{SESSION_PREFIX}{token}")
    return int(value) if value is not None else None


def delete_session(token: str) -> None:
    redis_client.delete(f"{SESSION_PREFIX}{token}")


def check_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False
