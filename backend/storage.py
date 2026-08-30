"""Media storage — local disk by default, Emergent cloud when EMERGENT_LLM_KEY is set.

All I/O is async (httpx) so cloud operations never block the event loop.
Local reads/writes use asyncio.to_thread() for the same reason.
"""
import asyncio
import os
from pathlib import Path

import httpx

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "openads"

LOCAL_ROOT = Path(os.environ.get("LOCAL_UPLOAD_DIR") or Path(__file__).resolve().parent.parent / "uploads")
LOCAL_ROOT.mkdir(parents=True, exist_ok=True)

_storage_key = None


def _use_cloud() -> bool:
    return bool((os.environ.get("EMERGENT_LLM_KEY") or "").strip())


def _local_path(path: str) -> Path:
    """Resolve a storage path safely inside LOCAL_ROOT.

    Uses Path.relative_to() which raises ValueError on traversal —
    immune to prefix-sharing sibling attacks unlike startswith() checks.
    """
    # Resolve the candidate without allowing symlink escapes
    candidate = (LOCAL_ROOT / path).resolve()
    try:
        candidate.relative_to(LOCAL_ROOT.resolve())
    except ValueError:
        raise ValueError(f"Path traversal blocked: {path!r}")
    return candidate


async def init_storage(force: bool = False) -> str:
    global _storage_key
    if not _use_cloud():
        return None
    if _storage_key and not force:
        return _storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{STORAGE_URL}/init", json={"emergent_key": emergent_key})
        resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


async def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Store object. Fully async — safe to call from any async context."""
    if not _use_cloud():
        dest = _local_path(path)
        await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(dest.write_bytes, data)
        return {"path": path}

    key = await init_storage()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            content=data,
        )
        if resp.status_code == 404:
            key = await init_storage(force=True)
            resp = await client.put(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key, "Content-Type": content_type},
                content=data,
            )
    resp.raise_for_status()
    return resp.json()


async def get_object(path: str) -> tuple[bytes, str]:
    """Fetch object bytes. Fully async — safe to call from any async context."""
    if not _use_cloud():
        src = _local_path(path)
        if not await asyncio.to_thread(src.is_file):
            raise FileNotFoundError(path)
        data = await asyncio.to_thread(src.read_bytes)
        ext = src.suffix.lstrip(".").lower()
        return data, MIME_TYPES.get(ext, "application/octet-stream")

    key = await init_storage()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key})
        if resp.status_code == 404:
            key = await init_storage(force=True)
            resp = await client.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key})
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "pdf": "application/pdf",
}
