# seed_sweep_dedupe.py — 去重口径的 200 种子对照
# 问题：同一物品被多家商店重复出售（如 匕首/长剑/剑士臂甲 各占 2–3 行），会让该池"重复占多数"，
#       数学上无法完全打散（条件：任一物品占用的槽位 ≤ n/2）。
# 方案：每池内按物品去重，只保留第一行参与置换；其余重复行**原样不动**。
# 输出：与被审版（不去重）的对照数据 evidence/seed_sweep_dedupe.json
import csv, json, math, os, sys, collections

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun as D

N_SEEDS = 200


def build_pools():
    overlay = D.load_overlay()
    _, slots = D.load_index_slots()
    pools = D.lot_cells(overlay, slots, merge=False)
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    sp, _ = D.shop_cells(shops, set(), merge=False)
    for k, v in sp.items():
        pools.setdefault(k, []).extend(v)
    return pools


def dedupe(pools):
    out, dropped = {}, []
    for sub, cs in pools.items():
        seen, keep = set(), []
        for c in cs:
            if c["item_id"] in seen:
                dropped.append({"subpool": sub, "item_id": c["item_id"], "name_cn": c["name_cn"],
                                "source_table": c["source_table"], "row_id": c["row_id"]})
                continue
            seen.add(c["item_id"])
            keep.append(c)
        out[sub] = keep
    return out, dropped


def sweep(pools):
    stat = collections.defaultdict(lambda: {"unchanged": 0, "received": collections.Counter()})
    for seed in range(N_SEEDS):
        plan, _ = D.permute(pools, seed)
        for p in plan:
            k = (p["subpool"], p["source_table"], p["row_id"], p["slot"])
            stat[k]["received"][p["new_item_id"]] += 1
            if p["unchanged"]:
                stat[k]["unchanged"] += 1
    ratios, ever_unchanged = [], 0
    for k, s in stat.items():
        n = len(pools[k[0]])
        mx = max(n - 1, 1)
        tot = sum(s["received"].values())
        probs = [v / tot for v in s["received"].values()] if tot else []
        h = -sum(p * math.log(p) for p in probs if p > 0)
        ratios.append(h / math.log(mx) if mx > 1 else 1.0)
        if s["unchanged"]:
            ever_unchanged += 1
    return {"cells": sum(len(v) for v in pools.values()),
            "permuted": sum(1 for sub, cs in pools.items() if len(cs) >= 2 for _ in cs),
            "cells_ever_unchanged": ever_unchanged,
            "uniformity_min": round(min(ratios), 4) if ratios else "",
            "uniformity_mean": round(sum(ratios) / len(ratios), 4) if ratios else ""}


def main():
    base = build_pools()
    dd, dropped = dedupe(base)
    infeasible = {sub: {"cells": len(cs), "distinct": len({c['item_id'] for c in cs})}
                  for sub, cs in base.items() if len(cs) >= 2 and max(collections.Counter(c['item_id'] for c in cs).values()) > len(cs) // 2}
    a, b = sweep(base), sweep(dd)
    out = {"seeds": N_SEEDS,
           "no_dedupe": a, "dedupe": b,
           "duplicate_rows_left_untouched": len(dropped),
           "duplicate_rows_detail": dropped,
           "pools_infeasible_without_dedupe": infeasible,
           "note": "去重口径下，重复商店行保持原样；如需'同一物品在所有商店同步替换'，应改为分组联动（需另做设计）"}
    json.dump(out, open(os.path.join(DRY, "evidence", "seed_sweep_dedupe.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("=== 不去重 vs 去重（各 200 种子）===")
    for k in ("cells", "permuted", "cells_ever_unchanged", "uniformity_min", "uniformity_mean"):
        print(f"  {k:<24} 不去重 {str(a[k]):>8}   去重 {str(b[k]):>8}")
    print(f"  因去重而被保留原样的重复商店行: {len(dropped)} 条（例：", [(d['name_cn'], d['row_id']) for d in dropped[:6]], "）")
    print(f"  不去重时无法完全打散的池: {infeasible}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
