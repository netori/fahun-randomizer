# dryrun_class.py — 新口径干跑：职业倾向分层 + 套装保持完整(A) + 按物品 M1
#   ① 完整四件套（同倾向、四部位齐且件件有入口）→ 套与套整组互换（头→头、身→身、臂→臂、腿→腿）
#   ② 散件（含缺件套的单件）→ 在同一 `部位@倾向 / 类别@倾向 / 等级@倾向` 池内按物品 M1 置换
# 保证：不跨职业倾向、不改部位、套装不拆散、同一物品的多处来源整组一致
# 不做：不写回 MOD、不写注入代码、不改数量·概率·价格·库存·领取flag·事件、不动未列出的 slot
import argparse, collections, csv, json, os, random, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
CATCODE = {"protector": "3", "weapon": "2", "goods": "1"}
SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}


def load_items(with_shops):
    draft = [r for r in csv.DictReader(open(os.path.join(DRY, "class_candidate_draft.csv"), encoding="utf-8-sig"))
             if r["has_entrance"] == "yes" and not r["is_starter_set_piece"]
             and r["category"] in CATCODE and "@" in r["subpool_proposal"] and "?" not in r["subpool_proposal"]]
    votes, name_of, sub_of = collections.defaultdict(collections.Counter), {}, {}
    for r in draft:
        key = (r["category"], r["matched_id"])
        votes[key][r["archetype"]] += 1
        name_of[key] = r["sheet_name"]
        sub_of.setdefault(key, r["subpool_proposal"])
    items, conflicts = {}, []
    for key, v in votes.items():
        if len(v) > 1:
            conflicts.append({"item": f"{key[0]}:{key[1]}", "votes": dict(v)})
        items[key] = {"name": name_of[key], "arch": v.most_common(1)[0][0], "subpool": sub_of[key], "cells": []}

    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    for L in idx["lots"]:
        for s in L["slots"]:
            for cat, code in CATCODE.items():
                if str(s["category"]) == code and (cat, str(s["item_id"])) in items:
                    items[(cat, str(s["item_id"]))]["cells"].append(
                        {"source_table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                         "row_name": L.get("row_name", "")})
    shop_skipped = 0
    if with_shops:
        for r in json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]:
            if r["quality"] != "clean" or r["is_starter_set_piece"]:
                shop_skipped += 1
                continue
            cat = {"weapon": "weapon", "protector": "protector", "goods": "goods"}.get(r["equip_type_name"])
            k = (cat, r["equipId"]) if cat else None
            if k and k in items:
                items[k]["cells"].append({"source_table": "ShopLineupParam", "row_id": str(r["shop_row_id"]), "slot": "",
                                          "row_name": f"shop row {r['shop_row_id']}（{r['name_cn']} 价 {r['price']}）"})
    return {k: v for k, v in items.items() if v["cells"]}, conflicts, shop_skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-shops", action="store_true")
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--out", default="dryrun_class_swaps.csv")
    ns = ap.parse_args()

    items, conflicts, shop_skipped = load_items(ns.with_shops)

    # 完整套装（护甲 · 同倾向 · 四部位齐）
    groups = collections.defaultdict(dict)
    for (cat, iid), v in items.items():
        if cat == "protector" and iid[-4:] in SUF:
            groups[(iid[:-4], v["arch"])][SUF[iid[-4:]]] = (cat, iid)
    complete = {k: m for k, m in groups.items() if len(m) == 4}
    set_pieces = {v for m in complete.values() for v in m.values()}

    plan, rng = [], random.Random(ns.seed)
    # ① 套装整组互换：同倾向内按"每部位入口数"分层
    by_arch = collections.defaultdict(list)
    for (base, arch) in complete:
        by_arch[arch].append((base, arch))
    stats = collections.Counter()
    for arch, members in sorted(by_arch.items()):
        strata = collections.defaultdict(list)
        for base, a in members:
            prof = tuple(sorted((p, len(items[complete[(base, a)][p]]["cells"])) for p in complete[(base, a)]))
            strata[prof].append((base, a))
        for prof, grp in strata.items():
            if len(grp) < 2:
                for base, a in grp:
                    stats["层内唯一·保持原样"] += 1
                    for p, key in complete[(base, a)].items():
                        for c in items[key]["cells"]:
                            plan.append({**c, "unit": f"set:{base}", "role": "set", "pool": f"set@{a}",
                                         "arch": a, "part": p, "old": key, "new": key})
                continue
            src = grp[:]
            for _ in range(500):
                cand = src[:]
                rng.shuffle(cand)
                if all(cand[i] != grp[i] for i in range(len(grp))):
                    break
            for (tbase, a), (sbase, _) in zip(grp, cand):
                stats["整组互换"] += 1
                for p, key in complete[(tbase, a)].items():
                    skey = complete[(sbase, a)][p]
                    for c in items[key]["cells"]:
                        plan.append({**c, "unit": f"set:{tbase}", "role": "set", "pool": f"set@{a}",
                                     "arch": a, "part": p, "old": key, "new": skey})

    # ② 散件：同池（部位/类别/等级 × 倾向）内按物品 M1 置换
    pools = collections.defaultdict(dict)
    for (cat, iid), v in items.items():
        if (cat, iid) in set_pieces:
            continue
        sub = v["subpool"]
        if cat == "protector":
            tail = iid[-4:]
            if SUF.get(tail) not in ("head", "body", "arm", "leg"):
                continue
            sub = f"armor:{SUF[tail]}@{v['arch']}"
        elif cat == "weapon" and not sub.startswith("weapon:cat"):
            continue
        elif cat == "goods" and not sub.startswith("rune:"):
            continue
        pools[sub][f"{cat}:{iid}"] = {"name": v["name"], "cells": v["cells"], "arch": v["arch"]}
    pool_sizes = {k: len(v) for k, v in pools.items()}
    r2 = random.Random(ns.seed + 977)
    for sub, pool in sorted(pools.items()):
        if len(pool) < 2:
            continue
        keys = sorted(pool, key=lambda k: (k.split(":")[0], int(k.split(":")[1])))
        for _ in range(500):
            cand = keys[:]
            r2.shuffle(cand)
            if all(cand[i] != keys[i] for i in range(len(keys))):
                break
        for tgt, src in zip(keys, cand):
            for c in pool[tgt]["cells"]:
                plan.append({**c, "unit": f"item:{tgt}", "role": "single", "pool": sub, "arch": pool[tgt]["arch"],
                             "part": "", "old": tgt, "new": src})

    def pk(x):
        return x if isinstance(x, str) else f"{x[0]}:{x[1]}"

    def base_of(x):
        return pk(x).split(":")[1][:-4]

    # 校验
    checks = {"with_shops": ns.with_shops, "seed": ns.seed, "rows": len(plan),
              "set_units_total": len(complete), "set_units_swapped": stats["整组互换"],
              "set_units_kept_singleton": stats["层内唯一·保持原样"],
              "single_pools": len(pools), "single_items": sum(pool_sizes.values()),
              "single_pools_too_small": sorted(k for k, v in pool_sizes.items() if v < 2),
              "shop_rows_skipped": shop_skipped, "items_with_multiple_archetypes": len(conflicts)}
    # 套内一致：目标套四部位来自同一源套
    ok_sets = True
    for (base, arch) in complete:
        rows = [p for p in plan if p["unit"] == f"set:{base}"]
        if len({base_of(p["new"]) for p in rows}) > 1:
            ok_sets = False
    checks["set_integrity_one_source_per_set"] = ok_sets
    # 部位正确（套装 + 护甲散件）
    ok_part = True
    for p in plan:
        tgt_part = p["part"] or (SUF.get(pk(p["old"]).split(":")[1][-4:], "") if p["pool"].startswith("armor:") else "")
        if tgt_part:
            if pk(p["new"]).split(":")[1][-4:] not in SUF or SUF[pk(p["new"]).split(":")[1][-4:]] != tgt_part:
                ok_part = False
    checks["part_consistency"] = ok_part
    # 倾向一致
    ok_arch = True
    for p in plan:
        tgt = p["pool"].split("@")[-1] if "@" in p["pool"] else p["arch"]
        nk = (pk(p["new"]).split(":")[0], pk(p["new"]).split(":")[1])
        src_arch = items.get(nk, {}).get("arch")
        if src_arch and tgt and src_arch != tgt:
            ok_arch = False
    checks["archetype_consistency"] = ok_arch
    # 同物品多处来源整组一致
    by_group = collections.defaultdict(set)
    for p in plan:
        if p["role"] == "set":
            continue
        by_group[(p["pool"], pk(p["old"]))].add(pk(p["new"]))
    checks["group_consistency"] = all(len(v) == 1 for v in by_group.values())
    # 多重集合不变（散件池）
    ms, ms_detail = True, []
    for sub, pool in pools.items():
        if len(pool) < 2:
            continue
        before = sorted(pool)                                     # 物品键（唯一）
        after = sorted({pk(p["new"]) for p in plan if p["pool"] == sub})   # 按物品去重，避免多来源物品重复计数
        if before != after:
            ms = False
            ms_detail.append({"pool": sub, "n_before": len(before), "n_after": len(after),
                              "only_before": [x for x in before if x not in after][:6],
                              "only_after": [x for x in after if x not in before][:6]})
    checks["multiset_preserved"] = ms
    checks["multiset_violations"] = ms_detail

    cols = ["unit", "role", "pool", "arch", "part", "old", "new", "source_table", "row_id", "slot", "row_name"]
    with open(os.path.join(DRY, ns.out), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in sorted(plan, key=lambda x: (str(x["pool"]), str(x["unit"]), x["source_table"], x["row_id"], x["slot"])):
            w.writerow({**{k: p.get(k, "") for k in cols}, "old": pk(p["old"]), "new": pk(p["new"])})
    json.dump({**checks, "conflict_examples": conflicts[:8],
               "pool_sizes": pool_sizes},
              open(os.path.join(DRY, "evidence", "dryrun_class_checks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"=== 新口径干跑（with_shops={ns.with_shops} seed={ns.seed}）===")
    for k, v in checks.items():
        if isinstance(v, list):
            print(f"   {k}: {v[:12]}{' …' if len(v) > 12 else ''}")
        else:
            print(f"   {k}: {v}")
    print(f"   写出 {ns.out}（{len(plan)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
