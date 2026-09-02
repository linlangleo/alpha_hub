from typing import Any

from psycopg.types.json import Jsonb

from app.core.database import get_connection
from app.core.snowflake import generate_id


def create_document(document_id: int, name: str, original_filename: str,
                    source_type: str, source_name: str, category: str,
                    strategy_id: int | None, file_type: str, metadata: dict[str, Any],
                    user_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        return connection.execute(
            '''
            INSERT INTO knowledge_document (
                id, knowledge_base_id, strategy_id, name, file_type, original_filename, source_type,
                source_name, category, status, metadata, create_by, update_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'UPLOADED', %s, %s, %s)
            RETURNING *
            ''',
            (document_id, user_id, strategy_id, name, file_type, original_filename, source_type,
             source_name, category, Jsonb(metadata), user_id, user_id),
        ).fetchone()


def update_document_storage(document_id: int, bucket: str, object_key: str,
                            metadata: dict[str, Any], user_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            '''
            UPDATE knowledge_document
            SET minio_bucket = %s, minio_object_key = %s, metadata = metadata || %s,
                update_time = CURRENT_TIMESTAMP, update_by = %s
            WHERE id = %s AND create_by = %s
            ''',
            (bucket, object_key, Jsonb(metadata), user_id, document_id, user_id),
        )


def update_document_status(document_id: int, status: str, user_id: int,
                           metadata: dict[str, Any] | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            '''
            UPDATE knowledge_document
            SET status = %s, metadata = metadata || %s,
                update_time = CURRENT_TIMESTAMP, update_by = %s
            WHERE id = %s AND create_by = %s
            ''',
            (status, Jsonb(metadata or {}), user_id, document_id, user_id),
        )


def get_document(document_id: int, user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        return connection.execute(
            '''
            SELECT document.*, strategy.name AS strategy_name, strategy.code AS strategy_code,
                   COUNT(chunk.id) AS chunk_count,
                   COUNT(chunk.id) FILTER (WHERE chunk.analysis_status = 'reviewed') AS reviewed_count
            FROM knowledge_document AS document
            LEFT JOIN strategy ON strategy.id = document.strategy_id
            LEFT JOIN knowledge_chunk AS chunk ON chunk.document_id = document.id
            WHERE document.id = %s AND document.create_by = %s
            GROUP BY document.id, strategy.id
            ''',
            (document_id, user_id),
        ).fetchone()


def find_document(document_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, create_by, status, file_type, minio_bucket, minio_object_key, metadata
            FROM knowledge_document
            WHERE id = %s
            """,
            (document_id,),
        ).fetchone()


def claim_failed_document(document_id: int, user_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            UPDATE knowledge_document
            SET status = 'PROCESSING',
                metadata = metadata || %s,
                update_time = CURRENT_TIMESTAMP,
                update_by = %s
            WHERE id = %s AND create_by = %s AND status = 'FAILED'
            RETURNING id
            """,
            (
                Jsonb(
                    {
                        "processing_stage": "REPROCESS_QUEUED",
                        "progress": 0,
                        "stage_label": "等待重新处理",
                        "error_stage": None,
                        "error_message": None,
                    }
                ),
                user_id,
                document_id,
                user_id,
            ),
        ).fetchone()
    return row is not None


def delete_document(document_id: int, user_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            DELETE FROM knowledge_document
            WHERE id = %s AND create_by = %s
            RETURNING id
            """,
            (document_id, user_id),
        ).fetchone()
    return row is not None


def list_documents(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return connection.execute(
            '''
            SELECT document.*, strategy.name AS strategy_name, strategy.code AS strategy_code,
                   COUNT(chunk.id) AS chunk_count,
                   COUNT(chunk.id) FILTER (WHERE chunk.analysis_status = 'reviewed') AS reviewed_count
            FROM knowledge_document AS document
            LEFT JOIN strategy ON strategy.id = document.strategy_id
            LEFT JOIN knowledge_chunk AS chunk ON chunk.document_id = document.id
            WHERE document.create_by = %s
            GROUP BY document.id, strategy.id
            ORDER BY document.create_time DESC, document.id DESC LIMIT %s
            ''',
            (user_id, limit),
        ).fetchall()


CHUNK_SELECT = '''
    SELECT chunk.*, document.name AS document_name, document.original_filename,
           document.source_type, document.source_name, document.minio_bucket,
           document.minio_object_key, document.metadata AS document_metadata,
           strategy.name AS strategy_name, strategy.code AS strategy_code,
           COALESCE(jsonb_agg(DISTINCT tag.name) FILTER (WHERE tag.id IS NOT NULL),
                    '[]'::jsonb) AS tags
    FROM knowledge_chunk AS chunk
    JOIN knowledge_document AS document ON document.id = chunk.document_id
    LEFT JOIN strategy ON strategy.id = chunk.strategy_id
    LEFT JOIN chunk_tag ON chunk_tag.chunk_id = chunk.id
    LEFT JOIN knowledge_tag AS tag ON tag.id = chunk_tag.tag_id
'''


def list_document_chunks(document_id: int, user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return connection.execute(
            CHUNK_SELECT + '''
            WHERE chunk.document_id = %s AND document.create_by = %s
            GROUP BY chunk.id, document.id, strategy.id
            ORDER BY chunk.chunk_index
            ''',
            (document_id, user_id),
        ).fetchall()


def get_chunk(chunk_id: int, user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        return connection.execute(
            CHUNK_SELECT + '''
            WHERE chunk.id = %s AND document.create_by = %s
            GROUP BY chunk.id, document.id, strategy.id
            ''',
            (chunk_id, user_id),
        ).fetchone()


def list_tag_names(user_id: int) -> list[str]:
    return [str(item["name"]) for item in list_tags(user_id)]


def save_analysis(document_id: int, user_id: int, summary: str, category: str,
                  strategy_id: int | None, document_metadata: dict[str, Any],
                  chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    with get_connection() as connection:
        connection.execute(
            '''
            UPDATE knowledge_document
            SET summary = %s, category = %s, strategy_id = %s, metadata = metadata || %s,
                update_time = CURRENT_TIMESTAMP, update_by = %s
            WHERE id = %s AND create_by = %s
            ''',
            (summary, category, strategy_id, Jsonb(document_metadata), user_id,
             document_id, user_id),
        )
        connection.execute("DELETE FROM knowledge_chunk WHERE document_id = %s", (document_id,))
        for item in chunks:
            chunk_id = generate_id()
            row = connection.execute(
                '''
                INSERT INTO knowledge_chunk (
                    id, knowledge_base_id, document_id, strategy_id, chunk_type, title, content, context,
                    summary, chunk_index, image_keys, metadata, analysis_status,
                    retrieval_status, status, create_by, update_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          'draft', 'active', 'pending', %s, %s)
                RETURNING *
                ''',
                (chunk_id, user_id, document_id, item.get("strategy_id"), item["chunk_type"],
                 item["title"], item["content"], item.get("context"), item.get("summary"),
                 item["chunk_index"], Jsonb(item.get("image_keys", [])),
                 Jsonb(item.get("metadata", {})), user_id, user_id),
            ).fetchone()
            _replace_tags(connection, chunk_id, item.get("tags", []), user_id)
            row["tags"] = item.get("tags", [])
            saved.append(row)
    return saved


def set_chunks_status(chunk_ids: list[int], status: str, user_id: int,
                      qdrant_point_ids: bool = False) -> None:
    if not chunk_ids:
        return
    with get_connection() as connection:
        for chunk_id in chunk_ids:
            connection.execute(
                '''
                UPDATE knowledge_chunk SET status = %s,
                    qdrant_point_id = CASE WHEN %s THEN %s ELSE qdrant_point_id END,
                    update_time = CURRENT_TIMESTAMP, update_by = %s WHERE id = %s
                ''',
                (status, qdrant_point_ids, str(chunk_id), user_id, chunk_id),
            )


def update_chunk_fields(chunk_id: int, user_id: int, values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"content", "context", "summary", "title", "chunk_type", "strategy_id",
               "analysis_status", "retrieval_status", "status", "qdrant_point_id"}
    invalid = set(values) - allowed
    if invalid or not values:
        raise ValueError(f"不允许更新字段: {sorted(invalid)}")
    assignments = [f"{field} = %s" for field in values]
    parameters = list(values.values()) + [user_id, chunk_id, user_id]
    with get_connection() as connection:
        row = connection.execute(
            f'''UPDATE knowledge_chunk SET {', '.join(assignments)},
                update_time = CURRENT_TIMESTAMP, update_by = %s
                WHERE id = %s AND document_id IN (
                    SELECT id FROM knowledge_document WHERE create_by = %s
                ) RETURNING *''',
            parameters,
        ).fetchone()
    if row is None:
        raise LookupError("知识 Chunk 不存在")
    return row


def replace_chunk_tags(chunk_id: int, tag_names: list[str], user_id: int) -> None:
    with get_connection() as connection:
        owned = connection.execute(
            '''SELECT 1 FROM knowledge_chunk AS chunk JOIN knowledge_document AS document
               ON document.id = chunk.document_id WHERE chunk.id = %s AND document.create_by = %s''',
            (chunk_id, user_id),
        ).fetchone()
        if owned is None:
            raise LookupError("知识 Chunk 不存在")
        connection.execute("DELETE FROM chunk_tag WHERE chunk_id = %s", (chunk_id,))
        _replace_tags(connection, chunk_id, tag_names, user_id)


def _replace_tags(connection: Any, chunk_id: int, tag_names: list[str], user_id: int) -> None:
    seen: set[str] = set()
    for value in tag_names:
        name = str(value).strip()[:100]
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        connection.execute(
            '''INSERT INTO knowledge_tag (id, name, category, create_by)
               VALUES (%s, %s, 'auto', %s) ON CONFLICT (name) DO NOTHING''',
            (generate_id(), name, user_id),
        )
        tag = connection.execute("SELECT id FROM knowledge_tag WHERE name = %s", (name,)).fetchone()
        connection.execute(
            "INSERT INTO chunk_tag (chunk_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (chunk_id, tag["id"]),
        )


def get_chunks_by_ids(chunk_ids: list[int], user_id: int) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []
    with get_connection() as connection:
        return connection.execute(
            CHUNK_SELECT + '''
            WHERE chunk.id = ANY(%s) AND document.create_by = %s
              AND chunk.retrieval_status = 'active'
            GROUP BY chunk.id, document.id, strategy.id
            ''',
            (chunk_ids, user_id),
        ).fetchall()


def get_neighbor_chunks(anchors: list[tuple[int, int]], window: int,
                        user_id: int) -> list[dict[str, Any]]:
    if not anchors or window <= 0:
        return []
    clauses: list[str] = []
    parameters: list[Any] = []
    for document_id, chunk_index in anchors:
        clauses.append("(chunk.document_id = %s AND chunk.chunk_index BETWEEN %s AND %s)")
        parameters.extend([document_id, max(0, chunk_index - window), chunk_index + window])
    parameters.append(user_id)
    with get_connection() as connection:
        return connection.execute(
            CHUNK_SELECT + f'''
            WHERE ({' OR '.join(clauses)}) AND document.create_by = %s
              AND chunk.retrieval_status = 'active'
            GROUP BY chunk.id, document.id, strategy.id
            ORDER BY chunk.document_id, chunk.chunk_index
            ''',
            parameters,
        ).fetchall()


def list_tags(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return connection.execute(
            '''
            SELECT tag.*, COUNT(DISTINCT chunk_tag.chunk_id) AS chunk_count
            FROM knowledge_tag AS tag
            LEFT JOIN chunk_tag ON chunk_tag.tag_id = tag.id
            LEFT JOIN knowledge_chunk AS chunk ON chunk.id = chunk_tag.chunk_id
            LEFT JOIN knowledge_document AS document ON document.id = chunk.document_id
            WHERE tag.create_by = %s OR document.create_by = %s
            GROUP BY tag.id ORDER BY chunk_count DESC, tag.name
            ''',
            (user_id, user_id),
        ).fetchall()


def dashboard_data(user_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        counts = connection.execute(
            '''SELECT
                (SELECT COUNT(*) FROM knowledge_document WHERE create_by = %s) AS document_count,
                (SELECT COUNT(*) FROM knowledge_chunk c JOIN knowledge_document d ON d.id=c.document_id
                 WHERE d.create_by = %s) AS chunk_count,
                (SELECT COUNT(*) FROM strategy WHERE status = 'active') AS strategy_count,
                (SELECT COUNT(DISTINCT t.id) FROM knowledge_tag t LEFT JOIN chunk_tag ct ON ct.tag_id=t.id
                 LEFT JOIN knowledge_chunk c ON c.id=ct.chunk_id LEFT JOIN knowledge_document d ON d.id=c.document_id
                 WHERE t.create_by = %s OR d.create_by = %s) AS tag_count,
                (SELECT COUNT(*) FROM knowledge_chunk c JOIN knowledge_document d ON d.id=c.document_id
                 WHERE d.create_by = %s AND c.analysis_status='draft') AS draft_count,
                (SELECT COUNT(*) FROM knowledge_chunk c JOIN knowledge_document d ON d.id=c.document_id
                 WHERE d.create_by = %s AND c.analysis_status='reviewed') AS reviewed_count
            ''',
            (user_id, user_id, user_id, user_id, user_id, user_id),
        ).fetchone()
        recent = connection.execute(
            '''SELECT id, name, status, metadata, create_time FROM knowledge_document
               WHERE create_by = %s ORDER BY create_time DESC LIMIT 8''', (user_id,)
        ).fetchall()
        failed = connection.execute(
            '''SELECT id, name, status, metadata, update_time FROM knowledge_document
               WHERE create_by = %s AND status = 'FAILED' ORDER BY update_time DESC LIMIT 8''',
            (user_id,),
        ).fetchall()
    return {"counts": counts, "recent": recent, "failed": failed}
