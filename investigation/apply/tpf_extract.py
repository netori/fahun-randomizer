# -*- coding: utf-8 -*-
"""TPF 布局确认 + 把模型贴图导成 PNG（用来"看长相"）。

布局（用已知模型反推、并用 DDS 魔数验证）：
  0x00 'TPF\\0'  0x04 数据大小  0x08 贴图数  0x0C 平台/标志  0x10 头大小(=第一条数据起点)
  0x20 起，每条 0x14 字节：flags1(u8) flags2(u8) format(u8) ?(u8) ?(u16) ?(u16) size(i32) offset(i32) ?(i32)
  offset 处就是一段**完整的 DDS**（c2300 的第一条 = 0x120 = 头里那个 288）
"""
import csv
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chr_peek as CP                                              # noqa: E402
import erio                                                        # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, os.pardir, "chr_peek"))


def tpf_entries(raw):
    """→ [(序号, size, offset)]（布局用已知模型反推、再用 DDS 魔数验证过）

    实测（c2300）：条目表从 **0x10** 起、步长 **0x14**，每条前两个 i32 就是 offset / size；
    每个 offset 处是一段**完整的 DDS**（不是裸像素），所以解出来直接能读。
    """
    if raw[:4] != b"TPF\0":
        return []
    cnt = struct.unpack_from("<i", raw, 8)[0]
    out = []
    for i in range(cnt):
        p = 0x10 + i * 0x14
        if p + 8 > len(raw):
            break
        off, size = struct.unpack_from("<ii", raw, p)
        out.append((i, size, off))
    return out


def extract(model, out_dir=OUT, max_px=512):
    """把某个模型的贴图导成 PNG，返回 [(文件, 尺寸, 字节数)]"""
    from PIL import Image
    got = []
    for cand in (model + "_h.texbnd.dcx", model + "_l.texbnd.dcx", model + "_m.texbnd.dcx"):
        p = os.path.join(CP.CHR, cand)
        if not os.path.isfile(p):
            continue
        raw = CP._plain(open(p, "rb").read())
        if raw[:4] != b"BND4":
            continue
        for _n, d in erio.Bnd4.parse(raw).files:
            d2 = CP._plain(d) if d[:4] == b"DCX\0" else d
            if d2[:4] != b"TPF\0":
                continue
            for i, size, off in tpf_entries(d2):
                blob = d2[off:off + size]
                if not blob.startswith(b"DDS ") or size < 128:
                    continue
                try:
                    im = Image.open(io.BytesIO(blob))
                    im.load()
                    if im.width < 32 or im.height < 32:
                        continue
                    im = im.convert("RGB")
                    if max(im.size) > max_px:
                        im.thumbnail((max_px, max_px))
                    op = os.path.join(out_dir, "%s_%02d.png" % (model, i))
                    im.save(op)
                    got.append((os.path.basename(op), im.size, size))
                except Exception:
                    continue
    return got


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    if "--from-review" in argv:
        csvp = os.path.normpath(os.path.join(HERE, os.pardir, "models_to_review.csv"))
        models = [r["model"] for r in csv.DictReader(open(csvp, encoding="utf-8-sig"))]
    else:
        models = [a for a in argv if not a.startswith("--")]
    print("mod:", CP.CHR)
    ok = 0
    index = []
    for m in models:
        got = extract(m)
        if got:
            ok += 1
            print("  %-8s 导出 %d 张贴图，例：%s" % (m, len(got), got[0][0]))
            for f, size, n in got[:3]:
                index.append({"model": m, "file": f, "w": size[0], "h": size[1], "dds_bytes": n})
        else:
            print("  %-8s ✗ 没导出（没有 texbnd 或里面不是 DDS）" % m)
    print("成功 %d / %d → %s" % (ok, len(models), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
