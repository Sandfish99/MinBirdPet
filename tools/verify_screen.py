# -*- coding: utf-8 -*-
"""Launch the pet, verify its layered window, grab the screen, then stop it."""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

from PIL import Image, ImageGrab

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
SCRIPT = os.path.join(BASE, "minbird_pet.py")
SHOT = os.path.join(BASE, "_screen.png")
CROP = os.path.join(BASE, "_screen_crop.png")

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetLayeredWindowAttributes.argtypes = [wt.HWND, ctypes.c_void_p,
                                              ctypes.c_void_p, ctypes.c_void_p]
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

cmd = [PYW, SCRIPT, "--debug"]
if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".exe"):
    cmd = [sys.argv[1], "--debug"]
    print("verifying exe:", sys.argv[1])

# match the pet's DPI awareness so window rects line up with grabbed pixels
try:
    user32.SetProcessDPIAware()
except Exception:
    pass
if os.path.exists(os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                               "MinBirdPet", "config.json")):
    os.remove(os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                           "MinBirdPet", "config.json"))
    print("removed stale config")

proc = subprocess.Popen(cmd, cwd=BASE)
print("launched pid", proc.pid)
time.sleep(6)
print("alive:", proc.poll() is None)

hwnd = user32.FindWindowW("MinBirdPetWindow", None)
print("hwnd:", hwnd)
if hwnd:
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    print("rect:", rect.left, rect.top, rect.right, rect.bottom,
          "size:", rect.right - rect.left, rect.bottom - rect.top)
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    print("exstyle: 0x%08X" % (ex & 0xFFFFFFFF))
    print("  layered:", bool(ex & WS_EX_LAYERED),
          "toolwindow:", bool(ex & WS_EX_TOOLWINDOW),
          "topmost:", bool(ex & WS_EX_TOPMOST),
          "noactivate:", bool(ex & WS_EX_NOACTIVATE))
    print("visible:", bool(user32.IsWindowVisible(hwnd)))
    time.sleep(2)
    img = ImageGrab.grab(all_screens=True)
    img.save(SHOT)
    print("screen:", img.size, "->", SHOT)
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    pad = 190
    box = (max(0, cx - pad), max(0, cy - pad), min(img.width, cx + pad), min(img.height, cy + pad))
    img.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.LANCZOS).save(CROP)
    print("crop:", box, "->", CROP)
proc.terminate()
time.sleep(1)
if proc.poll() is None:
    proc.kill()
print("stopped")
