"""Telethon client management + ad sending logic.

Key reliability features:
- Per-account FloodWait cooldowns: flooded accounts are skipped, NOT rotated.
- FloodWait ≠ ban: cooldown is temporary. Only auth/deactivate errors = banned.
- Per-send jitter (2–5s) prevents spam-flag on same account.
- Media LRU cache (20 entries): same file is not re-fetched from storage every send.
- TTLCache for join attempts: auto-expires after 24h, preventing unbounded RAM growth.
- MAX_CACHED_CLIENTS is env-configurable (default 50).
"""
import asyncio
import io
import logging
import os
import random
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone

import python_socks
from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy
from telethon import TelegramClient
from telethon import errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat, User

import storage

logger = logging.getLogger(__name__)

# ── In-process state ─────────────────────────────────────────────────────────
# account_id -> connected TelegramClient
_clients: dict[str, TelegramClient] = {}
# account_id -> lock guarding client creation
_client_locks: dict[str, asyncio.Lock] = {}
# account_id -> lock guarding join attempts (prevents parallel joins from same account)
_join_locks: dict[str, asyncio.Lock] = {}
# (account_id, group_key) pairs already joined this session — TTL 24h, max 50k entries
# Using simple dict with manual TTL since cachetools may not be installed
_join_attempted: dict[tuple[str, str], float] = {}
_JOIN_TTL_SECONDS = 86400  # 24 hours
_JOIN_MAX_ENTRIES = 50_000
# campaign_id -> asyncio.Task
_campaign_tasks: dict[str, asyncio.Task] = {}

# ── FloodWait cooldowns ───────────────────────────────────────────────────────
# account_id -> monotonic timestamp when cooldown expires
_account_cooldowns: dict[str, float] = {}

# ── Media LRU cache ──────────────────────────────────────────────────────────
# Keyed by storage path. Evicts LRU when > MAX_MEDIA_CACHE entries.
_media_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_MEDIA_CACHE_MAX = 20

# Injected by server.py at startup — allows MongoDB-aware media fetch
# without circular imports. Falls back to storage.get_object.
_media_fetcher = None


def set_media_fetcher(fetcher):
    """Inject a custom async media fetcher: async (path: str) -> (bytes, str).
    Called at app startup by server.py to use MongoDB-stored files.
    """
    global _media_fetcher
    _media_fetcher = fetcher


# ── Tunables ─────────────────────────────────────────────────────────────────
CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "12"))
# Keep at most this many Telegram sessions connected
MAX_CACHED_CLIENTS = int(os.environ.get("MAX_CLIENTS", "50"))
# Per-attempt time-boxes (seconds) so a dead account/proxy can't stall a cycle
CLIENT_TIMEOUT = 20
SEND_TIMEOUT = 30

# account_id -> last used monotonic time (for LRU eviction)
_client_last_used: dict[str, float] = {}

_PROXY_TYPES = {"socks5": ProxyType.SOCKS5, "socks4": ProxyType.SOCKS4, "http": ProxyType.HTTP}


# ── Errors classified as PERMANENT bans (mark account banned in DB) ──────────
# FloodWait is NOT here — it's temporary, handle with cooldown only.
_PERMANENT_BAN_TYPES = (
    "UserDeactivatedBanError",
    "UserDeactivatedError",
    "AuthKeyUnregisteredError",
    "AuthKeyInvalidError",
    "AuthKeyDuplicatedError",
    "SessionExpiredError",
    "SessionRevokedError",
)


def is_permanent_ban(exc: Exception) -> bool:
    """True only for permanent account termination errors — NOT FloodWait."""
    return type(exc).__name__ in _PERMANENT_BAN_TYPES


def is_account_in_cooldown(account_id: str) -> bool:
    """True if this account is in a FloodWait cooldown period."""
    until = _account_cooldowns.get(account_id)
    if until is None:
        return False
    if time.monotonic() >= until:
        _account_cooldowns.pop(account_id, None)
        return False
    return True


