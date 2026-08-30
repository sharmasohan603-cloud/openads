"""Backend tests for concurrency field, campaign validation, and account-groups.

SAFETY: We only CREATE, GET, and DELETE campaigns targeting a fake group. We NEVER
call /start — that would send real Telegram messages.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
SAFE_TARGET = "@qa_nonexistent_grp_zzz999"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def created_ids(client):
    ids = []
    yield ids
    for cid in ids:
        try:
            client.delete(f"{API}/campaigns/{cid}", timeout=15)
        except Exception:
            pass


def _payload(name, **over):
    p = {
        "name": name,
        "message_type": "text",
        "text": "hello",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
    }
    p.update(over)
    return p


# ---------- concurrency clamping ----------
def test_concurrency_default_25(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_default"))
    assert r.status_code == 200, r.text
    data = r.json()
    created_ids.append(data["id"])
    assert data["concurrency"] == 25


def test_concurrency_50_stored(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_50", concurrency=50))
    assert r.status_code == 200, r.text
    data = r.json()
    created_ids.append(data["id"])
    assert data["concurrency"] == 50


def test_concurrency_999_clamped_to_100(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_999", concurrency=999))
    assert r.status_code == 200, r.text
    data = r.json()
    created_ids.append(data["id"])
    assert data["concurrency"] == 100


def test_concurrency_0_clamped_to_1(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_0", concurrency=0))
    assert r.status_code == 200, r.text
    data = r.json()
    created_ids.append(data["id"])
    assert data["concurrency"] == 1


def test_concurrency_negative_clamped_to_1(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_neg", concurrency=-5))
    assert r.status_code == 200, r.text
    data = r.json()
    created_ids.append(data["id"])
    assert data["concurrency"] == 1


def test_concurrency_persisted_in_list(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_conc_list", concurrency=42))
    assert r.status_code == 200
    cid = r.json()["id"]
    created_ids.append(cid)
    lst = client.get(f"{API}/campaigns").json()
    match = [c for c in lst if c["id"] == cid]
    assert match and match[0]["concurrency"] == 42


# ---------- validation ----------
def test_empty_target_groups_returns_400(client):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_empty_targets", target_groups=[]))
    assert r.status_code == 400


def test_whitespace_only_target_groups_returns_400(client):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_ws_targets", target_groups=["   ", ""]))
    assert r.status_code == 400


def test_message_type_media(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_media", message_type="media",
                                                     media_path="fake/path.jpg",
                                                     media_filename="p.jpg"))
    assert r.status_code == 200
    data = r.json()
    created_ids.append(data["id"])
    assert data["message_type"] == "media"
    assert data["media_path"] == "fake/path.jpg"


def test_message_type_forward(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_fwd", message_type="forward",
                                                     forward_link="https://t.me/somechan/1"))
    assert r.status_code == 200
    data = r.json()
    created_ids.append(data["id"])
    assert data["forward_link"] == "https://t.me/somechan/1"


def test_interval_seconds_preserved(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_interval", interval_seconds=123))
    assert r.status_code == 200
    data = r.json()
    created_ids.append(data["id"])
    assert data["interval_seconds"] == 123


def test_invalid_account_batch_id_returns_400(client):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_bad_batch",
                                                     account_batch_id="nonexistent-batch-id-xyz"))
    assert r.status_code == 400


# ---------- account-groups ----------
def test_account_groups_accounts_section(client):
    r = client.get(f"{API}/account-groups")
    assert r.status_code == 200
    groups = r.json()
    acc = [g for g in groups if g.get("batch_name") == "accounts"]
    assert acc, f"'accounts' section missing: {[g.get('batch_name') for g in groups]}"
    assert acc[0]["count"] == 156


# ---------- newly created campaigns don't auto-start ----------
def test_created_campaign_status_stopped(client, created_ids):
    r = client.post(f"{API}/campaigns", json=_payload("TEST_stopped_check"))
    assert r.status_code == 200
    data = r.json()
    created_ids.append(data["id"])
    assert data["status"] == "stopped"
