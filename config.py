"""設定的唯一讀取點。其他模組一律 `import config` 再取值,不要自己讀 os.environ。

★ 為什麼集中在這裡(沿用 group-judge):模組層的 `X = os.environ.get("X")` 在 import
  當下就執行,只要它比 load_dotenv() 早被載入就會讀到空值,而且之後不會再重讀。
  集中成一支、由這一支自己先載入 .env,載入順序就不可能出錯。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _text(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _int(name: str, default: int) -> int:
    raw = _text(name)
    return int(raw) if raw else default


# ── 資料庫 ────────────────────────────────────────────────────
# ★ 沒有預設值也沒有備援:沒設就是連不上,不會退回任何本機資料庫。
DATABASE_URL = _text("DATABASE_URL")
# 資料庫一句查詢最多等幾秒,超過就放棄並回「資料庫暫時無法使用」。
DB_TIMEOUT_SECONDS = _int("DB_TIMEOUT_SECONDS", 20)
# 公用資料快取載入失敗時,隔幾秒再試(SPEC 第 3 節第 2 項:每 30 秒重試)。
CACHE_RETRY_SECONDS = _int("CACHE_RETRY_SECONDS", 30)
# 啟動時在背景載入公用資料快取。只有測試會關掉(tests/conftest.py)。
START_CACHE_LOADER = _text("START_CACHE_LOADER", "1") != "0"

# ── Google 登入 ───────────────────────────────────────────────
# Google Cloud 的「網頁應用程式」用戶端 ID。管理後台網頁登入用它;App 登入時
# 帶的 serverClientId 也是它,所以 App 送來的 ID token 的 aud 一樣是這個值。
GOOGLE_CLIENT_ID = _text("GOOGLE_CLIENT_ID")

# ── 管理後台 ──────────────────────────────────────────────────
# 允許呼叫後台 API 的網頁來源,逗號分隔,含 scheme、不要結尾斜線。
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _text("ALLOWED_ORIGINS").split(",") if o.strip()]
# 第一位管理員。用這個帳號登入後台一律放行,其他管理員在後台的「管理員」頁設定。
FIRST_ADMIN_EMAIL = _text("FIRST_ADMIN_EMAIL").lower()
# 後台 session token 的簽章金鑰。沒設的話後台登入回 503(其他功能照常)。
SESSION_SECRET = _text("SESSION_SECRET")
SESSION_IDLE_DAYS = _int("SESSION_IDLE_DAYS", 90)
# 「這張 session 是哪個管理員」的快取秒數。拿掉權限後最慢這麼久生效。
AUTH_CACHE_TTL_SECONDS = _int("AUTH_CACHE_TTL_SECONDS", 30)

# ── 每人每天的上限(SPEC 第 3、4、10 節;「一天」以台北時間計) ───────
DAILY_CHECK_LIMIT = _int("DAILY_CHECK_LIMIT", 10)
CONVERT_DAILY_LIMIT = _int("CONVERT_DAILY_LIMIT", 5)
FEEDBACK_DAILY_LIMIT = _int("FEEDBACK_DAILY_LIMIT", 3)

# ── 意見回饋 ──────────────────────────────────────────────────
FEEDBACK_RETENTION_DAYS = _int("FEEDBACK_RETENTION_DAYS", 90)
# 意見回饋資料表超過這個大小就不再收附件(記錄檔),並在後台顯示警告。
FEEDBACK_TABLE_LIMIT_MB = _int("FEEDBACK_TABLE_LIMIT_MB", 150)

# 目前跑的是哪一個 commit。Render 會自己帶這個環境變數,本機是空的。只給 /ready 用。
COMMIT = _text("RENDER_GIT_COMMIT")[:7]
# 5003:同一台機器上常常同時開著 group-judge(5002)。
PORT = _int("PORT", 5003)
