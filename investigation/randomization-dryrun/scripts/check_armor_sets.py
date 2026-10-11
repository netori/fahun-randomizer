# check_armor_sets.py — 只读：护甲在候选池里的"成套"结构
# 目的：回答"身上穿的甲是成套的"这个问题——现有池子里有多少完整四件套、多少散件、多少缺件套；
#      并按"整套置换"口径算一遍可行性。
# 套装识别：沿用 MOD 的 ID 布局惯例（同一基址 + 0000/0100/0200/0300 = 头/身/臂/腿）
import collections, csv, json, os, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}
PART_WORD = {"head": "头", "body": "身", "arm": "臂", "leg": "腿"}


def main():
    sys.path.insert(0, os.path.join(DRY, "scripts"))
    import dryrun_by_item as BI
    overlay, idx, shops = BI.load()
    pools = BI.build_groups(overlay, idx, shops, True, False)

    armor = {}
    for sub, pool in pools.items():
        if not sub.startswith("armor:"):
            continue
        for key, info in pool.items():
            iid = key.split(":")[1]
            armor[iid] = {"sub": sub, "part": sub.split(":")[1], "name": info["name"],
                          "cells": len(info["cells"]), "origin": info["origin"]}

    # 按 ID 基址归套
    sets = collections.defaultdict(dict)
    singles = []
    for iid, v in armor.items():
        tail = iid[-4:]
        if tail in SUF:
            base = iid[:-4]
            sets[base][SUF[tail]] = {"id": iid, **v}
        else:
            singles.append({"id": iid, **v})

    complete = {b: m for b, m in sets.items() if set(m) == {"head", "body", "arm", "leg"}}
    partial = {b: m for b, m in sets.items() if b not in complete}
    print(f"=== 护甲候选（开商店口径）：{len(armor)} 件 ===")
    print(f"  完整四件套：{len(complete)} 套（{len(complete)*4} 件）")
    print(f"  缺件套：{len(partial)} 套（{sum(len(m) for m in partial.values())} 件）")
    print(f"  不属任何套（散件）：{len(singles)} 件")
    print()
    print("=== 完整四件套明细（前 20 套）===")
    for b, m in sorted(complete.items())[:20]:
        names = " / ".join(m[p]["name"] for p in ("head", "body", "arm", "leg"))
        cells = sum(m[p]["cells"] for p in ("head", "body", "arm", "leg"))
        print(f"  基址 {b:<8} 格数 {cells}  {names}")
    print()
    if partial:
        print("=== 缺件套明细（前 12 套）===")
        for b, m in sorted(partial.items())[:12]:
            have = "".join(PART_WORD[p] for p in ("head", "body", "arm", "leg") if p in m)
            miss = "".join(PART_WORD[p] for p in ("head", "body", "arm", "leg") if p not in m)
            print(f"  基址 {b:<8} 有[{have}] 缺[{miss}]  {' / '.join(m[p]['name'] for p in m)}")
    print()
    print("=== 散件明细 ===")
    for s in sorted(singles, key=lambda x: x["id"]):
        print(f"  {s['id']:<9} {s['part']:<5} {s['name'][:14]:<15} 来源={s['origin']} 格={s['cells']}")
    print()
    # 整套置换可行性：只让"同样四件齐"的套互换
    ok = len(complete) >= 2
    print("=== 「整套置换」可行性 ===")
    print(f"  完整套 {len(complete)} 组 → {'可以整组互换（套与套之间按部位对应互换）' if ok else '不足 2 组，无法互换'}")
    print(f"  散件 {len(singles)} 件 → 只能与散件做同部位互换（否则会把某一套拆开）")
    print(f"  缺件套 {len(partial)} 组 → 缺的部位无法成套转让；建议按'散件'处理或冻结")
    out = {"armor_items": len(armor), "complete_sets": len(complete), "partial_sets": len(partial),
           "singles": len(singles),
           "complete_set_bases": sorted(complete.keys()), "partial_set_bases": sorted(partial.keys()),
           "single_ids": sorted(s["id"] for s in singles)}
    json.dump(out, open(os.path.join(DRY, "evidence", "armor_set_structure.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写出 evidence/armor_set_structure.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
