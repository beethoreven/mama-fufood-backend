"""Google ID Token 的驗證。

沿用 group-judge 的 auth_utils/google_auth.py(2026-10 上線過的版本),差別是回傳
帳號的固定編號(sub)與 Email 兩個值。

## App 與後台用法不同(刻意的)

- **App**:每次請求都帶一張新的 ID token,後端每次驗證,**刻意不做 session**
  (SPEC 第 2 節:App 對後端只有零星的短請求,每次一來一回就結束,不會有
  「做到一半被登出」的問題)。ID token 約一小時過期,App 每次送出前要先取得
  一張新的。
- **管理後台**:登入時驗證一次,換成我們自己簽發的 session(auth_utils/sessions.py)。

## 防護(都沿用 group-judge,理由寫在各自的位置)

1. 形狀不對的字串連 Google 的公開金鑰都不用拿,直接拒絕。
2. header 沒有 kid 的直接拒絕(否則 google-auth 會把每一把金鑰都拿來試,純 CPU)。
3. 用 CacheControl 快取 Google 的公開金鑰,不必每次向 Google 查。
4. 容許 10 秒的時鐘誤差。
5. 要求 email_verified。

這幾道都在碰資料庫之前。
"""

from __future__ import annotations

import base64
import json
import logging
import re

import cachecontrol
import requests as requests_lib
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

import config

log = logging.getLogger(__name__)

_CLOCK_SKEW_SECONDS = 10
_google_request = google_requests.Request(
    session=cachecontrol.CacheControl(requests_lib.session()),
)
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+$")
_MAX_ID_TOKEN_LENGTH = 8192


def _has_kid(token: str) -> bool:
    head = token.split(".", 1)[0]
    try:
        raw = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))
        return bool(json.loads(raw).get("kid"))
    except Exception:  # noqa: BLE001 - 解不開就是形狀不對,跟沒有 kid 同義
        return False


def extract_bearer_token(request) -> str | None:
    """從 Authorization: Bearer <token> 取出 token。"""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token or None


def verify(token: str | None) -> dict | None:
    """驗證 Google ID Token。通過回傳 {"sub": 帳號固定編號, "email": 小寫 Email},
    不通過回傳 None。

    sub 是 Google 帳號的固定編號,不會因為改 Email 而變,每日上限用它計數
    (SPEC 第 3 節第 3 項)。

    ★ 測試會把這支換掉(tests/conftest.py),所以呼叫端一律寫
      `google_auth.verify(...)`,不要 `from ... import verify`。
    """
    if not token or not config.GOOGLE_CLIENT_ID:
        return None
    if len(token) > _MAX_ID_TOKEN_LENGTH or not _JWT_SHAPE.match(token):
        return None
    if not _has_kid(token):
        return None
    try:
        payload = google_id_token.verify_oauth2_token(
            token, _google_request, config.GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        # 刻意不只攔 ValueError:取金鑰那段是真的網路請求,連不上時丟的是別的型別。
        # ★ 只記例外的型別與訊息,不記 token 本身(SPEC 第 3 節第 4 項:token 不印進日誌)。
        log.warning("Google ID Token 驗證失敗:%s", type(exc).__name__)
        return None
    if not payload.get("email_verified"):
        return None
    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        return None
    return {"sub": str(sub), "email": email.lower().strip()}
