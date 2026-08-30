import asyncio
import io
import logging
import os
import random
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

# ── Load .env FIRST — before any local modules that read env vars at import time ──
from dotenv import load_dotenv
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import certifi
from fastapi import FastAPI, APIRouter, Depends, HTTPException, UploadFile, File, Form
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response, StreamingResponse

# Local modules imported AFTER load_dotenv so their module-level env reads work
import telegram_service as tg
import storage
from auth import require_auth, authenticate_user

# ── Cross-campaign dedup guard ─────────────────────────────────────────────
# (account_id, group_id) pairs currently being sent to in ANY campaign.
# Prevents same account hitting same group in two simultaneous campaigns.
_active_sends: set[tuple[str, str]] = set()

# ── Per-campaign ban map ───────────────────────────────────────────────────
# campaign_id → set of (account_id, group_id) pairs where the account got
# "banned from sending" in that group. Skipped in future cycles of the SAME
# campaign. Cleared when campaign stops/restarts. New campaigns start fresh.
_campaign_bans: dict[str, set[tuple[str, str]]] = {}

# ── Per-campaign dead groups ───────────────────────────────────────────────
# campaign_id → set of group_ids that are dead (deleted, renamed, etc).
# Once marked dead, ALL accounts skip this group for the rest of the campaign.
_campaign_dead_groups: dict[str, set[str]] = {}

mongo_url = os.environ['MONGO_URL']
# Atlas (mongodb+srv://) needs certifi CA bundle; Railway internal MongoDB does not
mongo_opts = {"tlsCAFile": certifi.where()} if mongo_url.startswith("mongodb+srv") else {}
client = AsyncIOMotorClient(mongo_url, **mongo_opts)
db = client[os.environ['DB_NAME']]

api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ----------------------- Models -----------------------
class AccountCreate(BaseModel):
    name: str
    api_id: int
    api_hash: str
    session_string: str


class Account(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    api_id: int
    api_hash: str
    session_string: str
    phone: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    status: str = "disconnected"
    created_at: str


class TargetGroup(BaseModel):
    id: str
    title: str


class CampaignCreate(BaseModel):
    name: str
    message_type: str  # text | media | forward
    text: Optional[str] = ""
    media_path: Optional[str] = None
    media_url: Optional[str] = None
    media_filename: Optional[str] = None
    forward_link: Optional[str] = None
    target_groups: List[str]  # raw identifiers: @username, t.me link, or numeric id
    interval_seconds: int = 60
    account_batch_id: Optional[str] = None
    concurrency: int = 25


PUBLIC_ACCOUNT_FIELDS = {"session_string": 0, "api_hash": 0}


def account_public(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k not in ("_id", "session_string", "api_hash")}
    return d


# ----------------------- Auth routes (public) -----------------------
class LoginRequest(BaseModel):
    username: str
    password: str


@api_router.post("/auth/login")
async def login(payload: LoginRequest):
    token = authenticate_user(payload.username, payload.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": token, "username": payload.username}


# ----------------------- Account routes -----------------------
@api_router.post("/accounts")
async def add_account(payload: AccountCreate, _user: str = Depends(require_auth)):
    try:
        info = await tg.validate_account(payload.api_id, payload.api_hash, payload.session_string)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Session validation failed: {e}")

    acc = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "api_id": payload.api_id,
        "api_hash": payload.api_hash,
        "session_string": payload.session_string,
        "phone": info.get("phone"),
        "username": info.get("username"),
        "display_name": info.get("display_name"),
        "status": "connected",
        "created_at": now_iso(),
    }
    await db.accounts.insert_one(acc)
    return account_public(acc)


def _new_account_doc(name, api_id, api_hash, session_string, info, batch_id, batch_name):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "batch_id": batch_id,
        "batch_name": batch_name,
        "api_id": int(api_id),
        "api_hash": api_hash,
        "session_string": session_string,
        "phone": info.get("phone"),
        "username": info.get("username"),
        "display_name": info.get("display_name"),
        "status": "connected",
        "created_at": now_iso(),
    }


@api_router.post("/accounts/upload")
async def upload_account(
    name: str = Form(...),
    api_id: int = Form(...),
    api_hash: str = Form(...),
    file: UploadFile = File(...),
    batch_id: Optional[str] = Form(None),
    _user: str = Depends(require_auth),
):
    content = await file.read()
    fname = (file.filename or "").lower()

    sessions = []  # list of (label, bytes)
    if fname.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid .zip file")
        for n in zf.namelist():
            if n.lower().endswith(".session") and not n.endswith("/"):
                sessions.append((Path(n).stem, zf.read(n)))
        if not sessions:
            raise HTTPException(status_code=400, detail="No .session files found inside the zip")
    elif fname.endswith(".session"):
        sessions.append((Path(file.filename).stem, content))
    else:
        raise HTTPException(status_code=400, detail="Upload a .session file or a .zip containing .session files")

    # If batch_id is provided, try to add to an existing account section/folder.
    # Otherwise create a new section.
    if batch_id:
        existing = await db.accounts.find_one({"batch_id": batch_id})
        if not existing:
            raise HTTPException(status_code=400, detail="Account section not found — it may have been deleted.")
        batch_name = existing.get("batch_name") or name
    else:
        batch_id = str(uuid.uuid4())
        batch_name = name

    created, errors = [], []
    multi = len(sessions) > 1
    for label, data in sessions:
        try:
            string_session, info = await tg.session_file_to_string(data, api_id, api_hash)
        except Exception as e:
            errors.append({"file": label, "error": str(e)})
            continue
        acc_name = f"{batch_name} - {label}"
        acc = _new_account_doc(acc_name, api_id, api_hash, string_session, info, batch_id, batch_name)
        await db.accounts.insert_one(acc)
        created.append(account_public(acc))

    if not created:
        detail = "; ".join(f"{e['file']}: {e['error']}" for e in errors) or "No sessions processed"
        raise HTTPException(status_code=400, detail=f"Session load failed: {detail}")
    return {"created": created, "errors": errors, "batch_id": batch_id, "batch_name": batch_name}


