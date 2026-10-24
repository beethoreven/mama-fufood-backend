"""資料庫連線層。每次呼叫各自開一條連線,用號誌限制同時上限(做法沿用 group-judge)。

    with pool.connection() as conn:
        with conn.cursor() as cur:
            ...

正常離開就 commit,拋例外就 rollback,最後一定關掉。

## 為什麼不是連線池

group-judge 2026-08 實測:psycopg 的 ConnectionPool 在 Render 免費方案上會永久卡死
(閒置時容器被凍結,喚醒後連線池的背景執行緒沒有恢復)。每次請求自己開、自己關,
就沒有東西會「壞掉之後一直壞著」。連線池也會一直維持連線、把 Neon 叫醒,而本專案
平常(每日檢查)根本不碰資料庫(SPEC 第 3 節第 2 項)。

## 等多久

連不上最多等 _CONNECT_TIMEOUT 秒;每一句查詢最多等 config.DB_TIMEOUT_SECONDS 秒
(statement_timeout 寫成 SET LOCAL:Neon 的連線字串走交易層級的連線池,連線層級的
設定帶不過去)。資料庫完全沒回應時靠 tcp_user_timeout 讓作業系統斷線。
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import psycopg

import config
from db import schema

_MAX_CONCURRENT = 5
_SLOT_WAIT = 10
_CONNECT_TIMEOUT = 8

_slots = threading.BoundedSemaphore(_MAX_CONCURRENT)
# 最後一次成功連上資料庫的時間(UTC 秒)。/ready 用它回報,不必為了回報自己去連一次。
last_ok: float | None = None


class DatabaseBusy(Exception):
    """同時連線數已達上限,而且等不到名額。"""


class DatabaseNotConfigured(Exception):
    """沒有設定 DATABASE_URL。"""


class _Connections:
    @contextmanager
    def connection(self):
        if not config.DATABASE_URL:
            raise DatabaseNotConfigured("DATABASE_URL 未設定")
        if not _slots.acquire(timeout=_SLOT_WAIT):
            raise DatabaseBusy(f"資料庫同時連線已達上限（{_MAX_CONCURRENT}）")
        try:
            # prepare_threshold=None:不用伺服器端的預備語句(Neon 的 -pooler 是交易層級的池子)。
            conn = psycopg.connect(config.DATABASE_URL, connect_timeout=_CONNECT_TIMEOUT,
                                   tcp_user_timeout=config.DB_TIMEOUT_SECONDS * 1000,
                                   prepare_threshold=None)
            global last_ok
            last_ok = time.time()
            try:
                schema.ensure_once(conn)
                with conn:
                    conn.execute(f"SET LOCAL statement_timeout = {config.DB_TIMEOUT_SECONDS * 1000:d}")
                    yield conn
            finally:
                conn.close()
        finally:
            _slots.release()


pool = _Connections()
