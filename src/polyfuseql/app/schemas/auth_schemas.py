# src/polyfuseql/app/schemas/auth_schemas.py
"""
Pydantic schemas for authentication and user management.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class LoginRequest(BaseModel):
    """Schema for login requests."""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4)


class LoginResponse(BaseModel):
    """Schema for login responses."""
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    allowed_engines: List[str]


class UserCreate(BaseModel):
    """Schema for creating a new user (admin only)."""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4)
    role: str = Field(default="user", pattern="^(admin|user)$")
    allowed_engines: List[str] = Field(
        default_factory=lambda: ["postgres", "redis", "cassandra", "neo4j", "mongodb"]
    )


class UserUpdate(BaseModel):
    """Schema for updating a user (admin only)."""
    username: Optional[str] = Field(None, min_length=2, max_length=50)
    password: Optional[str] = Field(None, min_length=4)
    role: Optional[str] = Field(None, pattern="^(admin|user)$")
    allowed_engines: Optional[List[str]] = None


class UserResponse(BaseModel):
    """Schema for user responses (no password)."""
    id: int
    username: str
    role: str
    allowed_engines: List[str]


class ConnectionCredentials(BaseModel):
    """Schema for database connection credentials."""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    use_env: bool = False


class ConnectionRequest(BaseModel):
    """Schema for connecting to a database."""
    engine: str
    credentials: ConnectionCredentials


class ConnectionStatusResponse(BaseModel):
    """Schema for connection status."""
    engine: str
    connected: bool
    details: Optional[str] = None
