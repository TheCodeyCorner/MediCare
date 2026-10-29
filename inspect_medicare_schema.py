#!/usr/bin/env python
"""Read-only inventory of the PostgreSQL schema named medicare.

Uses DATABASE_URL from the environment or the project's .env file.
Prints a human-readable inventory; pass --json for the complete metadata payload.
This script reads PostgreSQL catalogs only and opens a read-only transaction.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv

SCHEMA = "medicare"
PROJECT_ROOT = Path(__file__).resolve().parent


def fetch_rows(cursor: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    columns = [description.name for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_schema(connection: Any) -> dict[str, Any]:
    with connection.cursor() as cursor:
        relations = fetch_rows(
            cursor,
            """
            SELECT
                c.relname AS name,
                CASE c.relkind
                    WHEN 'r' THEN 'table'
                    WHEN 'p' THEN 'partitioned table'
                    WHEN 'v' THEN 'view'
                    WHEN 'm' THEN 'materialized view'
                    WHEN 'f' THEN 'foreign table'
                    WHEN 'S' THEN 'sequence'
                    ELSE c.relkind::text
                END AS kind,
                c.relispartition AS is_partition,
                c.relrowsecurity AS row_level_security,
                c.relforcerowsecurity AS force_row_level_security,
                obj_description(c.oid, 'pg_class') AS comment
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            ORDER BY c.relkind, c.relname
            """,
            (SCHEMA,),
        )
        columns = fetch_rows(
            cursor,
            """
            SELECT
                table_name,
                column_name,
                ordinal_position,
                data_type,
                udt_schema,
                udt_name,
                is_nullable,
                column_default,
                is_identity,
                identity_generation,
                is_generated,
                generation_expression,
                col_description(
                    (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass,
                    ordinal_position
                ) AS comment
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (SCHEMA,),
        )
        constraints = fetch_rows(
            cursor,
            """
            SELECT
                c.relname AS table_name,
                con.conname AS constraint_name,
                CASE con.contype
                    WHEN 'p' THEN 'PRIMARY KEY'
                    WHEN 'u' THEN 'UNIQUE'
                    WHEN 'f' THEN 'FOREIGN KEY'
                    WHEN 'c' THEN 'CHECK'
                    WHEN 'x' THEN 'EXCLUSION'
                    ELSE con.contype::text
                END AS constraint_type,
                con.condeferrable AS is_deferrable,
                con.condeferred AS initially_deferred,
                con.convalidated AS enforced,
                pg_get_constraintdef(con.oid, true) AS constraint_definition
            FROM pg_constraint AS con
            JOIN pg_class AS c ON c.oid = con.conrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
            ORDER BY c.relname, constraint_type, con.conname
            """,
            (SCHEMA,),
        )
        indexes = fetch_rows(
            cursor,
            """
            SELECT tablename AS table_name, indexname AS index_name, indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = %s
            ORDER BY tablename, indexname
            """,
            (SCHEMA,),
        )
        policies = fetch_rows(
            cursor,
            """
            SELECT schemaname, tablename, policyname, permissive, roles,
                   cmd, qual, with_check
            FROM pg_policies
            WHERE schemaname = %s
            ORDER BY tablename, policyname
            """,
            (SCHEMA,),
        )
        enum_types = fetch_rows(
            cursor,
            """
            SELECT t.typname AS type_name, e.enumsortorder AS sort_order,
                   e.enumlabel AS label
            FROM pg_type AS t
            JOIN pg_namespace AS n ON n.oid = t.typnamespace
            JOIN pg_enum AS e ON e.enumtypid = t.oid
            WHERE n.nspname = %s
            ORDER BY t.typname, e.enumsortorder
            """,
            (SCHEMA,),
        )
        domains = fetch_rows(
            cursor,
            """
            SELECT t.typname AS type_name,
                   format_type(t.typbasetype, t.typtypmod) AS base_type,
                   t.typnotnull AS not_null,
                   pg_get_expr(t.typdefaultbin, 0) AS default_value,
                   pg_get_constraintdef(c.oid, true) AS constraint_definition
            FROM pg_type AS t
            JOIN pg_namespace AS n ON n.oid = t.typnamespace
            LEFT JOIN pg_constraint AS c ON c.contypid = t.oid
            WHERE n.nspname = %s AND t.typtype = 'd'
            ORDER BY t.typname, c.conname
            """,
            (SCHEMA,),
        )
        routines = fetch_rows(
            cursor,
            """
            SELECT p.proname AS name,
                   CASE p.prokind
                       WHEN 'f' THEN 'function'
                       WHEN 'p' THEN 'procedure'
                       WHEN 'a' THEN 'aggregate'
                       WHEN 'w' THEN 'window function'
                       ELSE p.prokind::text
                   END AS kind,
                   pg_get_function_identity_arguments(p.oid) AS arguments,
                   pg_get_function_result(p.oid) AS result_type,
                   l.lanname AS language,
                   p.prosecdef AS security_definer,
                   p.provolatile AS volatility
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            JOIN pg_language AS l ON l.oid = p.prolang
            WHERE n.nspname = %s
            ORDER BY p.proname, arguments
            """,
            (SCHEMA,),
        )
        triggers = fetch_rows(
            cursor,
            """
            SELECT c.relname AS table_name, t.tgname AS trigger_name,
                   pg_get_triggerdef(t.oid, true) AS definition
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND NOT t.tgisinternal
            ORDER BY c.relname, t.tgname
            """,
            (SCHEMA,),
        )
        views = fetch_rows(
            cursor,
            """
            SELECT c.relname AS view_name, pg_get_viewdef(c.oid, true) AS definition
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relkind IN ('v', 'm')
            ORDER BY c.relname
            """,
            (SCHEMA,),
        )

    return {
        "schema": SCHEMA,
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "row_level_security_policies": policies,
        "enum_types": enum_types,
        "domains": domains,
        "routines": routines,
        "triggers": triggers,
        "views": views,
    }


