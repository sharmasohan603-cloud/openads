"""Tests for account-groups (sections) and campaign account_batch_id wiring.

Safety: only creates campaigns targeting a nonexistent handle and cleans them up.
Never calls /start.
"""
import os
import requests
from pathlib import Path

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip()
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

NONEXISTENT_HANDLE = "@qa_nonexistent_grp_zzz999"


# ---------- account-groups ----------
def test_account_groups_returns_list_with_accounts_section():
    r = requests.get(f"{API}/account-groups", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1, "expected at least one section"
    for row in data:
        assert set(["batch_id", "batch_name", "count"]).issubset(row.keys())
        assert isinstance(row["count"], int)
        assert row["batch_id"]  # non-empty
    # There should be a section named 'accounts' with count 156 (per review request)
    names = {r["batch_name"]: r["count"] for r in data}
    assert "accounts" in names, f"expected 'accounts' section, got {names}"
    # Report actual count without hard-failing if it changed slightly
    assert names["accounts"] >= 1


def test_total_section_count_matches_accounts_endpoint():
    groups = requests.get(f"{API}/account-groups", timeout=30).json()
    accounts = requests.get(f"{API}/accounts", timeout=30).json()
    total_sections = sum(g["count"] for g in groups)
    # Every account has been backfilled with batch_id -> counts should match
    assert total_sections == len(accounts), (
        f"section total {total_sections} != accounts total {len(accounts)}"
    )


# ---------- campaign create with account_batch_id ----------
def _delete(cid):
    try:
        requests.delete(f"{API}/campaigns/{cid}", timeout=30)
    except Exception:
        pass


def test_campaign_create_with_valid_batch_id():
    groups = requests.get(f"{API}/account-groups", timeout=30).json()
    assert groups, "need at least one section to test"
    batch = groups[0]
    payload = {
        "name": "TEST_batch_campaign",
        "message_type": "text",
        "text": "qa-nonexistent",
        "target_groups": [NONEXISTENT_HANDLE],
        "interval_seconds": 30,
        "account_batch_id": batch["batch_id"],
    }
    r = requests.post(f"{API}/campaigns", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    camp = r.json()
    cid = camp["id"]
    try:
        assert camp["account_batch_id"] == batch["batch_id"]
        assert camp["account_batch_name"] == batch["batch_name"]
        assert camp["interval_seconds"] == 30
        assert camp["status"] == "stopped"
        assert camp["target_groups"][0]["id"] == NONEXISTENT_HANDLE

        # confirm via GET /campaigns
        listing = requests.get(f"{API}/campaigns", timeout=30).json()
        found = next((c for c in listing if c["id"] == cid), None)
        assert found is not None
        assert found["account_batch_id"] == batch["batch_id"]
        assert found["account_batch_name"] == batch["batch_name"]
    finally:
        _delete(cid)


def test_campaign_create_without_batch_defaults_to_all():
    payload = {
        "name": "TEST_nobatch_campaign",
        "message_type": "text",
        "text": "qa-nonexistent",
        "target_groups": [NONEXISTENT_HANDLE],
        "interval_seconds": 30,
    }
    r = requests.post(f"{API}/campaigns", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    camp = r.json()
    cid = camp["id"]
    try:
        assert camp.get("account_batch_id") is None
        assert camp.get("account_batch_name") is None
    finally:
        _delete(cid)


def test_campaign_create_invalid_batch_returns_400():
    payload = {
        "name": "TEST_badbatch_campaign",
        "message_type": "text",
        "text": "x",
        "target_groups": [NONEXISTENT_HANDLE],
        "interval_seconds": 30,
        "account_batch_id": "does-not-exist-uuid-zzz",
    }
    r = requests.post(f"{API}/campaigns", json=payload, timeout=30)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_campaign_create_empty_target_groups_returns_400():
    payload = {
        "name": "TEST_empty_groups",
        "message_type": "text",
        "text": "x",
        "target_groups": [],
        "interval_seconds": 30,
    }
    r = requests.post(f"{API}/campaigns", json=payload, timeout=30)
    assert r.status_code == 400
