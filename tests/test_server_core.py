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
    try:
        server.connect_db = lambda: conn
        server.DB_LOCK = NoopLock()
        yield
    finally:
        server.connect_db = old_connect
        server.DB_LOCK = old_lock


@contextmanager
def patched_server_data_dirs(root):
    old_data_dir = server.DATA_DIR
    old_sample_dir = server.SAMPLE_DATA_DIR
    old_backup_dir = server.BACKUP_DIR
    try:
        server.DATA_DIR = Path(root)
        server.SAMPLE_DATA_DIR = Path(root) / "samples"
        server.BACKUP_DIR = Path(root) / "backups"
        server.ensure_dirs()
        yield
    finally:
        server.DATA_DIR = old_data_dir
        server.SAMPLE_DATA_DIR = old_sample_dir
        server.BACKUP_DIR = old_backup_dir


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


class ServerCoreTests(unittest.TestCase):
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

            def fake_get_state(*, compact=False):
                calls.append(compact)
                return empty_state(), 12, "2026-06-04T00:00:00+08:00"

            server.get_state = fake_get_state
            headers, body = make_multipart(files=[
                ("file", "bundle.zip", "application/zip", bundle.getvalue()),
            ])

            result = server.analyze_import_bundle(headers, body)

            self.assertEqual(calls, [True])
            self.assertEqual(result["source"]["revision"], 1)
            entry = server._IMPORT_PREVIEWS[result["previewId"]]
            self.assertNotIn("_incoming", entry)
            self.assertNotIn("result", entry)
            self.assertTrue(Path(entry["_payload_path"]).is_file())
            incoming_payload, result_payload = server._load_import_preview_payload(entry)
            self.assertEqual(incoming_payload.get("version"), "V7")
            self.assertEqual(result_payload.get("previewId"), result["previewId"])
        finally:
            server.get_state = old_get_state
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
        with patched_server_db(conn):
            tmp_path, filename = server.build_export_bundle_file()
        try:
            self.assertTrue(tmp_path.is_file())
            self.assertTrue(filename.startswith("testchamber_export_"))
            with server.zipfile.ZipFile(tmp_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("state.json", names)
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                self.assertEqual(manifest["format"], "testchamber-export-bundle-v1")
                self.assertEqual(manifest["projectCount"], 1)
        finally:
            tmp_path.unlink(missing_ok=True)

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

        old_connect = server.connect_db
        old_lock = server.DB_LOCK
        class NoopLock:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False

        try:
            server.connect_db = lambda: conn
            server.DB_LOCK = NoopLock()
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
        finally:
            server.connect_db = old_connect
            server.DB_LOCK = old_lock

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

        result = server.list_sample_history_page(conn, "sample_1", {"page": ["1"], "pageSize": ["10"]})

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

        slim = server.load_project_detail(conn, "p1", include_tasks=False)
        full = server.load_project_detail(conn, "p1", include_tasks=True)

        self.assertEqual(slim["stages"][0]["progress"][0]["id"], "prog1")
        self.assertEqual(slim["stages"][0]["tasks"], [])
        self.assertEqual(full["stages"][0]["tasks"][0]["id"], "task1")
        self.assertEqual(full["stages"][0]["tasks"][0]["logs"][0]["id"], "log1")

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
