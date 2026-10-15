# -*- coding: utf-8 -*-
"""敌人随机 · 本地数据侦察 v4（只读）

v4 修掉两处：
* paramdef 的**位域**要按 bit 累加、非位域字段才对齐到字节（v3 的偏移飘了，读出来是乱码）
* FMG 偏移表起点扫描范围放宽到 0x8000（基础版 NpcName 比 dlc01 大，0x400 扫不到）
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
    """返回 ([(名, 类型, 行内字节偏移, 字节大小)], 行大小) —— 位域按 bit 累加"""
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
        if bits:                                    # 位域：按 bit 推进（同一字节内的多个位域共用）
            byte_off = bit_off // 8
            out.append((nm, typ, byte_off, 0))
            bit_off += bits
        else:                                       # 普通字段：先对齐到字节，再乘数组长度
            sz = SIZE.get(typ, 0) * cnt
            if bit_off % 8:
                bit_off += 8 - (bit_off % 8)
            byte_off = bit_off // 8
            out.append((nm, typ, byte_off, sz))
            bit_off += sz * 8
    return out, (bit_off + 7) // 8


def rd(plain, off, typ):
    if typ in ("u8", "i8"):
        return plain[off]
    if typ in ("u16", "i16"):
        return struct.unpack_from("<H", plain, off)[0]
    if typ in ("u32", "i32", "s32"):
        return struct.unpack_from("<I", plain, off)[0]
    if typ == "f32":
        return round(struct.unpack_from("<f", plain, off)[0], 1)
    return None


def read_fmg(data, scan_max=0x8000):
    """通用 FMG 读取：扫一张"全是合法文件内偏移"的 u64 表（越长的表越可能是真表）"""
    best = None
    hi = min(len(data) - 16, scan_max)
    for start in range(0x0C, hi, 4):
        off, out = start, []
        while off + 8 <= len(data):
            v = struct.unpack_from("<Q", data, off)[0]
            if not (0x20 < v < len(data)):
                break
            out.append(v)
            off += 8
        if out and (best is None or len(out) > len(best[1])):
            best = (start, out)
    if not best:
        return []
    res = []
    for v in best[1]:
        j = v
        while j + 1 < len(data) and data[j:j + 2] != b"\0\0":
            j += 2
        res.append(data[v:j].decode("utf-16-le", "ignore"))
    return res


def main():
    import native_apply as na
    reg = os.path.join(MOD, "mod", "regulation.bin")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(reg)))
    entries = list(na.bnd4_entries(plain))
    sizes = {}
    for name, off, size in entries:
        base = os.path.basename(name.replace("\\", "/"))
        if base.endswith(".param"):
            sizes[base[:-6]] = (off, size)

    print("=== 1) 敌人相关表：行表扫出来的行数 ===")
    rowtabs = {}
    for t in ("NpcParam", "NpcThinkParam", "CharaInitParam", "NpcAiActionParam"):
        if t not in sizes:
            continue
        off0, size0 = sizes[t]
        region = plain[off0:off0 + size0]
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
        rowtabs[t] = (off0, best)
        fields, row_size = paramdef_fields(t)
        print(f"  {t:18s} 行 {len(best):>5}｜行大小 {row_size} B")

    print("\n=== 2) NpcParam 关键字段（修好位域后的真实值）===")
    fields, row_size = paramdef_fields("NpcParam")
    off0, rows = rowtabs["NpcParam"]
    off = {f[0]: (f[2], f[1]) for f in fields}
    for k in ("hp", "getSoul", "itemLotId_enemy", "teamType", "npcType", "nameId"):
        if k in off:
            print(f"  {k:18s} +{off[k][0]:#05x} {off[k][1]}")
    modelish = [f[0] for f in fields if re.search(r"(?i)^modelId|modelId$|charaModel|^chrId", f[0])]
    print(f"  真正的'模型 id'类字段: {modelish or '（无）'}")
    ids = sorted(rows)
    step = max(1, len(ids) // 6)
    print("  抽样:")
    hps = []
    for rid in ids:
        base = off0 + rows[rid]
        v = rd(plain, base + off["hp"][0], off["hp"][1]) if "hp" in off else None
        if isinstance(v, int) and 0 < v < 10 ** 8:
            hps.append(v)
    for rid in ids[::step][:6]:
        base = off0 + rows[rid]
        vals = {k: rd(plain, base + off[k][0], off[k][1]) for k in
                ("hp", "getSoul", "itemLotId_enemy", "teamType", "npcType") if k in off}
        print(f"    {rid:>8}: {vals}")
    if hps:
        hps.sort()
        q = lambda p: hps[min(len(hps) - 1, int(len(hps) * p))]
        print(f"  血量（{len(hps)} 条合理值）: 中位 {q(.5)}｜75% {q(.75)}｜90% {q(.9)}｜最大 {hps[-1]}")

    print("\n=== 3) 敌人名字（NpcName）===")
    import native_guide as ng
    msgdir = os.path.join(MOD, "mod", "msg", "zhocn")
    print("  msg 目录里的 msgbnd:", [f for f in os.listdir(msgdir) if f.endswith(".dcx")][:8])
    for fn in ("item_dlc02.msgbnd.dcx", "item.msgbnd.dcx"):
        p = os.path.join(msgdir, fn)
        if not os.path.isfile(p):
            continue
        bnd, _h, _raw = ng.read_msgbnd(p)
        names = [n for n, _d in bnd.files]
        hits = [n for n in names if re.search(r"(?i)npcname", n)]
        print(f"\n  【{fn}】{len(names)} 个 FMG，NpcName 系列: {[h.split(chr(92))[-1] for h in hits]}")
        for h in hits:
            strs = read_fmg(dict(bnd.files)[h])
            zh = [s for s in strs if s and any("\u4e00" <= c <= "\u9fff" for c in s)]
            print(f"    {h.split(chr(92))[-1]}: 读出 {len(strs)} 条（中文 {len(zh)}）")
            if zh:
                print(f"      样例: {zh[:10]}")


if __name__ == "__main__":
    main()
