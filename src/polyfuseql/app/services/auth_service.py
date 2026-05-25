# src/polyfuseql/app/services/auth_service.py
"""
Authentication and user management service using SQLite.
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import jwt
from passlib.context import CryptContext

logger = logging.getLogger("uvicorn.error")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT config
JWT_SECRET = os.getenv("JWT_SECRET", "polyfuseql-super-secret-key-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# SQLite database path (inside src to avoid Docker root permission issues)
DB_PATH = Path(__file__).parent.parent.parent.parent / "polyfuseql_users.db"


def _get_db() -> sqlite3.Connection:
    """Get a SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialize the database and create tables if needed."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                allowed_engines TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # Seed default admin if no users exist
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM users")
        row = cursor.fetchone()
        if row["cnt"] == 0:
            _seed_admin(conn)

    finally:
        conn.close()


def _seed_admin(conn: sqlite3.Connection) -> None:
    """Seed the default admin user."""
    hashed = pwd_context.hash("Admin123!")
    engines = json.dumps(["postgres", "redis", "cassandra", "neo4j", "mongodb"])
    conn.execute(
        "INSERT INTO users (username, password_hash, role, allowed_engines) VALUES (?, ?, ?, ?)",
        ("admin", hashed, "admin", engines),
    )
    conn.commit()
    logger.info("Default admin user seeded: admin / Admin123!")


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user and return user dict if valid."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        user = cursor.fetchone()
        if not user:
            return None
        if not pwd_context.verify(password, user["password_hash"]):
            return None
        return _row_to_dict(user)
    finally:
        conn.close()


def create_access_token(user: Dict[str, Any]) -> str:
    """Create a JWT access token."""
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "allowed_engines": json.loads(user["allowed_engines"])
        if isinstance(user["allowed_engines"], str)
        else user["allowed_engines"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_user(
    username: str,
    password: str,
    role: str = "user",
    allowed_engines: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new user."""
    if allowed_engines is None:
        allowed_engines = ["postgres", "redis", "cassandra", "neo4j", "mongodb"]

    hashed = pwd_context.hash(password)
    engines_json = json.dumps(allowed_engines)

    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, role, allowed_engines) VALUES (?, ?, ?, ?)",
            (username, hashed, role, engines_json),
        )
        conn.commit()
        user_id = cursor.lastrowid

        return {
            "id": user_id,
            "username": username,
            "role": role,
            "allowed_engines": allowed_engines,
        }
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' already exists")
    finally:
        conn.close()


def get_all_users() -> List[Dict[str, Any]]:
    """Get all users (without passwords)."""
    conn = _get_db()
    try:
        cursor = conn.execute("SELECT * FROM users ORDER BY id")
        users = []
        for row in cursor.fetchall():
            user = _row_to_dict(row)
            user.pop("password_hash", None)
            users.append(user)
        return users
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get a user by ID."""
    conn = _get_db()
    try:
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        user = _row_to_dict(row)
        user.pop("password_hash", None)
        return user
    finally:
        conn.close()


def update_user(
    user_id: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    role: Optional[str] = None,
    allowed_engines: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Update user fields."""
    conn = _get_db()
    try:
        updates = []
        params = []

        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if password is not None:
            updates.append("password_hash = ?")
            params.append(pwd_context.hash(password))
        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if allowed_engines is not None:
            updates.append("allowed_engines = ?")
            params.append(json.dumps(allowed_engines))

        if not updates:
            return get_user_by_id(user_id)

        updates.append("updated_at = datetime('now')")
        params.append(user_id)

        sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()

        return get_user_by_id(user_id)
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' already exists")
    finally:
        conn.close()


def delete_user(user_id: int) -> bool:
    """Delete a user by ID."""
    conn = _get_db()
    try:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a SQLite row to a dict with parsed JSON fields."""
    d = dict(row)
    if "allowed_engines" in d and isinstance(d["allowed_engines"], str):
        try:
            d["allowed_engines"] = json.loads(d["allowed_engines"])
        except json.JSONDecodeError:
            d["allowed_engines"] = []
    return d
