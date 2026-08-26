from typing import Any

from app.core.database import get_connection


def list_strategies(active_only: bool = True) -> list[dict[str, Any]]:
    status_filter = "WHERE strategy.status = 'active'" if active_only else ""
    with get_connection() as connection:
        return connection.execute(
            f"""
            SELECT strategy.*, COUNT(chunk.id) AS chunk_count
            FROM strategy
            LEFT JOIN knowledge_chunk AS chunk ON chunk.strategy_id = strategy.id
            {status_filter}
            GROUP BY strategy.id
            ORDER BY strategy.category, strategy.name
            """
        ).fetchall()


def get_strategy(strategy_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM strategy WHERE id = %s AND status = 'active'",
            (strategy_id,),
        ).fetchone()


def get_strategy_by_code(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM strategy WHERE code = %s AND status = 'active'",
            (code,),
        ).fetchone()
