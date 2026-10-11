# seed_sweep_byitem.py — 默认口径（按物品 M1，商店参与）的 200 种子分布体检
# 关注点：
#   ① 每轮置换量是否稳定（318 处）
#   ② 组内一致是否每轮都成立（同一物品的所有获取处拿同一个新物品）
#   ③ 逐格收件的可换面：M1 下每格只能收到"同处数层"里除自己以外的物品 → 按各自可换面归一后应接近 1
#   ④ 是否出现"原地不动"（除 22 件处数独一无二者之外）
# 只读输入；只写本目录。
import collections, csv, json, math, os, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun_by_item as BI

N_SEEDS = 200
MODE = "M1"


def main():
    overlay, idx, shops = BI.load()
    pools = BI.build_groups(overlay, idx, shops, True, False)      # 开商店 + 幽影分池

    # 每个物品 → 其所在"处数层"成员
    stratum_of = {}
    for sub, pool in pools.items():
        st = collections.defaultdict(list)
        for k, v in pool.items():
            st[len(v["cells"])].append(k)
        for size, mem in st.items():
            for k in mem:
                stratum_of[(sub, k)] = mem
    cell2group = {}
    for sub, pool in pools.items():
        for k, v in pool.items():
            for c in v["cells"]:
                cell2group[(sub, c["source_table"], c["row_id"], c["slot"])] = k

    recv = collections.defaultdict(collections.Counter)
    per_seed, consistency_ok = [], True
    for seed in range(N_SEEDS):
        grp_new = collections.defaultdict(set)
        cells = 0
        for sub, pool in pools.items():
            for p in BI.permute_items(pool, seed, MODE):
                key = (sub, p["source_table"], p["row_id"], p["slot"])
                recv[key][p["new_item_id"]] += 1
                grp_new[(sub, p["group_item"])].add(p["new_item_id"])
                cells += 1
        if any(len(v) != 1 for v in grp_new.values()):
            consistency_ok = False
        moved = sum(1 for k, c in recv.items() if len(c) > 1)
        per_seed.append({"seed": seed, "cells": cells, "groups": len(grp_new),
                         "groups_consistent": all(len(v) == 1 for v in grp_new.values()),
                         "cells_that_moved_this_seed": moved})

    rows, ratios, singleton_cells = [], [], 0
    for key, cnt in recv.items():
        sub = key[0]
        gi = cell2group[key]
        allowed = [m for m in stratum_of[(sub, gi)] if m != gi]
        k = len(allowed)
        tot = sum(cnt.values())
        pr = [v / tot for v in cnt.values()]
        h = -sum(x * math.log(x) for x in pr if x > 0)
        if k <= 1:
            singleton_cells += 1
            ratio = ""
        else:
            ratio = h / math.log(k)
            ratios.append(ratio)
        rows.append({"subpool": sub, "source_table": key[1], "row_id": key[2], "slot": key[3],
                     "group_item": gi, "stratum_size": k + 1, "allowed_items": k, "seeds": tot,
                     "distinct_received": len(cnt), "coverage_of_allowed": round(len(cnt) / k, 4) if k else "",
                     "mean_entropy": round(h, 4), "max_entropy": round(math.log(k), 4) if k > 1 else "",
                     "uniformity_ratio": round(ratio, 4) if ratio != "" else "",
                     "min_share": round(min(pr), 4), "max_share": round(max(pr), 4),
                     "ideal_share": round(1 / k, 4) if k else ""})

    with open(os.path.join(DRY, "seed_sweep_byitem_cells.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(DRY, "seed_sweep_byitem_summary.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_seed[0].keys()))
        w.writeheader()
        w.writerows(per_seed)

    by_pool = collections.defaultdict(list)
    for r in rows:
        if r["uniformity_ratio"] != "":
            by_pool[r["subpool"]].append(r["uniformity_ratio"])
    agg = {
        "config": {"mode": MODE, "with_shops": True, "merge_shadow": False, "seeds": N_SEEDS},
        "cells_per_seed": sorted({s["cells"] for s in per_seed}),
        "groups_per_seed": sorted({s["groups"] for s in per_seed}),
        "group_consistency_all_seeds": consistency_ok,
        "singleton_stratum_cells": singleton_cells,
        "uniformity": {"mean": round(sum(ratios) / len(ratios), 4), "min": round(min(ratios), 4),
                       "max": round(max(ratios), 4),
                       "cells_below_0.98": sum(1 for x in ratios if x < 0.98), "cells_compared": len(ratios)},
        "coverage": {"mean_coverage_of_allowed": round(sum(r["coverage_of_allowed"] for r in rows if r["coverage_of_allowed"] != "") /
                                                       max(1, sum(1 for r in rows if r["coverage_of_allowed"] != "")), 4),
                     "cells_seeing_all_allowed": sum(1 for r in rows if r["coverage_of_allowed"] == 1)},
        "per_pool_uniformity_mean": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_pool.items())},
    }
    json.dump(agg, open(os.path.join(DRY, "evidence", "seed_sweep_byitem.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"=== 默认口径体检：mode={MODE} shops=on，种子 0..{N_SEEDS-1} ===")
    print("  每轮：格子", agg["cells_per_seed"], "组", agg["groups_per_seed"])
    print("  组内一致（每一轮都成立）:", agg["group_consistency_all_seeds"])
    print(f"  均匀性（按各自可换面归一）: 均值 {agg['uniformity']['mean']}  最低 {agg['uniformity']['min']}  最高 {agg['uniformity']['max']}  "
          f"低于 0.98 的格子 {agg['uniformity']['cells_below_0.98']} / {agg['uniformity']['cells_compared']}")
    print(f"  覆盖度：平均见过可换面的 {agg['coverage']['mean_coverage_of_allowed']*100:.1f}%，其中 {agg['coverage']['cells_seeing_all_allowed']} 个格子见过全部可选物品")
    print(f"  从不更换的格子（处数独一无二的层）: {singleton_cells} 个")
    print()
    print("=== 各子池的均匀性均值 ===")
    for k, v in agg["per_pool_uniformity_mean"].items():
        print(f"   {k:<26} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
