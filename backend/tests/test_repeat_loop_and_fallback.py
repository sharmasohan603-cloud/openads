"""Tests for:
  - campaign_loop REPEAT (uses mocked telegram + mocked send)
  - HANG-DOES-NOT-STALL (one hanging account, cycle still repeats via wait_for timeout)
  - MEDIA -> TEXT fallback in telegram_service.send_ad_to_group

SAFETY: Nothing hits Telegram. We monkeypatch telegram_service.get_client and
telegram_service.send_ad_to_group. We insert fake accounts (batch_id 'qa-batch')
and a test campaign directly into Mongo, then delete everything at the end.
"""
import asyncio
import os
import sys
import uuid
import pytest
from pathlib import Path

# make backend importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import server  # noqa: E402
import telegram_service as tg  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


BATCH_ID = "qa-batch-repeat"


@pytest.fixture(autouse=True)
def _reset_motor_client():
    """Motor binds to the current event loop; pytest-asyncio creates a fresh loop
    per test, so rebind server.db to the active loop before each test."""
    server.client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    server.db = server.client[os.environ["DB_NAME"]]
    yield


async def _seed(num_accounts=3, num_groups=3, interval=1):
    # cleanup any prior state
    await server.db.accounts.delete_many({"batch_id": BATCH_ID})
    await server.db.campaigns.delete_many({"name": {"$regex": "^TEST_repeat_"}})
    await server.db.logs.delete_many({"campaign_name": {"$regex": "^TEST_repeat_"}})

    for i in range(num_accounts):
        await server.db.accounts.insert_one({
            "id": f"qa-acc-{i}",
            "name": f"qa-acc-{i}",
            "batch_id": BATCH_ID,
            "batch_name": "qa-batch",
            "api_id": 1,
            "api_hash": "x",
            "session_string": "x",
            "status": "connected",
            "created_at": server.now_iso(),
        })

    cid = str(uuid.uuid4())
    camp = {
        "id": cid,
        "name": f"TEST_repeat_{cid[:6]}",
        "message_type": "text",
        "text": "hi",
        "target_groups": [{"id": f"@g{i}", "title": f"@g{i}"} for i in range(num_groups)],
        "interval_seconds": interval,
        "account_batch_id": BATCH_ID,
        "concurrency": 5,
        "status": "running",
        "sent_count": 0,
        "last_run": None,
        "created_at": server.now_iso(),
    }
    await server.db.campaigns.insert_one(camp)
    return cid, num_groups


async def _cleanup(cid):
    await server.db.campaigns.delete_one({"id": cid})
    await server.db.accounts.delete_many({"batch_id": BATCH_ID})
    await server.db.logs.delete_many({"campaign_id": cid})


@pytest.mark.asyncio
async def test_repeat_loop_runs_multiple_cycles(monkeypatch):
    """Campaign loop must repeat until status flips to 'stopped'.
    sent_count should exceed one full cycle (num_groups) in a few seconds.
    """
    # Speed up timeouts
    monkeypatch.setattr(tg, "CLIENT_TIMEOUT", 1)
    monkeypatch.setattr(tg, "SEND_TIMEOUT", 1)

    async def fake_get_client(acc):
        return object()

    async def fake_send(client, gid, camp):
        return None

    monkeypatch.setattr(tg, "get_client", fake_get_client)
    monkeypatch.setattr(tg, "send_ad_to_group", fake_send)

    cid, ngroups = await _seed(num_accounts=3, num_groups=3, interval=1)
    try:
        task = asyncio.create_task(server.campaign_loop(cid))
        await asyncio.sleep(4.5)
        await server.db.campaigns.update_one({"id": cid}, {"$set": {"status": "stopped"}})
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
        camp = await server.db.campaigns.find_one({"id": cid})
        assert camp["sent_count"] > ngroups, (
            f"expected >{ngroups} sends (multiple cycles), got {camp['sent_count']}"
        )
        assert camp["last_run"] is not None
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_hanging_account_does_not_stall(monkeypatch):
    """One account hangs for 5s (>SEND_TIMEOUT=1). Other accounts succeed instantly.
    Cycle must still complete and repeat — sent_count grows over time."""
    monkeypatch.setattr(tg, "CLIENT_TIMEOUT", 1)
    monkeypatch.setattr(tg, "SEND_TIMEOUT", 1)

    async def fake_get_client(acc):
        return {"acc_id": acc["id"]}

    async def fake_send(client, gid, camp):
        # First account hangs; others succeed
        if client.get("acc_id") == "qa-acc-0":
            await asyncio.sleep(5)
        return None

    monkeypatch.setattr(tg, "get_client", fake_get_client)
    monkeypatch.setattr(tg, "send_ad_to_group", fake_send)

    cid, ngroups = await _seed(num_accounts=3, num_groups=3, interval=1)
    try:
        task = asyncio.create_task(server.campaign_loop(cid))
        await asyncio.sleep(5.0)
        # Snapshot mid-way
        mid = await server.db.campaigns.find_one({"id": cid})
        await asyncio.sleep(2.5)
        await server.db.campaigns.update_one({"id": cid}, {"$set": {"status": "stopped"}})
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
        final = await server.db.campaigns.find_one({"id": cid})
        # Must have completed more than one cycle
        assert final["sent_count"] > ngroups, f"sent_count={final['sent_count']} not > {ngroups}"
        # And still growing — mid vs final
        assert final["sent_count"] >= mid["sent_count"], "sent_count went backwards"
    finally:
        await _cleanup(cid)


