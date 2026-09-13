# -*- coding: utf-8 -*-
"""珉鸟桌宠 / MinBird Desktop Pet

A tiny always-on-top desktop pet built on raw Win32 layered windows.
No GUI toolkit required: pixels are composited with Pillow and pushed to a
per-pixel-alpha layered window through UpdateLayeredWindow.

Author: WorkBuddy
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from ctypes import wintypes as wt

from PIL import Image, ImageChops, ImageDraw, ImageFont


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
def _base_dir() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller onefile
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
ASSET_DIR = os.path.join(BASE_DIR, "assets")
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", BASE_DIR), "MinBirdPet")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# 外部检查进程（--check-balance）把要播报的提醒写这里，桌宠读取后清空。
# 纯本地文件中转，桌宠自己不发起任何周期性的网络请求。
ALERT_PATH = os.path.join(CONFIG_DIR, "alerts.jsonl")
APP_TITLE = "珉鸟桌宠"

# 保证同目录的 minbird_info 能被 import（vbs/快捷方式启动时 cwd 可能不是这里）
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import minbird_info  # noqa: E402  —— 余额 / 天气服务

SPRITE_CANDIDATES = ("minbird.png", "minbird_flip.png")
ICON_CANDIDATES = ("minbird.ico",)
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

SIZE_PRESETS = [("小", 118), ("中", 168), ("大", 232), ("特大", 300)]
BUBBLE_TEXTS = [
    "啾~", "珉鸟在此", "摸摸头", "咕咕咕", "今天也要加油鸭",
    "别摸鱼啦", "饿饿，饭饭", "珉鸟巡逻中", "在的在的", "有事叫我",
]
WALK_ENABLED_DEFAULT = True


# --------------------------------------------------------------------------
# Win32 constants
# --------------------------------------------------------------------------
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_CHILD = 0x40000000
GWL_STYLE = -16
GWL_EXSTYLE = -20
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0

WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_SETFONT = 0x0030
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_LBUTTONDBLCLK = 0x0203

HTTRANSPARENT = -1
HTCLIENT = 1
MA_NOACTIVATE = 3
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
GWLP_WNDPROC = -4

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008

SPI_GETWORKAREA = 0x0030
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

ID_REACT = 1001
ID_TOGGLE_WALK = 1002
ID_CYCLE_SIZE = 1003
ID_TOPMOST = 1004
ID_AUTOSTART = 1005
ID_HIDE = 1006
ID_QUIT = 1007
ID_INFO = 1008
ID_BALANCE = 1009
ID_WEATHER = 1010
ID_SETTINGS = 1011
ID_BALSTEP = 1012
ID_BALTASK = 1013
ID_WINDOWWALK = 1014
ID_SEQANIM = 1015
ID_DANCE = 1016

TIMER_ID = 1

# 余额提醒台阶（元）。0 = 关闭提醒。
BALANCE_STEPS = (1.0, 5.0, 10.0, 0.0)

# 配置文件里应当存在的字段与默认值。缺了就补，但绝不覆盖用户填过的值。
CONFIG_DEFAULTS = (
    ("deepseek_api_key", ""),
    ("city", ""),
    ("balance_step", 1.0),          # 每花满多少元提醒一次；0 = 关
    ("balance_baseline", None),     # 提醒基准，首次查到余额时自动建立
    ("balance_check_on_start", True),   # 珉鸟启动时静默查一次（不弹余额，只在跨台阶时开口）
    # 兜底方案：珉鸟自己每隔多少分钟查一次。0 = 不查（推荐用计划任务，进程查完就退）。
    ("balance_check_minutes", 0),
    # 能不能站/走在应用窗口的顶边（标题栏）上。False = 只待在任务栏。
    ("window_walk", True),
)


# --------------------------------------------------------------------------
# Win32 plumbing
# --------------------------------------------------------------------------
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint, WPARAM, LPARAM)
TIMERPROC = ctypes.WINFUNCTYPE(None, wt.HWND, ctypes.c_uint, ctypes.c_size_t, wt.DWORD)
ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.biSize = ctypes.sizeof(BITMAPINFOHEADER)


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", wt.DWORD), ("pt", POINT),
                ("lPrivate", wt.DWORD)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
        ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON),
        ("szTip", ctypes.c_wchar * 128), ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD), ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wt.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wt.DWORD), ("guidItem", GUID), ("hBalloonIcon", wt.HICON),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _bind_prototypes() -> None:
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wt.HWND
    user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
    user32.SetCapture.argtypes = [wt.HWND]
    user32.SetCapture.restype = wt.HWND
    user32.ReleaseCapture.argtypes = []
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.UpdateLayeredWindow.argtypes = [
        wt.HWND, wt.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE), wt.HDC,
        ctypes.POINTER(POINT), wt.DWORD, ctypes.POINTER(BLENDFUNCTION), wt.DWORD,
    ]
    user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                                  ctypes.c_int, wt.UINT]
    user32.LoadImageW.restype = wt.HANDLE
    user32.DestroyIcon.argtypes = [wt.HICON]
    user32.CreatePopupMenu.restype = wt.HMENU
    user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wt.HWND, ctypes.c_void_p]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.DestroyMenu.argtypes = [wt.HMENU]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetProcessDPIAware.argtypes = []
    user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wt.HANDLE
    user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wt.HICON
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.DeleteDC.argtypes = [wt.HDC]
    gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
    gdi32.CreateDIBSection.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]

    shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HINSTANCE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE


_bind_prototypes()

dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

if hasattr(user32, "GetWindowLongPtrW"):
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

    def _get_window_long(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongPtrW(hwnd, index))
else:
    def _get_window_long(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongW(hwnd, index))


def work_area() -> RECT:
    rect = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if rect.right <= rect.left:
        rect = RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return rect


def cursor_pos() -> tuple:
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def to_premul_bgra(img: Image.Image) -> bytes:
    """UpdateLayeredWindow wants premultiplied BGRA."""
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    alpha_rgb = Image.merge("RGB", (a, a, a))
    premul = ImageChops.multiply(Image.merge("RGB", (r, g, b)), alpha_rgb)
    pr, pg, pb = premul.split()
    return Image.merge("RGBA", (pr, pg, pb, a)).tobytes("raw", "BGRA")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _money(v) -> str:
    """1.0 -> '1'，1.5 -> '1.50'。整数金额别带一串零。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.2f}"


# --------------------------------------------------------------------------
# 余额提醒的中转站
#
# 珉鸟自己**不做任何周期性网络请求**。要自动提醒，就让 Windows 任务计划程序
# 定期跑一次 `MinBirdPet.exe --check-balance` —— 那个进程查一次 API、算完台阶
# 就退出。提醒写进 alerts.jsonl，桌宠在已有的本地文件轮询里顺手取走。
# --------------------------------------------------------------------------
ALERT_MAX_AGE = 12 * 3600.0   # 超过 12 小时的补播提醒就别念了，过时了


def _read_alerts():
    try:
        with open(ALERT_PATH, "r", encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        return []
    items = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("text"):
            items.append(obj)
    return items


def _append_alert(text: str) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(ALERT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "text": text},
                                ensure_ascii=False) + "\n")
    except OSError:
        pass


def _clear_alerts() -> None:
    try:
        os.remove(ALERT_PATH)
    except OSError:
        pass


def balance_step_text(step: float) -> str:
    return "关" if step <= 0 else f"每 ¥{_money(step)}"


def _out(msg: str) -> None:
    """无控制台（console=False 打包）时 print 会炸，所以顺手写进日志。"""
    try:
        if sys.stdout is not None:
            print(msg)
    except Exception:
        pass
    log_line("check-balance:", msg)


# Windows 计划任务名。用它来跑定期的余额检查 —— 系统唤醒进程、查完就走，
# 珉鸟自己不需要常驻一个轮询循环。
TASK_NAME = "MinBirdPet-BalanceCheck"


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          creationflags=_NO_WINDOW)


def _ps(script: str, timeout=30):
    # 统一让 PowerShell 输出 UTF-8（歌名/报错可能带中文），解码容错
    script = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    r = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
              "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
    r.stdout = (r.stdout or b"").decode("utf-8", "replace")
    r.stderr = (r.stderr or b"").decode("utf-8", "replace")
    return r


def _sq(s: str) -> str:
    """PowerShell 单引号字符串里把 ' 写成 ''。"""
    return str(s).replace("'", "''")


