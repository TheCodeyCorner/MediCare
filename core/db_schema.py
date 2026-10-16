
import os
import re

import psycopg2.extensions


DB_SCHEMA = os.getenv("DB_SCHEMA", "medicare").strip()

# Restrict schema names to simple, lowercase PostgreSQL identifiers.
if not re.fullmatch(r"[a-z_][a-z0-9_]*", DB_SCHEMA):
    raise ValueError(
        "DB_SCHEMA must be a lowercase PostgreSQL identifier "
        "containing only letters, numbers, and underscores."
    )


class SchemaCursor(psycopg2.extensions.cursor):
    """Replace the project's default schema in SQL statements."""

    def execute(self, query, vars=None):
        if isinstance(query, str):
            query = query.replace(
                "medicare.",
                f'"{DB_SCHEMA}".',
            )

        return super().execute(query, vars)