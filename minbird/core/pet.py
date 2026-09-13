# -*- coding: utf-8 -*-
"""珉鸟状态机与逐帧合成（核心层，零 OS 依赖）。

Pet 只依赖 Pillow 与注入进来的 work_area_fn / font_provider /
surfaces（鸭子类型），所有 OS 细节由应用层注入。
"""
from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw, ImageFont

from minbird.core.hittest import HTCLIENT, hit_test
from minbird.core.interfaces import Rect

PERCH_SNAP = 160.0   # 下落没进窗口时，离窗沿多高以内会「扑棱」上去落住

BUBBLE_TEXTS = [
    "啾~", "珉鸟在此", "摸摸头", "咕咕咕", "今天也要加油鸭",
    "别摸鱼啦", "饿饿，饭饭", "珉鸟巡逻中", "在的在的", "有事叫我",
]


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class Pet:
    """Holds the pet state and composes the RGBA frame."""

    GRAVITY = 2800.0

    def __init__(self, sprite: Image.Image, options, seq: tuple | None = None,
                work_area_fn=None, font_provider=None):
        self.sprite_src = sprite
        self.options = options
        self.seq = seq              # (朝右帧, 朝左帧, fps)；None = 静态图模式
        # OS 依赖注入：核心层不直接调平台 API（缺省为中性占位，生产由 App 注入）
        self._work_area_fn = work_area_fn or (lambda: Rect(0, 0, 0, 0))
        self._font_provider = font_provider
        self.opacity = 1.0            # 0.1~1.0，合成时缩放 alpha
        self.theme_dark = False       # 气泡深色主题
        self.muted = False            # 勿扰：不说话不跳舞
        self.seq_mode = seq is not None
        self.base_right = None
        self.base_left = None
        _fp = font_provider or (lambda size: ImageFont.load_default())
        self.font = _fp(15)
        self.bubble_font = _fp(15)
        self._work_area_fn = work_area_fn or (lambda: Rect(0, 0, 0, 0))
        self.set_size(options.size)

        # --- kinematics (foot anchor in screen coords) ---
        wa = self._work_area_fn()
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

        if self.opacity < 1.0:
            alpha = canvas.getchannel("A").point(
                lambda v: int(v * self.opacity))
            canvas.putalpha(alpha)
        return canvas

    def _draw_bubble(self, canvas: Image.Image, layout, top_space: int) -> None:
        lines, line_h, bw, bh = layout
        cw = canvas.width
        d = ImageDraw.Draw(canvas, "RGBA")

        bx = clamp(cw / 2 - bw / 2, 2, max(2, cw - bw - 2))
        by = top_space + self.hop - bh - 10
        if by < 2:
            by = 2

        if self.theme_dark:
            fill, edge = (45, 45, 50, 242), (200, 204, 214, 255)
        else:
            fill, edge = (255, 255, 255, 240), (96, 104, 120, 255)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=11,
                            fill=fill, outline=edge, width=2)
        # 指向鸟嘴的小尖角
        tip_x = clamp(cw / 2, bx + 14, bx + bw - 14)
        d.polygon([(tip_x - 6, by + bh - 1), (tip_x + 6, by + bh - 1), (tip_x, by + bh + 9)],
                  fill=fill, outline=edge)
        d.line([(tip_x - 5, by + bh), (tip_x + 5, by + bh)], fill=fill, width=3)

        ty = by + 8
        for line in lines:
            d.text((bx + 13, ty), line, font=self.bubble_font,
                   fill=((235, 236, 240, 255) if self.theme_dark
                         else (38, 40, 48, 255)))
            ty += line_h

    # -- behaviour --------------------------------------------------------
    def say(self, text: str, seconds: float | None = None) -> None:
        if self.muted:
            return
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
        wa = self._work_area_fn()
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
    def _ground_under(self, wa: Rect) -> float:
        """站着/走着时脚下的地面：脚下窗沿，没有就任务栏顶。"""
        surf = self.surfaces
        if surf is None:
            return wa.bottom - 2
        return surf.ground_at(self.fx, self.fy, wa.bottom - 2)

    def _landing_under(self, wa: Rect, prev_fy: float) -> float:
        """下落时这一帧脚底扫过的最高落点。"""
        surf = self.surfaces
        if surf is None:
            return wa.bottom - 2
        return surf.landing_at(self.fx, prev_fy, self.fy, wa.bottom - 2)

    def _perch_under(self, wa: Rect) -> float | None:
        """身体已经没进某扇窗口时，够不够得着它的窗沿扑棱上去。"""
        surf = self.surfaces
        if surf is None:
            return None
        return surf.perch_at(self.fx, self.fy, PERCH_SNAP)

    def set_opacity(self, v: float) -> None:
        self.opacity = min(1.0, max(0.1, float(v)))

    def set_theme(self, dark: bool) -> None:
        self.theme_dark = bool(dark)

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
        wa = self._work_area_fn()

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
        return hit_test(self.alpha_mask, *self.frame_size, cx, cy) == HTCLIENT


# --------------------------------------------------------------------------
# 设置窗口（原生 Win32 控件，零第三方依赖）

