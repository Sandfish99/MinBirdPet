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

from PIL import Image, ImageDraw, ImageFont


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
from minbird.platform.win32 import (  # noqa: F401 —— 平台适配层（唯一 OS 出口）
    SWP_NOZORDER,
    WM_DISPLAYCHANGE,
    WM_DPICHANGED,
    enable_dpi_awareness,
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BITMAPINFO,
    BITMAPINFOHEADER,
    BI_RGB,
    BLENDFUNCTION,
    DIB_RGB_COLORS,
    HTCLIENT,
    HTTRANSPARENT,
    HWND_NOTOPMOST,
    HWND_TOPMOST,
    ID_AUTOSTART,
    ID_BALANCE,
    ID_BALSTEP,
    ID_BALTASK,
    ID_CYCLE_SIZE,
    ID_DANCE,
    ID_FSHIDE,
    ID_HIDE,
    ID_QUIT,
    ID_REACT,
    ID_SEQANIM,
    ID_SETTINGS,
    ID_TOGGLE_WALK,
    ID_TOPMOST,
    ID_WEATHER,
    ID_WINDOWWALK,
    IMAGE_ICON,
    LPARAM,
    LRESULT,
    LR_DEFAULTSIZE,
    LR_LOADFROMFILE,
    MA_NOACTIVATE,
    MF_CHECKED,
    MF_SEPARATOR,
    MF_STRING,
    MSG,
    NIF_ICON,
    NIF_MESSAGE,
    NIF_TIP,
    NIM_ADD,
    NIM_DELETE,
    NOTIFYICONDATAW,
    POINT,
    RECT,
    SIZE,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    TIMER_ID,
    TPM_RETURNCMD,
    TPM_RIGHTBUTTON,
    ULW_ALPHA,
    WM_CLOSE,
    WM_COMMAND,
    WM_DESTROY,
    WM_LBUTTONDBLCLK,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEACTIVATE,
    WM_MOUSEMOVE,
    WM_NCHITTEST,
    WM_NULL,
    WM_RBUTTONUP,
    WM_SETFONT,
    WM_TIMER,
    WM_TRAYICON,
    WNDCLASSEXW,
    WNDPROC,
    WPARAM,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_POPUP,
    cursor_pos,
    gdi32,
    kernel32,
    shell32,
    to_premul_bgra,
    user32,
    work_area,
)
from minbird.core.music import match_aespa as _match_aespa  # noqa: F401 —— 测试经此访问
from minbird.platform.music import query_music as _query_music  # noqa: F401
from minbird.platform.proc import _ps, _run, _sq  # noqa: F401 —— 子进程适配
from minbird.platform.surfaces import WindowSurfaces  # noqa: F401 —— 平台适配层
from minbird.core.pet import BUBBLE_TEXTS, PERCH_SNAP, Pet, clamp  # noqa: F401 —— 核心层
from minbird.core import geom
from minbird.core.hittest import hit_test  # 逐像素命中（纯逻辑）
from minbird.core.interfaces import Rect
from minbird.platform import monitors, win32
from minbird.platform.autostart import autostart_enabled, autostart_target, set_autostart  # noqa: F401
from minbird.platform.boot import boot_signature  # noqa: F401
from minbird.platform.state import load_state, save_state
from minbird.platform.memory import current_rss_mb
from minbird.platform.fullscreen import fullscreen_hwnd
from minbird.platform import env
from minbird.platform.update_swap import apply_pending_update, has_prev_version, rollback  # noqa: F401
from minbird.core.safemode import next_streak, safe_mode_required
from minbird.settings_ui import SettingsWindow  # noqa: F401
from minbird.logging_setup import (  # noqa: F401 —— 日志与崩溃捕获
    install_excepthook, log_line, write_crash_report)
from minbird.config_store import ConfigStore  # 配置原子写/备份/迁移
from minbird.platform.tasks import TASK_NAME, balance_task_enabled, set_balance_task  # noqa: F401

SPRITE_CANDIDATES = ("minbird.png", "minbird_flip.png")
ICON_CANDIDATES = ("minbird.ico",)
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

SIZE_PRESETS = [("小", 118), ("中", 168), ("大", 232), ("特大", 300)]
WALK_ENABLED_DEFAULT = True



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


# helpers
# --------------------------------------------------------------------------

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
ALERT_MAX_LINES = 50          # 提醒队列文件行数上限（资源限制）


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
        # 资源上限：队列文件最多 50 行，超出只留最新的
        with open(ALERT_PATH, "r", encoding="utf-8") as fh:
            alines = fh.readlines()
        if len(alines) > ALERT_MAX_LINES:
            with open(ALERT_PATH, "w", encoding="utf-8") as fh:
                fh.writelines(alines[-ALERT_MAX_LINES:])
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


