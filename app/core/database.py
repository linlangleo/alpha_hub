import logging
import os
import time

import psycopg
from psycopg.rows import dict_row

from app.core.config import CONFIG


logger = logging.getLogger(__name__)
DATABASE_CONFIG = CONFIG["database"]


def get_connection(max_retries: int = 3):
    """Create and validate a PostgreSQL connection with bounded retries."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            connection = psycopg.connect(
                host=os.getenv("POSTGRES_HOST", DATABASE_CONFIG["host"]),
                port=int(os.getenv("POSTGRES_PORT", DATABASE_CONFIG["port"])),
                user=os.getenv("POSTGRES_USER", DATABASE_CONFIG["user"]),
                password=os.getenv("POSTGRES_PASSWORD", DATABASE_CONFIG["password"]),
                dbname=os.getenv("POSTGRES_DB", DATABASE_CONFIG["database"]),
                connect_timeout=DATABASE_CONFIG.get("connect_timeout", 5),
                row_factory=dict_row,
            )
            connection.execute("SELECT 1")
            return connection
        except psycopg.OperationalError as exc:
            last_error = exc
            logger.warning("PostgreSQL 连接失败 (%s/%s): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(1)
    raise RuntimeError("无法连接 PostgreSQL") from last_error


def check_database() -> bool:
    try:
        with get_connection(max_retries=1):
            return True
    except RuntimeError:
        return False