def set_account_cooldown(account_id: str, seconds: int):
    """Record a FloodWait cooldown for an account."""
    _account_cooldowns[account_id] = time.monotonic() + max(seconds, 1)
    logger.warning(f"Account {account_id} in FloodWait cooldown for {seconds}s")


def get_cooldown_remaining(account_id: str) -> float:
    """Seconds remaining in cooldown, or 0 if not in cooldown."""
    until = _account_cooldowns.get(account_id)
    if until is None:
        return 0
    remaining = until - time.monotonic()
    return max(0, remaining)


# ── Join-attempted TTL cache helpers ─────────────────────────────────────────

def _join_key_is_fresh(key: tuple) -> bool:
    ts = _join_attempted.get(key)
    return ts is not None and (time.time() - ts) < _JOIN_TTL_SECONDS


def _mark_join_attempted(key: tuple):
    if len(_join_attempted) >= _JOIN_MAX_ENTRIES:
        # Evict oldest 10% to make room
        cutoff = time.time() - _JOIN_TTL_SECONDS
        stale = [k for k, ts in _join_attempted.items() if ts < cutoff]
        for k in stale[:max(1, _JOIN_MAX_ENTRIES // 10)]:
            _join_attempted.pop(k, None)
    _join_attempted[key] = time.time()


def cleanup_join_cache_for_accounts(account_ids: set):
    """Remove join-cache entries for a set of account IDs (called on campaign stop)."""
    to_remove = [k for k in _join_attempted if k[0] in account_ids]
    for k in to_remove:
        _join_attempted.pop(k, None)
    # Also prune their locks
    for aid in account_ids:
        _client_locks.pop(aid, None)
        _join_locks.pop(aid, None)


# ── Media cache helpers ───────────────────────────────────────────────────────

async def _get_cached_media(media_path: str) -> tuple[bytes, str]:
    """Fetch media bytes, using in-process LRU cache to avoid re-downloading per-group."""
    if media_path in _media_cache:
        # Move to end (most recently used)
        _media_cache.move_to_end(media_path)
        return _media_cache[media_path]

    # Use injected fetcher (MongoDB-aware) if set, otherwise fall back to storage.get_object
    fetcher = _media_fetcher or storage.get_object
    data, content_type = await fetcher(media_path)

    # Evict LRU if at capacity
    while len(_media_cache) >= _MEDIA_CACHE_MAX:
        _media_cache.popitem(last=False)

    _media_cache[media_path] = (data, content_type)
    return data, content_type


def invalidate_media_cache(media_path: str = None):
    """Invalidate a specific or all cached media entries."""
    if media_path:
        _media_cache.pop(media_path, None)
    else:
        _media_cache.clear()


# ── Proxy helpers ─────────────────────────────────────────────────────────────

def parse_proxy_line(line: str, default_type: str = "socks5"):
    """Parse a proxy line into a dict. Supports:
    user:pass@host:port | host:port | host:port:user:pass | scheme://... prefix."""
    line = (line or "").strip()
    if not line:
        return None
    ptype = default_type
    m = re.match(r"^(socks5|socks4|http)://(.*)$", line, re.I)
    if m:
        ptype, line = m.group(1).lower(), m.group(2)
    user = pwd = None
    if "@" in line:
        cred, hostport = line.rsplit("@", 1)
        if ":" in cred:
            user, pwd = cred.split(":", 1)
    else:
        hostport = line
    parts = hostport.split(":")
    if len(parts) == 2:
        host, port = parts
    elif len(parts) == 4:
        host, port, user, pwd = parts
    else:
        return None
    if not port.isdigit():
        return None
    return {"proxy_type": ptype, "host": host, "port": int(port), "username": user or None, "password": pwd or None}


def _proxy_tuple(p):
    if not p:
        return None
    ptype = _PROXY_TYPES.get(p.get("proxy_type", "socks5"), ProxyType.SOCKS5)
    return (ptype, p["host"], int(p["port"]), True, p.get("username"), p.get("password"))


async def test_proxy(p, timeout: int = 15) -> None:
    """Raise if the proxy can't reach Telegram, else return None."""
    ptype = _PROXY_TYPES.get(p.get("proxy_type", "socks5"), ProxyType.SOCKS5)
    proxy = Proxy(proxy_type=ptype, host=p["host"], port=int(p["port"]),
                  username=p.get("username"), password=p.get("password"))
    sock = await asyncio.wait_for(
        proxy.connect(dest_host="149.154.167.51", dest_port=443), timeout=timeout)
    try:
        sock.close()
    except Exception:
        pass


# ── Client lifecycle ──────────────────────────────────────────────────────────

async def build_client(api_id: int, api_hash: str, session_string: str, proxy=None) -> TelegramClient:
    kwargs = {}
    ptuple = _proxy_tuple(proxy)
    if ptuple:
        kwargs["proxy"] = ptuple
    client = TelegramClient(StringSession(session_string), api_id, api_hash, **kwargs)
    await client.connect()
    return client


async def get_client(account: dict) -> TelegramClient:
    """Return a connected+authorized client for an account, caching it (concurrency-safe).

    On auth failure: raises ValueError (caller should mark account status).
    Does NOT mark as banned here — caller decides based on error type.
    """
    acc_id = account["id"]
    existing = _clients.get(acc_id)
    if existing is not None and existing.is_connected():
        _client_last_used[acc_id] = time.monotonic()
        return existing
    lock = _client_locks.setdefault(acc_id, asyncio.Lock())
    async with lock:
        existing = _clients.get(acc_id)
        if existing is not None and existing.is_connected():
            _client_last_used[acc_id] = time.monotonic()
            return existing
        await _evict_clients_if_needed(keep=acc_id)
        client = await build_client(int(account["api_id"]), account["api_hash"],
                                    account["session_string"], proxy=account.get("proxy"))
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError("Session is not authorized.")
        _clients[acc_id] = client
        _client_last_used[acc_id] = time.monotonic()
        return client


async def _evict_clients_if_needed(keep: str = None):
    """Drop oldest cached Telegram sessions when over the memory-safe limit."""
    if len(_clients) < MAX_CACHED_CLIENTS:
        return
    victims = sorted(
        (aid for aid in _clients if aid != keep),
        key=lambda aid: _client_last_used.get(aid, 0),
    )
    for aid in victims[: max(1, len(_clients) - MAX_CACHED_CLIENTS + 1)]:
        await disconnect_client(aid)


async def release_client(account_id: str):
    """Disconnect after a send attempt so hundreds of sessions don't stay in RAM."""
    await disconnect_client(account_id)
    _client_last_used.pop(account_id, None)


async def disconnect_all_clients():
    for aid in list(_clients.keys()):
        await disconnect_client(aid)
    _client_last_used.clear()


async def disconnect_client(account_id: str):
    client = _clients.pop(account_id, None)
    _client_last_used.pop(account_id, None)
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


async def validate_account(api_id: int, api_hash: str, session_string: str) -> dict:
    """Validate a session string and return the account's own profile info."""
    client = await build_client(api_id, api_hash, session_string)
    try:
        if not await client.is_user_authorized():
            raise ValueError("Session string is not authorized.")
        me = await client.get_me()
        name = " ".join(filter(None, [me.first_name, me.last_name])) or "Unknown"
        return {
            "phone": me.phone,
            "username": me.username,
            "display_name": name,
            "telegram_id": me.id,
        }
    finally:
        await client.disconnect()


async def session_file_to_string(file_bytes: bytes, api_id: int, api_hash: str):
    """Load a Telethon .session (SQLite) file, validate it, and convert to a StringSession.

    Returns (string_session, profile_info).
    """
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "acc")
        with open(base + ".session", "wb") as f:
            f.write(file_bytes)
        client = TelegramClient(base, int(api_id), api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise ValueError("Session file is not authorized / not logged in.")
            me = await client.get_me()
            name = " ".join(filter(None, [me.first_name, me.last_name])) or "Unknown"
            string_session = StringSession.save(client.session)
            info = {
                "phone": me.phone,
                "username": me.username,
                "display_name": name,
                "telegram_id": me.id,
            }
            return string_session, info
        finally:
            await client.disconnect()


async def fetch_dialogs(account: dict) -> list[dict]:
    """Fetch groups / supergroups / channels the account belongs to."""
    client = await get_client(account)
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, User):
            continue
        if isinstance(entity, Chat):
            dtype = "group"
            participants = getattr(entity, "participants_count", None)
        elif isinstance(entity, Channel):
            dtype = "channel" if getattr(entity, "broadcast", False) else "supergroup"
            participants = getattr(entity, "participants_count", None)
        else:
            continue
        dialogs.append({
            "id": str(dialog.id),
            "title": dialog.name or "Untitled",
            "type": dtype,
            "participants": participants,
            "username": getattr(entity, "username", None),
        })
    return dialogs


def _parse_forward_link(link: str):
    """Parse a t.me message link into (entity, message_id)."""
    link = link.strip()
    m = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    if m:
        return int("-100" + m.group(1)), int(m.group(2))
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", link)
    if m:
        return m.group(1), int(m.group(2))
    raise ValueError("Invalid forward link. Use a t.me message link e.g. https://t.me/channel/123")


def _normalize_target(raw: str):
    """Turn pasted group identifiers into a Telethon-friendly target."""
    parsed = _parse_group_identifier(raw)
    if parsed["kind"] == "username":
        return parsed["username"]
    if parsed["kind"] == "numeric":
        return parsed["id"]
    if parsed["kind"] == "invite":
        return parsed["raw"]
    return str(raw).strip()


def _parse_group_identifier(raw: str) -> dict:
    raw = str(raw).strip()
    m = re.match(r"https?://(?:www\.)?t\.me/(?:\+|joinchat/)([A-Za-z0-9_-]+)", raw, re.I)
    if m:
        return {"kind": "invite", "invite_hash": m.group(1), "raw": raw}
    m = re.match(r"https?://(?:www\.)?t\.me/([A-Za-z0-9_]+)/?", raw, re.I)
    if m:
        return {"kind": "username", "username": f"@{m.group(1)}", "raw": raw}
    if raw.startswith("@"):
        return {"kind": "username", "username": raw, "raw": raw}
    if raw.lstrip("-").isdigit():
        return {"kind": "numeric", "id": int(raw), "raw": raw}
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw):
        return {"kind": "username", "username": f"@{raw}", "raw": raw}
    return {"kind": "unknown", "raw": raw}


