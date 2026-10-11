# verify_cross_source.py — 验证「商店专属」与「别处掉落」是否已经混在同一个池里打乱
# 判据：看置换表里
#   ① 目标是 Lot 槽（ItemLotParam_map/enemy）、但换上去的物品"只有商店来源" → 掉落点能拿到商店专属
#   ② 目标是商店行、但换上去的物品"只有 Lot 来源" → 商店能卖到原本只在掉落点的东西
# 只读输入；写出 evidence/cross_source_exchange.json
import collections, csv, json, os, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")


def main():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    lot_items, shop_items = collections.Counter(), collections.Counter()
    for L in idx["lots"]:
        for s in L["slots"]:
            lot_items[str(s["item_id"])] += 1
    for s in idx["shops"]:
        shop_items[str(s["equipId"])] += 1

    plan = list(csv.DictReader(open(os.path.join(DRY, "dryrun_swaps_by-item_shops.csv"), encoding="utf-8-sig")))

    def origin(iid):
        """物品的来源类型：lot / shop / both / unknown"""
        raw = iid.split(":")[-1]
        has_l, has_s = lot_items.get(raw, 0) > 0, shop_items.get(raw, 0) > 0
        return ("both" if has_l and has_s else "lot_only" if has_l else "shop_only" if has_s else "unknown")

    cross = collections.Counter()
    examples = {"drop_got_shop_only": [], "shop_got_lot_only": []}
    for p in plan:
        new_iid = p["new_item_id"]
        o_new = origin(new_iid)
        o_old = origin(p["group_item"])
        is_lot_cell = p["source_table"] != "ShopLineupParam"
        if is_lot_cell and o_new == "shop_only":
            cross["掉落点 → 商店专属物品"] += 1
            if len(examples["drop_got_shop_only"]) < 5:
                examples["drop_got_shop_only"].append({"slot": f"{p['source_table']}:{p['row_id']}:s{p['slot']}",
                                                       "old": f"{p['group_item']} {p['old_name'] if 'old_name' in p else ''}",
                                                       "new": f"{new_iid} {p['new_name']}", "row_name": p["row_name"][:52]})
        if (not is_lot_cell) and o_new == "lot_only":
            cross["商店行 → 仅掉落物品"] += 1
            if len(examples["shop_got_lot_only"]) < 5:
                examples["shop_got_lot_only"].append({"slot": f"ShopLineupParam:{p['row_id']}",
                                                      "new": f"{new_iid} {p['new_name']}", "row_name": p["row_name"][:52]})
    total_lot_cells = sum(1 for p in plan if p["source_table"] != "ShopLineupParam")
    total_shop_cells = sum(1 for p in plan if p["source_table"] == "ShopLineupParam")
    both_pools = {p["subpool"] for p in plan}
    # 每个池里是否同时含 lot 组与 shop 组
    mix = collections.defaultdict(lambda: {"lot_groups": 0, "shop_groups": 0})
    for p in plan:
        key = "lot_groups" if p["source_table"] != "ShopLineupParam" else "shop_groups"
        mix[p["subpool"]][key] = max(mix[p["subpool"]][key], 1)
    mixed_pools = [k for k, v in mix.items() if v["lot_groups"] and v["shop_groups"]]

    out = {"lot_cells": total_lot_cells, "shop_cells": total_shop_cells,
           "cross_source": dict(cross), "examples": examples,
           "pools_total": len(both_pools), "pools_mixing_lot_and_shop": len(mixed_pools),
           "mixed_pool_names": sorted(mixed_pools)[:30]}
    json.dump(out, open(os.path.join(DRY, "evidence", "cross_source_exchange.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=== 跨来源交换（当前默认口径的置换表）===")
    print(f"  参与位置：Lot 槽 {total_lot_cells} 个 / 商店行 {total_shop_cells} 个")
    print(f"  同时含'掉落组'与'商店组'的子池：{len(mixed_pools)} / {len(both_pools)} → {sorted(mixed_pools)[:8]} …")
    print()
    for k, v in cross.items():
        print(f"  {k}: {v} 处")
    print()
    print("=== 样例：掉落点拿到了'只有商店卖'的东西 ===")
    for e in examples["drop_got_shop_only"]:
        print(f"   {e['slot']:<38} → {e['new']:<22} | {e['row_name']}")
    print("=== 样例：商店行卖起了'只在掉落点的东西' ===")
    for e in examples["shop_got_lot_only"]:
        print(f"   {e['slot']:<28} → {e['new']:<22} | {e['row_name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
