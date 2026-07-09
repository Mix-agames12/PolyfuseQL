import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from sqlglot import exp


class LiteralParser:
    """
    A class that provides logic to parse sqlglot Literal expressions
    into native Python types. This is shared across Insert, Update, and
    Select strategies.
    """

    def _parse_literal_expression(self, lit_expr: exp.Literal) -> Any:
        """
        [Sonar Refactor] Shared helper to parse sqlglot Literal expressions.
        Reduces Cognitive Complexity and duplication across strategies.
        """
        if not isinstance(lit_expr, exp.Literal):
            # Fallback for unexpected types
            return lit_expr.this

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

        # Handle Numerics.
        # Integers are returned as native `int` (Cassandra `int` columns and
        # the Neo4j driver reject decimal.Decimal, and it keeps the stored type
        # consistent with the bulk-loaded rows). Values with a decimal point
        # keep `Decimal` for precision (e.g. Postgres `numeric` columns).
        # This mirrors SelectStrategy._parse_pk_value_from_literal.
        try:
            d = Decimal(val_str)
            if "." not in val_str:
                return int(d)
            return d
        except InvalidOperation:
            # Fallback for any other unhandled literal (e.g., 'abc')
            msg = f"Could not parse literal '{val_str}' "
            msg += "as numeric, returning as string."
            logging.warning(msg)
            return val_str
