# -*- coding: utf-8 -*-
"""Smoke test: build the window, render one frame, run one tick, tear down."""
import argparse
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import minbird_pet as mp  # noqa: E402

print("import ok; frozen =", getattr(sys, "frozen", False))
print("assets dir:", mp.ASSET_DIR)
print("sprite:", mp.find_asset(mp.SPRITE_CANDIDATES))
print("icon:", mp.find_asset(mp.ICON_CANDIDATES))

try:
    options = argparse.Namespace(size=168, walk=True, debug=False)
    app = mp.MinBirdApp(options)
    print("Pet built: display", app.pet.display_w, "x", app.pet.display_h,
          "canvas", app.pet.canvas_w, "x", app.pet.canvas_h)
    app.create_window()
    print("window:", app.hwnd)
    app.create_tray()
    print("tray:", app.tray_ok, "hicon:", app.hicon)
    frame = app.pet.compose()
    app._present(frame)
    print("present ok", frame.size)
    import time
    app._last_render = time.perf_counter()
    app._tick()
    print("tick ok")
    app.pet.state = "walk"
    app.pet.facing = -1
    app._tick()
    print("walk tick ok")
    for _ in range(20):
        app._tick()
    print("20 ticks ok")
    app.pet.react()
    for _ in range(10):
        app._tick()
    print("react ticks ok, bubble =", app.pet.bubble_text)
    app._command(mp.ID_REACT)
    app._command(mp.ID_CYCLE_SIZE)
    app._command(mp.ID_WINDOWWALK)
    app._command(mp.ID_WINDOWWALK)
    print("menu commands ok, size =", app.pet.display_h,
          "window_walk =", app.config.get("window_walk"))
    mp.user32.DestroyWindow(app.hwnd)
    print("ALL OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