@api_router.get("/account-groups")
async def account_groups(_user: str = Depends(require_auth)):
    pipeline = [
        {"$group": {"_id": {"batch_id": "$batch_id", "batch_name": "$batch_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = await db.accounts.aggregate(pipeline).to_list(1000)
    return [
        {
            "batch_id": r["_id"].get("batch_id"),
            "batch_name": r["_id"].get("batch_name") or "Ungrouped",
            "count": r["count"],
        }
        for r in rows
        if r["_id"].get("batch_id")
    ]


@api_router.get("/accounts")
async def list_accounts(_user: str = Depends(require_auth)):
    docs = await db.accounts.find({}, {"_id": 0, "session_string": 0, "api_hash": 0, "proxy": 0}).to_list(5000)
    return docs


# ----------------------- Proxy routes -----------------------
def _proxy_public(p):
    return {
        "id": p["id"],
        "proxy_type": p["proxy_type"],
        "host": p["host"],
        "port": p["port"],
        "username": p.get("username"),
        "label": f"{p['host']}:{p['port']}",
        "created_at": p.get("created_at"),
    }


class ProxyLoad(BaseModel):
    text: str
    proxy_type: str = "socks5"


@api_router.post("/proxies")
async def load_proxies(payload: ProxyLoad, _user: str = Depends(require_auth)):
    added, skipped = 0, 0
    for line in payload.text.splitlines():
        parsed = tg.parse_proxy_line(line, payload.proxy_type)
        if not parsed:
            if line.strip():
                skipped += 1
            continue
        exists = await db.proxies.find_one({
            "host": parsed["host"], "port": parsed["port"],
            "username": parsed["username"], "proxy_type": parsed["proxy_type"],
        })
        if exists:
            skipped += 1
            continue
        doc = {"id": str(uuid.uuid4()), **parsed, "created_at": now_iso()}
        await db.proxies.insert_one(doc)
        added += 1
    total = await db.proxies.count_documents({})
    return {"added": added, "skipped": skipped, "total": total}


@api_router.get("/proxies")
async def list_proxies(_user: str = Depends(require_auth)):
    docs = await db.proxies.find({}).sort("created_at", 1).to_list(10000)
    return [_proxy_public(p) for p in docs]


@api_router.delete("/proxies")
async def clear_proxies(_user: str = Depends(require_auth)):
    await db.proxies.delete_many({})
    return {"ok": True}


@api_router.delete("/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str, _user: str = Depends(require_auth)):
    await db.proxies.delete_one({"id": proxy_id})
    return {"ok": True}


class ProxyTest(BaseModel):
    proxy_type: str = "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None


@api_router.post("/proxies/test")
async def test_proxy_endpoint(payload: ProxyTest, _user: str = Depends(require_auth)):
    try:
        await tg.test_proxy(payload.model_dump())
        return {"ok": True, "message": "Proxy connected to Telegram successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Proxy test failed: {e}")


@api_router.post("/proxies/{proxy_id}/test")
async def test_stored_proxy(proxy_id: str, _user: str = Depends(require_auth)):
    p = await db.proxies.find_one({"id": proxy_id})
    if not p:
        raise HTTPException(status_code=404, detail="Proxy not found")
    try:
        await tg.test_proxy({"proxy_type": p["proxy_type"], "host": p["host"], "port": p["port"],
                             "username": p.get("username"), "password": p.get("password")})
        return {"ok": True, "message": f"{p['host']}:{p['port']} reaches Telegram."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Proxy test failed: {e}")


class ProxyAssign(BaseModel):
    batch_id: Optional[str] = None  # limit assignment to one section


@api_router.post("/proxies/assign")
async def assign_proxies(payload: ProxyAssign, _user: str = Depends(require_auth)):
    proxies = await db.proxies.find({}).sort("created_at", 1).to_list(10000)
    if not proxies:
        raise HTTPException(status_code=400, detail="No proxies loaded. Load a proxy list first.")
    query = {}
    if payload.batch_id:
        query["batch_id"] = payload.batch_id
    accounts = await db.accounts.find(query).to_list(20000)
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to assign proxies to.")
    n = len(proxies)
    assigned = 0
    for i, acc in enumerate(accounts):
        p = proxies[i % n]
        proxy_doc = {"proxy_type": p["proxy_type"], "host": p["host"], "port": p["port"],
                     "username": p.get("username"), "password": p.get("password")}
        await db.accounts.update_one(
            {"id": acc["id"]},
            {"$set": {"proxy": proxy_doc, "proxy_label": f"{p['host']}:{p['port']}"}})
        await tg.disconnect_client(acc["id"])  # force rebuild through the proxy
        assigned += 1
    return {"assigned": assigned, "proxies_used": n}


@api_router.post("/proxies/unassign")
async def unassign_proxies(payload: ProxyAssign, _user: str = Depends(require_auth)):
    query = {}
    if payload.batch_id:
        query["batch_id"] = payload.batch_id
    accounts = await db.accounts.find(query).to_list(20000)
    for acc in accounts:
        await db.accounts.update_one({"id": acc["id"]}, {"$unset": {"proxy": "", "proxy_label": ""}})
        await tg.disconnect_client(acc["id"])
    return {"unassigned": len(accounts)}


@api_router.get("/proxies/coverage")
async def proxy_coverage(_user: str = Depends(require_auth)):
    total = await db.accounts.count_documents({})
    with_proxy = await db.accounts.count_documents({"proxy": {"$exists": True}})
    proxy_count = await db.proxies.count_documents({})
    return {"total_accounts": total, "accounts_with_proxy": with_proxy, "proxy_count": proxy_count}


@api_router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, _user: str = Depends(require_auth)):
    acc = await db.accounts.find_one({"id": account_id})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    # stop campaigns of this account
    camps = await db.campaigns.find({"account_id": account_id}).to_list(1000)
    for c in camps:
        tg.stop_campaign_task(c["id"])
    await db.campaigns.update_many({"account_id": account_id}, {"$set": {"status": "stopped"}})
    await tg.disconnect_client(account_id)
    await db.accounts.delete_one({"id": account_id})
    return {"ok": True}


@api_router.delete("/campaigns/{campaign_id}/accounts")
async def delete_campaign_accounts(campaign_id: str, _user: str = Depends(require_auth)):
    """Delete only the account section used by this campaign (not every account)."""
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    batch_id = camp.get("account_batch_id")
    if not batch_id:
        raise HTTPException(
            status_code=400,
            detail="This campaign uses All accounts. Pick a campaign tied to a specific account section, or change the campaign section first.",
        )

    accounts = await db.accounts.find({"batch_id": batch_id}).to_list(20000)
    if not accounts:
        return {
            "ok": True,
            "deleted": 0,
            "campaign_name": camp.get("name"),
            "batch_name": camp.get("account_batch_name"),
            "message": "No accounts left in this campaign section",
        }

    # Stop this campaign and any other campaigns using the same section
    related = await db.campaigns.find({"account_batch_id": batch_id}).to_list(1000)
    for c in related:
        tg.stop_campaign_task(c["id"])
    await db.campaigns.update_many(
        {"account_batch_id": batch_id},
        {"$set": {"status": "stopped", "last_error": "Account section removed"}},
    )

    for acc in accounts:
        try:
            await tg.disconnect_client(acc["id"])
        except Exception:
            pass
    result = await db.accounts.delete_many({"batch_id": batch_id})

    return {
        "ok": True,
        "deleted": result.deleted_count,
        "campaign_name": camp.get("name"),
        "batch_name": camp.get("account_batch_name") or accounts[0].get("batch_name"),
    }


@api_router.get("/accounts/{account_id}/groups")
async def get_groups(account_id: str, _user: str = Depends(require_auth)):
    acc = await db.accounts.find_one({"id": account_id})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        groups = await tg.fetch_dialogs(acc)
        await db.accounts.update_one({"id": account_id}, {"$set": {"status": "connected"}})
        return groups
    except Exception as e:
        await db.accounts.update_one({"id": account_id}, {"$set": {"status": "disconnected"}})
        raise HTTPException(status_code=400, detail=f"Could not fetch groups: {e}")


class TestMessage(BaseModel):
    account_id: str
    target: str
    text: str


@api_router.post("/session-test")
async def session_test(payload: TestMessage, _user: str = Depends(require_auth)):
    acc = await db.accounts.find_one({"id": payload.account_id})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        c = await tg.get_client(acc)
        target = payload.target.strip()
        entity = int(target) if target.lstrip("-").isdigit() else target
        if not entity or entity == "me":
            entity = "me"
        await c.send_message(entity, payload.text)
        return {"ok": True, "message": "Test message sent successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Test failed: {e}")


# ----------------------- Upload -----------------------
@api_router.post("/upload")
async def upload_media(file: UploadFile = File(...), _user: str = Depends(require_auth)):
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "bin"
    path = f"{storage.APP_NAME}/uploads/{uuid.uuid4()}.{ext}"
    content = await file.read()
    content_type = file.content_type or storage.MIME_TYPES.get(ext, "application/octet-stream")
    result = await storage.put_object(path, content, content_type)
    stored_path = result["path"]
    await db.files.insert_one({
        "id": str(uuid.uuid4()),
        "storage_path": stored_path,
        "original_filename": file.filename,
        "content_type": content_type,
        "is_deleted": False,
        "created_at": now_iso(),
    })
    return {"media_path": stored_path, "media_url": f"/api/uploads/{stored_path}",
            "filename": file.filename}


@api_router.get("/uploads/{path:path}")
async def serve_upload(path: str, _user: str = Depends(require_auth)):
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Not found")
    data, content_type = await storage.get_object(path)
    ct = record.get("content_type", content_type)
    return StreamingResponse(io.BytesIO(data), media_type=ct)


# ----------------------- Campaign loop -----------------------
# Max accounts to try per group before moving on (keeps cycles within the interval).
MAX_ACCOUNT_TRIES = 12
# Unified concurrency constant — same value used in create_campaign and campaign_loop.
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", str(tg.CONCURRENCY)))

# ── Batched counter state ─────────────────────────────────────────────────
# campaign_id -> {"sent": int, "failed": int, "last_flush": float}
_counter_buffer: dict[str, dict] = {}
_COUNTER_FLUSH_INTERVAL = 30  # seconds


def _counter_add(campaign_id: str, field: str):
    buf = _counter_buffer.setdefault(campaign_id, {"sent": 0, "failed": 0, "last_flush": time.monotonic()})
    buf[field] += 1


async def _flush_counters():
    """Flush batched sent/failed counts to MongoDB (one write per campaign)."""
    now = time.monotonic()
    for cid, buf in list(_counter_buffer.items()):
        if buf["sent"] == 0 and buf["failed"] == 0:
            continue
        if now - buf["last_flush"] >= _COUNTER_FLUSH_INTERVAL:
            await db.campaigns.update_one(
                {"id": cid},
                {"$inc": {"sent_count": buf["sent"], "failed_count": buf["failed"]}}
            )
            buf["sent"] = buf["failed"] = 0
            buf["last_flush"] = now


async def _force_flush_counter(campaign_id: str):
    """Flush immediately (called on campaign stop)."""
    buf = _counter_buffer.pop(campaign_id, None)
    if buf and (buf["sent"] or buf["failed"]):
        await db.campaigns.update_one(
            {"id": campaign_id},
            {"$inc": {"sent_count": buf["sent"], "failed_count": buf["failed"]}}
        )


def _is_media_error_string(err: str) -> bool:
    """Check if an error string indicates a media restriction (group-level, not account-level)."""
    msg = (err or "").upper()
    return any(k in msg for k in (
        "MEDIA", "PHOTO", "VIDEO", "GIF", "STICKER", "VOICE",
        "SENDMEDIA", "SEND_MEDIA",
    )) and any(k in msg for k in ("FORBIDDEN", "BLOCKED", "RESTRICTED", "NOT ALLOWED"))


def _is_flood_error_string(err: str) -> bool:
    msg = (err or "").lower()
    return "flood" in msg or "wait of" in msg or "seconds is required" in msg


def _should_try_next_account(err: str) -> bool:
    """Returns True to rotate to next account. Returns False to abort (group/flood-level error).

    FloodWait: handled by cooldown — do NOT rotate (caller records cooldown and skips).
    Media restrictions: group-level — text fallback in telegram_service handles it.
    Note: "no user has" is NOT here — that was a join error, handled by _proactive_join now.
    """
    if _is_media_error_string(err):
        return False
    if _is_flood_error_string(err):
        return False  # Caller must record cooldown, not rotate

    msg = (err or "").lower()
    return any(p in msg for p in (
        "banned from send",
        "auth key",
        "you can't write",
        "chat_write_forbidden",
        "invalid peer",
        "not a member",
    ))


def _is_group_ban_error(err: str) -> bool:
    """True if the error means this specific account is banned/blocked in this specific group.
    NOT a permanent account ban — account is fine for other groups/campaigns."""
    msg = (err or "").lower()
    return any(p in msg for p in (
        "banned from send",
        "you can't write",
        "chat_write_forbidden",
        "chat admin privileges",
    ))


def _is_dead_group_error(err: str) -> bool:
    """True if the error means the group itself is deleted/inaccessible for ALL accounts.
    
    IMPORTANT: "no user has X as username" is NOT a dead group — it means the account
    wasn't a member and couldn't resolve it. After joining, it will work fine.
    Only mark dead when Telegram explicitly says the group/channel doesn't exist.
    """
    msg = (err or "").lower()
    return any(p in msg for p in (
        "peer_id_invalid",
        "channel_invalid",
        "chat_id_invalid",
        "the group has been deactivated",
        "groupdeactivated",
    ))

async def _send_to_group(campaign, accounts, start_idx, grp):
    """Deliver the ad to one group. Tries accounts in rotation; handles cooldowns and dedup."""
    success, last_err, used, note, last_acc = False, None, None, None, None
    grp_id = grp["id"]
    camp_id = campaign["id"]

    # Skip dead groups — no account can ever send to these
    if grp_id in _campaign_dead_groups.get(camp_id, set()):
        return

    # Filter: skip accounts in FloodWait cooldown
    ready_accounts = [a for a in accounts if not tg.is_account_in_cooldown(a["id"])]
    if not ready_accounts:
        await log_send(campaign, None, grp, "failed", "All accounts in FloodWait cooldown")
        return

    # Filter: skip accounts banned in this group for this campaign
    campaign_ban_set = _campaign_bans.get(camp_id, set())
    unbanned_accounts = [a for a in ready_accounts if (a["id"], grp_id) not in campaign_ban_set]
    if not unbanned_accounts:
        # All accounts have been banned in this group — skip silently
        return

    # Filter: cross-campaign dedup — skip (account, group) pairs already being sent
    dedup_accounts = [a for a in unbanned_accounts if (a["id"], grp_id) not in _active_sends]
    effective_accounts = dedup_accounts if dedup_accounts else unbanned_accounts

    n = len(effective_accounts)
    if n == 0:
        await log_send(campaign, None, grp, "failed", "No accounts available")
        return

    tries = min(n, MAX_ACCOUNT_TRIES)
    order = [effective_accounts[(start_idx + k) % n] for k in range(tries)]
    tried = 0
    for acc in order:
        last_acc = acc
        note = None
        tried += 1
        send_key = (acc["id"], grp_id)
        _active_sends.add(send_key)
        try:
            tclient = await asyncio.wait_for(tg.get_client(acc), timeout=tg.CLIENT_TIMEOUT)
            note = await asyncio.wait_for(
                tg.send_ad_to_group(tclient, grp_id, campaign, account_id=acc["id"]),
                timeout=tg.SEND_TIMEOUT + 5,  # +5 for jitter budget
            )
            used, success = acc, True
            if tried > 1:
                extra = f"Delivered after {tried} account tries"
                note = f"{note} · {extra}" if note else extra
            break
        except asyncio.TimeoutError:
            last_err = "Timed out (account/proxy unresponsive)"
        except asyncio.CancelledError:
            # Must re-raise — swallowing CancelledError prevents campaign from stopping.
            _active_sends.discard(send_key)
            raise
        except Exception as e:
            last_err = str(e)
            # Missing media: campaign-level issue — no account can fix it
            if isinstance(e, FileNotFoundError):
                break  # Stop trying — file is missing for ALL accounts
            # FloodWait: record cooldown, do NOT rotate accounts
            if tg._is_flood_error(e):
                seconds = getattr(e, "seconds", 60)
                tg.set_account_cooldown(acc["id"], seconds)
                break  # Stop trying accounts — it's rate limiting, not a bad account
            # Permanent ban: mark in DB
            if tg.is_permanent_ban(e):
                await db.accounts.update_one(
                    {"id": acc["id"]},
                    {"$set": {"status": "banned", "last_error": str(e)}}
                )
            # Per-campaign group ban: account banned/blocked in this group
            # Skip this (account, group) in future cycles of THIS campaign only
            elif _is_dead_group_error(str(e)):
                # Group itself is dead — mark for ALL accounts, stop trying
                _campaign_dead_groups.setdefault(camp_id, set()).add(grp_id)
                logger.info(f"Campaign {camp_id}: dead group {grp_id} — skipping in future cycles")
                break  # No point trying more accounts
            elif _is_group_ban_error(str(e)):
                _campaign_bans.setdefault(camp_id, set()).add((acc["id"], grp_id))
                logger.info(
                    f"Campaign {camp_id}: banned {acc.get('name',acc['id'])} "
                    f"from {grp_id} — will skip in future cycles"
                )
        finally:
            _active_sends.discard(send_key)

        if not success and last_err and _should_try_next_account(last_err):
            continue

    if success:
        await log_send(campaign, used, grp, "success", note)
        _counter_add(camp_id, "sent")
    else:
        detail = f"All {tried} accounts failed"
        if n > tries:
            detail = f"{detail} (tried {tries}/{n})"
        if last_err:
            detail = f"{detail} — last error: {last_err}"
        await log_send(campaign, last_acc, grp, "failed", detail)
        _counter_add(camp_id, "failed")


async def campaign_loop(campaign_id: str):
    """Broadcast to ALL target groups in parallel (many accounts at once), then wait
    the interval and repeat. Accounts are loaded via cursor (no silent cap).
    FloodWait is handled per-account with cooldowns; CancelledError propagates correctly.
    """
    try:
        while True:
            campaign = await db.campaigns.find_one({"id": campaign_id})
            if not campaign or campaign.get("status") != "running":
                break

            query = {"status": {"$ne": "banned"}}  # skip banned accounts
            if campaign.get("account_batch_id"):
                query["batch_id"] = campaign["account_batch_id"]

            # Paginate accounts via cursor — no silent to_list(N) cap
            accounts = []
            async for acc in db.accounts.find(query):
                accounts.append(acc)
            if len(accounts) > 1000:
                logger.warning(
                    f"Campaign {campaign.get('name')}: {len(accounts)} accounts loaded — "
                    f"consider splitting into sections for better performance"
                )

            interval = max(1, int(campaign.get("interval_seconds", 60)))

            if not accounts:
                await db.campaigns.update_one({"id": campaign_id},
                    {"$set": {"status": "stopped", "last_error": "No accounts available in the selected section."}})
                break

            random.shuffle(accounts)
            groups = campaign["target_groups"]
            # Use unified MAX_CONCURRENCY — same cap in create_campaign and here
            conc = max(1, min(MAX_CONCURRENCY, int(campaign.get("concurrency", tg.CONCURRENCY))))
            sem = asyncio.Semaphore(conc)
            dead_count = len(_campaign_dead_groups.get(campaign_id, set()))
            ban_count = len(_campaign_bans.get(campaign_id, set()))
            live_groups = len(groups) - dead_count
            logger.info(
                f"Campaign {campaign.get('name')} cycle start: "
                f"{live_groups}/{len(groups)} live groups ({dead_count} dead), "
                f"{len(accounts)} accounts ({ban_count} group-bans), conc={conc}, interval={interval}s"
            )

            async def bounded(i, grp):
                try:
                    async with sem:
                        await _send_to_group(campaign, accounts, i, grp)
                except asyncio.CancelledError:
                    # Re-raise — swallowing prevents the campaign from stopping cleanly
                    raise
                except Exception as e:
                    await log_send(campaign, None, grp, "failed", str(e))

            await asyncio.gather(
                *[bounded(i, g) for i, g in enumerate(groups)],
                return_exceptions=True,
            )
            # Flush batched counters every cycle
            await _flush_counters()
            # Persist dead groups + ban stats to campaign doc for frontend visibility
            dead_grps = _campaign_dead_groups.get(campaign_id, set())
            ban_pairs = _campaign_bans.get(campaign_id, set())
            await db.campaigns.update_one({"id": campaign_id}, {"$set": {
                "last_run": now_iso(),
                "dead_groups_count": len(dead_grps),
                "banned_pairs_count": len(ban_pairs),
                "dead_group_ids": list(dead_grps),
            }})
            logger.info(
                f"Campaign {campaign.get('name')} cycle done — "
                f"{len(dead_grps)} dead groups, {len(ban_pairs)} account bans — sleeping {interval}s"
            )

            fresh = await db.campaigns.find_one({"id": campaign_id})
            if not fresh or fresh.get("status") != "running":
                break
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info(f"Campaign {campaign_id} loop cancelled")
        await _force_flush_counter(campaign_id)
    except Exception as e:
        logger.error(f"Campaign {campaign_id} crashed: {e}")
        await _force_flush_counter(campaign_id)
        await db.campaigns.update_one({"id": campaign_id},
            {"$set": {"status": "stopped", "last_error": f"Crashed: {e}"}})
    finally:
        # Clean up per-campaign maps — new campaign start = fresh slate
        bans = _campaign_bans.pop(campaign_id, set())
        dead = _campaign_dead_groups.pop(campaign_id, set())
        if bans or dead:
            logger.info(f"Campaign {campaign_id}: cleared {len(bans)} account-group bans, {len(dead)} dead groups")


async def log_send(campaign, acc, grp, status, error):
    entry = {
        "id": str(uuid.uuid4()),
        "campaign_id": campaign["id"],
        "campaign_name": campaign["name"],
        "account_id": acc["id"] if acc else None,
        "account_name": acc["name"] if acc else "—",
        "group_id": grp["id"],
        "group_title": grp["title"],
        "status": status,
        "error": error,
        "timestamp": now_iso(),
    }
    await db.logs.insert_one(entry)


def start_campaign_task(campaign_id: str):
    existing = tg._campaign_tasks.get(campaign_id)
    if existing is not None and existing.done():
        tg._campaign_tasks.pop(campaign_id, None)
    if tg.is_campaign_running(campaign_id):
        return
    task = asyncio.create_task(campaign_loop(campaign_id))
    tg._campaign_tasks[campaign_id] = task
    logger.info(f"Started campaign loop task for {campaign_id}")


# campaign_id -> retry count for watchdog restarts
_watchdog_retry_counts: dict[str, int] = {}
_WATCHDOG_MAX_RETRIES = 3


async def _campaign_watchdog():
    """Restart campaign loops that died while DB status is still 'running'.

    Uses retry-with-backoff: 3 attempts before permanently marking stopped.
    This prevents a transient error from killing the campaign permanently on first crash.
    """
    while True:
        try:
            await asyncio.sleep(30)
            running = await db.campaigns.find({"status": "running"}).to_list(100)
            running_ids = {c["id"] for c in running}
            # Clean up retry counts for campaigns no longer running
            for cid in list(_watchdog_retry_counts):
                if cid not in running_ids:
                    _watchdog_retry_counts.pop(cid, None)
            for c in running:
                cid = c["id"]
                if not tg.is_campaign_running(cid):
                    retries = _watchdog_retry_counts.get(cid, 0)
                    if retries < _WATCHDOG_MAX_RETRIES:
                        logger.warning(
                            f"Campaign '{c.get('name')}' dead — restart attempt {retries + 1}/{_WATCHDOG_MAX_RETRIES}"
                        )
                        _watchdog_retry_counts[cid] = retries + 1
                        start_campaign_task(cid)
                    else:
                        logger.error(
                            f"Campaign '{c.get('name')}' failed {_WATCHDOG_MAX_RETRIES} restart attempts — marking stopped"
                        )
                        _watchdog_retry_counts.pop(cid, None)
                        await db.campaigns.update_one(
                            {"id": cid},
                            {"$set": {"status": "stopped", "last_error": f"Watchdog gave up after {_WATCHDOG_MAX_RETRIES} restarts"}}
                        )
                else:
                    # Campaign is healthy — reset retry counter
                    _watchdog_retry_counts.pop(cid, None)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Campaign watchdog error: {e}")


# ----------------------- Campaign routes -----------------------
@api_router.post("/campaigns")
async def create_campaign(payload: CampaignCreate, _user: str = Depends(require_auth)):
    groups = []
    for raw in payload.target_groups:
        g = raw.strip()
        if g:
            groups.append({"id": g, "title": g})
    if not groups:
        raise HTTPException(status_code=400, detail="Add at least one target group")

    batch_name = None
    if payload.account_batch_id:
        one = await db.accounts.find_one({"batch_id": payload.account_batch_id})
        if not one:
            raise HTTPException(status_code=400, detail="Selected account section not found")
        batch_name = one.get("batch_name")

    camp = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "message_type": payload.message_type,
        "text": payload.text,
        "media_path": payload.media_path,
        "media_url": payload.media_url,
        "media_filename": payload.media_filename,
        "forward_link": payload.forward_link,
        "target_groups": groups,
        "interval_seconds": payload.interval_seconds,
        "account_batch_id": payload.account_batch_id,
        "account_batch_name": batch_name,
        "concurrency": max(1, min(MAX_CONCURRENCY, payload.concurrency)),
        "status": "stopped",
        "sent_count": 0,
        "failed_count": 0,
        "last_run": None,
        "last_error": None,
        "created_at": now_iso(),
    }
    await db.campaigns.insert_one(camp)
    camp.pop("_id", None)
    return camp


@api_router.get("/campaigns")
async def list_campaigns(_user: str = Depends(require_auth)):
    docs = await db.campaigns.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    for d in docs:
        d["running"] = tg.is_campaign_running(d["id"])
    return docs


@api_router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, payload: CampaignCreate, _user: str = Depends(require_auth)):
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    groups = [{"id": g.strip(), "title": g.strip()} for g in payload.target_groups if g.strip()]
    if not groups:
        raise HTTPException(status_code=400, detail="Add at least one target group")

    batch_name = None
    if payload.account_batch_id:
        one = await db.accounts.find_one({"batch_id": payload.account_batch_id})
        if not one:
            raise HTTPException(status_code=400, detail="Selected account section not found")
        batch_name = one.get("batch_name")

    updates = {
        "name": payload.name,
        "message_type": payload.message_type,
        "text": payload.text,
        "media_path": payload.media_path,
        "media_url": payload.media_url,
        "media_filename": payload.media_filename,
        "forward_link": payload.forward_link,
        "target_groups": groups,
        "interval_seconds": payload.interval_seconds,
        "account_batch_id": payload.account_batch_id,
        "account_batch_name": batch_name,
        "concurrency": max(1, min(100, payload.concurrency)),
    }
    await db.campaigns.update_one({"id": campaign_id}, {"$set": updates})
    updated = await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})
    updated["running"] = tg.is_campaign_running(campaign_id)
    return updated


@api_router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str, _user: str = Depends(require_auth)):
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.campaigns.update_one({"id": campaign_id}, {"$set": {"status": "running", "last_error": None}})
    start_campaign_task(campaign_id)
    return {"ok": True, "status": "running"}


