# -*- coding: utf-8 -*-
"""子进程适配层：隐藏窗口地跑外部命令 / PowerShell。"""
from __future__ import annotations

import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          creationflags=_NO_WINDOW)


def _ps(script: str, timeout=30):
    # 统一让 PowerShell 输出 UTF-8（歌名/报错可能带中文），解码容错
    script = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    r = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
              "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
    r.stdout = (r.stdout or b"").decode("utf-8", "replace")
    r.stderr = (r.stderr or b"").decode("utf-8", "replace")
    return r


def _sq(s: str) -> str:
    """PowerShell 单引号字符串里把 ' 写成 ''。"""
    return str(s).replace("'", "''")


# 系统媒体会话（SMTC）：网易云 / QQ音乐 / Spotify 等主流播放器都接入了，
# 不用装任何依赖，问 Windows 就知道"现在谁在放什么歌"。
# 输出约定：SMTC_NONE = 会话正常但没在放；SMTC_META|歌手|歌名 = 在放；
# SMTC_PARTIAL = 这台机器的 WinRT 投影读不到状态/元数据 → 走窗口标题兜底。
