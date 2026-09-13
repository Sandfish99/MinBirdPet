# -*- coding: utf-8 -*-
"""从绿幕视频生成桌宠序列帧素材（spritesheet + manifest）。

用法：
    python tools/make_seq.py <绿幕视频路径> [--store-h 320] [--t-lo 30] [--t-hi 95]

流程：去水印（角落非绿像素按绿幕填充）→ 逐帧色键抠像（软边缘 + 去绿边）
→ 搜索无缝循环点 → 统一裁切框 → 打包 assets/seq/sheet.png + manifest.json。

依赖：pip install imageio imageio-ffmpeg numpy（仅重新生成素材时需要，
仓库里的 sheet.png 已经生成好，普通用户不需要装）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import imageio.v3 as iio
import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEQ_DIR = os.path.join(BASE_DIR, "assets", "seq")

# 两处水印所在的大致角落区域（1280×720）：左上「AI生成」、右下「即梦AI」。
# 区域内所有"不够绿"的像素都会被绿幕色填充，鸟本体不会进入这些角落。
WM_RECTS = [(0, 0, 170, 105), (950, 575, 1280, 720)]


def greenness(rgb: np.ndarray) -> np.ndarray:
    """绿幕度 = G - max(R, B)。纯绿幕很大，灰白/暖色 ≈ 0 上下。"""
    return rgb[:, :, 1].astype(np.int16) - np.maximum(
        rgb[:, :, 0], rgb[:, :, 2]).astype(np.int16)


def kill_watermarks(rgb: np.ndarray, fill: np.ndarray) -> np.ndarray:
    """把水印区域里非绿的像素换成绿幕色（这些区域最终都会被抠掉）。"""
    out = rgb.copy()
    for x0, y0, x1, y1 in WM_RECTS:
        region = out[y0:y1, x0:x1]
        mask = greenness(region) < 40
        region[mask] = fill
    return out


def chroma_key(rgb: np.ndarray, t_lo: int, t_hi: int) -> Image.Image:
    """色键抠像：软边缘 alpha + 去绿边（despill）+ 水印区 alpha 清零。"""
    g = greenness(rgb)
    alpha = np.clip((t_hi - g) / float(t_hi - t_lo), 0.0, 1.0)
    out = rgb.astype(np.float32)
    # despill：凡是偏绿的像素，把 G 压回 max(R,B)+12，去掉边缘绿边
    spill = g > 0
    cap = np.maximum(out[:, :, 0], out[:, :, 2]) + 12.0
    out[:, :, 1] = np.where(spill, np.minimum(out[:, :, 1], cap), out[:, :, 1])
    a = alpha * 255.0
    # 半透明水印混绿后绿度超过填充阈值会留残影；鸟不会进这两个角落，直接清零
    for x0, y0, x1, y1 in WM_RECTS:
        a[y0:y1, x0:x1] = 0.0
    rgba = np.dstack([out, a]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def frame_feature(img: Image.Image) -> np.ndarray:
    """循环搜索用的降采样特征（灰度 + alpha）。"""
    small = img.resize((64, 64), Image.BILINEAR)
    arr = np.asarray(small, dtype=np.float32) / 255.0
    gray = arr[:, :, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return np.concatenate([gray.ravel(), (arr[:, :, 3] * 2.0).ravel()])


def find_loop(feats: np.ndarray, fps: float, n: int) -> tuple:
    """返回 (i, j)：frames[i:j] 是差异最小的无缝循环。"""
    best = None
    # 循环至少 2 秒：眨眼约每 2 秒一次，太短的循环会把眨眼切掉
    lo, hi = int(fps * 2.0), int(fps * 3.9)   # 循环长度 2.0s ~ 3.9s
    for i in range(2, n - lo):
        for j in range(i + lo, min(n, i + hi + 1)):
            d = float(np.mean((feats[i] - feats[j]) ** 2))
            if best is None or d < best[0]:
                best = (d, i, j)
    return best[1], best[2]


def main() -> int:
    ap = argparse.ArgumentParser(description="绿幕视频 → 桌宠序列帧素材")
    ap.add_argument("video", help="绿幕视频路径")
    ap.add_argument("--store-h", type=int, default=320,
                    help="素材帧存储高度（默认 320，需大于最大显示档 300）")
    ap.add_argument("--t-lo", type=int, default=30, help="色键全透明阈值")
    ap.add_argument("--t-hi", type=int, default=95, help="色键全不透明阈值")
    ap.add_argument("--fps", type=float, default=None, help="手动指定帧率")
    args = ap.parse_args()

    print("reading", args.video)
    frames_rgb = [np.asarray(f) for f in iio.imiter(args.video)]
    n = len(frames_rgb)
    meta_fps = args.fps or float(iio.immeta(args.video)["fps"])
    print(f"frames={n} fps={meta_fps:.2f}")

    # 每帧的绿幕填充色 = 整帧中位数（画面大部分是绿幕）
    keyed: list[Image.Image] = []
    for idx, rgb in enumerate(frames_rgb):
        fill = np.median(rgb.reshape(-1, 3), axis=0)
        rgb = kill_watermarks(rgb, fill)
        keyed.append(chroma_key(rgb, args.t_lo, args.t_hi))
        if (idx + 1) % 24 == 0:
            print(f"  keyed {idx + 1}/{n}")
    frames_rgb = None

    print("searching loop ...")
    feats = np.stack([frame_feature(k) for k in keyed])
    i0, j0 = find_loop(feats, meta_fps, n)
    loop = keyed[i0:j0]
    ln = len(loop)
    print(f"loop frames[{i0}:{j0}] len={ln} ({ln / meta_fps:.2f}s)")

    # 统一裁切框：循环内所有帧 alpha>8 的并集，四周留 6px
    boxes = [k.getchannel("A").point(lambda a: 255 if a > 8 else 0)
             .getbbox() for k in loop]
    boxes = [b for b in boxes if b]
    x0 = max(0, min(b[0] for b in boxes) - 6)
    y0 = max(0, min(b[1] for b in boxes) - 6)
    x1 = max(b[2] for b in boxes) + 6
    y1 = min(keyed[0].height, max(b[3] for b in boxes) + 6)
    x1, y1 = min(x1, keyed[0].width), min(y1, keyed[0].height)
    print("crop box:", (x0, y0, x1, y1))

    crop = [k.crop((x0, y0, x1, y1)) for k in loop]
    ch = args.store_h
    cw = round(crop[0].width * ch / crop[0].height / 2) * 2
    crop = [k.resize((cw, ch), Image.LANCZOS) for k in crop]

    cols = int(np.ceil(np.sqrt(ln)))
    rows = int(np.ceil(ln / cols))
    sheet = Image.new("RGBA", (cols * cw, rows * ch), (0, 0, 0, 0))
    for idx, k in enumerate(crop):
        r, c = divmod(idx, cols)
        sheet.paste(k, (c * cw, r * ch))
    os.makedirs(SEQ_DIR, exist_ok=True)
    sheet.save(os.path.join(SEQ_DIR, "sheet.png"), optimize=True)

    manifest = {
        "fps": round(meta_fps, 3),
        "frames": ln,
        "frame_w": cw,
        "frame_h": ch,
        "cols": cols,
        "loop_source": f"frames[{i0}:{j0}] of {n}",
        "note": "绿幕视频自动生成：tools/make_seq.py",
    }
    with open(os.path.join(SEQ_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # 预览图：6 帧白底 + 6 帧暗底，供人工检查抠像质量
    picks = [crop[int(k * ln / 6)] for k in range(6)]
    ph = 240
    pw = round(cw * ph / ch)
    strip_w = pw * 6 + 7 * 8
    preview = Image.new("RGB", (strip_w, ph * 2 + 24), (255, 255, 255))
    dark = Image.new("RGB", (strip_w, ph), (32, 34, 40))
    preview.paste(dark, (0, ph + 24))
    for k, p in enumerate(picks):
        s = p.resize((pw, ph), Image.LANCZOS)
        x = 8 + k * (pw + 8)
        preview.paste(s, (x, 8), s)
        preview.paste(s, (x, ph + 16), s)
    preview.save(os.path.join(BASE_DIR, "assets", "_seq_preview.png"))

    sz = os.path.getsize(os.path.join(SEQ_DIR, "sheet.png")) / 1e6
    print(f"sheet: {sheet.size}, {sz:.1f} MB -> assets/seq/")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
