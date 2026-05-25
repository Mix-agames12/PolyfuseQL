# src/polyfuseql/app/services/services.py
"""
Service layer to abstract business logic from API endpoints.
Uses per-user connection manager for isolation.
"""
from polyfuseql.app.services.connection_manager import connection_manager
from typing import Any, List


async def execute_query(engine: str, sql: str, user_id: str = "anonymous") -> List[Any]:
    """
    Executes a query on the specified database engine using the
    user's dedicated PolyClient instance.

    Args:
        engine: The name of the database engine (e.g., 'postgres').
        sql: The SQL query to execute.
        user_id: The user ID from JWT for session isolation.

    Returns:
        The result of the query.
    """
    client = connection_manager.get_client_for_user(user_id)
    result = await client.execute(sql, engine=engine, use_catalogue=False)
    return result