@api_router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: str, _user: str = Depends(require_auth)):
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.campaigns.update_one({"id": campaign_id}, {"$set": {"status": "stopped", "next_run": None}})
    tg.stop_campaign_task(campaign_id)
    return {"ok": True, "status": "stopped"}


@api_router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, _user: str = Depends(require_auth)):
    tg.stop_campaign_task(campaign_id)
    await db.campaigns.delete_one({"id": campaign_id})
    return {"ok": True}


@api_router.get("/campaigns/{campaign_id}/targets-health")
async def targets_health(campaign_id: str, _user: str = Depends(require_auth)):
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$sort": {"timestamp": 1}},
        {"$group": {
            "_id": "$group_id",
            "success": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "last_status": {"$last": "$status"},
            "last_error": {"$last": "$error"},
            "last_ts": {"$last": "$timestamp"},
            "title": {"$last": "$group_title"},
        }},
    ]
    rows = await db.logs.aggregate(pipeline).to_list(10000)
    by_id = {r["_id"]: r for r in rows}
    result = []
    for g in camp.get("target_groups", []):
        r = by_id.get(g["id"])
        if r:
            result.append({
                "id": g["id"],
                "title": g.get("title") or r.get("title") or g["id"],
                "success": r["success"],
                "failed": r["failed"],
                "last_status": r["last_status"],
                "last_error": r["last_error"],
                "last_ts": r["last_ts"],
                "health": "dead" if (r["success"] == 0 and r["failed"] > 0) else ("failing" if r["failed"] > 0 else "ok"),
            })
        else:
            result.append({
                "id": g["id"], "title": g.get("title") or g["id"],
                "success": 0, "failed": 0, "last_status": None,
                "last_error": None, "last_ts": None, "health": "unknown",
            })
    # dead/failing first
    order = {"dead": 0, "failing": 1, "unknown": 2, "ok": 3}
    result.sort(key=lambda x: (order.get(x["health"], 4), -x["failed"]))
    return result


