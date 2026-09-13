# -*- coding: utf-8 -*-
"""内存占用查询（平台适配层）：当前进程工作集大小。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD),
                ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def current_rss_mb() -> float | None:
    """当前进程工作集（MB）；查询失败返回 None（调用方自行降级）。"""
    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # 伪句柄 (-1)
        if not psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle),
                                          ctypes.byref(pmc), pmc.cb):
            return None
        return pmc.WorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        return None
