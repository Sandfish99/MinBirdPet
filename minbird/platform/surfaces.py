# -*- coding: utf-8 -*-
"""窗口表面探测（平台适配层）：枚举可作为地面的应用窗口。

珉鸟"站在/走在应用窗口标题栏上"的能力全部依赖本模块的 OS 查询。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

import os

from minbird.platform.win32 import (
    DWMWA_CLOAKED,
    DWMWA_EXTENDED_FRAME_BOUNDS,
    ENUMPROC,
    GWL_EXSTYLE,
    GWL_STYLE,
    RECT,
    WS_CHILD,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    _get_window_long,
    dwmapi,
    user32,
)

GROUND_TOL = 10.0    # 站立判定：脚点下方 2px、上方 10px 以内的窗沿都算踩着
RIDE_SNAP = 56.0     # 窗口被拖动、顶边一帧抬高 56px 以内时，鸟直接跟着上去
PERCH_SNAP = 160.0   # 下落没进窗口时，离窗沿多高以内会「扑棱」上去落住


class WindowSurfaces:
    """枚举可作为地面的应用窗口，回答三个问题：

    - ground_at：站在 (fx, fy) 时脚下有没有窗沿（站立 / 沿窗沿走 / 跟着窗口拖动）
    - landing_at：这一帧从 prev_fy 掉到 fy，脚底扫过了哪条窗沿（落地）
    - perch_at：身体已经没进某扇窗口时，够不够得着它的窗沿扑棱上去
    """

    SKIP_CLASSES = {
        "Progman", "WorkerW",                       # 桌面
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd",  # 任务栏（由 work_area 兜底）
        "Shell_ChangeWindow", "NotifyIconOverflowWindow",
        "SysListView32", "SHELLDLL_DefView",
        "Tooltips_class32", "SysShadow", "BaseBar",
        "MSCTFIME UI", "Default IME",
        "Windows.UI.Core.CoreWindow",               # 开始菜单 / 提示等 shell 界面
        "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
    }
    MIN_W = 64    # 太窄的条状窗不给站
    MIN_H = 60
    ENUM_INTERVAL = 1.0   # 秒；重新枚举窗口列表的间隔，rect 每帧另取实时值

    def __init__(self) -> None:
        self.enabled = True
        self.min_top = 0.0    # 顶边比这更高的窗沿不站（鸟身子会探出屏幕外），由 App 按体型设置
        self._own_pid = os.getpid()
        self._own_hwnd = None
        self._windows = []          # hwnd 列表，z 序（前 → 后）
        self._next_enum = 0.0

    def set_own_hwnd(self, hwnd) -> None:
        self._own_hwnd = hwnd

    def refresh(self, now: float) -> None:
        """重建窗口列表（每秒一次，便宜）。"""
        if now < self._next_enum:
            return
        self._next_enum = now + self.ENUM_INTERVAL
        found = []

        def on_window(hwnd, _lparam):
            try:
                if self._walkable(hwnd):
                    found.append(hwnd)
            except Exception:
                pass
            return True

        user32.EnumWindows(ENUMPROC(on_window), 0)
        self._windows = found

    def _walkable(self, hwnd: int) -> bool:
        if not hwnd or hwnd == self._own_hwnd:
            return False
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return False
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == self._own_pid:
            return False          # 自己（鸟、气泡、托盘）不算地面
        cloak = wt.DWORD(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloak),
                                        ctypes.sizeof(cloak)) == 0 and cloak.value:
            return False          # UWP 挂起 / 被遮蔽的窗口
        exstyle = _get_window_long(hwnd, GWL_EXSTYLE)
        if exstyle & (WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT):
            return False          # 工具窗、点击穿透的悬浮层
        if _get_window_long(hwnd, GWL_STYLE) & WS_CHILD:
            return False
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, 256)
        if name.value in self.SKIP_CLASSES:
            return False
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return False
        rect = self._bounds(hwnd)
        if rect is None:
            return False
        return (rect.right - rect.left >= self.MIN_W
                and rect.bottom - rect.top >= self.MIN_H)

    @staticmethod
    def _bounds(hwnd: int) -> RECT | None:
        """可见边界。GetWindowRect 带一圈透明的 resize 边框，最大化窗口还会
        超出屏幕 8px，所以优先用 DWM 的扩展边界，鸟才能正好站在标题栏上。"""
        rect = RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                        ctypes.byref(rect),
                                        ctypes.sizeof(rect)) == 0 \
                and rect.right > rect.left and rect.bottom > rect.top:
            return rect
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect
        return None

    def _live(self) -> list:
        out = []
        for hwnd in self._windows:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                continue
            rect = self._bounds(hwnd)
            if rect is not None and rect.right > rect.left and rect.bottom > rect.top:
                out.append(rect)
        return out

    def ground_at(self, fx: float, fy: float, fallback: float) -> float:
        """站立/行走时的地面。脚点下方 2px 落在哪扇窗口里，就站它的顶边。"""
        if not self.enabled:
            return fallback
        px, py = int(fx), int(fy) + 2
        for rect in self._live():          # z 序：最前面的先看
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                standable = rect.top >= self.min_top
                if standable and rect.top >= fy - GROUND_TOL:
                    return float(rect.top)
                if standable and fy - rect.top <= RIDE_SNAP:
                    return float(rect.top)   # 窗口刚被拖高 —— 跟着上去
                break   # 顶边压在脚上方 / 太高站不下：贴着它前面掉下去
        return fallback

    def landing_at(self, fx: float, prev_fy: float, fy: float,
                   fallback: float) -> float:
        """下落时这一帧脚底扫过的最高窗沿（最先碰到的那条）。

        只看脚点正前方那扇最前面的窗口 —— 它的顶边被更高处的窗沿挡住时
        （顶边不在这一帧的扫过区间里），鸟就贴着它前面继续掉，不会站到
        被挡住的隐形窗沿上。
        """
        if not self.enabled:
            return fallback
        px, py = int(fx), int(fy) + 2
        for rect in self._live():
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                if prev_fy <= rect.top <= fy and rect.top >= self.min_top:
                    return float(rect.top)
                break
        return fallback

    def perch_at(self, fx: float, fy: float, max_rise: float) -> float | None:
        """脚点已经没入某扇窗口时，给一条够得着的窗沿让它扑棱上去。"""
        if not self.enabled:
            return None
        px, py = int(fx), int(fy) + 2
        for rect in self._live():
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                if fy - rect.top <= max_rise and rect.top >= self.min_top:
                    return float(rect.top)
                return None   # 窗沿太高够不着 —— 贴着窗口前面滑下去
        return None


