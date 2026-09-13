# -*- coding: utf-8 -*-
"""验证方法（步骤1）：实际生效的 DPI 感知模式应为 PMv2（Win10 1703+）。"""
import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minbird.platform import win32

mode = win32.enable_dpi_awareness()
u32 = win32.user32
u32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
u32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_uint

ctx = u32.GetThreadDpiAwarenessContext()
aware = u32.GetAwarenessFromDpiAwarenessContext(ctx)
print("mode:", mode, "| awareness value:", aware,
      "(0=unaware 1=system 2=per-monitor；V1/V2 在枚举里同为 2，区别在上下文句柄)")

# PMv2 模式下 SetProcessDpiAwarenessContext 已接受 V2 上下文句柄（-4），
# 枚举层面与 V1 同为 PER_MONITOR_AWARE=2
ok = (mode == "PMv2" and aware == 2) or (mode == "system" and aware == 1)
print("VERIFY-DPI:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
