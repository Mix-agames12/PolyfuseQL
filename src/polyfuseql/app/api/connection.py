# src/polyfuseql/app/api/connection.py
"""
API router for database connection management.
Uses per-user session-based connections via ConnectionManager.
"""
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from polyfuseql.app.schemas.auth_schemas import ConnectionCredentials
from polyfuseql.app.services.connection_manager import connection_manager
from polyfuseql.app.core.auth_middleware import get_current_user

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

VALID_ENGINES = ["postgres", "redis", "neo4j", "cassandra", "mongodb"]


def _get_user_id(current_user: Dict[str, Any]) -> str:
    """Extract user_id from JWT payload."""
    return str(current_user.get("sub", "anonymous"))


@router.post("/{engine}/connect")
async def connect_to_engine(
    engine: str,
    credentials: ConnectionCredentials,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Connect to a database engine with provided or env credentials."""
    if engine not in VALID_ENGINES:
        raise HTTPException(400, f"Invalid engine. Must be one of: {VALID_ENGINES}")

    user_id = _get_user_id(current_user)

    try:
        client = connection_manager.get_client_for_user(user_id)

        if not credentials.use_env:
            _apply_credentials(engine, credentials)

        conn = await client.get_connector(engine)
        await conn.ping()

        return {"engine": engine, "connected": True,
                "message": f"Successfully connected to {engine}"}
    except Exception as e:
        logger.error(f"Connection to {engine} failed for user {user_id}: {e}")
        raise HTTPException(500, f"Connection failed: {str(e)}")


@router.post("/{engine}/disconnect")
async def disconnect_from_engine(
    engine: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Disconnect from a database engine."""
    user_id = _get_user_id(current_user)

    try:
        client = connection_manager.get_client_for_user(user_id)
        conn = client._connections.get(engine)
        if conn:
            await conn.disconnect()
            del client._connections[engine]

        return {"engine": engine, "connected": False,
                "message": f"Disconnected from {engine}"}
    except Exception as e:
        raise HTTPException(500, f"Disconnect failed: {str(e)}")


@router.get("/status")
async def get_connection_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get connection status for all engines for the current user."""
    user_id = _get_user_id(current_user)
    statuses = connection_manager.get_connection_status(user_id)
    return {"connections": statuses}


def _apply_credentials(engine: str, creds: ConnectionCredentials):
    """Apply credentials to the global settings (runtime override)."""
    from polyfuseql.config import settings

    if engine == "postgres":
        settings.postgres.host = creds.host
        settings.postgres.port = creds.port
        settings.postgres.user = creds.username or "postgres"
        settings.postgres.password = creds.password or ""
        settings.postgres.db = creds.database or "postgres"
    elif engine == "redis":
        settings.redis.host = creds.host
        settings.redis.port = creds.port
        settings.redis.password = creds.password or ""
    elif engine == "neo4j":
        settings.neo4j.host = creds.host
        settings.neo4j.port = creds.port
        settings.neo4j.user = creds.username or "neo4j"
        settings.neo4j.password = creds.password or ""
    elif engine == "cassandra":
        settings.cassandra.host = creds.host
        settings.cassandra.port = creds.port
        settings.cassandra.user = creds.username
        settings.cassandra.password = creds.password
        if creds.database:
            settings.cassandra.keyspace = creds.database
    elif engine == "mongodb":
        settings.mongodb.host = creds.host
        settings.mongodb.port = creds.port
        settings.mongodb.user = creds.username or "root"
        settings.mongodb.password = creds.password or ""
        if creds.database:
            settings.mongodb.db = creds.database