@api_router.get("/campaigns/{campaign_id}/bans")
async def campaign_bans(campaign_id: str, _user: str = Depends(require_auth)):
    """Return the in-memory list of (account, group) bans for this campaign."""
    bans = _campaign_bans.get(campaign_id, set())
    return [{"account_id": a, "group_id": g} for a, g in bans]


class RemoveGroups(BaseModel):
    group_ids: List[str]


@api_router.post("/campaigns/{campaign_id}/remove-groups")
async def remove_groups(campaign_id: str, payload: RemoveGroups, _user: str = Depends(require_auth)):
    camp = await db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not payload.group_ids:
        raise HTTPException(status_code=400, detail="No groups specified")
    await db.campaigns.update_one(
        {"id": campaign_id},
        {"$pull": {"target_groups": {"id": {"$in": payload.group_ids}}}})
    updated = await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})
    updated["running"] = tg.is_campaign_running(campaign_id)
    return updated


# ----------------------- Logs & Stats -----------------------
# Auto-purge keeps Mongo RAM/disk low so multiple campaigns can run on a small VPS.
LOG_MAX_AGE_HOURS = 6
LOG_MAX_KEEP = 2500
LOG_CLEANUP_INTERVAL_SEC = 600
LOG_DELETE_BATCH = 5000

