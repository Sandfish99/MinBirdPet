"""Cut the min-bird meme photo into a transparent-background desktop-pet sprite."""
import os
import sys
from collections import deque

from PIL import Image, ImageFilter, ImageOps

SRC = r"C:\Users\Sendi\Desktop\ocajtzIH6ArhGMaelHPDMEAIGeBtLBAVeEATDQ.webp"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(OUT_DIR, exist_ok=True)


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def flood_remove_bg(img, local_tol=14, global_tol=60):
    """Region-grow from the image border, stopping at colour edges (handles gradients)."""
    w, h = img.size
    px = img.load()
    # global background reference = median of the border ring
    ring = []
    for x in range(w):
        ring.append(px[x, 0])
        ring.append(px[x, h - 1])
    for y in range(h):
        ring.append(px[0, y])
        ring.append(px[w - 1, y])
    ring.sort(key=lambda c: c[0] + c[1] + c[2])
    bg = ring[len(ring) // 2]

    bg_mask = bytearray(w * h)  # 1 = background
    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            q.append((x, y))

    lt = local_tol * local_tol
    gt = global_tol * global_tol
    while q:
        x, y = q.popleft()
        i = y * w + x
        if visited[i]:
            continue
        visited[i] = 1
        c = px[x, y]
        if dist2(c, bg) > gt:
            continue
        bg_mask[i] = 1
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if not visited[j] and dist2(c, px[nx, ny]) <= lt:
                    q.append((nx, ny))
    return bg_mask


def largest_component_keep(mask_obj, w, h):
    """Drop tiny stray blobs left in the foreground mask."""
    seen = bytearray(w * h)
    comps = []
    for start in range(w * h):
        if mask_obj[start] or seen[start]:
            continue
        comp = []
        q = deque([start])
        seen[start] = 1
        while q:
            i = q.popleft()
            comp.append(i)
            x, y = i % w, i // w
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if not seen[j] and not mask_obj[j]:
                        seen[j] = 1
                        q.append(j)
        comps.append(comp)
    if not comps:
        return mask_obj
    big = max(comps, key=len)
    keep = set(big)
    # absorb neighbouring small blobs (antialiasing fragments near the subject)
    for comp in comps:
        if comp is big:
            continue
        if len(comp) < w * h * 0.002:
            for i in comp:
                x, y = i % w, i // w
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and (ny * w + nx) in keep:
                        keep.update(comp)
                        break
                else:
                    continue
                break
    out = bytearray(w * h)
    for i in keep:
        out[i] = 1
    return out


def main():
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size
    print("source size:", img.size)

    bg = flood_remove_bg(img)
    fg = bytearray(1 if not v else 0 for v in bg)
    fg = largest_component_keep(fg, w, h)

    alpha = Image.new("L", (w, h), 0)
    ap = alpha.load()
    for i, v in enumerate(fg):
        if v:
            ap[i % w, i // w] = 255

    # soften: erode 1px then blur, so the old background halo disappears
    alpha = alpha.filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    alpha = ImageOps.autocontrast(alpha)

    out = img.copy()
    out.putalpha(alpha)

    bbox = alpha.getbbox()
    print("subject bbox:", bbox)
    if bbox:
        pad = 6
        bbox = (
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(w, bbox[2] + pad),
            min(h, bbox[3] + pad),
        )
        out = out.crop(bbox)

    path = os.path.join(OUT_DIR, "minbird.png")
    out.save(path)
    print("saved:", path, out.size)

    # preview on a checkerboard-ish dark plate so the cut can be judged
    prev = Image.new("RGBA", out.size, (40, 44, 52, 255))
    prev.alpha_composite(out)
    prev.convert("RGB").save(os.path.join(OUT_DIR, "_preview.png"))
    print("preview saved")


if __name__ == "__main__":
    sys.exit(main())
