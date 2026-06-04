import argparse
import io
import json
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import server  # noqa: E402
from perf_benchmark import seed_database  # noqa: E402


class ExplodingLock:
    def __enter__(self):
        raise AssertionError("HTTP concurrency benchmark path must not enter DB_LOCK")

    def __exit__(self, exc_type, exc, tb):
        return False


class QuietHandler(server.Handler):
    def log_message(self, fmt, *args):
        return


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def timed_request(
    base_url,
    path,
    *,
    method="GET",
    body=None,
    headers=None,
    expect_zip=False,
    allow_statuses=None,
    require_ok=True,
):
    start = time.perf_counter()
    allow_statuses = set(allow_statuses or [])
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        if exc.code not in allow_statuses:
            raise RuntimeError(f"{path} returned HTTP {exc.code}: {body[:200]!r}") from exc
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        elapsed_ms = (time.perf_counter() - start) * 1000
        payload = json.loads(body.decode("utf-8"))
        return elapsed_ms, len(body), content_type, payload
    elapsed_ms = (time.perf_counter() - start) * 1000
    if status != 200:
        raise RuntimeError(f"{path} returned HTTP {status}")
    if expect_zip:
        if not body.startswith(b"PK"):
            raise RuntimeError(f"{path} did not return a ZIP payload")
    payload = None
    if not expect_zip:
        payload = json.loads(body.decode("utf-8"))
        if require_ok and payload.get("ok") is not True:
            raise RuntimeError(f"{path} returned ok=false: {payload}")
    return elapsed_ms, len(body), content_type, payload


def measure_parallel(label, operations, *, workers):
    latencies = []
    sizes = []
    errors = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(op) for op in operations]
        for future in as_completed(futures):
            try:
                latency_ms, size, _, _ = future.result()
                latencies.append(latency_ms)
                sizes.append(size)
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
        "bytes_total": sum(sizes),
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "p50": round(statistics.median(latencies), 2) if latencies else 0,
            "p95": round(percentile(latencies, 0.95), 2),
            "max": round(max(latencies), 2) if latencies else 0,
        },
    }


def build_read_operations(base_url, read_requests):
    endpoints = [
        "/api/bootstrap",
        "/api/projects/summary",
        "/api/sample-categories",
        "/api/stages/stage_000_00/tasks?page=1&pageSize=100&flowStatus=%E8%BF%9B%E8%A1%8C%E4%B8%AD",
        "/api/sample-categories/cat_000/samples?page=1&pageSize=100&status=%E9%97%B2%E7%BD%AE",
        "/api/sample-destroy-impact?sampleId=sample_000000",
    ]
    operations = []
    for idx in range(read_requests):
        path = endpoints[idx % len(endpoints)]
        operations.append(lambda path=path: timed_request(base_url, path))
    return operations


def build_export_operations(base_url, export_requests):
    return [
        lambda: timed_request(base_url, "/api/export-bundle", expect_zip=True)
        for _ in range(export_requests)
    ]


def multipart_body(fields=None, files=None, boundary="tcv7_http_benchmark"):
    parts = []
    for name, value in (fields or {}).items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for field, filename, content_type, content in (files or []):
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
            .encode("utf-8")
        )
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, b"".join(parts)


