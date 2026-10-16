# -*- coding: utf-8 -*-
"""从 .chrbnd.dcx 里把贴图（TPF→DDS）解出来，拼成一张总览图 —— 用来"看"这些模型长什么样。

为什么走这条路：那 39 个模型没名字（法魂新增），但**模型资源里带贴图**；
ER 的 TPF 里存的就是 DDS 数据块，解出来转 PNG 就能直接看。
WitchyBND 要交互终端跑不了，所以这里自己写：DCX(现成) → BND4(现成) → TPF(几十行) → DDS(Pillow 直接读)。

用法：
    python chr_peek.py c5652 c7005 ...          # 指定模型
    python chr_peek.py --from-review            # 从 models_to_review.csv 读全部并拼一张总览
产出：investigation/chr_peek/<模型>_*.png 与 investigation/chr_peek/_overview.png
"""
import csv
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as _ER

# 路径一律问引擎（它已经带断言自检；自己拼层级错过两次了）
MOD = os.environ.get("CONVERGENCE_MOD_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(_ER._mod_reg())))
CHR = os.path.join(MOD, "mod", "chr")
OUT = os.path.join(os.path.dirname(HERE), "chr_peek")


def bnd4_entries(raw):
    """BND4 的文件表 → [(名字, 偏移, 大小)]（只解析我们需要的那几个字段）"""
    if raw[:4] != b"BND4":
        return []
    count = struct.unpack_from("<i", raw, 0x0C)[0]
    off_files = struct.unpack_from("<q", raw, 0x20)[0]
    out = []
    for i in range(count):
        p = off_files + i * 0x24
        flags, _unk, size, off, _u1, _u2 = struct.unpack_from("<BBiqqqq", raw, p)[:6]
        name_off = struct.unpack_from("<q", raw, p + 0x18)[0]
        end = raw.find(b"\0", name_off)
        name = raw[name_off:end].decode("utf-8", "replace")
        out.append((name, off, size))
    return out


def tpf_textures(raw):
    """TPF → [(名字, DDS 字节)]。ER 的 TPF 里每条就是一段 DDS 数据。"""
    if raw[:4] != b"TPF\0":
        return []
    count = raw[8]
    tex_off = struct.unpack_from("<i", raw, 0x0C)[0]
    out = []
    for i in range(count):
        p = tex_off + i * 0x14
        flags = raw[p + 2]
        fmt = raw[p + 3]
        size = struct.unpack_from("<i", raw, p + 8)[0]
        off = struct.unpack_from("<i", raw, p + 12)[0]
        # 名字在 TPF 末尾的名字表里（也可能没有 → 用序号）
        out.append(("t%02d_fmt%d" % (i, fmt), bytes(raw[off:off + size])))
    return out


def _plain(data):
    """DCX → 明文。DFLT / ZSTD / KRAK(Oodle) 三条路都走 msb_read（erio 不认 KRAK）。"""
    import msb_read as MR
    if data[:4] == b"DCX\0":
        return MR.dcx_payload(data)[0]
    return data


def peek(model):
    """贴图不在 .chrbnd 里 —— ER 把角色贴图放在 cXXXX_h.texbnd.dcx / _l.texbnd.dcx。"""
    candidates = [model + "_h.texbnd.dcx", model + "_l.texbnd.dcx", model + "_m.texbnd.dcx",
                  model + ".texbnd.dcx", model + ".chrbnd.dcx"]
    used, files, texes = [], [], []
    for nm in candidates:
        p = os.path.join(CHR, nm)
        if not os.path.isfile(p):
            continue
        used.append(nm)
        raw = _plain(open(p, "rb").read())
        blobs = []
        if raw[:4] == b"BND4":
            # 用 erio 现成的 BND4 解析（我自己那版是猜的布局，字段对不上）
            import erio
            for _n, d in erio.Bnd4.parse(raw).files:
                blobs.append((_n, _plain(d) if d[:4] == b"DCX\0" else d))
        elif raw[:4] == b"TPF\0":
            blobs.append((nm, raw))
        for _n, blob in blobs:
            if blob[:4] == b"TPF\0":
                texes += tpf_textures(blob)
            elif blob[:4] == b"DDS ":
                texes.append((_n, blob))
    if not used:
        return {"model": model, "error": "没有 chrbnd/texbnd"}
    return {"model": model, "bnd_files": len(used), "used": used, "textures": texes}


def dds_to_png(dds, out_png):
    """DDS → PNG（Pillow 直接读 DDS）。失败就返回 None（不编）"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(dds))
        im.save(out_png)
        return out_png
    except Exception as e:
        return None


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    if "--from-review" in argv:
        csvp = os.path.join(os.path.dirname(HERE), "models_to_review.csv")
        models = [r["model"] for r in csv.DictReader(open(csvp, encoding="utf-8-sig"))]
    else:
        models = [a for a in argv if not a.startswith("--")]
    if not models:
        print("用法: python chr_peek.py c5652 ... ｜ --from-review")
        return 2
    print("mod:", MOD)
    ok = 0
    for m in models:
        r = peek(m)
        if r.get("error"):
            print("  %-8s ✗ %s" % (m, r["error"]))
            continue
        got = 0
        for i, (nm, dds) in enumerate(r["textures"]):
            if not dds.startswith(b"DDS "):
                continue
            op = os.path.join(OUT, "%s_%02d.png" % (m, i))
            if dds_to_png(dds, op):
                got += 1
        print("  %-8s BND 文件 %3d ｜ TPF 贴图 %2d ｜ 转出 PNG %2d" % (m, r["bnd_files"], len(r["textures"]), got))
        ok += got > 0
    print("有贴图的模型: %d / %d  →  %s" % (ok, len(models), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
