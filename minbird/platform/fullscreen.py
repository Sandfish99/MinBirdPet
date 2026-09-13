# -*- coding: utf-8 -*-
"""前台全屏检测（平台适配层）：游戏/全屏视频识别。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from minbird.platform.monitors import MONITORINFOEXW
from minbird.platform.win32 import RECT, _get_window_long, dwmapi, user32

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
DWMWA_CLOAKED = 14

_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd",
                  "Shell_SecondaryTrayWnd"}

user32.GetForegroundWindow.restype = wt.HWND
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def looks_fullscreen(style: int, win_rect, mon_rect, cloaked: bool,
                     cls_name: str) -> bool:
    """纯判定（核心语义，放适配层便于与 OS 常量同址）：
    盖满所在屏 + 无标题栏 + 未被 DWM 遮蔽 + 不是壳窗口。"""
    if cls_name in _SHELL_CLASSES or cloaked:
        return False
    if style & WS_CAPTION:
        return False
    return (win_rect.left, win_rect.top, win_rect.right, win_rect.bottom) == \
           (mon_rect.left, mon_rect.top, mon_rect.right, mon_rect.bottom)


def fullscreen_hwnd(own_hwnd=None) -> int | None:
    """前台全屏窗口句柄；没有则 None。own_hwnd 用于排除珉鸟自己。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == own_hwnd:
        return None
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    style = _get_window_long(hwnd, GWL_STYLE)
    cloaked = wt.DWORD()
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                 ctypes.sizeof(cloaked))
    win_rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(win_rect)):
        return None
    hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    if looks_fullscreen(style, win_rect, mi.rcMonitor,
                        bool(cloaked.value), buf.value):
        return hwnd
    return None
