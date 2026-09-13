# -*- coding: utf-8 -*-
"""运行环境探测（平台适配层）：远程桌面 / 虚拟机识别。"""
from __future__ import annotations

import ctypes

SM_REMOTESESSION = 0x1000

# 常见虚拟机的 CPU 品牌 / 主板信息标记（小写匹配）
_VM_MARKERS = ("vmware", "virtualbox", "kvm", "qemu", "virtual machine",
               "hyper-v", "bochs", "xen", "parallels", "vbox")


def is_remote_session() -> bool:
    """当前会话是否为远程桌面（RDP）。"""
    try:
        return bool(ctypes.windll.user32.GetSystemMetrics(SM_REMOTESESSION))
    except Exception:
        return False


def _cpu_brand() -> str:
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            val, _ = winreg.QueryValueEx(k, "ProcessorNameString")
            return str(val).lower()
    except OSError:
        return ""


def _board_info() -> str:
    try:
        import winreg
        out = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\BIOS") as k:
            for name in ("SystemManufacturer", "SystemProductName"):
                try:
                    out.append(str(winreg.QueryValueEx(k, name)[0]))
                except OSError:
                    pass
        return " ".join(out).lower()
    except OSError:
        return ""


def vm_markers_hit(haystack: str) -> list[str]:
    """纯逻辑：命中的虚拟机标记列表（大小写不敏感，便于单测）。"""
    hay = haystack.lower()
    return [m for m in _VM_MARKERS if m in hay]


def is_virtual_machine() -> bool:
    hay = _cpu_brand() + " " + _board_info()
    return bool(vm_markers_hit(hay))


def degrade_reasons() -> list[str]:
    """应降级运行的原因（空列表 = 不降级）。"""
    reasons = []
    if is_remote_session():
        reasons.append("远程桌面会话")
    if is_virtual_machine():
        reasons.append("虚拟机")
    return reasons
