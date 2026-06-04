"""SQLite schema definition and structural migrations."""

from __future__ import annotations

import sqlite3


STRUCTURAL_SCHEMA_ID = "structural_schema_v1"


def ensure_table_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_static_schema(conn: sqlite3.Connection) -> None:
    """Create tables, indexes, and structural compatibility columns."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            data_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            user TEXT,
            action TEXT,
            remark TEXT,
            revision_before INTEGER,
            revision_after INTEGER,
            client_ip TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_records (
            id TEXT PRIMARY KEY,
            category_id TEXT NOT NULL,
            sample_no TEXT,
            sn TEXT,
            imei TEXT,
            board_sn TEXT,
            is_reassembled INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            has_problem INTEGER NOT NULL DEFAULT 0,
            effective_status TEXT,
            location TEXT,
            owner TEXT,
            borrower TEXT,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(category_id) REFERENCES sample_categories(id)
        )
        """
    )
    ensure_table_column(conn, "sample_records", "has_problem", "INTEGER NOT NULL DEFAULT 0")
    ensure_table_column(conn, "sample_records", "effective_status", "TEXT")
    ensure_table_column(conn, "sample_records", "board_sn", "TEXT")
    ensure_table_column(conn, "sample_records", "is_reassembled", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category ON sample_records(category_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_sn ON sample_records(sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_imei ON sample_records(imei)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_board_sn ON sample_records(board_sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_identity_active ON sample_records(deleted_at, is_reassembled, sn, imei, board_sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_status ON sample_records(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_active ON sample_records(category_id, deleted_at, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_created ON sample_records(category_id, deleted_at, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_effective_created ON sample_records(category_id, deleted_at, effective_status, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_problem_created ON sample_records(category_id, deleted_at, has_problem, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_owner_created ON sample_records(category_id, deleted_at, owner, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_borrower_created ON sample_records(category_id, deleted_at, borrower, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_owner ON sample_records(owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_borrower ON sample_records(borrower)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_assets (
            id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            original_name TEXT,
            file_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            mime_type TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            created_by TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_assets_sample ON sample_assets(sample_id, kind, deleted_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_events (
            id TEXT PRIMARY KEY,
            sample_id TEXT,
            time TEXT,
            event_type TEXT,
            project_id TEXT,
            stage_id TEXT,
            task_id TEXT,
            test_item TEXT,
            user TEXT,
            data_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_events_sample ON sample_events(sample_id, time)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_records (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            owner TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_records_active ON project_records(deleted_at, sort_order)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_stages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(project_id) REFERENCES project_records(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_stages_project ON project_stages(project_id, deleted_at, sort_order)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            progress_id TEXT,
            category TEXT,
            test_item TEXT,
            sku_index INTEGER,
            status TEXT,
            flow_status TEXT,
            owner TEXT,
            sample_ids_json TEXT NOT NULL DEFAULT '[]',
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            deleted_at TEXT,
            FOREIGN KEY(project_id) REFERENCES project_records(id),
            FOREIGN KEY(stage_id) REFERENCES project_stages(id)
        )
        """
    )
    ensure_table_column(conn, "project_tasks", "flow_status", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage ON project_tasks(stage_id, deleted_at, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_progress ON project_tasks(progress_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, deleted_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_sku ON project_tasks(stage_id, deleted_at, sku_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_owner ON project_tasks(stage_id, deleted_at, owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_updated ON project_tasks(stage_id, deleted_at, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_created ON project_tasks(stage_id, deleted_at, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_flow_created ON project_tasks(stage_id, deleted_at, flow_status, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_sku_created ON project_tasks(stage_id, deleted_at, sku_index, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project_created ON project_tasks(project_id, deleted_at, created_at, id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_task_samples (
            task_id TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            test_item TEXT,
            status TEXT,
            flow_status TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(task_id, sample_id),
            FOREIGN KEY(task_id) REFERENCES project_tasks(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_task_samples_sample ON project_task_samples(sample_id, flow_status, task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_task_samples_task ON project_task_samples(task_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_logs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            project_id TEXT,
            stage_id TEXT,
            time TEXT,
            action TEXT,
            user TEXT,
            data_json TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES project_tasks(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_stage ON task_logs(stage_id, time)")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (id) VALUES (?)",
        (STRUCTURAL_SCHEMA_ID,),
    )