def photo_upload_delete_request(base_url, sample_id, idx):
    started = time.perf_counter()
    boundary = f"tcv7_http_photo_{idx}"
    headers, body = multipart_body(
        fields={"remark": "HTTP 并发压测照片上传"},
        files=[("photos", f"bench_{idx}.jpg", "image/jpeg", f"bench-photo-{idx}".encode("utf-8"))],
        boundary=boundary,
    )
    upload_ms, upload_size, _, payload = timed_request(
        base_url,
        f"/api/samples/{sample_id}/photos",
        method="POST",
        body=body,
        headers=headers,
    )
    uploaded = payload.get("uploaded") or []
    if not uploaded:
        raise RuntimeError(f"photo upload for {sample_id} returned no uploaded metadata")
    photo_id = uploaded[0].get("id")
    delete_ms, delete_size, _, _ = timed_request(
        base_url,
        f"/api/samples/{sample_id}/photos/{photo_id}",
        method="DELETE",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return elapsed_ms, upload_size + delete_size, "application/json", {
        "upload_ms": upload_ms,
        "delete_ms": delete_ms,
    }


def build_photo_operations(base_url, photo_requests, sample_count):
    sample_slots = max(1, min(sample_count, max(1, photo_requests), 24))
    operations = []
    for idx in range(photo_requests):
        sample_id = f"sample_{idx % sample_slots:06d}"
        operations.append(lambda sample_id=sample_id, idx=idx: photo_upload_delete_request(base_url, sample_id, idx))
    return operations


def build_import_zip(idx):
    incoming = server.empty_data()
    pid = f"import_http_project_{idx:04d}"
    incoming["projects"] = [{
        "id": pid,
        "name": f"HTTP 并发导入项目 {idx}",
        "code": f"HTTP-IMP-{idx:04d}",
        "owner": "benchmark/000",
        "members": [],
        "locations": [],
        "stages": [],
    }]
    manifest = {
        "format": "testchamber-export-bundle-v1",
        "appVersion": "V7",
        "exportedAt": server.now_iso(),
        "exportId": f"http_import_{idx:04d}",
        "sourceDeploymentId": "deploy_http_benchmark",
        "sourceName": "HTTP 并发压测",
        "revision": idx + 1,
        "projectCount": 1,
        "sampleCount": 0,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("state.json", json.dumps(incoming, ensure_ascii=False))
        zf.writestr("checksums.json", "{}")
    return buf.getvalue()


def import_preview_commit_request(base_url, idx, max_attempts=4):
    started = time.perf_counter()
    total_size = 0
    for attempt in range(max_attempts):
        bundle = build_import_zip(idx * 100 + attempt)
        headers, body = multipart_body(
            files=[("bundle", f"import_{idx}_{attempt}.zip", "application/zip", bundle)],
            boundary=f"tcv7_http_import_{idx}_{attempt}",
        )
        preview_ms, preview_size, _, preview = timed_request(
            base_url,
            "/api/import-bundle/preview",
            method="POST",
            body=body,
            headers=headers,
        )
        total_size += preview_size
        preview_id = preview.get("previewId")
        commit_body = json.dumps({"previewId": preview_id, "decisions": {}}, ensure_ascii=False).encode("utf-8")
        commit_ms, commit_size, _, commit = timed_request(
            base_url,
            "/api/import-bundle/commit",
            method="POST",
            body=commit_body,
            headers={"Content-Type": "application/json"},
            allow_statuses={409},
            require_ok=False,
        )
        total_size += commit_size
        if commit.get("ok") is True:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, total_size, "application/json", {
                "attempts": attempt + 1,
                "preview_ms": preview_ms,
                "commit_ms": commit_ms,
            }
        is_revision_conflict = (
            commit.get("error_code") == "IMPORT_REVISION_CONFLICT"
            or (commit.get("status") == 409 and "revision" in str(commit.get("error") or "").lower())
            or (commit.get("status") == 409 and "revision" in str(commit).lower())
        )
        if not is_revision_conflict:
            raise RuntimeError(f"import commit failed: {commit}")
    raise RuntimeError("import commit kept hitting revision conflicts")


def build_import_operations(base_url, import_requests):
    return [
        lambda idx=idx: import_preview_commit_request(base_url, idx)
        for idx in range(import_requests)
    ]


def main():
    parser = argparse.ArgumentParser(description="Temporary ThreadingHTTPServer concurrency benchmark for TestChamber V7.")
    parser.add_argument("--projects", type=int, default=3)
    parser.add_argument("--stages-per-project", type=int, default=3)
    parser.add_argument("--tasks", type=int, default=3000)
    parser.add_argument("--categories", type=int, default=4)
    parser.add_argument("--samples", type=int, default=1200)
    parser.add_argument("--photos-per-sample", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--read-requests", type=int, default=60)
    parser.add_argument("--export-requests", type=int, default=4)
    parser.add_argument("--photo-requests", type=int, default=6)
    parser.add_argument("--import-requests", type=int, default=2)
    args = parser.parse_args()

    old_paths = {
        "DATA_DIR": server.DATA_DIR,
        "SAMPLE_DATA_DIR": server.SAMPLE_DATA_DIR,
        "BACKUP_DIR": server.BACKUP_DIR,
        "IMPORT_PREVIEW_DIR": server.IMPORT_PREVIEW_DIR,
        "EXPORT_DIR": server.EXPORT_DIR,
        "DB_PATH": server.DB_PATH,
        "DEPLOYMENT_FILE": server.DEPLOYMENT_FILE,
        "_RUNTIME_PATHS": server._RUNTIME_PATHS,
    }
    old_lock = server.DB_LOCK

    with tempfile.TemporaryDirectory(prefix="tcv7_http_concurrency_") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        db_path = data_dir / "testchamber_http.sqlite"
        data_dir.mkdir(parents=True, exist_ok=True)
        server.DATA_DIR = data_dir
        server.SAMPLE_DATA_DIR = data_dir / "samples"
        server.BACKUP_DIR = data_dir / "backups"
        server.IMPORT_PREVIEW_DIR = data_dir / "import-previews"
        server.EXPORT_DIR = data_dir / "exports"
        server.DB_PATH = db_path
        server.DEPLOYMENT_FILE = data_dir / "deployment.json"
        server._RUNTIME_PATHS = server.runtime_paths.build_runtime_paths(data_dir)
        server.ensure_dirs()

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

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server.DB_LOCK = ExplodingLock()
        try:
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
            read_ops = build_read_operations(base_url, args.read_requests)
            export_ops = build_export_operations(base_url, args.export_requests)
            photo_ops = build_photo_operations(base_url, args.photo_requests, args.samples)
            import_ops = build_import_operations(base_url, args.import_requests)
            mixed_ops = []
            reads = list(read_ops)
            exports = list(export_ops)
            photos = list(photo_ops)
            imports = list(import_ops)
            while reads or exports or photos or imports:
                for _ in range(5):
                    if reads:
                        mixed_ops.append(reads.pop(0))
                if exports:
                    mixed_ops.append(exports.pop(0))
                if photos:
                    mixed_ops.append(photos.pop(0))
                if imports:
                    mixed_ops.append(imports.pop(0))

            report = {
                "base_url": base_url,
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
                    measure_parallel("http-read-pages-and-summaries", read_ops, workers=max(1, args.workers)),
                    measure_parallel("http-photo-upload-delete", photo_ops, workers=max(1, args.workers)),
                    measure_parallel("http-import-preview-commit", import_ops, workers=max(1, args.workers)),
                    measure_parallel("http-read-plus-export-mix", mixed_ops, workers=max(1, args.workers)),
                ],
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if any(item["error_count"] for item in report["benchmarks"]):
                return 1
            return 0
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            server.DB_LOCK = old_lock
            server.DATA_DIR = old_paths["DATA_DIR"]
            server.SAMPLE_DATA_DIR = old_paths["SAMPLE_DATA_DIR"]
            server.BACKUP_DIR = old_paths["BACKUP_DIR"]
            server.IMPORT_PREVIEW_DIR = old_paths["IMPORT_PREVIEW_DIR"]
            server.EXPORT_DIR = old_paths["EXPORT_DIR"]
            server.DB_PATH = old_paths["DB_PATH"]
            server.DEPLOYMENT_FILE = old_paths["DEPLOYMENT_FILE"]
            server._RUNTIME_PATHS = old_paths["_RUNTIME_PATHS"]


if __name__ == "__main__":
    raise SystemExit(main())
