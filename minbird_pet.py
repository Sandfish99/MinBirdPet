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
from minbird.platform.surfaces import PERCH_SNAP, WindowSurfaces  # noqa: F401 —— 平台适配层
from minbird.platform.autostart import autostart_enabled, autostart_target, set_autostart  # noqa: F401
from minbird.platform.boot import boot_signature  # noqa: F401
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
BUBBLE_TEXTS = [
    "啾~", "珉鸟在此", "摸摸头", "咕咕咕", "今天也要加油鸭",
    "别摸鱼啦", "饿饿，饭饭", "珉鸟巡逻中", "在的在的", "有事叫我",
]
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
        v = {
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