_stats_cache = {"data": None, "ts": 0.0}


async def cleanup_old_logs() -> int:
    """Drop logs older than LOG_MAX_AGE_HOURS, then trim to LOG_MAX_KEEP newest entries."""
    removed = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOG_MAX_AGE_HOURS)).isoformat()
    while True:
        res = await db.logs.delete_many({"timestamp": {"$lt": cutoff}})
        removed += res.deleted_count
        if res.deleted_count < LOG_DELETE_BATCH:
            break

    while True:
        count = await db.logs.count_documents({})
        excess = count - LOG_MAX_KEEP
        if excess <= 0:
            break
        batch = min(excess, LOG_DELETE_BATCH)
        oldest = await db.logs.find({}, {"_id": 1}).sort("timestamp", 1).limit(batch).to_list(batch)
        if not oldest:
            break
        res = await db.logs.delete_many({"_id": {"$in": [d["_id"] for d in oldest]}})
        removed += res.deleted_count
        if res.deleted_count == 0:
            break

    if removed:
        _stats_cache["data"] = None
        logger.info(f"Log cleanup removed {removed} entries (keep {LOG_MAX_KEEP}, max age {LOG_MAX_AGE_HOURS}h)")
    return removed


async def _log_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(LOG_CLEANUP_INTERVAL_SEC)
            await cleanup_old_logs()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Log cleanup error: {e}")


