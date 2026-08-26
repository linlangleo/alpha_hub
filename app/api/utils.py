from typing import Any


def serialize_ids(value: Any, key: str = "") -> Any:
    """Keep Snowflake IDs exact when consumed by JavaScript."""
    if isinstance(value, dict):
        return {name: serialize_ids(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [serialize_ids(item, key) for item in value]
    if isinstance(value, int) and (key == "id" or key.endswith("_id")):
        return str(value)
    return value
