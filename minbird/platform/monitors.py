# -*- coding: utf-8 -*-
"""显示器枚举（平台适配层）：每屏工作区、按点找屏、虚拟桌面范围。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from minbird.core.interfaces import Rect
from minbird.platform.win32 import POINT, RECT, user32, work_area


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wt.BOOL
user32.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
user32.MonitorFromPoint.restype = wt.HMONITOR


def work_areas() -> list[Rect]:
    """每个显示器的有效工作区（去掉任务栏）。至少返回主屏一个。"""
    hmons: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC,
                        ctypes.POINTER(RECT), wt.LPARAM)
    def _cb(hmon, _hdc, _rc, _lp):
        hmons.append(hmon)
        return True

    user32.EnumDisplayMonitors(None, None, _cb, 0)
    out: list[Rect] = []
    for hmon in hmons:
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            out.append(Rect(r.left, r.top, r.right, r.bottom))
    if not out:
        wa = work_area()
        out.append(Rect(wa.left, wa.top, wa.right, wa.bottom))
    return out


def work_area_for_point(x: float, y: float) -> Rect:
    """点所在显示器的有效工作区；点在所有屏之外时取最近的屏。"""
    hmon = user32.MonitorFromPoint(POINT(int(x), int(y)), 2)
    if hmon:
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            return Rect(r.left, r.top, r.right, r.bottom)
    areas = work_areas()
    return areas[0]


def virtual_screen() -> tuple[int, int, int, int]:
    """虚拟桌面包围盒 (left, top, right, bottom)。"""
    sm = user32.GetSystemMetrics
    l, t = sm(76), sm(77)
    w, h = sm(78), sm(79)
    return (l, t, l + w, t + h)
