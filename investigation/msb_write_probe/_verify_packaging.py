# -*- coding: utf-8 -*-
"""封装细节验证：① from-scratch 前缀 vs 真实前缀；② unk04 与 kind 的对应；
③ edits 的歧义/未命中/别名/part-name 寻址；④ model 字段改写。只读（不碰 mod 目录）。"""
import glob
import os
import struct
import sys

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import msb_read   # noqa: E402
import msb_write as mw  # noqa: E402

MOD = (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
       r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
D = os.path.join(MOD, "mod", "map", "MapStudio")


def main():
    files = sorted(glob.glob(os.path.join(D, "*.msb.dcx")))
    dflt = krak = None
    for p in files:
        b = open(p, "rb").read(76)
        if b[40:44] == b"DFLT" and dflt is None:
            dflt = (p, b)
        if b[40:44] == b"KRAK" and krak is None:
            krak = (p, b)
        if dflt and krak:
            break
    print("① 真实前缀（前 24 字节 = DCX 头）")
    for tag, (p, b) in (("DFLT", dflt), ("KRAK", krak)):
        print("   %s %-24s 0..24=%s" % (tag, os.path.basename(p), b[:24].hex(" ")))
        h = mw.erio.dcx_parts(open(p, "rb").read())
        built = mw._build_prefix(tag, h["unc"], h["comp"], mw.LEVEL_DFLT if tag == "DFLT" else mw.LEVEL_KRAK)
        print("      克隆 vs 从零拼：%s" % ("逐字节相同" if built == b else "不同 -> " + built.hex(" ")))
        print("      unk04=%#x  level=%d  kind=%r" % (struct.unpack_from(">I", b, 4)[0], b[48], b[40:44]))

    print("\n② 634 张里 unk04 与 kind 的联合分布")
    dist = {}
    for p in files:
        b = open(p, "rb").read(76)
        k = b[40:44].decode()
        dist[(k, struct.unpack_from(">I", b, 4)[0], b[48])] = dist.get(
            (k, struct.unpack_from(">I", b, 4)[0], b[48]), 0) + 1
    for k, v in sorted(dist.items()):
        print("   kind=%-4s unk04=%#08x level=%d  ×%d" % (k[0], k[1], k[2], v))

    # ③ edits 语义
    print("\n③ edits 语义（用 m10_00_00_00）")
    p = [f for f in files if os.path.basename(f).startswith("m10_00_00_00")][0]
    data = open(p, "rb").read()
    raw, _ = mw.dcx_unpack(data)
    parts = mw.enemy_parts(raw)
    eid0 = next(x["entity_id"] for x in parts if x["entity_id"] > 0)
    multi = next((x["entity_id"] for x in parts
                  if sum(1 for y in parts if y["entity_id"] == x["entity_id"]) > 1), None)
    nm = parts[1]["name"]
    print("   一个唯一的 EntityID=%d ; 一个重复的 EntityID=%r ; 一个 part 名=%r"
          % (eid0, multi, nm))
    _o, r1 = mw.patch_ex(data, {999999999: {"npc_id": 1}})
    print("   未命中 -> issues=%s" % r1["issues"])
    if multi is not None:
        _o, r2 = mw.patch_ex(data, {multi: {"npc_id": 12345}})
        print("   重复 EntityID -> issues=%s" % [(i["code"], i["detail"][:60]) for i in r2["issues"]])
    _o, r3 = mw.patch_ex(data, {nm: {"npc": 111, "think": 222}})
    print("   别名 + part 名寻址 -> applied=%s issues=%s"
          % ([(a["part_name"], a["via"], a["changes"]) for a in r3["applied"]], r3["issues"]))
    _o, r4 = mw.patch_ex(data, {nm: {"nonsense": 1}})
    print("   未知字段 -> issues=%s" % r4["issues"])
    _o, r5 = mw.patch_ex(data, {nm: {"model": 309}})
    app = r5["applied"][0]
    print("   model 改写 -> changes=%s (part=%s)" % (app["changes"], app["part_name"]))

    print("\n④ out_kind='same' 在 KRAK 上的降级行为（伪造一个不存在的 kind）")
    try:
        o, rr = mw.dcx_repack(raw, in_kind="KRAK", out_kind="same",
                              orig_prefix=open(p, "rb").read(76))
        print("   in=KRAK out_kind=same -> out=%s degraded=%s (产物 %d B)"
              % (rr["out_kind"], rr["degraded"], len(o)))
    except Exception as e:                                    # noqa: BLE001
        print("   异常:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
