"""Test import/export bundle — comprehensive P0 safety coverage"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, ".")
from server import *
import server as _server

# Ensure clean state for test session
_TEST_TMP = tempfile.TemporaryDirectory(prefix="tcv7_import_tests_")
DATA_DIR = Path(_TEST_TMP.name) / "data"
SAMPLE_DATA_DIR = DATA_DIR / "samples"
DB_PATH = DATA_DIR / "testchamber.sqlite"
DEPLOYMENT_FILE = DATA_DIR / "deployment.json"
_server.DATA_DIR = DATA_DIR
_server.SAMPLE_DATA_DIR = SAMPLE_DATA_DIR
_server.DB_PATH = DB_PATH
_server.DEPLOYMENT_FILE = DEPLOYMENT_FILE
ensure_dirs()

_passed = 0
_failed = 0


def _assert(cond, msg=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✅ {msg}" if msg else "  ✅")
    else:
        _failed += 1
        print(f"  ❌ FAIL: {msg}" if msg else "  ❌ FAIL")


def _build_zip(incoming_data: dict, manifest: dict = None, extra_files: dict = None) -> bytes:
    """Build a test import zip bundle"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest is None:
            manifest = {
                "format": "testchamber-export-bundle-v1", "appVersion": "V7",
                "exportedAt": now_iso(), "exportId": "test_001",
                "sourceDeploymentId": "deploy_test_001", "sourceName": "测试机",
                "revision": 100, "projectCount": 1, "sampleCount": 1,
            }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("state.json", json.dumps(incoming_data, ensure_ascii=False, indent=2))
        zf.writestr("checksums.json", json.dumps({}, ensure_ascii=False))
        if extra_files:
            for path, content in extra_files.items():
                zf.writestr(path, content)
    return buf.getvalue()


def _make_multipart(zip_bytes: bytes) -> tuple:
    """Build multipart/form-data body and headers for a zip file"""
    boundary = "----TestBoundary789"
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="bundle"; filename="import.zip"\r\n'
        f'Content-Type: application/zip\r\n'
        f'\r\n'
    ).encode() + zip_bytes + f'\r\n--{boundary}--\r\n'.encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return headers, body


def _analyze(zip_bytes: bytes) -> dict:
    """Shorthand: build multipart → analyze_import_bundle"""
    headers, body = _make_multipart(zip_bytes)
    return analyze_import_bundle(headers, body)


def _setup_main_data(projects=None, sample_categories=None):
    """Set up clean DB with given data and return state+rev"""
    init_db()
    state, rev, _ = get_state()
    if projects is not None:
        state["projects"] = projects
    if sample_categories is not None:
        state["sampleLibrary"]["categories"] = sample_categories
    ok, resp = save_state(state, rev, "test-setup", remark="test", user="test")
    return get_state()


# ============================================================
# Test 1: zip-slip rejection
# ============================================================
print("\n1. zip-slip rejection")
init_db()

malicious_paths = [
    "../evil.txt",
    "..\\evil.txt",
    "/etc/passwd",
    "C:\\Windows\\evil.dll",
    "D:/evil.txt",
]
for bad_path in malicious_paths:
    try:
        zbytes = _build_zip({"version": "V7", "projects": [], "sampleLibrary": {"categories": []}},
                           extra_files={bad_path: "malicious content"})
        _analyze(zbytes)
        _assert(False, f"Should reject path: {bad_path}")
    except ValueError as e:
        _assert(True, f"Rejects {bad_path}: {e}")

# Also test: non-whitelisted file
zbytes = _build_zip({"version": "V7", "projects": [], "sampleLibrary": {"categories": []}},
                    extra_files={"random_file.txt": "test"})
try:
    _analyze(zbytes)
    _assert(False, "Should reject non-whitelisted file")
except ValueError as e:
    _assert("不允许" in str(e) or "allow" in str(e).lower(), f"Rejects non-whitelisted: {e}")

# ============================================================
# Test 2: Photo export includes files (relativePath-based)
# ============================================================
print("\n2. Photo export with relativePath")

