# -*- coding: utf-8 -*-
"""计划任务适配器：注册/注销"每小时自动查余额"的 Windows 计划任务。"""
from __future__ import annotations

import subprocess
import sys
import time

from minbird.platform.proc import _ps, _run, _sq


TASK_NAME = "MinBirdPet-BalanceCheck"


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def boot_signature() -> str:
    """本次开机的签名（系统上次启动时间）；拿不到就返回空。"""
    try:
        r = _ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('s')",
                timeout=25)
        return (getattr(r, "stdout", "") or "").strip()
    except Exception:
        return ""


def _date_line() -> str:
    t = time.localtime()
    return f"{t.tm_mon}月{t.tm_mday}日 周{'一二三四五六日'[t.tm_wday]}"


def balance_task_enabled() -> bool:
    # 先试 schtasks；少数机器禁用了 schtasks.exe，再用 PowerShell cmdlet
    try:
        if _run(["schtasks", "/query", "/tn", TASK_NAME], timeout=10).returncode == 0:
            return True
    except Exception:
        pass
    try:
        r = _ps(f"if (Get-ScheduledTask -TaskName '{_sq(TASK_NAME)}' "
                f"-ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}")
        return r.returncode == 0
    except Exception:
        return False


def _task_schtasks(enable: bool, hours: int) -> tuple:
    try:
        if enable:
            tr = f'"{sys.executable}" --check-balance'
            cmd = ["schtasks", "/create", "/tn", TASK_NAME, "/tr", tr,
                   "/sc", "hourly", "/mo", str(hours), "/f"]
        else:
            cmd = ["schtasks", "/delete", "/tn", TASK_NAME, "/f"]
        r = _run(cmd)
        if r.returncode == 0:
            return True, "已开启" if enable else "已关闭"
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else f"退出码 {r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or "schtasks 调不动"


def _task_powershell(enable: bool, hours: int) -> tuple:
    name, exe = _sq(TASK_NAME), _sq(sys.executable)
    if enable:
        script = (
            "$ErrorActionPreference='Stop';"
            f"$a=New-ScheduledTaskAction -Execute '{exe}' -Argument '--check-balance';"
            "$t=New-ScheduledTaskTrigger -Once -At (Get-Date) "
            f"-RepetitionInterval (New-TimeSpan -Hours {hours}) "
            "-RepetitionDuration ([TimeSpan]::MaxValue);"
            f"Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t -Force "
            "| Out-Null; exit 0"
        )
    else:
        script = (
            "$ErrorActionPreference='Stop';"
            f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false | Out-Null; exit 0"
        )
    try:
        r = _ps(script)
        if r.returncode == 0:
            return True, "已开启" if enable else "已关闭"
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else f"退出码 {r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or "PowerShell 调不动"


def set_balance_task(enable: bool, hours: int = 1) -> tuple:
    """创建 / 删除余额定期检查的计划任务。返回 (ok, 说明)。

    两条路都试：schtasks.exe（绝大多数机器可用）→ PowerShell cmdlet（兜底）。
    两条都不通就把原因原样报给用户在气泡里，不静默失败。
    """
    hours = max(1, min(24, int(hours)))
    ok, msg = _task_schtasks(enable, hours)
    if ok:
        return True, msg
    ok2, msg2 = _task_powershell(enable, hours)
    if ok2:
        return True, msg2
    return False, msg2 or msg


