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
