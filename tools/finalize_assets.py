"""Finalise the matted cut-out into desktop-pet assets."""
import os
import sys

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(BASE, "assets")
SRC = os.path.join(ASSETS, "minbird_matted_source.png")


def main():
    img = Image.open(SRC).convert("RGBA")
    a = img.getchannel("A")
    bbox = a.getbbox()
    pad = 4
    w, h = img.size
    bbox = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(w, bbox[2] + pad),
        min(h, bbox[3] + pad),
    )
    sprite = img.crop(bbox)
    out = os.path.join(ASSETS, "minbird.png")
    sprite.save(out)
    print("sprite:", out, sprite.size)

    # mirrored copy for walking left
    sprite.transpose(Image.FLIP_LEFT_RIGHT).save(os.path.join(ASSETS, "minbird_flip.png"))

    # tray / window icon
    icon_src = sprite.copy()
    icon_src.thumbnail((256, 256), Image.LANCZOS)
    sq = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    sq.paste(icon_src, ((256 - icon_src.width) // 2, (256 - icon_src.height) // 2), icon_src)
    sq.save(os.path.join(ASSETS, "minbird.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon saved")

    # previews on light & dark plates to judge the cut edge
    for name, bg in (("_preview_light.png", (245, 246, 248, 255)), ("_preview_dark.png", (32, 34, 40, 255))):
        plate = Image.new("RGBA", sprite.size, bg)
        plate.alpha_composite(sprite)
        plate.convert("RGB").save(os.path.join(ASSETS, name))
    print("previews saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
