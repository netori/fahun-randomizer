# dryrun.py — 随机化干跑（不写回 MOD）· 统一入口
#
# 随机化单位（默认 = 按物品 M1，符合"多处可得的物品保持一致"的要求）：
#   --mode by-item（默认）：把同一物品(类别:id)的所有获取处绑成一组，整组换成同一个新物品
#        · 默认口径 M1：只在"可获取处数相同"的物品之间换 → 组内一致 ✔ 且每件物品的"处数"不变 ✔
#        · --mixed-strata：让"处数独一无二"的物品也参与（并入同池最大层，接受这些物品的处数发生变化）
#   --mode by-row：旧的按行/按槽口径（保留用于对照；会有同一物品在不同商店不一致的情况）
#
# 其它开关：--with-shops（商店路径，默认关）、--merge-shadow（幽影并入大师级，默认关）、--seed、--out
# 不做：不写回 MOD、不写注入代码、不改数量·权重·价格·库存·领取flag·解锁条件·事件、不动未列出的 slot
import argparse, csv, json, os, random, collections, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun_by_item as BI
WANT = {"protector": "3", "goods": "1"}


def load_overlay():
    return [x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig"))]


def load_index_slots():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    out = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            out[str(s["item_id"])].append({"source_table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                           "category": str(s["category"]), "quantity": str(s.get("num", "")),
                                           "base_point": str(s.get("base_point", "")),
                                           "cumulate_lot_point": str(s.get("cumulate_lot_point", "")),
                                           "row_get_flag": str(L.get("getItemFlagId", "")), "row_name": L.get("row_name", "")})
    return idx, out


# ---------- 按行（旧口径，对照用） ----------
def lot_cells(overlay, slots, merge):
    pools = collections.defaultdict(list)
    for it in overlay:
        if it["row_kind"] != "item" or it["final_decision"] != "approved":
            continue
        cat = it["category"]
        if cat not in WANT:
            continue
        for s in slots.get(it["item_id"], []):
            if s["category"] != WANT[cat]:
                continue
            sub = ("armor:" + it["part"]) if cat == "protector" else \
                  ("rune:" + ("大师级" if (merge and it["rune_tier"].startswith("大师级")) else it["rune_tier"]))
            pools[sub].append({"item_id": it["item_id"], "name_cn": it["name_cn"], "category": cat, "part": it["part"],
                               "rune_tier": it["rune_tier"], "rune_school": it["rune_school"], **s})
    return pools


def shop_cells(shop_rows, merge):
    pools, skipped = collections.defaultdict(list), collections.Counter()
    for r in shop_rows:
        if r["quality"] != "clean":
            skipped["semantics_unverified"] += 1
            continue
        if r["is_starter_set_piece"]:
            skipped["frozen_starter_set"] += 1
            continue
        if r["equip_type_name"] == "protector" and r["part"]:
            sub = "armor:" + r["part"]
        elif r["equip_type_name"] == "weapon" and r["weaponCategory"]:
            sub = "weapon:category=" + r["weaponCategory"]
        else:
            skipped["other_or_unknown"] += 1
            continue
        pools[sub].append({"item_id": r["equipId"], "name_cn": r["name_cn"],
                           "category": "protector" if r["equip_type_name"] == "protector" else "weapon",
                           "part": r["part"], "rune_tier": "", "rune_school": "",
                           "source_table": "ShopLineupParam", "row_id": r["shop_row_id"], "slot": "",
                           "category_field": r["equipType"], "quantity": r["stock"], "base_point": "",
                           "cumulate_lot_point": "", "row_get_flag": "",
                           "row_name": f"shop row {r['shop_row_id']}（价 {r['price']}/库存 {r['stock']}）"})
    return pools, skipped


def permute_rows(pools, seed):
    rng = random.Random(seed)
    plan, skipped = [], []
    for sub, cs in sorted(pools.items()):
        if len(cs) < 2:
            skipped.append({"subpool": sub, "cells": len(cs)})
            continue
        orig = [c["item_id"] for c in cs]
        for _ in range(500):
            cand = orig[:]
            rng.shuffle(cand)
            if all(cand[i] != orig[i] for i in range(len(cs))):
                break
        name = {c["item_id"]: c["name_cn"] for c in cs}
        for c, nid in zip(cs, cand):
            plan.append({**c, "new_item_id": nid, "new_name_cn": name.get(nid, ""), "subpool": sub,
                         "group_item": c["item_id"], "group_size": 1, "unchanged": nid == c["item_id"]})
    return plan, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["by-item", "by-row"], default="by-item")
    ap.add_argument("--mixed-strata", action="store_true", help="按物品口径下，让'处数独一无二'的物品也参与")
    ap.add_argument("--merge-shadow", action="store_true", help="D4：幽影卢恩并入 rune:大师级")
    ap.add_argument("--with-shops", action="store_true", help="D3：把商店可售候选纳入目标池")
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--out", default="")
    ns = ap.parse_args()

    overlay = load_overlay()
    idx, slots = load_index_slots()
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"] if ns.with_shops else []

    if ns.mode == "by-item":
        mode = "M1MIX" if ns.mixed_strata else "M1"
        pools = BI.build_groups(overlay, idx, shops, ns.with_shops, ns.merge_shadow)
        plan, per_pool = [], {}
        for sub, pool in sorted(pools.items()):
            pl = BI.permute_items(pool, ns.seed, mode)
            for p in pl:
                p["subpool"] = sub
            plan += pl
            per_pool[sub] = {"items": len(pool), "cells": sum(len(v["cells"]) for v in pool.values()),
                             "multi_cell_items": sum(1 for v in pool.values() if len(v["cells"]) > 1)}
        item_id_of = {}          # (subpool, 组物品) -> 显示用 id
        name_of = {}
        for sub, pool in pools.items():
            for k, v in pool.items():
                item_id_of[(sub, k)] = k.split(":")[1]
                name_of[(sub, k)] = v["name"]
        # 组内一致 & 处数保持
        grp = collections.defaultdict(set)
        for p in plan:
            grp[(p["subpool"], p["group_item"])].add(p["new_item_id"])
        consistency = all(len(v) == 1 for v in grp.values())
        avail_ok = True
        for sub, pool in pools.items():
            for k, v in pool.items():
                got = next((x["new_item_id"] for x in plan if x["subpool"] == sub and x["group_item"] == k), None)
                new_size = len(pool[got]["cells"]) if got in pool else len(v["cells"])
                if new_size != len(v["cells"]):
                    avail_ok = False
        unchanged_groups = sorted({k for sub, pool in pools.items() for k in pool
                                   if all(x["group_item"] == x["new_item_id"] for x in plan if x["subpool"] == sub and x["group_item"] == k)})
        checks = {"mode": mode, "subpools": len(pools), "items": sum(len(v) for v in pools.values()),
                  "cells_total": sum(len(info["cells"]) for pool in pools.values() for info in pool.values()),
                  "cells_in_plan": len(plan),
                  "group_consistency_ok": consistency, "availability_preserved": avail_ok,
                  "items_left_unchanged": len(unchanged_groups),
                  "items_left_unchanged_list": unchanged_groups[:40], "per_pool": per_pool}
        cols = ["subpool", "group_item", "group_size", "new_item_id", "new_name", "source_table", "row_id", "slot", "row_name"]
        rows = [{"subpool": p["subpool"], "group_item": p["group_item"], "group_size": p["group_size"],
                 "new_item_id": p["new_item_id"], "new_name": p["new_name"], "source_table": p["source_table"],
                 "row_id": p["row_id"], "slot": p["slot"], "row_name": p["row_name"]} for p in plan]
    else:
        pools = lot_cells(overlay, slots, ns.merge_shadow)
        shop_skipped = {}
        if ns.with_shops:
            sp, shop_skipped = shop_cells(shops, ns.merge_shadow)
            for k, v in sp.items():
                pools.setdefault(k, []).extend(v)
        plan, skipped = permute_rows(pools, ns.seed)
        checks = {"mode": "by-row", "subpools": len(pools), "cells_total": sum(len(v) for v in pools.values()),
                  "cells_in_plan": len(plan), "subpools_too_small": skipped, "shop_rows_skipped": shop_skipped,
                  "no_slot_duplicated": len({(p["source_table"], p["row_id"], p["slot"]) for p in plan}) == len(plan)}
        cols = ["subpool", "group_item", "group_size", "new_item_id", "new_name_cn", "source_table", "row_id", "slot", "row_name"]
        rows = [{"subpool": p["subpool"], "group_item": p["item_id"], "group_size": 1, "new_item_id": p["new_item_id"],
                 "new_name_cn": p["new_name_cn"], "source_table": p["source_table"], "row_id": p["row_id"],
                 "slot": p["slot"], "row_name": p["row_name"]} for p in plan]

    frozen = {x["item_id"] for x in overlay if x.get("user_rule_applied") in ("D1_USER_RULE_GLIMMER_RUNE", "D5_STARTER_SET_FROZEN")}
    checks["no_frozen_used"] = not any(p["new_item_id"].split(":")[-1] in frozen for p in plan)
    out = ns.out or f"dryrun_swaps_{ns.mode}{'_mixed' if ns.mixed_strata else ''}{'_shops' if ns.with_shops else ''}{'_merge' if ns.merge_shadow else ''}.csv"
    with open(os.path.join(DRY, out), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["subpool"], x["source_table"], x["row_id"], x["slot"])):
            w.writerow({k: r.get(k, "") for k in cols})

    print(f"=== 干跑 mode={ns.mode} mixed_strata={ns.mixed_strata} shops={ns.with_shops} merge_shadow={ns.merge_shadow} seed={ns.seed} ===")
    for k, v in checks.items():
        if k not in ("items_left_unchanged_list", "per_pool", "subpools_too_small"):
            print(f"   {k}: {v}")
    if "items_left_unchanged_list" in checks:
        print("   换不动的物品:", checks["items_left_unchanged_list"])
    if "subpools_too_small" in checks:
        print("   单件池（不换）:", checks["subpools_too_small"])
    print("   写出:", out)
    json.dump(checks, open(os.path.join(DRY, "evidence", "dryrun_last_run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
