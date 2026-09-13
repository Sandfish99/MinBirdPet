# -*- coding: utf-8 -*-
"""日志与崩溃捕获（共享基础设施，仅标准库）。

- log_line：带日期时间戳追加诊断日志；超过 512KB 自动轮转为 .old
- write_crash_report：崩溃现场写入独立文件（保留最近 5 份）
- install_excepthook：主线程 / 子线程未捕获异常统一落盘
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
import time

_seq = itertools.count(1)

LOG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "MinBirdPet")
LOG_PATH = os.path.join(LOG_DIR, "minbird_pet.log")
LOG_MAX_BYTES = 512 * 1024
CRASH_KEEP = 5

_prev_hook = None
_thread_prev_hook = None


def log_line(*parts) -> None:
    """追加一行诊断日志（带日期时间，超限自动轮转）。任何线程任何阶段都可调。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        try:
            if os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
                old = LOG_PATH + ".old"
                if os.path.exists(old):
                    os.remove(old)
                os.replace(LOG_PATH, old)
        except OSError:
            pass
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                     + " ".join(str(p) for p in parts) + "\n")
    except OSError:
        pass


def write_crash_report(kind: str, tb: str) -> str | None:
    """把崩溃现场写成独立文件（crashes/ 下保留最近 CRASH_KEEP 份）。"""
    try:
        cdir = os.path.join(LOG_DIR, "crashes")
        os.makedirs(cdir, exist_ok=True)
        # 秒级时间戳 + 自增序号：同秒内的多次崩溃也不会互相覆盖
        name = f"crash_{time.strftime('%Y%m%d_%H%M%S')}_{next(_seq)}_{kind}.log"
        path = os.path.join(cdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write(f"kind: {kind}\n")
            fh.write(f"python: {sys.version}\n")
            fh.write(f"frozen: {getattr(sys, 'frozen', False)}\n\n")
            fh.write(tb)
        crashes = sorted(f for f in os.listdir(cdir) if f.startswith("crash_"))
        for f in crashes[:-CRASH_KEEP]:
            try:
                os.remove(os.path.join(cdir, f))
            except OSError:
                pass
        return path
    except OSError:
        return None


def install_excepthook() -> None:
    """主线程 / 子线程未捕获异常 → 崩溃文件 + 常规日志（保留原钩子链）。"""
    global _prev_hook, _thread_prev_hook
    import traceback

    def _hook(tp, val, tb):
        write_crash_report("uncaught", "".join(
            traceback.format_exception(tp, val, tb)))
        log_line("FATAL", repr(val))
        if _prev_hook and _prev_hook is not sys.__excepthook__:
            _prev_hook(tp, val, tb)

    def _thread_hook(args):
        write_crash_report("thread", "".join(
            traceback.format_exception(args.exc_type, args.exc_value,
                                       args.exc_traceback)))
        log_line("THREAD-FATAL", getattr(args.exc_type, "__name__", "?"),
                 repr(args.exc_value))
        if _thread_prev_hook and _thread_prev_hook is not threading.__excepthook__:
            _thread_prev_hook(args)

    _prev_hook = sys.excepthook
    _thread_prev_hook = threading.excepthook
    sys.excepthook = _hook
    threading.excepthook = _thread_hook
