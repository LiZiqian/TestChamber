import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import update_agents_map  # noqa: E402


SERVER_PATH = ROOT / "server.py"
HTTP_CONCURRENCY_PATH = ROOT / "tools" / "http_concurrency_benchmark.py"


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
    def test_runtime_db_lock_is_only_used_for_startup_migration(self):
        lines = source_lines(SERVER_PATH)
        lock_lines = [i + 1 for i, line in enumerate(lines) if "with DB_LOCK:" in line]
        self.assertEqual(lock_lines, [next(i + 1 for i, line in enumerate(lines) if line.strip() == "with DB_LOCK:")])

        init_start = next(i + 1 for i, line in enumerate(lines) if line.startswith("def init_db("))
        next_top_level = next(
            i + 1
            for i, line in enumerate(lines[init_start:], init_start)
            if line.startswith("def ") or line.startswith("class ")
        )
        self.assertGreater(lock_lines[0], init_start)
        self.assertLess(lock_lines[0], next_top_level)

    def test_full_state_save_uses_sqlite_write_transaction_and_compact_current_snapshot(self):
        body = top_level_body(source_lines(SERVER_PATH), "save_state")
        self.assertIn("with write_db_connection() as conn:", body)
        self.assertNotIn("with DB_LOCK", body)
        self.assertIn("include_sample_photos=False", body)

    def test_import_preview_cache_keeps_large_payloads_on_disk(self):
        lines = source_lines(SERVER_PATH)
        analyze_body = top_level_body(lines, "analyze_import_bundle")
        commit_body = top_level_body(lines, "commit_import_bundle")
        self.assertIn("_store_import_preview_payload", analyze_body)
        self.assertIn("_payload_path", analyze_body)
        self.assertNotIn('"_incoming": incoming_state', analyze_body)
        self.assertNotIn('"result": result', analyze_body)
        self.assertIn("_load_import_preview_payload", commit_body)

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
