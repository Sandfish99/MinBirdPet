# -*- coding: utf-8 -*-
"""音乐匹配决策（核心层，纯逻辑，零 OS 依赖）。"""
from __future__ import annotations

AESPA_KEYS = ("aespa", "에스파")


def match_aespa(artist: str, title: str) -> bool:
    hay = f"{artist} {title}".lower()
    return any(k in hay for k in AESPA_KEYS)


