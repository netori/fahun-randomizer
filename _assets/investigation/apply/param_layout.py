# param_layout.py — 用"已知改动"攻下 ER param(format2D/2E) 的行表与字段偏移
#   原版：work/orig/regulation-bin/ItemLotParam_map.param
#   已改：work/pilot2/regulation-bin/ItemLotParam_map.param（首测 36 处改动，已部署验证过）
#   答案键：out/plan_pilot.csv 里的 (row_id, slot, old_id, new_id, old_cat, new_cat)
import csv, os, re, struct, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
OLD = os.path.join(APPLY, "work", "orig", "regulation-bin", "ItemLotParam_map.param")
NEW = os.path.join(APPLY, "work", "pilot2", "regulation-bin", "ItemLotParam_map.param")
PLAN = os.path.join(APPLY, "out", "plan_pilot.csv")


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def main():
    old, new = open(OLD, "rb").read(), open(NEW, "rb").read()
    print(f"  原版 {len(old)} B | 已改 {len(new)} B | 大小相同: {len(old) == len(new)}")
    mi = old.find(b"PARAM")
    print(f"  'PARAM' 魔数位置: {hex(mi)}")
    print("  魔数附近 0x40 字节:")
    for off in range(mi, mi + 0x40, 16):
        c = old[off:off + 16]
        print(f"   {off:06x}  {c.hex(' ')}  {''.join(chr(x) if 32 <= x < 127 else '.' for x in c)}")

    # 计划（只取本表的行）
    plan = [r for r in csv.DictReader(open(PLAN, encoding="utf-8-sig"))
            if r["old"] != r["new"] and r["source_table"] == "ItemLotParam_map"]
    by_row = {}
    for r in plan:
        by_row.setdefault(int(r["row_id"]), []).append(r)
    print(f"\n  本表计划改动 {len(plan)} 行，涉及 {len(by_row)} 个 lot 行")

    # 逐字节 diff
    diff = [i for i in range(min(len(old), len(new))) if old[i] != new[i]]
    print(f"  差异字节 {len(diff)} 个；区间：")
    groups, cur = [], [diff[0]]
    for i in diff[1:]:
        if i - cur[-1] <= 6:
            cur.append(i)
        else:
            groups.append((cur[0], cur[-1]))
            cur = [i]
    groups.append((cur[0], cur[-1]))
    for a, b in groups:
        print(f"    {hex(a)}..{hex(b)} ({b - a + 1}B)")
        for off in range(a - (a % 4), b + 1, 4):
            if off + 4 <= len(old):
                print(f"       @{hex(off)}  原={u32(old, off)}  新={u32(new, off)}")

    # row id 在文件里的位置（行表）
    print("\n  计划里的 lot 行 id 在文件中的位置：")
    found = 0
    for rid in list(by_row)[:6]:
        pat = struct.pack("<I", rid)
        pos = [m.start() for m in re.finditer(re.escape(pat), old)]
        print(f"    row {rid}: 出现 {len(pos)} 次 位置 {[hex(p) for p in pos[:4]]}")
        found += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
