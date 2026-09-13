# -*- coding: utf-8 -*-
"""屏幕几何纯逻辑（核心层，零 OS 依赖）。"""
from __future__ import annotations


def clamp_into(rect, x: float, y: float, pad: int = 8,
               bottom_pad: int = 2) -> tuple[float, float]:
    """把点钳进矩形内（默认脚点：左右留 pad，底部留 bottom_pad）。"""
    lo = rect.left + pad
    hi = rect.right - pad
    if hi < lo:
        lo = hi = rect.left
    return (min(max(x, lo), hi),
            min(max(y, rect.top + pad), rect.bottom - bottom_pad))


def relative_of(rect, x: float, y: float) -> tuple[float, float]:
    """点在矩形内的相对坐标（0~1，越界钳回）。"""
    w = max(1, rect.right - rect.left)
    h = max(1, rect.bottom - rect.top)
    rx = (x - rect.left) / w
    ry = (y - rect.top) / h
    return (min(max(rx, 0.0), 1.0), min(max(ry, 0.0), 1.0))


def point_from_relative(rect, rx: float, ry: float) -> tuple[float, float]:
    """相对坐标 → 绝对坐标（钳回矩形内）。"""
    rx = min(max(rx, 0.0), 1.0)
    ry = min(max(ry, 0.0), 1.0)
    return (rect.left + (rect.right - rect.left) * rx,
            rect.top + (rect.bottom - rect.top) * ry)