async def backfill_failed_counts():
    """One-time migration: copy failed totals from logs onto campaigns before log purge."""
    missing = await db.campaigns.count_documents({"failed_count": {"$exists": False}})
    if not missing:
        return
    rows = await db.logs.aggregate([
        {"$match": {"status": "failed"}},
        {"$group": {"_id": "$campaign_id", "n": {"$sum": 1}}},
    ]).to_list(1000)
    by_id = {r["_id"]: r["n"] for r in rows}
    async for camp in db.campaigns.find({"failed_count": {"$exists": False}}, {"id": 1}):
        await db.campaigns.update_one(
            {"id": camp["id"]},
            {"$set": {"failed_count": by_id.get(camp["id"], 0)}},
        )


@api_router.get("/logs")
async def get_logs(limit: int = 200, _user: str = Depends(require_auth)):
    limit = max(1, min(500, limit))
    docs = await db.logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return docs


@api_router.delete("/logs")
async def clear_logs(_user: str = Depends(require_auth)):
    await db.logs.delete_many({})
    _stats_cache["data"] = None
    return {"ok": True}


@api_router.get("/stats")
async def get_stats(_user: str = Depends(require_auth)):
    import time
    now = time.monotonic()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 15:
        return _stats_cache["data"]

    total_accounts = await db.accounts.count_documents({})
    total_campaigns = await db.campaigns.count_documents({})
    active_campaigns = await db.campaigns.count_documents({"status": "running"})
    totals = await db.campaigns.aggregate([
        {"$group": {
            "_id": None,
            "sent": {"$sum": {"$ifNull": ["$sent_count", 0]}},
            "failed": {"$sum": {"$ifNull": ["$failed_count", 0]}},
        }},
    ]).to_list(1)
    total_sent = totals[0]["sent"] if totals else 0
    total_failed = totals[0]["failed"] if totals else 0
    total_attempts = total_sent + total_failed
    success_rate = round((total_sent / total_attempts) * 100, 1) if total_attempts else 100.0
    data = {
        "total_accounts": total_accounts,
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "total_sent": total_sent,
        "total_failed": total_failed,
        "success_rate": success_rate,
    }
    _stats_cache["data"] = data
    _stats_cache["ts"] = now
    return data


