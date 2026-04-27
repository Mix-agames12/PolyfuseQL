import asyncio
import csv
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import aiofiles
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import _camelize_keys, get_pydantic_model

logger = logging.getLogger(__name__)


class CassandraConnector(Connector):
    """
    Local connector for Cassandra using the cassandra-driver.
    Connects directly to Cassandra without requiring external
    translator/auth/permission microservices.
    Returns data in JSON format with camelCase keys,
    consistent with PostgreSQL and Redis connectors.
    """

    def __init__(
        self,
        catalogue: Optional[Catalogue] = None,
        options: Optional[Dict] = None,
    ) -> None:
        # is_local_implementation=True — handles queries locally
        super().__init__(options=options, catalogue=catalogue,
                         is_local_implementation=True)

        from polyfuseql.config import settings

        self._host = settings.cassandra.host
        self._port = settings.cassandra.port
        self._user = settings.cassandra.user
        self._password = settings.cassandra.password
        self._keyspace = settings.cassandra.keyspace
        self._cluster = None
        self._session = None
        logger.info(
            f"CassandraConnector initialized for "
            f"{self._host}:{self._port}/{self._keyspace}"
        )

    async def connect(self) -> None:
        """Establishes a connection to the Cassandra cluster."""
        if self._session:
            return

        def _connect_sync():
            from cassandra.cluster import Cluster
            from cassandra.auth import PlainTextAuthProvider

            auth_provider = None
            if self._user and self._password:
                auth_provider = PlainTextAuthProvider(
                    username=self._user, password=self._password
                )
            cluster = Cluster(
                [self._host],
                port=self._port,
                auth_provider=auth_provider,
            )
            session = cluster.connect(self._keyspace)
            return cluster, session

        self._cluster, self._session = await asyncio.to_thread(
            _connect_sync
        )
        logger.info("Cassandra connection established.")

    async def disconnect(self) -> None:
        """Closes the Cassandra connection."""
        if self._cluster:
            def _shutdown():
                self._cluster.shutdown()
            await asyncio.to_thread(_shutdown)
            self._cluster = None
            self._session = None
            logger.info("Cassandra connection closed.")

    def _get_session(self):
        """Returns the active Cassandra session."""
        if not self._session:
            raise ConnectionError(
                "CassandraConnector is not connected. Call connect() first."
            )
        return self._session

    async def ping(self) -> bool:
        """Pings the Cassandra cluster."""
        session = self._get_session()
        result = await asyncio.to_thread(
            session.execute, "SELECT release_version FROM system.local"
        )
        return result is not None

    async def count(self, entity: str) -> int:
        """Counts all records for a given entity."""
        session = self._get_session()
        cql = f"SELECT COUNT(*) FROM {entity}"
        result = await asyncio.to_thread(session.execute, cql)
        row = result.one()
        return row.count if row else 0

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:
        """Retrieves a single record by primary key."""
        session = self._get_session()

        # Cast pk_val to proper type for Cassandra
        pk_val = self._cast_pk_value(pk_val)

        cql = f"SELECT * FROM {entity} WHERE {pk_col} = %s"
        result = await asyncio.to_thread(session.execute, cql, [pk_val])
        row = result.one()
        if not row:
            return {}

        raw_data = self._row_to_dict(row)
        return self._validate_and_camelize(entity, raw_data)

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        """Retrieves all records for a given entity."""
        session = self._get_session()
        cql = f"SELECT * FROM {entity}"
        result = await asyncio.to_thread(session.execute, cql)
        rows = result.all()

        processed = []
        for row in rows:
            raw_data = self._row_to_dict(row)
            processed.append(self._validate_and_camelize(entity, raw_data))
        return processed

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        """Inserts a new record."""
        session = self._get_session()
        cols = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())

        cql = f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"
        await asyncio.to_thread(session.execute, cql, values)
        return {"status": "inserted", "table": entity}

    async def update(
        self, entity: str, pk_col: str, pk_val: Any,
        payload: Dict[str, Any]
    ) -> int:
        """Updates a record by primary key."""
        session = self._get_session()
        pk_val = self._cast_pk_value(pk_val)

        set_clause = ", ".join(f"{k} = %s" for k in payload.keys())
        values = list(payload.values()) + [pk_val]

        cql = f"UPDATE {entity} SET {set_clause} WHERE {pk_col} = %s"
        await asyncio.to_thread(session.execute, cql, values)
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        """Deletes a record by primary key."""
        session = self._get_session()
        pk_val = self._cast_pk_value(pk_val)

        cql = f"DELETE FROM {entity} WHERE {pk_col} = %s"
        await asyncio.to_thread(session.execute, cql, [pk_val])
        return 1

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        """Executes a CQL query directly."""
        session = self._get_session()
        if params:
            result = await asyncio.to_thread(
                session.execute, sql, list(params)
            )
        else:
            result = await asyncio.to_thread(session.execute, sql)
        rows = result.all()
        return [_camelize_keys(self._row_to_dict(row)) for row in rows]

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        Cassandra does not support JOINs natively.
        Falls back to application-side join logic.
        """
        raise NotImplementedError(
            "Cassandra does not support JOINs. "
            "Use application-side logic or denormalized tables."
        )

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a GROUP BY query (limited Cassandra support)."""
        # Cassandra has limited GROUP BY support, try to execute directly
        cql = ast.sql()
        return await self.query(cql)

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a simple aggregation query."""
        cql = ast.sql()
        return await self.query(cql)

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """Bulk inserts data from a TPC-H .tbl file."""
        session = self._get_session()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            raise ValueError(f"No schema for table: {table_name}")

        columns = list(schema["columns"].keys())
        col_types = schema["columns"]

        count = 0
        async with aiofiles.open(
            file_path, "r", encoding="utf-8"
        ) as f:
            content = await f.read()
            reader = csv.reader(content.splitlines(), delimiter="|")

            cols_str = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            cql = (
                f"INSERT INTO {table_name} ({cols_str}) "
                f"VALUES ({placeholders})"
            )

            for line in reader:
                if line and line[-1] == "":
                    line.pop()

                if len(line) != len(columns):
                    continue

                values = self._cast_row(line, columns, col_types)
                if values:
                    await asyncio.to_thread(
                        session.execute, cql, values
                    )
                    count += 1

                if count % 2000 == 0 and count > 0:
                    logger.info(f"Loaded {count} rows into {table_name}...")

        logger.info(
            f"Loaded {count} records into '{table_name}'."
        )
        return count

    # ────────────── Helper Methods ────────────── #

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        """Converts a Cassandra Row to a plain dict."""
        if hasattr(row, '_asdict'):
            return dict(row._asdict())
        # Fallback for named tuples or Row objects
        return {col: getattr(row, col) for col in row._fields}

    def _validate_and_camelize(
        self, entity: str, raw_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validates data through the Pydantic model and returns
        camelCase keys, consistent with Postgres/Redis connectors.
        """
        # Convert Cassandra date types to Python date for serialization
        for key, value in raw_data.items():
            if hasattr(value, 'date') and callable(value.date):
                raw_data[key] = value.date()
            elif isinstance(value, date) and not isinstance(value, datetime):
                raw_data[key] = value

        schema = self.catalogue.get_schema(entity)
        if not schema:
            return _camelize_keys(raw_data)

        try:
            dynamic_model = get_pydantic_model(entity, schema)
            # Convert all values to strings for pydantic casting
            str_data = {k: str(v) if v is not None else None
                        for k, v in raw_data.items()}
            validated = dynamic_model(**str_data)
            return _camelize_keys(validated.model_dump())
        except Exception:
            return _camelize_keys(raw_data)

    @staticmethod
    def _cast_pk_value(pk_val: Any) -> Any:
        """Casts the primary key value to a proper Python type."""
        from decimal import Decimal
        if isinstance(pk_val, Decimal):
            if pk_val == int(pk_val):
                return int(pk_val)
            return float(pk_val)
        return pk_val

    @staticmethod
    def _cast_row(
        parts: List[str], columns: List[str],
        col_types: Dict[str, str]
    ) -> Optional[List[Any]]:
        """Casts a raw CSV row to typed values for CQL insertion."""
        try:
            values = []
            for val, col in zip(parts, columns):
                col_type = col_types.get(col, "str")
                val = val.strip()
                if not val:
                    values.append(None)
                elif col_type == "int":
                    values.append(int(val))
                elif col_type == "decimal":
                    values.append(float(val))
                elif col_type == "date":
                    values.append(val)  # Cassandra accepts date strings
                else:
                    values.append(val)
            return values
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping malformed row: {parts}. Error: {e}")
            return None
