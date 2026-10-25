"""App 的登入通行證:Google ID Token 只用在登入那一刻,之後用我們自己發的通行證。"""

from __future__ import annotations

import time

import pytest

from auth_utils import app_tokens, sessions
from tests.conftest import bearer

DAY = 24 * 60 * 60


def test_issue_and_verify():
    token, exp = app_tokens.issue("user-1", "mom@example.com")
    assert token.startswith("mff1.")
    assert exp - time.time() == pytest.approx(app_tokens.APP_TOKEN_DAYS * DAY, abs=5)
    assert app_tokens.verify(token) == {"sub": "user-1", "email": "mom@example.com", "renew": False}


def test_tampered_or_foreign_tokens_are_rejected():
    token, _ = app_tokens.issue("user-1", "mom@example.com")
    body, sig = token[len("mff1."):].split(".")
    other, _ = app_tokens.issue("user-2", "someone@example.com")
    forged = "mff1." + other[len("mff1."):].split(".")[0] + "." + sig
    for bad in (forged, token[:-2] + "xx", "mff1." + body, "mff1.", "", None, "tok:user-1:mom@example.com"):
        assert app_tokens.verify(bad) is None, bad
    # 管理後台的 session 和通行證不能互用。
    admin_like = "a" * 40 + "b" * 24
    assert app_tokens.verify(admin_like) is None
    assert not sessions.looks_valid(token)


def test_expiry_and_renewal():
    issued_at = time.time() - (app_tokens.APP_TOKEN_RENEW_DAYS + 1) * DAY
    token, _ = app_tokens.issue("user-1", "mom@example.com", now=issued_at)
    assert app_tokens.verify(token)["renew"] is True
    old, _ = app_tokens.issue("user-1", "mom@example.com", now=time.time() - (app_tokens.APP_TOKEN_DAYS + 1) * DAY)
    assert app_tokens.verify(old) is None


def test_session_endpoint_exchanges_a_google_token(client):
    resp = client.post("/api/v1/session", headers=bearer("user-9", "dad@example.com"))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert app_tokens.verify(data["token"])["sub"] == "user-9"
    assert client.post("/api/v1/session", headers={"Authorization": "Bearer nope"}).status_code == 401
    # 通行證本身不能拿來換新的通行證(只有 Google 登入才能換)。
    assert client.post("/api/v1/session", headers={"Authorization": f"Bearer {data['token']}"}).status_code == 401


@pytest.mark.db
def test_daily_check_accepts_the_app_token_and_renews_old_ones(client, db):
    body = {"app_version": "1.0.0", "datasets": {"food_list": {"version": None, "formats": [1]}}}
    fresh, _ = app_tokens.issue("user-1", "mom@example.com")
    resp = client.post("/api/v1/check", json=body, headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 200, resp.get_json()
    assert "session_token" not in resp.get_json()

    old, _ = app_tokens.issue("user-1", "mom@example.com", now=time.time() - 40 * DAY)
    data = client.post("/api/v1/check", json=body, headers={"Authorization": f"Bearer {old}"}).get_json()
    assert app_tokens.verify(data["session_token"]) == {"sub": "user-1", "email": "mom@example.com", "renew": False}
    assert data["session_expires_at"] > time.time()
