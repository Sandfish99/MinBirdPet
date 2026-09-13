# -*- coding: utf-8 -*-
"""番茄钟/设置注册表单元测试：python tools/test_settings_registry.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minbird.core import settings_registry as sr


def test_search():
    assert len(sr.ITEMS) >= 20
    assert sr.search("").__len__() == len(sr.ITEMS)
    hit = sr.search("番茄")
    assert hit and all(i.category == sr.CAT_POMO for i in hit)
    assert any(i.key == "pomo_focus_min" for i in sr.search("focus"))
    assert sr.search("不存在的设置xyz") == ()
    print("PASS 搜索过滤")


def test_coerce_defaults():
    d = sr.normalized_defaults()
    assert d["size"] == 168 and d["opacity"] == 100 and d["topmost"] is True
    assert d["pomo_focus_min"] == 25 and d["pomo_interval"] == 4
    assert d["theme"] == "跟随系统"
    it = sr.BY_KEY["opacity"]
    assert sr.coerce(it, 250) == 100 and sr.coerce(it, "abc") == 100
    assert sr.coerce(it, "70%") == 70          # enum 显示值 → 实际值
    it = sr.BY_KEY["size"]
    assert sr.coerce(it, "中") == 168 and sr.coerce(it, "特大") == 300
    it = sr.BY_KEY["pomo_focus_min"]
    assert sr.coerce(it, "15") == 15 and sr.coerce(it, 0) == 1   # 钳到下界
    print("PASS 类型规范化/默认值")


def test_apply_mapping():
    # 每个持久化项必须有生效分发键（或声明需重启）
    for i in sr.ITEMS:
        if i.type == "action":
            assert i.apply, f"{i.key} 动作项必须有 apply"
        elif i.type == "str":
            pass  # 字符串项（Key/城市）允许仅落盘，查询时自读
        else:
            assert i.apply, f"{i.key} 缺少 apply 分发键"
    # 动作项必须有 apply
    for i in sr.ITEMS:
        if i.type == "action":
            assert i.apply
    assert sr.BY_KEY["topmost"].apply == "topmost"
    print("PASS 生效分发映射完整")


def main() -> int:
    test_search()
    test_coerce_defaults()
    test_apply_mapping()
    print("== 设置注册表 3/3 通过 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
