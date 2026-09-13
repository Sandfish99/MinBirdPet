# -*- coding: utf-8 -*-
"""更新/回滚交换（平台适配层，仅打包 exe 运行时生效）。

离线更新约定（不引入任何联网更新器）：
1. 用户把新版下载为 exe 同目录下的 ``MinBirdPet_new.exe``
2. 启动时检测到 pending → 当前 exe 改名为 ``MinBirdPet_prev.exe``
   （Windows 允许改名运行中的 exe，但不允许覆盖/删除），
   再把 pending 原子替换为当前名 → 本次仍跑旧代码，下次启动即新版
3. 新版有问题：``MinBirdPet.exe --rollback`` 把 prev 换回来
"""
from __future__ import annotations

import os
import sys

PENDING_NAME = "MinBirdPet_new.exe"
PREV_NAME = "MinBirdPet_prev.exe"
BAD_NAME = "MinBirdPet_bad.exe"


def _swap_in(cur: str, pending: str, prev: str, log=None) -> bool:
    log = log or (lambda *a: None)
    if not os.path.exists(pending):
        return False
    if os.path.exists(prev):
        try:
            os.remove(prev)
        except OSError as exc:
            log("update: cannot clear old prev:", repr(exc))
            return False
    try:
        os.replace(cur, prev)      # 运行中的 exe 允许改名
        os.replace(pending, cur)   # pending 不被锁定，直接替换
    except OSError as exc:
        log("update swap failed:", repr(exc))
        try:
            if os.path.exists(prev) and not os.path.exists(cur):
                os.replace(prev, cur)  # 尽力把现状恢复回去
        except OSError:
            pass
        return False
    log("update applied; 本次仍跑旧版，下次启动即新版（prev 保留供 --rollback）")
    return True


def _rollback_in(cur: str, prev: str, bad: str, log=None) -> bool:
    log = log or (lambda *a: None)
    if not os.path.exists(prev):
        log("rollback: 没有可回退的 prev 版本")
        return False
    try:
        if os.path.exists(cur):
            if os.path.exists(bad):
                os.remove(bad)
            os.replace(cur, bad)
        os.replace(prev, cur)
    except OSError as exc:
        log("rollback failed:", repr(exc))
        return False
    log("rollback done; 下次启动跑上一个版本")
    return True


def apply_pending_update(log=None) -> bool:
    """启动早期调用：存在 pending 新版就完成交换。仅打包 exe 生效。"""
    if not getattr(sys, "frozen", False):
        return False
    cur = os.path.abspath(sys.executable)
    d = os.path.dirname(cur)
    return _swap_in(cur, os.path.join(d, PENDING_NAME),
                    os.path.join(d, PREV_NAME), log)


def has_prev_version() -> bool:
    """是否存在可回退的 prev 版本（供安全模式提示用）。"""
    if not getattr(sys, "frozen", False):
        return False
    return os.path.exists(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                       PREV_NAME))


def rollback(log=None) -> bool:
    """--rollback 入口。"""
    if not getattr(sys, "frozen", False):
        log = log or (lambda *a: None)
        log("rollback: 仅打包 exe 运行时可用")
        return False
    cur = os.path.abspath(sys.executable)
    d = os.path.dirname(cur)
    return _rollback_in(cur, os.path.join(d, PREV_NAME),
                        os.path.join(d, BAD_NAME), log)