init_db()
# Create a sample with photo files on disk
sample_id = "sample_photos_test"
photo_id = "photo_test_001"
SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
photo_dir = SAMPLE_DATA_DIR / sample_id / "photos"
photo_dir.mkdir(parents=True, exist_ok=True)

# Write a test photo
test_photo_data = b"fake-image-bytes-12345"
photo_file = photo_dir / f"{photo_id}.jpg"
photo_file.write_bytes(test_photo_data)

# Write thumbnail
thumb_file = photo_dir / f"{photo_id}_thumb.jpg"
thumb_file.write_bytes(b"fake-thumb-bytes")

# Build state with proper relativePath/thumbRelativePath
photo_rel = f"samples/{sample_id}/photos/{photo_id}.jpg"
thumb_rel = f"samples/{sample_id}/photos/{photo_id}_thumb.jpg"

state, rev, _ = get_state()
state["sampleLibrary"]["categories"] = [{
    "id": "cat_photo", "name": "测试池",
    "samples": [{
        "id": sample_id, "sampleNo": "T-PHOTO", "sn": "SN-PHOTO-001", "imei": "",
        "boardSn": "", "status": "闲置", "location": "", "owner": "", "borrower": "",
        "sourceStageName": "", "sourceSkuName": "",
        "problemRecords": [], "logs": [],
        "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
        "photos": [{
            "id": photo_id, "name": "test.jpg", "type": "image/jpeg", "size": len(test_photo_data),
            "uploadedAt": "2026-06-02T12:00:00",
            "relativePath": photo_rel,
            "thumbRelativePath": thumb_rel,
            "url": f"/api/samples/{sample_id}/photos/{photo_id}",
            "thumbUrl": f"/api/samples/{sample_id}/photos/{photo_id}_thumb",
        }]
    }]
}]
save_state(state, rev, "test-photo", remark="photo test", user="test")

# Export
zip_data, filename = build_export_bundle()
_assert(len(zip_data) > 100, f"Export size: {len(zip_data)} bytes")
_assert(filename.endswith(".zip"), f"Filename: {filename}")

# Verify photos in zip
with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
    names = zf.namelist()
    _assert(f"assets/samples/{sample_id}/photos/{photo_id}.jpg" in names, f"Photo in zip: {names}")
    _assert(f"assets/samples/{sample_id}/photos/{photo_id}_thumb.jpg" in names, f"Thumb in zip: {names}")
    # Verify content
    photo_content = zf.read(f"assets/samples/{sample_id}/photos/{photo_id}.jpg")
    _assert(photo_content == test_photo_data, "Photo content matches")
    thumb_content = zf.read(f"assets/samples/{sample_id}/photos/{photo_id}_thumb.jpg")
    _assert(thumb_content == b"fake-thumb-bytes", "Thumb content matches")

# Cleanup
shutil.rmtree(SAMPLE_DATA_DIR / sample_id, ignore_errors=True)

# ============================================================
# Test 3: Photo import path rewrite
# ============================================================
print("\n3. Photo import path rewrite")

init_db()
# Prepare incoming data with photo metadata (but actual files only in zip)
incoming_sid = "sample_import_photo"
incoming_pid = "photo_test_001"
incoming_photo_rel = f"samples/{incoming_sid}/photos/{incoming_pid}.jpg"
incoming_thumb_rel = f"samples/{incoming_sid}/photos/{incoming_pid}_thumb.jpg"

incoming = {
    "version": "V7",
    "projects": [],
    "sampleLibrary": {
        "categories": [{
            "id": "cat_import_photo", "name": "测试池",
            "samples": [{
                "id": incoming_sid, "sampleNo": "T-IMP-PHOTO", "sn": "SN-IMP-PHOTO", "imei": "",
                "boardSn": "", "status": "闲置", "location": "实验室", "owner": "", "borrower": "",
                "sourceStageName": "", "sourceSkuName": "",
                "problemRecords": [], "logs": [],
                "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
                "photos": [{
                    "id": incoming_pid, "name": "import_test.jpg", "type": "image/jpeg", "size": 20,
                    "uploadedAt": "2026-06-02T12:00:00",
                    "relativePath": incoming_photo_rel,
                    "thumbRelativePath": incoming_thumb_rel,
                    "url": f"/api/samples/{incoming_sid}/photos/{incoming_pid}",
                    "thumbUrl": f"/api/samples/{incoming_sid}/photos/{incoming_pid}_thumb",
                }]
            }]
        }]
    },
    "testCaseMaster": [], "users": [],
}

