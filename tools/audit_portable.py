# -*- coding: utf-8 -*-
r"""验证方法（步骤6）：便携性/权限审计。

断言：
1. 代码不含管理员/机器级痕迹：无 HKEY_LOCAL_MACHINE 写入、schtasks 无 /rl 提权、
   无硬编码用户目录（C:\\Users / 用户名 / Program Files）
2. 自启走 HKCU\...\Run（当前用户，无需管理员）
3. 所有数据落点在 %APPDATA%（Roaming，普通权限可写）
4. 实测：当前以非管理员身份运行时，配置/日志目录可写
任一违反即失败。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = []

# ---- 1) 静态扫描：禁止管理员/提权/硬编码路径痕迹 ----
# 注册表：只允许 HKCU 读/写自启键；HKLM 只允许 env.py 只读硬件键（VM 识别）
FORBIDDEN = ["/rl ", "C:\\Users", "C:/Users", "Sendi", "Program Files"]
# 注册表写入只允许伴随 HKCU（当前用户）；HKLM+写 = 需要管理员，禁止
_REG_WRITES = ["winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey",
               "SetValueEx"]
targets = [ROOT / "minbird_pet.py", ROOT / "minbird_info.py"]
targets += sorted((ROOT / "minbird").rglob("*.py"))
for f in targets:
    text = f.read_text(encoding="utf-8", errors="replace")
    for pat in FORBIDDEN:
        if pat in text:
            failures.append(f"{f.name}: 含禁止内容 {pat!r}")
    if any(w in text for w in _REG_WRITES) and "HKEY_LOCAL_MACHINE" in text:
        failures.append(f"{f.name}: 存在 HKLM 注册表写入")

# ---- 2) 自启必须走 HKCU ----
pet = (ROOT / "minbird_pet.py").read_text(encoding="utf-8", errors="replace")
auto = (ROOT / "minbird" / "platform" / "autostart.py").read_text(
    encoding="utf-8", errors="replace")
if "HKEY_CURRENT_USER" not in auto:
    failures.append("autostart.py 未使用 HKEY_CURRENT_USER")
for f in (pet, auto):
    if "HKEY_LOCAL_MACHINE" in f:
        failures.append("存在 HKLM 引用")
# env.py 允许只读 HKLM 硬件键，但禁止任何注册表写入
envsrc = (ROOT / "minbird" / "platform" / "env.py").read_text(
    encoding="utf-8", errors="replace")
for pat in ("winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey"):
    if pat in envsrc:
        failures.append(f"env.py 存在注册表写入: {pat}")

# ---- 3) 数据落点必须派生自 %APPDATA% ----
if 'os.environ.get("APPDATA"' not in pet:
    failures.append("数据目录未派生自 %APPDATA%")

# ---- 4) 实测：非管理员 + 目录可写 ----
try:
    import ctypes
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"当前管理员权限: {is_admin}（便携版不要求管理员）")
except Exception as exc:
    failures.append(f"权限探测失败: {exc!r}")

try:
    import minbird_pet as m
    probe = os.path.join(m.CONFIG_DIR, "_portable_probe.tmp")
    os.makedirs(m.CONFIG_DIR, exist_ok=True)
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("ok")
    os.remove(probe)
    print(f"数据目录可写: {m.CONFIG_DIR}")
except Exception as exc:
    failures.append(f"数据目录不可写: {exc!r}")

for f in failures:
    print("FAIL:", f)
print("AUDIT-PORTABLE:", "PASS" if not failures else "FAIL")
sys.exit(0 if not failures else 1)
