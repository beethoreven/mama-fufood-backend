"""在本機用唯讀帳號讀正式資料庫的意見回饋(除錯用)。

    .venv/bin/python tools/read_feedback.py                 # 最近 10 則的摘要
    .venv/bin/python tools/read_feedback.py <編號開頭幾碼>   # 那一則的完整內容與記錄檔

連線字串從環境變數 MFF_READONLY_DATABASE_URL 讀;沒有的話讀 ~/.config/mama-fufood/readonly.env
(內容是一行 MFF_READONLY_DATABASE_URL=postgresql://...)。這個檔案在 repo 外面,不會進 git。

★ 要用只有 feedback 表 SELECT 權限的帳號(建立方式見 README),不要用 Render 上那組
  DATABASE_URL:那組可以改、可以刪。這支程式另外也把連線設成唯讀,兩層保護。
★ 不印出連線字串;錯誤訊息只印類型,避免連線字串出現在畫面或記錄裡。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import payload  # noqa: E402

ENV_FILE = Path.home() / ".config" / "mama-fufood" / "readonly.env"
KEY = "MFF_READONLY_DATABASE_URL"
TAIPEI = timezone(timedelta(hours=8))


def _url() -> str:
    url = os.environ.get(KEY, "").strip()
    if not url and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == KEY:
                url = value.strip().strip('"').strip("'")
    if not url:
        sys.exit(f"找不到 {KEY}:設定環境變數,或寫在 {ENV_FILE}")
    return url


def _connect():
    """密碼裡有 @、: 這類符號時,網址會被讀錯(第一個 @ 被當成密碼結束)。
    所以自己拆:帳號到第一個冒號為止,主機從最後一個 @ 開始,中間都是密碼。"""
    url = _url()
    scheme, sep, rest = url.partition("://")
    creds, at, location = rest.rpartition("@")
    if not sep or not at or not scheme.startswith("postgres"):
        sys.exit("連線字串的格式要是 postgresql://帳號:密碼@主機/資料庫?參數")
    user, _, password = creds.partition(":")
    hostport, _, tail = location.partition("/")
    dbname, _, query = tail.partition("?")
    params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
    host, _, port = hostport.partition(":")
    return psycopg.connect(host=host, port=port or None, dbname=dbname, user=user, password=password,
                           connect_timeout=20, **params)


def _logs(attachment: bytes | None):
    if attachment is None:
        return None
    try:
        raw = payload.gunzip_limited(bytes(attachment), 4 * 1024 * 1024)
    except payload.PayloadError:
        return {"text": "(記錄檔解不開)"}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"text": raw.decode("utf-8", errors="replace")}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prefix = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        conn = _connect()
    except psycopg.Error as exc:
        sys.exit(f"連不上資料庫:{type(exc).__name__}")
    with conn:
        conn.read_only = True
        with conn.cursor() as cur:
            if prefix is None:
                cur.execute(
                    "SELECT id, received_at, kind, status, app_version, device_model, os_version, left(description, 60)"
                    "  FROM feedback ORDER BY received_at DESC LIMIT 10")
                for row in cur.fetchall():
                    fid, at, kind, status, ver, model, os_ver, desc = row
                    when = at.astimezone(TAIPEI)
                    print(f"{str(fid)[:8]}  {when:%Y-%m-%d %H:%M} GMT+8  {kind:<10} {status:<11} {ver:<8} {model} / {os_ver}")
                    print(f"          {desc}")
                return
            cur.execute(
                "SELECT id, received_at, email, kind, description, device_time, app_version, build_number,"
                "       device_model, os_version, snapshot, attachment, status, admin_note"
                "  FROM feedback WHERE id::text LIKE %s ORDER BY received_at DESC LIMIT 2",
                (prefix + "%",),
            )
            rows = cur.fetchall()
    if not rows:
        sys.exit("找不到這個編號的意見回饋")
    if len(rows) > 1:
        sys.exit("這個開頭對到不只一則,請多給幾碼")
    keys = ("id", "received_at", "email", "kind", "description", "device_time", "app_version", "build_number",
            "device_model", "os_version", "snapshot", "attachment", "status", "admin_note")
    item = dict(zip(keys, rows[0]))
    item["id"] = str(item["id"])
    item["received_at"] = item["received_at"].astimezone(TAIPEI).isoformat()
    item["logs"] = _logs(item.pop("attachment"))
    print(json.dumps(item, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
