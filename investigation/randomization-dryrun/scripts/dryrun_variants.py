# dryrun_variants.py — 干跑变体矩阵：D4（幽影合并/分池）× D3（商店开/关）
# 只读输入；只写本目录。不做任何写回。
# 变体说明：
#   base       : 仅当前 approved（防具 7 + 卢恩 90），幽影独立成池，商店不参与
#   merge      : base + 幽影并入 rune:大师级（D4 = 合并模式）
#   shop       : base + 「商店可售候选」（语义 clean、非初始套装件）作为额外物品/槽位
#   shop_merge : shop + merge
import csv, json, os, random, collections, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
SEED = 20261010
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
                                           "base_point": str(s.get("base_point", "")), "row_get_flag": str(L.get("getItemFlagId", "")),
                                           "row_name": L.get("row_name", "")})
    return idx, out


def subpool_of(cat, part, tier, merge):
    if cat == "protector":
        return "armor:" + part
    if cat == "goods":
        return "rune:" + ("大师级" if (merge and tier.startswith("大师级")) else tier)
    if cat == "weapon":
        return None  # 由调用方补 weapon:category=N
    return None


def cells_from_lots(overlay, slots, merge):
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
            pools[subpool_of(cat, it["part"], it["rune_tier"], merge)].append(
                {"item_id": it["item_id"], "name_cn": it["name_cn"], "category": cat, "part": it["part"],
                 "rune_tier": it["rune_tier"], "rune_school": it["rune_school"], **s})
    return pools


def cells_from_shops(shop_rows, part_map, frozen, merge):
    """商店可售候选：只取语义 clean、非初始套装件、且类别属于 武器/防具"""
    pools = collections.defaultdict(list)
    skipped = collections.Counter()
    for r in shop_rows:
        if r["quality"] != "clean":
            skipped["semantics_unverified"] += 1
            continue
        if r["is_starter_set_piece"]:
            skipped["frozen_starter_set"] += 1
            continue
        if r["equip_type_name"] == "protector":
            part = r["part"] or part_map.get(r["equipId"], "")
            if not part:
                skipped["part_unknown"] += 1
                continue
            pools["armor:" + part].append({"item_id": r["equipId"], "name_cn": r["name_cn"], "category": "protector",
                                           "part": part, "rune_tier": "", "rune_school": "",
                                           "source_table": "ShopLineupParam", "row_id": r["shop_row_id"], "slot": "",
                                           "category_field": "1", "quantity": r["stock"], "base_point": "",
                                           "row_get_flag": "", "row_name": f"shop row {r['shop_row_id']}"})
        elif r["equip_type_name"] == "weapon":
            wc = r["weaponCategory"]
            if not wc:
                skipped["weaponCategory_unknown"] += 1
                continue
            pools["weapon:category=" + wc].append({"item_id": r["equipId"], "name_cn": r["name_cn"], "category": "weapon",
                                                   "part": "", "rune_tier": "", "rune_school": "",
                                                   "source_table": "ShopLineupParam", "row_id": r["shop_row_id"], "slot": "",
                                                   "category_field": "0", "quantity": r["stock"], "base_point": "",
                                                   "row_get_flag": "", "row_name": f"shop row {r['shop_row_id']}"})
        else:
            skipped["other_equip_type"] += 1
    return pools, skipped


def permute(pools, seed):
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
        name_of = {c["item_id"]: c["name_cn"] for c in cs}
        for c, nid in zip(cs, cand):
            plan.append({**c, "new_item_id": nid, "new_name_cn": name_of.get(nid, ""), "subpool": sub})
    return plan, skipped


def main():
    overlay = load_overlay()
    idx, slots = load_index_slots()
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    part_map = {r["equipId"]: r["part"] for r in shops if r["part"]}
    frozen = {x["item_id"] for x in overlay if x.get("user_rule_applied") == "D1_USER_RULE_GLIMMER_RUNE"}

    matrix = {}
    for name, use_shop, merge in (("base", False, False), ("merge", False, True),
                                  ("shop", True, False), ("shop_merge", True, True)):
        pools = cells_from_lots(overlay, slots, merge)
        skipped_shop = {}
        if use_shop:
            sp, skipped_shop = cells_from_shops(shops, part_map, frozen, merge)
            for k, v in sp.items():
                pools.setdefault(k, []).extend(v)
        plan, skipped = permute(pools, SEED)
        matrix[name] = {
            "with_shops": use_shop, "merge_shadow": merge,
            "subpools": {k: len(v) for k, v in sorted(pools.items())},
            "cells_total": sum(len(v) for v in pools.values()),
            "cells_permuted": len(plan),
            "subpools_too_small": skipped,
            "shop_rows_skipped": dict(skipped_shop),
        }
        print(f"=== {name}（shops={'on' if use_shop else 'off'}, merge_shadow={merge}）===")
        print(f"    子池 {len(pools)} 个 | 槽位合计 {matrix[name]['cells_total']} | 实际置换 {len(plan)}")
        for k, v in sorted(pools.items()):
            flag = "可换" if len(v) >= 2 else "不可换(单件)"
            print(f"      {k:<26} {len(v):>4} 槽  {flag}")
        if skipped_shop:
            print("    商店行被跳过:", skipped_shop)
        print()

    json.dump({"seed": SEED, "variants": matrix}, open(os.path.join(DRY, "dryrun_variants_matrix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 给「shop」变体落一份对照表，便于人工审查
    pools = cells_from_lots(overlay, slots, False)
    sp, _ = cells_from_shops(shops, part_map, frozen, False)
    for k, v in sp.items():
        pools.setdefault(k, []).extend(v)
    plan, _ = permute(pools, SEED)
    cols = ["subpool", "source_table", "row_id", "slot", "item_id", "name_cn", "new_item_id", "new_name_cn", "category", "part", "quantity", "row_name"]
    with open(os.path.join(DRY, "dryrun_swaps_shop_variant.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in sorted(plan, key=lambda x: (x["subpool"], x["source_table"], x["row_id"], x["slot"])):
            w.writerow({k: p.get(k, "") for k in cols})
    print("写出 dryrun_variants_matrix.json 与 dryrun_swaps_shop_variant.csv（含商店变体，仅作对照，未写回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
