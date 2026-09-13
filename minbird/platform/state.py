# -*- coding: utf-8 -*-
"""运行时状态持久化（平台适配层）：崩溃连击 / 干净退出的标记文件。"""
from __future__ import annotations

import json
import os


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.loads(fh.read())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, data: dict) -> bool:
    """原子写（临时文件 + replace），自己崩溃也不能弄坏看门狗的判断依据。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
