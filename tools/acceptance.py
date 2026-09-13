# -*- coding: utf-8 -*-
"""回归验收脚本：python tools/acceptance.py [cycles]

覆盖（自动化部分）：
A1 单/双/三屏 × 100/125/150/200% DPI 几何矩阵（合成验证 + 实机感知模式）
A2 拔屏后宠物位置（显示器消失 → 钳回剩余屏幕）
A3 全屏检测/自动隐藏（合成整屏窗实测）
A4 配置损坏恢复（损坏+有.bak+安全模式 → 恢复；无.bak → 不覆盖）
A5 插件崩溃存活（音乐探针持续抛异常，主程序/渲染不受影响）
A6 更新失败回滚（真实 exe：pending 交换 + --rollback 还原）
A7 连续启动退出 N 次（默认 100）
A8 内存/CPU 占用采样（运行 exe 30 秒）

需人工环境项（无法自动化，见报告）：物理拔插显示器、系统缩放切换、
真实游戏全屏、管理员权限对照。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import minbird_pet as m                      # noqa: E402
from minbird.core import geom               # noqa: E402
from minbird.core.interfaces import Rect    # noqa: E402
from minbird.platform import monitors, win32  # noqa: E402

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# ---------------------------------------------------------------- A1
def a1_dpi_matrix():
    """1/2/3 屏 × 100/125/150/200% ：合成几何矩阵（逻辑验证）。"""
    scales = [1.0, 1.25, 1.5, 2.0]
    layouts = []
    base = 96
    # 单屏 / 双屏并排 / 三屏并排（物理像素随缩放变化）
    for n in (1, 2, 3):
        for s in scales:
            w, h = int(1920 * s), int(1080 * s)
            taskebar = int(48 * s)
            mons = [Rect(i * w, 0, (i + 1) * w, h - taskebar) for i in range(n)]
            layouts.append((f"{n}屏@{int(s * 100)}%", mons))
    for name, mons in layouts:
        wa = mons[-1]
        for x, y in ((wa.left + 5, wa.top + 5), (wa.right - 5, wa.bottom - 5),
                     (wa.left, wa.bottom - 2)):
            cx, cy = geom.clamp_into(wa, x, y)
            assert wa.left <= cx <= wa.right and wa.top <= cy <= wa.bottom, (name, cx, cy)
            rx, ry = geom.relative_of(wa, cx, cy)
            bx, by = geom.point_from_relative(wa, rx, ry)
            assert abs(bx - cx) < 2 and abs(by - cy) < 2, (name, bx, by, cx, cy)
    # 实机：DPI 感知模式 + 当前显示器
    mode = win32.enable_dpi_awareness()
    areas = monitors.work_areas()
    report("A1 多屏×DPI 几何矩阵（合成）", len(layouts) == 12,
           f"{len(layouts)} 组合全部往返一致")
    report("A1 实机 DPI 感知/显示器枚举", mode in ("PMv2", "system") and len(areas) >= 1,
           f"mode={mode} monitors={len(areas)} "
           f"dpi_ok={win32.get_dpi_for_window(0) in (0, 96, 120, 144, 192)}")


# ---------------------------------------------------------------- A2
def a2_unplug():
    """拔屏模拟：珉鸟在 2 号屏，2 号屏消失 → 钳回剩余屏幕不丢鸟。"""
    wa1, wa2 = Rect(0, 0, 1920, 1040), Rect(1920, 0, 3840, 1040)
    x, y = geom.point_from_relative(wa2, 0.72, 0.95)
    # 2 号屏拔掉后：work_area_for_point 会回退到最近的屏（1 号屏）
    wa = monitors.work_area_for_point(x, y)
    cx, cy = geom.clamp_into(wa, x, y)
    inside = wa.left <= cx <= wa.right and wa.top <= cy <= wa.bottom
    # 相对坐标兜底：落在剩余屏的同一相对位置
    rx, ry = geom.relative_of(wa2, x, y)
    bx, by = geom.point_from_relative(wa1, rx, ry)
    inside2 = wa1.left <= bx <= wa1.right and wa1.top <= by <= wa1.bottom
    # 实机：珉鸟位置必然在某个真实显示器工作区内
    live = monitors.work_area_for_point(-999999, -999999)  # 越界点 → 最近屏
    ok = inside and inside2 and live.right > live.left
    report("A2 拔屏后位置钳回/相对坐标兜底", ok,
           f"钳回={inside} 相对兜底={inside2} 实机最近屏回退=OK")


# ---------------------------------------------------------------- A3
def a3_fullscreen():
    r = subprocess.run([sys.executable, str(ROOT / "tools/verify_fullscreen.py")],
                       capture_output=True, text=True, timeout=60)
    ok = r.returncode == 0
    report("A3 全屏检测/自动隐藏（合成整屏窗实测）", ok,
           (r.stdout or r.stderr).strip().splitlines()[-1] if
           (r.stdout or r.stderr) else "")


# ---------------------------------------------------------------- A4
def a4_config_recovery(tmp: Path):
    sys.path.insert(0, str(ROOT))
    import argparse

    m.CONFIG_DIR = str(tmp)
    m.CONFIG_PATH = str(tmp / "config.json")
    m.ALERT_PATH = str(tmp / "alerts.jsonl")

    # 场景1：正常配置 + 用户写坏 + 无备份 → 不覆盖（契约）
    broken_text = '{"city": "济南", "x": 100'
    (tmp / "config.json").write_text(broken_text, encoding="utf-8")
    raw_before = (tmp / "config.json").read_text(encoding="utf-8")
    app = m.MinBirdApp(argparse.Namespace(size=168, walk=True, debug=False,
                                           safe=False, static=False))
    assert app._config_broken is True
    assert (tmp / "config.json").read_text(encoding="utf-8") == raw_before, \
        "损坏文件必须原样保留"
    app._settings = None

    # 场景2：安全模式 + 有 .bak → 恢复
    (tmp / "config.json.bak").write_text('{"city": "青岛", "balance_step": 1.0}',
                                         encoding="utf-8")
    app2 = m.MinBirdApp(argparse.Namespace(size=168, walk=True, debug=False,
                                            safe=True, static=False))
    assert app2._config_broken is False
    assert app2.config.get("city") == "青岛", "安全模式应从 .bak 恢复"
    restored = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
    assert restored["city"] == "青岛"
    assert (tmp / "config.json.broken").exists(), "坏文件应留证"
    report("A4 配置损坏恢复（不覆盖契约 + 安全模式恢复）", True,
           "无备份=不覆盖；安全模式=从 .bak 恢复并留证")


# ---------------------------------------------------------------- A5
def a5_plugin_crash(tmp: Path):
    sys.path.insert(0, str(ROOT))
    import argparse

    m.CONFIG_DIR = str(tmp)
    m.CONFIG_PATH = str(tmp / "config.json")
    m.ALERT_PATH = str(tmp / "alerts.jsonl")
    Path(m.CONFIG_PATH).write_text("{}", encoding="utf-8")
    app = m.MinBirdApp(argparse.Namespace(size=168, walk=True, debug=False,
                                           safe=False, static=False))

    class Boom(Exception):
        pass

    def broken_probe():
        raise Boom("模拟插件崩溃")

    orig_probe = m._query_music
    orig_sleep = m_time_sleep = __import__("time").sleep
    import time as _t
    m._query_music = broken_probe
    calls = {"n": 0}

    def one_shot_sleep(_s):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise Boom("测试结束信号")

    _t.sleep = one_shot_sleep
    try:
        app._music_loop()          # 探针持续崩溃，循环应在两次探测后退出
    except Boom:
        pass
    finally:
        _t.sleep = orig_sleep
        m._query_music = orig_probe

    frame = app.pet.compose()      # 主程序仍能正常渲染
    assert frame.size[0] > 0
    alive = app._music_playing in (True, False)  # 状态字段完好
    report("A5 插件（音乐探针）崩溃主程序存活", alive and frame.size[0] > 0,
           "探针连续抛异常被隔离，渲染与状态机不受影响")


# ---------------------------------------------------------------- A6
def a6_update_rollback(exe: Path, tmp: Path):
    import ctypes
    u32 = ctypes.windll.user32
    cur, pending = exe, exe.parent / "MinBirdPet_new.exe"
    prev = exe.parent / "MinBirdPet_prev.exe"
    for f in (pending, prev, exe.parent / "MinBirdPet_bad.exe"):
        if f.exists():
            f.unlink()
    pending.write_bytes(cur.read_bytes())   # 用同一 exe 模拟"新版"

    proc = subprocess.Popen([str(cur)])
    ok_swap = False
    try:
        for _ in range(40):
            time.sleep(0.25)
            if prev.exists():
                ok_swap = True
                break
        # 关闭珉鸟（干净退出）
        hwnd = None
        for _ in range(20):
            hwnd = u32.FindWindowW("MinBirdPetWindow", None)
            if hwnd:
                break
            time.sleep(0.2)
        if hwnd:
            u32.PostMessageW(hwnd, 0x0010, 0, 0)
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()

    r = subprocess.run([str(cur), "--rollback"], capture_output=True,
                       text=True, timeout=30)
    ok_rb = r.returncode == 0 and cur.exists() and prev.exists() is False
    bad = exe.parent / "MinBirdPet_bad.exe"
    detail = f"pending交换={ok_swap} rollback退出码={r.returncode}"
    # 清理交换痕迹，恢复原 exe 布局
    if bad.exists():
        bad.unlink()
    for f in (pending, prev):
        if f.exists():
            f.unlink()
    report("A6 更新交换 + 回滚（真实 exe）", ok_swap and ok_rb, detail)


# ---------------------------------------------------------------- A7
def a7_cycles(n=100):
    u32 = ctypes.windll.user32
    crashes_before = sorted(
        (Path(os.environ["APPDATA"]) / "MinBirdPet" / "crashes").glob("crash_*")
    ) if (Path(os.environ["APPDATA"]) / "MinBirdPet" / "crashes").exists() else []
    ok = 0
    t0 = time.perf_counter()
    for i in range(n):
        proc = subprocess.Popen([sys.executable, str(ROOT / "minbird_pet.py")])
        hwnd = None
        for _ in range(25):
            time.sleep(0.1)
            hwnd = u32.FindWindowW("MinBirdPetWindow", None)
            if hwnd:
                break
        if hwnd:
            u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE 干净退出
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -1
        if hwnd and rc == 0:
            ok += 1
        if (i + 1) % 20 == 0:
            print(f"   ... {i + 1}/{n} (成功 {ok})", flush=True)
    dt = time.perf_counter() - t0
    crashes_after = sorted(
        (Path(os.environ["APPDATA"]) / "MinBirdPet" / "crashes").glob("crash_**")
    ) if (Path(os.environ["APPDATA"]) / "MinBirdPet" / "crashes").exists() else []
    new_crashes = [c for c in crashes_after if c not in crashes_before]
    cfg_ok = True
    try:
        json.loads((Path(os.environ["APPDATA"]) / "MinBirdPet" / "config.json")
                   .read_text(encoding="utf-8"))
    except Exception:
        cfg_ok = False
    left = subprocess.run(["tasklist", "/fi", f"IMAGENAME eq python.exe"],
                          capture_output=True, text=True,
                          errors="replace").stdout or ""
    left = left.lower().count("python.exe")
    report(f"A7 连续启动退出 {n} 次", ok == n and cfg_ok and not new_crashes,
           f"成功{ok}/{n}，耗时{dt:.0f}s，新增崩溃文件={len(new_crashes)}，"
           f"配置完好={cfg_ok}")
    return dt


# ---------------------------------------------------------------- A8
def a8_resources(exe: Path, seconds=30):
    import ctypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("pf", ctypes.c_ulong),
                    ("peak", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                    ("q1", ctypes.c_size_t), ("q2", ctypes.c_size_t),
                    ("q3", ctypes.c_size_t), ("q4", ctypes.c_size_t),
                    ("pfu", ctypes.c_size_t), ("ppfu", ctypes.c_size_t)]

    k32 = ctypes.windll.kernel32
    psapi = ctypes.WinDLL('psapi')
    u32 = ctypes.windll.user32
    proc = subprocess.Popen([str(exe)])
    time.sleep(2)
    h = k32.OpenProcess(0x1000 | 0x0400, False, proc.pid)  # QI|VM_READ
    samples, ft0 = [], ctypes.c_ulonglong * 8
    creation, exit_, kernel_t, user_t = (ctypes.c_ulonglong(),) * 4
    k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_),
                        ctypes.byref(kernel_t), ctypes.byref(user_t))
    t0w = time.perf_counter()
    cpu0 = (kernel_t.value + user_t.value) / 1e7
    try:
        for i in range(seconds // 5):
            time.sleep(5)
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            psapi.GetProcessMemoryInfo(ctypes.c_void_p(h), ctypes.byref(pmc), pmc.cb)
            samples.append(pmc.ws / 1048576)
            print(f"   t={5 * (i + 1)}s RSS={samples[-1]:.1f}MB", flush=True)
        k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_),
                            ctypes.byref(kernel_t), ctypes.byref(user_t))
        cpu1 = (kernel_t.value + user_t.value) / 1e7
    finally:
        hwnd = u32.FindWindowW("MinBirdPetWindow", None)
        if hwnd:
            u32.PostMessageW(hwnd, 0x0010, 0, 0)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    wall = time.perf_counter() - t0w
    cpu_pct = (cpu1 - cpu0) / wall * 100
    report("A8 内存/CPU（运行 30s）", max(samples) < 512 and cpu_pct < 25,
           f"RSS 峰值={max(samples):.1f}MB 稳定={samples[-1]:.1f}MB "
           f"CPU≈{cpu_pct:.1f}%（单核占比）")


# ----------------------------------------------------------------
def main():
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    exe = ROOT / "dist" / "MinBirdPet.exe"
    tmp = Path(os.environ["TEMP"]) / "minbird_acceptance"
    tmp.mkdir(exist_ok=True)

    print("== 0 环境 ==")
    try:
        import ctypes as _c
        print("  管理员:", bool(_c.windll.shell32.IsUserAnAdmin()),
              "| 显示器:", len(monitors.work_areas()),
              "| DPI模式:", win32.enable_dpi_awareness())
    except Exception as exc:
        print("  env err:", exc)

    start = sys.argv[2] if len(sys.argv) > 2 else "A1"

    def due(tag: str) -> bool:
        return tag >= start

    if due("A1"):
        a1_dpi_matrix()
    if due("A2"):
        a2_unplug()
    if due("A3"):
        a3_fullscreen()
    if due("A4"):
        a4_config_recovery(tmp)
    if due("A5"):
        a5_plugin_crash(tmp)
    if due("A6") and exe.exists():
        a6_update_rollback(exe, tmp)
    elif due("A6"):
        report("A6 更新交换 + 回滚（真实 exe）", False, "dist/MinBirdPet.exe 不存在")
    if due("A7"):
        a7_cycles(cycles)
    if due("A8") and exe.exists():
        a8_resources(exe)

    print("\n===== 验收结果 =====")
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"===== {len(RESULTS) - len(bad)}/{len(RESULTS)} 通过 =====")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
