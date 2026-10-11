import collections, json, math, os, sys
DRY = r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\randomization-dryrun"
sys.path.insert(0, os.path.join(DRY, "scripts"))
import dryrun_by_item as B
overlay, idx, shops = B.load()
pools = B.build_groups(overlay, idx, shops, True, False)
# 找出被重复计入的 (item, cell)
seen = collections.Counter()
for sub, pool in pools.items():
    for iid, v in pool.items():
        for c in v["cells"]:
            seen[(sub, iid, c["source_table"], c["row_id"], c["slot"])] += 1
dups = [k for k, v in seen.items() if v > 1]
print("重复计入的 (池,物品,格子):", dups)
for k in dups:
    iid = k[1]
    for sub, pool in pools.items():
        if iid in pool and sub == k[0]:
            print("   ", sub, iid, len(pool[iid]["cells"]), "格:", [(c["source_table"], c["row_id"]) for c in pool[iid]["cells"]])
# 物品同时出现在两个池
loc = collections.defaultdict(set)
for sub, pool in pools.items():
    for iid in pool:
        loc[iid].add(sub)
print("同时出现在多个池的物品:", {k: v for k, v in loc.items() if len(v) > 1})
# 修正版 M1 均匀性：200 种子，只统计'层内成员 >=2'的格子，按层归一
stratum = {}
for sub, pool in pools.items():
    st = collections.defaultdict(list)
    for iid, v in pool.items():
        st[len(v["cells"])].append(iid)
    for size, mem in st.items():
        for iid in mem:
            stratum[(sub, iid)] = mem
recv = collections.defaultdict(collections.Counter)
cell2group = {}
for sub, pool in pools.items():
    for iid, v in pool.items():
        for c in v["cells"]:
            cell2group[(sub, c["source_table"], c["row_id"], c["slot"])] = iid
for seed in range(200):
    for sub, pool in pools.items():
        for p in B.permute_items(pool, seed, "M1"):
            recv[(sub, p["source_table"], p["row_id"], p["slot"])][p["new_item_id"]] += 1
ratios, sing = [], 0
for k, cnt in recv.items():
    gi = cell2group[k]
    mem = stratum.get((k[0], gi), [])
    if len(mem) < 2:
        sing += 1
        continue
    tot = sum(cnt.values())
    pr = [v / tot for v in cnt.values()]
    h = -sum(x * math.log(x) for x in pr if x > 0)
    ratios.append(h / math.log(len(mem) - 1))
print(f"200 种子，层内成员>=2 的格子 {len(ratios)} 个：均匀性均值 {sum(ratios)/len(ratios):.4f}，最低 {min(ratios):.4f}；单件层（必然不动）{sing} 个格子")
