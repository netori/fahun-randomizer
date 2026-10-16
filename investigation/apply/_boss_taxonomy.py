# -*- coding: utf-8 -*-
"""法魂 Boss 分类 · 数据挖掘（只读）

做三件事：
1) 稳健的 FMG 读取器（id → 文本）：允许条目为空（offset=0），不再像上次那样读到一半就断
2) 在所有 FMG 里找"类别凭证"关键词：追忆 / 楔石 / 大锅 / 传送门 / 卢恩 / 追忆
3) 用 NpcParam.nameId 把 7823 行敌人对上中文名，并按"卢恩奖励"排序给出 Boss 候选
"""
import os
import re
import struct
import sys

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa

ROOT = os.path.abspath(os.path.join(WS, "..", "..", ".."))
MOD = os.environ.get("MOD_ROOT") or os.path.join(
    ROOT, "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
PARAMDEX = os.path.abspath(os.path.join(WS, "..", "..", "tools", "witchybnd-3.0.1.0",
                                        "Assets", "Paramdex", "ER", "Defs"))
SIZE = {"u8": 1, "i8": 1, "s8": 1, "dummy8": 1, "u16": 2, "i16": 2, "s16": 2, "dummy16": 2,
        "u32": 4, "i32": 4, "s32": 4, "f32": 4, "angle32": 4,
        "u64": 8, "i64": 8, "s64": 8, "f64": 8}


def paramdef_fields(name):
    p = os.path.join(PARAMDEX, name + ".xml")
    if not os.path.isfile(p):
        return None, 0
    x = open(p, encoding="utf-8-sig").read()
    out, bit_off = [], 0
    for m in re.finditer(r'<Field Def="([^"]+)">', x):
        d = m.group(1)
        typ, _, rest = d.partition(" ")
        bits = 0
        if ":" in rest:
            rest, _, b = rest.partition(":")
            b = b.split("=")[0].strip()
            bits = int(b) if b.isdigit() else 0
        nm = rest.split("=")[0].strip()
        cnt = 1
        mm = re.search(r"\[(\d+)\]", nm)
        if mm:
            cnt = int(mm.group(1))
            nm = nm[:mm.start()].strip()
        if bits:
            out.append((nm, typ, bit_off // 8, 0))
            bit_off += bits
        else:
            sz = SIZE.get(typ, 0) * cnt
            if bit_off % 8:
                bit_off += 8 - (bit_off % 8)
            out.append((nm, typ, bit_off // 8, sz))
            bit_off += sz * 8
    return out, (bit_off + 7) // 8


def fmg_parse(data):
    """FMG → {真 id: 文本}。

    ⚠️ 2026-10-16 口径修正：本函数原来的实现是"启发式找偏移表 + 把**字符串槽号当 id**"，
    与 NpcParam 引用的 nameId **不是同一套 id** —— FMG 的一条区间记录 [lo, hi] 里，
    每个 id 各占一个字符串槽，必须按槽号直读偏移表。
    现在统一委托给权威解析 `enemy_names.parse_fmg`（已修正并自检通过：
    902130002 → 「“恶兆王”蒙葛特」、902110001 → 「“黑剑”玛利喀斯」）。
    老实现留作 `_fmg_parse_legacy` 兜底。
    """
    try:
        import enemy_names as _EN
        return _EN.parse_fmg(data)
    except Exception:
        return _fmg_parse_legacy(data)


def _fmg_parse_legacy(data):
    """历史实现（启发式，槽号当 id）：只在权威解析不可用时兜底。"""
    best, best_len = None, 0
    for start in range(0x10, min(len(data) - 16, 0x2000), 4):
        off, zeros, bad = start, 0, 0
        n = 0
        while off + 8 <= len(data) and bad < 4:
            v = struct.unpack_from("<Q", data, off)[0]
            if v == 0:
                zeros += 1
                if zeros > 200:      # 表尾一长串 0 就停
                    break
            elif 0x20 < v < len(data):
                zeros = 0
                n += 1
            else:
                bad += 1
            off += 8
        total = (off - start) // 8
        if n > best_len:
            best, best_len = (start, total), n
    if not best:
        return {}
    start, total = best
    out = {}
    for i in range(total):
        v = struct.unpack_from("<Q", data, start + 8 * i)[0]
        if not (0x20 < v < len(data)):
            continue
        j = v
        while j + 1 < len(data) and data[j:j + 2] != b"\0\0":
            j += 2
        s = data[v:j].decode("utf-16-le", "ignore")
        if s:
            out[i] = s
    return out


def scan_rows(raw, base, size):
    region = raw[base:base + size]
    best, o = {}, 0
    while o + 0x18 <= len(region):
        rid, data, nm = struct.unpack_from("<QQQ", region, o)
        if 0 < rid < 0x7FFFFFFF and 0 < data < nm < len(region):
            run, r = {}, o
            while r + 0x18 <= len(region):
                _id, _d, _n = struct.unpack_from("<QQQ", region, r)
                if not (0 < _id < 0x7FFFFFFF and 0 < _d < _n < len(region)):
                    break
                run[_id] = _d
                r += 0x18
            if len(run) > len(best):
                best = run
            o = r
        else:
            o += 1
    return best


def main():
    import native_apply as na
    reg = os.path.join(MOD, "mod", "regulation.bin")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(reg)))
    sizes = {}
    for name, off, size in na.bnd4_entries(plain):
        b = os.path.basename(name.replace("\\", "/"))
        if b.endswith(".param"):
            sizes[b[:-6]] = (off, size)

    # ── 1) 读所有 FMG ──
    import native_guide as ng
    msg = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    bnd, _h, _raw = ng.read_msgbnd(msg)
    fmgs = {}
    for n, d in bnd.files:
        short = n.split("\\")[-1].replace(".fmg", "")
        fmgs[short] = fmg_parse(d)
    print("=== FMG 读取结果 ===")
    for k in sorted(fmgs, key=lambda x: -len(fmgs[x]))[:14]:
        print(f"  {k:24s} {len(fmgs[k]):>6} 条")

    # ── 2) 找类别凭证关键词 ──
    keys = ["追忆", "楔石", "大锅", "传送门", "追忆"]
    print("\n=== 关键词命中（前若干条）===")
    for kw in dict.fromkeys(keys):
        hits = []
        for fname, tbl in fmgs.items():
            for i, s in tbl.items():
                if kw in s:
                    hits.append((fname, i, s[:60]))
        print(f"\n  【{kw}】命中 {len(hits)} 条")
        for fname, i, s in hits[:8]:
            print(f"    {fname}[{i}] {s}")

    # ── 3) 敌人名字全量对上 ──
    npc_fields, row_size = paramdef_fields("NpcParam")
    off0, size0 = sizes["NpcParam"]
    rows = scan_rows(plain, off0, size0)
    off = {f[0]: (f[2], f[1]) for f in npc_fields}

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

    names = {}
    for f in ("NpcName", "NpcName_dlc01", "NpcName_dlc02"):
        names.update(fmgs.get(f, {}))
    print(f"\n=== 敌人名字表: {len(names)} 条（NpcName 系列合计）===")

    got = []
    for rid, base in rows.items():
        nid = rd(base, "nameId")
        nm = names.get(nid) if nid is not None else None
        soul = rd(base, "getSoul")
        hp = rd(base, "hp")
        if nm and soul:
            got.append((soul, hp, rid, nm))
    got.sort(reverse=True)
    print(f"有名字且有卢恩奖励的行: {len(got)}")
    print("\n=== 卢恩奖励最高的 30 个（Boss 候选）===")
    for soul, hp, rid, nm in got[:30]:
        print(f"  {soul:>7} 魂  hp={hp:<6} id={rid:<9} {nm}")

    zh = sorted({nm for _s, _h, _r, nm in got})
    print(f"\n=== 唯一名字 {len(zh)} 个，包含以下关键词的 ===")
    for kw in ("追忆", "大锅", "黄金树", "王", "神", "龙", "骑士", "兽", "领主"):
        hit = [x for x in zh if kw in x]
        if hit:
            print(f"  【{kw}】{len(hit)}: {hit[:6]}")


if __name__ == "__main__":
    main()
