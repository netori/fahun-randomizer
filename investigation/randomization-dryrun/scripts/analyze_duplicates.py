# analyze_duplicates.py — 多轮种子体检的补充：定位"打不散"的槽与原因（重复商店行）
# 数学条件：一个多重集合能做「完全不留原地」的置换，当且仅当任一物品占用的槽位数 ≤ n/2。
# 超过这个条件时，代码会退回普通洗牌（可能有槽保持原样）——本脚本把这类池/槽全部列出来。
import csv, json, math, os, sys, collections

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun as D

N_SEEDS = 200
MERGE, WITH_SHOPS = False, True


def main():
    overlay = D.load_overlay()
    idx, slots = D.load_index_slots()
    pools = D.lot_cells(overlay, slots, MERGE)
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    sp, _ = D.shop_cells(shops, set(), MERGE)
    for k, v in sp.items():
        pools.setdefault(k, []).extend(v)

    pool_stat = {}
    dup_items = []
    for sub, cs in sorted(pools.items()):
        n = len(cs)
        cnt = collections.Counter(c["item_id"] for c in cs)
        mx_item, mx = (cnt.most_common(1)[0] if cnt else ("", 0))   # most_common → (item, count)
        names = {c["item_id"]: c["name_cn"] for c in cs}
        feasible = (mx <= n - mx) if n else True          # 等价于 mx <= n/2
        pool_stat[sub] = {"cells": n, "distinct_items": len(cnt), "max_dup": mx, "max_dup_item": mx_item,
                          "max_dup_item_name": names.get(mx_item, ""), "full_derangement_feasible": feasible,
                          "ideal_share": round(1 / (n - 1), 4) if n > 1 else ""}
        for iid, c in cnt.items():
            if c > 1:
                dup_items.append({"subpool": sub, "item_id": iid, "name_cn": names.get(iid, ""), "cells": c,
                                  "cells_list": [f"{x['source_table']}:{x['row_id']}" for x in cs if x["item_id"] == iid]})

    # 200 种子：逐槽统计
    stat = collections.defaultdict(lambda: {"seeds": 0, "unchanged": 0, "received": collections.Counter()})
    for seed in range(N_SEEDS):
        plan, _ = D.permute(pools, seed)
        for p in plan:
            k = (p["subpool"], p["source_table"], p["row_id"], p["slot"])
            stat[k]["seeds"] += 1
            stat[k]["received"][p["new_item_id"]] += 1
            if p["unchanged"]:
                stat[k]["unchanged"] += 1

    problem_rows = []
    for k, s in stat.items():
        sub = k[0]
        n = pool_stat[sub]["cells"]
        max_h = math.log(max(n - 1, 1)) if n > 1 else 0.0
        tot = sum(s["received"].values())
        probs = [v / tot for v in s["received"].values()] if tot else []
        h = -sum(p * math.log(p) for p in probs if p > 0)
        ratio = (h / max_h) if max_h > 0 else ""
        if s["unchanged"] > 0 or (ratio != "" and ratio < 0.95):
            problem_rows.append({"subpool": sub, "source_table": k[1], "row_id": k[2], "slot": k[3],
                                 "cells_in_pool": n, "distinct_items_in_pool": pool_stat[sub]["distinct_items"],
                                 "max_dup": pool_stat[sub]["max_dup"], "full_derangement_feasible": pool_stat[sub]["full_derangement_feasible"],
                                 "seeds_unchanged": s["unchanged"], "distinct_items_received": len(s["received"]),
                                 "uniformity_ratio": round(ratio, 4) if ratio != "" else ""})

    with open(os.path.join(DRY, "seed_sweep_problem_cells.csv"), "w", encoding="utf-8-sig", newline="") as f:
        cols = list(problem_rows[0].keys()) if problem_rows else ["subpool", "source_table", "row_id", "slot"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(problem_rows)

    infeasible = {k: v for k, v in pool_stat.items() if not v["full_derangement_feasible"]}
    out = {"config": {"with_shops": WITH_SHOPS, "merge_shadow": MERGE, "seeds": N_SEEDS},
           "pool_statistics": pool_stat,
           "duplicated_items": dup_items,
           "infeasible_pools": infeasible,
           "problem_cells": problem_rows,
           "summary": {
               "pools_total": len(pool_stat),
               "pools_with_duplicates": len({d["subpool"] for d in dup_items}),
               "pools_unable_to_fully_derange": len(infeasible),
               "cells_unable_to_fully_derange": sum(v["cells"] for v in infeasible.values()),
               "cells_ever_unchanged": sum(1 for s in stat.values() if s["unchanged"] > 0),
               "problem_cells_below_0.95_or_unchanged": len(problem_rows)}}
    json.dump(out, open(os.path.join(DRY, "evidence", "pool_dedup_analysis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=== 池级：重复与可行性 ===")
    for sub, v in sorted(pool_stat.items()):
        flag = "可完全打散" if v["full_derangement_feasible"] else f"**不可完全打散**（{v['max_dup_item']} {v['max_dup_item_name']} 占 {v['max_dup']}/{v['cells']}）"
        print(f"  {sub:<26} 槽 {v['cells']:>3} / 不同物品 {v['distinct_items']:>3}  {flag}")
    print()
    print("=== 重复条目（同一物品占多行）top ===")
    for d in sorted(dup_items, key=lambda x: -x["cells"])[:12]:
        print(f"  {d['subpool']:<22} {d['item_id']:<9} {d['name_cn'][:12]:<13} 占 {d['cells']} 行: {d['cells_list'][:4]}")
    print()
    print("=== 汇总 ===")
    print(f"  池 {out['summary']['pools_total']} 个；含重复的池 {out['summary']['pools_with_duplicates']} 个；"
          f"无法完全打散的池 {out['summary']['pools_unable_to_fully_derange']} 个（涉及 {out['summary']['cells_unable_to_fully_derange']} 槽）")
    print(f"  200 种子里出现过'原地不动'的槽：{out['summary']['cells_ever_unchanged']} 个；均匀性<0.95 或曾不动的槽合计 {out['summary']['problem_cells_below_0.95_or_unchanged']} 个")
    print("写出 seed_sweep_problem_cells.csv 与 evidence/pool_dedup_analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
