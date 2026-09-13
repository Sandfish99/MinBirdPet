# -*- coding: utf-8 -*-
"""Render-cost benchmark for the pet frame pipeline."""
import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PIL import Image  # noqa: E402
import minbird_pet as mp  # noqa: E402

sprite = Image.open(mp.find_asset(mp.SPRITE_CANDIDATES)).convert("RGBA")
sprite = sprite.crop(sprite.getchannel("A").getbbox() or (0, 0, *sprite.size))

for size in (118, 168, 232):
    pet = mp.Pet(sprite, argparse.Namespace(size=size, walk=True, debug=False))
    pet.say("今天也要加油鸭", 999)
    pet.compose()
    n = 60
    t0 = time.perf_counter()
    for i in range(n):
        pet.angle = (i % 20) - 10
        pet.compose()
    t1 = time.perf_counter()
    t2 = time.perf_counter()
    for i in range(n):
        mp.to_premul_bgra(pet.compose())
    t3 = time.perf_counter()
    print(f"size {size:4d}  canvas {pet.canvas_w}x{pet.canvas_h}"
          f"  compose {1000*(t1-t0)/n:.2f} ms/frame"
          f"  compose+premul {1000*(t3-t2)/n:.2f} ms/frame"
          f"  -> max {n/(t3-t2):.0f} fps")
