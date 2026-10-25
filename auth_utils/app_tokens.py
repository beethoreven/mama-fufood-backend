"""App 的登入通行證。

使用者在 App 裡按一次「登入」,App 拿 Google 的 ID Token 換一張通行證存在手機上;
之後的每日檢查、意見回饋、格式轉換都帶這張,不用每次再跟 Google 要新的 ID Token。

為什麼要有這一層:Google 的 ID Token 大約一小時就過期,每次要一張新的得靠 Android
的「自動登入」;系統不肯自動登入時,Google 的登入外掛會改跳選帳號畫面,使用者按掉就變成
沒登入(實際發生過:重開 App 就跳選帳號、登入不見)。ID Token 只用在登入那一刻,
之後用我們自己的通行證,是一般的做法。

- **無狀態**:內容是 {"v", "sub", "email", "iat", "exp"} 加上 HMAC 簽章。伺服器**不保存**
  任何東西,只驗證簽章與期限(隱私權政策:伺服器不保存登入資料)。
- 有效期 APP_TOKEN_DAYS 天。每日檢查時,這張已經發出超過 APP_TOKEN_RENEW_DAYS 天
  就在回應裡附一張新的,所以有在用就不會過期;半年沒開 App 才要重新登入。
- 撤銷:沒有個別撤銷的機制(沒有資料庫)。要讓所有通行證失效就換 SESSION_SECRET。
- 簽章金鑰從 SESSION_SECRET 衍生,和管理後台的 session 用不同的用途字串,兩邊的
  token 不能互用。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

import config

PREFIX = "mff1."
APP_TOKEN_DAYS = 180
APP_TOKEN_RENEW_DAYS = 30
_DAY = 24 * 60 * 60
_MAX_LEN = 1024


def enabled() -> bool:
    return bool(config.SESSION_SECRET)


def _key() -> bytes:
    return hmac.new(config.SESSION_SECRET.encode("utf-8"), b"mama-fufood:app-token:v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(sub: str, email: str, now: float | None = None) -> tuple[str, int]:
    """發一張通行證。回傳(token, 到期時間的 Unix 秒)。"""
    now = int(time.time() if now is None else now)
    exp = now + APP_TOKEN_DAYS * _DAY
    body = _b64(json.dumps({"v": 1, "sub": sub, "email": email, "iat": now, "exp": exp},
                           separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{PREFIX}{body}.{sig}", exp


def is_app_token(token: str | None) -> bool:
    return bool(token) and token.startswith(PREFIX)


def verify(token: str | None, now: float | None = None) -> dict | None:
    """簽章對、沒過期就回傳 {"sub", "email", "renew"};否則 None。**不碰資料庫**。

    renew = 這張已經發出超過 APP_TOKEN_RENEW_DAYS 天,呼叫端可以順便發一張新的。
    """
    if not enabled() or not is_app_token(token) or len(token) > _MAX_LEN:
        return None
    body, dot, sig = token[len(PREFIX):].partition(".")
    if not dot:
        return None
    expected = _b64(hmac.new(_key(), body.encode("ascii", errors="replace"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    now = time.time() if now is None else now
    if (not isinstance(claims, dict) or claims.get("v") != 1 or not isinstance(claims.get("sub"), str)
            or not isinstance(claims.get("email"), str) or not isinstance(claims.get("exp"), int)
            or not isinstance(claims.get("iat"), int) or claims["exp"] <= now):
        return None
    return {"sub": claims["sub"], "email": claims["email"],
            "renew": now - claims["iat"] > APP_TOKEN_RENEW_DAYS * _DAY}
