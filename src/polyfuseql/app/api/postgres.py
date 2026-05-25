# src/polyfuseql/app/api/postgres.py
"""
API router for PostgreSQL operations.
"""
import logging
import traceback
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.schemas.schemas import QueryRequest, QueryResponse
from polyfuseql.app.services import services
from polyfuseql.app.core.auth_middleware import get_current_user

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


@router.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint for the API.
    """
    logger.info("read_root")
    return {"message": "Welcome to the Postgres API!"}


@router.post("/query", response_model=QueryResponse)
async def postgres_query(
    request: QueryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Executes a SQL query on the PostgreSQL database.
    """
    logger.debug("postgres_query")
    try:
        logger.debug("Executing SQL query")
        logger.debug(f"request: {request}")
        user_id = str(current_user.get("sub", "anonymous"))
        results = await services.execute_query(
            engine="postgres", sql=request.sql, user_id=user_id
        )
        return {"result": results}
    except Exception as e:
        print(e)
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
