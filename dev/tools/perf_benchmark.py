import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import server  # noqa: E402


STATUSES = ["待下发", "进行中", "阻塞中", "正常完成", "异常终止"]
SAMPLE_STATUSES = ["闲置", "在位等待", "测试中", "取走分析", "已退库"]


def batched(iterable, size=5000):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def insert_many(conn, sql, rows, *, batch_size=5000):
    for batch in batched(rows, batch_size):
        conn.executemany(sql, batch)


def seed_database(conn, *, projects, stages_per_project, tasks, categories, samples, photos_per_sample):
    ts = "2026-06-02T00:00:00"
    state = server.empty_data()
    state["currentProjectId"] = "project_000"
    state["currentStageId"] = "stage_000_00"
    conn.execute(
        "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, 1, ?)",
        (server.json_dumps(server.split_state_for_storage(state)), ts),
    )

    project_rows = []
    stage_rows = []
    stage_ids = []
    for p in range(projects):
        pid = f"project_{p:03d}"
        project_rows.append((
            pid,
            f"项目{p + 1}",
            f"P{p + 1:03d}",
            f"负责人{p % 8}/E{p:04d}",
            p,
            server.json_dumps({"id": pid, "name": f"项目{p + 1}", "members": [], "locations": ["实验室"]}),
            ts,
            ts,
            None,
        ))
        for s in range(stages_per_project):
            sid = f"stage_{p:03d}_{s:02d}"
            progress = [
                {
                    "id": f"prog_{p:03d}_{s:02d}_{i:03d}",
                    "category": f"类别{i % 12}",
                    "testItem": f"用例{i % 240}",
                    "skuIndex": i % 4,
                    "sampleSize": 2,
                }
                for i in range(240)
            ]
            stage_ids.append((pid, sid))
            stage_rows.append((
                sid,
                pid,
                f"阶段{s + 1}",
                s,
                server.json_dumps({"id": sid, "projectId": pid, "name": f"阶段{s + 1}", "progress": progress}),
                ts,
                ts,
                None,
            ))

    conn.executemany(
        """
        INSERT INTO project_records
        (id, name, code, owner, sort_order, data_json, created_at, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        project_rows,
    )
    conn.executemany(
        """
        INSERT INTO project_stages
        (id, project_id, name, sort_order, data_json, created_at, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        stage_rows,
    )

    def task_rows():
        stage_count = len(stage_ids)
        for i in range(tasks):
            pid, sid = stage_ids[i % stage_count]
            stage_slot = i // stage_count
            status = STATUSES[stage_slot % len(STATUSES)]
            flow_status = server.task_flow_status({"status": status, "completed": status == "正常完成"})
            task = {
                "id": f"task_{i:06d}",
                "projectId": pid,
                "stageId": sid,
                "progressId": f"prog_{pid[-3:]}_{sid[-2:]}_{stage_slot % 240:03d}",
                "category": f"类别{stage_slot % 12}",
                "testItem": f"用例{stage_slot % 240}",
                "skuIndex": stage_slot % 4,
                "status": status,
                "completed": status == "正常完成",
                "owner": f"执行人{stage_slot % 24}/E{stage_slot % 24:04d}",
                "issueRecord": {"dtsNo": f"DTS-{stage_slot % 5000:05d}", "issueNote": f"备注{stage_slot % 200}"},
                "resultSummary": f"结果摘要{stage_slot % 300}",
                "sampleIds": [],
            }
            yield (
                task["id"],
                pid,
                sid,
                task["progressId"],
                task["category"],
                task["testItem"],
                task["skuIndex"],
                status,
                flow_status,
                task["owner"],
                "[]",
                server.json_dumps(task),
                ts,
                ts,
                ts if task["completed"] else "",
                None,
            )

    insert_many(
        conn,
        """
        INSERT INTO project_tasks
        (id, project_id, stage_id, progress_id, category, test_item, sku_index, status, flow_status, owner,
         sample_ids_json, data_json, created_at, updated_at, completed_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        task_rows(),
    )

    category_rows = []
    for c in range(categories):
        cid = f"cat_{c:03d}"
        category_rows.append((
            cid,
            f"样机池{c + 1}",
            "压测样机池",
            c,
            server.json_dumps({"id": cid, "name": f"样机池{c + 1}", "description": "压测样机池"}),
            ts,
            ts,
            None,
        ))
    conn.executemany(
        """
        INSERT INTO sample_categories
        (id, name, description, sort_order, data_json, created_at, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        category_rows,
    )

    def sample_rows():
        for i in range(samples):
            cid = f"cat_{i % categories:03d}"
            category_slot = i // categories
            has_problem = 1 if i % 23 == 0 else 0
            status = SAMPLE_STATUSES[category_slot % len(SAMPLE_STATUSES)]
            effective_status = "故障" if has_problem else status
            sample = {
                "id": f"sample_{i:06d}",
                "categoryId": cid,
                "sampleNo": f"TC-{i:06d}",
                "sn": f"SN{i:08d}",
                "imei": f"86{i:013d}"[-15:],
                "boardSn": f"BD{i:07d}",
                "status": status,
                "location": f"库位{category_slot % 80}",
                "owner": f"保管人{category_slot % 20}/S{category_slot % 20:04d}",
                "borrower": f"借用人{category_slot % 18}/B{category_slot % 18:04d}" if category_slot % 7 == 0 else "",
                "problemRecords": [{"id": f"prob_{i}", "description": "不开机"}] if has_problem else [],
            }
            yield (
                sample["id"],
                cid,
                sample["sampleNo"],
                sample["sn"],
                sample["imei"],
                status,
                has_problem,
                effective_status,
                sample["location"],
                sample["owner"],
                sample["borrower"],
                server.json_dumps(sample),
                ts,
                ts,
                None,
            )

    insert_many(
        conn,
        """
        INSERT INTO sample_records
        (id, category_id, sample_no, sn, imei, status, has_problem, effective_status, location, owner, borrower,
         data_json, created_at, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        sample_rows(),
    )

    if photos_per_sample > 0:
        def asset_rows():
            for i in range(samples):
                sid = f"sample_{i:06d}"
                for p in range(photos_per_sample):
                    aid = f"photo_{i:06d}_{p:02d}"
                    yield (
                        aid,
                        sid,
                        "photo",
                        f"{aid}.jpg",
                        f"{aid}.jpg",
                        f"samples/{sid}/photos/{aid}.jpg",
                        "image/jpeg",
                        128_000,
                        ts,
                        "",
                        None,
                    )

        insert_many(
            conn,
            """
            INSERT INTO sample_assets
            (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            asset_rows(),
            batch_size=10000,
        )

    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()


def measure(label, fn, *, repeat=5):
    fn()
    values = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        values.append((time.perf_counter() - start) * 1000)
    return {
        "label": label,
        "min_ms": round(min(values), 2),
        "median_ms": round(statistics.median(values), 2),
        "max_ms": round(max(values), 2),
        "last_size": len(json.dumps(result, ensure_ascii=False)) if result is not None else 0,
    }


def benchmark(conn, *, repeat):
    first_stage = "stage_000_00"
    first_category = "cat_000"
    cases = [
        ("bootstrap", lambda: server.compose_bootstrap_state(conn)[0]),
        ("project-summary", lambda: server.list_project_summary(conn)),
        ("sample-category-summary", lambda: server.list_sample_categories_summary(conn)),
        ("project-detail-no-tasks", lambda: server.load_project_detail(conn, "project_000", include_tasks=False)),
        ("project-detail-with-tasks", lambda: server.load_project_detail(conn, "project_000", include_tasks=True)),
        ("tasks-page-default", lambda: server.list_stage_tasks_page(conn, first_stage, {"page": ["1"], "pageSize": ["100"]})),
        ("tasks-page-flow-status", lambda: server.list_stage_tasks_page(conn, first_stage, {"page": ["1"], "pageSize": ["100"], "flowStatus": ["进行中"]})),
        ("tasks-page-sku-owner", lambda: server.list_stage_tasks_page(conn, first_stage, {"page": ["1"], "pageSize": ["100"], "sku": ["2"], "ownerName": ["执行人2"]})),
        ("tasks-page-deep-result-keyword", lambda: server.list_stage_tasks_page(conn, first_stage, {"page": ["1"], "pageSize": ["100"], "resultKeyword": ["结果摘要1"]})),
        ("samples-page-default", lambda: server.list_samples_page(conn, first_category, {"page": ["1"], "pageSize": ["100"]})),
        ("samples-page-status", lambda: server.list_samples_page(conn, first_category, {"page": ["1"], "pageSize": ["100"], "status": ["故障"]})),
        ("samples-page-owner", lambda: server.list_samples_page(conn, first_category, {"page": ["1"], "pageSize": ["100"], "owner": ["保管人1"]})),
        ("samples-page-deep-keyword", lambda: server.list_samples_page(conn, first_category, {"page": ["1"], "pageSize": ["100"], "keyword": ["SN0001"]})),
    ]
    return [measure(label, fn, repeat=repeat) for label, fn in cases]


def main():
    parser = argparse.ArgumentParser(description="TestChamber V7 temporary SQLite performance benchmark.")
    parser.add_argument("--projects", type=int, default=20)
    parser.add_argument("--stages-per-project", type=int, default=5)
    parser.add_argument("--tasks", type=int, default=100000)
    parser.add_argument("--categories", type=int, default=30)
    parser.add_argument("--samples", type=int, default=70000)
    parser.add_argument("--photos-per-sample", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--keep-db", type=Path, default=None, help="Optional path to keep the generated SQLite DB.")
    args = parser.parse_args()

    if args.keep_db:
        db_path = args.keep_db
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(db_path)
        temp_dir = None
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="tcv7_perf_")
        db_path = Path(temp_dir.name) / "testchamber_perf.sqlite"
        conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        server.ensure_schema(conn)
        started = time.perf_counter()
        seed_database(
            conn,
            projects=args.projects,
            stages_per_project=args.stages_per_project,
            tasks=args.tasks,
            categories=args.categories,
            samples=args.samples,
            photos_per_sample=args.photos_per_sample,
        )
        seed_ms = round((time.perf_counter() - started) * 1000, 2)
        report = {
            "db_path": str(db_path),
            "seed_ms": seed_ms,
            "scale": {
                "projects": args.projects,
                "stages_per_project": args.stages_per_project,
                "tasks": args.tasks,
                "categories": args.categories,
                "samples": args.samples,
                "photos_per_sample": args.photos_per_sample,
                "photo_assets": args.samples * args.photos_per_sample,
            },
            "benchmarks": benchmark(conn, repeat=max(1, args.repeat)),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        conn.close()
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    main()
