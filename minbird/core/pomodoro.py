# -*- coding: utf-8 -*-
"""番茄钟状态机（核心层，纯逻辑，零 UI / 零 OS 依赖）。

设计要点：
- **deadline 制**：每阶段只存"结束时刻"（单调时钟），剩余时间 = deadline - now，
  天然免疫系统时间修改（改墙钟不影响 monotonic）
- **休眠恢复**：挂起/恢复由宿主转发（Windows 上即 WM_POWERBROADCAST 的
  SUSPEND/RESUME 消息），on_suspend 冻结剩余时间、on_resume 用当前单调
  时刻重建 deadline —— 无论平台单调钟是否跨休眠计时，结果都正确
- **事件驱动**：宿主每秒调 tick()，核心通过 listener 回调抛事件：
  tick / phase_started / phase_completed / completed / paused / resumed / reset
- 状态流转：idle → focus →(短休/长休循环)→ ... → longBreak → focus → ...
  长休间隔 = 每完成几个专注进入长休；longBreak 结束发 completed 并开启下一循环
"""
from __future__ import annotations

import time
from dataclasses import dataclass

IDLE = "idle"
FOCUS = "focus"
SHORT_BREAK = "short_break"
LONG_BREAK = "long_break"
PAUSED = "paused"


@dataclass(frozen=True)
class PomodoroConfig:
    """时长单位为秒；long_break_interval = 每完成几个专注进入长休。"""
    focus_sec: int = 25 * 60
    short_break_sec: int = 5 * 60
    long_break_sec: int = 15 * 60
    long_break_interval: int = 4

    def __post_init__(self):
        for name in ("focus_sec", "short_break_sec", "long_break_sec"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} 必须 >= 1 秒")
        if self.long_break_interval < 1:
            raise ValueError("long_break_interval 必须 >= 1")


class Pomodoro:
    """番茄钟核心。宿主每秒调 tick()；OS 事件由宿主转发给 on_suspend/on_resume。"""

    def __init__(self, config: PomodoroConfig | None = None,
                 clock=time.monotonic, listener=None):
        self.config = config or PomodoroConfig()
        self._clock = clock
        self._listeners = []
        if listener:
            self._listeners.append(listener)
        self._reset_state()   # 初始状态不作为 reset 事件广播

    # ---- 事件 ----
    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, event: str, **payload) -> None:
        for fn in tuple(self._listeners):
            fn(event, payload)

    # ---- 对外状态 ----
    @property
    def state(self) -> str:
        """idle / focus / short_break / long_break / paused。"""
        return PAUSED if self._paused else (self._phase or IDLE)

    @property
    def phase(self) -> str | None:
        """当前阶段名；idle/paused 下返回 None/paused 前的阶段。"""
        return self._phase

    @property
    def focus_count(self) -> int:
        """本循环内已完成的专注数（0..long_break_interval）。"""
        return self._round - 1

    @property
    def remaining_sec(self) -> float | None:
        """当前阶段剩余秒数；idle 下为 None，暂停下为冻结值。"""
        if self._phase is None:
            return None
        if self._paused or self._suspended:
            return self._frozen_remaining
        return max(0.0, self._deadline - self._clock())

    # ---- 操作 ----
    def start(self) -> None:
        """idle → 第一轮专注。已在运行/暂停时为 no-op。"""
        if self._phase is not None:
            return
        self._round = 1
        self._enter(FOCUS)

    def pause(self) -> None:
        if self._phase is None or self._paused or self._suspended:
            return
        self._frozen_remaining = max(0.0, self._deadline - self._clock())
        self._paused = True
        self._emit("paused", remaining_sec=self._frozen_remaining)

    def resume(self) -> None:
        if not self._paused:
            return
        self._deadline = self._clock() + self._frozen_remaining
        self._paused = False
        self._emit("resumed", remaining_sec=self._frozen_remaining)

    def skip(self) -> None:
        """放弃当前阶段，按正常完成规则切换到下一阶段。idle 下 no-op。"""
        if self._phase is None or self._suspended:
            return
        if self._paused:
            self._paused = False
        finished = self._phase
        self._advance(finished)

    def reset(self) -> None:
        """任意状态 → idle，清空轮次。"""
        self._reset_state()
        self._emit("reset")

    def _reset_state(self) -> None:
        self._phase = None
        self._round = 1
        self._paused = False
        self._suspended = False
        self._deadline = 0.0
        self._frozen_remaining = 0.0

    # ---- 休眠/唤醒（宿主转发 WM_POWERBROADCAST）----
    def on_suspend(self) -> None:
        if self._phase is not None and not self._paused and not self._suspended:
            self._frozen_remaining = max(0.0, self._deadline - self._clock())
            self._suspended = True

    def on_resume(self) -> None:
        if self._suspended:
            self._deadline = self._clock() + self._frozen_remaining
            self._suspended = False

    # ---- 每秒心跳 ----
    def tick(self) -> None:
        """宿主每秒调用一次。阶段到点自动切换并抛事件。"""
        if self._phase is None or self._paused or self._suspended:
            return
        # 防御：宿主长时间卡顿可能一次跨越多个阶段，设上限防死循环
        for _ in range(1000):
            now = self._clock()
            if now < self._deadline:
                self._emit("tick", remaining_sec=self._deadline - now,
                           phase=self._phase)
                return
            finished = self._phase
            self._advance(finished)
            if self._phase is None or self._paused:
                return

    # ---- 内部 ----
    def _duration_of(self, phase: str) -> int:
        cfg = self.config
        return {FOCUS: cfg.focus_sec, SHORT_BREAK: cfg.short_break_sec,
                LONG_BREAK: cfg.long_break_sec}[phase]

    def _enter(self, phase: str) -> None:
        self._phase = phase
        self._paused = False
        self._deadline = self._clock() + self._duration_of(phase)
        self._emit("phase_started", phase=phase, round=self._round,
                   duration_sec=self._duration_of(phase))

    def _advance(self, finished: str) -> None:
        """完成一个阶段并切换到下一阶段（skip 与到点共用）。"""
        self._emit("phase_completed", phase=finished, round=self._round)
        if finished == FOCUS:
            nxt = (LONG_BREAK if self._round % self.config.long_break_interval == 0
                   else SHORT_BREAK)
            self._round += 1
        else:
            nxt = FOCUS
            if finished == LONG_BREAK:
                # 此时 _round 已含本轮全部专注；结束后循环重置
                self._emit("completed", rounds=self._round - 1)
                self._round = 1
        self._enter(nxt)
