# -*- coding: utf-8 -*-
"""余额 / 天气功能的离线自检。

不开窗口，不碰注册表，只做三件事：
  1. 打一遍接口（天气走真实网络，余额只验证报错路径）
  2. 验证多行气泡渲染，并确认气泡出现时鸟在屏幕上不位移
  3. 把三种状态拼成一张对比图，方便肉眼检查

用法：
    python tools/test_info.py
产物：
    assets/_bubble_preview.png
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

import minbird_info as mi  # noqa: E402
import minbird_pet as mp  # noqa: E402

log: list[str] = []


def p(*parts) -> None:
    line = " ".join(str(x) for x in parts)
    log.append(line)
    print(line)


def main() -> int:
    # --- 1. 天气 ---
    try:
        text, city = mi.fetch_weather("")
        p("[天气] 城市 =", city)
        p("[天气]\n" + text)
    except Exception as exc:
        p("[天气] 失败:", repr(exc))
        traceback.print_exc()

    # --- 2. 余额的两条失败路径 ---
    try:
        mi.fetch_balance("")
    except Exception as exc:
        p("[余额·空key] 预期报错:", repr(exc))
    try:
        mi.fetch_balance("sk-invalid-test-key")
        p("[余额·坏key] 居然成功了？这不合理")
    except Exception as exc:
        p("[余额·坏key] 预期报错:", repr(exc))

    # --- 3. 渲染 + 位移检查 ---
    sprite_path = mp.find_asset(mp.SPRITE_CANDIDATES)
    if not sprite_path:
        p("[渲染] 找不到宠物图")
        return 1
    sprite = Image.open(sprite_path).convert("RGBA")
    sprite = sprite.crop(sprite.getchannel("A").getbbox() or (0, 0, *sprite.size))
    pet = mp.Pet(sprite, argparse.Namespace(size=168, walk=True))

    pet.bubble_text = ""
    plain = pet.compose()
    pos_plain = pet.window_pos()

    pet.say("DeepSeek 余额\n余额 ¥9.98\n充值 ¥9.98 · 赠送 ¥0.00\n快见底了，该充值了", 999)
    bal = pet.compose()
    p("[渲染] 余额帧 =", bal.size, "窗口位置 =", pet.window_pos())

    pet.say("山东济南 · 晴间少云 30°\n湿度29% 风12km/h\n"
            "今日 21°~30° 阴 雨20%\n明日 21°~32° 阴\n"
            "紫外线 6（强）\n记得带伞！", 999)
    wth = pet.compose()
    pos_wth = pet.window_pos()
    p("[渲染] 天气帧 =", wth.size, "窗口位置 =", pos_wth)

    shift = (abs(pos_plain[0] - pos_wth[0]), abs(pos_plain[1] - pos_wth[1]))
    p("[位移] 无气泡 -> 天气气泡，窗口偏移 =", shift,
      "OK" if max(shift) <= 1 else "!! 鸟跑了，画布居中算错了")

    cw = max(f.width for f in (plain, bal, wth))
    ch = max(f.height for f in (plain, bal, wth))
    sheet = Image.new("RGBA", (cw * 3, ch), (238, 240, 244, 255))
    for i, f in enumerate((plain, bal, wth)):
        sheet.alpha_composite(f, (i * cw + (cw - f.width) // 2, ch - f.height))
    out = os.path.join(ROOT, "assets", "_bubble_preview.png")
    sheet.convert("RGB").save(out)
    p("[产物]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
