# -*- coding: utf-8 -*-
"""设置项注册表（核心层，纯逻辑）。

PowerToys 模式的声明式注册表：每个设置项一条声明，UI 渲染、持久化校验、
搜索过滤、恢复默认全部由注册表驱动。核心层不持有 OS 引用——
"应用生效"通过 apply 键由应用层分发（app.apply_setting）。
"""
from __future__ import annotations

from dataclasses import dataclass

CAT_PET, CAT_BEHAVIOR, CAT_POMO, CAT_LOOK, CAT_ADV = (
    "宠物", "行为", "番茄钟", "外观", "高级")

# type: bool | int | str | enum(choices) | action（动作按钮，不持久化）


@dataclass(frozen=True)
class SettingItem:
    key: str            # 配置键；action 项为动作名
    category: str
    type: str
    label: str
    default: object = None
    choices: tuple = ()          # enum 的取值（display 列表）
    choices_map: tuple = ()      # 与 choices 等长的实际值（缺省同 choices）
    hint: str = ""
    apply: str = ""              # 生效分发键；空 = 只落盘（重启生效）
    restart: bool = False        # True = 明确提示需重启


ITEMS = (
    # ---- 宠物 ----
    SettingItem("size", CAT_PET, "enum", "缩放",
                default=168, choices=("小", "中", "大", "特大"),
                choices_map=(118, 168, 232, 300), apply="size"),
    SettingItem("opacity", CAT_PET, "enum", "透明度",
                default=100, choices=("30%", "50%", "70%", "85%", "100%"),
                choices_map=(30, 50, 70, 85, 100), apply="opacity"),
    SettingItem("topmost", CAT_PET, "bool", "总在最前",
                default=True, apply="topmost"),
    SettingItem("click_through", CAT_PET, "bool", "点击穿透（整只幽灵化，仅托盘可操作）",
                default=False, apply="click_through"),
    SettingItem("lock_position", CAT_PET, "bool", "锁定位置（禁止拖拽）",
                default=False, apply="lock_position"),
    # ---- 行为 ----
    SettingItem("autostart", CAT_BEHAVIOR, "bool", "开机自启",
                default=False, apply="autostart"),
    SettingItem("dnd", CAT_BEHAVIOR, "bool", "勿扰模式（不说话不蹦跶）",
                default=False, apply="dnd"),
    SettingItem("fullscreen_hide", CAT_BEHAVIOR, "bool", "全屏时自动躲起来",
                default=True, apply="fullscreen_hide"),
    SettingItem("window_walk", CAT_BEHAVIOR, "bool", "能在窗口上走",
                default=True, apply="window_walk"),
    # ---- 番茄钟 ----
    SettingItem("pomo_focus_min", CAT_POMO, "int", "专注时长（分钟）",
                default=25, apply="pomodoro"),
    SettingItem("pomo_short_min", CAT_POMO, "int", "短休时长（分钟）",
                default=5, apply="pomodoro"),
    SettingItem("pomo_long_min", CAT_POMO, "int", "长休时长（分钟）",
                default=15, apply="pomodoro"),
    SettingItem("pomo_interval", CAT_POMO, "int", "长休间隔（几个专注后长休）",
                default=4, apply="pomodoro"),
    SettingItem("pomo_auto_next", CAT_POMO, "bool", "自动开始下一阶段",
                default=True, apply="pomodoro"),
    # ---- 外观 ----
    SettingItem("theme", CAT_LOOK, "enum", "气泡主题",
                default="跟随系统", choices=("跟随系统", "浅色", "深色"),
                apply="theme"),
    # ---- 高级（动作 + 提示）----
    SettingItem("act_export_log", CAT_ADV, "action", "导出日志", apply="export_log"),
    SettingItem("act_backup", CAT_ADV, "action", "立即备份配置", apply="backup"),
    SettingItem("act_restore", CAT_ADV, "action", "从备份恢复配置", apply="restore_bak"),
    SettingItem("act_export", CAT_ADV, "action", "导出配置 JSON", apply="export_cfg"),
    SettingItem("act_import", CAT_ADV, "action", "导入配置 JSON", apply="import_cfg"),
    SettingItem("act_reset", CAT_ADV, "action", "恢复全部默认值", apply="reset_all"),
)

BY_KEY = {i.key: i for i in ITEMS}
CATEGORIES = (CAT_PET, CAT_BEHAVIOR, CAT_POMO, CAT_LOOK, CAT_ADV)


def items(category: str | None = None) -> tuple:
    """全部设置项；可按分类过滤（动作项归入所在分类）。"""
    return tuple(i for i in ITEMS if category is None or i.category == category)


def categories() -> tuple:
    return CATEGORIES


def search(query: str) -> tuple:
    """按关键字过滤（匹配标签/键/分类，大小写不敏感）。"""
    q = (query or "").strip().lower()
    if not q:
        return ITEMS
    return tuple(i for i in ITEMS
                 if q in i.label.lower() or q in i.key.lower()
                 or q in i.category.lower())


def defaults() -> dict:
    """全部持久化设置的默认值（不含 action）。"""
    return {i.key: i.default for i in ITEMS if i.type != "action"}


def coerce(item: SettingItem, value):
    """把外部值规范化为该设置项的类型；非法值回退默认。"""
    if item.type == "bool":
        return bool(value)
    if item.type == "int":
        try:
            v = int(float(value))
        except (TypeError, ValueError):
            return item.default
        lo, hi = 1, 600
        if item.key == "size":
            lo, hi = 60, 600
        elif item.key == "opacity":
            lo, hi = 10, 100
        elif item.key.startswith("pomo_"):
            lo, hi = 1, 180
        return min(max(v, lo), hi)
    if item.type == "enum":
        m = item.choices_map or item.choices
        if value in m:
            return value
        if value in item.choices:
            return m[item.choices.index(value)]
        return item.default
    if item.type == "str":
        return str(value) if value is not None else item.default
    return value


def normalized_defaults() -> dict:
    """默认值字典（enum 取实际值）。"""
    out = {}
    for i in ITEMS:
        if i.type == "action":
            continue
        out[i.key] = coerce(i, i.default)
    return out