async def _is_member(client: TelegramClient, entity: Channel) -> bool:
    try:
        me = await client.get_me()
        await client(GetParticipantRequest(channel=entity, participant=me))
        return True
    except errors.UserNotParticipantError:
        return False
    except Exception:
        return False


async def _join_channel_entity(client: TelegramClient, entity: Channel):
    """Join a public channel/supergroup. Returns optional status note."""
    try:
        await client(JoinChannelRequest(entity))
        return "Joined group before sending"
    except errors.UserAlreadyParticipantError:
        return None
    except errors.InviteRequestSentError:
        return "Join request sent — waiting for admin approval"
    except errors.FloodWaitError as e:
        logger.warning(f"Join rate-limited ({e.seconds}s) — will try sending anyway")
        return None
    except errors.RPCError as e:
        if _is_flood_error(e):
            return None
        raise


async def _join_discussion_group(client: TelegramClient, channel: Channel):
    """Channels with comments require joining the linked discussion group first."""
    try:
        full = await client(GetFullChannelRequest(channel))
        linked_id = getattr(full.full_chat, "linked_chat_id", None)
        if not linked_id:
            return None
        linked = await client.get_entity(linked_id)
        if isinstance(linked, Channel):
            if await _is_member(client, linked):
                return None
            return await _join_channel_entity(client, linked)
    except errors.FloodWaitError:
        return None
    except Exception as e:
        logger.warning(f"Could not join linked discussion group: {e}")
    return None


