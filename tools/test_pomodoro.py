# -*- coding: utf-8 -*-
"""番茄钟核心单元测试：python tools/test_pomodoro.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minbird.core.pomodoro import (FOCUS, IDLE, LONG_BREAK, PAUSED,
                                   SHORT_BREAK, Pomodoro, PomodoroConfig)


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Recorder:
    """事件收集器。"""

    def __init__(self):
        self.events = []

    def __call__(self, event, payload):
        self.events.append((event, payload))

    def of(self, event):
        return [p for e, p in self.events if e == event]

    def sequence(self):
        return [e for e, _ in self.events]


def make(focus=25, short=5, long=15, interval=4, t0=100.0):
    clock = FakeClock(t0)
    rec = Recorder()
    p = Pomodoro(PomodoroConfig(focus_sec=focus, short_break_sec=short,
                                long_break_sec=long,
                                long_break_interval=interval),
                 clock=clock, listener=rec)
    return p, clock, rec


def run_until_phase(p, clock, target, max_steps=20):
    """推进时钟并 tick，直到进入 target 阶段。"""
    for _ in range(max_steps):
        if p.phase == target:
            return True
        clock.advance(p.config.focus_sec if p.phase == FOCUS else
                      p.config.short_break_sec if p.phase == SHORT_BREAK
                      else p.config.long_break_sec)
        p.tick()
    return p.phase == target


# ---------------------------------------------------------------- 场景 1
def test_normal_4_rounds():
    """正常流程 4 轮：focus→short×3→long→focus，事件完整。"""
    p, clock, rec = make(interval=4)
    p.start()
    assert p.state == FOCUS and p.focus_count == 0
    seen = []
    for expected in (SHORT_BREAK, SHORT_BREAK, SHORT_BREAK, LONG_BREAK):
        # 专注到点
        clock.advance(25)
        p.tick()
        assert p.phase == expected, (p.phase, expected)
        seen.append(p.phase)
        # 休息到点
        dur = 15 if expected == LONG_BREAK else 5
        clock.advance(dur)
        p.tick()
        assert p.phase == FOCUS
    # 事件断言
    started = [e["phase"] for e in rec.of("phase_started")]
    assert started == [FOCUS, SHORT_BREAK, FOCUS, SHORT_BREAK, FOCUS,
                       SHORT_BREAK, FOCUS, LONG_BREAK, FOCUS]
    completed = [e["phase"] for e in rec.of("phase_completed")]
    assert completed == [FOCUS, SHORT_BREAK, FOCUS, SHORT_BREAK, FOCUS,
                         SHORT_BREAK, FOCUS, LONG_BREAK]
    assert len(rec.of("completed")) == 1 and rec.of("completed")[0]["rounds"] == 4
    assert len([e for e in rec.sequence() if e == "tick"]) >= 0
    # 4 个专注完成 + 1 次整组完成
    assert p.focus_count == 0  # longBreak 结束后循环重置
    print("PASS 正常流程 4 轮")


# ---------------------------------------------------------------- 场景 2
def test_pause_skip_reset():
    """暂停冻结剩余、继续接续；跳过按规则切换；重置回 idle。"""
    p, clock, rec = make()
    p.start()
    clock.advance(20)
    p.tick()
    rem_before = p.remaining_sec
    assert abs(rem_before - 5) < 1e-9

    # 暂停：时钟随便走，剩余冻结
    p.pause()
    assert p.state == PAUSED
    clock.advance(100)
    p.tick()
    assert p.remaining_sec == rem_before, "暂停期间剩余不应减少"
    p.pause()  # 重复暂停 no-op
    p.resume()  # 重复继续 no-op（先 resume 再 resume 第二次才是 no-op）
    p.resume()
    assert p.state == FOCUS
    clock.advance(3)
    p.tick()
    assert abs(p.remaining_sec - 2) < 1e-9, "继续后从冻结值接续"

    # 跳过：focus(round1) → short_break
    p.skip()
    assert p.phase == SHORT_BREAK
    p.skip()
    assert p.phase == FOCUS and p.focus_count == 1

    # 重置
    p.reset()
    assert p.state == IDLE and p.phase is None and p.focus_count == 0
    assert rec.of("reset")
    # idle 下操作均 no-op
    p.pause(); p.resume(); p.skip(); p.tick()
    assert p.state == IDLE
    p.start()
    assert p.state == FOCUS and p.focus_count == 0
    print("PASS 暂停/跳过/重置")


# ---------------------------------------------------------------- 场景 3
def test_sleep_resume():
    """休眠唤醒：on_suspend 冻结、on_resume 用新单调时刻重建 deadline。"""
    p, clock, rec = make(focus=25)
    p.start()
    clock.advance(5)
    p.tick()
    assert abs(p.remaining_sec - 20) < 1e-9

    # 休眠：挂起后时钟跳 1 小时（无论平台单调钟是否跨休眠计时）
    p.on_suspend()
    clock.advance(3600)
    p.tick()
    assert p.state == FOCUS, "挂起期间不应推进"
    p.on_resume()
    assert abs(p.remaining_sec - 20) < 1e-9, "唤醒后剩余应恢复为挂起前的值"

    # 对照：不挂起直接跳时钟 → 单调钟前进 = 真实流逝，阶段立即完成
    clock.advance(30)
    p.tick()
    assert p.phase == SHORT_BREAK
    print("PASS 休眠唤醒恢复")


# ---------------------------------------------------------------- 场景 4
def test_config_boundaries():
    """自定义时长边界：非法配置拒绝；1 秒阶段可用；interval=1 直接长休。"""
    for bad in ({"focus_sec": 0}, {"short_break_sec": -1},
                {"long_break_sec": 0}, {"long_break_interval": 0}):
        try:
            PomodoroConfig(**bad)
            raise AssertionError(f"{bad} 应拒绝")
        except ValueError:
            pass

    # 1 秒阶段
    p, clock, rec = make(focus=1, short=1, long=1, interval=1)
    p.start()
    clock.advance(1)
    p.tick()
    assert p.phase == LONG_BREAK, "interval=1 时专注后应直接长休"
    clock.advance(1)
    p.tick()
    assert p.phase == FOCUS and rec.of("completed")

    # 2 秒阶段 + interval=2
    p, clock, rec = make(focus=2, short=1, long=3, interval=2)
    p.start()
    clock.advance(2); p.tick()
    assert p.phase == SHORT_BREAK
    clock.advance(1); p.tick()
    clock.advance(2); p.tick()
    assert p.phase == LONG_BREAK
    print("PASS 自定义时长边界")


def main() -> int:
    test_normal_4_rounds()
    test_pause_skip_reset()
    test_sleep_resume()
    test_config_boundaries()
    print("== 番茄钟核心 4/4 场景通过 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
