import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEV_TOOLS = ROOT / "dev" / "tools"
if str(DEV_TOOLS) not in sys.path:
    sys.path.insert(0, str(DEV_TOOLS))

import update_agents_map  # noqa: E402


SERVER_PATH = ROOT / "backend" / "server.py"
ROOT_SERVER_PATH = ROOT / "server.py"
BACKEND_MODULES = ROOT / "backend" / "server_modules"
DATABASE_BACKFILLS_PATH = BACKEND_MODULES / "database_backfills.py"
STATE_READ_SERVICE_PATH = BACKEND_MODULES / "state_read_service.py"
STATE_EXTERNALIZATION_PATH = BACKEND_MODULES / "state_externalization.py"
STATE_PERSISTENCE_PATH = BACKEND_MODULES / "state_persistence.py"
SAMPLE_QUERIES_PATH = BACKEND_MODULES / "sample_queries.py"
IMPORT_BUNDLE_SERVICE_PATH = BACKEND_MODULES / "import_bundle_service.py"
BUNDLE_PREVIEW_SERVICE_PATH = BACKEND_MODULES / "bundle_preview_service.py"
HTTP_RUNTIME_PATH = BACKEND_MODULES / "http_runtime.py"
HTTP_CONCURRENCY_PATH = ROOT / "dev" / "tools" / "http_concurrency_benchmark.py"
RUNTIME_PATHS_PATH = BACKEND_MODULES / "runtime_paths.py"


def source_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def top_level_body(lines, name):
    start = next(i for i, line in enumerate(lines) if line.startswith(f"def {name}("))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("def ") or line.startswith("class ") or line.startswith("@contextmanager"):
            end = i
            break
    return "\n".join(lines[start:end])