@api_router.get("/")
async def root():
    return {"message": "OpenAds Ad Platform API"}


# ── App lifecycle (replaces deprecated @app.on_event) ─────────────────
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown logic using the modern lifespan pattern."""
    # ── STARTUP ──
    if storage._use_cloud():
        try:
            await storage.init_storage()
            logger.info("Cloud object storage initialized")
        except Exception as e:
            logger.error(f"Cloud storage init failed: {e}")
    else:
        logger.info(f"Using local media storage at {storage.LOCAL_ROOT}")

    # Database indexes (non-fatal — app works without them, they're perf optimizations)
    try:
        await db.logs.create_index([("timestamp", -1)])
        await db.logs.create_index([("status", 1)])
        await db.logs.create_index([("campaign_id", 1)])
        await db.logs.create_index([("campaign_id", 1), ("timestamp", -1)])
        await db.accounts.create_index("id", unique=True)
        await db.accounts.create_index("batch_id")
        await db.accounts.create_index("status")
        await db.campaigns.create_index("id", unique=True)
        await db.campaigns.create_index("status")
        await db.proxies.create_index("id", unique=True)
        logger.info("Database indexes ensured")
    except Exception as e:
        logger.warning(f"Index creation skipped (non-fatal): {e}")

    # Backfill account sections for accounts uploaded before batch tracking existed.
    try:
        NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")
        legacy = await db.accounts.find({"batch_id": {"$exists": False}}).to_list(10000)
        migrated = 0
        for acc in legacy:
            prefix = (acc.get("name") or "Ungrouped").split(" - ")[0].strip() or "Ungrouped"
            bid = str(uuid.uuid5(NS, prefix))
            await db.accounts.update_one({"id": acc["id"]}, {"$set": {"batch_id": bid, "batch_name": prefix}})
            migrated += 1
        if migrated:
            logger.info(f"Backfilled sections for {migrated} legacy accounts")

        await backfill_failed_counts()
        removed = await cleanup_old_logs()
        if removed:
            logger.info(f"Startup log purge freed {removed} old log entries")
    except Exception as e:
        logger.warning(f"Startup migrations skipped (non-fatal): {e}")

    running = await db.campaigns.find({"status": "running"}).to_list(1000)
    for c in running:
        start_campaign_task(c["id"])
    logger.info(f"Resumed {len(running)} running campaigns")
    asyncio.create_task(_campaign_watchdog())
    asyncio.create_task(_log_cleanup_loop())

    yield  # ← App is running

    # ── SHUTDOWN ──
    await tg.disconnect_all_clients()
    client.close()
    logger.info("Shutdown complete")


# ── App assembly ──────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)

app.include_router(api_router)

_cors_origins_raw = os.environ.get('CORS_ORIGINS', 'http://localhost:3000').strip()
# Never use '*' with allow_credentials=True — browsers reject credentialed cross-origin requests
# and it's a wide-open security hole. Use explicit origins instead.
if _cors_origins_raw == '*':
    logger.warning(
        "CORS_ORIGINS=* with credentials is invalid. Falling back to http://localhost:3000. "
        "Set CORS_ORIGINS to your actual frontend domain in production."
    )
    _cors_origins = ["http://localhost:3000"]
else:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