# Build zip with actual photo files included
photo_bytes = b"imported-photo-bytes"
thumb_bytes = b"imported-thumb-bytes"
zbytes = _build_zip(incoming, extra_files={
    f"assets/samples/{incoming_sid}/photos/{incoming_pid}.jpg": photo_bytes,
    f"assets/samples/{incoming_sid}/photos/{incoming_pid}_thumb.jpg": thumb_bytes,
})

# Preview
preview = _analyze(zbytes)
_assert(len(preview["autoApply"]) > 0, f"Has autoApply: {len(preview['autoApply'])}")
_assert(len(preview["conflicts"]) == 0, "No conflicts for new sample")

# Commit
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": {}})
_assert(result["ok"], f"Commit: {result.get('error', 'OK')}")
_assert(result["stats"]["samplesAdded"] == 1, f"Sample added: {result['stats']}")
_assert(result["stats"]["photosAdded"] >= 1, f"Photo added: {result['stats']}")

# Verify: photo files exist on disk
target_photo_dir = SAMPLE_DATA_DIR / incoming_sid / "photos"
_assert(target_photo_dir.is_dir(), f"Photo dir exists: {target_photo_dir}")
photo_on_disk = target_photo_dir / f"{incoming_pid}.jpg"
thumb_on_disk = target_photo_dir / f"{incoming_pid}_thumb.jpg"
_assert(photo_on_disk.is_file(), f"Photo file exists: {photo_on_disk}")
_assert(thumb_on_disk.is_file(), f"Thumb file exists: {thumb_on_disk}")
_assert(photo_on_disk.read_bytes() == photo_bytes, "Photo content correct")
_assert(thumb_on_disk.read_bytes() == thumb_bytes, "Thumb content correct")

# Verify: metadata fields rewritten
state, _, _ = get_state()
cats = state["sampleLibrary"]["categories"]
sample = None
for cat in cats:
    for s in cat.get("samples", []):
        if s["id"] == incoming_sid:
            sample = s
            break
_assert(sample is not None, "Sample found")
photo = sample["photos"][0]
_assert(photo["relativePath"] == f"samples/{incoming_sid}/photos/{incoming_pid}.jpg", f"relativePath: {photo['relativePath']}")
_assert(photo["url"] == f"/api/samples/{incoming_sid}/photos/{incoming_pid}", f"url: {photo['url']}")
_assert(photo["thumbRelativePath"] == f"samples/{incoming_sid}/photos/{incoming_pid}_thumb.jpg", f"thumbRelativePath: {photo['thumbRelativePath']}")
_assert(photo["thumbUrl"] == f"/api/samples/{incoming_sid}/photos/{incoming_pid}__thumb", f"thumbUrl: {photo['thumbUrl']}")

# Cleanup
shutil.rmtree(SAMPLE_DATA_DIR / incoming_sid, ignore_errors=True)

# ============================================================
# Test 4: Sample identity edit with import_as_new_with_identity_edit
# ============================================================
print("\n4. Sample identity edit (import_as_new_with_identity_edit)")

init_db()
# Create main data with existing sample
main_state, main_rev, _ = get_state()
main_state["sampleLibrary"]["categories"] = [{
    "id": "cat_main", "name": "测试池",
    "samples": [{
        "id": "sample_existing", "sampleNo": "T-EXIST", "sn": "SN-EXISTING", "imei": "86800001", "boardSn": "",
        "status": "闲置", "location": "", "owner": "", "borrower": "",
        "sourceStageName": "", "sourceSkuName": "",
        "problemRecords": [], "photos": [], "logs": [],
        "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
    }]
}]
save_state(main_state, main_rev, "test-4", remark="test", user="test")

