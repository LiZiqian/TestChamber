from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from server_modules import chamber_package, import_defaults, import_diff, import_preview_cache, zip_security


@dataclass(frozen=True)
class BundlePreviewContext:
    app_version: str
    server_version: str
    data_dir: Path
    export_dir: Path
    import_preview_dir: Path
    import_previews: dict
    import_preview_ttl_seconds: int
    import_preview_max_entries: int
    import_preview_max_state_bytes: int
    import_preview_max_cached_bytes: int
    get_state: Callable[..., tuple[dict, int, str]]
    load_deployment_id: Callable[[], str]
    now_iso: Callable[[], str]
    json_dumps: Callable[..., str]
    path_inside_data: Callable[[str], Path]
    ensure_dirs: Callable[[], None]
    parse_multipart: Callable


def preview_id() -> str:
    return import_preview_cache.preview_id()


def cleanup_expired_previews(ctx: BundlePreviewContext) -> None:
    import_preview_cache.cleanup_expired_previews(
        ctx.import_previews,
        ttl_seconds=ctx.import_preview_ttl_seconds,
        max_entries=ctx.import_preview_max_entries,
        max_cached_bytes=ctx.import_preview_max_cached_bytes,
    )


def cleanup_preview_temp(ctx: BundlePreviewContext, preview_id_value: str) -> None:
    import_preview_cache.cleanup_preview_temp(ctx.import_previews, preview_id_value)


def store_import_preview_payload(ctx: BundlePreviewContext, tmp_path: Path, incoming: dict, result: dict) -> Path:
    return import_preview_cache.store_payload(tmp_path, incoming, result, ctx.json_dumps)


def load_import_preview_payload(entry: dict) -> tuple[dict, dict]:
    return import_preview_cache.load_payload(entry)


def text_sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_export_bundle_parts(ctx: BundlePreviewContext) -> tuple[dict, dict, dict[str, str], dict, str]:
    """Build ChamberData v2 export payloads shared by byte/file exports."""
    data, revision, _ = ctx.get_state()
    export_data = import_diff.strip_view_state(data)
    deployment_id = ctx.load_deployment_id()
    exported_at = ctx.now_iso()
    export_id = f"exp_{exported_at.replace('-','').replace(':','').replace('T','_')[:15]}_{uuid.uuid4().hex[:6]}"

    package = chamber_package.build_export_package(
        export_data,
        data_dir=ctx.data_dir,
        app_version=ctx.app_version,
        server_version=ctx.server_version,
        exported_at=exported_at,
        export_id=export_id,
        deployment_id=deployment_id,
        revision=revision,
    )
    payloads = chamber_package.package_payloads(package, pretty=True)
    checksums = {path: text_sha256(text) for path, text in payloads.items()}
    payloads["checksums.json"] = ctx.json_dumps(checksums, pretty=True)

    ts = exported_at.replace("-", "").replace(":", "")[:15]
    filename = f"chamberdata_export_{ts}.zip"
    return export_data, package, payloads, checksums, filename


def write_export_bundle_zip(ctx: BundlePreviewContext, zf: zipfile.ZipFile, export_data: dict, package: dict, payloads: dict[str, str]) -> None:
    for path, text in payloads.items():
        zf.writestr(path, text)

    for asset in (package.get("assetIndex") or {}).get("assets") or []:
        if not asset.get("exists"):
            print(f"[EXPORT] 资产缺失，已记录但未写入: {asset.get('sourceRelativePath')}")
            continue
        rel = str(asset.get("sourceRelativePath") or "")
        zip_path = str(asset.get("zipPath") or "")
        if not rel or not zip_path:
            continue
        try:
            source_path = ctx.path_inside_data(rel)
            if source_path.is_file():
                zf.write(source_path, zip_path)
        except (ValueError, OSError, RuntimeError) as e:
            print(f"[EXPORT] 跳过资产 {asset.get('assetId')}: {e}")


def build_export_bundle(ctx: BundlePreviewContext) -> tuple[bytes, str]:
    """生成完整导出包 zip，返回 (bytes, filename)。测试和低频工具保留该兼容接口。"""
    tmp_path, filename = build_export_bundle_file(ctx)
    try:
        return tmp_path.read_bytes(), filename
    finally:
        tmp_path.unlink(missing_ok=True)