# 系统媒体会话（SMTC）：网易云 / QQ音乐 / Spotify 等主流播放器都接入了，
# 不用装任何依赖，问 Windows 就知道"现在谁在放什么歌"。
# 输出约定：SMTC_NONE = 会话正常但没在放；SMTC_META|歌手|歌名 = 在放；
# SMTC_PARTIAL = 这台机器的 WinRT 投影读不到状态/元数据 → 走窗口标题兜底。
MUSIC_SMTC_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$mgr = Await ($mgrType::RequestAsync()) $mgrType
$sessions = $mgr.GetSessions()
if ($sessions.Count -eq 0) { Write-Output "SMTC_NONE"; exit 0 }
# 探测状态枚举能不能读：读不出来就如实报 PARTIAL，别误报"没在放"
$status = [string]($sessions | Select-Object -First 1).PlaybackStatus
if ([string]::IsNullOrWhiteSpace($status)) { Write-Output "SMTC_PARTIAL"; exit 0 }
$s = $sessions | Where-Object { $_.PlaybackStatus -eq 'Playing' } | Select-Object -First 1
if (-not $s) { Write-Output "SMTC_NONE"; exit 0 }
$propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
$i = Await ($s.TryGetMediaPropertiesAsync()) $propsType
Write-Output ("SMTC_META|{0}|{1}" -f $i.Artist, $i.Title)
""".strip()

PLAYER_PROCESSES = ("qqmusic", "cloudmusic", "kugou", "kuwo", "kwmusic",
                    "spotify", "netease", "orpheus")

AESPA_KEYS = ("aespa", "에스파")


def _match_aespa(artist: str, title: str) -> bool:
    hay = f"{artist} {title}".lower()
    return any(k in hay for k in AESPA_KEYS)


TH32CS_SNAPPROCESS = 0x2


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _scan_player_windows() -> set:
    """兜底检测：枚举所有顶层窗口（含隐藏/托盘化），返回标题里出现 aespa
    （标题一般是"歌名 - 歌手"）的播放器进程 pid 集合。"""
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pids = {}
    if snap:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pids[entry.th32ProcessID] = entry.szExeFile
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        kernel32.CloseHandle(snap)
    hits = set()

    def _on_window(hwnd, _lparam):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = pids.get(pid.value, "").lower()
        if exe and any(p in exe for p in PLAYER_PROCESSES):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                left, sep, right = buf.value.strip().rpartition(" - ")
                if sep and left and _match_aespa(left, right):
                    hits.add(pid.value)
        return True

    cb = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(_on_window)
    user32.EnumWindows(cb, 0)
    return hits


# ---- Core Audio 会话峰值表：判断播放器进程此刻是否真的在出声（暂停检测） ----
_CLS_MMDEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAUDIO_SESSION_MANAGER2 = "{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"
_IID_IAUDIO_SESSION_CONTROL2 = "{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}"
_IID_IAUDIO_METER_INFORMATION = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"


def _guid_from_str(s: str) -> GUID:
    g = GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g)) != 0:
        raise OSError("CLSIDFromString failed")
    return g


def _com_method(obj, index: int, restype, *argtypes):
    """取 COM 对象 vtable 上第 index 个方法（obj 为接口指针 c_void_p）。
    注意先解引用槽位拿到真正的函数地址，不能把槽位地址当函数地址调用。"""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p)).contents.value
    fn_addr = ctypes.cast(vtbl + index * ctypes.sizeof(ctypes.c_void_p),
                          ctypes.POINTER(ctypes.c_void_p)).contents.value
    proto = ctypes.WINFUNCTYPE(restype, *argtypes)
    return ctypes.cast(fn_addr, proto)


def _com_release(obj) -> None:
    if obj:
        try:
            _com_method(obj, 2, ctypes.c_ulong, ctypes.c_void_p)(obj)
        except Exception:
            pass


def _process_peak(pids: set) -> float | None:
    """这些进程在默认输出设备上的瞬时峰值（0~1，取最大）；查不到返回 None。"""
    ole32 = ctypes.windll.ole32
    c_void_p, byref = ctypes.c_void_p, ctypes.byref
    p_enum, p_dev, p_mgr, p_enum_s = c_void_p(), c_void_p(), c_void_p(), c_void_p()
    peak = None
    try:
        hr = ole32.CoCreateInstance(byref(_guid_from_str(_CLS_MMDEVICE_ENUMERATOR)),
                                    None, 23,  # CLSCTX_ALL
                                    byref(_guid_from_str(_IID_IMMDEVICE_ENUMERATOR)),
                                    byref(p_enum))
        if hr != 0 or not p_enum:
            return None
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eMultimedia=1)
        hr = _com_method(p_enum, 4, ctypes.HRESULT, c_void_p, ctypes.c_int,
                         ctypes.c_int, ctypes.POINTER(c_void_p))(p_enum, 0, 1, byref(p_dev))
        _com_release(p_enum)
        if hr != 0 or not p_dev:
            return None
        # IMMDevice::Activate(IAudioSessionManager2)
        hr = _com_method(p_dev, 3, ctypes.HRESULT, c_void_p, GUID, ctypes.c_uint,
                         c_void_p, ctypes.POINTER(c_void_p))(
            p_dev, _guid_from_str(_IID_IAUDIO_SESSION_MANAGER2), 23, None, byref(p_mgr))
        _com_release(p_dev)
        if hr != 0 or not p_mgr:
            return None
        # IAudioSessionManager2::GetSessionEnumerator
        hr = _com_method(p_mgr, 5, ctypes.HRESULT, c_void_p,
                         ctypes.POINTER(c_void_p))(p_mgr, byref(p_enum_s))
        _com_release(p_mgr)
        if hr != 0 or not p_enum_s:
            return None
        count = ctypes.c_int()
        if _com_method(p_enum_s, 3, ctypes.HRESULT, c_void_p,
                       ctypes.POINTER(ctypes.c_int))(p_enum_s, byref(count)) != 0:
            return None
        iid_c2 = _guid_from_str(_IID_IAUDIO_SESSION_CONTROL2)
        iid_meter = _guid_from_str(_IID_IAUDIO_METER_INFORMATION)
        for i in range(count.value):
            p_ctrl, p_c2, p_meter = c_void_p(), c_void_p(), c_void_p()
            if _com_method(p_enum_s, 4, ctypes.HRESULT, c_void_p, ctypes.c_int,
                           ctypes.POINTER(c_void_p))(p_enum_s, i, byref(p_ctrl)) != 0:
                continue
            try:
                _com_method(p_ctrl, 0, ctypes.HRESULT, c_void_p,
                            ctypes.POINTER(GUID), ctypes.POINTER(c_void_p))(
                    p_ctrl, byref(iid_c2), byref(p_c2))
                # GetProcessId 的槽位在新版 Windows 上会移动（实测 12 或 14 都出现过），
                # 哪个槽位读出"进程表里真实存在的 pid"就用哪个
                session_pid = None
                if p_c2:
                    for slot in (14, 12):
                        v = ctypes.c_ulong()
                        try:
                            _com_method(p_c2, slot, ctypes.HRESULT, c_void_p,
                                        ctypes.POINTER(ctypes.c_ulong))(
                                p_c2, byref(v))
                        except OSError:
                            continue
                        if v.value in pids:
                            session_pid = v.value
                            break
                if session_pid is None:
                    continue
                _com_method(p_ctrl, 0, ctypes.HRESULT, c_void_p,
                            ctypes.POINTER(GUID), ctypes.POINTER(c_void_p))(
                    p_ctrl, byref(iid_meter), byref(p_meter))
                if p_meter:
                    val = ctypes.c_float()
                    if _com_method(p_meter, 3, ctypes.HRESULT, c_void_p,
                                   ctypes.POINTER(ctypes.c_float))(
                        p_meter, byref(val)) == 0:
                        peak = max(peak or 0.0, val.value)
            finally:
                _com_release(p_c2)
                _com_release(p_meter)
                _com_release(p_ctrl)
        return peak
    except Exception:
        return peak if peak is not None else None
    finally:
        _com_release(p_enum_s)


def _query_music() -> bool:
    """有没有在放 aespa：先问系统媒体会话；读不到就看播放器窗口（含隐藏的），
    标题对上后还要验证播放器此刻真的在出声（暂停/静音就不跳）。"""
    try:
        line = (_ps(MUSIC_SMTC_PS, timeout=15).stdout or "").strip()
    except Exception:
        line = ""
    if line.startswith("SMTC_META|"):
        parts = line.split("|", 2)
        return len(parts) == 3 and _match_aespa(parts[1], parts[2])
    if line == "SMTC_NONE":
        return False   # SMTC 可信：媒体会话正常但没在放
    hit_pids = _scan_player_windows()   # SMTC_PARTIAL / 查询失败
    if not hit_pids:
        return False
    peak = _process_peak(hit_pids)
    if peak is None:
        return True   # 音量峰值读不到就以标题为准
    return peak > 0.02


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


def check_balance_once(verbose: bool = False) -> int:
    """一次性的余额检查（--check-balance）。查完就退出，不留任何后台连接。

    返回 0 正常 / 1 查询失败 / 2 没配 Key 或提醒关着。
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key:
        if verbose:
            _out("还没有配置 deepseek_api_key")
        return 2
    try:
        step = float(cfg.get("balance_step", 1.0))
    except (TypeError, ValueError):
        step = 1.0
    if step <= 0:
        if verbose:
            _out("余额提醒已关闭（balance_step = 0）")
        return 2

    try:
        raw = minbird_info.fetch_balance_raw(key)
    except Exception as exc:  # noqa: BLE001
        if verbose:
            _out(f"查询失败：{exc}")
        return 1

    baseline = cfg.get("balance_baseline")
    alert, new_base = minbird_info.evaluate_spend(baseline, raw.get("total"), step)

    if new_base != baseline:
        cfg["balance_baseline"] = new_base
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    if alert:
        if alert["kind"] == "topup":
            text = (f"DeepSeek 充值 +¥{_money(alert['amount'])}\n"
                    f"现在 ¥{_money(alert['current'])}")
        else:
            text = (f"DeepSeek 又花掉 ¥{_money(alert['amount'])}\n"
                    f"余额 ¥{_money(alert['current'])}")
        _append_alert(text)
        _out(text.replace("\n", " / "))
    else:
        _out(f"余额 ¥{_money(raw.get('total'))}，还没跨过一个提醒台阶")
    return 0


LOG_PATH = os.path.join(CONFIG_DIR, "minbird_pet.log")