# Incoming with SN conflict
incoming = {
    "version": "V7", "projects": [],
    "sampleLibrary": {
        "categories": [{
            "id": "cat_inc", "name": "测试池",
            "samples": [{
                "id": "sample_inc_conflict", "sampleNo": "T-NEW", "sn": "SN-EXISTING", "imei": "86800001",
                "boardSn": "", "status": "取走分析", "location": "远程实验室", "owner": "张三", "borrower": "李四",
                "sourceStageName": "", "sourceSkuName": "",
                "problemRecords": [], "photos": [], "logs": [],
                "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
            }]
        }]
    },
    "testCaseMaster": [], "users": [],
}

zbytes = _build_zip(incoming)
preview = _analyze(zbytes)
conflicts = preview["conflicts"]
_assert(len(conflicts) >= 1, f"Has conflicts: {len(conflicts)}")
sample_conflict = [c for c in conflicts if c["type"] == "sample_identity_conflict"]
_assert(len(sample_conflict) > 0, "Has sample_identity_conflict")

# Test: import_as_new_with_identity_edit with new SN (should work)
cid = sample_conflict[0]["conflictId"]
decisions = {
    cid: {"action": "import_as_new_with_identity_edit", "newSN": "SN-NEW-EDITED", "newIMEI": "", "newSampleNo": ""}
}
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": decisions})
_assert(result["ok"], f"Sample identity edit: {result.get('error', 'OK')}")
_assert(result["stats"]["samplesAdded"] == 1, "Sample added via identity edit")

# Verify: new SN applied
state, _, _ = get_state()
all_samples = []
for cat in state["sampleLibrary"]["categories"]:
    for s in cat.get("samples", []):
        all_samples.append(s)
# Should have 2 samples: existing (SN-EXISTING) + imported (SN-NEW-EDITED)
_assert(len(all_samples) == 2, f"2 samples: {len(all_samples)}")
edited = [s for s in all_samples if s["sn"] == "SN-NEW-EDITED"]
_assert(len(edited) == 1, f"New SN applied: {[s['sn'] for s in all_samples]}")

# Test: import_as_new_with_identity_edit with no new identifiers (should fail)
# Fresh import: need fresh state to get the same sample_identity_conflict again
init_db()
save_state(main_state, None, "test-4b", remark="test", user="test")
zbytes2 = _build_zip(incoming)
preview2 = _analyze(zbytes2)
cid2 = [c for c in preview2["conflicts"] if c["type"] == "sample_identity_conflict"][0]["conflictId"]
decisions2 = {cid2: {"action": "import_as_new_with_identity_edit", "newSN": "", "newIMEI": "", "newSampleNo": ""}}
result2 = commit_import_bundle({"previewId": preview2["previewId"], "decisions": decisions2})
_assert(not result2["ok"], f"Rejects empty identity edit: ok={result2['ok']}")

# ============================================================
# Test 5: field_conflict apply_field_choices
# ============================================================
print("\n5. field_conflict apply_field_choices")

init_db()
main_state, main_rev, _ = get_state()
main_state["projects"] = [{
    "id": "proj_field", "name": "FieldTest", "code": "FT", "owner": "管理员/001",
    "members": [], "locations": ["实验室A"],
    "stages": [{
        "id": "stage_field", "name": "EVT",
        "skuNames": [], "bom": [], "strategy": [], "progress": [], "tasks": []
    }]
}]
main_state["sampleLibrary"]["categories"] = [{
    "id": "cat_field", "name": "测试池",
    "samples": [{
        "id": "sample_field", "sampleNo": "T-FIELD", "sn": "SN-FIELD", "imei": "", "boardSn": "",
        "status": "闲置", "location": "原位置", "owner": "原持有人", "borrower": "",
        "sourceStageName": "", "sourceSkuName": "",
        "problemRecords": [], "photos": [], "logs": [],
        "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
    }]
}]
save_state(main_state, main_rev, "test-5", remark="test", user="test")