def _group_cache_key(group_id: str) -> str:
    parsed = _parse_group_identifier(group_id)
    return str(parsed.get("username") or parsed.get("id") or parsed.get("raw") or group_id).lower()


async def _try_join(client: TelegramClient, account_id: str, group_id: str, entity) -> str | None:
    """Join a group once per account/session. Skips if already a member."""
    if not account_id:
        return None
    cache_key = (account_id, _group_cache_key(group_id))
    lock = _join_locks.setdefault(account_id, asyncio.Lock())
    async with lock:
        if _join_key_is_fresh(cache_key):
            return None
        _mark_join_attempted(cache_key)

        parsed = _parse_group_identifier(group_id)
        if parsed["kind"] == "invite":
            try:
                await client(ImportChatInviteRequest(parsed["invite_hash"]))
                return "Joined group via invite link"
            except errors.UserAlreadyParticipantError:
                return None
            except errors.InviteRequestSentError:
                return "Join request sent — waiting for admin approval"
            except errors.FloodWaitError:
                return None

        if isinstance(entity, Channel):
            if await _is_member(client, entity):
                return None
            note = await _join_channel_entity(client, entity)
            await _join_discussion_group(client, entity)
            return note
    return None


async def _resolve_entity(client: TelegramClient, group_id: str):
    """Resolve a group entity. If first attempt fails with username error,
    warm the entity cache via get_dialogs() and retry — handles cold sessions
    (e.g., after Railway restart where StringSession has no entity cache).
    """
    parsed = _parse_group_identifier(group_id)
    if parsed["kind"] == "invite":
        return await client.get_entity(parsed["raw"])
    target = parsed.get("username") or parsed.get("id") or parsed["raw"]

    try:
        return await client.get_entity(target)
    except Exception as e:
        err_msg = str(e).lower()
        if "no user has" in err_msg or "nobody is using" in err_msg:
            # Entity not in session cache — warm it by fetching dialogs
            logger.debug(f"Entity cache miss for {group_id}, warming via get_dialogs()")
            try:
                await client.get_dialogs(limit=100)
                return await client.get_entity(target)
            except Exception:
                pass  # Re-raise the original error
        raise


