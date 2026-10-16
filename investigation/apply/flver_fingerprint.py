# -*- coding: utf-8 -*-
"""网格指纹：把每个模型的 FLVER 拿出来算哈希，找"同一个网格"。

用在剩下那几个没有名字线索的模型上：如果法魂只是**换贴图**，网格会与某个已知模型
**逐字节相同**（或者顶点数/包围盒一致）—— 那原身就找到了。

产出：investigation/flver_fingerprint.csv（模型 / FLVER 数 / 字节数 / sha256 前 16 位 / 顶点数）
"""
import csv
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)
import chr_peek as CP                                               # noqa: E402
import erio                                                         # noqa: E402

OUT = os.path.join(DATA, "flver_fingerprint.csv")


def flvers_of(model):
    """→ [(名字, FLVER 字节)]（先解 DCX，再解 BND4，再挑 .flver 条目）"""
    p = os.path.join(CP.CHR, model + ".chrbnd.dcx")
    if not os.path.isfile(p):
        return []
    try:
        raw = CP._plain(open(p, "rb").read())
    except Exception as e:
        print("   ✗ %s 解 DCX: %s" % (model, e))
        return []
    out = []
    if raw[:4] == b"BND4":
        try:
            entries = list(erio.Bnd4.parse(raw).files)
        except Exception as e:
            import traceback
            print("   ✗ %s: %s" % (model, e))
            traceback.print_exc()
            return []
        for n, d in entries:
            d2 = CP._plain(d) if d[:4] == b"DCX\0" else d
            if d2[:4] == b"FLVER":
                out.append((n, d2))
    elif raw[:4] == b"FLVER":
        out.append((model, raw))
    return out


def flver_stats(b):
    """从 FLVER 头里取：版本 / 骨骼数 / 网格数 / 顶点缓冲数（位置按 ER 的 FLVER2 布局）"""
    try:
        ver = struct.unpack_from("<i", b, 4)[0]
        bone_cnt = struct.unpack_from("<i", b, 0x1C)[0]
        mesh_cnt = struct.unpack_from("<i", b, 0x24)[0]
        vb_cnt = struct.unpack_from("<i", b, 0x2C)[0]
        return ver, bone_cnt, mesh_cnt, vb_cnt
    except Exception:
        return (0, 0, 0, 0)


def main():
    models = sorted(f[:-len(".chrbnd.dcx")] for f in os.listdir(CP.CHR)
                    if f.endswith(".chrbnd.dcx"))
    print("chr 目录里的模型:", len(models))
    rows = []
    n_dbg = 0
    for m in models:
        got = flvers_of(m)
        if not got and n_dbg < 3:
            n_dbg += 1
            print("   ? %s 没解出（isfile=%s）" % (
                m, os.path.isfile(os.path.join(CP.CHR, m + ".chrbnd.dcx"))))
        for n, b in got:
            ver, bn, mc, vb = flver_stats(b)
            rows.append({"model": m, "flver": os.path.basename(n), "bytes": len(b),
                         "sha16": hashlib.sha256(b).hexdigest()[:16],
                         "version": ver, "bones": bn, "meshes": mc, "vbs": vb})
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    by_sha = {}
    for r in rows:
        by_sha.setdefault(r["sha16"], []).append(r["model"])
    dupes = {k: v for k, v in by_sha.items() if len(set(v)) > 1}
    print("FLVER 条目 %d ｜ 唯一网格 %d ｜ **网格逐字节相同的组: %d**" % (
        len(rows), len(by_sha), len(dupes)))
    for k, v in list(dupes.items())[:12]:
        print("   相同网格:", sorted(set(v)))
    left = ["c3361", "c3371", "c8003", "c8004", "c8005"]
    print()
    for m in left:
        mine = [r for r in rows if r["model"] == m]
        if not mine:
            print("  %-8s 没有 chrbnd/FLVER" % m)
            continue
        hit = [k for k, v in dupes.items() if m in v]
        print("  %-8s FLVER %d 个｜字节 %s｜同网格的模型: %s" % (
            m, len(mine), [r["bytes"] for r in mine][:3],
            sorted(set(sum([dupes[k] for k in hit], []))) if hit else "（没有）"))
    print("→", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
