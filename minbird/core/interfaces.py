# -*- coding: utf-8 -*-
"""核心层接口定义。

本模块是"核心层 ↔ 平台适配层"的唯一契约：核心层（状态机、决策逻辑）
只依赖这里声明的 Protocol，绝不直接 import ctypes / winreg / subprocess 等
OS 能力；平台适配层负责实现这些接口。

约定：
- 核心层用到的几何类型统一用 Rect（纯数据），平台层负责与 Win32 RECT 互转。
- 所有 Protocol 都是小接口（1~3 个方法），便于用假对象替身测试。
"""
from __future__ import annotations

from typing import NamedTuple, Protocol, runtime_checkable


class Rect(NamedTuple):
    """与 Win32 RECT 同名的纯数据矩形（left/top/right/bottom）。"""
    left: int
    top: int
    right: int
    bottom: int


@runtime_checkable
class WorkAreaSource(Protocol):
    """工作区（去掉任务栏后的桌面区域）提供者。"""

    def work_area(self) -> Rect:
        ...


@runtime_checkable
class MusicProbe(Protocol):
    """音乐检测探针：判断某进程/系统当前是否在放目标歌手的歌。

    实现方负责全部 OS 细节（SMTC、窗口枚举、音频峰值），
    返回值是纯数据结论，核心层只做决策。
    """

    def smtc_line(self) -> str:
        """系统媒体会话原始结论：SMTC_NONE / SMTC_PARTIAL / SMTC_META|歌手|歌名 / 空。"""
        ...

    def scan_player_pids(self) -> set:
        """标题匹配到目标歌手的播放器进程 pid 集合（含隐藏窗口）。"""
        ...

    def process_peak(self, pids: set) -> float | None:
        """这些进程的音频输出峰值（0~1）；读不到返回 None。"""
        ...


@runtime_checkable
class TaskScheduler(Protocol):
    """"每小时自动查余额"的计划任务适配器。"""

    def enabled(self) -> bool:
        ...

    def set_enabled(self, enable: bool, hours: int = 1) -> tuple:
        """返回 (是否成功, 消息)。"""
        ...


@runtime_checkable
class AutostartStore(Protocol):
    """开机自启（注册表 Run 键）适配器。"""

    def enabled(self) -> bool:
        ...

    def set_enabled(self, enable: bool) -> bool:
        ...


@runtime_checkable
class BootIdentity(Protocol):
    """开机签名提供者：用于判断"本次开机后第一次启动"。"""

    def signature(self) -> str:
        """返回本次开机的唯一签名（如系统启动时间）；拿不到返回空串。"""
        ...


@runtime_checkable
class AlertStore(Protocol):
    """余额提醒的本地暂存队列（跨进程文件中转）。"""

    def read(self, max_age: float) -> list:
        ...

    def append(self, text: str) -> None:
        ...

    def clear(self) -> None:
        ...


@runtime_checkable
class FontProvider(Protocol):
    """UI 字体加载器：size → PIL ImageFont。"""

    def __call__(self, size: int):
        ...