def _needs_join(exc: Exception) -> bool:
    if isinstance(exc, errors.UserNotParticipantError):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in (
        "not a participant",
        "user_not_participant",
        "you can't write in this chat",
        "have no rights",
        "channel_private",
        "not a member",
        "join the group",
    ))


def _needs_discussion_join(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "discussion group" in msg or "join the discussion" in msg


def _media_filename(campaign: dict, media_path: str, content_type: str) -> str:
    name = (campaign.get("media_filename") or "").strip()
    if name and "." in name:
        return name
    if "." in media_path:
        ext = media_path.rsplit(".", 1)[-1].lower()
        if ext in storage.MIME_TYPES:
            return f"media.{ext}"
    for ext, mime in storage.MIME_TYPES.items():
        if mime == content_type:
            return f"media.{ext}"
    return "media.jpg"


MEDIA_FORBIDDEN_ERRORS = tuple(
    cls for cls in (
        getattr(errors, n, None)
        for n in (
            "ChatSendMediaForbiddenError",
            "ChatSendPhotosForbiddenError",
            "ChatSendVideosForbiddenError",
            "ChatSendGifsForbiddenError",
            "ChatSendStickersForbiddenError",
            "ChatSendVoicesForbiddenError",
        )
    )
    if cls is not None
)


def _is_flood_error(exc: Exception) -> bool:
    if isinstance(exc, errors.FloodWaitError):
        return True
    ename = type(exc).__name__.upper()
    msg = str(exc).upper()
    return "FLOOD" in ename or ("WAIT" in msg and "SECOND" in msg)


def _is_media_restricted(exc: Exception) -> bool:
    if isinstance(exc, MEDIA_FORBIDDEN_ERRORS):
        return True
    ename = type(exc).__name__.upper()
    msg = str(exc).upper()
    return (
        ("FORBIDDEN" in ename and any(k in ename for k in ("MEDIA", "PHOTO", "GIF", "VIDEO", "DOCUMENT", "STICKER", "ROUNDVIDEO", "VOICE")))
        or "SENDMEDIA" in msg
        or "SEND_MEDIA" in msg
        or "MEDIA_INVALID" in msg
        or ("MEDIA" in msg and "FORBIDDEN" in msg)
        or "CAN'T SEND MEDIA" in msg
    )


async def _try_send_media(client: TelegramClient, entity, data: bytes, filename: str, caption: str):
    """Send image/video; retry as document; if group blocks media, send text only.

    Catches ALL exceptions (not just RPCError) so that no media-related error
    can prevent the text fallback from firing.
    Re-raises FloodWaitError immediately — those need cooldown handling upstream.
    """
    caption = (caption or "").strip() or None
    last_err = None

    for force_document in (False, True):
        buf = io.BytesIO(data)
        buf.name = filename
        try:
            await client.send_file(entity, buf, caption=caption, force_document=force_document)
            if force_document:
                return "Sent as file attachment (inline media blocked)"
            return None
        except Exception as e:
            # Re-raise flood errors immediately — those need cooldown, not fallback
            if _is_flood_error(e):
                raise
            last_err = e
            logger.debug(f"Media send attempt failed (force_doc={force_document}): {e}")

    # --- Text fallback ---
    if not caption:
        raise last_err or ValueError("Media blocked and no caption to send")

    try:
        await client.send_message(entity, caption)
        return "Media blocked in group — sent text only"
    except Exception as text_err:
        if _is_flood_error(text_err):
            raise
        raise text_err


async def _send_with_entity(client: TelegramClient, entity, mtype: str, campaign: dict, text: str, join_note=None):
    note = join_note

    if mtype == "text":
        await client.send_message(entity, text)
        return note

    if mtype == "media":
        media_path = campaign.get("media_path")
        if not media_path:
            raise ValueError("No media attached to campaign.")
        # Use cached media — avoids re-fetching the same file for every group in the cycle
        data, content_type = await _get_cached_media(media_path)
        filename = _media_filename(campaign, media_path, content_type)
        media_note = await _try_send_media(client, entity, data, filename, text)
        if media_note and note:
            return f"{note}; {media_note}"
        return media_note or note

    if mtype == "forward":
        src, msg_id = _parse_forward_link(campaign.get("forward_link", ""))
        await client.forward_messages(entity, msg_id, src)
        return note

    raise ValueError(f"Unknown message type: {mtype}")


async def _proactive_join(client: TelegramClient, account_id: str, group_id: str):
    """Join the group BEFORE resolving entity. Returns (join_note, entity_or_None).

    CRITICAL: Do NOT swallow 'no user has X' errors — those mean THIS account
    cannot resolve the group. By re-raising, server.py will rotate to the next
    account which may succeed.

    Returns the entity from the join response when available, avoiding a
    redundant resolve call that would fail the same way.
    """
    parsed = _parse_group_identifier(group_id)
    cache_key = (account_id, _group_cache_key(group_id))
    lock = _join_locks.setdefault(account_id, asyncio.Lock())

    async with lock:
        if _join_key_is_fresh(cache_key):
            return None, None  # already joined this session

        # ── Invite link ───────────────────────────────────────────────────────
        if parsed["kind"] == "invite":
            try:
                updates = await client(ImportChatInviteRequest(parsed["invite_hash"]))
                _mark_join_attempted(cache_key)
                # Extract entity from the updates response
                entity = None
                if hasattr(updates, 'chats') and updates.chats:
                    entity = updates.chats[0]
                return "Joined via invite link", entity
            except errors.UserAlreadyParticipantError:
                _mark_join_attempted(cache_key)
                return None, None
            except errors.InviteRequestSentError:
                _mark_join_attempted(cache_key)
                return "Join request sent", None
            except errors.FloodWaitError:
                raise  # Let caller handle flood
            except Exception as e:
                logger.debug(f"Invite join failed for {group_id}: {e}")
                return None, None

        # ── Username (e.g. @forex_temes or https://t.me/voipiran_channel) ─────
        if parsed["kind"] == "username":
            username = parsed["username"]  # already has @ prefix
            try:
                updates = await client(JoinChannelRequest(username))
                _mark_join_attempted(cache_key)
                # Extract entity from the join response
                entity = None
                if hasattr(updates, 'chats') and updates.chats:
                    entity = updates.chats[0]
                # After joining, try to also join linked discussion group
                if entity and isinstance(entity, Channel):
                    try:
                        await _join_discussion_group(client, entity)
                    except Exception:
                        pass
                return "Joined group", entity
            except errors.UserAlreadyParticipantError:
                _mark_join_attempted(cache_key)
                return None, None
            except errors.InviteRequestSentError:
                _mark_join_attempted(cache_key)
                return "Join request sent", None
            except errors.FloodWaitError:
                raise  # Let caller handle flood
            except Exception as e:
                err_msg = str(e).lower()
                # RE-RAISE username resolution errors — this account can't access this group
                # Server.py will rotate to the next account which may succeed
                if "no user has" in err_msg or "nobody is using this username" in err_msg or "username is unacceptable" in err_msg:
                    logger.info(f"Account {account_id} can't resolve {group_id}: {e}")
                    raise  # Don't swallow — let account rotation handle it
                logger.debug(f"Username join failed for {group_id}: {e}")
                _mark_join_attempted(cache_key)
                return None, None

        # ── Numeric ID ────────────────────────────────────────────────────────
        if parsed["kind"] == "numeric":
            try:
                updates = await client(JoinChannelRequest(parsed["id"]))
                _mark_join_attempted(cache_key)
                entity = None
                if hasattr(updates, 'chats') and updates.chats:
                    entity = updates.chats[0]
                return "Joined group", entity
            except errors.UserAlreadyParticipantError:
                _mark_join_attempted(cache_key)
                return None, None
            except errors.InviteRequestSentError:
                _mark_join_attempted(cache_key)
                return "Join request sent", None
            except errors.FloodWaitError:
                raise  # Let caller handle flood
            except Exception as e:
                logger.debug(f"Numeric join failed for {group_id}: {e}")
                _mark_join_attempted(cache_key)
                return None, None

    return None, None


async def send_ad_to_group(
    client: TelegramClient,
    group_id: str,
    campaign: dict,
    account_id: str = None,
    apply_jitter: bool = True,
):
    """Send the ad. Joins the group only when send fails due to not being a member.

    This matches the original working logic:
    1. Resolve entity via get_entity
    2. Try to send
    3. If fails with 'needs join' → join reactively → retry

    apply_jitter: add random 2-5s delay before sending — reduces spam-flag risk.
    Re-raises FloodWaitError for caller to handle cooldown.
    """
    if apply_jitter:
        await asyncio.sleep(random.uniform(2.0, 5.0))

    mtype = campaign["message_type"]
    text = campaign.get("text") or ""

    entity = await _resolve_entity(client, group_id)
    join_note = None

    for attempt in range(2):
        try:
            return await _send_with_entity(client, entity, mtype, campaign, text, join_note)
        except Exception as e:
            if attempt == 0 and (_needs_join(e) or _needs_discussion_join(e)):
                join_note = await _try_join(client, account_id, group_id, entity)
                if _needs_discussion_join(e) and isinstance(entity, Channel):
                    disc = await _join_discussion_group(client, entity)
                    join_note = disc or join_note
                continue

            # --- Top-level media fallback safety net ---
            if mtype == "media" and text and _is_media_restricted(e):
                try:
                    await client.send_message(entity, text)
                    note = "Media blocked in group — sent text only (fallback)"
                    if join_note:
                        note = f"{join_note}; {note}"
                    return note
                except Exception as fallback_err:
                    if _is_flood_error(fallback_err):
                        raise
                    logger.warning(f"Text fallback also failed for {group_id}: {fallback_err}")
                    raise fallback_err

            raise


def is_campaign_running(campaign_id: str) -> bool:
    task = _campaign_tasks.get(campaign_id)
    return task is not None and not task.done()


def stop_campaign_task(campaign_id: str):
    task = _campaign_tasks.pop(campaign_id, None)
    if task is not None and not task.done():
        logger.info(f"Stopping campaign task {campaign_id}")
        task.cancel()