# Incoming with same sample ID but different field values
incoming = {
    "version": "V7", "projects": [],
    "sampleLibrary": {
        "categories": [{
            "id": "cat_field_inc", "name": "测试池",
            "samples": [{
                "id": "sample_field", "sampleNo": "T-FIELD", "sn": "SN-FIELD", "imei": "", "boardSn": "",
                "status": "取走分析", "location": "新位置", "owner": "新持有人", "borrower": "借用人",
                "sourceStageName": "", "sourceSkuName": "",
                "problemRecords": [], "photos": [], "logs": [],
                "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
            }]
        }]
    },
    "testCaseMaster": [], "users": [],
}

zbytes = _build_zip(incoming)
preview = _analyze(zbytes)
field_conflicts = [c for c in preview["conflicts"] if c["type"] == "field_conflict"]
_assert(len(field_conflicts) > 0, f"Has field_conflict: {len(field_conflicts)}")

cid = field_conflicts[0]["conflictId"]
decisions = {
    cid: {"action": "apply_field_choices", "fieldChoices": {"location": "incoming", "owner": "current", "status": "incoming"}}
}
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": decisions})
_assert(result["ok"], f"field_conflict commit: {result.get('error', 'OK')}")

# Verify fields applied correctly
state, _, _ = get_state()
for cat in state["sampleLibrary"]["categories"]:
    for s in cat.get("samples", []):
        if s["id"] == "sample_field":
            _assert(s["location"] == "新位置", f"location=incoming: {s['location']}")
            _assert(s["owner"] == "原持有人", f"owner=current: {s['owner']}")
            _assert(s["status"] == "取走分析", f"status=incoming: {s['status']}")

# ============================================================
# Test 6: Revision conflict rejection
# ============================================================
print("\n6. Revision conflict rejection")

init_db()
# Create main data
state, rev, _ = get_state()
state["sampleLibrary"]["categories"] = [{
    "id": "cat_rev", "name": "测试池",
    "samples": [{
        "id": "sample_rev", "sampleNo": "T-REV", "sn": "SN-REV", "imei": "", "boardSn": "",
        "status": "闲置", "location": "", "owner": "", "borrower": "",
        "sourceStageName": "", "sourceSkuName": "",
        "problemRecords": [], "photos": [], "logs": [],
        "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
    }]
}]
save_state(state, rev, "test-6", remark="test", user="test")

# Build incoming with a new sample (no conflicts)
incoming = {
    "version": "V7", "projects": [],
    "sampleLibrary": {
        "categories": [{
            "id": "cat_rev_inc", "name": "测试池",
            "samples": [{
                "id": "sample_rev_new", "sampleNo": "T-REV-NEW", "sn": "SN-REV-NEW", "imei": "", "boardSn": "",
                "status": "闲置", "location": "", "owner": "", "borrower": "",
                "sourceStageName": "", "sourceSkuName": "",
                "problemRecords": [], "photos": [], "logs": [],
                "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
            }]
        }]
    },
    "testCaseMaster": [], "users": [],
}

zbytes = _build_zip(incoming)
preview = _analyze(zbytes)

# Modify the DB state (change revision) between preview and commit
state2, rev2, _ = get_state()
# A small modification to bump revision
state2["sampleLibrary"]["categories"][0]["samples"][0]["location"] = "changed"
save_state(state2, rev2, "test-6-modify", remark="concurrent", user="other")

# Commit should fail with revision conflict
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": {}})
_assert(not result["ok"], f"Revision conflict detected: ok={result['ok']}")
_assert(result.get("error_code") == "IMPORT_REVISION_CONFLICT" or result.get("status") == 409,
        f"Error code: {result.get('error_code')}, status: {result.get('status')}")

# ============================================================
# Test 7: ID mapping (sample merge → task references remapped)
# ============================================================
print("\n7. ID mapping after sample merge")

