# -*- coding: utf-8 -*-
"""侦察 3：zlib 参数能否字节级复现原 DFLT payload；Oodle 压缩能否往返 KRAK。只读。"""
import glob
import os
import sys
import zlib

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import erio      # noqa: E402
import msb_read  # noqa: E402

MOD = (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
       r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
MAPDIR = os.path.join(MOD, "mod", "map", "MapStudio")


def zlib_rep(plain, orig):
    hits = []
    for lvl in (1, 6, 9):
        for ml in (9, 12, 15):
            for strat in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED):
                co = zlib.compressobj(lvl, zlib.DEFLATED, ml, 8, strat)
                out = co.compress(plain) + co.flush()
                if out == orig:
                    hits.append((lvl, ml, strat))
    return hits


def main():
    files = sorted(glob.glob(os.path.join(MAPDIR, "*.msb.dcx")))
    done = 0
    for p in files:
        d = open(p, "rb").read()
        h = erio.dcx_parts(d)
        if h["kind"] != "DFLT" or h["comp"] < 200000:
            continue
        plain, _ = msb_read.dcx_payload(d)
        orig = d[h["payload_off"]:h["payload_off"] + h["comp"]]
        print("DFLT %-24s plain=%d comp=%d  复现参数=%s"
              % (os.path.basename(p), len(plain), h["comp"], zlib_rep(plain, orig) or "无"))
        done += 1
        if done >= 3:
            break

    # Oodle
    try:
        import oodle
        print("\noodle dll:", oodle.find_dll())
        done = 0
        for p in files:
            d = open(p, "rb").read()
            h = erio.dcx_parts(d)
            if h["kind"] != "KRAK":
                continue
            plain, _ = msb_read.dcx_payload(d)
            orig = d[h["payload_off"]:h["payload_off"] + h["comp"]]
            for lvl in (6,):
                try:
                    co = oodle.compress(plain, level=lvl, compressor=8)
                except Exception as e:                        # noqa: BLE001
                    print("KRAK %s Oodle 压缩失败: %s: %s" % (os.path.basename(p), type(e).__name__, e))
                    break
                ok = co == orig
                # 解回来验证
                back = oodle.decompress(co, len(plain))
                print("KRAK %-24s plain=%d comp=%d oodle_comp=%d 字节等同原=%s 解回一致=%s"
                      % (os.path.basename(p), len(plain), h["comp"], len(co), ok, back == plain))
                done += 1
                break
            if done >= 2:
                break
    except Exception as e:                                     # noqa: BLE001
        print("Oodle 测试失败:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
