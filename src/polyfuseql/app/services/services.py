# src/polyfuseql/app/services/services.py
"""
Service layer to abstract business logic from API endpoints.
Uses per-user connection manager for isolation.
"""
from polyfuseql.app.services.connection_manager import connection_manager
from typing import Any, Dict, List


def _normalize_result(result: Any) -> List[Dict[str, Any]]:
    """
    Normalizes a strategy result into the List[Dict] shape required by
    QueryResponse.

    SELECT strategies already return a list of dicts. Write strategies
    (INSERT/UPDATE/DELETE) return a single dict (e.g. {"updated_count": 1})
    or a scalar. Returning a bare dict/scalar makes FastAPI's response_model
    validation fail *after* the write already succeeded, surfacing a spurious
    HTTP 500 to the frontend. Wrapping keeps the operation metadata while
    satisfying the schema.
    """
    if result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    # Scalars such as an affected-row count
    return [{"affected": result}]


async def execute_query(engine: str, sql: str, user_id: str = "anonymous") -> List[Any]:
    """
    Executes a query on the specified database engine using the
    user's dedicated PolyClient instance.

    Args:
        engine: The name of the database engine (e.g., 'postgres').
        sql: The SQL query to execute.
        user_id: The user ID from JWT for session isolation.

    Returns:
        The result of the query, normalized to a List[Dict].
    """
    client = connection_manager.get_client_for_user(user_id)
    result = await client.execute(sql, engine=engine, use_catalogue=False)
    return _normalize_result(result)
