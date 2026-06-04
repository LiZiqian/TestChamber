import copy
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def empty_state():
    return {
        "version": "V7",
        "currentProjectId": None,
        "currentStageId": None,
        "users": [],
        "projects": [],
        "sampleLibrary": {"categories": [], "logs": []},
    }


class NoopLock:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False


class ExplodingLock:
    def __enter__(self):
        raise AssertionError("read path must not enter DB_LOCK")
    def __exit__(self, exc_type, exc, tb): return False


@contextmanager
def patched_server_db(conn):
    old_connect = server.connect_db
    old_lock = server.DB_LOCK
    old_backup_dir = server.BACKUP_DIR
    tmp_backup = tempfile.TemporaryDirectory()
    try:
        server.connect_db = lambda: conn
        server.DB_LOCK = NoopLock()
        server.BACKUP_DIR = Path(tmp_backup.name) / "backups"
        yield
    finally:
        server.connect_db = old_connect
        server.DB_LOCK = old_lock
        server.BACKUP_DIR = old_backup_dir
        tmp_backup.cleanup()


@contextmanager
def patched_server_data_dirs(root):
    old_data_dir = server.DATA_DIR
    old_sample_dir = server.SAMPLE_DATA_DIR
    old_backup_dir = server.BACKUP_DIR
    old_import_preview_dir = server.IMPORT_PREVIEW_DIR
    old_export_dir = server.EXPORT_DIR
    old_db_path = server.DB_PATH
    old_deployment_file = server.DEPLOYMENT_FILE
    old_runtime_paths = server._RUNTIME_PATHS
    try:
        server.DATA_DIR = Path(root)
        server.SAMPLE_DATA_DIR = Path(root) / "samples"
        server.BACKUP_DIR = Path(root) / "backups"
        server.IMPORT_PREVIEW_DIR = Path(root) / "import-previews"
        server.EXPORT_DIR = Path(root) / "exports"
        server.DB_PATH = Path(root) / "testchamber.sqlite"
        server.DEPLOYMENT_FILE = Path(root) / "deployment.json"
        server._RUNTIME_PATHS = server.runtime_paths.build_runtime_paths(Path(root))
        server.ensure_dirs()
        yield
    finally:
        server.DATA_DIR = old_data_dir
        server.SAMPLE_DATA_DIR = old_sample_dir
        server.BACKUP_DIR = old_backup_dir
        server.IMPORT_PREVIEW_DIR = old_import_preview_dir
        server.EXPORT_DIR = old_export_dir
        server.DB_PATH = old_db_path
        server.DEPLOYMENT_FILE = old_deployment_file
        server._RUNTIME_PATHS = old_runtime_paths


def make_multipart(fields=None, files=None, boundary="tcv7_test_boundary"):
    parts = []
    for name, value in (fields or {}).items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for item in files or []:
        field, filename, content_type, content = item
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        header = (
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        )
        parts.append(header.encode("utf-8"))
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return {"Content-Type": f"multipart/form-data; boundary={boundary}"}, b"".join(parts)


def call_handler_json(method, path, *, body=b"", headers=None, client_ip="127.0.0.1"):
    handler = object.__new__(server.Handler)
    handler.path = path
    handler.headers = headers or {}
    handler.client_address = (client_ip, 12345)
    handler._read_body = lambda max_bytes=server.MAX_UPLOAD_BYTES: body

    result = {}

    def send_json(payload, status=200):
        result["payload"] = payload
        result["status"] = status

    handler._send_json = send_json
    getattr(server.Handler, method)(handler)
    return result.get("status"), result.get("payload")


def state_conn(data):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    server.ensure_schema(conn)
    conn.execute(
        "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, 1, ?)",
        (server.json_dumps(server.split_state_for_storage(data)), server.now_iso()),
    )
    server.sync_project_library(conn, data)
    server.sync_sample_library(conn, data)
    return conn


class TrackingLock:
    def __init__(self):
        self.in_lock = False

    def __enter__(self):
        self.in_lock = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.in_lock = False
        return False


class FakeHttpHandler:
    def __init__(self, *, headers=None, body=b""):
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = []
        self.ended = False

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent_headers.append((name, value))

    def end_headers(self):
        self.ended = True

    def header_value(self, name):
        for key, value in self.sent_headers:
            if key.lower() == name.lower():
                return value
        return None


