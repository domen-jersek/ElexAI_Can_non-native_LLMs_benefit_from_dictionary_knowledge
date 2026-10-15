"""DDDS (PostgreSQL) access helpers.

The DDDS snapshot is restored into a local Postgres container (see
``scripts/db_restore.py``). This module only provides the connection helper;
the full ``SourceAdapter`` implementation for DDDS lands in Phase 1.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_env(repo_root: Path | None = None) -> None:
    """Load repo-root .env (does not override existing environment)."""
    load_dotenv((repo_root or REPO_ROOT) / ".env", override=False)


def ddds_connect(repo_root: Path | None = None, autocommit: bool = True) -> psycopg.Connection:
    """Connect to the local DDDS staging database (see docker-compose.yml)."""
    load_env(repo_root)
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
        connect_timeout=5,
        autocommit=autocommit,
    )


# ---------------------------------------------------------------------------
# schema introspection helpers (shared by inspection/export/graph scripts)
# ---------------------------------------------------------------------------


def table_columns(conn: psycopg.Connection) -> dict[str, set[str]]:
    """Map table name -> column names for the public schema."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        cols: dict[str, set[str]] = {}
        for t, c in cur.fetchall():
            cols.setdefault(t, set()).add(c)
    return cols


def fk_edges(conn: psycopg.Connection) -> list[tuple[str, str, str, str]]:
    """All foreign keys as (from_table, from_column, to_table, to_column)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conrelid::regclass::text, a.attname,
                   confrelid::regclass::text, af.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = ANY (c.confkey)
            WHERE c.contype = 'f'
            """
        )
        return [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]


def find_join_path(
    edges: list[tuple[str, str, str, str]], src: str, dst: str, max_hops: int = 6
) -> list[tuple[str, str, str]] | None:
    """BFS over FK edges (both directions); returns JOIN steps src -> dst.

    Each step is ``(next_table, next_col, prev_col)``, meaning::

        JOIN next_table <alias> ON <alias>.next_col = <prev_alias>.prev_col
    """
    adj: dict[str, list[tuple[str, str, str]]] = {}
    for ft, fc, tt, tc in edges:
        adj.setdefault(ft, []).append((tt, tc, fc))  # ft -> tt
        adj.setdefault(tt, []).append((ft, fc, tc))  # tt -> ft
    queue: list[tuple[str, list[tuple[str, str, str]]]] = [(src, [])]
    seen = {src}
    while queue:
        table, path = queue.pop(0)
        if table == dst:
            return path
        if len(path) >= max_hops:
            continue
        for nt, ncol, pcol in adj.get(table, []):
            if nt not in seen:
                seen.add(nt)
                queue.append((nt, [*path, (nt, ncol, pcol)]))
    return None


def query(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """SELECT helper returning a list of dicts (column name -> value)."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:  # pragma: no cover - misuse guard
            raise RuntimeError("query() requires a SELECT statement")
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def prepare_analytics(conn: psycopg.Connection) -> None:
    """Tame memory for large analytic scans.

    The restored DDDS snapshot has multi-million-row tables; on a ~12 GB Docker
    VM, parallel hash joins over them can OOM-kill a backend (which forces a
    full crash recovery). Disabling per-gather parallelism lets PostgreSQL use
    disk-backed sorts/aggregates instead (slower, but memory-bounded).
    """
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather = 0")
        cur.execute("SET work_mem = '128MB'")
        cur.execute("SET statement_timeout = 0")
