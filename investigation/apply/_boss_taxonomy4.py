# -*- coding: utf-8 -*-
"""法魂 Boss 分类 · 第四轮（只读）

用游戏自己的字段口径统计"什么算 Boss"：
  * NpcParam.isSoulGetByBoss == 1  → 游戏认定"击杀给追忆/大魂"的 Boss
  * getSoul 分档（卢恩奖励）→ 强度档
  * nameId → NpcName 中文名
并把 32 个追忆与 Boss 名字对上。
"""
import os
import struct
import sys
import importlib.util

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa
import native_apply as na
import native_guide as ng

spec = importlib.util.spec_from_file_location("bt", os.path.join(WS, "_boss_taxonomy.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)
MOD = bt.MOD


def main():
    reg = os.path.join(MOD, "mod", "regulation.bin")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(reg)))
    sizes = {}
    for name, off, size in na.bnd4_entries(plain):
        b = os.path.basename(name.replace("\\", "/"))
        if b.endswith(".param"):
            sizes[b[:-6]] = (off, size)

    fields, row_size = bt.paramdef_fields("NpcParam")
    off0, size0 = sizes["NpcParam"]
    rows = bt.scan_rows(plain, off0, size0)
    off = {f[0]: (f[2], f[1]) for f in fields}

    def rd(base, k):
        o, t = off[k]
        p = off0 + base + o
        if t in ("u8", "i8", "s8"):
            return plain[p]
        if t in ("u16", "i16", "s16"):
            return struct.unpack_from("<H", plain, p)[0]
        if t in ("u32", "i32", "s32"):
            return struct.unpack_from("<I", plain, p)[0]
        return None

    # FMG（逐文件，避免 id 撞车）
    bnd, _h, _r = ng.read_msgbnd(os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx"))
    fm = {n.split("\\")[-1].replace(".fmg", ""): bt.fmg_parse(d) for n, d in bnd.files}
    npc = {}
    for k in ("NpcName", "NpcName_dlc01", "NpcName_dlc02"):
        for i, s in fm.get(k, {}).items():
            npc[i] = s
    goods = {}
    for k in ("GoodsName", "GoodsName_dlc01"):
        for i, s in fm.get(k, {}).items():
            goods[(k, i)] = s

    print("=== 1) isSoulGetByBoss == 1 的行（游戏口径的 Boss）===")
    boss_rows, other = [], 0
    for rid, base in rows.items():
        v = rd(base, "isSoulGetByBoss") if "isSoulGetByBoss" in off else None
        if v == 1:
            boss_rows.append(rid)
        else:
            other += 1
    print(f"  Boss 行 {len(boss_rows)}｜非 Boss 行 {other}｜合计 {len(rows)}")
    named = []
    for rid in boss_rows:
        base = rows[rid]
        nid = rd(base, "nameId")
        nm = npc.get(nid, "")
        soul = rd(base, "getSoul") or 0
        hp = rd(base, "hp") or 0
        named.append((soul, hp, rid, nm))
    named.sort(reverse=True)
    print(f"  其中有中文名的 {sum(1 for x in named if x[3])} 个")
    print("\n  卢恩奖励前 40：")
    for soul, hp, rid, nm in named[:40]:
        print(f"    {soul:>7} 魂 hp={hp:<6} id={rid:<9} {nm or '（无名）'}")

    print("\n=== 2) 追忆 ↔ Boss 名字匹配 ===")
    rems = []
    for (fname, i), s in sorted(goods.items()):
        if "追忆" in s:
            rems.append((fname, i, s))
    print(f"  追忆物品 {len(rems)} 个")
    npc_vals = [v for v in npc.values() if v]
    ok, miss = 0, []
    for fname, i, s in rems:
        stem = s.replace("的追忆", "").strip("“”")
        hit = [n for n in npc_vals if stem and stem in n]
        if hit:
            ok += 1
        else:
            miss.append(f"[{fname}:{i}] {s}")
    print(f"  按名字能对上 Boss 的: {ok}/{len(rems)}")
    if miss:
        print("  对不上的（可能要人工标注）:")
        for m in miss:
            print(f"    {m}")


if __name__ == "__main__":
    main()
