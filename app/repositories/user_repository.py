from typing import Any

from app.core.database import get_connection


def authenticate_user(username: str, password: str) -> Any:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, username
            FROM users
            WHERE username = %s
              AND password = crypt(%s, password)
            """,
            (username, password),
        ).fetchone()
