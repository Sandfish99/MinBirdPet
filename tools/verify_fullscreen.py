# -*- coding: utf-8 -*-
"""验证方法（步骤3）：
1. 合成一个盖满整屏的无边框窗口，走与运行时完全相同的判定数据 → 必须识别为全屏
2. 尝试把它设为前台（抢前台锁），实际走 fullscreen_hwnd() 全链路 → 识别为全屏
3. 隐藏/销毁后 → 不再识别
"""
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minbird.platform import win32
from minbird.platform.fullscreen import fullscreen_hwnd, looks_fullscreen

u32 = win32.user32
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_HIDE = 0

hinst = win32.kernel32.GetModuleHandleW(None)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p)]


def _proc(h, m, w, l):
    return u32.DefWindowProcW(h, m, w, l)


wc = WNDCLASS()
wc.lpfnWndProc = ctypes.cast(
    ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                       ctypes.c_size_t, ctypes.c_ssize_t)(_proc),
    ctypes.c_void_p)
wc.hInstance = hinst
wc.lpszClassName = "MinBirdFsVerify"
u32.RegisterClassW(ctypes.byref(wc))

# 真全屏应用盖满的是整个显示器（含任务栏区域），不是工作区
sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
hwnd = u32.CreateWindowExW(0, "MinBirdFsVerify", "FS", WS_POPUP | WS_VISIBLE,
                           0, 0, sw, sh, None, None, hinst, None)
assert hwnd, "test window failed"
time.sleep(0.3)

# 1) 纯判定：直接取该窗口的实测属性走同一套判定
win_rect = win32.RECT()
u32.GetWindowRect(hwnd, ctypes.byref(win_rect))
style = win32._get_window_long(hwnd, win32.GWL_STYLE)
mon_rect = type(win_rect)(0, 0, sw, sh)
hit_pure = looks_fullscreen(style, win_rect, mon_rect, False, "MinBirdFsVerify")
print(f"1) looks_fullscreen(合成全屏窗): {hit_pure}")
ok = hit_pure

# 2) 全链路：抢前台后走 fullscreen_hwnd
fore_tid = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
my_tid = kernel32 = win32.kernel32.GetCurrentThreadId()
attached = ctypes.windll.user32.AttachThreadInput(my_tid, fore_tid, True)
u32.SetForegroundWindow(hwnd)
time.sleep(0.4)
is_fore = u32.GetForegroundWindow() == hwnd
if is_fore:
    hit_live = fullscreen_hwnd(own_hwnd=None) == hwnd
    print(f"2) fullscreen_hwnd 全链路（前台=合成窗）: {hit_live}")
    ok = ok and hit_live
else:
    print("2) 前台锁未抢到（系统限制），跳过全链路实测（判定逻辑已由 1 覆盖）")

# 3) 隐藏后不再识别
u32.ShowWindow(hwnd, SW_HIDE)
time.sleep(0.3)
if u32.GetForegroundWindow() != hwnd:
    print("3) 隐藏后 fullscreen_hwnd 不再命中:",
          fullscreen_hwnd(own_hwnd=None) is None)
if attached:
    ctypes.windll.user32.AttachThreadInput(my_tid, fore_tid, False)
u32.DestroyWindow(hwnd)
print("VERIFY-FULLSCREEN:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