init_db()
# Main data: project with task referencing sample_A
main_state, main_rev, _ = get_state()
main_state["projects"] = [{
    "id": "proj_map", "name": "MappingTest", "code": "MT", "owner": "管理员/001",
    "members": [], "locations": ["实验室"],
    "stages": [{
        "id": "stage_map", "name": "EVT",
        "skuNames": [], "bom": [], "strategy": [], "progress": [],
        "tasks": [{
            "id": "task_map", "progressId": "", "category": "环境", "testItem": "温度测试",
            "skuIndex": 0, "owner": "张三/002",
            "planStartDate": "2026-06-01", "planEndDate": "2026-06-15",
            "status": "进行中", "completed": False, "archived": False,
            "sampleIds": ["sample_main_A"], "removedSampleRecords": [],
            "sampleFaultRecords": [], "resultUploads": [], "resultDraft": {},
            "logs": [{"id": "log1", "time": "2026-06-02T12:00:00", "action": "start",
                      "user": "张三", "sampleId": "sample_main_A"}],
            "issueRecord": {}
        }]
    }]
}]
main_state["sampleLibrary"]["categories"] = [{
    "id": "cat_map", "name": "测试池",
    "samples": [{
        "id": "sample_main_A", "sampleNo": "T-MAP-A", "sn": "SN-MAP-001", "imei": "868-MAP-001", "boardSn": "",
        "status": "测试中", "location": "实验室", "owner": "李四", "borrower": "",
        "sourceStageName": "", "sourceSkuName": "",
        "problemRecords": [], "photos": [], "logs": [],
        "currentProjectId": "proj_map", "currentStageId": "stage_map",
        "currentTaskId": "task_map", "currentTestItem": "温度测试",
    }]
}]
save_state(main_state, main_rev, "test-7", remark="test", user="test")

# Incoming: sample with same SN, different ID, plus a project
incoming = {
    "version": "V7", "projects": [],
    "sampleLibrary": {
        "categories": [{
            "id": "cat_map_inc", "name": "测试池",
            "samples": [{
                "id": "sample_inc_B", "sampleNo": "T-MAP-B", "sn": "SN-MAP-001", "imei": "868-MAP-001",
                "boardSn": "", "status": "闲置", "location": "远程", "owner": "王五", "borrower": "",
                "sourceStageName": "", "sourceSkuName": "",
                "problemRecords": [], "photos": [], "logs": [],
                "currentProjectId": None, "currentStageId": None, "currentTaskId": None, "currentTestItem": None,
            }]
        }]
    },
    "testCaseMaster": [], "users": [],
}

zbytes = _build_zip(incoming)
preview = _analyze(zbytes)
cid = [c for c in preview["conflicts"] if c["type"] == "sample_identity_conflict"][0]["conflictId"]
decisions = {cid: {"action": "merge_into_existing", "targetId": "sample_main_A", "fieldChoices": {}}}
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": decisions})
_assert(result["ok"], f"Merge commit: {result.get('error', 'OK')}")

# Verify: sample_id_map correctly applied — task still references sample_main_A
state, _, _ = get_state()
task = state["projects"][0]["stages"][0]["tasks"][0]
_assert("sample_main_A" in task.get("sampleIds", []), f"Task sampleIds: {task['sampleIds']}")
# Verify: log's sampleId remapped
log_sample_id = task["logs"][0].get("sampleId", "")
_assert(log_sample_id == "sample_main_A", f"Log sampleId remapped: {log_sample_id}")
# Verify: only 1 sample (merged, not duplicated)
samples = [s for cat in state["sampleLibrary"]["categories"] for s in cat.get("samples", [])]
_assert(len(samples) == 1, f"1 sample after merge: {len(samples)}")
_assert(samples[0]["id"] == "sample_main_A", f"Sample ID: {samples[0]['id']}")

# ============================================================
# Test 8: Unsupported conflict type rejection
# ============================================================
print("\n8. Unsupported conflict type rejection")

init_db()
# Build incoming where we manually inject an unsupported conflict type
# by abusing the preview mode: we build a zip with state that has a fake conflict.
# Actually, the check is in commit_import_bundle, not preview. So we test via
# the hard rule that fires when a conflict type has no handler.
# Let's craft a scenario where _diff returns a conflict that won't be handled.

