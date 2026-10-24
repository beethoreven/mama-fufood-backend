"""時間的唯一來源。

- 存與比較一律用 UTC(SPEC 第 3 節:時間戳用 UTC 儲存)。
- 「一天」以台北時間計(每日上限、午夜清空)。台灣沒有日光節約時間,固定 UTC+8,
  所以不需要時區資料庫。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")
_STAMP = "%Y%m%d%H%M%S"


def now() -> datetime:
    """現在(UTC)。測試會把這支換掉來模擬跨日。"""
    return datetime.now(timezone.utc)


def taipei_today() -> date:
    return now().astimezone(TAIPEI).date()


def taipei_day_start_utc() -> datetime:
    """台北時間今天 00:00,換成 UTC。"""
    d = taipei_today()
    return datetime(d.year, d.month, d.day, tzinfo=TAIPEI).astimezone(timezone.utc)


def stamp(dt: datetime) -> str:
    """公用資料的版本號:發布時間的年月日時分秒(UTC),例如 20261021153000。"""
    return dt.astimezone(timezone.utc).strftime(_STAMP)


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, _STAMP).replace(tzinfo=timezone.utc)


def next_stamp(previous: str | None) -> str:
    """下一個版本號:現在的時間;萬一不比上一版大(同一秒內發布兩次、時鐘倒退),
    就用上一版加一秒,保證版本號只會往上。"""
    candidate = stamp(now())
    if previous and candidate <= previous:
        return stamp(parse_stamp(previous) + timedelta(seconds=1))
    return candidate
