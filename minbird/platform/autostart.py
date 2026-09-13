# -*- coding: utf-8 -*-
r"""开机自启适配器：HKCU\...\Run 注册表键。"""
from __future__ import annotations

import os
import sys

# 源码运行时的项目根目录（与 minbird_pet._base_dir 等价；打包运行走 sys.executable 分支）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



def autostart_target() -> str:
    """Command line used for the Run registry entry."""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    script = os.path.join(BASE_DIR, "minbird_pet.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return f'"{exe}" "{script}"'


def autostart_enabled() -> bool:
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            val, _ = winreg.QueryValueEx(k, "MinBirdPet")
            return bool(val)
    except OSError:
        return False


def set_autostart(enable: bool) -> bool:
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, "MinBirdPet", 0, winreg.REG_SZ, autostart_target())
            else:
                try:
                    winreg.DeleteValue(k, "MinBirdPet")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# 可站立的窗口表面
#
# 把「可见应用窗口的顶边（标题栏）」也当成珉鸟脚下的地面。z 序、透明穿透层、
# UWP 挂起窗口、桌面和任务栏都过滤掉，只留真正看得见、站得上去的正常窗口。
# --------------------------------------------------------------------------
GROUND_TOL = 10.0    # 站立判定：脚点下方 2px、上方 10px 以内的窗沿都算踩着
RIDE_SNAP = 56.0     # 窗口被拖动、顶边一帧抬高 56px 以内时，鸟直接跟着上去


