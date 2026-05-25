# src/polyfuseql/app/services/connection_manager.py
"""
Per-user session-based connection manager.
Each user (identified by JWT user_id) gets their own PolyClient instance,
ensuring isolation between concurrent sessions.
"""
import logging
from typing import Dict, Optional, Any

from polyfuseql.client.PolyClient import PolyClient

logger = logging.getLogger("uvicorn.error")


class ConnectionManager:
    """
    Manages per-user PolyClient instances.
    Users are isolated — each user gets their own set of DB connections.
    """

    def __init__(self):
        # Map: user_id (str) -> PolyClient
        self._user_clients: Dict[str, PolyClient] = {}
        # Fallback global client for unauthenticated schema queries
        self._global_client: Optional[PolyClient] = None

    def get_client_for_user(self, user_id: str) -> PolyClient:
        """Get or create a PolyClient for a specific user."""
        if user_id not in self._user_clients:
            logger.info(f"Creating new PolyClient for user '{user_id}'")
            self._user_clients[user_id] = PolyClient()
        return self._user_clients[user_id]

    def get_global_client(self) -> PolyClient:
        """Get or create the global fallback PolyClient (for schema, etc.)."""
        if self._global_client is None:
            self._global_client = PolyClient()
        return self._global_client

    async def remove_user(self, user_id: str) -> None:
        """Remove and close all connections for a user."""
        client = self._user_clients.pop(user_id, None)
        if client:
            await client.close_all_connections()
            logger.info(f"Closed all connections for user '{user_id}'")

    def get_connection_status(self, user_id: str):
        """Get connection status for a user's engines."""
        engines = ["postgres", "redis", "neo4j", "cassandra", "mongodb"]
        client = self._user_clients.get(user_id)
        statuses = []
        for eng in engines:
            connected = False
            if client:
                connected = eng in client._connections
            statuses.append({
                "engine": eng,
                "connected": connected,
                "details": "",
            })
        return statuses


# Singleton instance
connection_manager = ConnectionManager()
