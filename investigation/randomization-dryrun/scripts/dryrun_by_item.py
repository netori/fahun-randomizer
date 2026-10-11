# dryrun_by_item.py — 「按物品」置换原型：同一物品的所有获取处 = 一组，整组换成同一个新物品
#
# 用户要求：某个物品在 N 处都能获得时，随机化后替换它的物品也必须在这 N 处都出现（组内一致）。
#
# 两种口径：
#   M1 同规模内换（推荐）：只让"可获取处数相同"的物品互相替换
#        → 组内一致 ✔；每个物品的可获取处数保持不变 ✔；代价：某规模层里只有 1 个物品时它换不了
#   M2 全池换：池内任意物品互相替换
#        → 组内一致 ✔；"处数"这个属性会在物品之间转移（处数的多重集合仍不变）；全部物品都能换
#
# 只读输入；只写本目录；不写回 MOD。
import csv, json, os, random, collections, math, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WANT = {"protector": "3", "goods": "1"}
SEED = 20261010
N_SEEDS = 200


def load():
    overlay = [x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig"))]
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    return overlay, idx, shops


def build_groups(overlay, idx, shops, with_shops, merge):
    """返回 {subpool: {item_id: {'name':.., 'cells':[..]}}}"""
    lot_cells = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot_cells[str(s["item_id"])].append({"source_table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                                 "category": str(s["category"]), "quantity": str(s.get("num", "")),
                                                 "row_get_flag": str(L.get("getItemFlagId", "")), "row_name": L.get("row_name", ""),
                                                 "kind": "lot"})
    shop_cells = collections.defaultdict(list)
    for r in shops:
        if r["quality"] != "clean" or r["is_starter_set_piece"]:
            continue
        shop_cells[str(r["equipId"])].append({"source_table": "ShopLineupParam", "row_id": str(r["shop_row_id"]), "slot": "",
                                              "category": r["equipType"], "quantity": r["stock"], "row_get_flag": "",
                                              "row_name": f"shop row {r['shop_row_id']}（{r['name_cn']} 价 {r['price']}）", "kind": "shop"})

    pools = collections.defaultdict(dict)          # subpool -> item_id -> info
    def subpool_for(cat, part, tier):
        if cat == "protector":
            return "armor:" + part
        if cat == "goods":
            return "rune:" + ("大师级" if (merge and tier.startswith("大师级")) else tier)
        return None

    # (a) 已批准候选（防具 7 + 卢恩 90）：Lot 槽是主入口；开了商店就把它的商店行也纳入同一组
    # 注意：身份 = (类别, item_id)——同一 id 在武器表/防具表可能撞号（如 5020000）
    for it in overlay:
        if it["row_kind"] != "item" or it["final_decision"] != "approved":
            continue
        cat, iid = it["category"], it["item_id"]
        if cat not in WANT:
            continue
        sub = subpool_for(cat, it["part"], it["rune_tier"])
        cells = [c for c in lot_cells.get(iid, []) if c["category"] == WANT[cat]]
        if with_shops:
            cells += [c for c in shop_cells.get(iid, []) if c["category"] == WANT[cat]]
        if cells:
            pools[sub][f"{cat}:{iid}"] = {"name": it["name_cn"], "part": it["part"], "tier": it["rune_tier"],
                                          "cells": cells, "origin": "approved"}
    # (b) 商店单品（开商店时借入）：它的全部 clean 商店行 = 一组
    if with_shops:
        for iid, cells in shop_cells.items():
            rows_by_cat = collections.defaultdict(list)
            for c in cells:
                rows_by_cat[c["category"]].append(c)
            for cat_id, cat_cells in rows_by_cat.items():
                if cat_id not in ("0", "1"):
                    continue
                row = next((r for r in shops if str(r["shop_row_id"]) == cat_cells[0]["row_id"]), None)
                if row is None:
                    continue
                cat = "protector" if cat_id == "1" else "weapon"
                if cat == "protector" and row.get("part"):
                    sub = "armor:" + row["part"]
                elif cat == "weapon" and row.get("weaponCategory"):
                    sub = "weapon:category=" + row["weaponCategory"]
                else:
                    continue
                pools.setdefault(sub, {})
                pools[sub][f"{cat}:{iid}"] = {"name": row["name_cn"], "part": row.get("part", ""), "tier": "",
                                              "cells": list(cat_cells), "origin": "shop"}
    return pools


def permute_items(pool, seed, mode):
    """把"物品"分配给"位置组"：组 S_i 收到物品 π(i)，组内所有格子都换成 π(i)。"""
    rng = random.Random(seed)
    items = sorted(pool.keys(), key=lambda k: (k.split(":")[0], int(k.split(":")[1])))   # 身份 = 类别:id
    groups = {i: pool[i]["cells"] for i in items}
    sizes = {i: len(groups[i]) for i in items}
    assign = {}
    if mode in ("M1", "M1MIX"):
        strata = collections.defaultdict(list)
        for i in items:
            strata[sizes[i]].append(i)
        singles, multi = [], []
        for k, members in sorted(strata.items()):
            (multi if len(members) >= 2 else singles).extend(members)
        for members in [m for m in strata.values() if len(m) >= 2]:
            src = members[:]
            for _ in range(500):
                cand = src[:]
                rng.shuffle(cand)
                if all(cand[j] != members[j] for j in range(len(members))):
                    break
            for j, m in enumerate(members):
                assign[m] = cand[j]
        if mode == "M1":
            for m in singles:
                assign[m] = m                                   # 处数独一无二 → 只能保持原样
        else:                                                    # M1MIX：把这些物品放进混合层
            if len(singles) >= 2:
                src = singles[:]
                for _ in range(500):
                    cand = src[:]
                    rng.shuffle(cand)
                    if all(cand[j] != singles[j] for j in range(len(singles))):
                        break
                for j, m in enumerate(singles):
                    assign[m] = cand[j]
            elif singles:                                        # 只剩 1 个 → 并入最大的规模层（接受处数转移）
                for m in singles:
                    big = max(strata.values(), key=len)
                    members = big + [m]
                    src = members[:]
                    for _ in range(500):
                        cand = src[:]
                        rng.shuffle(cand)
                        if all(cand[j] != members[j] for j in range(len(members))):
                            break
                    for j, mm in enumerate(members):
                        assign[mm] = cand[j]
    else:  # M2：全池置换
        src = items[:]
        for _ in range(500):
            cand = src[:]
            rng.shuffle(cand)
            if all(cand[j] != items[j] for j in range(len(items))):
                break
        for j, m in enumerate(items):
            assign[m] = cand[j]
    plan = []
    for m in items:
        new_id = assign[m]
        for c in groups[m]:
            plan.append({**c, "group_item": m, "group_size": sizes[m], "new_item_id": new_id,
                         "new_name": pool[new_id]["name"], "old_name": pool[m]["name"], "subpool": None})
    return plan


def main():
    overlay, idx, shops = load()
    results = {}
    for label, with_shops, merge in (("lot_only_M1", False, False), ("lot_only_M2", False, False),
                                     ("shop_M1", True, False), ("shop_M2", True, False)):
        mode = label.split("_")[-1]
        pools = build_groups(overlay, idx, shops, with_shops, merge)
        plan_all, per_pool = [], {}
        for sub, pool in sorted(pools.items()):
            pl = permute_items(pool, SEED, mode)
            for p in pl:
                p["subpool"] = sub
            plan_all += pl
            grp_sizes = collections.Counter(len(v["cells"]) for v in pool.values())
            per_pool[sub] = {"items": len(pool), "cells": sum(len(v["cells"]) for v in pool.values()),
                             "items_with_multi_cells": sum(1 for v in pool.values() if len(v["cells"]) > 1),
                             "size_strata": dict(sorted(grp_sizes.items()))}
        # 校验
        by_group = collections.defaultdict(set)
        for p in plan_all:
            by_group[(p["subpool"], p["group_item"])].add(p["new_item_id"])
        consistency = all(len(v) == 1 for v in by_group.values())
        avail_preserved = True
        for sub, pool in pools.items():
            size_of_new = collections.defaultdict(int)
            for p in plan_all:
                if p["subpool"] == sub:
                    size_of_new[p["new_item_id"]] = p["group_size"]
            for iid, info in pool.items():
                if size_of_new.get(iid, len(info["cells"])) != len(info["cells"]):
                    avail_preserved = False
        unchanged_items = sorted({p["group_item"] for p in plan_all if p["group_item"] == p["new_item_id"]})
        # 多轮种子：逐格统计"收到过哪些新物品"的均匀性
        recv_all = collections.defaultdict(collections.Counter)
        for seed in range(min(N_SEEDS, 60)):
            for sub, pool in pools.items():
                for p in permute_items(pool, seed, mode):
                    recv_all[(sub, p["source_table"], p["row_id"], p["slot"])][p["new_item_id"]] += 1
        ratios = []
        for key, cnt in recv_all.items():
            sub = key[0]
            mx = math.log(max(len(pools[sub]) - 1, 1))
            tot = sum(cnt.values())
            pr = [v / tot for v in cnt.values()]
            h = -sum(x * math.log(x) for x in pr if x > 0)
            if mx > 0:
                ratios.append(h / mx)
        results[label] = {"with_shops": with_shops, "mode": mode,
                          "pools": per_pool,
                          "cells_total": len(plan_all),
                          "items_total": sum(v["items"] for v in per_pool.values()),
                          "group_consistency_ok": consistency,
                          "availability_preserved": avail_preserved,
                          "items_left_unchanged": unchanged_items,
                          "items_left_unchanged_count": len(unchanged_items),
                          "uniformity_mean_60seeds": round(sum(ratios) / len(ratios), 4) if ratios else ""}
        if label == "shop_M1":
            cols = ["subpool", "group_item", "old_name", "group_size", "new_item_id", "new_name",
                    "source_table", "row_id", "slot", "row_name"]
            with open(os.path.join(DRY, "dryrun_by_item_M1.csv"), "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for p in sorted(plan_all, key=lambda x: (x["subpool"], x["group_item"])):
                    w.writerow({k: p.get(k, "") for k in cols})

    json.dump(results, open(os.path.join(DRY, "evidence", "by_item_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("=== 按物品置换：两种口径 × 商店开关 ===")
    for k, v in results.items():
        print(f"\n-- {k}: 物品 {v['items_total']} 件 / 涉及格子 {v['cells_total']} 个")
        print(f"   组内一致(同一组的格子都换成同一物品): {v['group_consistency_ok']}")
        print(f"   可获取处数是否保持不变: {v['availability_preserved']}")
        print(f"   换不动的物品: {v['items_left_unchanged_count']} 件 {v['items_left_unchanged'][:12]}")
        print(f"   均匀性(60 种子均值): {v['uniformity_mean_60seeds']}")
        for sub, s in v["pools"].items():
            print(f"      {sub:<26} 物品 {s['items']:>3} / 格子 {s['cells']:>3} / 多处可得的物品 {s['items_with_multi_cells']:>2} / 处数分布 {s['size_strata']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
