# src/polyfuseql/app/api/mongodb.py
"""
API router for MongoDB operations.
"""
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.schemas.schemas import QueryRequest, QueryResponse
from polyfuseql.app.services import services
from polyfuseql.app.core.auth_middleware import get_current_user

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def mongodb_query(
    request: QueryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Executes a SQL query on the MongoDB database.
    """
    try:
        user_id = str(current_user.get("sub", "anonymous"))
        results = await services.execute_query(
            engine="mongodb", sql=request.sql, user_id=user_id
        )
        return {"result": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
