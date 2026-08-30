"""HTTP tests for PUT /api/campaigns/{id} — edit an existing campaign.
SAFETY: never calls /start. Cleans up all TEST_* campaigns at the end.
"""
import os
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
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


def _create(client, name, **over):
    payload = {
        "name": name,
        "message_type": "text",
        "text": "orig",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 25,
    }
    payload.update(over)
    r = client.post(f"{API}/campaigns", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def test_update_basic_fields(client, created_ids):
    orig = _create(client, "TEST_edit_basic")
    created_ids.append(orig["id"])
    new = {
        "name": "TEST_edit_basic_v2",
        "message_type": "text",
        "text": "new text",
        "target_groups": ["@qa_new_grp_1", "@qa_new_grp_2"],
        "interval_seconds": 123,
        "concurrency": 42,
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=new, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "TEST_edit_basic_v2"
    assert d["text"] == "new text"
    assert d["interval_seconds"] == 123
    assert d["concurrency"] == 42
    assert len(d["target_groups"]) == 2
    assert d["target_groups"][0]["id"] == "@qa_new_grp_1"
    # preserved
    assert d["status"] == orig["status"] == "stopped"
    assert d["sent_count"] == orig["sent_count"]
    assert d["created_at"] == orig["created_at"]


def test_update_concurrency_clamped(client, created_ids):
    orig = _create(client, "TEST_edit_clamp")
    created_ids.append(orig["id"])
    payload = {
        "name": orig["name"],
        "message_type": "text",
        "text": "x",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 999,
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 200
    assert r.json()["concurrency"] == 100

    payload["concurrency"] = 0
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 200
    assert r.json()["concurrency"] == 1


def test_update_empty_target_groups_400(client, created_ids):
    orig = _create(client, "TEST_edit_empty")
    created_ids.append(orig["id"])
    payload = {
        "name": orig["name"],
        "message_type": "text",
        "text": "x",
        "target_groups": [],
        "interval_seconds": 60,
        "concurrency": 25,
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 400


def test_update_nonexistent_id_404(client):
    payload = {
        "name": "TEST_edit_ghost",
        "message_type": "text",
        "text": "x",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 25,
    }
    r = client.put(f"{API}/campaigns/no-such-id-xyz", json=payload, timeout=15)
    assert r.status_code == 404


def test_update_bad_account_batch_400(client, created_ids):
    orig = _create(client, "TEST_edit_bad_batch")
    created_ids.append(orig["id"])
    payload = {
        "name": orig["name"],
        "message_type": "text",
        "text": "x",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 25,
        "account_batch_id": "nonexistent-batch-xyz",
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 400


def test_update_message_type_and_media_fields(client, created_ids):
    orig = _create(client, "TEST_edit_media")
    created_ids.append(orig["id"])
    payload = {
        "name": orig["name"],
        "message_type": "media",
        "text": "caption",
        "media_path": "some/path.jpg",
        "media_url": "/api/uploads/some/path.jpg",
        "media_filename": "path.jpg",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 25,
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["message_type"] == "media"
    assert d["media_path"] == "some/path.jpg"
    assert d["media_filename"] == "path.jpg"


def test_update_forward_link(client, created_ids):
    orig = _create(client, "TEST_edit_fwd")
    created_ids.append(orig["id"])
    payload = {
        "name": orig["name"],
        "message_type": "forward",
        "text": "",
        "forward_link": "https://t.me/somechan/999",
        "target_groups": [SAFE_TARGET],
        "interval_seconds": 60,
        "concurrency": 25,
    }
    r = client.put(f"{API}/campaigns/{orig['id']}", json=payload, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["message_type"] == "forward"
    assert d["forward_link"] == "https://t.me/somechan/999"