class ArchitectureGuardTests(unittest.TestCase):
    def test_backend_entrypoint_stays_inside_backend_directory(self):
        self.assertTrue(SERVER_PATH.is_file())
        self.assertFalse(ROOT_SERVER_PATH.exists())

    def test_runtime_db_lock_is_only_used_for_startup_migration(self):
        self.assertNotIn("with DB_LOCK:", "\n".join(source_lines(SERVER_PATH)))
        body = top_level_body(source_lines(STATE_READ_SERVICE_PATH), "init_db")
        self.assertEqual(body.count("with ctx.db_lock:"), 1)

    def test_full_state_save_uses_sqlite_write_transaction_and_compact_current_snapshot(self):
        body = top_level_body(source_lines(STATE_PERSISTENCE_PATH), "save_state")
        self.assertIn("with ctx.write_db_connection() as conn:", body)
        self.assertNotIn("with DB_LOCK", body)
        self.assertIn("include_sample_photos=False", body)
        self.assertIn("ctx.hydrate_externalized_sample_fields(new_data, current_data)", body)

    def test_externalized_sample_field_hydration_stays_in_state_externalization_module(self):
        server_body = top_level_body(source_lines(SERVER_PATH), "hydrate_externalized_sample_fields")
        module_body = top_level_body(source_lines(STATE_EXTERNALIZATION_PATH), "hydrate_externalized_sample_fields")
        self.assertIn("state_externalization.hydrate_externalized_sample_fields", server_body)
        self.assertNotIn("photosExternalized", server_body)
        self.assertIn("photosExternalized", module_body)
        self.assertIn("eventsExternalized", module_body)
        self.assertIn("content_hash(log)", module_body)

    def test_sample_category_detail_query_stays_in_sample_queries_module(self):
        server_body = top_level_body(source_lines(SERVER_PATH), "load_sample_category_detail")
        module_body = top_level_body(source_lines(SAMPLE_QUERIES_PATH), "load_sample_category_detail")
        self.assertIn("sample_queries.load_sample_category_detail", server_body)
        self.assertNotIn("SELECT", server_body)
        self.assertIn("FROM sample_categories", module_body)
        self.assertIn("FROM sample_records", module_body)

    def test_database_backfill_sql_stays_in_backfill_module(self):
        server_lines = source_lines(SERVER_PATH)
        module_text = "\n".join(source_lines(DATABASE_BACKFILLS_PATH))
        for name in ("backfill_query_state_columns", "backfill_sample_identity_columns", "backfill_project_task_samples"):
            body = top_level_body(server_lines, name)
            self.assertIn(f"database_backfills.{name}", body)
            self.assertNotIn("SELECT", body)
        self.assertIn("FROM project_tasks", module_text)
        self.assertIn("FROM sample_records", module_text)
        self.assertIn("UPDATE sample_records", module_text)

    def test_http_runtime_context_contract_stays_in_http_runtime_module(self):
        server_body = top_level_body(source_lines(SERVER_PATH), "http_runtime_context")
        module_text = "\n".join(source_lines(HTTP_RUNTIME_PATH))
        self.assertIn("http_runtime.build_context(globals())", server_body)
        self.assertNotIn("SimpleNamespace(", server_body)
        self.assertIn("HTTP_RUNTIME_FIELDS", module_text)
        self.assertIn('"compose_bootstrap_state"', module_text)
        self.assertIn('"FRONTEND_DIR"', module_text)
        self.assertIn('"load_sample_category_detail"', module_text)
        self.assertIn('"commit_import_bundle"', module_text)
        self.assertIn('"save_state"', module_text)

    def test_import_preview_cache_keeps_large_payloads_on_disk(self):
        analyze_body = top_level_body(source_lines(BUNDLE_PREVIEW_SERVICE_PATH), "analyze_import_bundle")
        commit_body = top_level_body(source_lines(IMPORT_BUNDLE_SERVICE_PATH), "commit_import_bundle")
        self.assertIn("store_import_preview_payload", analyze_body)
        self.assertIn("_payload_path", analyze_body)
        self.assertNotIn('"_incoming": incoming_state', analyze_body)
        self.assertNotIn('"result": result', analyze_body)
        self.assertIn("_load_import_preview_payload", commit_body)

    def test_runtime_data_migration_keeps_copy_then_promote_verification(self):
        text = "\n".join(source_lines(RUNTIME_PATHS_PATH))
        prepare_body = top_level_body(source_lines(RUNTIME_PATHS_PATH), "prepare_runtime_paths")
        self.assertIn("copy_tree_without_loss_detailed", prepare_body)
        self.assertIn('"mode": "copy-then-promote"', prepare_body)
        self.assertIn('"copiedBytes": copied_bytes', prepare_body)
        self.assertIn('"verifiedFiles": verified_files', prepare_body)
        self.assertIn("filecmp.cmp(item, copied_to, shallow=False)", text)
        self.assertIn(".legacy-conflict-", text)

    def test_http_concurrency_benchmark_exercises_real_server_and_export(self):
        text = HTTP_CONCURRENCY_PATH.read_text(encoding="utf-8")
        self.assertIn("ThreadingHTTPServer", text)
        self.assertIn("QuietHandler", text)
        self.assertIn("ExplodingLock", text)
        self.assertIn("/api/export-bundle", text)
        self.assertIn("/api/import-bundle/preview", text)
        self.assertIn("/api/import-bundle/commit", text)
        self.assertIn("/api/sample-destroy-impact", text)
        self.assertIn("IMPORT_REVISION_CONFLICT", text)
        self.assertIn('method="POST"', text)
        self.assertIn('method="DELETE"', text)
        self.assertIn("/api/samples/{sample_id}/photos", text)
        self.assertIn("/api/stages/stage_000_00/tasks", text)
        self.assertIn("/api/sample-categories/cat_000/samples", text)

    def test_agents_file_map_is_current(self):
        index = update_agents_map.build_index()
        text = update_agents_map.AGENTS_PATH.read_text(encoding="utf-8")
        self.assertEqual(update_agents_map.refresh_agents_text(text, index), text)


if __name__ == "__main__":
    unittest.main()
