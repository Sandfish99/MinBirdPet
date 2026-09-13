# -*- coding: utf-8 -*-
"""端到端演示：开一个临时文件的记事本窗口，让珉鸟落上它的标题栏，截图留证。

- 只碰按标题匹配的临时记事本窗口，绝不动用户自己的记事本/其他窗口；
- 挪动后校验位置生效才继续；
- finally 无条件恢复现场：关临时记事本、杀演示珉鸟、还原 config.json、
  再正常启动一次珉鸟。
运行：python tools/demo_window_perch.py
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes as wt

from PIL import ImageGrab

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import minbird_pet as mp  # noqa: E402

CONFIG = mp.CONFIG_PATH
EXE = os.path.join(BASE, "MinBirdPet.exe")
SHOT = os.path.join(BASE, "tools", "_demo_perch.png")
TAG = "minbird_perch_demo"
WM_CLOSE = 0x0010
DETACHED = 0x00000008 | 0x00000200

try:
    mp.user32.SetProcessDPIAware()
except Exception:
    pass

pet = None
cfg_raw = None
demo_hwnd = None
try:
    # 1) 备份配置
    with open(CONFIG, "r", encoding="utf-8") as fh:
        cfg_raw = fh.read()
    cfg = json.loads(cfg_raw)

    # 2) 先杀掉正在运行的珉鸟（演示要用自己的配置启动它）
    subprocess.run(["taskkill", "/F", "/IM", "MinBirdPet.exe"],
                   capture_output=True)
    time.sleep(1.0)

    # 3) 开临时记事本，挪到固定位置
    txt = os.path.join(tempfile.gettempdir(), TAG + ".txt")
    open(txt, "w", encoding="utf-8").close()
    subprocess.Popen(["notepad.exe", txt])
    demo_hwnd = None
    for _ in range(25):
        time.sleep(0.4)

        def cb(hwnd, _lp):
            global demo_hwnd
            if not mp.user32.IsWindowVisible(hwnd):
                return True
            t = ctypes.create_unicode_buffer(256)
            mp.user32.GetWindowTextW(hwnd, t, 256)
            if TAG in t.value:
                demo_hwnd = hwnd
            return True
        mp.user32.EnumWindows(mp.ENUMPROC(cb), 0)
        if demo_hwnd:
            break
    if not demo_hwnd:
        raise RuntimeError("没找到临时记事本窗口")
    time.sleep(1.5)   # 等它自己布局完，避免会话恢复把位置改回去

    r = mp.RECT()
    moved = False
    for _ in range(5):
        mp.user32.SetWindowPos(demo_hwnd, None, 2000, 320, 520, 500, 0x4)
        time.sleep(0.6)
        mp.user32.GetWindowRect(demo_hwnd, ctypes.byref(r))
        if abs(r.top - 320) < 10:
            moved = True
            break
    if not moved:
        raise RuntimeError(f"记事本挪不动: top={r.top}")
    time.sleep(0.8)

    # 4) 用真实检测逻辑算窗沿：在临时记事本顶边上找一个
    #    「z 序里没有被更前面的窗口挡住」的 x（脚点下方 2px 和上方 98px 都要露出来）
    surf = mp.WindowSurfaces()
    surf.refresh(time.perf_counter())
    if demo_hwnd not in surf._windows:
        raise RuntimeError("临时记事本不在可站立窗口列表里")
    idx = surf._windows.index(demo_hwnd)
    b = surf._bounds(demo_hwnd)
    top = float(b.top)

    def exposed(x, y):
        for f in surf._windows[:idx]:
            fb = surf._bounds(f)
            if fb and fb.left <= x < fb.right and fb.top <= y < fb.bottom:
                return False
        return True

    cx = None
    for x in range(b.left + 40, b.right - 40, 20):
        if exposed(x, top + 2) and exposed(x, top - 98):
            cx = float(x)
            break
    if cx is None:
        raise RuntimeError("临时记事本的标题栏被别的窗口挡住了")
    g = surf.ground_at(cx, top, 1e9)
    if abs(g - top) > 3:
        raise RuntimeError(f"ground_at 校验失败: {g} != {top}")
    print(f"窗沿就绪: x={cx} top={top}")

    # 5) 改配置：脚点放窗沿上方 150px，散步关掉
    cfg["x"] = cx
    cfg["y"] = top - 150
    cfg["walk"] = False
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)

    # 6) 启动新版 exe，等它落稳后截图
    pet = subprocess.Popen([EXE])
    time.sleep(5.0)
    hwnd_pet = mp.user32.FindWindowW("MinBirdPetWindow", None)
    mp.user32.GetWindowRect(hwnd_pet, ctypes.byref(r))
    print("pet rect:", r.left, r.top, r.right, r.bottom,
          f"(脚点应≈{top}: bottom-6={r.bottom - 6})")
    img = ImageGrab.grab()
    box = (max(0, int(cx) - 260), max(0, int(top) - 420),
           int(cx) + 260, min(img.height, int(top) + 90))
    crop = img.crop(box)
    crop = crop.resize((crop.width * 2, crop.height * 2))
    crop.save(SHOT)
    print("shot:", SHOT, crop.size)

    # 7) 5 秒后再确认一次，站得稳（没沉下去/飘走）
    time.sleep(5.0)
    mp.user32.GetWindowRect(hwnd_pet, ctypes.byref(r))
    print("pet rect +5s:", r.left, r.top, r.right, r.bottom)
    ok = abs((r.bottom - 6) - top) <= 3
    print("PERCH OK" if ok else "PERCH MISMATCH")
finally:
    # 8) 恢复现场
    subprocess.run(["taskkill", "/F", "/IM", "MinBirdPet.exe"],
                   capture_output=True)
    if demo_hwnd:
        mp.user32.PostMessageW(demo_hwnd, WM_CLOSE, 0, 0)
        time.sleep(1.0)
    if cfg_raw is not None:
        with open(CONFIG, "w", encoding="utf-8") as fh:
            fh.write(cfg_raw)
    subprocess.Popen([EXE], creationflags=DETACHED)
    print("现场已恢复，珉鸟已重新启动")