def build_export_bundle_file(ctx: BundlePreviewContext) -> tuple[Path, str]:
    """生成完整导出包到临时文件，HTTP 下载路径用它避免整包 bytes 常驻内存。"""
    ctx.ensure_dirs()
    export_data, package, payloads, _checksums, filename = prepare_export_bundle_parts(ctx)
    tmp = tempfile.NamedTemporaryFile(prefix="tcv7_export_", suffix=".zip", dir=ctx.export_dir, delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            write_export_bundle_zip(ctx, zf, export_data, package, payloads)
        return tmp_path, filename
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def analyze_import_bundle(ctx: BundlePreviewContext, headers, raw_body: bytes) -> dict:
    """解压导入包，与主库对比生成 preview 分析结果"""
    cleanup_expired_previews(ctx)

    _, files = ctx.parse_multipart(headers, raw_body)
    zip_raw = None
    for f in files:
        if f.get("filename", "").endswith(".zip"):
            zip_raw = f.get("content", b"")
            break
    if not zip_raw:
        for f in files:
            zip_raw = f.get("content", b"")
            break

    if not zip_raw or len(zip_raw) < 4:
        raise ValueError("未找到有效的 zip 文件内容")
    zip_bytes = len(zip_raw)

    ctx.ensure_dirs()
    tmp_dir = tempfile.mkdtemp(prefix="tcv7_import_", dir=ctx.import_preview_dir)
    try:
        zip_path = Path(tmp_dir) / "bundle.zip"
        zip_path.write_bytes(zip_raw)
        zip_raw = None
        for item in files:
            item["content"] = b""

        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_security.safe_extract_zip(zf, tmp_dir)

        tmp_path = Path(tmp_dir)

        manifest_path = tmp_path / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("导入包缺少 manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        asset_index = None
        if chamber_package.is_chamberdata_manifest(manifest):
            checksums = None
            checksums_path = tmp_path / chamber_package.CHECKSUMS_PATH
            if checksums_path.is_file():
                if checksums_path.stat().st_size > ctx.import_preview_max_state_bytes:
                    raise ValueError(f"导入包 {chamber_package.CHECKSUMS_PATH} 过大，超过 {ctx.import_preview_max_state_bytes} bytes 上限")
                checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
            chamber_package.verify_checksums(tmp_path, checksums)

            def _read_package_json(rel_path: str):
                path = tmp_path / rel_path
                if not path.is_file():
                    raise ValueError(f"导入包缺少 {rel_path}")
                if path.stat().st_size > ctx.import_preview_max_state_bytes:
                    raise ValueError(f"导入包 {rel_path} 过大，超过 {ctx.import_preview_max_state_bytes} bytes 上限")
                return json.loads(path.read_text(encoding="utf-8"))

            domains = chamber_package.read_domain_documents(_read_package_json)
            asset_index = chamber_package.read_asset_index(_read_package_json)
            chamber_package.validate_domain_documents(manifest, domains, asset_index)
            incoming_state = chamber_package.state_from_domain_documents(manifest, domains)
            state_bytes = sum((tmp_path / rel).stat().st_size for rel in chamber_package.DOMAIN_PATHS.values())
            state_bytes += (tmp_path / chamber_package.ASSET_INDEX_PATH).stat().st_size
            if checksums_path.is_file():
                state_bytes += checksums_path.stat().st_size
        else:
            state_path = tmp_path / "state.json"
            if not state_path.is_file():
                raise ValueError("导入包缺少 state.json")
            state_bytes = state_path.stat().st_size
            if state_bytes > ctx.import_preview_max_state_bytes:
                raise ValueError(f"导入包 state.json 过大 ({state_bytes} bytes)，超过 {ctx.import_preview_max_state_bytes} bytes 上限")
            incoming_state = json.loads(state_path.read_text(encoding="utf-8"))
        incoming_state = import_defaults.normalize_import_state(
            incoming_state,
            source_format=str(manifest.get("format") or manifest.get("protocol") or ""),
        )

        current_data, current_revision, _ = ctx.get_state(compact=True)

        result = import_diff.diff_import_bundle(current_data, incoming_state, manifest, tmp_path, asset_index=asset_index)
        preview_id_value = preview_id()
        result["previewId"] = preview_id_value
        payload_path = store_import_preview_payload(ctx, tmp_path, incoming_state, result)
        payload_bytes = payload_path.stat().st_size
        ctx.import_previews[preview_id_value] = {
            "_ts": time.time(),
            "_tmp_dir": str(tmp_path),
            "_payload_path": str(payload_path),
            "_revision": current_revision,
            "_zip_bytes": zip_bytes,
            "_state_bytes": state_bytes,
            "_payload_bytes": payload_bytes,
            "_cache_bytes": zip_bytes + payload_bytes,
        }
        cleanup_expired_previews(ctx)
        if preview_id_value not in ctx.import_previews:
            raise ValueError("导入预览缓存已超过服务器上限，请稍后重试")
        return result
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
