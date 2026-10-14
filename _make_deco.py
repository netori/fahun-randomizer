# -*- coding: utf-8 -*-
"""把 AI 生图裁成程序能用的装饰件 → _assets/deco/

三条处理原则（第一版没做好，重做）：
* 金线画（装饰条 / 页签图标）：黑底要**真的**变透明 —— 生成图的黑不是纯黑（约 #0a0a0a），
  直接拿亮度当 alpha 会留下一层灰底方块；要先把低亮度**砍掉**再拉曲线。
* 插画（空状态）：转透明会脏 —— 改成"黑点抬到窗口底色 + 椭圆羽化"，让它融进背景，不出方块边。
* 每件出 1× 与 2× 两档（程序按屏幕缩放挑），图标另出 .ico 给 exe 用。
"""
import io
import os
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

SRC = "dsh-image-gen"
OUT = os.path.join("_assets", "deco")
BG = (26, 23, 20)          # #1a1714 窗口底
os.makedirs(OUT, exist_ok=True)


def load(name):
    return Image.open(os.path.join(SRC, name)).convert("RGB")


def content_box(im, thresh=20):
    g = im.convert("L").point(lambda v: 255 if v > thresh else 0)
    return g.getbbox()


def keyed(im, lo=26, boost=1.7):
    """黑底 → 真透明：低于 lo 的亮度归零，其余拉曲线"""
    r, g, b = im.split()
    a = ImageChops.lighter(ImageChops.lighter(r, g), b)
    a = a.point(lambda v: 0 if v <= lo else min(255, int((v - lo) * boost)))
    out = im.convert("RGBA")
    out.putalpha(a)
    return out


def onto_bg(im, bg=BG, feather=0.34, boost=1.45, floor=14):
    """插画融进窗口底色：先削掉近黑 + 提亮主体，再把黑点抬到底色，最后椭圆羽化。

    顺序要紧：先提亮再抬黑点的话，背景会被抬得比窗口底色亮，又露出一个方块。"""
    im = im.convert("RGB")
    r, g, b = im.split()

    def ch(v, bgv):
        if v <= floor:
            v = 0
        else:
            v = min(255, int((v - floor) * 255 / (255 - floor) * boost))
        return bgv + (255 - bgv) * v // 255

    r = r.point(lambda v: ch(v, bg[0]))
    g = g.point(lambda v: ch(v, bg[1]))
    b = b.point(lambda v: ch(v, bg[2]))
    lifted = Image.merge("RGB", (r, g, b))
    flat = Image.new("RGB", im.size, bg)
    m = Image.new("L", im.size, 0)
    w, h = im.size
    ins = int(min(w, h) * feather)
    ImageDraw.Draw(m).ellipse((ins, ins, w - ins, h - ins), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(radius=min(w, h) * 0.10))
    return Image.composite(lifted, flat, m)


def save_pair(img, name, note=""):
    w, h = img.size
    img.save(os.path.join(OUT, f"{name}.png"))
    img.resize((w * 2, h * 2), Image.LANCZOS).save(os.path.join(OUT, f"{name}@2x.png"))
    print(f"  {name:14s} {w}x{h}（2× {w*2}x{h*2}）  {note}")


