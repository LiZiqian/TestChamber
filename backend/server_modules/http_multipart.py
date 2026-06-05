"""HTTP multipart/form-data parsing helpers."""

from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy


def parse_multipart(headers, raw: bytes) -> tuple[dict[str, str], list[dict]]:
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("请求必须使用 multipart/form-data")
    envelope = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + raw
    )
    message = BytesParser(policy=email_policy).parsebytes(envelope)
    fields: dict[str, str] = {}
    files: list[dict] = []
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append({
                "field": name,
                "filename": filename,
                "mime_type": part.get_content_type() or "application/octet-stream",
                "content": payload,
            })
        else:
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files
