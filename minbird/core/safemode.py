# -*- coding: utf-8 -*-
"""安全模式判定（核心层，纯逻辑）。

连续异常退出达到阈值 → 下次启动进入安全模式（只保留桌宠基础能力），
一次干净退出即清零。
"""
from __future__ import annotations

SAFE_STREAK_THRESHOLD = 3


def next_streak(prev_state: dict) -> int:
    """根据上一次运行的残留状态算新的崩溃连击数。"""
    if prev_state.get("clean", True):
        return 0
    try:
        return int(prev_state.get("run_streak", 0)) + 1
    except (TypeError, ValueError):
        return 1


def safe_mode_required(crash_streak: int,
                       threshold: int = SAFE_STREAK_THRESHOLD) -> bool:
    return crash_streak >= threshold
