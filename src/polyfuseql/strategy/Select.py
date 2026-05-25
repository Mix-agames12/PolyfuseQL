import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class SelectStrategy(QueryStrategy):
    def _parse_pk_value_from_literal(self, lit_expr: exp.Literal) -> Any:
        """
        [Sonar Refactor S3776] Helper for SelectStrategy:
        Parses a sqlglot Literal expression from a WHERE clause
        into its Python equivalent, reducing complexity.
        """
        if not isinstance(lit_expr, exp.Literal):
            msg = "WHERE clause must compare to a literal value."
            raise NotImplementedError(msg)

        if lit_expr.is_string:
            return lit_expr.this

        val_str = lit_expr.this
        if not val_str:
            return None

        val_lower = val_str.lower()

        # Handle NULL
        if val_lower == "null":
            return None

        # Handle Booleans
        if val_lower == "true":
            return True
        if val_lower == "false":
            return False

        # Handle Numerics — use native int/float for cross-engine
        # compatibility (Neo4j driver rejects decimal.Decimal)
        try:
            d = Decimal(val_str)
            # Convert to native types for compatibility
            if "." not in val_str:
                return int(d)
            return float(d)
        except InvalidOperation:
            # Fallback for simple int/float
            try:
                if "." in val_str:
                    return float(val_str)
                else:
                    return int(val_str)
            except (ValueError, TypeError):
                msg = f"Could not parse literal '{val_str}' "
                msg += "as numeric, returning as string."
                logging.warning(msg)
                return val_str

    def _get_pk_column(
        self,
        where_expr: exp.Expression,
        use_catalogue: bool,
        client: Any,
        table_name: str,
    ) -> str:
        """
        [Sonar Refactor S3776] Helper for SelectStrategy:
        Determines the primary key column name from the catalogue or
        by inferring from the WHERE clause.
        """
        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name.lower())
            msg = f"Table '{table_name}' not found in catalogue."
            logging.info(f"catalogue_entry {catalogue_entry}")
            if not catalogue_entry:
                raise ValueError(msg)

            pk_col = catalogue_entry.get("pk", None)
            if not pk_col:
                raise ValueError(
                    f"No 'pk' defined in catalogue for table '{table_name}'"
                )
            return pk_col
        else:
            # Fallback: Infer from the left side of the WHERE clause
            msg = "Inferring PK from WHERE clause: "
            msg += f"{where_expr.left.this}"
            logging.warning(msg)
            return str(where_expr.left.this)

    def _is_pk_query(self, where_expr, use_catalogue, client, table_name):
        """
        Checks if the WHERE clause column matches the declared PK.
        Returns (is_pk, pk_col, where_col) tuple.
        """
        where_col = str(where_expr.left.this) if where_expr.left else None

        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name.lower())
            if catalogue_entry:
                pk_col = catalogue_entry.get("pk", None)
                if isinstance(pk_col, list):
                    return where_col in pk_col, pk_col, where_col
                return where_col == pk_col, pk_col, where_col

        return True, where_col, where_col

    async def _handle_select_by_pk(self, conn, ast, use_catalogue, client):
        """
        [Sonar Refactor S3776] Helper for SelectStrategy:
        Executes a 'get' operation for a 'SELECT ... WHERE pk = val' query.
        If the WHERE column is NOT the PK, delegates to _handle_select_with_filter.
        """
        table_name = ast.find(exp.Table).name
        where_expr = ast.args.get("where").this

        # Check if the WHERE column matches the PK
        is_pk, pk_col, where_col = self._is_pk_query(
            where_expr, use_catalogue, client, table_name
        )

        if not is_pk:
            logging.info(
                f"WHERE column '{where_col}' != PK '{pk_col}', "
                f"using get_all with filter for table '{table_name}'"
            )
            return await self._handle_select_with_filter(
                conn, ast, table_name, where_expr
            )

        # 1. Determine the PK column
        pk_col = self._get_pk_column(
            where_expr, use_catalogue, client, table_name
        )  # noqa:E501

        # 2. Parse the PK value
        pk_val = self._parse_pk_value_from_literal(where_expr.right)

        # 3. Execute the 'get'
        result = await conn.get(table_name, pk_col, pk_val)
        return [result] if result else []

    async def _handle_select_with_filter(
        self, conn, ast, table_name, where_expr
    ):
        """
        Handles SELECT with WHERE on a non-PK column by using get_all
        with a WHERE clause filter.
        """
        where_col = str(where_expr.left.this)
        where_val = self._parse_pk_value_from_literal(where_expr.right)

        # Build a WHERE clause string for connectors that support it
        # (e.g., Neo4j get_all accepts where_clause and params)
        where_clause = f"WHERE n.`{where_col}` = $filter_val"
        params = {"filter_val": where_val}

        logging.info(
            f"Executing filtered get_all: table={table_name}, "
            f"where={where_col}={where_val}"
        )

        # Try calling get_all with where_clause support
        import inspect
        sig = inspect.signature(conn.get_all)
        if "where_clause" in sig.parameters:
            result = await conn.get_all(
                table_name, where_clause=where_clause, params=params
            )
        else:
            # Fallback: get all and filter in Python
            all_results = await conn.get_all(table_name)
            if all_results:
                # Use string comparison for cross-engine compatibility
                # (Redis stores all values as strings)
                result = [
                    r for r in all_results
                    if str(r.get(where_col, '')) == str(where_val)
                ]
            else:
                result = []

        return result if result else []

    async def _handle_select_all(self, conn, ast):
        """
        [Sonar Refactor S3776] Helper for SelectStrategy:
        Executes a 'get_all' operation for a 'SELECT' query
        with no WHERE clause.
        """
        physical_table = ast.find(exp.Table).name
        logging.warning(
            "SELECT queries without a WHERE clause can be heavy to execute and load take caution"  # noqa:E501
        )
        logging.info(f"Connector '{conn.__class__.__name__}' executing get_all on table '{physical_table}'")  # noqa:E501
        logging.info(f"connector {conn}")
        result = await conn.get_all(physical_table)
        return result if result else []

    async def execute(self, client, ast, backend, use_catalogue):
        """
        [Sonar Refactor] Executes a SELECT statement.
        This method acts as a dispatcher, delegating complex logic
        to helper methods to maintain low cognitive complexity.
        """
        conn = await client.get_connector(backend)

        if not conn:
            raise ValueError(f"Connector for backend '{backend}' not found.")

        # Case 0: Remote execution
        if not conn.is_local_implementation:
            result = await conn.query(ast.sql())
            return result if result else []

        # --- Local Implementation Dispatcher ---

        # Case 1: Aggregation query with GROUP BY
        if ast.find(exp.Group):
            return await conn.group_by(ast)

        # Case 2: Aggregation query without GROUP BY
        is_agg = any(
            isinstance(e, exp.AggFunc)
            or (isinstance(e, exp.Alias) and isinstance(e.this, exp.AggFunc))
            for e in ast.expressions
        )
        if is_agg:
            return await conn.aggregate(ast)

        # Case 3: Simple SELECT...WHERE... query
        if ast.args.get("where"):
            return await self._handle_select_by_pk(
                conn, ast, use_catalogue, client
            )  # noqa:E501

        # Case 4: Simple SELECT (no WHERE)
        return await self._handle_select_all(conn, ast)
