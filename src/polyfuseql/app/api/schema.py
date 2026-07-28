# src/polyfuseql/app/api/schema.py
"""
API router for database schema introspection.
Uses per-user connections when available, falls back to global client.
"""
import logging
from typing import Dict, List, Any
from fastapi import APIRouter, HTTPException, Depends
from polyfuseql.app.services.connection_manager import connection_manager
from polyfuseql.app.core.auth_middleware import get_current_user

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


def _get_user_id(current_user: Dict[str, Any]) -> str:
    return str(current_user.get("sub", "anonymous"))


@router.get("/postgres")
async def get_postgres_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Introspect PostgreSQL: database → tables → columns."""
    try:
        user_id = _get_user_id(current_user)
        client = connection_manager.get_client_for_user(user_id)
        conn = await client.get_connector("postgres")
        sql = (
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "ORDER BY table_name, ordinal_position"
        )
        rows = await conn.query(sql)
        tables: Dict[str, List[Dict]] = {}
        for row in rows:
            tname = row.get("tableName") or row.get("table_name")
            cname = row.get("columnName") or row.get("column_name")
            dtype = row.get("dataType") or row.get("data_type")
            nullable = row.get("isNullable") or row.get("is_nullable")
            if tname not in tables:
                tables[tname] = []
            tables[tname].append({"column": cname, "type": dtype, "nullable": nullable == "YES"})
        from polyfuseql.config import settings
        return {"engine": "postgres", "database": settings.postgres.db,
                "tables": [{"name": n, "columns": c} for n, c in tables.items()]}
    except Exception as e:
        logger.error(f"Failed to get postgres schema: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener esquema de PostgreSQL: {str(e)}")


@router.get("/mongodb")
async def get_mongodb_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Introspect MongoDB: database → collections → fields."""
    try:
        user_id = _get_user_id(current_user)
        client = connection_manager.get_client_for_user(user_id)
        conn = await client.get_connector("mongodb")
        db = conn._db
        if db is None:
            return {"engine": "mongodb", "database": "", "collections": []}

        coll_names = await db.list_collection_names()
        # Fallback to 'tpch' database if current db is empty but 'tpch' has collections
        if not coll_names and db.name != "tpch":
            client_mongo = conn._client
            if client_mongo:
                tpch_db = client_mongo["tpch"]
                tpch_colls = await tpch_db.list_collection_names()
                if tpch_colls:
                    db = tpch_db
                    coll_names = tpch_colls

        collections_info = []
        for coll_name in coll_names:
            coll = db[coll_name]
            sample = await coll.find_one()
            fields = []
            if sample:
                for key, val in sample.items():
                    fields.append({"field": key, "type": type(val).__name__})
            count = await coll.estimated_document_count()
            collections_info.append({"name": coll_name, "fields": fields,
                                     "count": count})
        return {"engine": "mongodb", "database": db.name,
                "collections": collections_info}
    except Exception as e:
        logger.error(f"Failed to get mongodb schema: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener esquema de MongoDB: {str(e)}")


@router.get("/redis")
async def get_redis_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Introspect Redis: namespaces → types → sample keys."""
    try:
        user_id = _get_user_id(current_user)
        client = connection_manager.get_client_for_user(user_id)

        # Check if Redis is connected
        if "redis" not in client._connections:
            return {"engine": "redis", "namespaces": [],
                    "message": "Redis no está conectado. Conecta primero el motor."}

        conn = await client.get_connector("redis")
        driver = conn._get_client()

        namespaces: Dict[str, Dict] = {}
        cursor = 0
        while True:
            cursor, keys = await driver.scan(cursor, count=200)
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode("utf-8")
                parts = key_str.split(":", 1)
                ns = parts[0] if len(parts) > 1 else "_default"
                if ns not in namespaces:
                    namespaces[ns] = {"keys": [], "types": set()}
                key_type = await driver.type(key)
                type_str = key_type if isinstance(key_type, str) else key_type.decode("utf-8")
                namespaces[ns]["types"].add(type_str)
                if len(namespaces[ns]["keys"]) < 5:
                    key_info = {"key": key_str, "type": type_str}
                    if type_str == "hash":
                        fields = await driver.hkeys(key)
                        key_info["fields"] = [f if isinstance(f, str) else f.decode("utf-8") for f in fields]
                    namespaces[ns]["keys"].append(key_info)
            if cursor == 0:
                break
        return {"engine": "redis", "namespaces": [
            {"name": ns, "types": list(d["types"]), "sample_keys": d["keys"]}
            for ns, d in namespaces.items()]}
    except Exception as e:
        logger.error(f"Failed to get redis schema: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener esquema de Redis: {str(e)}")


@router.get("/neo4j")
async def get_neo4j_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Introspect Neo4j: labels → properties, relationships."""
    try:
        user_id = _get_user_id(current_user)
        client = connection_manager.get_client_for_user(user_id)
        conn = await client.get_connector("neo4j")
        driver = conn._get_driver()
        labels_data, relationships_data = [], []
        async with driver.session() as session:
            result = await session.run("CALL db.labels()")
            labels = [rec["label"] async for rec in result]
            for label in labels:
                prop_result = await session.run(
                    f"MATCH (n:`{label}`) WITH keys(n) AS props LIMIT 1 "
                    "UNWIND props AS prop RETURN DISTINCT prop")
                properties = [rec["prop"] async for rec in prop_result]
                count_result = await session.run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt")
                count_rec = await count_result.single()
                labels_data.append({"label": label, "properties": properties,
                                    "count": count_rec["cnt"] if count_rec else 0})
            rel_result = await session.run("CALL db.relationshipTypes()")
            rel_types = [rec["relationshipType"] async for rec in rel_result]
            for rel_type in rel_types:
                rel_prop_result = await session.run(
                    f"MATCH ()-[r:`{rel_type}`]->() WITH keys(r) AS props LIMIT 1 "
                    "UNWIND props AS prop RETURN DISTINCT prop")
                rel_props = [rec["prop"] async for rec in rel_prop_result]
                relationships_data.append({"type": rel_type, "properties": rel_props})
        return {"engine": "neo4j", "graph": "default",
                "labels": labels_data, "relationships": relationships_data}
    except Exception as e:
        logger.error(f"Failed to get neo4j schema: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener esquema de Neo4j: {str(e)}")


@router.get("/cassandra")
async def get_cassandra_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Introspect Cassandra: keyspace → tables → columns."""
    try:
        from polyfuseql.config import settings
        user_id = _get_user_id(current_user)
        client = connection_manager.get_client_for_user(user_id)
        conn = await client.get_connector("cassandra")
        cluster = conn._cluster
        metadata = cluster.metadata
        keyspace_name = settings.cassandra.keyspace
        ks_meta = metadata.keyspaces.get(keyspace_name)
        if not ks_meta:
            return {"engine": "cassandra", "keyspace": keyspace_name, "tables": []}
        tables = []
        for table_name, table_meta in ks_meta.tables.items():
            columns = []
            for col_name, col_meta in table_meta.columns.items():
                columns.append({
                    "column": col_name, "type": str(col_meta.cql_type),
                    "is_partition_key": col_name in [c.name for c in table_meta.partition_key],
                    "is_clustering_key": col_name in [c.name for c in table_meta.clustering_key]})
            tables.append({"name": table_name, "columns": columns})
        return {"engine": "cassandra", "keyspace": keyspace_name, "tables": tables}
    except Exception as e:
        logger.error(f"Failed to get cassandra schema: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener esquema de Cassandra: {str(e)}")
