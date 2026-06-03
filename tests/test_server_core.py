import copy
import json
import sqlite3
import sys
import tempfile
import unittest
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


class ServerCoreTests(unittest.TestCase):
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
        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        task = state["projects"][0]["stages"][0]["tasks"][0]
        sample = state["sampleLibrary"]["categories"][0]["samples"][0]
        self.assertEqual(task["status"], "进行中")
        self.assertEqual(task["logs"][0]["id"], "log1")
        self.assertEqual(sample["status"], "测试中")
        self.assertEqual(state["sampleLibrary"]["logs"][0]["id"], "event1")

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

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["sampleLibrary"]["categories"][0]["samples"], [])

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

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 2)
        self.assertEqual(state["sampleLibrary"]["categories"], [])
        task = state["projects"][0]["stages"][0]["tasks"][0]
        self.assertEqual(task["status"], "异常终止")
        self.assertEqual(task["sampleIds"], [])
        self.assertEqual(task["logs"][0]["id"], "log_destroy_pool")

    def test_commit_project_mutation_creates_and_deletes_project(self):
        data = empty_state()
        conn = state_conn(data)

        with patched_server_db(conn):
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
            state, revision, _ = server.compose_state(conn)
            self.assertEqual(revision, 2)
            self.assertEqual(state["projects"][0]["name"], "新项目")
            self.assertEqual(state["projects"][0]["locations"], ["实验室"])

            ok, result = server.commit_project_mutation({
                "projectId": "p_new",
                "deleteProject": True,
            }, "127.0.0.1")
            self.assertTrue(ok, result)

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["projects"], [])

    def test_commit_stage_mutation_creates_and_deletes_stage(self):
        data = empty_state()
        data["projects"] = [{"id": "p1", "name": "项目A", "stages": []}]
        conn = state_conn(data)

        with patched_server_db(conn):
            ok, result = server.commit_stage_mutation({
                "projectId": "p1",
                "stageId": "st_new",
                "createIfMissing": True,
                "project": {"id": "p1", "name": "项目A"},
                "stages": [{"id": "st_new", "projectId": "p1", "name": "阶段1", "skuNames": ["SKU1"]}],
                "stage": {"id": "st_new", "projectId": "p1", "name": "阶段1", "skuNames": ["SKU1"], "progress": [], "tasks": []},
            }, "127.0.0.1")
            self.assertTrue(ok, result)
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

        state, revision, _ = server.compose_state(conn)
        self.assertEqual(revision, 3)
        self.assertEqual(state["projects"][0]["stages"], [])

    def test_commit_sample_category_mutation_creates_category_and_samples(self):
        data = empty_state()
        conn = state_conn(data)

        with patched_server_db(conn):
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
