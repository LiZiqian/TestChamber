"""SQLite connection primitives for TestChamber data access."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def write_db_connection(db_path: Path):
    """Open a SQLite write transaction without taking a process-wide lock."""
    with write_db_connection_from_factory(lambda: connect_db(db_path)) as conn:
        yield conn


@contextmanager
def write_db_connection_from_factory(connect_factory):
    """Open a SQLite write transaction using a caller-provided connection factory."""
    with connect_factory() as conn:
        began = False
        if not getattr(conn, "in_transaction", False):
            conn.execute("BEGIN IMMEDIATE")
            began = True
        try:
            yield conn
            if began and getattr(conn, "in_transaction", False):
                conn.commit()
        except Exception:
            if getattr(conn, "in_transaction", False):
                conn.rollback()
            raise