def check_balance_once(verbose: bool = False) -> int:
    """一次性的余额检查（--check-balance）。查完就退出，不留任何后台连接。

    返回 0 正常 / 1 查询失败 / 2 没配 Key 或提醒关着。
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
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


def _date_line() -> str:
    t = time.localtime()
    return f"{t.tm_mon}月{t.tm_mday}日 周{'一二三四五六日'[t.tm_wday]}"


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


# --------------------------------------------------------------------------
# pet
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
        self._last_tick_ok = time.perf_counter()
        self._next_mem_check = 0.0
        self._MEM_LIMIT_MB = 512.0   # 超过先 gc，仍超则回退静态图
        self._mem_guard_logged = False
        self._auto_hidden = False      # 全屏自动躲藏（区别于用户手动藏）
        self._next_fs_check = 0.0
        self._safe = bool(getattr(options, "safe", False))
        self._degrade_reasons = env.degrade_reasons()
        if self._degrade_reasons:
            self.TIMER_MS = 66   # RDP/虚拟机：降帧省带宽与 CPU
            log_line("degraded env:", ";".join(self._degrade_reasons))
        self._store = ConfigStore(CONFIG_PATH, CONFIG_DEFAULTS, log=log_line)
        self.config = self._load_config()
        if self._safe and getattr(self, "_config_broken", False):
            # 安全模式允许"显式"从 .bak 恢复配置（正常模式按契约绝不自动覆盖）
            if self._store.restore_from_backup():
                self._config_broken = False
                self.config = self._load_config()
                log_line("safe mode: config restored from .bak")
        self._ensure_config_file()
        try:
            self._config_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

        # 余额 / 天气：后台线程查，结果丢进 outbox，主线程在 _tick 里取
        self.outbox = queue.Queue()
        self.info = minbird_info.InfoService(self.outbox)

        # 设置窗口 / 音乐联动 / 开机问候（安全模式下只保留基础能力）
        self._settings = None
        self._dance_enabled = bool(self.config.get("dance_on_aespa", True))
        self._music_playing = False
        self._greet_at = None
        self._last_tick_ok = time.perf_counter()
        if not self._safe:
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
        self.pet = Pet(sprite, options, seq=seq,
                       work_area_fn=self._pet_work_area,
                       font_provider=load_font)
        if seq is not None:
            # --static = 本次启动强制静态（排障用）；平时由配置 seq_anim 决定
            self.pet.seq_mode = (not getattr(options, "static", False)) and \
                bool(self.config.get("seq_anim", True))
        self.pet.set_size(options.size)
        self.surfaces = WindowSurfaces()
        self.pet.surfaces = self.surfaces
        self.surfaces.min_top = self.pet.display_h + 8

        # 多屏兼容：绝对坐标仍在虚拟桌面内 → 原位；否则按相对坐标落回；
        # 最后钳进珉鸟所在的显示器（热插拔/改分辨率的兜底）
        try:
            vx0, vy0, vx1, vy1 = monitors.virtual_screen()
            x = float(self.config.get("x") or 0)
            y = float(self.config.get("y") or 0)
            inside = (vx0 <= x < vx1 and vy0 <= y < vy1) and (x or y)
        except (TypeError, ValueError):
            inside = False
        if inside:
            self.pet.place(x, y)
        else:
            wa = win32.work_area()
            rx = float(self.config.get("rx") or 0.72)
            ry = float(self.config.get("ry") or 0.85)
            self.pet.place(*geom.point_from_relative(wa, rx, ry))
        wa = monitors.work_area_for_point(self.pet.fx, self.pet.fy)
        self.pet.place(*geom.clamp_into(wa, self.pet.fx, self.pet.fy))

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
        data, broken = self._store.read()
        if broken:
            # 用户编辑到一半 / JSON 写坏了 —— 这时候千万不能覆盖文件，
            # 否则他填的 Key 就没了。记个标记，整个会话都别写盘。
            self._config_broken = True
            return {}
        return data

    def _write_config(self, data: dict) -> None:
        if getattr(self, "_config_broken", False):
            return
        self._store.write_atomic(data)
        try:
            self._config_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

    def _load_config(self) -> dict:
        # 启动时：损坏可从 .bak 自动恢复；随后按 config_version 迁移
        data, broken = self._store.load_with_recovery()
        if broken:
            self._config_broken = True
            return data
        data, migrated = self._store.migrate(data)
        if migrated and not self._store.write_atomic(data):
            log_line("config migrate write failed")
        return data

    def _ensure_config_file(self) -> None:
        """保证配置文件存在且带默认字段，方便直接填 API Key。"""
        data = self._read_disk_config()
        data, changed = self._store.ensure_defaults(data)
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
        try:
            wa = monitors.work_area_for_point(self.pet.fx, self.pet.fy)
            data["rx"], data["ry"] = geom.relative_of(wa, self.pet.fx, self.pet.fy)
        except Exception:
            pass
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

    def _pet_work_area(self) -> Rect:
        """珉鸟所在显示器的有效工作区（多屏；取不到回退主屏工作区）。"""
        pet = getattr(self, "pet", None)
        if pet is not None:
            try:
                return monitors.work_area_for_point(pet.fx, pet.fy)
            except Exception:
                pass
        wa = win32.work_area()
        return Rect(wa.left, wa.top, wa.right, wa.bottom)

    def _handle(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            sx = ctypes.c_short(lparam & 0xFFFF).value
            sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            wx, wy = self.pet.window_pos()
            return hit_test(self.pet.alpha_mask, *self.pet.frame_size,
                            sx - wx, sy - wy)

        if msg == WM_DISPLAYCHANGE:
            # 显示器热插拔 / 分辨率变化：把珉鸟重新钳回最近的屏幕
            try:
                wa = self._pet_work_area()
                self.pet.place(*geom.clamp_into(wa, self.pet.fx, self.pet.fy))
                log_line("display change; pet re-clamped to", wa)
            except Exception:
                pass
            return 0

        if msg == WM_DPICHANGED:
            # 跨屏 DPI 变化：用系统建议位置跟过去（尺寸仍是用户设定的物理像素）
            try:
                rect = ctypes.cast(lparam, ctypes.POINTER(RECT)).contents
                user32.SetWindowPos(hwnd, None, rect.left, rect.top, 0, 0,
                                    SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER)
                log_line("dpi changed ->", wparam & 0xFFFF)
            except Exception:
                pass
            return 0

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
        fsh = MF_CHECKED if self.config.get("fullscreen_hide", True) else 0
        user32.AppendMenuW(menu, MF_STRING | fsh, ID_FSHIDE, "全屏时自动躲起来")
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
        elif cmd == ID_FSHIDE:
            new = not bool(self.config.get("fullscreen_hide", True))
            self._set_config_value("fullscreen_hide", new)
            self.pet.say("好，全屏时我躲起来" if new else "那我看全屏也不走", 2.5)
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

    def _watchdog_loop(self) -> None:
        """看门狗：主渲染循环 60 秒无心跳 → 落盘诊断后强制退出（下次进安全模式）。
        系统休眠/恢复期间两个时钟会失真，检测到就跳过本轮，避免误杀。"""
        k32 = ctypes.windll.kernel32
        last_tick64 = k32.GetTickCount64()
        last_mono = time.perf_counter()
        while True:
            time.sleep(10)
            now_tick64 = k32.GetTickCount64()
            now_mono = time.perf_counter()
            if abs((now_tick64 - last_tick64) / 1000.0 - (now_mono - last_mono)) > 10:
                last_tick64, last_mono = now_tick64, now_mono
                continue   # 休眠/恢复，时钟失真
            last_tick64, last_mono = now_tick64, now_mono
            if not self.visible:
                continue   # 隐藏时主定时器本来就停着
            if now_mono - self._last_tick_ok > 60:
                log_line("watchdog: main loop stalled >60s; exiting")
                try:
                    path = os.path.join(CONFIG_DIR, "runtime_state.json")
                    save_state(path, {"clean": False,
                                      "run_streak": next_streak(
                                          load_state(path)) + 1})
                except Exception:
                    pass
                os._exit(3)

    def _music_loop(self) -> None:
        """每 5 秒查一次（纯本地：SMTC 优先，读不到就看播放器窗口+音频峰值）：
        发现 aespa 在放就通知主线程开跳。"""
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # MTA，音频峰值查询需要
        except Exception:
            pass
        fails = 0
        while True:
            if self._dance_enabled:
                try:
                    playing = _query_music()
                    if fails:
                        log_line("music probe recovered after", fails, "failure(s)")
                    fails = 0
                    if playing != self._music_playing:
                        self._music_playing = playing
                        self.outbox.put(("ok", "music", "1" if playing else "0", {}))
                except Exception as exc:
                    fails += 1
                    # 首次 + 之后约每 3 分钟记一条，别刷爆日志
                    if fails == 1 or fails % 36 == 0:
                        log_line("music probe failed x", fails, repr(exc))
            # 连续失败（多半是杀软拦 PowerShell）就退避到 5 分钟一问，
            # 避免无意义的反复触发
            time.sleep(5.0 if fails < 3 else 300.0)

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
        self._last_tick_ok = now
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
        # 全屏自动躲藏：前台全屏（游戏/视频）→ 藏；退出 → 回来
        if now >= self._next_fs_check:
            self._next_fs_check = now + 1.0
            if self._auto_hidden:
                try:
                    if not fullscreen_hwnd(self.hwnd):
                        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
                        self._auto_hidden = False
                except Exception:
                    pass
            elif self.visible and self.config.get("fullscreen_hide", True)                     and not self._safe:
                try:
                    if fullscreen_hwnd(self.hwnd):
                        user32.ShowWindow(self.hwnd, SW_HIDE)
                        self._auto_hidden = True
                except Exception:
                    pass
        if self._auto_hidden:
            return   # 躲藏期间跳过渲染，省合成开销
        # 内存守卫：超限先 gc，仍超就回退静态图（序列帧缓存是最大头）
        if now >= self._next_mem_check:
            self._next_mem_check = now + 60.0
            rss = current_rss_mb()
            if rss is not None and rss > self._MEM_LIMIT_MB:
                import gc
                gc.collect()
                rss2 = current_rss_mb()
                over = rss2 is not None and rss2 > self._MEM_LIMIT_MB
                if over and self.pet.seq_mode:
                    self.pet.set_seq_mode(False)
                    self.pet.say("内存占用过高\n已切回静态图", 6.0)
                if over != self._mem_guard_logged:
                    self._mem_guard_logged = over
                    log_line("memory guard:", rss, "->", rss2, "MB (limit",
                             self._MEM_LIMIT_MB, ")")
        # 窗口地面：每帧同步开关，每秒刷新一次窗口列表
        self.surfaces.enabled = (not self._safe) and (
            not self._degrade_reasons) and bool(
            self.config.get("window_walk", True))
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
            enable_dpi_awareness()
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
        if self._safe:
            self.pet.set_seq_mode(False)
            self.surfaces.enabled = False
            self.pet.say("安全模式启动\n只保留基础功能", 8.0)
        else:
            # 起来 5 秒后静默查一次余额（不弹余额，只在跨过提醒台阶时才开口）
            self._start_check_at = time.perf_counter() + 5.0
            # 开机后第一次启动的检测要查一次系统启动时间，丢后台线程
            threading.Thread(target=self._detect_first_boot, daemon=True).start()
        if self._log:
            self._log("shown; visible=", bool(user32.IsWindowVisible(self.hwnd)))

        threading.Thread(target=self._watchdog_loop, daemon=True).start()
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
    pet = Pet(sprite, options, work_area_fn=work_area, font_provider=load_font)

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
    parser.add_argument("--safe", action="store_true",
                        help="强制安全模式：静态图、关音乐联动/开机问候/自检")
    parser.add_argument("--rollback", action="store_true",
                        help="回退到上一个 exe 版本（需存在 MinBirdPet_prev.exe）")
    parser.add_argument("--debug", action="store_true", help="写运行日志")
    parser.add_argument("--selftest", action="store_true", help="只渲染预览图，不开窗口")
    parser.add_argument("--check-balance", action="store_true",
                        help="只查一次 DeepSeek 余额，跨过提醒台阶就写进待播队列，然后退出")
    args = parser.parse_args(argv)

    if args.rollback:
        return 0 if rollback(log_line) else 1

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
        enable_dpi_awareness()
    except Exception:
        pass

    install_excepthook()
    apply_pending_update(log_line)
    state_path = os.path.join(CONFIG_DIR, "runtime_state.json")
    streak = next_streak(load_state(state_path))
    safe = bool(getattr(args, "safe", False)) or safe_mode_required(streak)
    if safe:
        log_line("safe mode ON; run_streak=", streak)
    save_state(state_path, {"clean": False, "run_streak": streak})
    mutex = kernel32.CreateMutexW(None, False, "MinBirdPetSingleInstance")
    err = ctypes.get_last_error()
    if args.debug:
        log_line("start; mutex=", mutex, "err=", err, "exe=", sys.executable)
    if err == 183:  # ERROR_ALREADY_EXISTS
        if args.debug:
            log_line("another instance is already running; exit")
        return 0

    options = argparse.Namespace(size=args.size, walk=not args.no_walk,
                                 debug=args.debug, static=args.static, safe=safe)
    try:
        app = MinBirdApp(options)
        app.run()
        # 正常退出：清零崩溃连击
        save_state(state_path, {"clean": True, "run_streak": 0})
    except Exception:
        import traceback

        write_crash_report("fatal", traceback.format_exc())
        log_line("FATAL\n" + traceback.format_exc())
        if args.debug:
            traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