# ---------------------- MEDIA -> TEXT FALLBACK ----------------------

class _FakeMediaForbiddenRPCError(tg.errors.RPCError):
    """Subclass of telethon RPCError whose class name matches the media-forbidden pattern."""
    def __init__(self):
        # telethon's RPCError requires request+message; we bypass by just setting message
        self.message = "media forbidden"
    def __str__(self):
        return "media forbidden"


# rename so type(e).__name__ contains 'Media' + 'Forbidden'
_FakeMediaForbiddenRPCError.__name__ = "ChatSendMediaForbiddenError"


class _FakeOtherRPCError(tg.errors.RPCError):
    def __init__(self):
        self.message = "flood"
    def __str__(self):
        return "flood"


_FakeOtherRPCError.__name__ = "FloodWaitError"


class _FakeClient:
    def __init__(self, send_file_raises=None, send_file_raises_on_document=None):
        self._send_file_raises = send_file_raises
        self._send_file_raises_on_document = send_file_raises_on_document
        self.text_sent = None
        self.file_sent = False
        self.document_sent = False

    async def get_entity(self, target):
        return target

    async def __call__(self, request):
        return None

    async def send_message(self, target, text):
        self.text_sent = (target, text)

    async def send_file(self, target, buf, caption=None, force_document=False):
        self.file_sent = True
        if force_document:
            self.document_sent = True
            if self._send_file_raises_on_document is not None:
                raise self._send_file_raises_on_document
        elif self._send_file_raises is not None:
            raise self._send_file_raises

    async def forward_messages(self, target, msg_id, entity):
        pass


@pytest.mark.asyncio
async def test_media_forbidden_falls_back_to_text(monkeypatch):
    import storage
    monkeypatch.setattr(storage, "get_object", lambda p: (b"bytes", "image/jpeg"))

    client = _FakeClient(
        send_file_raises=_FakeMediaForbiddenRPCError(),
        send_file_raises_on_document=_FakeMediaForbiddenRPCError(),
    )
    campaign = {
        "message_type": "media",
        "text": "hello",
        "media_path": "x",
        "media_filename": "a.jpg",
    }
    note = await tg.send_ad_to_group(client, "https://t.me/mygroup", campaign)
    assert client.file_sent is True, "send_file should have been attempted"
    assert client.text_sent == ("@mygroup", "hello"), "fallback send_message should be called with text"
    assert note == "Media blocked in group — sent text only"


@pytest.mark.asyncio
async def test_media_photo_blocked_retries_as_document(monkeypatch):
    import storage
    monkeypatch.setattr(storage, "get_object", lambda p: (b"bytes", "image/jpeg"))

    client = _FakeClient(send_file_raises=_FakeMediaForbiddenRPCError())
    campaign = {
        "message_type": "media",
        "text": "hello",
        "media_path": "zydex/uploads/x.jpg",
        "media_filename": "a.jpg",
    }
    # First call (photo) raises; second call (document) succeeds
    client._send_file_raises_on_document = None
    original_send_file = client.send_file

    async def send_file_side_effect(target, buf, caption=None, force_document=False):
        if not force_document:
            raise _FakeMediaForbiddenRPCError()
        client.document_sent = True

    client.send_file = send_file_side_effect

    note = await tg.send_ad_to_group(client, "@grp", campaign)
    assert client.document_sent is True
    assert client.text_sent is None
    assert "file attachment" in (note or "")


@pytest.mark.asyncio
async def test_non_media_rpcerror_reraises(monkeypatch):
    import storage
    monkeypatch.setattr(storage, "get_object", lambda p: (b"bytes", "image/jpeg"))
    client = _FakeClient(send_file_raises=_FakeOtherRPCError())
    campaign = {
        "message_type": "media",
        "text": "hello",
        "media_path": "x",
        "media_filename": "a.jpg",
    }
    with pytest.raises(tg.errors.RPCError):
        await tg.send_ad_to_group(client, "@grp", campaign)
    assert client.text_sent is None, "must NOT fall back for non-media RPCError"


@pytest.mark.asyncio
async def test_text_message_type_sends_normally():
    client = _FakeClient()
    campaign = {"message_type": "text", "text": "hola"}
    note = await tg.send_ad_to_group(client, "@grp", campaign)
    assert client.text_sent == ("@grp", "hola")
    assert note is None