# Simplest approach: directly test that the SUPPORTED list includes all current types
# and any new type introduced later without a handler would be caught.
# We can test by patching the preview result with an unsupported type.
incoming = {
    "version": "V7", "projects": [], "sampleLibrary": {"categories": []},
    "testCaseMaster": [], "users": [],
}
zbytes = _build_zip(incoming)
preview = _analyze(zbytes)

# Manually inject an unsupported conflict type into the result
preview["conflicts"] = [{
    "conflictId": "conflict_9999",
    "type": "unsupported_made_up_type",
    "entity": "project",
    "currentId": "x", "incomingId": "y",
    "label": "fake",
}]
# Update the stored preview
from server import _IMPORT_PREVIEWS
for k, v in _IMPORT_PREVIEWS.items():
    if v.get("result") is preview:
        v["result"] = preview
        break

result = commit_import_bundle({"previewId": preview["previewId"], "decisions": {"conflict_9999": {"action": "skip"}}})
_assert(not result["ok"], f"Rejects unsupported type: ok={result['ok']}")
_assert(result.get("error_code") == "UNSUPPORTED_IMPORT_CONFLICT" or "不支持" in result.get("error", ""),
        f"Error: {result.get('error')}")

# ============================================================
# Test 9: Project field_conflict apply_field_choices
# ============================================================
print("\n9. Project field_conflict apply_field_choices")

init_db()
main_state, main_rev, _ = get_state()
main_state["projects"] = [{
    "id": "proj_pf", "name": "ProjField", "code": "PF-OLD", "owner": "管理员/001",
    "members": [], "locations": ["位置Old"],
    "stages": [],
}]
save_state(main_state, main_rev, "test-9", remark="test", user="test")

incoming = {
    "version": "V7",
    "projects": [{
        "id": "proj_pf", "name": "ProjField", "code": "PF-NEW", "owner": "新人员/999",
        "members": [], "locations": ["位置New"],
        "stages": [],
    }],
    "sampleLibrary": {"categories": []},
    "testCaseMaster": [], "users": [],
}

zbytes = _build_zip(incoming)
preview = _analyze(zbytes)
field_conflicts = [c for c in preview["conflicts"] if c["type"] == "field_conflict"]
_assert(len(field_conflicts) > 0, f"Project field_conflict: {len(field_conflicts)}")

cid = field_conflicts[0]["conflictId"]
decisions = {
    cid: {"action": "apply_field_choices", "fieldChoices": {"code": "incoming", "owner": "current"}}
}
result = commit_import_bundle({"previewId": preview["previewId"], "decisions": decisions})
_assert(result["ok"], f"Project field commit: {result.get('error', 'OK')}")

state, _, _ = get_state()
proj = state["projects"][0]
_assert(proj["code"] == "PF-NEW", f"code=incoming: {proj['code']}")
_assert(proj["owner"] == "管理员/001", f"owner=current: {proj['owner']}")

# ============================================================
# Test 10: Blank target full bundle import with occupied sample
# ============================================================
print("\n10. Blank target full bundle import")

init_db()
source_state, source_rev, _ = get_state()
source_state["projects"] = [{
    "id": "proj_blank_import",
    "name": "BlankImportProject",
    "code": "BIP",
    "owner": "管理员/001",
    "members": [],
    "locations": ["实验室A"],
    "stages": [{
        "id": "stage_blank_import",
        "name": "EVT",
        "skuNames": ["SKU-A"],
        "bom": [],
        "strategy": [],
        "progress": [],
        "tasks": [{
            "id": "task_blank_import",
            "progressId": "",
            "category": "可靠性",
            "testItem": "高温测试",
            "skuIndex": 0,
            "owner": "张三/001",
            "status": "进行中",
            "completed": False,
            "archived": False,
            "sampleIds": ["sample_blank_import"],
            "logs": [],
            "removedSampleRecords": [],
            "sampleFaultRecords": [],
            "resultUploads": [],
            "resultDraft": {},
        }],
    }],
}]
source_state["sampleLibrary"]["categories"] = [{
    "id": "cat_blank_import",
    "name": "空白导入样机池",
    "description": "full bundle import target",
    "samples": [{
        "id": "sample_blank_import",
        "sampleNo": "BIP-001",
        "sn": "SN-BIP-001",
        "imei": "",
        "boardSn": "MB-BIP-001",
        "status": "测试中",
        "location": "实验室A",
        "owner": "张三/001",
        "borrower": "",
        "sourceStageName": "EVT",
        "sourceSkuName": "SKU-A",
        "problemRecords": [],
        "photos": [],
        "logs": [],
        "currentProjectId": "proj_blank_import",
        "currentStageId": "stage_blank_import",
        "currentTaskId": "task_blank_import",
        "currentTestItem": "高温测试",
    }],
}]
ok, resp = save_state(source_state, source_rev, "test-10-source", remark="source", user="test")
_assert(ok, f"Source state saved: {resp}")

