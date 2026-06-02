import copy
import sqlite3
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
