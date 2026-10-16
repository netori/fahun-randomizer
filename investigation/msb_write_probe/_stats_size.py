# -*- coding: utf-8 -*-
"""体量影响 + 语料统计：634 张图的 part 总数 / 敌人 part 总数 / 原大小 vs 我方 DFLT 产物大小。"""
import collections
import os
import sys

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import msb_read        # noqa: E402
import msb_write as mw  # noqa: E402


def main():
    files = mw._maps()
    print("地图数: %d" % len(files))
    tot_parts = tot_enemy = 0
    kinds = collections.Counter()
    agg = collections.defaultdict(lambda: {"n": 0, "orig": 0, "new": 0, "plain": 0})
    dup_maps = 0
    dup_eid_enemy = 0
    dup_name = 0
    enemy_eid_not_unique_maps = 0
    for i, p in enumerate(files, 1):
        data = open(p, "rb").read()
        raw, h = mw.dcx_unpack(data)
        parts = list(mw.iter_parts(raw))
        en = [x for x in parts if x["type"] == 2]
        tot_parts += len(parts)
        tot_enemy += len(en)
        kinds[h["kind"]] += 1
        ce = collections.Counter(x["entity_id"] for x in en)
        cn = collections.Counter(x["name"] for x in en)
        if any(v > 1 for v in ce.values()):
            enemy_eid_not_unique_maps += 1
        if any(v > 1 for v in cn.values()):
            dup_name += 1
        out, rep = mw.patch_ex(data, {})
        g = agg[h["kind"]]
        g["n"] += 1
        g["orig"] += len(data)
        g["new"] += len(out)
        g["plain"] += len(raw)
        if i % 100 == 0:
            print("  ... %d/%d" % (i, len(files)))
    print("part 条目总数（全类型）= %d" % tot_parts)
    print("敌人(PartType=2)条目总数 = %d" % tot_enemy)
    print("DCX kind 分布 = %s" % dict(kinds))
    print("敌人 EntityID 在本图不唯一的图数 = %d / %d" % (enemy_eid_not_unique_maps, len(files)))
    print("敌人 part 名在本图不唯一的图数 = %d / %d" % (dup_name, len(files)))
    print("\n  kind   图数   明文总量(MB)   原 DCX 总量(MB)   我方 DFLT 总量(MB)   变化")
    for k, v in sorted(agg.items()):
        print("  %-5s  %4d   %10.1f   %13.1f   %16.1f   %+.1f%%"
              % (k, v["n"], v["plain"] / 1e6, v["orig"] / 1e6, v["new"] / 1e6,
                 100.0 * (v["new"] - v["orig"]) / max(v["orig"], 1)))
    tt = {kk: sum(v[kk] for v in agg.values()) for kk in ("n", "plain", "orig", "new")}
    print("  %-5s  %4d   %10.1f   %13.1f   %16.1f   %+.1f%%"
          % ("合计", tt["n"], tt["plain"] / 1e6, tt["orig"] / 1e6, tt["new"] / 1e6,
             100.0 * (tt["new"] - tt["orig"]) / max(tt["orig"], 1)))
    print("\n注：'我方 DFLT' = patch(空 edits) 后用 out_kind='dflt' 重新封装的字节数。")
    print("    这 634 张图在 mod 目录里是裸文件（不是 BND 归档），所以单文件变大 = 磁盘占用变大。")
    del dup_maps
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