# ── 1) 窗口 / exe 图标 ──
sig = load("image-c8f6b0d5.png")
sig = sig.crop(content_box(sig, 24))
side = max(sig.size)
pad = Image.new("RGB", (side, side), (8, 7, 6))
pad.paste(sig, ((side - sig.size[0]) // 2, (side - sig.size[1]) // 2))
icon = pad.resize((256, 256), Image.LANCZOS)
icon.save(os.path.join(OUT, "icon.png"))


def _core(size, zoom, mask_r, boost=1.15, contrast=1.10):
    """小尺寸专用：把**中心徽记**放大 + 圆形遮罩 + 提亮。

    为什么不能只把 256 那张缩小：华丽外圈在 16/24/32 px 会糊成一团暗金，
    而 Explorer 列表 / 桌面快捷方式最常用的正是这几档（2026-10-14 作者反馈）。
    圆形遮罩是为了让"被裁断的外圈"不在四角留下碎片。
    """
    box = int(256 * (1 - zoom) / 2)
    im = icon.crop((box, box, 256 - box, 256 - box)).resize((256, 256), Image.LANCZOS)
    m = Image.new("L", (256, 256), 0)
    r = int(256 * mask_r)
    ImageDraw.Draw(m).ellipse((128 - r, 128 - r, 128 + r, 128 + r), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(2.0))
    im = Image.composite(im, Image.new("RGB", (256, 256), (8, 7, 6)), m)
    im = ImageEnhance.Brightness(im).enhance(boost)
    im = ImageEnhance.Contrast(im).enhance(contrast)
    return im.resize((size, size), Image.LANCZOS)


def save_ico(entries, path):
    """自己写 ICO：PIL 只能把**同一张图**缩成多档，而我们要给小尺寸换一套画。

    每档用 PNG 载荷（现代 Windows 全认），256 在目录里记作 0。
    """
    import struct
    blobs = []
    for size, im in entries:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append((size, buf.getvalue()))
    n = len(blobs)
    out = bytearray(struct.pack("<HHH", 0, 1, n))
    offset = 6 + 16 * n
    tail = b""
    for size, data in blobs:
        d = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", d, d, 0, 0, 1, 32, len(data), offset + len(tail))
        tail += data
    out += tail
    with open(path, "wb") as f:
        f.write(bytes(out))


# 大尺寸用原徽记（好看），小尺寸换成中心徽记的放大版（看得清）
save_ico([(256, icon), (128, icon), (64, icon),
          (48, _core(48, 0.62, 0.47)), (32, _core(32, 0.62, 0.47)),
          (24, _core(24, 0.56, 0.46)), (16, _core(16, 0.56, 0.46))],
         os.path.join(OUT, "app.ico"))
print("  icon.png / app.ico  256x256（7 档；16~48 用中心徽记放大版）")

# ── 2) 标题栏装饰条 ──
orn = load("image-e03a8ba9.png")
orn = orn.crop(content_box(orn, 24))
w, h = orn.size
band_h = max(26, int(h * 0.52))
top = max(0, (h - band_h) // 2)
band = orn.crop((0, top, w, top + band_h))
band = band.resize((360, max(20, int(360 * band_h / w))), Image.LANCZOS)
save_pair(keyed(band), "divider", "金藤蔓（透明底，放哪都干净）")

# ── 3) 页签图标：齿轮 / 书卷 ──
sheet = load("image-c4ab3a1e.png")
w, h = sheet.size
for crop, name in ((sheet.crop((0, 0, w // 2, h)), "tab_settings"),
                   (sheet.crop((w // 2, 0, w, h)), "tab_library")):
    crop = crop.crop(content_box(crop, 20))
    side = max(crop.size)
    sq = Image.new("RGB", (side, side), (0, 0, 0))
    sq.paste(crop, ((side - crop.size[0]) // 2, (side - crop.size[1]) // 2))
    save_pair(keyed(sq.resize((22, 22), Image.LANCZOS)), name, "页签小图标")

# ── 4) 空状态插画 ──
book = load("image-424c71d2.png")
book = book.crop(content_box(book, 16))
side = max(book.size)
sq = Image.new("RGB", (side, side), (0, 0, 0))
sq.paste(book, ((side - book.size[0]) // 2, (side - book.size[1]) // 2))
save_pair(onto_bg(sq.resize((260, 260), Image.LANCZOS)), "empty_plans", "空库插画（融进底色）")

print("\n目录:", os.path.abspath(OUT))
for f in sorted(os.listdir(OUT)):
    print(f"  {f:22s} {os.path.getsize(os.path.join(OUT, f)) / 1024:.1f} KB")
