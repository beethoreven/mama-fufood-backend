"""字數與版本號這類小工具。"""

from __future__ import annotations

import re as _re

import regex

_VERSION = _re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d)$")


def graphemes(text: str) -> int:
    """使用者看到的字數:一個 emoji(包含 👨‍👩‍👧 這種組合)算一個字。

    ★ 不能用 len():len() 算的是 Unicode 碼位,一個家庭 emoji 就是 5 個。
      App 端用 Dart 的 characters 套件算,兩邊的規則都是 Unicode 的字素叢集。
    """
    return len(regex.findall(r"\X", text))


def parse_version(text: object) -> tuple[int, int, int] | None:
    """App 版本 x.y.z → (x, y, z);格式不對回 None。

    範圍照 SPEC 第 2 節的版本號規則:x、y 最大 99,z 最大 9。
    """
    if not isinstance(text, str):
        return None
    m = _VERSION.match(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
