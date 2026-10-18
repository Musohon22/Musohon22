import re
import uuid

from starlette.datastructures import UploadFile

from . import config
from .errors import ApiError
from .plans import log_event, stamp

# Extension → (mime, magic-byte check). The file content must match its extension.
ALLOWED = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "webp": ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}
_CHUNK = 1024 * 1024


def clean_filename(name: str) -> str:
    name = (name or "fayl").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "fayl"
    return name[-120:]


async def save(conn, plan, user_id: str, upload: UploadFile) -> dict:
    count = conn.execute("SELECT COUNT(*) FROM attachments WHERE plan_id = ?", (plan["id"],)).fetchone()[0]
    if count >= config.MAX_ATTACHMENTS_PER_PLAN:
        raise ApiError(400, "too_many_attachments", limit=config.MAX_ATTACHMENTS_PER_PLAN)
    filename = clean_filename(upload.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ApiError(400, "file_type_not_allowed", allowed=sorted(ALLOWED))
    mime, check = ALLOWED[ext]

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4()}.{ext}"
    path = config.UPLOAD_DIR / stored
    size = 0
    head = b""
    try:
        with open(path, "wb") as out:
            while chunk := await upload.read(_CHUNK):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise ApiError(413, "file_too_large", limit=config.MAX_UPLOAD_BYTES)
                out.write(chunk)
        if size == 0:
            raise ApiError(400, "file_empty")
        if not check(head):
            raise ApiError(400, "file_content_mismatch")
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    att_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO attachments(id, plan_id, user_id, filename, mime, size, stored_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (att_id, plan["id"], user_id, filename, mime, size, stored, stamp()),
    )
    log_event(conn, plan["id"], user_id, "attached", filename=filename)
    return {"id": att_id, "filename": filename, "mime": mime, "size": size, "created_at": stamp()}


def remove(conn, att, plan, user_id: str) -> None:
    (config.UPLOAD_DIR / att["stored_name"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM attachments WHERE id = ?", (att["id"],))
    log_event(conn, plan["id"], user_id, "detached", filename=att["filename"])