def log_line(*parts) -> None:
    """Append a diagnostic line. Safe to call from anywhere."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%H:%M:%S')}] " + " ".join(str(p) for p in parts) + "\n")
    except OSError:
        pass


def load_font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def find_asset(names) -> str | None:
    for name in names:
        path = os.path.join(ASSET_DIR, name)
        if os.path.exists(path):
            return path
    return None


SEQ_DIR = os.path.join(ASSET_DIR, "seq")


def load_sprite_seq() -> tuple | None:
    """序列帧模式素材：assets/seq/{sheet.png, manifest.json}（tools/make_seq.py 生成）。

    返回 (朝右帧列表, 朝左帧列表, fps)；文件缺失或损坏返回 None，回退静态图模式。
    """
    try:
        with open(os.path.join(SEQ_DIR, "manifest.json"), "r", encoding="utf-8") as f:
            m = json.load(f)
        sheet_path = os.path.join(SEQ_DIR, "sheet.png")
        sheet = Image.open(sheet_path).convert("RGBA")
        fw, fh, n = int(m["frame_w"]), int(m["frame_h"]), int(m["frames"])
        cols = int(m.get("cols", max(1, sheet.width // fw)))
        frames = []
        for i in range(n):
            r, c = divmod(i, cols)
            frames.append(sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)))
        left = [f.transpose(Image.FLIP_LEFT_RIGHT) for f in frames]
        return frames, left, float(m.get("fps", 24.0))
    except Exception:
        return None


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
PERCH_SNAP = 160.0   # 下落没进窗口时，离窗沿多高以内会「扑棱」上去落住


class WindowSurfaces:
    """枚举可作为地面的应用窗口，回答三个问题：

    - ground_at：站在 (fx, fy) 时脚下有没有窗沿（站立 / 沿窗沿走 / 跟着窗口拖动）
    - landing_at：这一帧从 prev_fy 掉到 fy，脚底扫过了哪条窗沿（落地）
    - perch_at：身体已经没进某扇窗口时，够不够得着它的窗沿扑棱上去
    """

    SKIP_CLASSES = {
        "Progman", "WorkerW",                       # 桌面
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd",  # 任务栏（由 work_area 兜底）
        "Shell_ChangeWindow", "NotifyIconOverflowWindow",
        "SysListView32", "SHELLDLL_DefView",
        "Tooltips_class32", "SysShadow", "BaseBar",
        "MSCTFIME UI", "Default IME",
        "Windows.UI.Core.CoreWindow",               # 开始菜单 / 提示等 shell 界面
        "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
    }
    MIN_W = 64    # 太窄的条状窗不给站
    MIN_H = 60
    ENUM_INTERVAL = 1.0   # 秒；重新枚举窗口列表的间隔，rect 每帧另取实时值

    def __init__(self) -> None:
        self.enabled = True
        self.min_top = 0.0    # 顶边比这更高的窗沿不站（鸟身子会探出屏幕外），由 App 按体型设置
        self._own_pid = os.getpid()
        self._own_hwnd = None
        self._windows = []          # hwnd 列表，z 序（前 → 后）
        self._next_enum = 0.0

    def set_own_hwnd(self, hwnd) -> None:
        self._own_hwnd = hwnd

    def refresh(self, now: float) -> None:
        """重建窗口列表（每秒一次，便宜）。"""
        if now < self._next_enum:
            return
        self._next_enum = now + self.ENUM_INTERVAL
        found = []

        def on_window(hwnd, _lparam):
            try:
                if self._walkable(hwnd):
                    found.append(hwnd)
            except Exception:
                pass
            return True

        user32.EnumWindows(ENUMPROC(on_window), 0)
        self._windows = found

    def _walkable(self, hwnd: int) -> bool:
        if not hwnd or hwnd == self._own_hwnd:
            return False
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return False
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == self._own_pid:
            return False          # 自己（鸟、气泡、托盘）不算地面
        cloak = wt.DWORD(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloak),
                                        ctypes.sizeof(cloak)) == 0 and cloak.value:
            return False          # UWP 挂起 / 被遮蔽的窗口
        exstyle = _get_window_long(hwnd, GWL_EXSTYLE)
        if exstyle & (WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT):
            return False          # 工具窗、点击穿透的悬浮层
        if _get_window_long(hwnd, GWL_STYLE) & WS_CHILD:
            return False
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, 256)
        if name.value in self.SKIP_CLASSES:
            return False
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return False
        rect = self._bounds(hwnd)
        if rect is None:
            return False
        return (rect.right - rect.left >= self.MIN_W
                and rect.bottom - rect.top >= self.MIN_H)

    @staticmethod
    def _bounds(hwnd: int) -> RECT | None:
        """可见边界。GetWindowRect 带一圈透明的 resize 边框，最大化窗口还会
        超出屏幕 8px，所以优先用 DWM 的扩展边界，鸟才能正好站在标题栏上。"""
        rect = RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                        ctypes.byref(rect),
                                        ctypes.sizeof(rect)) == 0 \
                and rect.right > rect.left and rect.bottom > rect.top:
            return rect
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect
        return None

    def _live(self) -> list:
        out = []
        for hwnd in self._windows:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                continue
            rect = self._bounds(hwnd)
            if rect is not None and rect.right > rect.left and rect.bottom > rect.top:
                out.append(rect)
        return out

    def ground_at(self, fx: float, fy: float, fallback: float) -> float:
        """站立/行走时的地面。脚点下方 2px 落在哪扇窗口里，就站它的顶边。"""
        if not self.enabled:
            return fallback
        px, py = int(fx), int(fy) + 2
        for rect in self._live():          # z 序：最前面的先看
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                standable = rect.top >= self.min_top
                if standable and rect.top >= fy - GROUND_TOL:
                    return float(rect.top)
                if standable and fy - rect.top <= RIDE_SNAP:
                    return float(rect.top)   # 窗口刚被拖高 —— 跟着上去
                break   # 顶边压在脚上方 / 太高站不下：贴着它前面掉下去
        return fallback

    def landing_at(self, fx: float, prev_fy: float, fy: float,
                   fallback: float) -> float:
        """下落时这一帧脚底扫过的最高窗沿（最先碰到的那条）。

        只看脚点正前方那扇最前面的窗口 —— 它的顶边被更高处的窗沿挡住时
        （顶边不在这一帧的扫过区间里），鸟就贴着它前面继续掉，不会站到
        被挡住的隐形窗沿上。
        """
        if not self.enabled:
            return fallback
        px, py = int(fx), int(fy) + 2
        for rect in self._live():
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                if prev_fy <= rect.top <= fy and rect.top >= self.min_top:
                    return float(rect.top)
                break
        return fallback

    def perch_at(self, fx: float, fy: float, max_rise: float) -> float | None:
        """脚点已经没入某扇窗口时，给一条够得着的窗沿让它扑棱上去。"""
        if not self.enabled:
            return None
        px, py = int(fx), int(fy) + 2
        for rect in self._live():
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                if fy - rect.top <= max_rise and rect.top >= self.min_top:
                    return float(rect.top)
                return None   # 窗沿太高够不着 —— 贴着窗口前面滑下去
        return None


# --------------------------------------------------------------------------
# pet
# --------------------------------------------------------------------------
class Pet:
    """Holds the pet state and composes the RGBA frame."""

    GRAVITY = 2800.0

    def __init__(self, sprite: Image.Image, options, seq: tuple | None = None):
        self.sprite_src = sprite
        self.options = options
        self.seq = seq              # (朝右帧, 朝左帧, fps)；None = 静态图模式
        self.seq_mode = seq is not None
        self.base_right = None
        self.base_left = None
        self.font = load_font(15)
        self.bubble_font = load_font(15)
        self.set_size(options.size)

        # --- kinematics (foot anchor in screen coords) ---
        wa = work_area()
        self.fx = float(wa.left + (wa.right - wa.left) * 0.72)
        self.fy = float(wa.bottom - 2)
        self.vx = 0.0
        self.vy = 0.0
        self.angle = 0.0
        self.angvel = 0.0
        self.squash = (1.0, 1.0)
        self.facing = 1
        self.state = "idle"
        self.t_state = 0.0
        self.bob = 0.0
        self.hop = 0.0
        self.lean = 0.0
        self.bubble_text = ""
        self.bubble_until = 0.0
        self.next_idle_action = time.perf_counter() + random.uniform(2.5, 6.0)
        self.walk_target = None
        self.walk_speed = 46.0
        self.sleepy = False
        self.dancing = False        # 听到 aespa 在放就摇摆
        self.alpha_mask = None      # bytes, for hit testing
        self.frame_size = (1, 1)
        self.surfaces = None        # WindowSurfaces，由 App 注入；None = 只认任务栏

    # -- geometry ---------------------------------------------------------
    def set_size(self, sh: int) -> None:
        self.display_h = int(sh)
        scale = self.display_h / self.sprite_src.height
        self.display_w = max(1, int(round(self.sprite_src.width * scale)))
        self.base_right = self.sprite_src.resize((self.display_w, self.display_h), Image.LANCZOS)
        self.base_left = self.base_right.transpose(Image.FLIP_LEFT_RIGHT)
        if self.seq is not None:
            dw, dh = self.display_w, self.display_h
            self.seq_right = [f.resize((dw, dh), Image.LANCZOS) for f in self.seq[0]]
            self.seq_left = [f.resize((dw, dh), Image.LANCZOS) for f in self.seq[1]]
        self.mx = 78
        self.m_top = 82
        self.m_bottom = 6
        self.canvas_w = self.display_w + 2 * self.mx
        self.canvas_h = self.m_top + self.display_h + self.m_bottom
        self.pad_x = int(self.display_w * 0.30) + 12
        self.pad_y = int(self.display_h * 0.30) + 12
        self.tile_w = self.display_w + 2 * self.pad_x
        self.tile_h = self.display_h + 2 * self.pad_y
        self.foot_in_tile = (self.pad_x + self.display_w / 2, self.pad_y + self.display_h)

    def set_seq_mode(self, on: bool) -> bool:
        """开/关序列帧待机动画。返回是否生效（没有素材时开不了）。"""
        if on:
            if self.seq is None:
                return False
            self.seq_mode = True
        else:
            self.seq_mode = False
        return True

    def place(self, fx: float, fy: float) -> None:
        self.fx, self.fy = fx, fy

    def window_pos(self) -> tuple:
        return (int(round(self.fx - self.canvas_w / 2)),
                int(round(self.fy - self.m_top - self.display_h)))

    # -- bubble layout ----------------------------------------------------
    def _layout_bubble(self):
        """把气泡文本排成多行，返回 (lines, line_h, box_w, box_h)；无气泡则 None。"""
        text = self.bubble_text
        if not text:
            return None
        if time.perf_counter() >= self.bubble_until:
            return None

        font = self.bubble_font
        max_text_w = max(110.0, float(self.display_w) + 46.0)

        def width_of(s: str) -> float:
            try:
                return font.getlength(s)
            except Exception:
                return len(s) * 8.0

        lines = []
        for raw in text.split("\n"):
            if not raw.strip():
                lines.append("")
                continue
            cur = ""
            for ch in raw:
                if width_of(cur + ch) > max_text_w and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)

        try:
            bb = font.getbbox("汉Mg")
            line_h = (bb[3] - bb[1]) + 7
        except Exception:
            line_h = 21

        box_w = int(max(width_of(l) for l in lines)) + 26
        box_h = line_h * len(lines) + 15
        return lines, line_h, box_w, box_h

    # -- composition ------------------------------------------------------
    def compose(self) -> Image.Image:
        sx, sy = self.squash
        w = max(1, int(round(self.display_w * sx)))
        h = max(1, int(round(self.display_h * sy)))
        if self.seq_mode:
            frames = self.seq_left if self.facing < 0 else self.seq_right
            base = frames[int(time.perf_counter() * self.seq[2]) % len(frames)]
        else:
            base = self.base_left if self.facing < 0 else self.base_right
        spr = base.resize((w, h), Image.BILINEAR)

        tile = Image.new("RGBA", (self.tile_w, self.tile_h), (0, 0, 0, 0))
        px = int(round(self.pad_x + self.display_w / 2 - w / 2))
        py = int(round(self.pad_y + self.display_h - h))
        tile.paste(spr, (px, py), spr)

        if abs(self.angle) > 0.15:
            tile = tile.rotate(self.angle, resample=Image.BICUBIC,
                               center=self.foot_in_tile, fillcolor=(0, 0, 0, 0))

        # 气泡可能比默认画布大 —— 画布按需要扩容。
        # UpdateLayeredWindow 每帧都重新设定窗口尺寸，所以画布可以逐帧改变；
        # 又因为鸟始终画在画布水平中心、垂直位置由 m_top 决定，
        # 画布变大变小都不会让鸟在屏幕上挪位置。
        layout = self._layout_bubble()
        if layout is None:
            top_space = self.m_top
            canvas_w = self.canvas_w
        else:
            _, _, bw, bh = layout
            top_space = max(self.m_top, bh + 14)
            canvas_w = max(self.canvas_w, bw + 10)
        canvas_h = top_space + self.display_h + self.m_bottom

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        # 把鸟放在画布水平中心：脚点 = ox + pad_x + display_w/2 = canvas_w/2
        ox = int(round(canvas_w / 2 - self.pad_x - self.display_w / 2))
        oy = int(round(top_space + self.hop - self.pad_y))
        canvas.alpha_composite(tile, (ox, oy))

        if layout is not None:
            self._draw_bubble(canvas, layout, top_space)
        elif self.bubble_text:
            self.bubble_text = ""

        return canvas

    def _draw_bubble(self, canvas: Image.Image, layout, top_space: int) -> None:
        lines, line_h, bw, bh = layout
        cw = canvas.width
        d = ImageDraw.Draw(canvas, "RGBA")

        bx = clamp(cw / 2 - bw / 2, 2, max(2, cw - bw - 2))
        by = top_space + self.hop - bh - 10
        if by < 2:
            by = 2

        fill = (255, 255, 255, 240)
        edge = (96, 104, 120, 255)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=11,
                            fill=fill, outline=edge, width=2)
        # 指向鸟嘴的小尖角
        tip_x = clamp(cw / 2, bx + 14, bx + bw - 14)
        d.polygon([(tip_x - 6, by + bh - 1), (tip_x + 6, by + bh - 1), (tip_x, by + bh + 9)],
                  fill=fill, outline=edge)
        d.line([(tip_x - 5, by + bh), (tip_x + 5, by + bh)], fill=fill, width=3)

        ty = by + 8
        for line in lines:
            d.text((bx + 13, ty), line, font=self.bubble_font, fill=(38, 40, 48, 255))
            ty += line_h

    # -- behaviour --------------------------------------------------------
    def say(self, text: str, seconds: float | None = None) -> None:
        self.bubble_text = text
        if seconds is None:
            # 余额/天气这类长文本自动给足阅读时间
            seconds = clamp(2.4 + len(text) * 0.16, 2.4, 14.0)
        self.bubble_until = time.perf_counter() + seconds

    def react(self) -> None:
        self.state = "react"
        self.t_state = 0.0
        self.vy = -330.0
        self.squash = (0.86, 1.16)
        self.say(random.choice(BUBBLE_TEXTS), random.uniform(1.2, 1.9))

    def start_walk(self) -> None:
        wa = work_area()
        margin = self.display_w / 2 + 10
        lo = wa.left + margin
        hi = wa.right - margin
        for _ in range(12):
            target = random.uniform(lo, hi)
            if abs(target - self.fx) > self.display_w * 0.8:
                break
        self.walk_target = target
        self.walk_speed = random.uniform(38.0, 62.0)
        self.state = "walk"
        self.t_state = 0.0

    # -- ground (窗沿或任务栏) --------------------------------------------
    def _ground_under(self, wa: RECT) -> float:
        """站着/走着时脚下的地面：脚下窗沿，没有就任务栏顶。"""
        surf = self.surfaces
        if surf is None:
            return wa.bottom - 2
        return surf.ground_at(self.fx, self.fy, wa.bottom - 2)

    def _landing_under(self, wa: RECT, prev_fy: float) -> float:
        """下落时这一帧脚底扫过的最高落点。"""
        surf = self.surfaces
        if surf is None:
            return wa.bottom - 2
        return surf.landing_at(self.fx, prev_fy, self.fy, wa.bottom - 2)

    def _perch_under(self, wa: RECT) -> float | None:
        """身体已经没进某扇窗口时，够不够得着它的窗沿扑棱上去。"""
        surf = self.surfaces
        if surf is None:
            return None
        return surf.perch_at(self.fx, self.fy, PERCH_SNAP)

    def start_dance(self) -> None:
        if not self.dancing:
            self.dancing = True
            self.next_idle_action = time.perf_counter() + 8.0
            self.react()

    def stop_dance(self) -> None:
        self.dancing = False
        self.angle = 0.0
        self.hop = 0.0
        self.bob = 0.0
        self.squash = (1.0, 1.0)

    def update(self, dt: float, now: float) -> None:
        self.t_state += dt
        wa = work_area()

        if self.state == "idle":
            g = self._ground_under(wa)
            if g > self.fy + 2.0:
                # 脚下的窗沿没了（窗口被拖走 / 关掉）—— 掉下去
                self.state = "fly"
                self.vx = 0.0
                self.vy = 0.0
                self.t_state = 0.0
                self.walk_target = None
            else:
                self.fy = g
                if self.dancing:
                    # 音乐联动：左右摇摆 + 上下蹦跳
                    self.bob = 0.0
                    self.hop = -abs(math.sin(now * 5.2)) * 7.0
                    self.angle = 9.0 * math.sin(now * 3.4)
                    beat = math.sin(now * 10.4)
                    self.squash = (1.0 + 0.05 * beat, 1.0 - 0.05 * beat)
                elif self.seq_mode:
                    # 呼吸/眨眼已烘进序列帧，只关掉程序化呼吸，避免双重呼吸
                    self.bob = 0.0
                    self.squash = (1.0, 1.0)
                    self.angle *= 0.85
                    self.hop = 0.0
                else:
                    self.bob = -abs(math.sin(now * 1.5)) * 2.4
                    breath = 1.0 + 0.009 * math.sin(now * 1.5)
                    self.squash = (breath, 2.0 - breath)
                    self.angle *= 0.85
                    self.hop = 0.0
                self.lean = 0.0
                if self.dancing:
                    return  # 跳舞的时候不开小差
                if self.options.walk and now >= self.next_idle_action:
                    self.next_idle_action = now + random.uniform(3.5, 9.0)
                    roll = random.random()
                    if roll < 0.62:
                        self.start_walk()
                    elif roll < 0.82:
                        self.facing *= -1
                        self.say("嗯？", 1.0)
                    else:
                        self.vy = -180.0
                        self.state = "hop"
                        self.t_state = 0.0

        elif self.state == "hop":
            prev_fy = self.fy
            self.vy += self.GRAVITY * dt
            self.fy += self.vy * dt
            if self.vy > 0:
                land = self._landing_under(wa, prev_fy)
                if self.fy >= land:
                    self.fy = land
                    self.state = "idle"
                    self.squash = (1.14, 0.86)
                    self.next_idle_action = now + random.uniform(2.0, 5.0)
            self.bob = 0.0

        elif self.state == "walk":
            if not self.options.walk:
                self.state = "idle"
                return
            target = self.walk_target or self.fx
            delta = target - self.fx
            step = math.copysign(min(abs(delta), self.walk_speed * dt), delta)
            self.fx += step
            g = self._ground_under(wa)
            if g > self.fy + 2.0:
                # 走出了窗沿 —— 掉下去
                self.state = "fly"
                self.vx = 0.0
                self.vy = 0.0
                self.t_state = 0.0
                self.walk_target = None
            else:
                self.fy = g
                self.facing = 1 if delta >= 0 else -1
                phase = now * 7.4
                self.hop = -abs(math.sin(phase)) * 9.0
                self.bob = 0.0
                self.lean = 0.0
                self.angle = -self.facing * 3.0 * math.sin(phase + 0.6)
                bob_s = 1.0 + 0.03 * math.cos(phase * 2)
                self.squash = (2.0 - bob_s, bob_s)
                if abs(delta) <= max(2.0, self.walk_speed * dt):
                    self.fx = target
                    self.state = "idle"
                    self.next_idle_action = now + random.uniform(2.5, 7.5)

        elif self.state == "react":
            prev_fy = self.fy
            self.vy += self.GRAVITY * dt
            self.fy += self.vy * dt
            if self.vy > 0:
                land = self._landing_under(wa, prev_fy)
                if self.fy >= land:
                    self.fy = land
                    self.vy = 0.0
                    if self.t_state > 0.35:
                        self.state = "idle"
                        self.squash = (1.12, 0.88)
                        self.next_idle_action = now + random.uniform(2.0, 5.0)
            stretch = 1.0 + clamp(self.vy, -400, 400) / 2600.0
            self.squash = (2.0 - stretch, stretch)

        elif self.state == "fly":
            prev_fy = self.fy
            self.vy += self.GRAVITY * dt
            self.fx += self.vx * dt
            self.fy += self.vy * dt
            self.angle = clamp(-self.vx * 0.05, -30, 30)
            if self.vy > 0:
                land = self._landing_under(wa, prev_fy)
                if self.fy < land:
                    perch = self._perch_under(wa)
                    if perch is not None and self.fy >= perch:
                        land = perch
                if self.fy >= land:
                    self.fy = land
                    if abs(self.vy) > 140:
                        self.vy = -self.vy * 0.42
                        self.vx *= 0.72
                        self.fy -= 1
                        self.squash = (1.2, 0.8)
                    else:
                        self.vy = 0.0
                        self.vx = 0.0
                        self.state = "idle"
                        self.squash = (1.1, 0.9)
                        self.next_idle_action = now + random.uniform(2.0, 5.0)
            if self.fy > wa.bottom - 2 + 400:
                self.fy = wa.bottom - 2
                self.state = "idle"

        elif self.state == "drag":
            pass

        # keep the pet inside the work area horizontally
        half = self.display_w / 2
        if self.state != "drag":
            if self.fx < wa.left + half:
                self.fx = wa.left + half
                self.vx = abs(self.vx) * 0.3
            elif self.fx > wa.right - half:
                self.fx = wa.right - half
                self.vx = -abs(self.vx) * 0.3

    # -- hit test ---------------------------------------------------------
    def hit(self, cx: int, cy: int) -> bool:
        mask = self.alpha_mask
        if mask is None:
            return True
        w, h = self.frame_size
        if not (0 <= cx < w and 0 <= cy < h):
            return False
        return mask[cy * w + cx] > 28


# --------------------------------------------------------------------------
# 设置窗口（原生 Win32 控件，零第三方依赖）
# --------------------------------------------------------------------------
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
WS_TABSTOP = 0x00010000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
ES_AUTOHSCROLL = 0x0080
BS_AUTOCHECKBOX = 0x0003
BS_DEFPUSHBUTTON = 0x0001
CBS_DROPDOWNLIST = 0x0003
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
CB_ADDSTRING = 0x0143
CB_SETCURSEL = 0x014E
CB_GETCURSEL = 0x0147


def _create_ui_font():
    """设置窗口用的雅黑字体句柄。"""
    if not hasattr(gdi32, "CreateFontW"):
        return None
    gdi32.CreateFontW.restype = wt.HFONT
    return gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                             "Microsoft YaHei UI")


class SettingsWindow:
    """珉鸟设置：Key / 城市 / 尺寸 / 各开关，保存后即时生效。"""

    CLIENT_W, CLIENT_H = 484, 384
    ID_SAVE, ID_CANCEL = 1, 2
    ID_KEY, ID_CITY, ID_SIZE, ID_STEP = 2001, 2002, 2003, 2004
    ID_WALK, ID_WWIN, ID_ANIM, ID_TOP = 2101, 2102, 2103, 2104
    ID_DANCE, ID_AUTOSTART, ID_BALTASK = 2105, 2106, 2107
    CLASS_NAME = "MinBirdSettingsWindow"

    def __init__(self, app):
        self.app = app
        self.hwnd = None
        self._font = _create_ui_font()
        self._controls = {}
        self._cb = WNDPROC(self._proc)
        if not getattr(user32, "_minbird_settings_bound", False):
            user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
            user32.SendMessageW.restype = LRESULT
            user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
            user32.AdjustWindowRectEx.argtypes = [
                ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
            user32._minbird_settings_bound = True
        self._build()

    # -- 布局 ----
    def _build(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._cb
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.lpszClassName = self.CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            if ctypes.get_last_error() != 1410:  # 1410 = 已注册
                raise OSError("RegisterClassExW(settings) failed")

        rect = wt.RECT(0, 0, self.CLIENT_W, self.CLIENT_H)
        style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
        user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, 0)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        wa = work_area()
        x = wa.left + max(0, (wa.right - wa.left - w) // 2)
        y = wa.top + max(0, (wa.bottom - wa.top - h) // 3)
        self.hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "珉鸟设置", style | WS_VISIBLE,
            x, y, w, h, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW(settings) failed")

        cfg = self.app.config
        step = self.app._balance_step()
        add = self._add

        # 城市（常用）放最上面，DeepSeek Key 是可选项放下面
        add("STATIC", "城市（天气用，留空自动定位）：", 0, 18, 16, 400, 20, 0)
        add("EDIT", cfg.get("city") or "",
            WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, 18, 40, 448, 24, self.ID_CITY)

        add("STATIC", "尺寸：", 0, 18, 84, 60, 20, 0)
        combo_size = add("COMBOBOX", "", CBS_DROPDOWNLIST | WS_TABSTOP,
                         84, 82, 120, 160, self.ID_SIZE)
        add("STATIC", "余额提醒台阶：", 0, 228, 84, 110, 20, 0)
        combo_step = add("COMBOBOX", "", CBS_DROPDOWNLIST | WS_TABSTOP,
                         342, 82, 124, 160, self.ID_STEP)

        # 下拉项的字符串缓冲区必须保活到发送完成，且要传字符串数据本身的
        # 地址（不是指针变量的地址），否则下拉框显示乱码
        self._keepalive = []
        for label, px in SIZE_PRESETS:
            p = ctypes.c_wchar_p(label)
            self._keepalive.append(p)
            user32.SendMessageW(combo_size, CB_ADDSTRING, 0,
                                LPARAM(ctypes.cast(p, ctypes.c_void_p).value))
            if px == self.app.pet.display_h:
                user32.SendMessageW(combo_size, CB_SETCURSEL,
                                    [p2 for _, p2 in SIZE_PRESETS].index(px), 0)
        for label, val in (("关", 0.0), ("每花 ¥1", 1.0),
                           ("每花 ¥5", 5.0), ("每花 ¥10", 10.0)):
            p = ctypes.c_wchar_p(label)
            self._keepalive.append(p)
            user32.SendMessageW(combo_step, CB_ADDSTRING, 0,
                                LPARAM(ctypes.cast(p, ctypes.c_void_p).value))
            if val == step:
                user32.SendMessageW(combo_step, CB_SETCURSEL,
                                    (0.0, 1.0, 5.0, 10.0).index(val), 0)

        add("BUTTON", "自己散步", BS_AUTOCHECKBOX | WS_TABSTOP, 18, 126, 220, 24,
            self.ID_WALK)
        add("BUTTON", "能在窗口上走", BS_AUTOCHECKBOX | WS_TABSTOP, 246, 126, 220, 24,
            self.ID_WWIN)
        add("BUTTON", "待机动画（呼吸/眨眼/歪头）", BS_AUTOCHECKBOX | WS_TABSTOP,
            18, 158, 220, 24, self.ID_ANIM)
        add("BUTTON", "总在最前", BS_AUTOCHECKBOX | WS_TABSTOP, 246, 158, 220, 24,
            self.ID_TOP)
        add("BUTTON", "听到 aespa 就跳舞", BS_AUTOCHECKBOX | WS_TABSTOP,
            18, 190, 220, 24, self.ID_DANCE)
        add("BUTTON", "开机自启", BS_AUTOCHECKBOX | WS_TABSTOP, 246, 190, 220, 24,
            self.ID_AUTOSTART)
        add("BUTTON", "每小时自动查余额（跨台阶才开口）", BS_AUTOCHECKBOX | WS_TABSTOP,
            18, 222, 400, 24, self.ID_BALTASK)

        add("STATIC", "DeepSeek API Key（可选：余额提醒用，不填不影响桌宠）：",
            0, 18, 262, 448, 20, 0)
        add("EDIT", cfg.get("deepseek_api_key") or "",
            WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, 18, 286, 448, 24, self.ID_KEY)

        add("BUTTON", "保存", BS_DEFPUSHBUTTON | WS_TABSTOP, 310, 336, 76, 30,
            self.ID_SAVE)
        add("BUTTON", "取消", WS_TABSTOP, 394, 336, 76, 30, self.ID_CANCEL)

        checks = {
            self.ID_WALK: bool(self.app.options.walk),
            self.ID_WWIN: bool(cfg.get("window_walk", True)),
            self.ID_ANIM: self.app.pet.seq_mode,
            self.ID_TOP: self.app.topmost,
            self.ID_DANCE: self.app._dance_enabled,
            self.ID_AUTOSTART: autostart_enabled(),
            self.ID_BALTASK: balance_task_enabled(),
        }
        for cid, on in checks.items():
            user32.SendMessageW(self._controls[cid], BM_SETCHECK, 1 if on else 0, 0)

    def _add(self, cls, text, style, x, y, w, h, cid):
        hwnd = user32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, w, h, self.hwnd, cid, kernel32.GetModuleHandleW(None), None)
        if self._font:
            user32.SendMessageW(hwnd, WM_SETFONT, self._font, 1)
        if cid:
            self._controls[cid] = hwnd
        return hwnd

    # -- 读取控件 ----
    def _text(self, cid: int) -> str:
        h = self._controls[cid]
        n = user32.GetWindowTextLengthW(h) + 1
        buf = ctypes.create_unicode_buffer(n)
        user32.GetWindowTextW(h, buf, n)
        return buf.value.strip()

    def _check(self, cid: int) -> bool:
        return user32.SendMessageW(self._controls[cid], BM_GETCHECK, 0, 0) == 1

    def _combo(self, cid: int) -> int:
        return user32.SendMessageW(self._controls[cid], CB_GETCURSEL, 0, 0)

    def _save(self) -> None:
        i_size, i_step = self._combo(self.ID_SIZE), self._combo(self.ID_STEP)
        self.app.apply_settings({
            "key": self._text(self.ID_KEY),
            "city": self._text(self.ID_CITY),
            "size": SIZE_PRESETS[i_size][1] if 0 <= i_size < len(SIZE_PRESETS)
                    else self.app.pet.display_h,
            "step": BALANCE_STEPS[i_step] if 0 <= i_step < len(BALANCE_STEPS)
                    else self.app._balance_step(),
            "walk": self._check(self.ID_WALK),
            "wwin": self._check(self.ID_WWIN),
            "anim": self._check(self.ID_ANIM),
            "top": self._check(self.ID_TOP),
            "dance": self._check(self.ID_DANCE),
            "autostart": self._check(self.ID_AUTOSTART),
            "baltask": self._check(self.ID_BALTASK),
        })
        user32.EnableWindow(self.hwnd, False)  # 保存期间防手滑再点
        try:
            self.app.apply_settings(v)
        finally:
            user32.DestroyWindow(self.hwnd)

    # -- 消息处理 ----
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            cid = wparam & 0xFFFF
            if cid == self.ID_SAVE:
                self._save()
                return 0
            if cid == self.ID_CANCEL:
                user32.DestroyWindow(hwnd)
                return 0
        elif msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            self.app._settings_closed(self)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
class MinBirdApp:
    TIMER_MS = 33

    def __init__(self, options):
        self.options = options
        self.hwnd = None
        self.tray_ok = False
        self.hicon = None
        self.visible = True
        self.topmost = True
        self._config_broken = False   # 配置文件 JSON 坏了就别写盘，保住用户内容
        self._config_mtime = None
        self._last_cfg_check = 0.0
        self.config = self._load_config()
        self._ensure_config_file()
        try:
            self._config_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

        # 余额 / 天气：后台线程查，结果丢进 outbox，主线程在 _tick 里取
        self.outbox = queue.Queue()
        self.info = minbird_info.InfoService(self.outbox)

        # 设置窗口 / 音乐联动 / 开机问候
        self._settings = None
        self._dance_enabled = bool(self.config.get("dance_on_aespa", True))
        self._music_playing = False
        self._greet_at = None
        threading.Thread(target=self._music_loop, daemon=True).start()

        sprite_path = find_asset(SPRITE_CANDIDATES)
        if not sprite_path:
            raise SystemExit(f"找不到宠物图片，请确认 {ASSET_DIR} 下有 minbird.png")
        sprite = Image.open(sprite_path).convert("RGBA")
        sprite = sprite.crop(sprite.getchannel("A").getbbox() or (0, 0, *sprite.size))

        # 序列帧素材（assets/seq/ 由 tools/make_seq.py 生成）。素材恒加载，
        # 用不用由菜单「待机动画」开关（seq_anim）决定；--static 只影响首次默认值。
        seq = load_sprite_seq()
        if seq is not None:
            sprite = seq[0][0]  # 用第 0 帧定宽高比，动画/静态切换不跳尺寸

        options.size = self.config.get("size", options.size)
        options.walk = self.config.get("walk", options.walk)
        self.pet = Pet(sprite, options, seq=seq)
        if seq is not None:
            # --static = 本次启动强制静态（排障用）；平时由配置 seq_anim 决定
            self.pet.seq_mode = (not getattr(options, "static", False)) and \
                bool(self.config.get("seq_anim", True))
        self.pet.set_size(options.size)
        self.surfaces = WindowSurfaces()
        self.pet.surfaces = self.surfaces
        self.surfaces.min_top = self.pet.display_h + 8

        if self.config.get("x") is not None:
            self.pet.place(self.config["x"], self.config["y"])

        self._drag = None
        self._last_render = 0.0
        self._start_check_at = None   # 启动后延迟静默查一次余额的时刻
        self._task_enabled = None     # 计划任务状态缓存（None = 还没查过）
        self._next_auto_check = None  # balance_check_minutes 的下一次检查时刻

        self._log = self._open_log() if getattr(options, "debug", False) else None
        self._wndproc_ref = None

    # -- config -----------------------------------------------------------
    # 配置文件是「磁盘唯一真相源」：用户可以随时用记事本改，程序只负责
    # 写自己拥有的运行时字段（size/walk/x/y）。绝不能用启动时的内存快照
    # 整体覆盖，否则用户刚填的 API Key 会被旧快照抹掉。
    USER_FIELDS = ("deepseek_api_key", "city")

    def _read_disk_config(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            # 用户编辑到一半 / JSON 写坏了 —— 这时候千万不能覆盖文件，
            # 否则他填的 Key 就没了。记个标记，整个会话都别写盘。
            self._config_broken = True
            return {}
        return data if isinstance(data, dict) else {}

    def _write_config(self, data: dict) -> None:
        if getattr(self, "_config_broken", False):
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            return
        try:
            self._config_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

    def _load_config(self) -> dict:
        return self._read_disk_config()

    def _ensure_config_file(self) -> None:
        """保证配置文件存在且带默认字段，方便直接填 API Key。"""
        data = self._read_disk_config()
        changed = False
        for key, default in CONFIG_DEFAULTS:
            if key not in data:
                data[key] = default
                changed = True
        if changed or not os.path.exists(CONFIG_PATH):
            self._write_config(data)
        for key, default in CONFIG_DEFAULTS:
            self.config.setdefault(key, data.get(key, default))

    def _save_config(self) -> None:
        """只写运行时字段，用户手填的 Key / 城市原样保留。"""
        data = self._read_disk_config()
        data["size"] = self.pet.display_h
        data["walk"] = self.options.walk
        data["x"] = self.pet.fx
        data["y"] = self.pet.fy
        self._write_config(data)
        self.config = data

    def _set_config_value(self, key: str, value) -> None:
        """回写单个字段（比如 IP 定位出来的城市），其他字段不动。"""
        data = self._read_disk_config()
        data[key] = value
        self._write_config(data)
        self.config = data

    def _watch_config(self) -> None:
        """配置文件被外部改动时自动重读，这样改完不用重启珉鸟。"""
        try:
            mt = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return
        if self._config_mtime is None:
            self._config_mtime = mt
            return
        if abs(mt - self._config_mtime) < 1e-6:
            return
        self._config_mtime = mt
        new = self._read_disk_config()
        if getattr(self, "_config_broken", False):
            self.pet.say("配置文件读不懂啦\n检查一下 JSON 格式？", 7.0)
            return
        if new != self.config:
            self.config = new
            self.pet.say("配置更新啦，已经重新读取", 5.0)

    def _open_log(self):
        try:
            open(LOG_PATH, "w", encoding="utf-8").close()
        except OSError:
            return None

        def log(*parts):
            log_line(*parts)

        return log

    # -- window -----------------------------------------------------------
    def create_window(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "MinBirdPetWindow"

        self._wndproc_ref = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.lpszClassName = class_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err not in (1410,):  # class already exists
                raise OSError(f"RegisterClassExW failed: {err}")

        ex_style = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if self.topmost:
            ex_style |= WS_EX_TOPMOST

        x, y = self.pet.window_pos()
        self.hwnd = user32.CreateWindowExW(
            ex_style, class_name, APP_TITLE, WS_POPUP,
            x, y, self.pet.canvas_w, self.pet.canvas_h,
            None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        self.surfaces.set_own_hwnd(self.hwnd)

        if self._log:
            self._log("window created", self.hwnd)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            return self._handle(hwnd, msg, wparam, lparam)
        except Exception as exc:  # never let an exception escape into the loop
            if self._log:
                self._log("wndproc error", msg, repr(exc))
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            sx = ctypes.c_short(lparam & 0xFFFF).value
            sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            wx, wy = self.pet.window_pos()
            if self.pet.hit(sx - wx, sy - wy):
                return HTCLIENT
            return HTTRANSPARENT

        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE

        if msg == WM_LBUTTONDOWN:
            self._on_lbutton_down(lparam)
            return 0

        if msg == WM_MOUSEMOVE:
            if self._drag is not None:
                self._on_mouse_move()
            return 0

        if msg in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            self._on_lbutton_up()
            return 0

        if msg == WM_RBUTTONUP:
            self._show_menu()
            return 0

        if msg == WM_TRAYICON:
            if lparam in (WM_RBUTTONUP, 0x0205):
                self._show_menu()
            elif lparam in (WM_LBUTTONUP, 0x0202, WM_LBUTTONDBLCLK):
                self._toggle_visible()
            return 0

        if msg == WM_TIMER and wparam == TIMER_ID:
            self._tick()
            return 0

        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- interaction ------------------------------------------------------
    def _on_lbutton_down(self, lparam) -> None:
        cx, cy = cursor_pos()
        wx, wy = self.pet.window_pos()
        self._drag = {
            "offset": (cx - wx, cy - wy),
            "start": (cx, cy),
            "moved": 0.0,
            "t0": time.perf_counter(),
            "last": (cx, cy),
            "last_t": time.perf_counter(),
            "vx": 0.0,
            "vy": 0.0,
        }
        self.pet.state = "drag"
        self.pet.squash = (0.96, 1.06)
        user32.SetCapture(self.hwnd)
        if self._log:
            self._log("drag start", cx, cy)

    def _on_mouse_move(self) -> None:
        d = self._drag
        cx, cy = cursor_pos()
        target_fx = cx - d["offset"][0] + self.pet.canvas_w / 2
        target_fy = cy - d["offset"][1] + self.pet.m_top + self.pet.display_h
        now = time.perf_counter()
        dt = max(1e-3, now - d["last_t"])

        prev_x, prev_y = self.pet.fx, self.pet.fy
        # springy lag so the body swings behind the cursor
        self.pet.fx += (target_fx - self.pet.fx) * 0.42
        self.pet.fy += (target_fy - self.pet.fy) * 0.42

        inst_vx = (self.pet.fx - prev_x) / dt
        inst_vy = (self.pet.fy - prev_y) / dt
        d["vx"] = d["vx"] * 0.7 + inst_vx * 0.3
        d["vy"] = d["vy"] * 0.7 + inst_vy * 0.3

        lag_x = target_fx - self.pet.fx
        lag_y = target_fy - self.pet.fy
        self.pet.angle = clamp(lag_x * 0.55, -26, 26)
        stretch = clamp(1.0 + lag_y * 0.004, 0.95, 1.12)
        self.pet.squash = (2.0 - stretch, stretch)
        self.pet.hop = 0.0
        if abs(target_fx - prev_x) > 0.4:
            self.pet.facing = 1 if target_fx > prev_x else -1

        d["moved"] += math.hypot(cx - d["last"][0], cy - d["last"][1])
        d["last"] = (cx, cy)
        d["last_t"] = now

    def _on_lbutton_up(self) -> None:
        if self._drag is None:
            return
        d = self._drag
        self._drag = None
        user32.ReleaseCapture()
        elapsed = time.perf_counter() - d["t0"]
        if d["moved"] < 6 and elapsed < 0.45:
            self.pet.react()
            if self._log:
                self._log("click -> react")
        else:
            self.pet.state = "fly"
            self.pet.vx = clamp(d["vx"], -1800, 1800)
            self.pet.vy = clamp(d["vy"], -1800, 1800)
            self.pet.t_state = 0.0
            self._save_config()
            if self._log:
                self._log("fling", round(self.pet.vx), round(self.pet.vy))

    # -- menu / tray ------------------------------------------------------
    def _build_menu(self) -> int:
        menu = user32.CreatePopupMenu()
        walk = MF_CHECKED if self.options.walk else 0
        top = MF_CHECKED if self.topmost else 0
        auto = MF_CHECKED if autostart_enabled() else 0
        wwin = MF_CHECKED if self.config.get("window_walk", True) else 0
        anim = MF_CHECKED if self.pet.seq_mode else 0
        dance = MF_CHECKED if self._dance_enabled else 0
        user32.AppendMenuW(menu, MF_STRING, ID_REACT, "摸摸头")
        user32.AppendMenuW(menu, MF_STRING | walk, ID_TOGGLE_WALK, "自己散步")
        user32.AppendMenuW(menu, MF_STRING | wwin, ID_WINDOWWALK, "能在窗口上走")
        user32.AppendMenuW(menu, MF_STRING | anim, ID_SEQANIM, "待机动画")
        user32.AppendMenuW(menu, MF_STRING | dance, ID_DANCE, "听到 aespa 就跳舞")
        user32.AppendMenuW(menu, MF_STRING, ID_CYCLE_SIZE,
                           f"尺寸：{self._size_label()}（点击切换）")
        user32.AppendMenuW(menu, MF_STRING | top, ID_TOPMOST, "总在最前")
        user32.AppendMenuW(menu, MF_STRING | auto, ID_AUTOSTART, "开机自启")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_BALANCE, "看看 DeepSeek 余额")
        user32.AppendMenuW(menu, MF_STRING, ID_BALSTEP,
                           f"余额提醒：{balance_step_text(self._balance_step())}（点击切换）")
        # schtasks 查询要几百毫秒，缓存起来，别每次开菜单都卡一下
        if self._task_enabled is None:
            self._task_enabled = balance_task_enabled()
        user32.AppendMenuW(menu, MF_STRING, ID_BALTASK,
                           "自动查余额："
                           f"{'每 1 小时' if self._task_enabled else '未开启'}（点击切换）")
        user32.AppendMenuW(menu, MF_STRING, ID_WEATHER, "今天天气怎么样")
        user32.AppendMenuW(menu, MF_STRING, ID_SETTINGS, "设置（填 Key / 改城市）")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_HIDE, "藏起来")
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "让珉鸟下班（退出）")
        return menu

    def _size_label(self) -> str:
        for label, px in SIZE_PRESETS:
            if px == self.pet.display_h:
                return label
        return f"{self.pet.display_h}px"

    def _show_menu(self) -> None:
        menu = self._build_menu()
        x, y = cursor_pos()
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, x, y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        if cmd:
            self._command(cmd)

    def _command(self, cmd: int) -> None:
        if cmd == ID_REACT:
            self.pet.react()
        elif cmd == ID_TOGGLE_WALK:
            self.options.walk = not self.options.walk
            if not self.options.walk and self.pet.state == "walk":
                self.pet.state = "idle"
            self._save_config()
        elif cmd == ID_WINDOWWALK:
            new = not bool(self.config.get("window_walk", True))
            self._set_config_value("window_walk", new)
            if new:
                self.pet.say("好耶，窗台也能走啦", 3.5)
            else:
                self.pet.say("那我只待在任务栏上", 3.5)
        elif cmd == ID_SEQANIM:
            new = not self.pet.seq_mode
            if self.pet.set_seq_mode(new):
                self._set_config_value("seq_anim", new)
                self.pet.say("好耶，动起来" if new else "那我安安静静待着", 2.5)
            else:
                self.pet.say("找不到动画素材啦", 2.5)
        elif cmd == ID_DANCE:
            self._dance_enabled = not self._dance_enabled
            self._set_config_value("dance_on_aespa", self._dance_enabled)
            if self._dance_enabled:
                self.pet.say("好！放 aespa 我就蹦", 2.5)
            else:
                self.pet.stop_dance()
                self.pet.say("那我就安静听歌", 2.5)
        elif cmd == ID_CYCLE_SIZE:
            sizes = [px for _, px in SIZE_PRESETS]
            idx = (sizes.index(self.pet.display_h) + 1) % len(sizes) if self.pet.display_h in sizes else 1
            self.pet.set_size(sizes[idx])
            self.surfaces.min_top = self.pet.display_h + 8
            self.pet.say(f"变{self._size_label()}啦", 1.2)
            self._save_config()
        elif cmd == ID_TOPMOST:
            self.topmost = not self.topmost
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST if self.topmost else HWND_NOTOPMOST,
                                0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        elif cmd == ID_AUTOSTART:
            set_autostart(not autostart_enabled())
        elif cmd == ID_HIDE:
            self._toggle_visible()
        elif cmd == ID_BALANCE:
            self._query_balance()
        elif cmd == ID_BALSTEP:
            self._cycle_balance_step()
        elif cmd == ID_BALTASK:
            # schtasks 会阻塞一秒左右，丢后台线程，别把鸟卡住
            threading.Thread(target=self._toggle_balance_task, daemon=True).start()
        elif cmd == ID_WEATHER:
            self._query_weather()
        elif cmd == ID_SETTINGS:
            self._open_settings()
        elif cmd == ID_QUIT:
            self._save_config()
            if self.tray_ok:
                nid = self._nid()
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            user32.DestroyWindow(self.hwnd)

    # -- 余额 / 天气 ------------------------------------------------------
    def _query_balance(self, silent: bool = False) -> None:
        key = (self.config.get("deepseek_api_key") or "").strip()
        if not key:
            if not silent:
                self.pet.say("还没填 API Key\n右键 → 设置，填完保存", 7.0)
            return
        if not silent:
            self.pet.say("帮你查余额…", 6.0)
        self.info.submit("balance", api_key=key, verbose=not silent)

    def _balance_step(self) -> float:
        try:
            return float(self.config.get("balance_step", 1.0))
        except (TypeError, ValueError):
            return 1.0

    def _balance_check_minutes(self) -> float:
        try:
            return max(0.0, float(self.config.get("balance_check_minutes", 0)))
        except (TypeError, ValueError):
            return 0.0

    def _toggle_balance_task(self) -> None:
        """开关「每小时自动查一次余额」的计划任务（后台线程里跑）。"""
        cur = self._task_enabled
        if cur is None:
            cur = balance_task_enabled()
        ok, msg = set_balance_task(not cur)
        if not ok:
            self.outbox.put(("err", "task", f"设置失败：{msg}", {"verbose": True}))
            return
        self._task_enabled = not cur
        if self._task_enabled:
            self.outbox.put(("ok", "task",
                             "自动查余额：开\n每小时一次，跨台阶才喊你", {}))
        else:
            self.outbox.put(("ok", "task",
                             "自动查余额：关\n只剩手动查和开机时查了", {}))

    def _cycle_balance_step(self) -> None:
        cur = self._balance_step()
        try:
            idx = BALANCE_STEPS.index(cur)
        except ValueError:
            idx = -1
        nxt = BALANCE_STEPS[(idx + 1) % len(BALANCE_STEPS)]
        self._set_config_value("balance_step", nxt)
        self.config["balance_step"] = nxt
        if nxt > 0:
            self.pet.say(f"余额提醒：每花 ¥{_money(nxt)}\n我就喊你一次", 6.0)
        else:
            self.pet.say("余额提醒关掉啦", 5.0)

    def _balance_alert_line(self, raw: dict):
        """推进消费台阶，返回要播报的文案（没跨台阶就是 None）。

        只在跨过台阶 / 首次读到 / 充值时写盘，用不着的磁盘写入一律免了。
        """
        if not raw:
            return None
        step = self._balance_step()
        current = raw.get("total")
        baseline = self.config.get("balance_baseline")
        alert, new_base = minbird_info.evaluate_spend(baseline, current, step)
        if new_base != baseline:
            self._set_config_value("balance_baseline", new_base)
            self.config["balance_baseline"] = new_base
        if alert is None:
            return None
        if alert["kind"] == "topup":
            return (f"DeepSeek 充值 +¥{_money(alert['amount'])}\n"
                    f"现在 ¥{_money(alert['current'])}")
        return (f"DeepSeek 又花掉 ¥{_money(alert['amount'])}\n"
                f"余额 ¥{_money(alert['current'])}")

    def _query_weather(self) -> None:
        self.pet.say("看看今天天气…", 6.0)
        self.info.submit("weather", city=(self.config.get("city") or "").strip())

    def _open_settings(self) -> None:
        if self._settings is not None:
            user32.SetForegroundWindow(self._settings.hwnd)
            return
        try:
            self._settings = SettingsWindow(self)
        except Exception:
            import traceback
            log_line("settings window failed\n" + traceback.format_exc())
            # 兜底：回到老办法，用记事本打开配置文件
            self._ensure_config_file()
            try:
                os.startfile(CONFIG_PATH)
                self.pet.say("设置窗口开不起来\n先用记事本改配置啦", 7.0)
            except Exception:
                self.pet.say(f"配置文件在：\n{CONFIG_PATH}", 9.0)
            return
        self.pet.say("设置窗口打开啦", 2.0)

    def _settings_closed(self, w) -> None:
        self._settings = None

    def apply_settings(self, v: dict) -> None:
        """设置窗口点保存：写配置 + 即时生效。"""
        data = self._read_disk_config()
        data.update({
            "deepseek_api_key": v["key"],
            "city": v["city"],
            "size": v["size"],
            "walk": v["walk"],
            "window_walk": v["wwin"],
            "seq_anim": v["anim"],
            "dance_on_aespa": v["dance"],
            "balance_step": v["step"],
        })
        self._write_config(data)
        self.config.update(data)

        self.options.walk = v["walk"]
        if not v["walk"] and self.pet.state == "walk":
            self.pet.state = "idle"
        self.pet.set_seq_mode(v["anim"] and self.pet.seq is not None)
        self._dance_enabled = v["dance"]
        if not v["dance"]:
            self._music_playing = False
            self.pet.stop_dance()
        if v["size"] != self.pet.display_h:
            self.pet.set_size(v["size"])
            self.surfaces.min_top = self.pet.display_h + 8
        if v["top"] != self.topmost:
            self._command(ID_TOPMOST)
        if v["autostart"] != autostart_enabled():
            set_autostart(v["autostart"])
        task_now = self._task_enabled if self._task_enabled is not None \
            else balance_task_enabled()
        if v["baltask"] != bool(task_now):
            threading.Thread(target=self._toggle_balance_task, daemon=True).start()
        self.pet.say("设置保存好啦", 2.5)

    def _music_loop(self) -> None:
        """每 5 秒查一次（纯本地：SMTC 优先，读不到就看播放器窗口+音频峰值）：
        发现 aespa 在放就通知主线程开跳。"""
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # MTA，音频峰值查询需要
        except Exception:
            pass
        while True:
            if self._dance_enabled:
                try:
                    playing = _query_music()
                    if playing != self._music_playing:
                        self._music_playing = playing
                        self.outbox.put(("ok", "music", "1" if playing else "0", {}))
                except Exception:
                    pass
            time.sleep(5.0)

    def _detect_first_boot(self) -> None:
        """对比系统启动时间签名，判断是不是本次开机后第一次启动珉鸟。"""
        sig = boot_signature()
        if not sig:
            return
        if sig != self.config.get("boot_sig"):
            self._set_config_value("boot_sig", sig)
            self._greet_at = time.perf_counter() + 1.0

    def _drain_info(self) -> None:
        """把后台线程查到的结果取回来，显示成气泡。"""
        try:
            while True:
                status, task, text, extra = self.outbox.get_nowait()
                if status == "ok":
                    if task == "balance":
                        verbose = extra.get("verbose", True)
                        line = self._balance_alert_line(extra.get("raw"))
                        if verbose:
                            # 手动查的：完整余额 + 这次跨过的台阶（如果有的话）
                            self.pet.say(text + (f"\n{line}" if line else ""))
                        elif line:
                            # 静默检查只在该提醒时才开口，否则一个字都不说
                            self.pet.react()
                            self.pet.say(line)
                    elif task == "music":
                        if text == "1":
                            self.pet.start_dance()   # 只跳舞，不打扰
                        else:
                            self.pet.stop_dance()
                    elif task == "weather" and extra.get("with_date"):
                        self.pet.say(f"{_date_line()}\n{text}")
                    else:
                        self.pet.say(text)
                else:
                    # 静默检查失败就别打扰了，手动查的才报错
                    if task == "task":
                        self.pet.say(text)
                    elif extra.get("verbose", True):
                        self.pet.say(f"没查到：{text}")
                # 首次查天气时若没配城市，把 IP 定位结果写回配置，下次直接用
                city = extra.get("city")
                if city and not (self.config.get("city") or "").strip():
                    self._set_config_value("city", city)
        except queue.Empty:
            return
        except Exception:
            return

    def _drain_alerts(self) -> None:
        """取走外部检查进程（--check-balance）留下的提醒。"""
        items = _read_alerts()
        if not items:
            return
        now = time.time()
        fresh = [it for it in items
                 if now - float(it.get("ts") or 0) <= ALERT_MAX_AGE]
        _clear_alerts()
        if not fresh:
            return
        # 最多念最近两条，攒了一堆也别糊一屏
        text = "\n".join(it["text"] for it in fresh[-2:])
        self.pet.react()
        self.pet.say(text)

    def _toggle_visible(self) -> None:
        self.visible = not self.visible
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetTimer(self.hwnd, TIMER_ID, self.TIMER_MS, None)
        else:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            user32.KillTimer(self.hwnd, TIMER_ID)

    # -- tray -------------------------------------------------------------
    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = APP_TITLE
        return nid

    def create_tray(self) -> None:
        icon_path = find_asset(ICON_CANDIDATES)
        if icon_path:
            self.hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                           LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self.hicon:
            self.hicon = user32.LoadIconW(None, 32512)
        nid = self._nid()
        self.tray_ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

    # -- render loop ------------------------------------------------------
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.08, now - self._last_render) if self._last_render else self.TIMER_MS / 1000.0
        self._last_render = now
        self._drain_info()
        # 启动后延迟几秒静默查一次余额（只在跨过提醒台阶时才开口）
        if self._start_check_at is not None and now >= self._start_check_at:
            self._start_check_at = None
            if self.config.get("balance_check_on_start", True):
                self._query_balance(silent=True)
        # 兜底：配置里写了 balance_check_minutes 才定期查，默认 0 = 一次都不查
        mins = self._balance_check_minutes()
        if mins > 0:
            if self._next_auto_check is None:
                self._next_auto_check = now + mins * 60.0
            elif now >= self._next_auto_check:
                self._next_auto_check = now + mins * 60.0
                self._query_balance(silent=True)
        elif self._next_auto_check is not None:
            self._next_auto_check = None
        # 开机后第一次启动：报一次日期 + 今日天气
        if self._greet_at is not None and now >= self._greet_at:
            self._greet_at = None
            self.pet.react()
            self.pet.say(f"开机啦！今天是{_date_line()}\n看看今天天气…", 8.0)
            self.info.submit("weather", city=(self.config.get("city") or "").strip(),
                             with_date=True)
        # 每 2 秒看一眼本地文件（配置有没有被手工改过 + 有没有待播的余额提醒）。
        # 这是本地磁盘读取，不是网络请求 —— 珉鸟不会自己去轮询 API。
        if now - self._last_cfg_check > 2.0:
            self._last_cfg_check = now
            self._watch_config()
            self._drain_alerts()
        # 窗口地面：每帧同步开关，每秒刷新一次窗口列表
        self.surfaces.enabled = bool(self.config.get("window_walk", True))
        self.surfaces.refresh(now)
        self.pet.update(dt, now)
        frame = self.pet.compose()
        self._present(frame)
        # alpha lookup table for hit testing
        self.pet.frame_size = frame.size
        self.pet.alpha_mask = frame.getchannel("A").tobytes()

    def _present(self, frame: Image.Image) -> None:
        w, h = frame.size
        x, y = self.pet.window_pos()
        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hbmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                      ctypes.byref(bits), None, 0)
        if not hbmp:
            if self._log and not getattr(self, "_dib_failed", False):
                self._dib_failed = True
                self._log("CreateDIBSection failed", "screen_dc=", screen_dc,
                          "mem_dc=", mem_dc, "err=", ctypes.get_last_error())
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)
            return
        data = to_premul_bgra(frame)
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem_dc, hbmp)

        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        size = SIZE(w, h)
        src = POINT(0, 0)
        dst = POINT(x, y)
        ok = user32.UpdateLayeredWindow(self.hwnd, screen_dc, ctypes.byref(dst),
                                        ctypes.byref(size), mem_dc, ctypes.byref(src),
                                        0, ctypes.byref(blend), ULW_ALPHA)
        self._present_calls = getattr(self, "_present_calls", 0) + 1
        if self._log and self._present_calls <= 4:
            opaque = sum(1 for i in range(3, len(data), 4) if data[i] > 8)
            self._log("present", w, h, "at", x, y, "ret=", ok,
                      "err=", ctypes.get_last_error(), "opaque_px=", opaque,
                      "bits=", bits.value, "mem_dc=", mem_dc, "screen_dc=", screen_dc)
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)

    # -- lifecycle --------------------------------------------------------
    def run(self) -> None:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        self.create_window()
        self.create_tray()
        frame = self.pet.compose()
        self._present(frame)
        self.pet.frame_size = frame.size
        self.pet.alpha_mask = frame.getchannel("A").tobytes()
        self._last_render = time.perf_counter()
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetTimer(self.hwnd, TIMER_ID, self.TIMER_MS, None)
        # 起来 5 秒后静默查一次余额（不弹余额，只在跨过提醒台阶时才开口）
        self._start_check_at = time.perf_counter() + 5.0
        # 开机后第一次启动的检测要查一次系统启动时间，丢后台线程
        threading.Thread(target=self._detect_first_boot, daemon=True).start()
        if self._log:
            self._log("shown; visible=", bool(user32.IsWindowVisible(self.hwnd)))

        msg = MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                if self._log:
                    self._log("message loop exit ret=", ret, "err=", ctypes.get_last_error())
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._save_config()


# --------------------------------------------------------------------------
# self test / preview
# --------------------------------------------------------------------------
def selftest() -> int:
    options = argparse.Namespace(size=168, walk=True)
    sprite_path = find_asset(SPRITE_CANDIDATES)
    if not sprite_path:
        print("sprite missing")
        return 1
    sprite = Image.open(sprite_path).convert("RGBA")
    sprite = sprite.crop(sprite.getchannel("A").getbbox() or (0, 0, *sprite.size))
    pet = Pet(sprite, options)

    shots = []

    pet.state = "idle"
    pet.bob = -1.0
    shots.append(pet.compose())

    pet.state = "walk"
    pet.facing = 1
    pet.hop = -8.0
    pet.angle = 4.0
    shots.append(pet.compose())

    pet.facing = -1
    pet.hop = -8.0
    pet.angle = -4.0
    shots.append(pet.compose())

    pet.facing = 1
    pet.hop = 0.0
    pet.angle = 20.0
    pet.squash = (0.94, 1.08)
    shots.append(pet.compose())

    pet.angle = -20.0
    shots.append(pet.compose())

    pet.angle = 0.0
    pet.squash = (1.0, 1.0)
    pet.say("珉鸟在此", 999)
    shots.append(pet.compose())
    pet.say("今天也要加油鸭", 999)
    shots.append(pet.compose())

    cw = max(s.width for s in shots)
    ch = max(s.height for s in shots)
    sheet = Image.new("RGBA", (cw * len(shots), ch), (238, 240, 244, 255))
    for i, s in enumerate(shots):
        sheet.alpha_composite(s, (i * cw + (cw - s.width) // 2, 0))
    out = os.path.join(ASSET_DIR, "_selftest.png")
    sheet.convert("RGB").save(out)
    print("selftest sheet:", out, sheet.size)
    return 0


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="珉鸟桌宠")
    parser.add_argument("--size", type=int, default=168, help="宠物高度（像素）")
    parser.add_argument("--no-walk", action="store_true", help="不要自己散步")
    parser.add_argument("--static", action="store_true",
                        help="不用序列帧动画，回退静态图模式")
    parser.add_argument("--debug", action="store_true", help="写运行日志")
    parser.add_argument("--selftest", action="store_true", help="只渲染预览图，不开窗口")
    parser.add_argument("--check-balance", action="store_true",
                        help="只查一次 DeepSeek 余额，跨过提醒台阶就写进待播队列，然后退出")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    # 一次性检查：不开窗口、不抢单实例锁、查完就走。
    # 交给 Windows 任务计划程序定期跑，就能做到"自动提醒但从不常驻轮询"。
    if args.check_balance:
        return check_balance_once(verbose=True)

    return _run_app(args)


def _run_app(args) -> int:
    # DPI awareness must be set before anything reads the work area, otherwise
    # the pet is positioned in logical coordinates while it paints in physical
    # pixels and lands in the wrong place on scaled displays.
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    mutex = kernel32.CreateMutexW(None, False, "MinBirdPetSingleInstance")
    err = ctypes.get_last_error()
    if args.debug:
        log_line("start; mutex=", mutex, "err=", err, "exe=", sys.executable)
    if err == 183:  # ERROR_ALREADY_EXISTS
        if args.debug:
            log_line("another instance is already running; exit")
        return 0

    options = argparse.Namespace(size=args.size, walk=not args.no_walk,
                                 debug=args.debug, static=args.static)
    try:
        app = MinBirdApp(options)
        app.run()
    except Exception:
        import traceback

        log_line("FATAL\n" + traceback.format_exc())
        if args.debug:
            traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