zip_data, filename = build_export_bundle()
_assert(filename.endswith(".zip"), f"Exported source bundle: {filename}")

target_blank, blank_rev, _ = get_state()
target_blank = empty_data()
ok, resp = save_state(target_blank, blank_rev, "test-10-blank", remark="blank target", user="test")
_assert(ok, f"Blank target prepared: {resp}")

preview = _analyze(zip_data)
_assert(len(preview["conflicts"]) == 0, f"No conflicts on blank target: {preview['conflicts']}")
_assert(len(preview["blockers"]) == 0, f"No blockers on blank target: {preview['blockers']}")

result = commit_import_bundle({"previewId": preview["previewId"], "decisions": {}})
_assert(result["ok"], f"Blank target commit: {result.get('error', 'OK')}")
_assert(result["stats"]["projectsAdded"] == 1, f"Project added: {result['stats']}")
_assert(result["stats"]["stagesAdded"] == 1, f"Stage added: {result['stats']}")
_assert(result["stats"]["tasksAdded"] == 1, f"Task added: {result['stats']}")
_assert(result["stats"]["samplesAdded"] == 1, f"Sample added: {result['stats']}")
mutation_summary = result.get("mutationSummary") or {}
_assert(mutation_summary.get("requiresFullState") is False, f"Import sync does not require full state: {mutation_summary}")
_assert("proj_blank_import" in mutation_summary.get("projectIds", []), f"Project in import sync summary: {mutation_summary}")
_assert("stage_blank_import" in mutation_summary.get("stageIds", []), f"Stage in import sync summary: {mutation_summary}")
_assert("task_blank_import" in mutation_summary.get("taskIds", []), f"Task in import sync summary: {mutation_summary}")
_assert("sample_blank_import" in mutation_summary.get("sampleIds", []), f"Sample in import sync summary: {mutation_summary}")
_assert(len(mutation_summary.get("sampleCategoryIds", [])) == 1, f"Sample category in import sync summary: {mutation_summary}")

state, _, _ = get_state()
_assert(len(state["projects"]) == 1, f"One project after import: {len(state['projects'])}")
project = state["projects"][0]
_assert(len(project["stages"]) == 1, f"One stage after import: {len(project['stages'])}")
stage = project["stages"][0]
_assert(len(stage["tasks"]) == 1, f"One task after import: {len(stage['tasks'])}")
task = stage["tasks"][0]
_assert(task["sampleIds"] == ["sample_blank_import"], f"Task sampleIds preserved: {task['sampleIds']}")

categories = state["sampleLibrary"]["categories"]
_assert(len(categories) == 1, f"One sample category after import: {len(categories)}")
samples = [s for cat in categories for s in cat.get("samples", [])]
_assert(len(samples) == 1, f"One sample after import: {len(samples)}")
sample = samples[0]
_assert(sample["currentProjectId"] == "proj_blank_import", f"Sample project occupancy: {sample['currentProjectId']}")
_assert(sample["currentStageId"] == "stage_blank_import", f"Sample stage occupancy: {sample['currentStageId']}")
_assert(sample["currentTaskId"] == "task_blank_import", f"Sample task occupancy: {sample['currentTaskId']}")

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
print(f"Results: {_passed} passed, {_failed} failed")
if _failed == 0:
    print("✅ ALL TESTS PASSED")
else:
    print(f"❌ {_failed} TESTS FAILED")
    sys.exit(1)
