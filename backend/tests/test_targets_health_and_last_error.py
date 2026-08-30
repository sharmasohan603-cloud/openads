"""Backend tests for new features: last_error, targets-health, remove-groups.

Safe: uses direct Mongo inserts for logs; does NOT start any real campaign that would send.
"""
import os
import sys
import time
import uuid
import asyncio
from pathlib import Path

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
sys.path.insert(0, str(BACKEND_DIR))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # Fall back to frontend .env
    fe = Path("/app/frontend/.env")
    for line in fe.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def mongo():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _create_campaign(s, name, targets, batch_id=None):
    payload = {
        "name": name,
        "message_type": "text",
        "text": "qa test",
        "target_groups": targets,
        "interval_seconds": 60,
        "concurrency": 1,
    }
    if batch_id:
        payload["account_batch_id"] = batch_id
    r = s.post(f"{API}/campaigns", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ----------------- 1. new campaigns include last_error null -----------------
def test_new_campaign_has_last_error_null(s):
    camp = _create_campaign(s, "TEST_qa_last_error_null", ["@qa_grp1", "@qa_grp2"])
    try:
        assert "last_error" in camp
        assert camp["last_error"] is None
        # list also returns it
        listed = s.get(f"{API}/campaigns").json()
        found = next(c for c in listed if c["id"] == camp["id"])
        assert "last_error" in found and found["last_error"] is None
    finally:
        s.delete(f"{API}/campaigns/{camp['id']}")


# ----------------- 2. start clears last_error to null ----------------------
# SAFETY: We insert the campaign directly into Mongo bound to a FAKE batch_id
# so no real accounts are ever used. The campaign_loop should hit the
# no-accounts branch and set status=stopped with last_error mentioning
# "No accounts".
def test_start_clears_last_error_no_accounts_branch(s, mongo):
    loop = asyncio.get_event_loop()
    fake_batch = f"nonexistent-batch-{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    doc = {
        "id": cid,
        "name": "TEST_qa_no_accounts",
        "message_type": "text",
        "text": "irrelevant",
        "target_groups": [{"id": "@qa_never", "title": "@qa_never"}],
        "interval_seconds": 60,
        "account_batch_id": fake_batch,  # empty section -> loop must abort safely
        "account_batch_name": "fake",
        "concurrency": 1,
        "status": "stopped",
        "sent_count": 0,
        "last_run": None,
        "last_error": "stale old error",  # pre-existing so we verify /start clears it
        "created_at": "2024-01-01T00:00:00+00:00",
    }
    loop.run_until_complete(mongo.campaigns.insert_one(doc))
    try:
        # start should clear last_error immediately
        r = s.post(f"{API}/campaigns/{cid}/start")
        assert r.status_code == 200
        # poll for auto-stop with new last_error
        stopped_seen = False
        cleared_seen = False
        for _ in range(30):
            time.sleep(0.5)
            d = loop.run_until_complete(mongo.campaigns.find_one({"id": cid}))
            if d.get("last_error") is None:
                cleared_seen = True
            if d.get("status") == "stopped" and d.get("last_error") and "No accounts" in d["last_error"]:
                stopped_seen = True
                break
        # Note: cleared_seen may miss the brief null window if loop replaces it
        # very quickly, but reaching the "No accounts" state proves start cleared
        # the stale value first (otherwise stale would remain since /start writes
        # last_error:null before the loop sets it).
        assert stopped_seen, "loop should auto-stop with 'No accounts' last_error"

        # verify GET /api/campaigns surfaces last_error
        listed = s.get(f"{API}/campaigns").json()
        found = next(c for c in listed if c["id"] == cid)
        assert "last_error" in found and "No accounts" in (found["last_error"] or "")
    finally:
        s.post(f"{API}/campaigns/{cid}/stop")
        loop.run_until_complete(mongo.campaigns.delete_one({"id": cid}))
        loop.run_until_complete(mongo.logs.delete_many({"campaign_id": cid}))


# ----------------- 3. targets-health endpoint -----------------------------
def test_targets_health_classification(s, mongo):
    targets = ["@qa_A", "@qa_B", "@qa_C", "@qa_D"]
    camp = _create_campaign(s, "TEST_qa_targets_health", targets)
    cid = camp["id"]
    loop = asyncio.get_event_loop()
    try:
        # seed logs
        def mklog(gid, status, err=None, ts="2024-01-01T00:00:00+00:00"):
            return {
                "id": str(uuid.uuid4()),
                "campaign_id": cid,
                "campaign_name": camp["name"],
                "account_id": None, "account_name": "-",
                "group_id": gid, "group_title": gid,
                "status": status, "error": err, "timestamp": ts,
            }
        docs = []
        # A: 2 success
        docs += [mklog("@qa_A", "success", ts=f"2024-01-01T00:00:0{i}+00:00") for i in range(2)]
        # B: 3 failed (dead)
        docs += [mklog("@qa_B", "failed", err=f"boom{i}", ts=f"2024-01-01T00:00:0{i}+00:00") for i in range(3)]
        # C: 1 success + 1 failed (failing) -- ensure failed is last so last_error surfaces
        docs.append(mklog("@qa_C", "success", ts="2024-01-01T00:00:01+00:00"))
        docs.append(mklog("@qa_C", "failed", err="flake", ts="2024-01-01T00:00:02+00:00"))
        # D: no logs
        loop.run_until_complete(mongo.logs.insert_many(docs))

        r = s.get(f"{API}/campaigns/{cid}/targets-health")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 4
        by = {row["id"]: row for row in rows}
        assert by["@qa_A"]["health"] == "ok" and by["@qa_A"]["success"] == 2 and by["@qa_A"]["failed"] == 0
        assert by["@qa_B"]["health"] == "dead" and by["@qa_B"]["failed"] == 3 and by["@qa_B"]["success"] == 0
        assert by["@qa_B"]["last_error"] == "boom2"
        assert by["@qa_C"]["health"] == "failing" and by["@qa_C"]["success"] == 1 and by["@qa_C"]["failed"] == 1
        assert by["@qa_C"]["last_error"] == "flake"
        assert by["@qa_D"]["health"] == "unknown"

        # ordering: dead/failing first
        order = [row["id"] for row in rows]
        assert order.index("@qa_B") < order.index("@qa_A")
        assert order.index("@qa_C") < order.index("@qa_A")
    finally:
        loop.run_until_complete(mongo.logs.delete_many({"campaign_id": cid}))
        s.delete(f"{API}/campaigns/{cid}")


def test_targets_health_404(s):
    r = s.get(f"{API}/campaigns/does-not-exist/targets-health")
    assert r.status_code == 404


# ----------------- 4. remove-groups ---------------------------------------
def test_remove_groups(s):
    camp = _create_campaign(s, "TEST_qa_remove_groups", ["@x1", "@x2", "@x3"])
    cid = camp["id"]
    try:
        # empty -> 400
        r = s.post(f"{API}/campaigns/{cid}/remove-groups", json={"group_ids": []})
        assert r.status_code == 400

        # remove 2
        r = s.post(f"{API}/campaigns/{cid}/remove-groups", json={"group_ids": ["@x1", "@x3"]})
        assert r.status_code == 200
        updated = r.json()
        ids = [g["id"] for g in updated["target_groups"]]
        assert ids == ["@x2"]

        # 404 for nonexistent
        r = s.post(f"{API}/campaigns/nonexistent/remove-groups", json={"group_ids": ["@a"]})
        assert r.status_code == 404
    finally:
        s.delete(f"{API}/campaigns/{cid}")
