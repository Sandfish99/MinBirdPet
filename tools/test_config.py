# -*- coding: utf-8 -*-
"""配置文件读写回归测试。

背景（真踩过的坑）：早期 `_save_config()` 用**启动时的内存快照**整体覆盖磁盘，
导致用户刚填好的 API Key，被程序随后任何一次保存（甩鸟 / 切尺寸 / 退出）抹掉。

现在的原则：磁盘是唯一真相源，程序只写自己拥有的运行时字段（size/walk/x/y）。

用法：
    python tools/test_config.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import minbird_pet as mp  # noqa: E402

CFG = mp.CONFIG_PATH
BAK = CFG + ".bak"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, ok, extra))


def read_cfg() -> dict:
    with open(CFG, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_cfg(data: dict) -> None:
    with open(CFG, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def main() -> int:
    original = None
    try:
        os.makedirs(os.path.dirname(CFG), exist_ok=True)
        if os.path.exists(CFG):
            shutil.copy2(CFG, BAK)
            try:
                original = read_cfg()
            except ValueError:
                original = None

        base = {"size": 168, "walk": True, "x": 100.0, "y": 900.0,
                "deepseek_api_key": "", "city": ""}
        write_cfg(base)
        time.sleep(0.02)

        app = mp.MinBirdApp(argparse.Namespace(size=168, walk=True, debug=False))

        # --- 1. 用户在程序运行时用记事本填了 Key ---
        user = dict(base)
        user["deepseek_api_key"] = "sk-test-key-123"
        user["city"] = "济南"
        write_cfg(user)
        time.sleep(0.02)

        # --- 2. 程序内部触发保存（甩鸟/切尺寸/退出都走这里）---
        app.options.walk = False
        app._save_config()

        after = read_cfg()
        check("保存后 API Key 还在",
              after.get("deepseek_api_key") == "sk-test-key-123",
              f"实际={after.get('deepseek_api_key')!r}")
        check("保存后 city 还在",
              after.get("city") == "济南", f"实际={after.get('city')!r}")
        check("运行时字段确实写进去了",
              after.get("walk") is False, f"walk={after.get('walk')!r}")

        # --- 3. 热更新：外部改动不重启也能读到 ---
        user2 = dict(after)
        user2["deepseek_api_key"] = "sk-new-456"
        write_cfg(user2)
        time.sleep(0.02)
        app._watch_config()
        check("外部改动自动重读（不用重启）",
              app.config.get("deepseek_api_key") == "sk-new-456",
              f"实际={app.config.get('deepseek_api_key')!r}")

        # --- 4. JSON 写坏了绝不能覆盖（否则 Key 全丢）---
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write("{ 这不是合法 json")
        time.sleep(0.02)
        app2 = mp.MinBirdApp(argparse.Namespace(size=168, walk=True, debug=False))
        check("坏 JSON 被识别", app2._config_broken is True,
              f"_config_broken={getattr(app2, '_config_broken', None)}")
        app2._save_config()
        with open(CFG, "r", encoding="utf-8") as fh:
            still = fh.read()
        check("坏 JSON 不被程序覆盖", "这不是合法" in still, f"内容={still[:40]!r}")

    finally:
        # 还原用户原本的配置
        if original is not None:
            write_cfg(original)
        elif os.path.exists(CFG):
            try:
                os.remove(CFG)
            except OSError:
                pass
        if os.path.exists(BAK):
            try:
                os.remove(BAK)
            except OSError:
                pass

    lines = []
    failed = 0
    for name, ok, extra in results:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"   {extra}" if extra else ""))
        if not ok:
            failed += 1
    lines.append(f"\n{len(results) - failed}/{len(results)} 通过")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(HERE, "test_config_out.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
