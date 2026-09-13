# -*- coding: utf-8 -*-
"""Win32 绑定与渲染原语（平台适配层）。

集中全部 ctypes 绑定、结构体、消息/样式常量与 GDI 上屏原语。
上层代码通过显式 import 使用这里的名字；核心层（minbird/core/）
禁止 import 本模块。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from PIL import Image, ImageChops


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



# ---- DPI 感知（Per-Monitor V2 优先，旧系统回退系统级）----
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
SWP_NOZORDER = 0x0004
WM_DPICHANGED = 0x02E0
WM_DISPLAYCHANGE = 0x007E


def enable_dpi_awareness() -> str:
    """设置进程 DPI 感知，返回实际生效模式："PMv2" / "system"。

    Per-Monitor V2（Win10 1703+）下多屏不同缩放不会糊/错位；
    老系统自动回退 SetProcessDPIAware。
    """
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_void_p
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "PMv2"
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "unavailable"


def get_dpi_for_window(hwnd) -> int:
    try:
        user32.GetDpiForWindow.argtypes = [wt.HWND]
        user32.GetDpiForWindow.restype = ctypes.c_uint
        return int(user32.GetDpiForWindow(hwnd))
    except Exception:
        return 96

_bind_prototypes()

if hasattr(user32, "GetWindowLongPtrW"):
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

    def _get_window_long(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongPtrW(hwnd, index))
else:
    def _get_window_long(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongW(hwnd, index))



dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long



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



# import 时完成全部原型绑定（与拆分前 minbird_pet 的模块级调用等价）
