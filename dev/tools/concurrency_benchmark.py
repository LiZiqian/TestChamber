import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from backend import server  # noqa: E402
from perf_benchmark import seed_database  # noqa: E402


class ExplodingLock:
    def __enter__(self):
        raise AssertionError("runtime concurrency benchmark path must not enter DB_LOCK")

    def __exit__(self, exc_type, exc, tb):
        return False


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def measure_parallel(label, operations, *, workers):
    latencies = []
    errors = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(op) for op in operations]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception as exc:  # pragma: no cover - surfaced in JSON report
                errors.append(repr(exc))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "label": label,
        "operations": len(operations),
        "workers": workers,
        "elapsed_ms": round(elapsed_ms, 2),
        "throughput_ops_sec": round((len(operations) / elapsed_ms) * 1000, 2) if elapsed_ms else 0,
        "error_count": len(errors),
        "errors": errors[:5],
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "p50": round(statistics.median(latencies), 2) if latencies else 0,
            "p95": round(percentile(latencies, 0.95), 2),
            "max": round(max(latencies), 2) if latencies else 0,
        },
    }


def timed(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def read_bootstrap():
    return timed(lambda: _with_conn(lambda conn: server.compose_bootstrap_state(conn)))


def read_task_page():
    return timed(lambda: _with_conn(lambda conn: server.list_stage_tasks_page(
        conn,
        "stage_000_00",
        {"page": ["1"], "pageSize": ["100"], "flowStatus": ["进行中"]},
    )))


def read_sample_page():
    return timed(lambda: _with_conn(lambda conn: server.list_samples_page(
        conn,
        "cat_000",
        {"page": ["1"], "pageSize": ["100"], "status": ["闲置"]},
    )))


def read_sample_destroy_impact_scope():
    return timed(lambda: _with_conn(lambda conn: server.list_sample_destroy_impact_scope(
        conn,
        {"sampleId": ["sample_000000"]},
    )))


def metadata_write():
    def write():
        with server.write_db_connection() as conn:
            conn.execute(
                "UPDATE app_state SET revision = revision + 1, updated_at = ? WHERE id = 1",
                (server.now_iso(),),
            )
    return timed(write)


def _with_conn(fn):
    with server.connect_db() as conn:
        return fn(conn)


def build_operations(read_requests, write_requests):
    reads = []
    read_fns = [read_bootstrap, read_task_page, read_sample_page, read_sample_destroy_impact_scope]
    for idx in range(read_requests):
        reads.append(read_fns[idx % len(read_fns)])
    writes = [metadata_write for _ in range(write_requests)]
    mixed = []
    while reads or writes:
        for _ in range(4):
            if reads:
                mixed.append(reads.pop(0))
        if writes:
            mixed.append(writes.pop(0))
    return mixed


def main():
    parser = argparse.ArgumentParser(description="Temporary SQLite concurrency benchmark for TestChamber V7.")
    parser.add_argument("--projects", type=int, default=4)
    parser.add_argument("--stages-per-project", type=int, default=3)
    parser.add_argument("--tasks", type=int, default=10000)
    parser.add_argument("--categories", type=int, default=6)
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--photos-per-sample", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--read-requests", type=int, default=90)
    parser.add_argument("--write-requests", type=int, default=15)
    args = parser.parse_args()

    old_db_path = server.DB_PATH
    old_lock = server.DB_LOCK
    with tempfile.TemporaryDirectory(prefix="tcv7_concurrency_") as tmp:
        db_path = Path(tmp) / "testchamber_concurrency.sqlite"
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            server.ensure_schema(conn)
            seed_started = time.perf_counter()
            seed_database(
                conn,
                projects=args.projects,
                stages_per_project=args.stages_per_project,
                tasks=args.tasks,
                categories=args.categories,
                samples=args.samples,
                photos_per_sample=args.photos_per_sample,
            )
            seed_ms = round((time.perf_counter() - seed_started) * 1000, 2)
        finally:
            conn.close()

        server.DB_PATH = db_path
        server.DB_LOCK = ExplodingLock()
        try:
            read_ops = build_operations(args.read_requests, 0)
            mixed_ops = build_operations(args.read_requests, args.write_requests)
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
                },
                "benchmarks": [
                    measure_parallel("concurrent-read-pages-and-summaries", read_ops, workers=max(1, args.workers)),
                    measure_parallel("read-write-mix-sqlite-transactions", mixed_ops, workers=max(1, args.workers)),
                ],
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if any(item["error_count"] for item in report["benchmarks"]):
                return 1
            return 0
        finally:
            server.DB_PATH = old_db_path
            server.DB_LOCK = old_lock


if __name__ == "__main__":
    raise SystemExit(main())
