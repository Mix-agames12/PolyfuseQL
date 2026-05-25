# src/polyfuseql/app/api/auth.py
"""
API router for authentication and user management (RBAC).
"""
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends, status

from polyfuseql.app.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserUpdate,
    UserResponse,
)
from polyfuseql.app.services import auth_service
from polyfuseql.app.core.auth_middleware import (
    get_current_user,
    require_admin,
)

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate a user and return a JWT token."""
    user = auth_service.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = auth_service.create_access_token(user)
    return LoginResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
        allowed_engines=user["allowed_engines"],
    )


@router.put("/me/password")
async def change_own_password(
    request: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Allow any authenticated user to change their own password."""
    new_password = request.get("password")
    if not new_password or len(new_password) < 4:
        raise HTTPException(400, "La contraseña debe tener al menos 4 caracteres")

    user_id = int(current_user["sub"])
    result = auth_service.update_user(user_id=user_id, password=new_password)
    if not result:
        raise HTTPException(404, "Usuario no encontrado")
    return {"message": "Contraseña actualizada exitosamente"}


@router.get("/me")
async def get_current_user_info(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get current authenticated user info."""
    return {
        "id": int(current_user["sub"]),
        "username": current_user["username"],
        "role": current_user["role"],
        "allowed_engines": current_user["allowed_engines"],
    }


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """List all users (admin only)."""
    return auth_service.get_all_users()


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    request: UserCreate,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Create a new user (admin only)."""
    try:
        user = auth_service.create_user(
            username=request.username,
            password=request.password,
            role=request.role,
            allowed_engines=request.allowed_engines,
        )
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UserUpdate,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Update a user (admin only). Admin can set name, password, and permissions."""
    try:
        user = auth_service.update_user(
            user_id=user_id,
            username=request.username,
            password=request.password,
            role=request.role,
            allowed_engines=request.allowed_engines,
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Delete a user (admin only)."""
    # Prevent admin from deleting themselves
    if str(user_id) == admin.get("sub"):
        raise HTTPException(
            status_code=400, detail="Cannot delete your own account"
        )

    deleted = auth_service.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
