"""/health 不碰資料庫;/ready 看資料庫與快取。"""

from __future__ import annotations

import pytest

from db.connection import pool


def test_health_never_touches_the_database(client, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("/health 不應該碰資料庫")

    monkeypatch.setattr(pool, "connection", boom)
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.get_json()["ok"] is True


@pytest.mark.db
def test_ready_after_cache_loads(client, db):
    from services import public_cache

    assert client.get("/ready").status_code == 503
    public_cache.reload()
    resp = client.get("/ready")
    assert resp.status_code == 200 and resp.get_json()["database_last_ok"] is not None


def test_ready_never_touches_the_database(client, monkeypatch):
    """/ready 不需要登入,所以不能碰資料庫(否則任何人都能讓 Neon 一直醒著)。"""
    def boom(*_a, **_k):
        raise AssertionError("/ready 不應該碰資料庫")

    monkeypatch.setattr(pool, "connection", boom)
    assert client.get("/ready").status_code == 503


def test_unknown_url_is_json(client):
    resp = client.get("/nope")
    assert resp.status_code == 404 and resp.get_json()["code"] == "http_404"


def test_cors_only_for_the_admin_site(client):
    resp = client.options("/api/admin/overview", headers={
        "Origin": "http://localhost:8003", "Access-Control-Request-Method": "GET"})
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:8003"
    resp = client.options("/api/admin/overview", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_loader_starts_on_first_request_not_at_import(monkeypatch):
    """背景載入要等第一個請求才開始,import 或建立 app 時不能開執行緒。"""
    import app as app_module
    from services import public_cache

    calls = []
    monkeypatch.setattr(public_cache, "start_background_loader", lambda: calls.append(1))
    flask_app = app_module.create_app(start_loader=True)
    assert calls == []
    flask_app.test_client().get("/health")
    assert calls == [1]


def test_gunicorn_access_log_is_off(app):
    """access log 會記下 IP,不管啟動參數怎麼設都要關掉。"""
    import logging

    assert logging.getLogger("gunicorn.access").disabled is True


def test_ready_says_whether_the_database_is_configured(client):
    assert "database_configured" in client.get("/ready").get_json()
