# -*- coding: utf-8 -*-
"""把待确认模型的贴图拼成一张总览图（带模型号），供人/agent 一眼看长相。

用法：python chr_sheet.py --from-review        # models_to_review.csv 里的模型
      python chr_sheet.py c2030 c2110          # 指定模型
产出：investigation/chr_peek/_sheet.png（网格，每格 = 某模型最大的一张贴图）
"""
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tpf_extract as TE                                            # noqa: E402

OUT = TE.OUT


def _is_normal_or_mask(im):
    """排掉法线图与遮罩：法线图整片偏蓝紫（B 明显大于 R），遮罩图偏黄绿（R≈G 且都高）

    第一版直接取"最大的那张"，结果大多是法线图（蓝紫），根本看不出长相 —— 这里改成挑基础色。
    """
    px = list(im.resize((24, 24)).getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    if b > r + 25 and b > 90:                 # 蓝紫 → 法线
        return True
    if g > r + 20 and g > b + 40:             # 黄绿 → 粗糙度/遮罩
        return True
    if r < 18 and g < 18 and b < 18:          # 纯黑（很多是 emissive 掩码）
        return True
    if min(r, g, b) > 200:                    # 纯白
        return True
    return False


def biggest_png(model):
    """挑一张最像**基础色**的贴图（分辨率大 + 不是法线/遮罩）"""
    from PIL import Image
    best, fallback = None, None
    for i in range(40):
        p = os.path.join(OUT, "%s_%02d.png" % (model, i))
        if not os.path.isfile(p):
            continue
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        area = im.width * im.height
        if fallback is None or area > fallback[2]:
            fallback = (p, im, area)
        if _is_normal_or_mask(im):
            continue
        if best is None or area > best[2]:
            best = (p, im, area)
    return (best or fallback) and ((best or fallback)[0], (best or fallback)[1])


def main(argv):
    from PIL import Image, ImageDraw
    if "--from-review" in argv:
        csvp = os.path.normpath(os.path.join(HERE, os.pardir, "models_to_review.csv"))
        models = [r["model"] for r in csv.DictReader(open(csvp, encoding="utf-8-sig"))]
    else:
        models = [a for a in argv if not a.startswith("--")]
    cell, pad, cols = 192, 22, 8
    rows = (len(models) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + pad)), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    n_ok = 0
    for k, m in enumerate(models):
        got = TE.extract(m) if not biggest_png(m) else None
        b = biggest_png(m)
        x, y = (k % cols) * cell, (k // cols) * (cell + pad)
        draw.text((x + 6, y + 4), m, fill=(230, 230, 235))
        if not b:
            draw.text((x + 6, y + 80), "（没解出贴图）", fill=(200, 120, 120))
            continue
        im = b[1].copy()
        im.thumbnail((cell - 8, cell - 16))
        sheet.paste(im, (x + 4, y + pad - 4))
        n_ok += 1
    p = os.path.join(OUT, "_sheet.png")
    sheet.save(p)
    print("总览图 →", p, "｜%d 格，其中 %d 格有贴图" % (len(models), n_ok))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
