# -*- coding: utf-8 -*-
"""侦察 2：逐 kind 比 DCX 前缀是否一致；并测 zlib 能不能字节级复现原 payload。只读。"""
import collections
import glob
import os
import sys
import zlib

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import erio  # noqa: E402

MOD = (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
       r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
MAPDIR = os.path.join(MOD, "mod", "map", "MapStudio")


def main():
    files = sorted(glob.glob(os.path.join(MAPDIR, "*.msb.dcx")))
    by_kind = collections.defaultdict(set)
    for p in files:
        d = open(p, "rb").read()
        h = erio.dcx_parts(d)
        by_kind[h["kind"]].add(bytes(d[24:h["payload_off"]]))
    for k, v in by_kind.items():
        print("[%s] 不同前缀数 = %d" % (k, len(v)))
        for pre in list(v)[:3]:
            print("   ", pre.hex(" "))

    # 挑一张 KRAK 打印头
    for p in files:
        d = open(p, "rb").read()
        h = erio.dcx_parts(d)
        if h["kind"] == "KRAK":
            print("\nKRAK 样例 %s  head(0..76)=%s" % (os.path.basename(p), d[:76].hex(" ")))
            break

    # zlib 字节级复现实验（挑 DFLT）
    tested = 0
    for p in files:
        d = open(p, "rb").read()
        h = erio.dcx_parts(d)
        if h["kind"] != "DFLT" or h["comp"] < 100000:
            continue
        plain = erio.dcx_decompress(d)
        orig = d[h["payload_off"]:h["payload_off"] + h["comp"]]
        hits = []
        for lvl in (6, 9):
            for ml in (9, 12, 15):
                co = zlib.compressobj(lvl, zlib.DEFLATED, ml)
                out = co.compress(plain) + co.flush()
                if out == orig:
                    hits.append((lvl, ml))
        print("zlib 复现 %s: %s (orig comp=%d)" % (os.path.basename(p), hits or "无", h["comp"]))
        tested += 1
        if tested >= 3:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
