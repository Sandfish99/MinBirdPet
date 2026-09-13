# -*- coding: utf-8 -*-
"""验证方法（步骤4）：真实启动珉鸟 → 用 SendMessage(WM_NCHITTEST) 直接问
珉鸟窗口"这个屏幕坐标算谁"：
- 画布左上角（透明边距）必须返回 HTTRANSPARENT(-1)（点击穿透）
- 珉鸟身体中心（脚点上方）必须返回 HTCLIENT(1)（自己响应）
- 管理员权限窗口不受普通进程穿透影响（UIPI），属系统限制，无法自动化验证
"""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from minbird.platform import win32

HTTRANSPARENT, HTCLIENT = -1, 1
u32 = win32.user32
proc = subprocess.Popen([sys.executable, str(ROOT / "minbird_pet.py")])
try:
    hwnd = None
    for _ in range(50):
        time.sleep(0.2)
        hwnd = u32.FindWindowW("MinBirdPetWindow", None)
        if hwnd:
            break
    assert hwnd, "珉鸟窗口未创建"

    # 取窗口矩形与尺寸
    rect = win32.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top

    def nchittest(sx, sy) -> int:
        lp = (sy & 0xFFFF) << 16 | (sx & 0xFFFF)
        return u32.SendMessageW(hwnd, 0x0084, 0, lp)  # WM_NCHITTEST

    corner = nchittest(rect.left + 2, rect.top + 2)      # 画布边距：透明
    body = nchittest(rect.left + w // 2, rect.top + h - 20)  # 脚点上方：珉鸟身体
    print(f"角落(应 {HTTRANSPARENT}): {corner} | 身体(应 {HTCLIENT}): {body}")
    ok = (corner == HTTRANSPARENT) and (body == HTCLIENT)
    print("VERIFY-CLICKTHROUGH:", "PASS" if ok else "FAIL")
finally:
    u32.PostMessageW(proc.pid and u32.FindWindowW("MinBirdPetWindow", None),
                     0x0010, 0, 0)  # WM_CLOSE → 珉鸟干净退出
    time.sleep(1.0)
sys.exit(0 if ok else 1)
