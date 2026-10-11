# why_duplicates.py — 只读：解释"重复"从哪来
# 两类重复：
#   A) 同一物品出现在多条商店行（多家商人卖同一件东西 / 同族多套 lineup）
#   B) 同一物品出现在多个 Lot 槽（同一件东西有多处获取点）
import csv, json, os, collections, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")


def load_pools():
    """重建"开商店 + 分池"的池，用来找 Lot 侧的重复"""
    sys.path.insert(0, os.path.join(DRY, "scripts"))
    import dryrun as D
    overlay = D.load_overlay()
    _, slots = D.load_index_slots()
    pools = D.lot_cells(overlay, slots, merge=False)
    return pools, slots


def main():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    rn = {str(s["shop_row_id"]): s.get("row_name", "") for s in idx["shops"]}
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    by_item = collections.defaultdict(list)
    for r in shops:
        if r["quality"] == "clean":
            by_item[(r["equip_type_name"], r["equipId"])].append({**r, "row_name": rn.get(str(r["shop_row_id"]), "")})

    print("=== A) 商店侧：同一物品被多行出售的情况 ===")
    dups = {k: v for k, v in by_item.items() if len(v) > 1}
    print("  clean 商店行里，同一物品出现 >=2 行的：", len(dups), "件")
    for (et, iid), rows in sorted(dups.items(), key=lambda kv: -len(kv[1]))[:6]:
        print(f"\n  [{et}] {iid} {rows[0]['name_cn']}（{len(rows)} 行）")
        for r in rows:
            print(f"     行 {r['shop_row_id']:<9} 价 {r['price']:<6} 库存 {r['stock']:<3} "
                  f"库存flag {r['stock_flag']:<8} 释放flag {r['release_flag']:<8} | 行名={r['row_name'][:58]}")

    print("\n=== 商店行号段分布（看是否来自不同商人/不同 lineup 套） ===")
    buckets = collections.Counter()
    for r in shops:
        if r["quality"] != "clean":
            continue
        p = str(r["shop_row_id"])
        key = p[:2] + "xxxx" if len(p) >= 6 else p[:1] + "xxxx"
        buckets[key] += 1
    for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])[:10]:
        print(f"   {k:<10} {v:>4} 行")
    # 同一物品的重复是否跨行号段
    cross = 0
    for k, rows in dups.items():
        segs = {str(r["shop_row_id"])[:2] for r in rows}
        if len(segs) > 1:
            cross += 1
    print(f"  重复物品中，重复行跨越不同行号段的：{cross} / {len(dups)}")

    print("\n=== B) Lot 侧：同一物品有多个获取点 ===")
    pools, slots = load_pools()
    multi = []
    for sub, cs in sorted(pools.items()):
        cnt = collections.Counter(c["item_id"] for c in cs)
        for iid, n in cnt.items():
            if n > 1 and n > sum(1 for c in cs if c["source_table"] == "ShopLineupParam" and c["item_id"] == iid):
                lot_cells = [c for c in cs if c["item_id"] == iid and c["source_table"] != "ShopLineupParam"]
                multi.append({"subpool": sub, "item_id": iid, "name_cn": cs[0]["name_cn"], "lot_cells": len(lot_cells),
                              "rows": [(c["source_table"], c["row_id"], c["slot"], c["row_name"][:46]) for c in lot_cells]})
    for m in multi[:10]:
        print(f"  [{m['subpool']}] {m['item_id']} {m['name_cn'][:12]} 有 {m['lot_cells']} 个 Lot 槽：")
        for r in m["rows"]:
            print(f"      {r[0]}:{r[1]}:s{r[2]}  行名={r[3]}")
    if not multi:
        print("  （本次参与池中，Lot 侧没有重复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
