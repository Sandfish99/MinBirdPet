# -*- coding: utf-8 -*-
"""珉鸟设置窗口（Win32 原生对话框，应用层 UI 适配）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from minbird.platform.autostart import autostart_enabled
from minbird.platform.tasks import balance_task_enabled
from minbird.platform.win32 import (
    LPARAM,
    LRESULT,
    WNDCLASSEXW,
    WNDPROC,
    WPARAM,
    WM_CLOSE,
    WM_COMMAND,
    WM_DESTROY,
    WM_SETFONT,
    gdi32,
    kernel32,
    user32,
    work_area,
)

# --------------------------------------------------------------------------
# 设置窗口控件样式（Win32）
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

        import minbird_pet as mp  # 惰性导入，避免循环

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
        for label, px in mp.SIZE_PRESETS:
            p = ctypes.c_wchar_p(label)
            self._keepalive.append(p)
            user32.SendMessageW(combo_size, CB_ADDSTRING, 0,
                                LPARAM(ctypes.cast(p, ctypes.c_void_p).value))
            if px == self.app.pet.display_h:
                user32.SendMessageW(combo_size, CB_SETCURSEL,
                                    [p2 for _, p2 in mp.SIZE_PRESETS].index(px), 0)
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
        import minbird_pet as mp  # 惰性导入，避免循环

        i_size, i_step = self._combo(self.ID_SIZE), self._combo(self.ID_STEP)
        v = {
            "key": self._text(self.ID_KEY),
            "city": self._text(self.ID_CITY),
            "size": mp.SIZE_PRESETS[i_size][1] if 0 <= i_size < len(mp.SIZE_PRESETS)
                    else self.app.pet.display_h,
            "step": mp.BALANCE_STEPS[i_step] if 0 <= i_step < len(mp.BALANCE_STEPS)
                    else self.app._balance_step(),
            "walk": self._check(self.ID_WALK),
            "wwin": self._check(self.ID_WWIN),
            "anim": self._check(self.ID_ANIM),
            "top": self._check(self.ID_TOP),
            "dance": self._check(self.ID_DANCE),
            "autostart": self._check(self.ID_AUTOSTART),
            "baltask": self._check(self.ID_BALTASK),
        }
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
