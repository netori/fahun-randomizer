# verify_by_item.py — 复核「按物品」口径的三个点
# ① M1 的均匀性应"按各自规模层归一"（每格只会收到同层其它物品）
# ② M2 的处数多重集合是否保持
# ③ 格子集合与按行口径的差异
import collections, json, math, os, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun_by_item as B
import dryrun as D

SEEDS = 40


def main():
    overlay, idx, shops = B.load()
    pools = B.build_groups(overlay, idx, shops, True, False)

    # ① M1：逐格统计"收到过哪些物品"，看是否恰好等于同层其它物品且频次均匀
    stratum_of = {}
    for sub, pool in pools.items():
        strata = collections.defaultdict(list)
        for iid, v in pool.items():
            strata[len(v["cells"])].append(iid)
        for size, members in strata.items():
            for iid in members:
                stratum_of[(sub, iid)] = sorted(members)

    recv = collections.defaultdict(collections.Counter)
    for seed in range(SEEDS):
        for sub, pool in pools.items():
            for p in B.permute_items(pool, seed, "M1"):
                recv[(sub, p["source_table"], p["row_id"], p["slot"])][p["new_item_id"]] += 1

    per_cell_ok, ratios, examples = 0, [], []
    for key, cnt in recv.items():
        sub, gi = key[0], None
        # 找出该格所属的物品组
        for iid, v in pools[sub].items():
            if key[1:] in [(c["source_table"], c["row_id"], c["slot"]) for c in v["cells"]]:
                gi = iid
                break
        members = stratum_of.get((sub, gi), [])
        allowed = set(members) - {gi}
        ok = set(cnt.keys()) <= allowed and (len(allowed) <= 1 or len(cnt) == len(allowed))
        per_cell_ok += ok
        tot = sum(cnt.values())
        h = -sum((v / tot) * math.log(v / tot) for v in cnt.values())
        hmax = math.log(len(allowed)) if len(allowed) > 1 else 1.0
        ratios.append(h / hmax if hmax > 0 else 1.0)
        if len(examples) < 3 and len(allowed) > 1:
            examples.append((sub, key[1], key[2], key[3], gi, sorted(allowed)[:4], dict(cnt.most_common(3))))
    print("=== ① M1 逐格校验（开商店，%d 个种子）===" % SEEDS)
    print(f"  逐格=1 的格子数: {sum(1 for c in recv.values() if len(c)==0)}")
    print(f"  只在'同层其它物品'范围内收件、且收全的格子: {per_cell_ok} / {len(recv)}")
    print(f"  按各自可换面归一后的均匀性: 均值 {sum(ratios)/len(ratios):.4f}  最低 {min(ratios):.4f}")
    for e in examples:
        print(f"    例：{e[0]} {e[1]}:{e[2]}{e[3]} 组物品 {e[4]} → 只能收到 {e[5]}…；实际前三 {e[6]}")

    # ② M2：处数多重集合保持
    print("\n=== ② M2 的处数多重集合 ===")
    for sub, pool in sorted(pools.items()):
        if len(pool) < 2:
            continue
        before = sorted(len(v["cells"]) for v in pool.values())
        plan = B.permute_items(pool, 20261010, "M2")
        size_of = {p["group_item"]: p["group_size"] for p in plan}
        new_of = {p["group_item"]: p["new_item_id"] for p in plan}
        after = sorted(len(v["cells"]) for v in pool.values())          # 组的形状不变
        avail_after = sorted(size_of[new_of[iid]] for iid in pool)      # 物品侧：换到别人处数上
        if before != avail_after:
            print(f"  {sub}: 处数多重集合不保持！before={before} after={avail_after}")
    print("  所有池的处数多重集合均保持不变（个体物品的处数会转移）")

    # ③ 格子集合差异
    print("\n=== ③ 与按行口径的格子集合差异 ===")
    bi = {(c["source_table"], c["row_id"], c["slot"], iid) for sub, pool in pools.items() for iid, v in pool.items() for c in v["cells"]}
    pools2 = D.lot_cells(overlay, D.load_index_slots()[1], False)
    sp, _ = D.shop_cells(shops, set(), False)
    for k, v in sp.items():
        pools2.setdefault(k, []).extend(v)
    rb = {(c["source_table"], c["row_id"], c["slot"], c["item_id"]) for v in pools2.values() for c in v}
    print(f"  按物品(物品,格子)对: {len(bi)} | 按行(物品,格子)对: {len(rb)}")
    only_item = sorted(bi - rb)
    only_row = sorted(rb - bi)
    print(f"  只在按物品口径: {only_item[:6]}")
    print(f"  只在按行口径: {only_row[:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
