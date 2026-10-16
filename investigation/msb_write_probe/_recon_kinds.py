# -*- coding: utf-8 -*-
"""侦察：634 张地图的 DCX 压缩类型分布 + DCX 头长度 + 明文大小。只读。"""
import collections
import glob
import os
import sys

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import erio  # noqa: E402

MOD = (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
       r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
MAPDIR = os.path.join(MOD, "mod", "map", "MapStudio")


def main():
    files = sorted(glob.glob(os.path.join(MAPDIR, "*.msb.dcx")))
    print("files:", len(files))
    kinds = collections.Counter()
    payload_offs = collections.Counter()
    total_unc = 0
    sizes = []
    for p in files:
        data = open(p, "rb").read()
        h = erio.dcx_parts(data)
        kinds[h["kind"]] += 1
        payload_offs[h["payload_off"]] += 1
        total_unc += h["unc"]
        sizes.append((h["unc"], os.path.basename(p), h["kind"], len(data)))
    print("kinds:", dict(kinds))
    print("payload_off:", dict(payload_offs))
    print("total unc MB: %.1f" % (total_unc / 1e6))
    sizes.sort(reverse=True)
    print("largest 3:", [(round(s / 1e6, 2), n, k) for s, n, k, _ in sizes[:3]])
    print("smallest 3:", [(round(s / 1e6, 2), n, k) for s, n, k, _ in sizes[-3:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
