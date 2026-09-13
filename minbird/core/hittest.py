# -*- coding: utf-8 -*-
"""逐像素命中判定（核心层，纯逻辑，零 OS 依赖）。

HTTRANSPARENT=-1 / HTCLIENT=1 为 Win32 数值约定，此处仅作为返回值数据；
alpha 阈值与拆分前完全一致（>28 视为不透明）。
"""
from __future__ import annotations

HTTRANSPARENT = -1
HTCLIENT = 1
ALPHA_THRESHOLD = 28


def hit_test(alpha_mask: bytes | None, w: int, h: int,
             x: int, y: int) -> int:
    """窗口内坐标 (x, y) 的命中结果。

    - 画布外 / alpha 低于阈值 → HTTRANSPARENT（点击穿透到下层窗口）
    - 其余 → HTCLIENT（珉鸟自己响应）
    - alpha_mask 为 None（首帧前）→ 放行为 HTCLIENT（保守）
    """
    if alpha_mask is None:
        return HTCLIENT
    if not (0 <= x < w and 0 <= y < h):
        return HTTRANSPARENT
    return HTCLIENT if alpha_mask[y * w + x] > ALPHA_THRESHOLD else HTTRANSPARENT
