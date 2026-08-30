"""Backend tests for proxy management endpoints (TelePulse)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend env file
    from pathlib import Path
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"

REAL_PROXY = {
    "proxy_type": "socks5",
    "host": "74.81.81.81",
    "port": 823,
    "username": "d04010bb23577fd5e905__cr.us",
    "password": "c79f6d6c8267b56a",
}


@pytest.fixture(scope="module", autouse=True)
def clean_after():
    # ensure clean state before + after
    requests.delete(f"{API}/proxies", timeout=30)
    yield
    # cleanup: unassign and clear
    requests.post(f"{API}/proxies/unassign", json={"batch_id": None}, timeout=60)
    requests.delete(f"{API}/proxies", timeout=30)


# ----- Parse & Load -----
def test_load_proxies_mixed_formats():
    text = "\n".join([
        "d04010bb23577fd5e905__cr.us:c79f6d6c8267b56a@74.81.81.81:823",
        "1.1.1.1:1080",
        "2.2.2.2:1080:u1:p1",
        "socks5://u2:p2@3.3.3.3:1080",
        "d04010bb23577fd5e905__cr.us:c79f6d6c8267b56a@74.81.81.81:823",  # duplicate
        "garbagelinenoport",
        "",
    ])
    r = requests.post(f"{API}/proxies", json={"text": text, "proxy_type": "socks5"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["added"] == 4, data
    # duplicate + garbage = 2 skipped
    assert data["skipped"] >= 1
    assert data["total"] == 4


def test_list_proxies_masks_password():
    r = requests.get(f"{API}/proxies", timeout=30)
    assert r.status_code == 200
    proxies = r.json()
    assert len(proxies) == 4
    for p in proxies:
        assert "password" not in p
        assert set(["id", "proxy_type", "host", "port", "username", "label"]).issubset(p.keys())


def test_delete_single_proxy():
    proxies = requests.get(f"{API}/proxies", timeout=30).json()
    pid = proxies[-1]["id"]
    r = requests.delete(f"{API}/proxies/{pid}", timeout=30)
    assert r.status_code == 200
    remaining = requests.get(f"{API}/proxies", timeout=30).json()
    assert len(remaining) == 3
    assert all(p["id"] != pid for p in remaining)


# ----- Test proxy endpoint -----
def test_proxy_test_real_working():
    r = requests.post(f"{API}/proxies/test", json=REAL_PROXY, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True


def test_proxy_test_bogus():
    r = requests.post(f"{API}/proxies/test",
                      json={"proxy_type": "socks5", "host": "10.0.0.1", "port": 9},
                      timeout=30)
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body


# ----- Test stored proxy by id -----
def test_stored_proxy_test_ok():
    requests.delete(f"{API}/proxies", timeout=30)
    r = requests.post(f"{API}/proxies", json={
        "text": "d04010bb23577fd5e905__cr.us:c79f6d6c8267b56a@74.81.81.81:823",
        "proxy_type": "socks5"
    }, timeout=30)
    assert r.status_code == 200
    proxies = requests.get(f"{API}/proxies", timeout=30).json()
    assert len(proxies) == 1
    pid = proxies[0]["id"]
    r = requests.post(f"{API}/proxies/{pid}/test", timeout=30)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True


def test_stored_proxy_test_404():
    r = requests.post(f"{API}/proxies/nonexistent-id-xyz/test", timeout=30)
    assert r.status_code == 404


# ----- Assign / Unassign / Coverage -----
def test_assign_and_coverage():
    # ensure at least one proxy loaded
    r = requests.post(f"{API}/proxies", json={
        "text": "d04010bb23577fd5e905__cr.us:c79f6d6c8267b56a@74.81.81.81:823",
        "proxy_type": "socks5"
    }, timeout=30)
    assert r.status_code == 200

    r = requests.post(f"{API}/proxies/assign", json={"batch_id": None}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["assigned"] > 0

    cov = requests.get(f"{API}/proxies/coverage", timeout=30).json()
    assert cov["accounts_with_proxy"] > 0
    assert cov["accounts_with_proxy"] == cov["total_accounts"]


def test_accounts_list_does_not_leak_password():
    accs = requests.get(f"{API}/accounts", timeout=30).json()
    assert isinstance(accs, list)
    for a in accs[:20]:
        assert "proxy" not in a  # excluded
        # proxy_label MAY be present after assign
    # at least one should have proxy_label after assignment
    with_label = [a for a in accs if a.get("proxy_label")]
    assert len(with_label) > 0


def test_unassign_resets_coverage():
    r = requests.post(f"{API}/proxies/unassign", json={"batch_id": None}, timeout=60)
    assert r.status_code == 200
    cov = requests.get(f"{API}/proxies/coverage", timeout=30).json()
    assert cov["accounts_with_proxy"] == 0


def test_assign_empty_returns_400():
    requests.delete(f"{API}/proxies", timeout=30)  # clear all
    r = requests.post(f"{API}/proxies/assign", json={"batch_id": None}, timeout=30)
    assert r.status_code == 400


def test_clear_all():
    # reload one then clear
    requests.post(f"{API}/proxies", json={
        "text": "1.2.3.4:1080", "proxy_type": "socks5"
    }, timeout=30)
    r = requests.delete(f"{API}/proxies", timeout=30)
    assert r.status_code == 200
    remaining = requests.get(f"{API}/proxies", timeout=30).json()
    assert remaining == []
