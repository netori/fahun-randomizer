# seed_sweep.py — 多轮种子分布体检：配置固定为「开商店 + 幽影分池」（D3 on, D4 off）
# 目的：回答"多跑几轮会不会偏"——逐槽统计它收到过哪些物品、均匀性如何。
# 只读输入；只写本目录。不做任何写回。
import csv, json, math, os, sys, collections

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(DRY, "scripts")
sys.path.insert(0, SCRIPT_DIR)
import dryrun as D  # 复用干跑脚本里的取数/置换逻辑（含开关实现）

N_SEEDS = 200
MERGE = False
WITH_SHOPS = True


def cell_key(c):
    return (c["subpool"], c["source_table"], c["row_id"], c["slot"])


def main():
    overlay = D.load_overlay()
    idx, slots = D.load_index_slots()
    pools = D.lot_cells(overlay, slots, MERGE)
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    sp, _ = D.shop_cells(shops, set(), MERGE)
    for k, v in sp.items():
        pools.setdefault(k, []).extend(v)

    received = collections.defaultdict(collections.Counter)   # cell -> 收到的 new_item_id 计数
    used = collections.defaultdict(int)                      # item -> 被作为新物品使用次数
    visited = collections.defaultdict(set)                   # item -> 去过的槽
    per_seed = []
    for seed in range(N_SEEDS):
        plan, skipped = D.permute(pools, seed)
        for p in plan:
            key = (p["subpool"], p["source_table"], p["row_id"], p["slot"])
            received[key][p["new_item_id"]] += 1
            used[p["new_item_id"]] += 1
            visited[p["new_item_id"]].add(key)
        per_seed.append({"seed": seed, "cells_total": sum(len(v) for v in pools.values()), "cells_permuted": len(plan),
                         "subpools_too_small": [s["subpool"] for s in skipped],
                         "shop_rows_permuted": sum(1 for p in plan if p["source_table"] == "ShopLineupParam"),
                         "weapon_pool_permuted": sum(1 for p in plan if p["subpool"].startswith("weapon:")),
                         "any_unchanged": any(p["unchanged"] for p in plan)})

    # 逐槽分布指标
    rows = []
    n_items_by_pool = {sub: len({c["item_id"] for c in cs}) for sub, cs in pools.items()}
    for key, cnt in received.items():
        sub = key[0]
        n = n_items_by_pool.get(sub, 1)
        max_h = math.log(max(n - 1, 1)) if n > 1 else 0.0
        tot = sum(cnt.values())
        probs = [v / tot for v in cnt.values()] if tot else []
        h = -sum(p * math.log(p) for p in probs if p > 0)
        top_item, top_n = cnt.most_common(1)[0]
        rows.append({"subpool": sub, "source_table": key[1], "row_id": key[2], "slot": key[3],
                     "pool_items": n, "seeds": tot, "distinct_items_received": len(cnt),
                     "max_distinct_possible": max(n - 1, 1),
                     "mean_entropy": round(h, 4), "max_entropy": round(max_h, 4),
                     "uniformity_ratio": round(h / max_h, 4) if max_h > 0 else "",
                     "min_share": round(min(probs), 4) if probs else "",
                     "max_share": round(max(probs), 4) if probs else "",
                     "ideal_share": round(1 / (n - 1), 4) if n > 1 else "",
                     "most_common_item": top_item, "most_common_item_share": round(top_n / tot, 4) if tot else ""})

    with open(os.path.join(DRY, "seed_sweep_cell_distribution.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(DRY, "seed_sweep_summary.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_seed[0].keys()))
        w.writeheader()
        for r in per_seed:
            w.writerow({**r, "subpools_too_small": ";".join(r["subpools_too_small"])})

    ratios = [r["uniformity_ratio"] for r in rows if r["uniformity_ratio"] != ""]
    agg = {
        "config": {"with_shops": WITH_SHOPS, "merge_shadow": MERGE, "seeds": N_SEEDS},
        "cells": len(rows), "permuted_per_seed": sorted({r["cells_permuted"] for r in per_seed}),
        "shop_rows_per_seed": sorted({r["shop_rows_permuted"] for r in per_seed}),
        "weapon_pool_rows_per_seed": sorted({r["weapon_pool_permuted"] for r in per_seed}),
        "any_seed_with_unchanged_cell": any(r["any_unchanged"] for r in per_seed),
        "uniformity": {"min": min(ratios), "max": max(ratios), "mean": round(sum(ratios) / len(ratios), 4),
                       "cells_below_0.95": sum(1 for x in ratios if x < 0.95)},
        "distinct_coverage": {"cells_that_ever_saw_all_possible_items":
                              sum(1 for r in rows if r["distinct_items_received"] >= r["max_distinct_possible"]),
                              "cells_total": len(rows)},
        "items": {"distinct_items_used": len(used),
                  "min_times_used": min(used.values()), "max_times_used": max(used.values()),
                  "items_used_in_all_seeds": sum(1 for v in used.values() if v == N_SEEDS)},
    }
    json.dump(agg, open(os.path.join(DRY, "evidence", "seed_sweep_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"=== 配置：with_shops={WITH_SHOPS} merge_shadow={MERGE}，种子 0..{N_SEEDS-1} ===")
    print("  每次种子：置换", agg["permuted_per_seed"], "槽；其中商店行", agg["shop_rows_per_seed"], "；武器池", agg["weapon_pool_rows_per_seed"])
    print("  有没有出现过'原地不动'的槽：", agg["any_seed_with_unchanged_cell"])
    print("  均匀性（实际熵 / 理论最大熵）：min", agg["uniformity"]["min"], "mean", agg["uniformity"]["mean"], "max", agg["uniformity"]["max"],
          "| 低于 0.95 的槽数:", agg["uniformity"]["cells_below_0.95"])
    print("  覆盖度：见过池内所有可能物品的槽", agg["distinct_coverage"]["cells_that_ever_saw_all_possible_items"], "/", agg["distinct_coverage"]["cells_total"])
    print("  物品侧：参与物品", agg["items"]["distinct_items_used"], "件；被使用次数 min/max =",
          agg["items"]["min_times_used"], "/", agg["items"]["max_times_used"])
    print()
    print("=== 各子池的均匀性（均值）===")
    by = collections.defaultdict(list)
    for r in rows:
        if r["uniformity_ratio"] != "":
            by[r["subpool"]].append(r["uniformity_ratio"])
    for sub, v in sorted(by.items()):
        print(f"   {sub:<26} 槽位 {len(v):>3}  均匀性均值 {sum(v)/len(v):.4f}  最低 {min(v):.4f}")
    print()
    print("=== 样例：某个槽 200 个种子里收到过的物品分布 ===")
    for key in list(received)[:2]:
        cnt = received[key]
        print(f"   {key[0]} | {key[1]}:{key[2]}:s{key[3]} → 收到 {len(cnt)} 种物品，前 5：",
              [(i, c) for i, c in cnt.most_common(5)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
