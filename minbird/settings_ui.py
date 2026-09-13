# -*- coding: utf-8 -*-
"""珉鸟设置中心（Win32 原生对话框，注册表驱动）。

- 设置项全部来自 core.settings_registry（分类/标签/类型/默认值/生效分发键）
- 顶部搜索框 + 分类下拉：实时过滤并重排可见控件
- 高级分类：日志导出/配置备份/恢复/导入导出/恢复默认值（comdlg32 文件对话框）
- 「保存」把全部控件值交回 app.apply_settings（注册表 coerce + 即时生效分发）
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from minbird.core import settings_registry as sr
from minbird.platform.autostart import autostart_enabled
from minbird.platform.tasks import balance_task_enabled
from minbird.platform.win32 import (
    LPARAM, LRESULT, WNDCLASSEXW, WNDPROC, WPARAM,
    WM_CLOSE, WM_COMMAND, WM_SETFONT,
    kernel32, user32, work_area)

# ---- 控件样式（应用层；与 win32 常量同值）----
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
WM_DESTROY = 0x0002
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
OFN_OVERWRITEPROMPT = 0x0002
OFN_PATHMUSTEXIST = 0x0800
OFN_FILEMUSTEXIST = 0x1000

comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)


class OPENFILENAME(ctypes.Structure):
    _fields_ = [("lStructSize", wt.DWORD), ("hwndOwner", wt.HWND),
                ("hInstance", wt.HINSTANCE), ("lpstrFilter", ctypes.c_void_p),
                ("lpstrCustomFilter", wt.LPWSTR), ("nMaxCustFilter", wt.DWORD),
                ("nFilterIndex", wt.DWORD), ("lpstrFile", ctypes.c_void_p),
                ("nMaxFile", wt.DWORD), ("lpstrFileTitle", wt.LPWSTR),
                ("nMaxFileTitle", wt.DWORD), ("lpstrInitialDir", wt.LPCWSTR),
                ("lpstrTitle", wt.LPCWSTR), ("Flags", wt.DWORD),
                ("nFileOffset", wt.WORD), ("nFileExtension", wt.WORD),
                ("lpstrDefExt", wt.LPCWSTR), ("lCustData", ctypes.c_void_p),
                ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wt.LPCWSTR)]


comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(OPENFILENAME)]
comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAME)]


def _create_ui_font():
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.CreateFontW.restype = wt.HFONT
    return gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                             "Microsoft YaHei UI")


def _lp_str(s: str):
    """CB_ADDSTRING 用的字符串缓冲区（调用方持有引用防回收）。"""
    return ctypes.create_unicode_buffer(s)


class SettingsWindow:
    """设置中心：搜索/分类过滤 + 注册表驱动控件 + 导入导出/恢复默认。"""

    CLIENT_W, CLIENT_H = 508, 424
    ID_SAVE, ID_CANCEL = 1, 2
    ID_SEARCH, ID_CAT = 3001, 3002
    CLASS_NAME = "MinBirdSettingsWindow"

    def __init__(self, app):
        self.app = app
        self.hwnd = None
        self._font = _create_ui_font()
        self._rows = []          # 持久化设置行
        self._actions = []       # 高级动作按钮
        self._keepalive = []
        self._controls = {}      # cid -> hwnd（搜索框/分类下拉）
        self._cb = WNDPROC(self._proc)
        if not getattr(user32, "_minbird_settings_bound", False):
            user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
            user32.SendMessageW.restype = LRESULT
            user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
            user32.AdjustWindowRectEx.argtypes = [
                ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
            user32._minbird_settings_bound = True
        self._build()

    # ---- 构建 ----
    def _build(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._cb
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, 32512)
        wc.lpszClassName = self.CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            if ctypes.get_last_error() != 1410:
                raise OSError("RegisterClassExW(settings) failed")

        rect = wt.RECT(0, 0, self.CLIENT_W, self.CLIENT_H)
        style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
        user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, 0)
        w, h = rect.right - rect.left, rect.bottom - rect.top
        wa = work_area()
        self.hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "珉鸟设置", style | WS_VISIBLE,
            wa.left + max(0, (wa.right - wa.left - w) // 2),
            wa.top + max(0, (wa.bottom - wa.top - h) // 3),
            w, h, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW(settings) failed")

        cfg = self.app.config
        add = self._add

        add("STATIC", "搜索：", 0, 14, 14, 44, 20, 0)
        h_search = add("EDIT", "", WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
                       60, 12, 170, 24, self.ID_SEARCH)
        self._controls[self.ID_SEARCH] = h_search
        add("STATIC", "分类：", 0, 250, 14, 44, 20, 0)
        combo = add("COMBOBOX", "", CBS_DROPDOWNLIST | WS_TABSTOP,
                    296, 10, 196, 160, self.ID_CAT)
        self._controls[self.ID_CAT] = combo
        cats = ("全部",) + sr.categories()
        for i, cat in enumerate(cats):
            p = _lp_str(cat)
            self._keepalive.append(p)
            user32.SendMessageW(combo, CB_ADDSTRING, 0,
                                LPARAM(ctypes.addressof(p)))
        user32.SendMessageW(combo, CB_SETCURSEL, 1, 0)  # 默认「宠物」

        # 注册表驱动的行控件
        for n, item in enumerate(sr.ITEMS):
            cid = 4000 + n
            if item.type == "bool":
                h = add("BUTTON", item.label, BS_AUTOCHECKBOX | WS_TABSTOP,
                        18, 0, 230, 24, cid)
                user32.SendMessageW(h, BM_SETCHECK,
                                    1 if bool(cfg.get(item.key, item.default)) else 0, 0)
                self._rows.append({"item": item, "hwnds": [h], "kind": "bool"})
            elif item.type == "enum":
                lab = add("STATIC", item.label + "：", 0, 18, 0, 150, 20, 0)
                h = add("COMBOBOX", "", CBS_DROPDOWNLIST | WS_TABSTOP,
                        244, 0, 246, 160, cid)
                cur = cfg.get(item.key, item.default)
                vals = item.choices_map or item.choices
                for disp in item.choices:
                    p2 = _lp_str(disp)
                    self._keepalive.append(p2)
                    user32.SendMessageW(h, CB_ADDSTRING, 0,
                                        LPARAM(ctypes.addressof(p2)))
                if cur in vals:
                    user32.SendMessageW(h, CB_SETCURSEL,
                                        list(vals).index(cur), 0)
                self._rows.append({"item": item, "hwnds": [lab, h],
                                   "kind": "enum"})
            elif item.type == "int":
                lab = add("STATIC", item.label + "：", 0, 18, 0, 216, 20, 0)
                h = add("EDIT", str(cfg.get(item.key, item.default)),
                        WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
                        244, 0, 246, 24, cid)
                self._rows.append({"item": item, "hwnds": [lab, h], "kind": "int"})
            elif item.type == "str":
                lab = add("STATIC", item.label + "：", 0, 18, 0, 216, 20, 0)
                h = add("EDIT", str(cfg.get(item.key, item.default) or ""),
                        WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
                        244, 0, 246, 24, cid)
                self._rows.append({"item": item, "hwnds": [lab, h], "kind": "str"})
            elif item.type == "action":
                h = add("BUTTON", item.label, WS_TABSTOP, 18, 0, 230, 26,
                        5000 + len(self._actions))
                self._actions.append({"item": item, "hwnd": h,
                                      "apply": item.apply})

        add("BUTTON", "保存", BS_DEFPUSHBUTTON | WS_TABSTOP, 316, 384, 84, 28,
            self.ID_SAVE)
        add("BUTTON", "取消", WS_TABSTOP, 406, 384, 84, 28, self.ID_CANCEL)
        self._apply_filter()

    def _add(self, cls, text, style, x, y, w, h, cid):
        hwnd = user32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, w, h, self.hwnd, cid, kernel32.GetModuleHandleW(None), None)
        if self._font:
            user32.SendMessageW(hwnd, WM_SETFONT, self._font, 1)
        return hwnd

    # ---- 过滤与重排 ----
    def _apply_filter(self) -> None:
        q = self._ctrl_text(self._controls.get(self.ID_SEARCH)).lower()
        i_cat = self._combo_sel(self._controls.get(self.ID_CAT))
        cats = ("全部",) + sr.categories()
        cat = cats[i_cat] if 0 <= i_cat < len(cats) else "全部"

        y = 48
        col = 0
        for row in self._rows:
            item = row["item"]
            match_search = (not q) or (q in item.label.lower()
                                       or q in item.key.lower()
                                       or q in item.category.lower())
            match_cat = (cat == "全部") or (item.category == cat)
            match = match_search if q else match_cat
            for h in row["hwnds"]:
                user32.ShowWindow(h, 5 if match else 0)
            if not match:
                continue
            if item.type == "bool":
                x = 18 if col == 0 else 254
                self._move(row["hwnds"], x, y)
                col += 1
                if col == 2:
                    col = 0
                    y += 28
            else:
                if col == 1:
                    col = 0
                    y += 28
                user32.SetWindowPos(row["hwnds"][0], None, 18, y + 2, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                user32.SetWindowPos(row["hwnds"][1], None, 244, y, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                y += 32
        if col == 1:
            y += 28
        # 高级动作按钮（跟随过滤）
        for a in self._actions:
            item = a["item"]
            match = (cat in ("全部", item.category)) and \
                    (not q or q in item.label.lower())
            user32.ShowWindow(a["hwnd"], 5 if match else 0)

    @staticmethod
    def _move(hwnds, x, y):
        for i, h in enumerate(hwnds):
            dx = (244 - 18) if i == 1 and len(hwnds) == 2 else 0
            user32.SetWindowPos(h, None, x + dx, y, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    # ---- 读控件 ----
    def _ctrl_text(self, h) -> str:
        if not h:
            return ""
        n = user32.GetWindowTextLengthW(h) + 1
        buf = ctypes.create_unicode_buffer(n)
        user32.GetWindowTextW(h, buf, n)
        return buf.value.strip()

    def _check(self, h) -> bool:
        return bool(h) and user32.SendMessageW(h, BM_GETCHECK, 0, 0) == 1

    def _combo_sel(self, h) -> int:
        return user32.SendMessageW(h, CB_GETCURSEL, 0, 0) if h else -1

    def _save(self) -> None:
        values = {}
        for row in self._rows:
            item = row["item"]
            if item.type == "bool":
                values[item.key] = self._check(row["hwnds"][0])
            elif item.type == "enum":
                i = self._combo_sel(row["hwnds"][1])
                vals = item.choices_map or item.choices
                if 0 <= i < len(vals):
                    values[item.key] = vals[i]
            elif item.type in ("int", "str"):
                values[item.key] = self._ctrl_text(row["hwnds"][1])
        user32.EnableWindow(self.hwnd, False)
        try:
            self.app.apply_settings(values)
        finally:
            user32.DestroyWindow(self.hwnd)

    # ---- 消息 ----
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            cid = wparam & 0xFFFF
            if cid == self.ID_SAVE:
                self._save()
                return 0
            if cid == self.ID_CANCEL:
                user32.DestroyWindow(hwnd)
                return 0
            if cid in (self.ID_SEARCH, self.ID_CAT):
                self._apply_filter()
                return 0
            for j, a in enumerate(self._actions):
                if cid == 5000 + j:
                    self.app.run_settings_action(a["apply"], self.hwnd)
                    return 0
        elif msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            self.app._settings_closed(self)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
