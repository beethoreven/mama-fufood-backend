"""測試共用的設定。

- 標了 `db` 的測試需要一個可以隨便清空的 Postgres:環境變數 TEST_DATABASE_URL
  (本機用 `tools/local_db.sh start` 開一個)。沒設就跳過那些測試,其餘照跑。
- **不要拿正式的資料庫來跑**:每個 db 測試開始前會把整個 public schema 清空。
- Google 的 ID token 驗證換成假的:`tok:<sub>:<email>` 這種字串會被當成驗證通過。
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

# ★ 一定要在 import config 之前設好(config 在 import 時讀環境變數)。
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["START_CACHE_LOADER"] = "0"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["FIRST_ADMIN_EMAIL"] = "admin@example.com"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8003"

import config  # noqa: E402
from app import create_app  # noqa: E402
from auth_utils import access, google_auth  # noqa: E402
from db import schema  # noqa: E402
from routes import public  # noqa: E402
from services import public_cache  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def fake_verify(token):
    if not isinstance(token, str) or not token.startswith("tok:"):
        return None
    _, sub, email = token.split(":", 2)
    return {"sub": sub, "email": email.lower()}


def bearer(sub: str = "user-1", email: str = "mom@example.com") -> dict:
    return {"Authorization": f"Bearer tok:{sub}:{email}"}


@pytest.fixture(autouse=True)
def _fake_google(monkeypatch):
    monkeypatch.setattr(google_auth, "verify", fake_verify)
    public.check_quota.clear()
    public.convert_quota.clear()
    public.feedback_attempts.clear()
    from routes import admin as admin_routes
    admin_routes.login_attempts.clear()
    access.forget_all()
    yield


@pytest.fixture
def app():
    return create_app(start_loader=False)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db():
    """清空測試資料庫,讓下一次連線重新建表與放入第一版公用資料。"""
    if not TEST_DATABASE_URL:
        pytest.skip("沒有設定 TEST_DATABASE_URL")
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    schema.reset_for_tests()
    public_cache.reset_for_tests()
    yield TEST_DATABASE_URL
    public_cache.reset_for_tests()


@pytest.fixture
def admin_token(client, db):
    resp = client.post("/api/admin/login", json={"credential": "tok:admin-sub:admin@example.com"})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["token"]


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def load_seed(name: str) -> dict:
    return json.loads((ROOT / "seed" / f"{name}.json").read_text(encoding="utf-8"))


def load_sample(version: int) -> dict:
    return json.loads((ROOT / "export_formats" / "samples" / f"v{version}.json").read_text(encoding="utf-8"))


def gz(data) -> bytes:
    return gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))


__all__ = ["bearer", "admin_headers", "load_seed", "load_sample", "gz", "config"]
