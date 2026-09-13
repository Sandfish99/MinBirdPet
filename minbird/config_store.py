# -*- coding: utf-8 -*-
"""配置文件存储（应用层基础设施）：原子写、.bak 备份恢复、版本迁移。

设计要点：
- 写入永远是"临时文件 + os.replace"，主路径上不会出现写了一半的 JSON
- 每次成功写入前，把上一个"可解析的"配置挪到 .bak（损坏文件不备份，避免污染）
- 读取时若主文件损坏且 .bak 可用：自动用备份顶上，坏文件改名 .broken 留证
- 迁移走 config_version 版本号，缺字段/坏类型由 defaults + 规范化兜底
"""
from __future__ import annotations

import json
import os

CONFIG_VERSION = 1

# 需要数值规范化的字段（外部手改可能写成字符串）
_NUMERIC_FIELDS = {"balance_step": float, "balance_check_minutes": float,
                   "size": int, "x": float, "y": float}


class ConfigStore:
    def __init__(self, path: str, defaults=(), log=None):
        self.path = path
        self.defaults = list(defaults)
        self._log = log or (lambda *a: None)

    # -- 读 -------------------------------------------------------------
    def read(self) -> tuple[dict, bool]:
        """返回 (data, broken)；broken=True 表示主文件 JSON 损坏。"""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return {}, False
        try:
            data = json.loads(raw)
        except ValueError:
            return {}, True
        return (data if isinstance(data, dict) else {}), False

    def read_backup(self) -> dict | None:
        try:
            with open(self.path + ".bak", "r", encoding="utf-8") as fh:
                data = json.loads(fh.read())
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def load_with_recovery(self) -> tuple[dict, bool]:
        """启动时读取。主文件损坏时**不自动覆盖**（尊重"坏配置绝不覆盖"契约），
        只返回 broken 标记；是否用 .bak 恢复由调用方（安全模式）显式决定。
        """
        data, broken = self.read()
        if not broken:
            return data, False
        self._log("config.json 无法解析；.bak",
                  "可用" if self.read_backup() is not None else "也不可用")
        return {}, True

    def restore_from_backup(self) -> bool:
        """显式恢复：坏主文件改名 .broken 留证，把 .bak 写回主路径。"""
        bak = self.read_backup()
        if bak is None:
            return False
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".broken")
        except OSError:
            pass
        ok = self.write_atomic(bak)
        if ok:
            self._log("已从 .bak 恢复配置", len(bak), "个字段")
        return ok

    # -- 迁移 ------------------------------------------------------------
    def migrate(self, data: dict) -> tuple[dict, bool]:
        """按 config_version 逐级迁移；返回 (data, changed)。"""
        changed = False
        try:
            version = int(data.get("config_version", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        if version < 1:
            for key, cast in _NUMERIC_FIELDS.items():
                if key in data:
                    try:
                        data[key] = cast(float(data[key]))
                    except (TypeError, ValueError):
                        del data[key]
                    changed = True
            data["config_version"] = CONFIG_VERSION
            changed = True
        return data, changed

    def ensure_defaults(self, data: dict) -> tuple[dict, bool]:
        changed = False
        for key, default in self.defaults:
            if key not in data:
                data[key] = default
                changed = True
        return data, changed

    # -- 写 --------------------------------------------------------------
    def write_atomic(self, data: dict) -> bool:
        """临时文件 + os.replace 原子替换；写前把可解析的旧配置备份为 .bak。"""
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        json.load(fh)  # 只有可解析的旧配置才值得备份
                    os.replace(self.path, self.path + ".bak")
                except (OSError, ValueError):
                    pass
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False