class ServerCoreTests(unittest.TestCase):
    def test_external_data_root_rejects_platform_internal_path(self):
        current_paths = server._RUNTIME_PATHS
        with self.assertRaises(ValueError):
            server.set_data_root(server.ROOT_DIR / "data")
        self.assertEqual(server._RUNTIME_PATHS, current_paths)

    def test_runtime_paths_migrate_legacy_data_and_backups_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            platform_root = Path(tmp) / "Platform"
            platform_root.mkdir()
            legacy_data = platform_root / "data"
            legacy_photo_dir = legacy_data / "samples" / "sample_1" / "photos"
            legacy_photo_dir.mkdir(parents=True)
            (legacy_data / "testchamber.sqlite").write_bytes(b"sqlite-bytes")
            (legacy_data / "deployment.json").write_text('{"deploymentId":"legacy"}', encoding="utf-8")
            (legacy_photo_dir / "front.jpg").write_bytes(b"photo-bytes")
            legacy_nested_backup = legacy_data / "backups"
            legacy_nested_backup.mkdir()
            (legacy_nested_backup / "same-name.json").write_text("from-data-dir", encoding="utf-8")
            legacy_backups = platform_root / "backups"
            legacy_backups.mkdir()
            (legacy_backups / "testchamber_v7_rev1_20260604_010203.json").write_text("{}", encoding="utf-8")
            (legacy_backups / "same-name.json").write_text("from-backups-dir", encoding="utf-8")
            expected_bytes = sum(path.stat().st_size for path in legacy_data.rglob("*") if path.is_file())
            expected_bytes += sum(path.stat().st_size for path in legacy_backups.rglob("*") if path.is_file())

            paths, report = server.runtime_paths.prepare_runtime_paths(platform_root)

            self.assertTrue(report.migrated)
            self.assertEqual(paths.data_dir, platform_root.with_name("Platform_data"))
            self.assertEqual(report.copied_bytes, expected_bytes)
            self.assertEqual(report.verified_files, 6)
            self.assertEqual((paths.data_dir / "testchamber.sqlite").read_bytes(), b"sqlite-bytes")
            self.assertEqual((paths.sample_data_dir / "sample_1" / "photos" / "front.jpg").read_bytes(), b"photo-bytes")
            self.assertTrue((paths.backup_dir / "testchamber_v7_rev1_20260604_010203.json").is_file())
            self.assertEqual((paths.backup_dir / "same-name.json").read_text(encoding="utf-8"), "from-data-dir")
            conflict_files = list(paths.backup_dir.glob("same-name.legacy-conflict-*.json"))
            self.assertEqual(len(conflict_files), 1)
            self.assertEqual(conflict_files[0].read_text(encoding="utf-8"), "from-backups-dir")
            self.assertTrue((paths.import_preview_dir).is_dir())
            self.assertTrue((paths.export_dir).is_dir())
            self.assertTrue((paths.data_dir / server.DATA_ROOT_MARKER_FILE).is_file())
            marker = json.loads((paths.data_dir / server.DATA_ROOT_MARKER_FILE).read_text(encoding="utf-8"))
            self.assertEqual(marker["migration"]["copiedBytes"], expected_bytes)
            self.assertEqual(marker["migration"]["verifiedFiles"], 6)

            self.assertTrue((legacy_data / "testchamber.sqlite").is_file())
            self.assertTrue((legacy_backups / "testchamber_v7_rev1_20260604_010203.json").is_file())

    def test_default_startup_uses_external_data_root_without_polluting_platform_dir(self):
        old_root = server.ROOT_DIR
        old_default_data_dir = server.DEFAULT_DATA_DIR
        old_index_path = server.INDEX_PATH
        old_runtime_paths = server._RUNTIME_PATHS
        with tempfile.TemporaryDirectory() as tmp:
            platform_root = Path(tmp) / "Platform"
            platform_root.mkdir()
            try:
                server.ROOT_DIR = platform_root
                server.DEFAULT_DATA_DIR = server.runtime_paths.default_data_dir(platform_root)
                server.INDEX_PATH = platform_root / "index.html"

                report = server.prepare_runtime_data_root()
                server.init_db()

                expected_data_root = platform_root.with_name("Platform_data")
                self.assertEqual(server.DATA_DIR, expected_data_root)
                self.assertFalse(server.runtime_paths.path_is_inside(server.DATA_DIR, platform_root))
                self.assertFalse(report.migrated)
                self.assertTrue((expected_data_root / server.DATA_ROOT_MARKER_FILE).is_file())
                self.assertTrue((expected_data_root / "testchamber.sqlite").is_file())
                self.assertTrue((expected_data_root / "deployment.json").is_file())
                self.assertFalse((platform_root / "data").exists())
                self.assertFalse((platform_root / "backups").exists())
                self.assertFalse((platform_root / "testchamber.sqlite").exists())
                self.assertFalse((platform_root / "deployment.json").exists())
            finally:
                server.ROOT_DIR = old_root
                server.DEFAULT_DATA_DIR = old_default_data_dir
                server.INDEX_PATH = old_index_path
                server._apply_runtime_paths(old_runtime_paths)

    def test_runtime_paths_skip_migration_when_external_target_has_business_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            platform_root = Path(tmp) / "Platform"
            platform_root.mkdir()
            legacy_data = platform_root / "data"
            legacy_data.mkdir()
            (legacy_data / "testchamber.sqlite").write_bytes(b"legacy-db")

            target_root = platform_root.with_name("Platform_data")
            target_root.mkdir()
            (target_root / "testchamber.sqlite").write_bytes(b"existing-db")

            paths, report = server.runtime_paths.prepare_runtime_paths(platform_root)

            self.assertFalse(report.migrated)
            self.assertEqual(report.skipped, "target_already_has_data")
            self.assertEqual(paths.data_dir, target_root)
            self.assertEqual((target_root / "testchamber.sqlite").read_bytes(), b"existing-db")
            self.assertEqual((legacy_data / "testchamber.sqlite").read_bytes(), b"legacy-db")

    def test_runtime_paths_rolls_back_staging_if_target_changes_during_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            platform_root = Path(tmp) / "Platform"
            platform_root.mkdir()
            legacy_data = platform_root / "data"
            legacy_data.mkdir()
            (legacy_data / "testchamber.sqlite").write_bytes(b"legacy-db")

            target_root = platform_root.with_name("Platform_data")
            target_root.mkdir()
            (target_root / "unrelated.tmp").write_text("keep", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                server.runtime_paths.prepare_runtime_paths(platform_root)

            self.assertEqual((target_root / "unrelated.tmp").read_text(encoding="utf-8"), "keep")
            self.assertEqual((legacy_data / "testchamber.sqlite").read_bytes(), b"legacy-db")
            leftovers = list(target_root.parent.glob(".Platform_data.migration-*"))
            self.assertEqual(leftovers, [])

    def test_sample_asset_storage_context_keeps_files_inside_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "external-data"
            sample_dir = data_dir / "samples"
            ctx = server.sample_assets.AssetStorageContext(
                data_dir=data_dir,
                sample_data_dir=sample_dir,
                now_iso=lambda: "2026-06-04T00:00:00+08:00",
            )

            meta = server.sample_assets.write_sample_asset_file(
                ctx,
                "sample/../A",
                "photo 1",
                b"asset-bytes",
                "front.jpg",
                "image/jpeg",
            )

            stored_path = data_dir / meta["relativePath"]
            self.assertTrue(stored_path.is_file())
            self.assertEqual(stored_path.read_bytes(), b"asset-bytes")
            self.assertTrue(stored_path.resolve().is_relative_to(data_dir.resolve()))
            with self.assertRaises(ValueError):
                server.sample_assets.path_inside_data(ctx, "../escape.jpg")

    def test_sample_query_module_normalizes_status_and_identity_flags(self):
        self.assertEqual(server.sample_queries.sample_effective_status({"status": "已分配"}), "在位等待")
        self.assertEqual(server.sample_queries.sample_effective_status({"status": "进入测试任务"}), "测试中")
        self.assertEqual(server.sample_queries.sample_effective_status({"status": "未知状态"}), "闲置")
        self.assertTrue(server.sample_queries.sample_is_reassembled({"isReassembled": "重组"}))
        self.assertTrue(server.sample_queries.sample_has_problem({"problemRecords": [{"description": "屏幕异常"}]}))
        self.assertEqual(server.sample_queries.sample_problem_state({"problemState": ["故障"]}), "fault")
        self.assertEqual(
            server.sample_constraints.sample_identity_fields({"sn": " SN123456 ", "imei": " IMEI9 ", "boardSn": " B1 "}),
            [
                {"field": "sn", "label": "SN", "value": "SN123456"},
                {"field": "imei", "label": "IMEI", "value": "IMEI9"},
                {"field": "boardSn", "label": "主板SN", "value": "B1"},
            ],
        )
        self.assertEqual(server.sample_constraints.sample_display_code({"sn": "SN123456789"}), "SN#456789")
        self.assertEqual(server.sample_constraints.sample_display_code({"imei": "IMEI123456"}), "IMEI#123456")
        self.assertEqual(server.sample_constraints.sample_display_code({"boardSn": "BOARD123456"}), "主板SN#123456")
        self.assertEqual(server.sample_constraints.sample_display_code({"sampleNo": "S001"}), "S001")
        self.assertEqual(server.sample_constraints.sample_identity_key(" SN-ABC "), "sn-abc")
        self.assertEqual(
            server.sample_constraints.sample_identity_match_field({"sn": "SN-1", "imei": "", "boardSn": ""}, "sn-1")["field"],
            "sn",
        )
        with sqlite3.connect(":memory:") as conn:
            result = server.sample_constraints.check_sample_identity_conflicts(conn, {
                "samples": [{"index": 7, "sn": "DUP", "isReassembled": True}],
            })
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["results"], [{"index": 7, "hasConflict": False, "conflict": None}])

    def test_task_query_module_keeps_pagination_and_candidate_rules(self):
        self.assertEqual(server.task_queries.task_flow_status({"status": "Fail"}), "异常终止")
        self.assertEqual(server.task_queries.task_flow_status({"completed": True}), "正常完成")
        self.assertEqual(server.task_queries.parse_page_params({"page": ["-2"], "pageSize": ["999"]}, max_size=100), (1, 100))
        self.assertEqual(server.task_queries.query_id_list({"selectedIds": ["a,b", "b,c"]}, "selectedIds"), ["a", "b", "c"])

        samples = [
            {"id": "s_selected", "status": "测试中"},
            {"id": "s_busy", "status": "闲置"},
            {"id": "s_blocked", "status": "已退库"},
            {"id": "s_free", "status": "闲置"},
        ]
        result = server.task_queries.decorate_task_sample_candidates(
            samples,
            selected_ids={"s_selected"},
            occupancy={"s_busy": [{"taskId": "task_1"}]},
        )
        by_id = {item["id"]: item for item in result}
        self.assertTrue(by_id["s_selected"]["selectable"])
        self.assertFalse(by_id["s_busy"]["selectable"])
        self.assertEqual(by_id["s_busy"]["disabledReason"], "样机已被其他未完成任务占用")
        self.assertFalse(by_id["s_blocked"]["selectable"])
        self.assertTrue(by_id["s_free"]["selectable"])

    def test_mutation_summary_module_builds_compact_sync_payloads(self):
        self.assertEqual(server.mutation_summary.sorted_nonempty_ids(["b", "", "a", "b"]), ["a", "b"])
        self.assertEqual(server.mutation_summary.limited_nonempty_ids(["b", "", "a", "b"], limit=1), (["b"], True))

        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "tasks": [{
                    "id": "task1",
                    "category": "可靠性",
                    "testItem": "跌落",
                    "status": "进行中",
                    "owner": "张三/001",
                    "sampleIds": ["sample1"],
                    "logs": [{"id": "log1", "action": "启动任务"}],
                }],
            }],
        }]
        data["sampleLibrary"] = {
            "categories": [{
                "id": "cat1",
                "name": "样机池",
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "测试中",
                    "photos": [],
                }],
            }],
            "logs": [],
        }
        conn = state_conn(data)
        try:
            conn.execute(
                """
                INSERT INTO sample_assets
                (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                ("photo1", "sample1", "photo", "front.jpg", "front.jpg", "samples/sample1/photos/front.jpg", "image/jpeg", 10, "2026-06-04T00:00:00+08:00", "tester"),
            )
            summary = server.mutation_summary.build_mutation_affected_summary(
                conn,
                project_ids=["p1", "", "p1"],
                stage_ids=["st1"],
                task_ids=["task1"],
                sample_ids=["sample1"],
                row_limit=2,
            )
        finally:
            conn.close()

        self.assertEqual(summary["rowLimit"], 2)
        self.assertEqual(summary["projectIds"], ["p1"])
        self.assertEqual(summary["stageIds"], ["st1"])
        self.assertEqual(summary["taskIds"], ["task1"])
        self.assertEqual(summary["sampleIds"], ["sample1"])
        self.assertEqual(summary["sampleCategoryIds"], ["cat1"])
        self.assertEqual(summary["projectSummaries"][0]["name"], "项目A")
        self.assertEqual(summary["sampleCategorySummaries"][0]["name"], "样机池")
        self.assertEqual(summary["tasks"][0]["logs"][0]["id"], "log1")
        self.assertEqual(summary["samples"][0]["photoCount"], 1)
        self.assertFalse(summary["tasksTruncated"])
        self.assertFalse(summary["samplesTruncated"])

        import_scope = server.mutation_summary.build_import_mutation_summary(
            data,
            {"incoming_p": "p1"},
            {},
            {"incoming_t": "task1"},
            {"incoming_s": "sample1"},
            set(),
        )
        self.assertEqual(import_scope["projectIds"], ["p1"])
        self.assertEqual(import_scope["stageIds"], ["st1"])
        self.assertEqual(import_scope["taskIds"], ["task1"])
        self.assertEqual(import_scope["sampleCategoryIds"], ["cat1"])
        self.assertFalse(import_scope["requiresFullState"])

    def test_import_diff_module_detects_identity_conflicts_and_missing_assets(self):
        stripped = server.import_diff.strip_view_state({
            "currentProjectId": "p1",
            "currentStageId": "st1",
            "peoplePool": ["张三"],
            "locationPool": ["实验室"],
            "projects": [],
        })
        self.assertEqual(stripped, {"projects": []})
        normalized = server.import_diff.normalize_project({
            "id": "p1",
            "stages": [{"id": "st1", "tasks": [{"id": "task1"}]}],
        })
        self.assertEqual(normalized["members"], [])
        self.assertEqual(normalized["stages"][0]["tasks"][0]["sampleIds"], [])
        self.assertEqual(
            server.import_diff.diff_fields(
                {"status": "闲置", "photoCount": 2, "_categoryName": "主库"},
                {"status": "测试中", "photoCount": 3, "_categoryName": "导入"},
            ),
            {"status"},
        )

        current = empty_state()
        current["sampleLibrary"]["categories"] = [{
            "id": "cat_current",
            "name": "主库池",
            "samples": [{
                "id": "sample_current",
                "sn": "SN-DUP",
                "status": "闲置",
            }],
        }]
        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_incoming",
            "name": "导入池",
            "samples": [{
                "id": "sample_incoming",
                "sn": "SN-DUP",
                "status": "闲置",
                "photos": [{
                    "id": "photo_missing",
                    "relativePath": "samples/sample_incoming/photos/front.jpg",
                }],
            }],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            result = server.import_diff.diff_import_bundle(
                current,
                incoming,
                {"sourceDeploymentId": "dep-src", "revision": 7, "appVersion": "old"},
                Path(tmp),
            )

        self.assertEqual(result["source"]["deploymentId"], "dep-src")
        self.assertEqual(result["blockers"][0]["type"], "missing_photos")
        self.assertEqual(result["blockers"][0]["assetIds"], ["photo_missing"])
        conflicts = [item for item in result["conflicts"] if item["type"] == "sample_identity_conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["currentId"], "sample_current")
        self.assertEqual(conflicts[0]["incomingId"], "sample_incoming")
        self.assertEqual(result["summary"]["sampleIdentityConflicts"], 1)

    def test_import_diff_blocks_chamberdata_asset_hash_mismatch(self):
        current = empty_state()
        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_hash",
            "name": "哈希池",
            "samples": [{
                "id": "sample_hash",
                "sn": "SN-HASH",
                "photos": [{"id": "photo_hash", "relativePath": ""}],
            }],
        }]
        asset_index = {
            "schemaVersion": 1,
            "assets": [{
                "assetId": "photo_hash::original",
                "entity": "sample",
                "entityId": "sample_hash",
                "kind": "sample_photo",
                "role": "original",
                "metadataId": "photo_hash",
                "zipPath": "assets/samples/sample_hash/photos/front.jpg",
                "fileName": "front.jpg",
                "exists": True,
                "bytes": 5,
                "sha256": "0" * 64,
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            asset_path = Path(tmp) / "assets" / "samples" / "sample_hash" / "photos" / "front.jpg"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(b"real-bytes")
            result = server.import_diff.diff_import_bundle(
                current,
                incoming,
                {"format": server.chamber_package.FORMAT_V2, "sourceDeploymentId": "dep-src"},
                Path(tmp),
                asset_index=asset_index,
            )

        blockers = [item for item in result["blockers"] if item["type"] == "asset_integrity_mismatch"]
        self.assertEqual(blockers[0]["assetIds"], ["photo_hash"])

    def test_import_commit_module_remaps_and_merges_import_subrecords(self):
        stage_map: dict[str, str] = {}
        task_map: dict[str, str] = {}
        stage_count, task_count, stage_id = server.import_commit.register_imported_stage_tree(
            {"id": "stage_in", "tasks": [{"id": "task_in"}, {"id": "task_2"}]},
            stage_map,
            task_map,
        )
        self.assertEqual((stage_count, task_count, stage_id), (1, 2, "stage_in"))
        self.assertEqual(stage_map, {"stage_in": "stage_in"})
        self.assertEqual(task_map, {"task_in": "task_in", "task_2": "task_2"})

        data = empty_state()
        data["projects"] = [{
            "id": "project_target",
            "stages": [{
                "id": "stage_target",
                "tasks": [{
                    "id": "task_target",
                    "sampleIds": ["sample_in"],
                    "logs": [{"sampleId": "sample_in", "projectId": "project_in", "stageId": "stage_in", "taskId": "task_in"}],
                    "removedSampleRecords": [{"sampleId": "sample_in"}],
                    "sampleFaultRecords": [{"sampleId": "sample_in"}],
                }],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "samples": [{
                "id": "sample_target",
                "currentProjectId": "project_in",
                "currentStageId": "stage_in",
                "currentTaskId": "task_in",
                "photos": [{"id": "photo_existing"}],
                "problemRecords": [{"id": "problem_existing"}],
            }],
        }]
        server.import_commit.apply_id_maps(
            data,
            {"project_in": "project_target"},
            {"stage_in": "stage_target"},
            {"task_in": "task_target"},
            {"sample_in": "sample_target"},
        )
        task = data["projects"][0]["stages"][0]["tasks"][0]
        sample = data["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertEqual(task["sampleIds"], ["sample_target"])
        self.assertEqual(task["logs"][0]["sampleId"], "sample_target")
        self.assertEqual(task["removedSampleRecords"][0]["sampleId"], "sample_target")
        self.assertEqual(sample["currentTaskId"], "task_target")

        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_in",
            "samples": [{
                "id": "sample_in",
                "photos": [{"id": "photo_existing"}, {"id": "photo_new", "name": "front.jpg"}],
                "problemRecords": [{"id": "problem_existing"}, {"id": "problem_new", "problem": "不开机"}],
            }],
        }]
        incoming["sampleLibrary"]["logs"] = [{
            "id": "event_in",
            "sampleId": "sample_in",
            "projectId": "project_in",
            "stageId": "stage_in",
            "taskId": "task_in",
        }]
        photos_added, problems_added = server.import_commit.merge_import_sample_subrecords(
            data,
            incoming,
            {"sample_in": "sample_target"},
        )
        events_added = server.import_commit.merge_import_sample_events(
            data,
            incoming,
            {"project_in": "project_target"},
            {"stage_in": "stage_target"},
            {"task_in": "task_target"},
            {"sample_in": "sample_target"},
        )
        sample = data["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertEqual((photos_added, problems_added, events_added), (1, 1, 1))
        self.assertEqual([photo["id"] for photo in sample["photos"]], ["photo_existing", "photo_new"])
        self.assertEqual(data["sampleLibrary"]["logs"][0]["sampleId"], "sample_target")
        self.assertEqual(data["sampleLibrary"]["logs"][0]["taskId"], "task_target")

        invalid = copy.deepcopy(data)
        invalid["projects"][0]["stages"].append(copy.deepcopy(invalid["projects"][0]["stages"][0]))
        invalid["projects"][0]["stages"][0]["tasks"][0]["sampleIds"] = ["missing_sample"]
        errors = server.import_commit.validate_import_commit_state(invalid, {"project_target"})
        self.assertTrue(any("阶段 ID 重复" in item for item in errors))
        self.assertTrue(any("引用不存在的样机" in item for item in errors))

        conflict_state = empty_state()
        conflict_state["projects"] = [{
            "id": "p1",
            "stages": [{
                "id": "st1",
                "tasks": [
                    {"id": "task_a", "status": "进行中", "sampleIds": ["sample_target"]},
                    {"id": "task_b", "status": "阻塞中", "sampleIds": ["sample_target"]},
                ],
            }],
        }]
        conflicts = server.import_commit.detect_sample_occupancy_conflicts(conflict_state)
        self.assertEqual(conflicts[0]["sampleId"], "sample_target")
        self.assertEqual({item["taskId"] for item in conflicts[0]["tasks"]}, {"task_a", "task_b"})

    def test_task_mutation_rules_detect_finished_tasks_status_blockers_and_occupancy(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "stages": [{
                "id": "st1",
                "tasks": [
                    {"id": "task_done", "status": "正常完成", "completed": True, "sampleIds": ["sample_idle"]},
                    {"id": "task_busy", "status": "进行中", "sampleIds": ["sample_busy"]},
                ],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "samples": [
                {"id": "sample_idle", "sampleNo": "S001", "status": "闲置"},
                {"id": "sample_testing", "sampleNo": "S002", "sn": "SN002", "status": "测试中"},
                {"id": "sample_busy", "sampleNo": "S003", "status": "闲置"},
            ],
        }]
        conn = state_conn(data)
        try:
            finished = server.task_mutation_rules.existing_finished_task(conn, "task_done")
            self.assertEqual(finished["id"], "task_done")
            self.assertEqual(server.task_mutation_rules.existing_finished_task(conn, "task_busy"), None)
            self.assertEqual(server.task_mutation_rules.existing_task_sample_ids(conn, "task_busy"), {"sample_busy"})

            blockers = server.task_mutation_rules.detect_task_mutation_sample_status_blockers(conn, [(
                "task_new",
                {"id": "task_new", "status": "进行中", "testItem": "跌落", "sampleIds": ["sample_idle", "sample_testing"]},
            )])
            self.assertEqual(len(blockers), 1)
            self.assertEqual(blockers[0]["sampleId"], "sample_testing")
            self.assertEqual(blockers[0]["status"], "测试中")

            conflicts = server.task_mutation_rules.detect_task_mutation_occupancy_conflicts(
                conn,
                "task_new",
                {"id": "task_new", "status": "进行中", "testItem": "新增任务", "sampleIds": ["sample_busy"]},
                "p1",
                "st1",
            )
        finally:
            conn.close()

        self.assertEqual(conflicts[0]["sampleId"], "sample_busy")
        self.assertEqual({item["taskId"] for item in conflicts[0]["tasks"]}, {"task_new", "task_busy"})

    def test_record_writers_module_upserts_records_and_deletes_sample_category_assets(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_schema(conn)
        try:
            server.record_writers.update_project_record(
                conn,
                {"id": "p1", "name": "项目A", "code": "P-A", "stages": [{"id": "st1"}]},
                create_if_missing=True,
            )
            server.record_writers.update_stage_record(
                conn,
                {"id": "st1", "name": "阶段A", "tasks": [{"id": "task1"}]},
                "p1",
                "st1",
                create_if_missing=True,
            )
            task = {
                "id": "task1",
                "progressId": "prog1",
                "category": "可靠性",
                "testItem": "跌落",
                "skuIndex": 1,
                "status": "进行中",
                "owner": "张三/001",
                "sampleIds": ["sample1"],
                "logs": [{"id": "log1", "time": "2026-06-04T00:00:00+08:00", "action": "启动"}],
            }
            server.record_writers.upsert_task_record(conn, task, "p1", "st1", create_if_missing=True)

            project_json = json.loads(conn.execute("SELECT data_json FROM project_records WHERE id = 'p1'").fetchone()["data_json"])
            stage_json = json.loads(conn.execute("SELECT data_json FROM project_stages WHERE id = 'st1'").fetchone()["data_json"])
            task_row = conn.execute("SELECT flow_status, sample_ids_json, data_json FROM project_tasks WHERE id = 'task1'").fetchone()
            self.assertNotIn("stages", project_json)
            self.assertNotIn("tasks", stage_json)
            self.assertEqual(task_row["flow_status"], "进行中")
            self.assertEqual(json.loads(task_row["sample_ids_json"]), ["sample1"])
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM task_logs WHERE task_id = 'task1'").fetchone()["count"], 1)
            self.assertEqual(conn.execute("SELECT sample_id FROM project_task_samples WHERE task_id = 'task1'").fetchone()["sample_id"], "sample1")

            server.record_writers.update_sample_category_record(
                conn,
                {"id": "cat1", "name": "样机池", "samples": [{"id": "sample1"}]},
                create_if_missing=True,
            )
            server.record_writers.update_sample_record(
                conn,
                {
                    "id": "sample1",
                    "categoryId": "cat1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "闲置",
                    "problemRecords": [{"description": "不开机"}],
                    "photos": [{"id": "photo1"}],
                },
                create_if_missing=True,
            )
            conn.execute(
                """
                INSERT INTO sample_assets
                (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                ("photo1", "sample1", "photo", "front.jpg", "front.jpg", "samples/sample1/photos/front.jpg", "image/jpeg", 10, "2026-06-04T00:00:00+08:00", "tester"),
            )
            server.record_writers.upsert_sample_events(conn, [
                {"id": "event1", "sampleId": "sample1", "time": "2026-06-04T00:00:00+08:00", "source": "测试"},
                {"id": "event1", "sampleId": "sample1", "time": "2026-06-04T00:00:00+08:00", "source": "重复"},
            ])

            sample_row = conn.execute("SELECT has_problem, data_json FROM sample_records WHERE id = 'sample1'").fetchone()
            self.assertEqual(sample_row["has_problem"], 1)
            self.assertNotIn("photos", json.loads(sample_row["data_json"]))
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_events WHERE sample_id = 'sample1'").fetchone()["count"], 1)

            paths = server.record_writers.delete_sample_category_record(conn, "cat1")
            self.assertEqual(paths, ["samples/sample1/photos/front.jpg"])
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_records WHERE id = 'sample1'").fetchone()["count"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_assets WHERE sample_id = 'sample1'").fetchone()["count"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_events WHERE sample_id = 'sample1'").fetchone()["count"], 0)
        finally:
            conn.close()

    def test_http_route_helpers_decode_routes_and_guard_static_paths(self):
        self.assertEqual(server.http_routes.sample_photo_route("/api/samples/sample%201/photos/photo%202"), ("sample 1", "photo 2"))
        self.assertEqual(server.http_routes.sample_photo_route("/api/samples/sample%201/photos"), ("sample 1", None))
        self.assertEqual(server.http_routes.stage_tasks_route("/api/stages/stage%201/tasks"), "stage 1")
        self.assertEqual(server.http_routes.stage_tasks_batch_route("/api/stages/stage%201/tasks/batch"), "stage 1")
        self.assertEqual(server.http_routes.project_detail_route("/api/projects/proj%201"), "proj 1")
        self.assertIsNone(server.http_routes.project_detail_route("/api/projects/summary"))
        self.assertEqual(server.http_routes.sample_category_samples_route("/api/sample-categories/cat%201/samples"), "cat 1")
        self.assertEqual(server.http_routes.task_mutation_route("/api/tasks/task%201/mutation"), "task 1")

        self.assertTrue(server.http_routes.is_public_static_path("/js/app.core.js"))
        self.assertTrue(server.http_routes.is_public_static_path("/css/style.css"))
        self.assertFalse(server.http_routes.is_public_static_path("/data/testchamber.sqlite"))
        self.assertFalse(server.http_routes.is_public_static_path("/js/../server.py"))
        self.assertFalse(server.http_routes.is_public_static_path("/js/app.py"))

    def test_http_helpers_send_file_etag_and_read_body_limit(self):
        handler = FakeHttpHandler()
        server.http_helpers.send_json(handler, {"ok": True}, json_dumps=server.json_dumps)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.header_value("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(handler.wfile.getvalue(), b'{"ok":true}')

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app.js"
            target.write_bytes(b"console.log(1)")
            first = FakeHttpHandler()
            server.http_helpers.send_file(first, target, "text/javascript")
            etag = first.header_value("ETag")
            self.assertEqual(first.status, 200)
            self.assertTrue(etag)

            cached = FakeHttpHandler(headers={"If-None-Match": etag})
            server.http_helpers.send_file(cached, target, "text/javascript")
            self.assertEqual(cached.status, 304)
            self.assertEqual(cached.wfile.getvalue(), b"")

        body_handler = FakeHttpHandler(headers={"Content-Length": "4"}, body=b"data-extra")
        self.assertEqual(server.http_helpers.read_body(body_handler, 4), b"data")
        with self.assertRaises(ValueError):
            server.http_helpers.read_body(FakeHttpHandler(headers={"Content-Length": "5"}, body=b"12345"), 4)

    def test_import_defaulting_fills_missing_legacy_fields_without_dropping_unknowns(self):
        incoming = {
            "projects": [{
                "id": "p_legacy",
                "name": "旧项目",
                "customProjectField": "keep",
                "stages": [{
                    "id": "s_legacy",
                    "name": "EVT",
                    "tasks": [{"id": "t_legacy", "customTaskField": "keep"}],
                }],
            }],
            "sampleLibrary": {
                "categories": [{
                    "id": "cat_legacy",
                    "name": "旧样机池",
                    "samples": [{"id": "sample_legacy", "customSampleField": "keep"}],
                }],
            },
        }

        normalized = server.import_defaults.normalize_import_state(incoming, source_format="legacy-test")

        task = normalized["projects"][0]["stages"][0]["tasks"][0]
        sample = normalized["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertEqual(normalized["_importNormalizedFrom"], "legacy-test")
        self.assertEqual(task["customTaskField"], "keep")
        self.assertEqual(task["sampleIds"], [])
        self.assertEqual(task["logs"], [])
        self.assertEqual(task["issueRecord"], {"dtsNo": "", "isIssue": "", "issueNote": ""})
        self.assertEqual(sample["customSampleField"], "keep")
        self.assertEqual(sample["status"], "闲置")
        self.assertEqual(sample["photos"], [])
        self.assertEqual(sample["problemRecords"], [])

    def test_import_defaulting_filters_malformed_structural_entries(self):
        incoming = {
            "projects": [
                "drop-project",
                {
                    "id": 123,
                    "name": {"bad": "name"},
                    "code": "P-123",
                    "customProjectField": {"keep": True},
                    "members": ["drop-member", {"employeeNo": "001", "name": "张三"}],
                    "locations": ["深圳", {"bad": "location"}, 7, None, True],
                    "stages": [
                        "drop-stage",
                        {
                            "id": "stage_1",
                            "skuNames": ["SKU-A", {"bad": "sku"}, 2],
                            "tasks": [
                                "drop-task",
                                {
                                    "id": "task_1",
                                    "sampleIds": ["sample_1", {"bad": "sample"}, 5, None, True],
                                    "logs": ["drop-log", {"id": "log_1"}],
                                    "removedSampleRecords": ["drop-removed", {"sampleId": "sample_1"}],
                                    "sampleFaultRecords": ["drop-fault", {"sampleId": "sample_1"}],
                                    "resultUploads": ["drop-upload", {"id": "upload_1"}],
                                    "issueRecord": "drop-issue",
                                },
                            ],
                        },
                    ],
                },
            ],
            "sampleLibrary": {
                "categories": [
                    "drop-category",
                    {
                        "id": 55,
                        "name": "样机池",
                        "samples": [
                            "drop-sample",
                            {
                                "id": 66,
                                "status": {"bad": "status"},
                                "problemRecords": ["legacy problem note", {"description": "不开机"}],
                                "photos": [
                                    "drop-photo",
                                    {
                                        "id": "photo_1",
                                        "size": {"bad": "size"},
                                        "futurePhotoField": {"keep": True},
                                    },
                                ],
                                "logs": ["drop-sample-log", {"id": "sample_log_1"}],
                            },
                        ],
                    },
                ],
                "logs": ["drop-event", {"id": "event_1"}],
            },
        }

        normalized = server.import_defaults.normalize_import_state(incoming, source_format="legacy-test")

        self.assertEqual(len(normalized["projects"]), 1)
        project = normalized["projects"][0]
        self.assertEqual(project["id"], "123")
        self.assertEqual(project["name"], "")
        self.assertEqual(project["customProjectField"], {"keep": True})
        self.assertEqual(project["members"], [{"employeeNo": "001", "name": "张三"}])
        self.assertEqual(project["locations"], ["深圳", "7"])
        self.assertEqual(len(project["stages"]), 1)
        stage = project["stages"][0]
        self.assertEqual(stage["projectId"], "123")
        self.assertEqual(stage["skuNames"], ["SKU-A", "2"])
        self.assertEqual(len(stage["tasks"]), 1)
        task = stage["tasks"][0]
        self.assertEqual(task["projectId"], "123")
        self.assertEqual(task["stageId"], "stage_1")
        self.assertEqual(task["sampleIds"], ["sample_1", "5"])
        self.assertEqual(task["logs"], [{"id": "log_1"}])
        self.assertEqual(task["removedSampleRecords"], [{"sampleId": "sample_1"}])
        self.assertEqual(task["sampleFaultRecords"], [{"sampleId": "sample_1"}])
        self.assertEqual(task["resultUploads"], [{"id": "upload_1"}])
        self.assertEqual(task["issueRecord"], {"dtsNo": "", "isIssue": "", "issueNote": ""})

        library = normalized["sampleLibrary"]
        self.assertEqual(library["logs"], [{"id": "event_1"}])
        self.assertEqual(len(library["categories"]), 1)
        category = library["categories"][0]
        self.assertEqual(category["id"], "55")
        sample = category["samples"][0]
        self.assertEqual(sample["id"], "66")
        self.assertEqual(sample["categoryId"], "55")
        self.assertEqual(sample["status"], "闲置")
        self.assertEqual(sample["problemRecords"], ["legacy problem note", {"description": "不开机"}])
        self.assertEqual(sample["logs"], [{"id": "sample_log_1"}])
        self.assertEqual(len(sample["photos"]), 1)
        self.assertEqual(sample["photos"][0]["size"], 0)
        self.assertEqual(sample["photos"][0]["futurePhotoField"], {"keep": True})

    def test_chamberdata_round_trip_preserves_future_unknown_fields(self):
        source = empty_state()
        source["futureAppSettings"] = {"videoSidebar": {"enabled": True, "fields": ["clipId"]}}
        source["sampleLibrary"]["futureLibraryPolicy"] = {"mergeMode": "append"}
        source["projects"] = [{
            "id": "p_future",
            "name": "未来项目",
            "futureProjectField": {"ownerGroup": "Lab-A"},
            "stages": [{
                "id": "stage_future",
                "name": "DVT",
                "futureStageField": ["thermal", "video"],
                "tasks": [{
                    "id": "task_future",
                    "testItem": "录像检查",
                    "futureTaskField": {"videoRequired": True},
                    "sampleIds": ["sample_future"],
                }],
            }],
        }]
        source["sampleLibrary"]["categories"] = [{
            "id": "cat_future",
            "name": "未来样机池",
            "futureCategoryField": "category-extra",
            "samples": [{
                "id": "sample_future",
                "sampleNo": "F001",
                "sn": "SN-FUTURE",
                "futureSampleField": {"leftPanelVideo": "clip-001"},
                "photos": [{
                    "id": "photo_future",
                    "name": "front.jpg",
                    "futurePhotoField": {"score": 0.98},
                    "relativePath": "",
                }],
            }],
        }]

        package = server.chamber_package.build_export_package(
            source,
            data_dir=Path(tempfile.gettempdir()),
            app_version="7.1.future",
            server_version="TestChamberServer/future",
            exported_at="2026-06-04T00:00:00+08:00",
            export_id="exp_future_fields",
            deployment_id="deploy_future",
            revision=99,
        )
        restored = server.chamber_package.state_from_domain_documents(package["manifest"], package["domains"])
        normalized = server.import_defaults.normalize_import_state(restored, source_format=server.chamber_package.FORMAT_V2)

        self.assertEqual(normalized["futureAppSettings"]["videoSidebar"]["fields"], ["clipId"])
        self.assertEqual(normalized["sampleLibrary"]["futureLibraryPolicy"]["mergeMode"], "append")
        project = normalized["projects"][0]
        stage = project["stages"][0]
        task = stage["tasks"][0]
        category = normalized["sampleLibrary"]["categories"][0]
        sample = category["samples"][0]
        photo = sample["photos"][0]
        self.assertEqual(project["futureProjectField"]["ownerGroup"], "Lab-A")
        self.assertEqual(stage["futureStageField"], ["thermal", "video"])
        self.assertTrue(task["futureTaskField"]["videoRequired"])
        self.assertEqual(category["futureCategoryField"], "category-extra")
        self.assertEqual(sample["futureSampleField"]["leftPanelVideo"], "clip-001")
        self.assertEqual(photo["futurePhotoField"]["score"], 0.98)
        self.assertEqual(task["logs"], [])
        self.assertEqual(sample["problemRecords"], [])

    def test_get_state_reads_use_sqlite_snapshot_without_db_lock(self):
        data = empty_state()
        data["projects"] = [{"id": "p1", "name": "项目A", "stages": []}]
        conn = state_conn(data)
        conn.execute("UPDATE app_state SET revision = 9 WHERE id = 1")
        old_connect = server.connect_db
        old_lock = server.DB_LOCK
        try:
            server.connect_db = lambda: conn
            server.DB_LOCK = ExplodingLock()

            state, revision, _ = server.get_state(compact=True)
            metadata_revision, _ = server.get_state_metadata()

            self.assertEqual(revision, 9)
            self.assertEqual(metadata_revision, 9)
            self.assertEqual(state["projects"][0]["id"], "p1")
        finally:
            server.connect_db = old_connect
            server.DB_LOCK = old_lock

    def test_sample_destroy_impact_scope_uses_targeted_ids_without_db_lock(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [
            {
                "id": "cat_destroy",
                "name": "销毁池",
                "samples": [
                    {"id": "sample_destroy", "sampleNo": "D001", "sn": "SN-D", "status": "测试中"},
                ],
            },
            {
                "id": "cat_keep",
                "name": "保留池",
                "samples": [
                    {"id": "sample_keep", "sampleNo": "K001", "sn": "SN-K", "status": "测试中"},
                ],
            },
        ]
        data["projects"] = [{
            "id": "project_destroy",
            "name": "项目A",
            "stages": [{
                "id": "stage_destroy",
                "projectId": "project_destroy",
                "name": "阶段A",
                "tasks": [
                    {
                        "id": "task_running",
                        "projectId": "project_destroy",
                        "stageId": "stage_destroy",
                        "testItem": "运行任务",
                        "status": "进行中",
                        "sampleIds": ["sample_destroy", "sample_keep"],
                    },
                    {
                        "id": "task_completed_removed",
                        "projectId": "project_destroy",
                        "stageId": "stage_destroy",
                        "testItem": "历史任务",
                        "status": "正常完成",
                        "completed": True,
                        "sampleIds": [],
                        "removedSampleRecords": [{"sampleId": "sample_destroy"}],
                    },
                ],
            }],
        }]
        conn = state_conn(data)
        old_lock = server.DB_LOCK
        try:
            server.DB_LOCK = ExplodingLock()
            category_scope = server.list_sample_destroy_impact_scope(conn, {"categoryId": ["cat_destroy"]})
            sample_scope = server.list_sample_destroy_impact_scope(conn, {"sampleId": ["sample_destroy"]})
        finally:
            server.DB_LOCK = old_lock

        self.assertEqual(category_scope["sampleIds"], ["sample_destroy"])
        self.assertEqual(category_scope["relatedSampleIds"], ["sample_destroy", "sample_keep"])
        self.assertEqual(category_scope["projectIds"], ["project_destroy"])
        self.assertEqual(category_scope["stageIds"], ["stage_destroy"])
        self.assertEqual(category_scope["taskIds"], ["task_running"])
        self.assertEqual(category_scope["sampleCategoryIds"], ["cat_destroy", "cat_keep"])
        self.assertIn("task_completed_removed", sample_scope["taskIds"])
        self.assertEqual(sample_scope["projectIds"], ["project_destroy"])

    def test_import_preview_cache_cleanup_enforces_entry_and_byte_limits(self):
        old_entries = server.IMPORT_PREVIEW_MAX_ENTRIES
        old_bytes = server.IMPORT_PREVIEW_MAX_CACHED_BYTES
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                server.IMPORT_PREVIEW_MAX_ENTRIES = 2
                server.IMPORT_PREVIEW_MAX_CACHED_BYTES = 1000
                base_ts = server.time.time()
                for idx in range(3):
                    preview_dir = Path(tmp) / f"preview_{idx}"
                    preview_dir.mkdir()
                    server._IMPORT_PREVIEWS[f"pv_{idx}"] = {
                        "_ts": base_ts + idx,
                        "_tmp_dir": str(preview_dir),
                        "_cache_bytes": 80,
                    }
                server._cleanup_expired_previews()
                self.assertEqual(sorted(server._IMPORT_PREVIEWS), ["pv_1", "pv_2"])
                self.assertFalse((Path(tmp) / "preview_0").exists())

                server._IMPORT_PREVIEWS.clear()
                server.IMPORT_PREVIEW_MAX_ENTRIES = 8
                server.IMPORT_PREVIEW_MAX_CACHED_BYTES = 150
                for idx in range(3):
                    preview_dir = Path(tmp) / f"bytes_{idx}"
                    preview_dir.mkdir()
                    server._IMPORT_PREVIEWS[f"pv_bytes_{idx}"] = {
                        "_ts": base_ts + idx,
                        "_tmp_dir": str(preview_dir),
                        "_cache_bytes": 80,
                    }
                server._cleanup_expired_previews()
                self.assertEqual(sorted(server._IMPORT_PREVIEWS), ["pv_bytes_2"])
                self.assertFalse((Path(tmp) / "bytes_0").exists())
                self.assertFalse((Path(tmp) / "bytes_1").exists())
        finally:
            server.IMPORT_PREVIEW_MAX_ENTRIES = old_entries
            server.IMPORT_PREVIEW_MAX_CACHED_BYTES = old_bytes
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_import_preview_uses_compact_state_snapshot(self):
        old_get_state = server.get_state
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        calls = []
        try:
            incoming = empty_state()
            manifest = {
                "format": "testchamber-export-bundle-v1",
                "revision": 1,
                "exportedAt": server.now_iso(),
            }
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", server.json_dumps(manifest))
                zf.writestr("state.json", server.json_dumps(incoming))
            bundle_bytes = bundle.getvalue()

            def fake_get_state(*, compact=False):
                calls.append(compact)
                return empty_state(), 12, "2026-06-04T00:00:00+08:00"

            server.get_state = fake_get_state
            headers, body = make_multipart(files=[
                ("file", "bundle.zip", "application/zip", bundle_bytes),
            ])

            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp):
                result = server.analyze_import_bundle(headers, body)

                self.assertEqual(calls, [True])
                self.assertEqual(result["source"]["revision"], 1)
                entry = server._IMPORT_PREVIEWS[result["previewId"]]
                self.assertNotIn("_incoming", entry)
                self.assertNotIn("result", entry)
                self.assertTrue(Path(entry["_payload_path"]).is_file())
                self.assertEqual(entry["_zip_bytes"], len(bundle_bytes))
                self.assertEqual(entry["_cache_bytes"], len(bundle_bytes) + entry["_payload_bytes"])
                incoming_payload, result_payload = server._load_import_preview_payload(entry)
                self.assertEqual(incoming_payload.get("version"), "V7")
                self.assertEqual(result_payload.get("previewId"), result["previewId"])
        finally:
            server.get_state = old_get_state
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_legacy_import_preview_normalizes_malformed_structural_lists(self):
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        conn = state_conn(empty_state())
        try:
            incoming = empty_state()
            incoming["projects"] = [
                "drop-project",
                {
                    "id": "project_valid",
                    "name": "兼容项目",
                    "stages": [
                        "drop-stage",
                        {
                            "id": "stage_valid",
                            "name": "EVT",
                            "tasks": [
                                "drop-task",
                                {
                                    "id": "task_valid",
                                    "category": "可靠性",
                                    "testItem": "跌落",
                                    "status": "进行中",
                                    "sampleIds": ["sample_valid", {"bad": "sample"}],
                                    "logs": ["drop-log", {"id": "log_valid"}],
                                    "issueRecord": "drop-issue",
                                },
                            ],
                        },
                    ],
                },
            ]
            incoming["sampleLibrary"]["categories"] = [
                "drop-category",
                {
                    "id": "cat_valid",
                    "name": "兼容样机池",
                    "samples": [
                        "drop-sample",
                        {
                            "id": "sample_valid",
                            "sampleNo": "S-001",
                            "sn": "SN-001",
                            "photos": ["drop-photo", {"id": "photo_valid", "size": {"bad": "size"}}],
                        },
                    ],
                },
            ]
            incoming["sampleLibrary"]["logs"] = ["drop-event", {"id": "event_valid", "sampleId": "sample_valid"}]
            manifest = {
                "format": server.chamber_package.LEGACY_FORMAT_V1,
                "revision": 2,
                "exportedAt": server.now_iso(),
                "sourceDeploymentId": "legacy_source",
            }
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", server.json_dumps(manifest))
                zf.writestr("state.json", server.json_dumps(incoming))

            headers, body = make_multipart(files=[
                ("bundle", "legacy-malformed.zip", "application/zip", bundle.getvalue()),
            ])
            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
                preview = server.analyze_import_bundle(headers, body)

                self.assertEqual(preview["blockers"], [])
                self.assertEqual(preview["summary"]["projects"]["new"], 1)
                self.assertEqual(preview["summary"]["stages"]["new"], 1)
                self.assertEqual(preview["summary"]["tasks"]["new"], 1)
                self.assertEqual(preview["summary"]["samples"]["new"], 1)
                entry = server._IMPORT_PREVIEWS[preview["previewId"]]
                incoming_payload, _ = server._load_import_preview_payload(entry)
                self.assertEqual(len(incoming_payload["projects"]), 1)
                task = incoming_payload["projects"][0]["stages"][0]["tasks"][0]
                sample = incoming_payload["sampleLibrary"]["categories"][0]["samples"][0]
                self.assertEqual(task["sampleIds"], ["sample_valid"])
                self.assertEqual(task["issueRecord"], {"dtsNo": "", "isIssue": "", "issueNote": ""})
                self.assertEqual(sample["photos"][0]["size"], 0)
                self.assertEqual(incoming_payload["sampleLibrary"]["logs"], [{"id": "event_valid", "sampleId": "sample_valid"}])
        finally:
            conn.close()
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_import_revision_conflict_uses_metadata_without_composing_state(self):
        data = empty_state()
        conn = state_conn(data)
        conn.execute("UPDATE app_state SET revision = 7 WHERE id = 1")
        old_previews = dict(server._IMPORT_PREVIEWS)
        old_compose_state = server.compose_state
        server._IMPORT_PREVIEWS.clear()
        try:
            server._IMPORT_PREVIEWS["preview_stale"] = {
                "_ts": server.time.time(),
                "_revision": 3,
                "result": {"conflicts": [], "blockers": []},
            }
            with patched_server_db(conn):
                server.compose_state = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stale import preview must not compose full state"))
                result = server.commit_import_bundle({"previewId": "preview_stale", "decisions": {}})
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "IMPORT_REVISION_CONFLICT")
            self.assertEqual(result["server_revision"], 7)
        finally:
            server.compose_state = old_compose_state
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_import_commit_uses_compact_snapshot_and_preserves_existing_photos(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat_current",
            "name": "样机池",
            "samples": [{
                "id": "sample_existing",
                "sampleNo": "S-001",
                "sn": "SN-DUP",
                "status": "闲置",
                "photos": [{
                    "id": "photo_existing",
                    "name": "旧照片.jpg",
                    "type": "image/jpeg",
                    "size": 3,
                    "uploadedAt": "2026-06-04T00:00:00+08:00",
                    "relativePath": "samples/sample_existing/photos/existing.jpg",
                    "url": "/api/samples/sample_existing/photos/photo_existing",
                }],
            }],
        }]
        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_import",
            "name": "样机池",
            "samples": [{
                "id": "sample_import",
                "sampleNo": "S-002",
                "sn": "SN-DUP",
                "status": "闲置",
                "photos": [{
                    "id": "photo_import",
                    "name": "导入照片.jpg",
                    "type": "image/jpeg",
                    "size": 4,
                    "uploadedAt": "2026-06-04T01:00:00+08:00",
                    "relativePath": "samples/sample_import/photos/import.jpg",
                    "url": "/api/samples/sample_import/photos/photo_import",
                }],
            }],
        }]

        old_previews = dict(server._IMPORT_PREVIEWS)
        old_get_state = server.get_state
        calls = []
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with patched_server_data_dirs(tmp):
                    conn = state_conn(data)
                    preview_dir = Path(tmp) / "preview_merge_photo"
                    asset_dir = preview_dir / "assets" / "samples" / "sample_import" / "photos"
                    asset_dir.mkdir(parents=True)
                    (asset_dir / "import.jpg").write_bytes(b"new!")
                    result_payload = {
                        "source": {},
                        "blockers": [],
                        "autoApply": [],
                        "conflicts": [{
                            "conflictId": "conflict_photo",
                            "type": "sample_identity_conflict",
                            "entity": "sample",
                            "currentId": "sample_existing",
                            "incomingId": "sample_import",
                            "preferredMergeTarget": "sample_existing",
                            "mergeableFields": [],
                            "autoMergeSubData": ["photos"],
                        }],
                    }
                    payload_path = server._store_import_preview_payload(preview_dir, incoming, result_payload)
                    server._IMPORT_PREVIEWS["preview_merge_photo"] = {
                        "_ts": server.time.time(),
                        "_tmp_dir": str(preview_dir),
                        "_payload_path": str(payload_path),
                        "_revision": 1,
                        "_cache_bytes": payload_path.stat().st_size,
                    }

                    def tracking_get_state(*, compact=False):
                        calls.append(compact)
                        return old_get_state(compact=compact)

                    server.get_state = tracking_get_state
                    with patched_server_db(conn):
                        result = server.commit_import_bundle({
                            "previewId": "preview_merge_photo",
                            "decisions": {
                                "conflict_photo": {"action": "merge_into_existing", "targetId": "sample_existing"}
                            },
                        })
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(calls, [True])
                    state, _, _ = server.compose_state(conn)
                    sample = server._sample_index_by_id(state)["sample_existing"]
                    photo_ids = {photo.get("id") for photo in sample.get("photos") or []}
                    self.assertIn("photo_existing", photo_ids)
                    self.assertIn("photo_import", photo_ids)
        finally:
            server.get_state = old_get_state
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_save_state_current_snapshot_skips_full_photos_and_preserves_assets_and_events(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat_current",
            "name": "样机池",
            "samples": [{
                "id": "sample_existing",
                "sampleNo": "S-001",
                "sn": "SN-001",
                "status": "闲置",
                "photos": [{
                    "id": "photo_existing",
                    "name": "旧照片.jpg",
                    "type": "image/jpeg",
                    "size": 3,
                    "uploadedAt": "2026-06-04T00:00:00+08:00",
                    "relativePath": "samples/sample_existing/photos/existing.jpg",
                    "url": "/api/samples/sample_existing/photos/photo_existing",
                }],
            }],
            "logs": [],
        }]
        data["sampleLibrary"]["logs"] = [{
            "id": "event_existing",
            "sampleId": "sample_existing",
            "time": "2026-06-04T00:00:00+08:00",
            "source": "原事件",
        }]
        conn = state_conn(data)
        compact_state, revision, _ = server.compose_state(conn, include_sample_photos=False, include_sample_logs=False)
        sample = compact_state["sampleLibrary"]["categories"][0]["samples"][0]
        sample["status"] = "测试中"

        old_compose_state = server.compose_state
        old_should_backup = server._should_backup
        calls = []
        try:
            def tracking_compose_state(conn_arg, **kwargs):
                calls.append(kwargs)
                return old_compose_state(conn_arg, **kwargs)

            server.compose_state = tracking_compose_state
            server._should_backup = lambda *args, **kwargs: False
            with patched_server_db(conn):
                server.DB_LOCK = ExplodingLock()
                ok, result = server.save_state(compact_state, revision, "127.0.0.1", remark="compact-save")

            self.assertTrue(ok, result)
            self.assertEqual(calls[0], {"include_sample_photos": False, "include_sample_logs": True})
            state, _, _ = old_compose_state(conn)
            saved_sample = server._sample_index_by_id(state)["sample_existing"]
            self.assertEqual(saved_sample["status"], "测试中")
            self.assertEqual(saved_sample["photos"][0]["id"], "photo_existing")
            self.assertEqual(state["sampleLibrary"]["logs"][0]["id"], "event_existing")
        finally:
            server.compose_state = old_compose_state
            server._should_backup = old_should_backup

    def test_build_export_bundle_file_writes_temp_zip_without_byte_buffer(self):
        data = empty_state()
        data["projects"] = [{"id": "p1", "name": "项目A", "stages": []}]
        conn = state_conn(data)
        with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
            tmp_path, filename = server.build_export_bundle_file()
            try:
                self.assertTrue(tmp_path.is_file())
                self.assertTrue(tmp_path.parent.samefile(server.EXPORT_DIR))
                self.assertTrue(filename.startswith("chamberdata_export_"))
                with server.zipfile.ZipFile(tmp_path, "r") as zf:
                    names = set(zf.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("domains/projects.json", names)
                    self.assertIn("domains/tasks.json", names)
                    self.assertIn("domains/samples.json", names)
                    self.assertIn("assets/index.json", names)
                    self.assertIn("checksums.json", names)
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                    self.assertEqual(manifest["format"], "chamberdata-package-v2")
                    self.assertEqual(manifest["protocol"], "ChamberData")
                    self.assertEqual(manifest["counts"]["projects"], 1)
                    checksums = json.loads(zf.read("checksums.json").decode("utf-8"))
                    self.assertIn("manifest.json", checksums)
                    self.assertIn("domains/projects.json", checksums)
                    self.assertIn("assets/index.json", checksums)
            finally:
                tmp_path.unlink(missing_ok=True)

    def test_chamberdata_export_writes_asset_manifest_with_hashes(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat_asset",
            "name": "资产池",
            "samples": [{
                "id": "sample_asset",
                "sampleNo": "A001",
                "sn": "SN-ASSET",
                "status": "闲置",
                "photos": [{
                    "id": "photo_asset",
                    "name": "front.jpg",
                    "type": "image/jpeg",
                    "size": 11,
                    "uploadedAt": "2026-06-04T00:00:00+08:00",
                    "relativePath": "samples/sample_asset/photos/front.jpg",
                    "url": "/api/samples/sample_asset/photos/photo_asset",
                }],
            }],
        }]
        conn = state_conn(data)
        with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
            photo_dir = server.SAMPLE_DATA_DIR / "sample_asset" / "photos"
            photo_dir.mkdir(parents=True)
            (photo_dir / "front.jpg").write_bytes(b"asset-bytes")
            tmp_path, _ = server.build_export_bundle_file()
            try:
                with server.zipfile.ZipFile(tmp_path, "r") as zf:
                    names = set(zf.namelist())
                    self.assertNotIn("state.json", names)
                    self.assertIn("assets/index.json", names)
                    self.assertIn("assets/samples/sample_asset/photos/front.jpg", names)
                    asset_index = json.loads(zf.read("assets/index.json").decode("utf-8"))
                    assets = asset_index["assets"]
                    self.assertEqual(len(assets), 1)
                    self.assertEqual(assets[0]["metadataId"], "photo_asset")
                    self.assertEqual(assets[0]["zipPath"], "assets/samples/sample_asset/photos/front.jpg")
                    self.assertEqual(assets[0]["bytes"], len(b"asset-bytes"))
                    self.assertTrue(assets[0]["sha256"])
            finally:
                tmp_path.unlink(missing_ok=True)

    def test_chamberdata_import_rejects_checksum_mismatch(self):
        data = empty_state()
        data["projects"] = [{"id": "p_checksum", "name": "校验项目", "stages": []}]
        conn = state_conn(data)
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
                tmp_path, _ = server.build_export_bundle_file()
                try:
                    tampered = io.BytesIO()
                    with zipfile.ZipFile(tmp_path, "r") as src, zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as dst:
                        for info in src.infolist():
                            if info.filename == "domains/projects.json":
                                dst.writestr(info.filename, '[{"id":"p_checksum","name":"被篡改"}]')
                            else:
                                dst.writestr(info.filename, src.read(info.filename))

                    headers, body = make_multipart(files=[
                        ("bundle", "tampered.zip", "application/zip", tampered.getvalue()),
                    ])
                    with self.assertRaisesRegex(ValueError, "checksum 不匹配"):
                        server.analyze_import_bundle(headers, body)
                finally:
                    tmp_path.unlink(missing_ok=True)
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_chamberdata_import_rejects_manifest_count_mismatch(self):
        data = empty_state()
        data["projects"] = [{"id": "p_count", "name": "计数项目", "stages": []}]
        conn = state_conn(data)
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
                tmp_path, _ = server.build_export_bundle_file()
                try:
                    broken = io.BytesIO()
                    with zipfile.ZipFile(tmp_path, "r") as src, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as dst:
                        for info in src.infolist():
                            if info.filename == "manifest.json":
                                manifest = json.loads(src.read(info.filename).decode("utf-8"))
                                manifest["counts"]["projects"] = 99
                                dst.writestr(info.filename, server.json_dumps(manifest))
                            elif info.filename == "checksums.json":
                                continue
                            else:
                                dst.writestr(info.filename, src.read(info.filename))

                    headers, body = make_multipart(files=[
                        ("bundle", "count-mismatch.zip", "application/zip", broken.getvalue()),
                    ])
                    with self.assertRaisesRegex(ValueError, "manifest counts 不匹配: projects"):
                        server.analyze_import_bundle(headers, body)
                finally:
                    tmp_path.unlink(missing_ok=True)
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_chamberdata_import_rejects_malformed_domain_documents(self):
        data = empty_state()
        conn = state_conn(data)
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
                tmp_path, _ = server.build_export_bundle_file()
                try:
                    broken = io.BytesIO()
                    with zipfile.ZipFile(tmp_path, "r") as src, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as dst:
                        for info in src.infolist():
                            if info.filename == "domains/tasks.json":
                                dst.writestr(info.filename, '{"not":"a-list"}')
                            elif info.filename == "checksums.json":
                                continue
                            else:
                                dst.writestr(info.filename, src.read(info.filename))

                    headers, body = make_multipart(files=[
                        ("bundle", "malformed-domain.zip", "application/zip", broken.getvalue()),
                    ])
                    with self.assertRaisesRegex(ValueError, "domains/tasks.json 格式不正确"):
                        server.analyze_import_bundle(headers, body)
                finally:
                    tmp_path.unlink(missing_ok=True)
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_chamberdata_import_rejects_non_object_domain_and_asset_items(self):
        data = empty_state()
        conn = state_conn(data)
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
                tmp_path, _ = server.build_export_bundle_file()
                try:
                    cases = [
                        ("domains/tasks.json", '["bad-task"]', "domains/tasks.json 第 1 项格式不正确"),
                        (server.chamber_package.ASSET_INDEX_PATH, '{"schemaVersion":1,"assets":["bad-asset"]}', "assets/index.json 第 1 项格式不正确"),
                    ]
                    for broken_path, broken_payload, expected_error in cases:
                        broken = io.BytesIO()
                        with zipfile.ZipFile(tmp_path, "r") as src, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as dst:
                            for info in src.infolist():
                                if info.filename == broken_path:
                                    dst.writestr(info.filename, broken_payload)
                                elif info.filename == "checksums.json":
                                    continue
                                else:
                                    dst.writestr(info.filename, src.read(info.filename))

                        headers, body = make_multipart(files=[
                            ("bundle", "non-object-domain.zip", "application/zip", broken.getvalue()),
                        ])
                        with self.assertRaisesRegex(ValueError, expected_error):
                            server.analyze_import_bundle(headers, body)
                finally:
                    tmp_path.unlink(missing_ok=True)
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_chamberdata_import_uses_asset_manifest_zip_paths(self):
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as target_dir:
                photo_bytes = b"manifest-photo-bytes"
                manifest = {
                    "format": server.chamber_package.FORMAT_V2,
                    "protocol": server.chamber_package.PROTOCOL_NAME,
                    "schemaVersion": server.chamber_package.SCHEMA_VERSION,
                    "appVersion": "7.1.0",
                    "serverVersion": "TestChamberServer/7.1.0",
                    "exportedAt": "2026-06-04T00:00:00+08:00",
                    "exportId": "exp_manifest_test",
                    "sourceDeploymentId": "deploy_manifest_source",
                    "revision": 3,
                    "domainPaths": server.chamber_package.DOMAIN_PATHS,
                    "assetIndexPath": server.chamber_package.ASSET_INDEX_PATH,
                }
                domains = {
                    "app": {
                        "version": "7.1.0",
                        "users": [],
                        "projects": [],
                        "sampleLibrary": {"categories": [], "logs": []},
                        "testCaseMaster": [],
                    },
                    "projects": [],
                    "stages": [],
                    "tasks": [],
                    "sampleCategories": [{"id": "cat_manifest", "name": "Manifest资产池", "description": ""}],
                    "samples": [{
                        "id": "sample_manifest",
                        "categoryId": "cat_manifest",
                        "sampleNo": "MAN-001",
                        "sn": "SN-MANIFEST-001",
                        "status": "闲置",
                        "problemRecords": [],
                    }],
                    "sampleAssets": [{
                        "id": "photo_manifest",
                        "sampleId": "sample_manifest",
                        "name": "manifest-photo.jpg",
                        "type": "image/jpeg",
                        "size": len(photo_bytes),
                        "uploadedAt": "2026-06-04T00:00:00+08:00",
                        "relativePath": "",
                        "url": "/api/samples/sample_manifest/photos/photo_manifest",
                    }],
                    "sampleEvents": [],
                }
                asset_index = {
                    "schemaVersion": 1,
                    "assets": [{
                        "assetId": "photo_manifest::original",
                        "entity": "sample",
                        "entityId": "sample_manifest",
                        "kind": "sample_photo",
                        "role": "original",
                        "metadataId": "photo_manifest",
                        "sourceRelativePath": "samples/sample_manifest/photos/stale-relative-name.jpg",
                        "zipPath": "assets/samples/sample_manifest/photos/manifest-photo.jpg",
                        "fileName": "manifest-photo.jpg",
                        "exists": True,
                        "bytes": len(photo_bytes),
                        "sha256": server.chamber_package.sha256_bytes(photo_bytes),
                    }],
                }
                bundle = io.BytesIO()
                with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("manifest.json", server.json_dumps(manifest))
                    for key, path in server.chamber_package.DOMAIN_PATHS.items():
                        zf.writestr(path, server.json_dumps(domains[key]))
                    zf.writestr(server.chamber_package.ASSET_INDEX_PATH, server.json_dumps(asset_index))
                    zf.writestr("assets/samples/sample_manifest/photos/manifest-photo.jpg", photo_bytes)

                with patched_server_data_dirs(target_dir):
                    server.init_db()
                    headers, body = make_multipart(files=[
                        ("bundle", "manifest.zip", "application/zip", bundle.getvalue()),
                    ])
                    preview = server.analyze_import_bundle(headers, body)
                    self.assertEqual(preview["blockers"], [])

                    result = server.commit_import_bundle({"previewId": preview["previewId"], "decisions": {}})
                    self.assertTrue(result["ok"], result)
                    imported, _, _ = server.get_state()
                    sample = server._sample_index_by_id(imported)["sample_manifest"]
                    photo = sample["photos"][0]
                    self.assertEqual(photo["relativePath"], "samples/sample_manifest/photos/manifest-photo.jpg")
                    self.assertEqual(photo["url"], "/api/samples/sample_manifest/photos/photo_manifest")
                    self.assertTrue(server.path_inside_data(photo["relativePath"]).is_file())
                    self.assertEqual(server.path_inside_data(photo["relativePath"]).read_bytes(), photo_bytes)
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_cross_deployment_export_import_preserves_photo_assets(self):
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
                with patched_server_data_dirs(source_dir):
                    server.init_db()
                    server.DEPLOYMENT_FILE.write_text(
                        server.json_dumps({"deploymentId": "deploy_source_cross", "name": "source"}),
                        encoding="utf-8",
                    )
                    photo_dir = server.SAMPLE_DATA_DIR / "sample_cross_source" / "photos"
                    photo_dir.mkdir(parents=True, exist_ok=True)
                    (photo_dir / "photo_cross.jpg").write_bytes(b"cross-photo-bytes")
                    (photo_dir / "photo_cross_thumb.jpg").write_bytes(b"cross-thumb-bytes")

                    state, rev, _ = server.get_state()
                    state["projects"] = [{
                        "id": "proj_cross_source",
                        "name": "跨部署项目",
                        "code": "CROSS-001",
                        "members": [],
                        "locations": [],
                        "stages": [{
                            "id": "stage_cross_source",
                            "name": "EVT",
                            "skuNames": [],
                            "bom": [],
                            "strategy": [],
                            "progress": [],
                            "tasks": [{
                                "id": "task_cross_source",
                                "category": "可靠性",
                                "testItem": "高温测试",
                                "skuIndex": 0,
                                "status": "进行中",
                                "sampleIds": ["sample_cross_source"],
                                "logs": [],
                                "removedSampleRecords": [],
                                "sampleFaultRecords": [],
                                "resultUploads": [],
                            }],
                        }],
                    }]
                    state["sampleLibrary"]["categories"] = [{
                        "id": "cat_cross_source",
                        "name": "跨部署样机池",
                        "samples": [{
                            "id": "sample_cross_source",
                            "sampleNo": "CROSS-S001",
                            "sn": "SN-CROSS-001",
                            "imei": "868000000000001",
                            "boardSn": "BOARD-CROSS-001",
                            "status": "测试中",
                            "location": "源实验室",
                            "owner": "张三/001",
                            "borrower": "",
                            "sourceStageName": "EVT",
                            "sourceSkuName": "SKU-A",
                            "problemRecords": [],
                            "photos": [{
                                "id": "photo_cross",
                                "name": "photo_cross.jpg",
                                "type": "image/jpeg",
                                "size": len(b"cross-photo-bytes"),
                                "uploadedAt": "2026-06-04T00:00:00+08:00",
                                "relativePath": "samples/sample_cross_source/photos/photo_cross.jpg",
                                "thumbRelativePath": "samples/sample_cross_source/photos/photo_cross_thumb.jpg",
                                "url": "/api/samples/sample_cross_source/photos/photo_cross",
                                "thumbUrl": "/api/samples/sample_cross_source/photos/photo_cross__thumb",
                            }],
                            "logs": [],
                            "currentProjectId": "proj_cross_source",
                            "currentStageId": "stage_cross_source",
                            "currentTaskId": "task_cross_source",
                            "currentTestItem": "高温测试",
                        }],
                    }]
                    ok, resp = server.save_state(state, rev, "source", remark="source export", user="test")
                    self.assertTrue(ok, resp)
                    zip_data, filename = server.build_export_bundle()
                    self.assertTrue(filename.endswith(".zip"))

                with patched_server_data_dirs(target_dir):
                    server.init_db()
                    server.DEPLOYMENT_FILE.write_text(
                        server.json_dumps({"deploymentId": "deploy_target_cross", "name": "target"}),
                        encoding="utf-8",
                    )
                    headers, body = make_multipart(files=[
                        ("bundle", "source.zip", "application/zip", zip_data),
                    ])
                    preview = server.analyze_import_bundle(headers, body)
                    self.assertEqual(preview["source"]["deploymentId"], "deploy_source_cross")
                    self.assertEqual(preview["blockers"], [])

                    result = server.commit_import_bundle({"previewId": preview["previewId"], "decisions": {}})
                    self.assertTrue(result["ok"], result)

                    imported, _, _ = server.get_state()
                    project = imported["projects"][0]
                    stage = project["stages"][0]
                    task = stage["tasks"][0]
                    self.assertEqual(task["sampleIds"], ["sample_cross_source"])
                    sample = server._sample_index_by_id(imported)["sample_cross_source"]
                    self.assertEqual(sample["currentProjectId"], "proj_cross_source")
                    self.assertEqual(sample["currentStageId"], "stage_cross_source")
                    self.assertEqual(sample["currentTaskId"], "task_cross_source")
                    photo = sample["photos"][0]
                    self.assertEqual(photo["relativePath"], "samples/sample_cross_source/photos/photo_cross.jpg")
                    self.assertEqual(photo["thumbRelativePath"], "samples/sample_cross_source/photos/photo_cross_thumb.jpg")
                    self.assertTrue(server.path_inside_data(photo["relativePath"]).is_file())
                    self.assertTrue(server.path_inside_data(photo["thumbRelativePath"]).is_file())
                    self.assertEqual(server.path_inside_data(photo["relativePath"]).read_bytes(), b"cross-photo-bytes")
                    self.assertEqual(server.path_inside_data(photo["thumbRelativePath"]).read_bytes(), b"cross-thumb-bytes")
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_import_merge_into_non_empty_target_does_not_duplicate_stage_or_drop_samples(self):
        old_previews = dict(server._IMPORT_PREVIEWS)
        server._IMPORT_PREVIEWS.clear()
        try:
            with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
                with patched_server_data_dirs(source_dir):
                    server.init_db()
                    server.DEPLOYMENT_FILE.write_text(
                        server.json_dumps({"deploymentId": "deploy_source_merge"}),
                        encoding="utf-8",
                    )
                    state, rev, _ = server.get_state()
                    state["projects"] = [{
                        "id": "proj_source_merge",
                        "name": "共享项目",
                        "code": "MERGE-001",
                        "members": [],
                        "locations": [],
                        "stages": [{
                            "id": "stage_shared",
                            "name": "EVT",
                            "skuNames": [],
                            "bom": [],
                            "strategy": [],
                            "progress": [],
                            "tasks": [{
                                "id": "task_import",
                                "category": "可靠性",
                                "testItem": "跌落测试",
                                "skuIndex": 0,
                                "status": "进行中",
                                "sampleIds": ["sample_import_merge"],
                                "logs": [],
                                "removedSampleRecords": [],
                                "sampleFaultRecords": [],
                                "resultUploads": [],
                            }],
                        }],
                    }]
                    state["sampleLibrary"]["categories"] = [{
                        "id": "cat_source_merge",
                        "name": "共享样机池",
                        "samples": [{
                            "id": "sample_import_merge",
                            "sampleNo": "IMP-001",
                            "sn": "SN-IMPORT-MERGE",
                            "imei": "",
                            "boardSn": "",
                            "status": "测试中",
                            "location": "源实验室",
                            "owner": "李四/002",
                            "borrower": "",
                            "sourceStageName": "EVT",
                            "sourceSkuName": "SKU-A",
                            "problemRecords": [],
                            "photos": [],
                            "logs": [],
                            "currentProjectId": "proj_source_merge",
                            "currentStageId": "stage_shared",
                            "currentTaskId": "task_import",
                            "currentTestItem": "跌落测试",
                        }],
                    }]
                    ok, resp = server.save_state(state, rev, "source", remark="source merge", user="test")
                    self.assertTrue(ok, resp)
                    zip_data, _ = server.build_export_bundle()

                with patched_server_data_dirs(target_dir):
                    server.init_db()
                    target_state, target_rev, _ = server.get_state()
                    target_state["projects"] = [{
                        "id": "proj_target_merge",
                        "name": "共享项目",
                        "code": "MERGE-001",
                        "members": [],
                        "locations": [],
                        "stages": [{
                            "id": "stage_shared",
                            "name": "EVT",
                            "skuNames": [],
                            "bom": [],
                            "strategy": [],
                            "progress": [],
                            "tasks": [{
                                "id": "task_existing",
                                "category": "可靠性",
                                "testItem": "高温测试",
                                "skuIndex": 0,
                                "status": "未开始",
                                "sampleIds": [],
                                "logs": [],
                                "removedSampleRecords": [],
                                "sampleFaultRecords": [],
                                "resultUploads": [],
                            }],
                        }],
                    }]
                    target_state["sampleLibrary"]["categories"] = [{
                        "id": "cat_target_merge",
                        "name": "共享样机池",
                        "samples": [{
                            "id": "sample_existing_merge",
                            "sampleNo": "EX-001",
                            "sn": "SN-EXISTING-MERGE",
                            "imei": "",
                            "boardSn": "",
                            "status": "闲置",
                            "location": "目标实验室",
                            "owner": "王五/003",
                            "borrower": "",
                            "sourceStageName": "",
                            "sourceSkuName": "",
                            "problemRecords": [],
                            "photos": [],
                            "logs": [],
                            "currentProjectId": None,
                            "currentStageId": None,
                            "currentTaskId": None,
                            "currentTestItem": None,
                        }],
                    }]
                    ok, resp = server.save_state(target_state, target_rev, "target", remark="target setup", user="test")
                    self.assertTrue(ok, resp)

                    headers, body = make_multipart(files=[
                        ("bundle", "source.zip", "application/zip", zip_data),
                    ])
                    preview = server.analyze_import_bundle(headers, body)
                    conflicts = [c for c in preview["conflicts"] if c.get("type") == "project_name_conflict"]
                    self.assertEqual(len(conflicts), 1, preview)
                    decision = {
                        conflicts[0]["conflictId"]: {
                            "action": "merge_into_existing",
                            "targetId": "proj_target_merge",
                        }
                    }
                    result = server.commit_import_bundle({"previewId": preview["previewId"], "decisions": decision})
                    self.assertTrue(result["ok"], result)

                    merged, _, _ = server.get_state()
                    self.assertEqual(len(merged["projects"]), 1)
                    project = merged["projects"][0]
                    self.assertEqual(project["id"], "proj_target_merge")
                    self.assertEqual(len(project["stages"]), 1)
                    task_ids = [task["id"] for task in project["stages"][0]["tasks"]]
                    self.assertEqual(sorted(task_ids), ["task_existing", "task_import"])
                    self.assertEqual(len(task_ids), len(set(task_ids)))
                    samples = server._sample_index_by_id(merged)
                    self.assertIn("sample_existing_merge", samples)
                    self.assertIn("sample_import_merge", samples)
                    imported_sample = samples["sample_import_merge"]
                    self.assertEqual(imported_sample["currentProjectId"], "proj_target_merge")
                    self.assertEqual(imported_sample["currentStageId"], "stage_shared")
                    self.assertEqual(imported_sample["currentTaskId"], "task_import")
                    task_import = [task for task in project["stages"][0]["tasks"] if task["id"] == "task_import"][0]
                    self.assertEqual(task_import["sampleIds"], ["sample_import_merge"])
        finally:
            for preview_id in list(server._IMPORT_PREVIEWS):
                server._cleanup_preview_temp(preview_id)
            server._IMPORT_PREVIEWS.clear()
            server._IMPORT_PREVIEWS.update(old_previews)

    def test_detects_sample_occupancy_conflict_across_open_tasks(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "s1",
                "name": "阶段A",
                "tasks": [
                    {"id": "t1", "testItem": "用例1", "status": "进行中", "sampleIds": ["sample_1"]},
                    {"id": "t2", "testItem": "用例2", "status": "阻塞", "sampleIds": ["sample_1"]},
                ],
            }],
        }]

        conflicts = server.detect_sample_occupancy_conflicts(data)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["sampleId"], "sample_1")
        self.assertEqual({t["taskId"] for t in conflicts[0]["tasks"]}, {"t1", "t2"})

    def test_completed_tasks_do_not_count_as_occupancy_conflict(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "s1",
                "name": "阶段A",
                "tasks": [
                    {"id": "t1", "testItem": "用例1", "status": "正常完成", "completed": True, "sampleIds": ["sample_1"]},
                    {"id": "t2", "testItem": "用例2", "status": "待下发", "sampleIds": ["sample_1"]},
                ],
            }],
        }]

        self.assertEqual(server.detect_sample_occupancy_conflicts(data), [])

    def test_merge_state_keeps_independent_client_and_server_additions(self):
        base = empty_state()
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        current["projects"].append({"id": "p_server", "name": "服务器新增", "stages": []})
        incoming["projects"].append({"id": "p_client", "name": "客户端新增", "stages": []})

        merged = server.merge_state(base, incoming, current)

        self.assertEqual({p["id"] for p in merged["projects"]}, {"p_server", "p_client"})

    def test_sample_photo_loader_returns_thumbnail_metadata(self):
        old_data_dir = server.DATA_DIR
        old_sample_dir = server.SAMPLE_DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            server.DATA_DIR = Path(tmp)
            server.SAMPLE_DATA_DIR = Path(tmp) / "samples"
            try:
                conn = sqlite3.connect(":memory:")
                conn.row_factory = sqlite3.Row
                server.ensure_schema(conn)
                photo = server.store_asset_bytes(conn, "sample_1", b"original", "photo.jpg", "image/jpeg")
                thumb = server.store_thumbnail_bytes(conn, "sample_1", photo["id"], b"thumb", "photo.thumb.jpg", "image/jpeg")
                server.attach_thumbnail_meta(photo, thumb)

                loaded = server.load_sample_photos(conn, "sample_1")

                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["id"], photo["id"])
                self.assertEqual(loaded[0]["thumbId"], thumb["id"])
                self.assertIn(thumb["id"], loaded[0]["thumbUrl"])
            finally:
                server.DATA_DIR = old_data_dir
                server.SAMPLE_DATA_DIR = old_sample_dir

    def test_sample_photo_routes_upload_rename_and_delete(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{
                "id": "sample_1",
                "sampleNo": "S001",
                "sn": "SN001",
                "status": "闲置",
                "photos": [],
                "problemRecords": [],
            }],
        }]
        conn = state_conn(data)

        with tempfile.TemporaryDirectory() as tmp, patched_server_data_dirs(tmp), patched_server_db(conn):
            original_compose_state = server.compose_state
            server.compose_state = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("photo routes must not compose full state"))
            headers, body = make_multipart(
                fields={"remark": "上传测试照片"},
                files=[
                    ("photos", "front.jpg", "image/jpeg", b"photo-bytes"),
                    ("thumb_0", "front.thumb.jpg", "image/jpeg", b"thumb-bytes"),
                ],
            )

            try:
                original_lock = server.DB_LOCK
                original_write_bytes = Path.write_bytes

                def checked_write_bytes(path_obj, *args, **kwargs):
                    return original_write_bytes(path_obj, *args, **kwargs)

                try:
                    server.DB_LOCK = ExplodingLock()
                    Path.write_bytes = checked_write_bytes
                    status, payload = call_handler_json(
                        "do_POST",
                        "/api/samples/sample_1/photos",
                        body=body,
                        headers=headers,
                    )
                finally:
                    Path.write_bytes = original_write_bytes
                    server.DB_LOCK = original_lock

                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["revision"], 2)
                self.assertEqual(len(payload["uploaded"]), 1)
                self.assertEqual(len(payload["photos"]), 1)
                photo = payload["photos"][0]
                self.assertEqual(photo["name"], "front.jpg")
                self.assertIn("thumbUrl", photo)
                self.assertTrue((Path(tmp) / photo["relativePath"]).is_file())
                self.assertEqual(
                    conn.execute("SELECT action FROM audit_log WHERE revision_after = 2").fetchone()["action"],
                    "upload_sample_photos",
                )

                rename_body = json.dumps({"name": "front-renamed.jpg", "user": "张三/001"}).encode("utf-8")
                original_lock = server.DB_LOCK
                try:
                    server.DB_LOCK = ExplodingLock()
                    status, payload = call_handler_json(
                        "do_PATCH",
                        f"/api/samples/sample_1/photos/{photo['id']}",
                        body=rename_body,
                    )
                finally:
                    server.DB_LOCK = original_lock

                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["revision"], 3)
                self.assertEqual(payload["photos"][0]["name"], "front-renamed.jpg")
                audit = conn.execute(
                    "SELECT user, action, revision_before, revision_after FROM audit_log WHERE revision_after = 3"
                ).fetchone()
                self.assertEqual(audit["user"], "张三/001")
                self.assertEqual(audit["action"], "rename_sample_photo")
                self.assertEqual(audit["revision_before"], 2)
                self.assertEqual(audit["revision_after"], 3)

                original_lock = server.DB_LOCK
                original_unlink = Path.unlink

                def checked_unlink(path_obj, *args, **kwargs):
                    return original_unlink(path_obj, *args, **kwargs)

                try:
                    server.DB_LOCK = ExplodingLock()
                    Path.unlink = checked_unlink
                    status, payload = call_handler_json(
                        "do_DELETE",
                        f"/api/samples/sample_1/photos/{photo['id']}",
                    )
                finally:
                    Path.unlink = original_unlink
                    server.DB_LOCK = original_lock

                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["revision"], 4)
                self.assertEqual(payload["photos"], [])
                rows = conn.execute(
                    """
                    SELECT id, deleted_at
                    FROM sample_assets
                    WHERE sample_id = ? AND id IN (?, ?)
                    """,
                    ("sample_1", photo["id"], server.thumbnail_asset_id(photo["id"])),
                ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["deleted_at"] for row in rows))
                self.assertEqual(
                    conn.execute("SELECT action FROM audit_log WHERE revision_after = 4").fetchone()["action"],
                    "delete_sample_photo",
                )
            finally:
                server.compose_state = original_compose_state

    def test_stage_tasks_page_filters_and_paginates(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "s1",
                "name": "阶段A",
                "progress": [
                    {"id": "prog_1", "category": "射频", "testItem": "吞吐", "skuIndex": 1},
                    {"id": "prog_2", "category": "协议", "testItem": "注册", "skuIndex": 2},
                ],
                "tasks": [
                    {"id": "t1", "progressId": "prog_1", "category": "射频", "testItem": "吞吐", "skuIndex": 1, "status": "进行中", "owner": "张三/001"},
                    {"id": "t2", "progressId": "prog_2", "category": "协议", "testItem": "注册", "skuIndex": 2, "status": "阻塞", "owner": "李四/002"},
                    {"id": "t3", "progressId": "prog_1", "category": "射频", "testItem": "功耗", "skuIndex": 1, "status": "正常完成", "completed": True, "owner": "张三/001"},
                ],
            }],
        }]

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_schema(conn)
        server.sync_project_library(conn, data)

        page = server.list_stage_tasks_page(conn, "s1", {
            "page": ["1"],
            "pageSize": ["1"],
            "ownerName": ["张三"],
            "sku": ["1"],
        })

        self.assertEqual(page["total"], 2)
        self.assertEqual(page["totalPages"], 2)
        self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(page["rows"][0]["task"]["id"], "t1")

    def test_samples_page_filters_faults(self):
        data = empty_state()
        data["sampleLibrary"] = {
            "categories": [{
                "id": "c1",
                "name": "样机池A",
                "samples": [
                    {"id": "s1", "sampleNo": "A001", "sn": "SN001", "status": "闲置", "owner": "张三/001"},
                    {"id": "s2", "sampleNo": "A002", "sn": "SN002", "status": "闲置", "problemRecords": [{"id": "p1", "description": "不开机"}]},
                    {"id": "s3", "sampleNo": "A003", "sn": "SN003", "status": "测试中", "borrower": "李四/002"},
                ],
            }],
            "logs": [],
        }

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_schema(conn)
        server.sync_sample_library(conn, data)
        conn.execute("UPDATE sample_records SET effective_status = '故障' WHERE id = 's2'")

        page = server.list_samples_page(conn, "c1", {
            "page": ["1"],
            "pageSize": ["10"],
            "status": ["闲置"],
        })

        self.assertEqual(page["total"], 2)
        self.assertEqual({item["id"] for item in page["items"]}, {"s1", "s2"})
        self.assertEqual({item["effectiveStatus"] for item in page["items"]}, {"闲置"})
        self.assertNotIn("故障", page["stats"]["statusCounts"])

        idle_fault_page = server.list_samples_page(conn, "c1", {
            "page": ["1"],
            "pageSize": ["10"],
            "status": ["闲置"],
            "problemState": ["fault"],
        })

        self.assertEqual(idle_fault_page["total"], 1)
        self.assertEqual(idle_fault_page["items"][0]["id"], "s2")
        self.assertEqual(idle_fault_page["items"][0]["effectiveStatus"], "闲置")
        self.assertTrue(idle_fault_page["items"][0]["hasProblem"])
        self.assertNotIn("故障", idle_fault_page["stats"]["statusCounts"])
        self.assertEqual(idle_fault_page["stats"]["statusCounts"].get("闲置"), 1)
        self.assertEqual(idle_fault_page["stats"]["problemCounts"].get("fault"), 1)
        self.assertEqual(idle_fault_page["stats"]["problemCounts"].get("ok"), 1)

        fault_page = server.list_samples_page(conn, "c1", {
            "page": ["1"],
            "pageSize": ["10"],
            "problemState": ["fault"],
        })
        ok_page = server.list_samples_page(conn, "c1", {
            "page": ["1"],
            "pageSize": ["10"],
            "problemState": ["ok"],
        })

        self.assertEqual(fault_page["total"], 1)
        self.assertEqual(fault_page["items"][0]["id"], "s2")
        self.assertEqual(ok_page["total"], 2)
        self.assertEqual({item["id"] for item in ok_page["items"]}, {"s1", "s3"})

        conn.execute("UPDATE sample_records SET has_problem = 0, effective_status = '故障' WHERE id = 's2'")
        server.ensure_schema(conn)
        repaired = conn.execute("SELECT has_problem, effective_status FROM sample_records WHERE id = 's2'").fetchone()
        self.assertEqual(int(repaired["has_problem"]), 1)
        self.assertEqual(repaired["effective_status"], "闲置")

        summary = server.list_sample_categories_summary(conn)[0]
        self.assertNotIn("故障", summary["statusCounts"])
        self.assertEqual(summary["statusCounts"].get("闲置"), 2)
        self.assertEqual(summary["problemCounts"].get("fault"), 1)

    def test_task_sample_candidates_page_marks_selectability_without_full_sample_load(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "tasks": [
                    {"id": "task_current", "testItem": "当前任务", "status": "待下发", "sampleIds": ["selected_busy"]},
                    {"id": "task_other", "testItem": "占用任务", "status": "进行中", "sampleIds": ["occupied_idle"]},
                    {"id": "task_done", "testItem": "完成任务", "status": "正常完成", "completed": True, "sampleIds": ["idle"]},
                ],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [
                {"id": "selected_busy", "categoryId": "cat1", "sampleNo": "S001", "sn": "SN001", "status": "在位等待"},
                {"id": "idle", "categoryId": "cat1", "sampleNo": "S002", "sn": "SN002", "status": "闲置"},
                {"id": "occupied_idle", "categoryId": "cat1", "sampleNo": "S003", "sn": "SN003", "status": "闲置"},
                {"id": "testing", "categoryId": "cat1", "sampleNo": "S004", "sn": "SN004", "status": "测试中"},
            ],
        }]
        conn = state_conn(data)

        page = server.list_task_sample_candidates_page(conn, {
            "taskId": ["task_current"],
            "selectedIds": ["selected_busy"],
            "page": ["1"],
            "pageSize": ["10"],
        })

        self.assertEqual(page["selectedItems"][0]["id"], "selected_busy")
        self.assertTrue(page["selectedItems"][0]["selectable"])
        self.assertEqual({item["id"] for item in page["items"]}, {"idle", "occupied_idle", "testing"})
        by_id = {item["id"]: item for item in page["items"]}
        self.assertTrue(by_id["idle"]["selectable"])
        self.assertFalse(by_id["occupied_idle"]["selectable"])
        self.assertIn("占用", by_id["occupied_idle"]["disabledReason"])
        self.assertEqual(by_id["occupied_idle"]["occupyingTasks"][0]["taskId"], "task_other")
        self.assertFalse(by_id["testing"]["selectable"])
        self.assertIn("测试中", by_id["testing"]["disabledReason"])

        status_page = server.list_task_sample_candidates_page(conn, {
            "status": ["闲置"],
            "page": ["1"],
            "pageSize": ["10"],
        })
        self.assertEqual({item["id"] for item in status_page["items"]}, {"idle", "occupied_idle"})

        with patched_server_db(conn):
            status, payload = call_handler_json("do_GET", "/api/task-sample-candidates?taskId=task_current&selectedIds=selected_busy&pageSize=2")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["pageSize"], 2)
        self.assertEqual(payload["selectedItems"][0]["id"], "selected_busy")

    def test_commit_task_mutation_updates_task_sample_and_events(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "待下发",
                    "owner": "张三/001",
                    "sampleIds": ["sample1"],
                    "logs": [],
                }],
            }],
        }]
        data["sampleLibrary"] = {
            "categories": [{
                "id": "cat1",
                "name": "样机池",
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "闲置",
                    "owner": "张三/001",
                    "problemRecords": [],
                    "photos": [],
                }],
            }],
            "logs": [],
        }

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_schema(conn)
        conn.execute(
            "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, 1, ?)",
            (server.json_dumps(server.split_state_for_storage(data)), server.now_iso()),
        )
        server.sync_project_library(conn, data)
        server.sync_sample_library(conn, data)

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "action": "task_start",
                "stage": {
                    "id": "st1",
                    "projectId": "p1",
                    "name": "阶段A",
                    "progress": [{"id": "prog1", "status": "Testing", "testItem": "吞吐"}],
                },
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "进行中",
                    "owner": "张三/001",
                    "sampleIds": ["sample1"],
                    "logs": [{"id": "log1", "time": "2026-06-02T16:00:00+08:00", "action": "启动任务", "user": "张三/001"}],
                },
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "测试中",
                    "owner": "张三/001",
                    "currentProjectId": "p1",
                    "currentStageId": "st1",
                    "currentTaskId": "task1",
                    "currentTestItem": "吞吐",
                }],
                "sampleEvents": [{
                    "id": "event1",
                    "sampleId": "sample1",
                    "time": "2026-06-02T16:00:00+08:00",
                    "source": "任务启动",
                    "projectId": "p1",
                    "stageId": "st1",
                    "taskId": "task1",
                    "testItem": "吞吐",
                    "user": "张三/001",
                }],
            }, "127.0.0.1")

        self.assertTrue(ok, result)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["affected"]["projectIds"], ["p1"])
        self.assertEqual(result["affected"]["stageIds"], ["st1"])
        self.assertEqual(result["affected"]["taskIds"], ["task1"])
        self.assertEqual(result["affected"]["sampleIds"], ["sample1"])
        self.assertEqual(result["affected"]["tasks"][0]["status"], "进行中")
        self.assertEqual(result["affected"]["samples"][0]["status"], "测试中")
        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        task = state["projects"][0]["stages"][0]["tasks"][0]
        sample = state["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertEqual(task["status"], "进行中")
        self.assertEqual(task["logs"][0]["id"], "log1")
        self.assertEqual(sample["status"], "测试中")
        self.assertEqual(state["sampleLibrary"]["logs"][0]["id"], "event1")

    def test_task_mutation_backup_uses_read_snapshot_without_second_db_lock(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "待下发",
                    "owner": "张三/001",
                    "sampleIds": ["sample1"],
                    "logs": [],
                }],
            }],
        }]
        data["sampleLibrary"] = {
            "categories": [{
                "id": "cat1",
                "name": "样机池",
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "闲置",
                    "owner": "张三/001",
                    "problemRecords": [],
                    "photos": [],
                }],
            }],
            "logs": [],
        }
        conn = state_conn(data)

        old_connect = server.connect_db
        old_lock = server.DB_LOCK
        old_should_backup = server._should_backup
        old_write_backup = server.write_backup
        backups = []
        try:
            server.connect_db = lambda: conn
            server.DB_LOCK = ExplodingLock()
            server._should_backup = lambda *args, **kwargs: True
            server.write_backup = lambda snapshot, revision: backups.append((copy.deepcopy(snapshot), revision))
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "action": "task_start",
                "stage": {
                    "id": "st1",
                    "projectId": "p1",
                    "name": "阶段A",
                    "progress": [{"id": "prog1", "status": "Testing", "testItem": "吞吐"}],
                },
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "进行中",
                    "owner": "张三/001",
                    "sampleIds": ["sample1"],
                    "logs": [],
                },
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "测试中",
                    "owner": "张三/001",
                    "currentProjectId": "p1",
                    "currentStageId": "st1",
                    "currentTaskId": "task1",
                    "currentTestItem": "吞吐",
                }],
            }, "127.0.0.1")
        finally:
            server.connect_db = old_connect
            server.DB_LOCK = old_lock
            server._should_backup = old_should_backup
            server.write_backup = old_write_backup

        self.assertTrue(ok, result)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0][1], 2)

    def test_commit_task_mutation_can_create_and_delete_task(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                "tasks": [],
            }],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task_new",
                "createIfMissing": True,
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A", "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}]},
                "task": {
                    "id": "task_new",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "待下发",
                    "owner": "张三/001",
                    "sampleIds": [],
                    "logs": [{"id": "log_new", "time": "2026-06-02T16:10:00+08:00", "action": "新增任务", "user": "张三/001"}],
                },
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["taskIds"], ["task_new"])
            self.assertEqual(result["affected"]["tasks"][0]["id"], "task_new")

            state, revision, _ = server.compose_state(conn)
            self.assertEqual(revision, 2)
            self.assertEqual(state["projects"][0]["stages"][0]["tasks"][0]["id"], "task_new")

            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task_new",
                "deleteMode": "delete",
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A", "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}]},
                "task": {"id": "task_new", "projectId": "p1", "stageId": "st1", "sampleIds": []},
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["taskIds"], ["task_new"])
            self.assertEqual(result["affected"]["tasks"], [])

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["projects"][0]["stages"][0]["tasks"], [])

    def test_commit_task_mutation_rejects_new_non_idle_samples(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "tasks": [{"id": "task1", "status": "待下发", "sampleIds": ["idle"]}],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [
                {"id": "idle", "categoryId": "cat1", "sampleNo": "S001", "status": "闲置"},
                {"id": "testing", "categoryId": "cat1", "sampleNo": "S002", "status": "测试中"},
                {"id": "waiting", "categoryId": "cat1", "sampleNo": "S003", "status": "在位等待"},
            ],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A"},
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "status": "待下发",
                    "sampleIds": ["idle", "testing", "waiting"],
                },
            }, "127.0.0.1")

        self.assertFalse(ok)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["error_code"], "SAMPLE_STATUS_NOT_SELECTABLE")
        self.assertEqual({item["sampleId"] for item in result["samples"]}, {"testing", "waiting"})

    def test_commit_task_mutation_allows_existing_waiting_sample_to_start(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                "tasks": [{"id": "task1", "progressId": "prog1", "status": "待下发", "sampleIds": ["sample1"]}],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [{"id": "sample1", "categoryId": "cat1", "sampleNo": "S001", "status": "在位等待"}],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A", "progress": [{"id": "prog1", "status": "Testing", "testItem": "吞吐"}]},
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "testItem": "吞吐",
                    "status": "进行中",
                    "sampleIds": ["sample1"],
                },
                "samples": [{
                    "id": "sample1",
                    "categoryId": "cat1",
                    "sampleNo": "S001",
                    "status": "测试中",
                    "currentTaskId": "task1",
                }],
            }, "127.0.0.1")

        self.assertTrue(ok, result)
        state, _, _ = server.compose_state(conn)
        self.assertEqual(state["sampleLibrary"]["categories"][0]["samples"][0]["status"], "测试中")

    def test_commit_task_mutation_rejects_duplicate_finish_without_writes(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "Pass", "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "正常完成",
                    "completed": True,
                    "sampleIds": ["sample1"],
                    "logs": [],
                }],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{
                "id": "sample1",
                "categoryId": "cat1",
                "sampleNo": "S001",
                "status": "闲置",
            }],
        }]
        conn = state_conn(data)
        before_revision = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()["revision"]
        before_task_logs = conn.execute("SELECT COUNT(*) AS count FROM task_logs").fetchone()["count"]
        before_sample_events = conn.execute("SELECT COUNT(*) AS count FROM sample_events").fetchone()["count"]
        before_audit_logs = conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"]

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "action": "finish_task_result",
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A"},
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "testItem": "吞吐",
                    "status": "正常完成",
                    "completed": True,
                    "sampleIds": ["sample1"],
                    "logs": [{"id": "dup_log", "action": "结束任务"}],
                },
                "samples": [{"id": "sample1", "categoryId": "cat1", "sampleNo": "S001", "status": "闲置"}],
                "sampleEvents": [{"id": "dup_event", "sampleId": "sample1", "taskId": "task1", "source": "任务结束"}],
            }, "127.0.0.1")

        self.assertFalse(ok)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["error_code"], "TASK_ALREADY_FINISHED")
        self.assertEqual(conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()["revision"], before_revision)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM task_logs").fetchone()["count"], before_task_logs)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_events").fetchone()["count"], before_sample_events)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"], before_audit_logs)

    def test_commit_task_mutation_allows_first_finish(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "Testing", "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "进行中",
                    "sampleIds": ["sample1"],
                    "logs": [],
                }],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{"id": "sample1", "categoryId": "cat1", "sampleNo": "S001", "status": "测试中"}],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "taskId": "task1",
                "action": "finish_task_result",
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A", "progress": [{"id": "prog1", "status": "Pass", "testItem": "吞吐"}]},
                "task": {
                    "id": "task1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "progressId": "prog1",
                    "testItem": "吞吐",
                    "status": "正常完成",
                    "completed": True,
                    "sampleIds": ["sample1"],
                    "logs": [{"id": "finish_log", "action": "结束任务"}],
                },
                "samples": [{"id": "sample1", "categoryId": "cat1", "sampleNo": "S001", "status": "闲置"}],
                "sampleEvents": [{"id": "finish_event", "sampleId": "sample1", "taskId": "task1", "source": "任务结束"}],
            }, "127.0.0.1")

        self.assertTrue(ok, result)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["affected"]["taskIds"], ["task1"])
        self.assertEqual(result["affected"]["sampleIds"], ["sample1"])
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM task_logs").fetchone()["count"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM sample_events").fetchone()["count"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"], 1)

    def test_commit_task_batch_mutation_creates_many_tasks_with_single_revision(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                "tasks": [],
            }],
        }]
        conn = state_conn(data)
        tasks = [{
            "id": f"task_batch_{idx}",
            "progressId": "prog1",
            "category": "射频",
            "testItem": f"吞吐 {idx}",
            "skuIndex": 1,
            "status": "待下发",
            "owner": "",
            "sampleIds": [],
            "logs": [{
                "id": f"log_batch_{idx}",
                "time": "2026-06-02T16:40:00+08:00",
                "action": "新增待下发任务",
                "user": "管理员",
            }],
        } for idx in range(40)]

        with patched_server_db(conn):
            server.DB_LOCK = ExplodingLock()
            ok, result = server.commit_task_batch_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "createIfMissing": True,
                "action": "create_tasks_batch",
                "stage": {
                    "id": "st1",
                    "projectId": "p1",
                    "name": "阶段A",
                    "progress": [{"id": "prog1", "status": "待启动", "testItem": "吞吐"}],
                },
                "tasks": tasks,
            }, "127.0.0.1")

        self.assertTrue(ok, result)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["count"], 40)
        self.assertEqual(len(result["affected"]["tasks"]), 40)
        self.assertEqual(result["affected"]["tasksTruncated"], False)
        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        self.assertEqual(len(state["projects"][0]["stages"][0]["tasks"]), 40)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM task_logs").fetchone()["count"], 40)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"], 1)

    def test_commit_task_batch_mutation_rejects_new_non_idle_samples(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{"id": "st1", "name": "阶段A", "tasks": []}],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [{"id": "busy", "categoryId": "cat1", "sampleNo": "S001", "status": "测试中"}],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_batch_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "createIfMissing": True,
                "stage": {"id": "st1", "projectId": "p1", "name": "阶段A"},
                "tasks": [{"id": "task1", "status": "待下发", "sampleIds": ["busy"]}],
            }, "127.0.0.1")

        self.assertFalse(ok)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["error_code"], "SAMPLE_STATUS_NOT_SELECTABLE")
        self.assertEqual(result["samples"][0]["sampleId"], "busy")

    def test_commit_task_batch_mutation_rejects_invalid_task_without_partial_write(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{"id": "st1", "name": "阶段A", "tasks": []}],
        }]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_batch_mutation({
                "projectId": "p1",
                "stageId": "st1",
                "createIfMissing": True,
                "tasks": [
                    {"id": "task_valid", "testItem": "有效任务", "status": "待下发", "logs": []},
                    {"testItem": "缺少 ID", "status": "待下发", "logs": []},
                ],
            }, "127.0.0.1")

        self.assertFalse(ok)
        self.assertEqual(result["status"], 400)
        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 1)
        self.assertEqual(state["projects"][0]["stages"][0]["tasks"], [])
        self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"], 0)

    def test_commit_task_batch_mutation_rejects_missing_stage(self):
        data = empty_state()
        data["projects"] = [{"id": "p1", "name": "项目A", "stages": []}]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_task_batch_mutation({
                "projectId": "p1",
                "stageId": "missing_stage",
                "createIfMissing": True,
                "tasks": [{"id": "task_new", "testItem": "吞吐", "status": "待下发", "logs": []}],
            }, "127.0.0.1")

        self.assertFalse(ok)
        self.assertEqual(result["status"], 404)
        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 1)
        self.assertEqual(state["projects"][0]["stages"], [])

    def test_commit_sample_mutation_updates_and_deletes_sample(self):
        data = empty_state()
        data["sampleLibrary"] = {
            "categories": [{
                "id": "cat1",
                "name": "样机池",
                "samples": [{
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "闲置",
                    "location": "库房",
                    "photos": [],
                }],
            }],
            "logs": [],
        }
        conn = state_conn(data)

        with patched_server_db(conn):
            server.DB_LOCK = ExplodingLock()
            ok, result = server.commit_sample_mutation({
                "sampleId": "sample1",
                "sample": {
                    "id": "sample1",
                    "sampleNo": "S001",
                    "sn": "SN001",
                    "status": "取走分析",
                    "location": "实验室",
                    "owner": "张三/001",
                },
                "sampleEvents": [{
                    "id": "event_sample_update",
                    "sampleId": "sample1",
                    "time": "2026-06-02T16:20:00+08:00",
                    "source": "样机详情编辑",
                    "user": "管理员",
                }],
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["sampleIds"], ["sample1"])
            self.assertEqual(result["affected"]["samples"][0]["status"], "取走分析")
            state, revision, _ = server.compose_state(conn)
            sample = state["sampleLibrary"]["categories"][0]["samples"][0]
            self.assertEqual(revision, 2)
            self.assertEqual(sample["status"], "取走分析")
            self.assertEqual(sample["location"], "实验室")
            self.assertEqual(state["sampleLibrary"]["logs"][0]["id"], "event_sample_update")

            ok, result = server.commit_sample_mutation({
                "sampleId": "sample1",
                "deleteSample": True,
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["sampleIds"], ["sample1"])
            self.assertEqual(result["affected"]["samples"], [])

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["sampleLibrary"]["categories"][0]["samples"], [])

    def test_commit_sample_destroy_unlinks_asset_files_outside_db_lock(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{
                "id": "sample1",
                "sampleNo": "S001",
                "sn": "SN001",
                "status": "闲置",
                "photos": [{
                    "id": "photo_sample_destroy",
                    "name": "销毁照片.jpg",
                    "type": "image/jpeg",
                    "size": 4,
                    "uploadedAt": "2026-06-04T00:00:00+08:00",
                    "relativePath": "samples/sample1/photos/destroy.jpg",
                    "url": "/api/samples/sample1/photos/photo_sample_destroy",
                }],
            }],
        }]

        with tempfile.TemporaryDirectory() as tmp:
            with patched_server_data_dirs(tmp):
                conn = state_conn(data)
                photo_path = server.SAMPLE_DATA_DIR / "sample1" / "photos" / "destroy.jpg"
                photo_path.parent.mkdir(parents=True, exist_ok=True)
                photo_path.write_bytes(b"gone")

                tracking_lock = TrackingLock()
                old_connect = server.connect_db
                old_lock = server.DB_LOCK
                original_unlink = Path.unlink
                unlinked = []

                def checked_unlink(path_obj, *args, **kwargs):
                    self.assertFalse(tracking_lock.in_lock, "sample destroy file unlink must happen outside DB_LOCK")
                    unlinked.append(Path(path_obj))
                    return original_unlink(path_obj, *args, **kwargs)

                try:
                    server.connect_db = lambda: conn
                    server.DB_LOCK = tracking_lock
                    Path.unlink = checked_unlink
                    ok, result = server.commit_sample_mutation({
                        "sampleId": "sample1",
                        "deleteSample": True,
                    }, "127.0.0.1")
                finally:
                    Path.unlink = original_unlink
                    server.connect_db = old_connect
                    server.DB_LOCK = old_lock

                self.assertTrue(ok, result)
                self.assertIn(photo_path, unlinked)
                self.assertFalse(photo_path.exists())

    def test_commit_sample_category_mutation_deletes_category_and_updates_tasks(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "progress": [{"id": "prog1", "status": "Testing", "sampleIds": ["sample1", "sample2"], "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "category": "射频",
                    "testItem": "吞吐",
                    "status": "进行中",
                    "owner": "张三/001",
                    "sampleIds": ["sample1", "sample2"],
                    "logs": [],
                }],
            }],
        }]
        data["sampleLibrary"] = {
            "categories": [{
                "id": "cat1",
                "name": "样机池",
                "samples": [
                    {"id": "sample1", "sampleNo": "S001", "sn": "SN001", "status": "测试中", "photos": []},
                    {"id": "sample2", "sampleNo": "S002", "sn": "SN002", "status": "测试中", "photos": []},
                ],
            }],
            "logs": [],
        }
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_sample_category_mutation({
                "categoryId": "cat1",
                "deleteCategory": True,
                "taskMutations": [{
                    "projectId": "p1",
                    "stageId": "st1",
                    "taskId": "task1",
                    "stage": {"id": "st1", "projectId": "p1", "name": "阶段A", "progress": [{"id": "prog1", "status": "Fail", "sampleIds": [], "testItem": "吞吐"}]},
                    "task": {
                        "id": "task1",
                        "projectId": "p1",
                        "stageId": "st1",
                        "progressId": "prog1",
                        "category": "射频",
                        "testItem": "吞吐",
                        "status": "异常终止",
                        "owner": "张三/001",
                        "sampleIds": [],
                        "logs": [{"id": "log_destroy_pool", "time": "2026-06-02T16:30:00+08:00", "action": "样机池档案销毁", "user": "管理员"}],
                    },
                }],
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["sampleCategoryIds"], ["cat1"])
            self.assertEqual(result["affected"]["sampleCategorySummaries"], [])

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        self.assertEqual(state["sampleLibrary"]["categories"], [])
        task = state["projects"][0]["stages"][0]["tasks"][0]
        self.assertEqual(task["status"], "异常终止")
        self.assertEqual(task["sampleIds"], [])
        self.assertEqual(task["logs"][0]["id"], "log_destroy_pool")

    def test_commit_sample_category_destroy_unlinks_asset_files_outside_db_lock(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{
                "id": "sample1",
                "sampleNo": "S001",
                "sn": "SN001",
                "status": "闲置",
                "photos": [{
                    "id": "photo_category_destroy",
                    "name": "池销毁照片.jpg",
                    "type": "image/jpeg",
                    "size": 4,
                    "uploadedAt": "2026-06-04T00:00:00+08:00",
                    "relativePath": "samples/sample1/photos/category-destroy.jpg",
                    "url": "/api/samples/sample1/photos/photo_category_destroy",
                }],
            }],
        }]

        with tempfile.TemporaryDirectory() as tmp:
            with patched_server_data_dirs(tmp):
                conn = state_conn(data)
                photo_path = server.SAMPLE_DATA_DIR / "sample1" / "photos" / "category-destroy.jpg"
                photo_path.parent.mkdir(parents=True, exist_ok=True)
                photo_path.write_bytes(b"gone")

                tracking_lock = TrackingLock()
                old_connect = server.connect_db
                old_lock = server.DB_LOCK
                original_unlink = Path.unlink
                unlinked = []

                def checked_unlink(path_obj, *args, **kwargs):
                    self.assertFalse(tracking_lock.in_lock, "sample category destroy file unlink must happen outside DB_LOCK")
                    unlinked.append(Path(path_obj))
                    return original_unlink(path_obj, *args, **kwargs)

                try:
                    server.connect_db = lambda: conn
                    server.DB_LOCK = tracking_lock
                    Path.unlink = checked_unlink
                    ok, result = server.commit_sample_category_mutation({
                        "categoryId": "cat1",
                        "deleteCategory": True,
                    }, "127.0.0.1")
                finally:
                    Path.unlink = original_unlink
                    server.connect_db = old_connect
                    server.DB_LOCK = old_lock

                self.assertTrue(ok, result)
                self.assertIn(photo_path, unlinked)
                self.assertFalse(photo_path.exists())

    def test_commit_project_mutation_creates_and_deletes_project(self):
        data = empty_state()
        conn = state_conn(data)

        with patched_server_db(conn):
            server.DB_LOCK = ExplodingLock()
            ok, result = server.commit_project_mutation({
                "projectId": "p_new",
                "createIfMissing": True,
                "project": {
                    "id": "p_new",
                    "name": "新项目",
                    "code": "P-NEW",
                    "owner": "张三/001",
                    "members": [{"id": "m1", "name": "张三", "employeeNo": "001", "active": True}],
                    "locations": ["实验室"],
                },
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["projectIds"], ["p_new"])
            self.assertEqual(result["affected"]["projectSummaries"][0]["name"], "新项目")
            state, revision, _ = server.compose_state(conn)
            self.assertEqual(revision, 2)
            self.assertEqual(state["projects"][0]["name"], "新项目")
            self.assertEqual(state["projects"][0]["locations"], ["实验室"])

            ok, result = server.commit_project_mutation({
                "projectId": "p_new",
                "deleteProject": True,
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["projectIds"], ["p_new"])
            self.assertEqual(result["affected"]["projectSummaries"], [])

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["projects"], [])

    def test_commit_stage_mutation_creates_and_deletes_stage(self):
        data = empty_state()
        data["projects"] = [{"id": "p1", "name": "项目A", "stages": []}]
        conn = state_conn(data)

        with patched_server_db(conn):
            server.DB_LOCK = ExplodingLock()
            ok, result = server.commit_stage_mutation({
                "projectId": "p1",
                "stageId": "st_new",
                "createIfMissing": True,
                "project": {"id": "p1", "name": "项目A"},
                "stages": [{"id": "st_new", "projectId": "p1", "name": "阶段1", "skuNames": ["SKU1"]}],
                "stage": {"id": "st_new", "projectId": "p1", "name": "阶段1", "skuNames": ["SKU1"], "progress": [], "tasks": []},
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["stageIds"], ["st_new"])
            state, revision, _ = server.compose_state(conn)
            self.assertEqual(revision, 2)
            self.assertEqual(state["projects"][0]["stages"][0]["id"], "st_new")

            ok, result = server.commit_stage_mutation({
                "projectId": "p1",
                "stageId": "st_new",
                "deleteStage": True,
                "project": {"id": "p1", "name": "项目A"},
                "stages": [],
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["stageIds"], ["st_new"])

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["projects"][0]["stages"], [])

    def test_commit_sample_category_mutation_creates_category_and_samples(self):
        data = empty_state()
        conn = state_conn(data)

        with patched_server_db(conn):
            server.DB_LOCK = ExplodingLock()
            ok, result = server.commit_sample_category_mutation({
                "categoryId": "cat_new",
                "createIfMissing": True,
                "createSamples": True,
                "category": {"id": "cat_new", "name": "新样机池", "description": "说明"},
                "samples": [
                    {"id": "sample_new_1", "categoryId": "cat_new", "sampleNo": "S001", "sn": "SN001", "status": "闲置"},
                    {"id": "sample_new_2", "categoryId": "cat_new", "sampleNo": "S002", "sn": "SN002", "status": "测试中"},
                ],
            }, "127.0.0.1")
            self.assertTrue(ok, result)
            self.assertEqual(result["affected"]["sampleCategoryIds"], ["cat_new"])
            self.assertEqual(result["affected"]["sampleIds"], ["sample_new_1", "sample_new_2"])
            self.assertEqual(len(result["affected"]["samples"]), 2)

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        category = state["sampleLibrary"]["categories"][0]
        self.assertEqual(category["name"], "新样机池")
        self.assertEqual(len(category["samples"]), 2)

    def test_sample_reassembled_flag_persists_in_sample_json(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [{
                "id": "sample_r",
                "categoryId": "cat1",
                "sampleNo": "R001",
                "sn": "SN-R",
                "imei": "IMEI-R",
                "boardSn": "MB-R",
                "status": "闲置",
                "isReassembled": True,
            }],
        }]
        conn = state_conn(data)

        row = conn.execute("SELECT data_json FROM sample_records WHERE id = 'sample_r'").fetchone()
        self.assertTrue(json.loads(row["data_json"])["isReassembled"])
        state, _, _ = server.compose_state(conn)
        sample = state["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertTrue(sample["isReassembled"])

    def test_sample_identity_check_uses_server_index_and_reassembled_rules(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat_a",
            "name": "池A",
            "samples": [{
                "id": "sample_a",
                "categoryId": "cat_a",
                "sampleNo": "A001",
                "sn": "SN-A",
                "imei": "IMEI-A",
                "boardSn": "MB-A",
                "status": "闲置",
            }],
        }, {
            "id": "cat_b",
            "name": "池B",
            "samples": [{
                "id": "sample_b",
                "categoryId": "cat_b",
                "sampleNo": "B001",
                "sn": "SN-B",
                "imei": "IMEI-B",
                "boardSn": "MB-B",
                "status": "闲置",
            }, {
                "id": "sample_r",
                "categoryId": "cat_b",
                "sampleNo": "R001",
                "sn": "SN-LATE",
                "isReassembled": True,
                "status": "闲置",
            }],
        }]
        conn = state_conn(data)

        result = server.check_sample_identity_conflicts(conn, {
            "categoryId": "cat_a",
            "samples": [
                {"index": 0, "categoryId": "cat_a", "boardSn": "MB-A"},
                {"index": 1, "categoryId": "cat_a", "sn": "SN-B"},
                {"index": 2, "categoryId": "cat_a", "sn": "SN-LATE"},
                {"index": 3, "categoryId": "cat_a", "sn": "SN-A", "excludeSampleId": "sample_a"},
                {"index": 4, "categoryId": "cat_a", "sn": "SN-A", "isReassembled": True},
            ],
        })

        by_index = {item["index"]: item for item in result["results"]}
        self.assertTrue(by_index[0]["hasConflict"])
        self.assertEqual(by_index[0]["conflict"]["scope"], "category")
        self.assertEqual(by_index[0]["conflict"]["existingField"], "boardSn")
        self.assertTrue(by_index[1]["hasConflict"])
        self.assertEqual(by_index[1]["conflict"]["scope"], "global")
        self.assertFalse(by_index[2]["hasConflict"])
        self.assertFalse(by_index[3]["hasConflict"])
        self.assertFalse(by_index[4]["hasConflict"])

        with patched_server_db(conn):
            status, payload = call_handler_json(
                "do_POST",
                "/api/sample-identity-check",
                body=json.dumps({"categoryId": "cat_a", "samples": [{"index": 0, "imei": "IMEI-B"}]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["results"][0]["conflict"]["sample"]["id"], "sample_b")

    def test_sample_history_page_is_aggregated_server_side(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "EVT",
                "tasks": [{
                    "id": "task_1",
                    "projectId": "p1",
                    "stageId": "st1",
                    "testItem": "跌落测试",
                    "status": "正常完成",
                    "owner": "张三/001",
                    "sampleIds": ["sample_1"],
                    "result": "Fail",
                    "resultDate": "2026-06-03",
                    "sampleFaultRecords": [{"id": "fault_1", "sampleId": "sample_1", "problem": "不开机"}],
                    "resultUploads": [{
                        "id": "result_1",
                        "result": "Fail",
                        "user": "张三/001",
                        "time": "2026-06-03T10:00:00",
                        "samples": [{
                            "sampleId": "sample_1",
                            "photos": [{"id": "photo_1", "name": "fail.jpg"}],
                        }],
                    }],
                }],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池",
            "samples": [{
                "id": "sample_1",
                "categoryId": "cat1",
                "sampleNo": "S001",
                "sn": "SN001",
                "status": "闲置",
                "photos": [{
                    "id": "photo_1",
                    "name": "fail.jpg",
                    "url": "/api/samples/sample_1/photos/photo_1",
                    "relativePath": "samples/sample_1/photos/photo_1/fail.jpg",
                    "type": "image/jpeg",
                    "size": 12,
                    "uploadedAt": "2026-06-03T09:59:00",
                }],
            }],
        }]
        data["sampleLibrary"]["logs"] = [{
            "id": "event_1",
            "sampleId": "sample_1",
            "taskId": "task_1",
            "projectId": "p1",
            "stageId": "st1",
            "testItem": "跌落测试",
            "time": "2026-06-03T10:01:00",
            "user": "张三/001",
            "flowStatus": "故障",
            "problemDescription": "不开机",
        }]
        conn = state_conn(data)

        module_result = server.sample_history.list_sample_history_page(conn, "sample_1", {"page": ["1"], "pageSize": ["10"]})
        result = server.list_sample_history_page(conn, "sample_1", {"page": ["1"], "pageSize": ["10"]})

        self.assertEqual(module_result, result)
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["task"]["id"], "task_1")
        self.assertEqual(item["projectName"], "项目A")
        self.assertEqual(item["stageName"], "EVT")
        self.assertTrue(item["faultMarked"])
        self.assertIn("不开机", item["problems"])
        self.assertEqual(item["resultPhotos"][0]["id"], "photo_1")
        self.assertIn("/api/samples/sample_1/photos/photo_1", item["resultPhotos"][0]["url"])

        with patched_server_db(conn):
            status, payload = call_handler_json("do_GET", "/api/samples/sample_1/history?page=1&pageSize=5")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["items"][0]["task"]["id"], "task_1")

    def test_import_bundle_sample_identity_conflict_respects_reassembled_flag(self):
        current = empty_state()
        current["sampleLibrary"]["categories"] = [{
            "id": "cat_current",
            "name": "主库池",
            "samples": [{
                "id": "sample_current",
                "sampleNo": "A001",
                "sn": "SN-DUP",
                "imei": "IMEI-A",
                "boardSn": "MB-DUP",
                "status": "闲置",
            }],
        }]
        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_incoming",
            "name": "导入池",
            "samples": [{
                "id": "sample_incoming",
                "sampleNo": "B001",
                "sn": "SN-DUP",
                "imei": "IMEI-B",
                "boardSn": "MB-B",
                "status": "闲置",
            }],
        }]

        with tempfile.TemporaryDirectory() as tmp:
            result = server._diff_import_bundle(current, incoming, {}, Path(tmp))
        conflicts = [c for c in result["conflicts"] if c["type"] == "sample_identity_conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["matchBy"], "sn")

        incoming_reassembled = copy.deepcopy(incoming)
        incoming_reassembled["sampleLibrary"]["categories"][0]["samples"][0]["isReassembled"] = True
        with tempfile.TemporaryDirectory() as tmp:
            result = server._diff_import_bundle(current, incoming_reassembled, {}, Path(tmp))
        self.assertFalse([c for c in result["conflicts"] if c["type"] == "sample_identity_conflict"])
        self.assertEqual(result["summary"]["samples"]["new"], 1)

    def test_import_bundle_sample_identity_conflict_checks_board_sn_and_allows_late_predecessor(self):
        current = empty_state()
        current["sampleLibrary"]["categories"] = [{
            "id": "cat_current",
            "name": "主库池",
            "samples": [{
                "id": "sample_current",
                "sampleNo": "A001",
                "sn": "SN-A",
                "imei": "IMEI-A",
                "boardSn": "MB-DUP",
                "status": "闲置",
            }],
        }]
        incoming = empty_state()
        incoming["sampleLibrary"]["categories"] = [{
            "id": "cat_incoming",
            "name": "导入池",
            "samples": [{
                "id": "sample_incoming",
                "sampleNo": "B001",
                "sn": "SN-B",
                "imei": "IMEI-B",
                "boardSn": "MB-DUP",
                "status": "闲置",
            }],
        }]

        with tempfile.TemporaryDirectory() as tmp:
            result = server._diff_import_bundle(current, incoming, {}, Path(tmp))
        conflicts = [c for c in result["conflicts"] if c["type"] == "sample_identity_conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["matchBy"], "boardSn")

        current_reassembled = copy.deepcopy(current)
        current_reassembled["sampleLibrary"]["categories"][0]["samples"][0]["isReassembled"] = True
        with tempfile.TemporaryDirectory() as tmp:
            result = server._diff_import_bundle(current_reassembled, incoming, {}, Path(tmp))
        self.assertFalse([c for c in result["conflicts"] if c["type"] == "sample_identity_conflict"])
        self.assertEqual(result["summary"]["samples"]["new"], 1)

    def test_bootstrap_state_uses_summaries_without_full_children(self):
        data = empty_state()
        data["currentProjectId"] = "p1"
        data["currentStageId"] = "st1"
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "code": "P-A",
            "owner": "张三/001",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "tasks": [{"id": "task1", "status": "待下发", "sampleIds": ["sample1"]}],
            }],
        }]
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [
                {"id": "sample1", "categoryId": "cat1", "sampleNo": "S1", "sn": "SN1", "status": "闲置"},
                {"id": "sample2", "categoryId": "cat1", "sampleNo": "S2", "sn": "SN2", "status": "测试中"},
            ],
        }]
        conn = state_conn(data)

        bootstrap, revision, _ = server.compose_bootstrap_state(conn)

        self.assertEqual(revision, 1)
        self.assertEqual(bootstrap["currentProjectId"], "p1")
        self.assertEqual(len(bootstrap["projects"]), 1)
        self.assertEqual(bootstrap["projects"][0]["stageCount"], 1)
        self.assertEqual(bootstrap["projects"][0]["taskCount"], 1)
        self.assertEqual(bootstrap["projects"][0]["stages"], [])
        self.assertTrue(bootstrap["projects"][0]["_summaryOnly"])
        self.assertEqual(bootstrap["sampleLibrary"]["categories"][0]["sampleCount"], 2)
        self.assertEqual(bootstrap["sampleLibrary"]["categories"][0]["samples"], [])
        self.assertTrue(bootstrap["bootstrapMode"])

    def test_load_project_detail_can_omit_or_include_tasks(self):
        data = empty_state()
        data["projects"] = [{
            "id": "p1",
            "name": "项目A",
            "stages": [{
                "id": "st1",
                "name": "阶段A",
                "skuNames": ["SKU1"],
                "progress": [{"id": "prog1", "testItem": "吞吐"}],
                "tasks": [{
                    "id": "task1",
                    "progressId": "prog1",
                    "status": "待下发",
                    "sampleIds": ["sample1"],
                    "logs": [{"id": "log1", "time": "2026-06-02T12:00:00+08:00", "action": "新增", "user": "管理员"}],
                }],
            }],
        }]
        conn = state_conn(data)

        summary = server.project_queries.list_project_summary(conn)
        library = server.project_queries.load_project_library(conn)
        slim = server.project_queries.load_project_detail(conn, "p1", include_tasks=False)
        full = server.project_queries.load_project_detail(conn, "p1", include_tasks=True)

        self.assertEqual(summary[0]["stageCount"], 1)
        self.assertEqual(summary[0]["taskCount"], 1)
        self.assertEqual(library[0]["stages"][0]["tasks"][0]["logs"][0]["id"], "log1")
        self.assertEqual(slim["stages"][0]["progress"][0]["id"], "prog1")
        self.assertEqual(slim["stages"][0]["tasks"], [])
        self.assertEqual(full["stages"][0]["tasks"][0]["id"], "task1")
        self.assertEqual(full["stages"][0]["tasks"][0]["logs"][0]["id"], "log1")

        self.assertEqual(server.load_project_detail(conn, "p1", include_tasks=True), full)

    def test_load_sample_category_detail_returns_samples_without_photos_by_default(self):
        data = empty_state()
        data["sampleLibrary"]["categories"] = [{
            "id": "cat1",
            "name": "样机池A",
            "samples": [
                {"id": "sample1", "categoryId": "cat1", "sampleNo": "S1", "sn": "SN1", "status": "闲置"},
                {"id": "sample2", "categoryId": "cat1", "sampleNo": "S2", "sn": "SN2", "status": "测试中"},
            ],
        }]
        conn = state_conn(data)

        category = server.load_sample_category_detail(conn, "cat1")

        self.assertEqual(category["sampleCount"], 2)
        self.assertTrue(category["samplesLoaded"])
        self.assertEqual([s["id"] for s in category["samples"]], ["sample1", "sample2"])
        self.assertFalse(category["samples"][0]["photosLoaded"])


if __name__ == "__main__":
    unittest.main()
