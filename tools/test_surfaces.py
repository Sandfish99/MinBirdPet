# -*- coding: utf-8 -*-
"""窗口表面检测自检：枚举过滤 + 站窗沿 + 高空落点 + 窗沿消失掉落。

不依赖特定应用窗口：在当前桌面上找一条「真正露出来」的窗沿当靶子
（顶边够高、且脚点正前方没有被更前面的窗口挡住）。
最后一段会真的建一次宠物窗口跑几帧（和 smoke.py 一样，一闪而过）。

运行：python tools/test_surfaces.py
"""
import argparse
import ctypes
import os
import sys
import time
import traceback
from ctypes import wintypes as wt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import minbird_pet as mp  # noqa: E402


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def find_perch(live, min_top, wa):
    """找一条露出来的窗沿：返回 (x, top)，没有则 None。

    条件：顶边 >= min_top（站得下），且在 x 处 (x, top+2) 和 (x, top-98)
    都没有被 z 序更靠前的窗口挡住 —— 这样站沿 / 高空 / 落地三个断言才确定。
    """
    for i, w in enumerate(live):
        if w.top < min_top or w.right - w.left < 200:
            continue
        lo = max(w.left + 40, wa.left + 60)
        hi = min(w.right - 40, wa.right - 60)
        for x in range(lo, hi, 24):
            sky_y = w.top - 98
            edge_y = w.top + 2
            blocked = any(
                f.left <= x < f.right and f.top <= y < f.bottom
                for f in live[:i]
                for y in (edge_y, sky_y)
            )
            if not blocked:
                return float(x), float(w.top)
    return None


def main() -> int:
    surf = mp.WindowSurfaces()
    surf.refresh(time.perf_counter())
    live = surf._live()
    print(f"可站立窗口：{len(live)} 个")
    for r in live[:10]:
        print(f"  top={r.top:<6} x=[{r.left}, {r.right}] h={r.bottom - r.top}")

    wa = mp.work_area()
    taskbar = float(wa.bottom - 2)

    # 1) 自己进程的窗口（控制台）绝不能算地面
    k32 = ctypes.WinDLL("kernel32")
    k32.GetConsoleWindow.restype = wt.HWND
    con = k32.GetConsoleWindow()
    if con and surf._walkable(con):
        fail("自己进程的窗口被当成了地面")
    print("1) 排除自身进程 ok")

    perch = find_perch(live, 0.0, wa)   # 检测逻辑本身不限高度
    if perch:
        x, top = perch

        # 2) 站在窗沿上：ground_at 就是这条顶边
        g = surf.ground_at(x, top, taskbar)
        if abs(g - top) > 3:
            fail(f"站沿判定：期望 ~{top}，得到 {g}")
        print(f"2) 站沿判定 ok（top={top}，g={g}）")

        # 3) 从更高处落下来：要落在 top，不是任务栏
        sky = top - 98.0
        if surf.ground_at(x, sky, taskbar) != taskbar:
            fail("悬空判定：高空处不该有地面")
        land = surf.landing_at(x, sky, top + 5.0, taskbar)
        if land != top:
            fail(f"落地判定：期望 {top}，得到 {land}")
        print(f"3) 高空落点判定 ok（land={land}）")
    else:
        print("2)/3) （当前桌面上没有露出来的窗沿，跳过）")

    # 4) 开关关掉后一律任务栏
    surf.enabled = False
    if perch:
        if surf.ground_at(perch[0], perch[1], taskbar) != taskbar:
            fail("enabled=False 时仍返回了窗沿")
    surf.enabled = True
    print("4) 开关 ok")

    # 5) 整合：真的把鸟放到窗沿上跑几帧，再让窗沿消失看它掉回任务栏
    print("5) 整合测试：建窗口、站窗沿、窗沿消失掉落…")
    options = argparse.Namespace(size=118, walk=True, debug=False)
    app = mp.MinBirdApp(options)
    app.options.walk = False          # 测试期间别自己乱跑
    app.create_window()
    perch = find_perch(live, app.surfaces.min_top, wa)
    if perch:
        x, top = perch
        app.pet.fx = x
        app.pet.fy = top
        app.pet.state = "idle"
        for _ in range(6):
            app._tick()
        if abs(app.pet.fy - top) > 3 or app.pet.state != "idle":
            fail(f"站窗沿失败：state={app.pet.state} fy={app.pet.fy} 期望 {top}")
        print(f"   站在窗沿 ok（fy={app.pet.fy}）")

        app.config["window_walk"] = False   # 模拟窗沿消失（_tick 每帧从配置同步开关）
        landed = False
        for _ in range(3000):
            app._tick()
            if app.pet.state == "idle" and app.pet.fy >= taskbar - 2:
                landed = True
                break
        if not landed:
            fail(f"掉落失败：state={app.pet.state} fy={app.pet.fy}")
        print(f"   窗沿消失掉落 ok（fy={app.pet.fy}）")
    else:
        print("   （没有露出来且站得下的窗沿，跳过站沿/掉落）")
    mp.user32.DestroyWindow(app.hwnd)
    print("ALL OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
