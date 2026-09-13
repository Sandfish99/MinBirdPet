import sys
from PIL import Image

p = sys.argv[1]
img = Image.open(p)
print("mode:", img.mode, "size:", img.size)
img = img.convert("RGBA")
a = img.getchannel("A")
print("alpha min/max:", a.getextrema())
print("alpha bbox:", a.getbbox())
# report corner alpha values
w, h = img.size
for name, xy in (("TL", (0, 0)), ("TR", (w - 1, 0)), ("BL", (0, h - 1)), ("BR", (w - 1, h - 1)), ("C", (w // 2, h // 2))):
    print(name, img.getpixel(xy))
hist = a.histogram()
print("fully transparent px:", hist[0], "fully opaque px:", hist[255], "total:", w * h)