def print_summary(schema: dict[str, Any]) -> None:
    print(f"PostgreSQL schema: {schema['schema']}")
    print(f"Relations: {len(schema['relations'])}")
    print(f"Columns: {len(schema['columns'])}")
    print(f"Constraints: {len(schema['constraints'])}")
    print(f"Indexes: {len(schema['indexes'])}")
    print(f"RLS policies: {len(schema['row_level_security_policies'])}")
    print(f"Enums: {len(schema['enum_types'])}; domains: {len(schema['domains'])}")
    print(f"Routines: {len(schema['routines'])}; triggers: {len(schema['triggers'])}")
    print()

    columns_by_table: dict[str, list[dict[str, Any]]] = {}
    for column in schema["columns"]:
        columns_by_table.setdefault(column["table_name"], []).append(column)
    constraints_by_table: dict[str, list[dict[str, Any]]] = {}
    for constraint in schema["constraints"]:
        constraints_by_table.setdefault(constraint["table_name"], []).append(constraint)
    indexes_by_table: dict[str, list[dict[str, Any]]] = {}
    for index in schema["indexes"]:
        indexes_by_table.setdefault(index["table_name"], []).append(index)

    for relation in schema["relations"]:
        name = relation["name"]
        print(f"{relation['kind'].upper()}: {name}")
        if relation["row_level_security"]:
            mode = "forced" if relation["force_row_level_security"] else "enabled"
            print(f"  RLS: {mode}")
        for column in columns_by_table.get(name, []):
            nullable = "NULL" if column["is_nullable"] == "YES" else "NOT NULL"
            default = f"; default={column['column_default']}" if column["column_default"] else ""
            identity = (
                f"; identity={column['identity_generation']}"
                if column["is_identity"] == "YES"
                else ""
            )
            print(
                f"  {column['ordinal_position']}. {column['column_name']}: "
                f"{column['data_type']} ({column['udt_schema']}.{column['udt_name']}), "
                f"{nullable}{identity}{default}"
            )
        for constraint in constraints_by_table.get(name, []):
            print(
                f"  {constraint['constraint_type']} "
                f"{constraint['constraint_name']}: "
                f"{constraint['constraint_definition']}"
            )
        for index in indexes_by_table.get(name, []):
            print(f"  INDEX {index['index_name']}: {index['definition']}")
        print()

    for key, label in (
        ("enum_types", "ENUM TYPES"),
        ("domains", "DOMAINS"),
        ("row_level_security_policies", "RLS POLICIES"),
        ("routines", "ROUTINES"),
        ("triggers", "TRIGGERS"),
        ("views", "VIEW DEFINITIONS"),
    ):
        if schema[key]:
            print(label)
            print(json.dumps(schema[key], indent=2, default=str))
            print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print full schema inventory as JSON")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL was not found in the environment or project .env file.")

    try:
        with psycopg2.connect(database_url, connect_timeout=10) as connection:
            connection.set_session(readonly=True, autocommit=False)
            inventory = fetch_schema(connection)
    except psycopg2.Error as error:
        raise SystemExit(f"Could not read the PostgreSQL schema: {error}") from error

    if args.json:
        print(json.dumps(inventory, indent=2, default=str))
    else:
        print_summary(inventory)


if __name__ == "__main__":
    main()
