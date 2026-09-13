# -*- coding: utf-8 -*-
"""开机签名适配器：读取系统上次启动时间，用于判断本次开机后是否首次启动。"""
from __future__ import annotations

from minbird.platform.proc import _ps


def boot_signature() -> str:
    """本次开机的签名（系统上次启动时间）；拿不到就返回空。"""
    try:
        r = _ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('s')",
                timeout=25)
        return (getattr(r, "stdout", "") or "").strip()
    except Exception:
        return ""


