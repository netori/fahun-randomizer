# -*- coding: utf-8 -*-
"""从整本摆放台账（placement_ledger.csv）汇总出**行级画像**，供引擎/swapper 用。

为什么要这一层：台账是"每个摆放点一行"（27780 行），而随机是**按 NpcParam 行**做置换的，
`arena:N` / `size:N` 挂在摆放点上 —— 行级替换天生用不到它。中间需要一张"行 → 它出现在
什么场地/什么档位"的表：
  * arena_min / arena_max：这一行最少出现在多大的场地里（**最小值才是约束**：能塞进小场地的才安全）
  * ref_classes：它的摆放里各档位各出现多少次（Boss×3 / Basic×27 …）—— 这就是"同一模型
    既是杂兵又是 Boss"那种粒度差异的原始证据
  * map_count / place_count：它铺得多广（到处都有的行不能乱换）

产出：investigation/row_arena.csv（npc_id 级）
用法：enemy_swapper 里按摆放点的 arena 挑替身时读它；引擎的报告也读它。
"""
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
LEDGER = os.path.join(DATA, "placement_ledger.csv")
OUT = os.path.join(DATA, "row_arena.csv")


def main():
    if not os.path.isfile(LEDGER):
        print("没有台账，先跑 placement_ledger.py")
        return 2
    rows = collections.defaultdict(lambda: {
        "n": 0, "n_arena": 0, "n_size": 0, "n_multi": 0, "n_unk": 0,
        "arena": set(), "size": set(), "cls": collections.Counter(),
        "maps": set(), "names": set(), "matched": 0})
    with open(LEDGER, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            nid = str(r.get("npc_id") or "")
            if not nid.isdigit():
                continue
            b = rows[int(nid)]
            b["n"] += 1
            b["maps"].add(r["map"])
            if r.get("ref_extra"):
                b["names"].add(r["ref_extra"])
            if r.get("arena"):
                b["n_arena"] += 1
                b["arena"].add(int(r["arena"]))
            if r.get("size"):
                b["n_size"] += 1
                b["size"].add(int(r["size"]))
            if r.get("multi") == "1":
                b["n_multi"] += 1
            if r.get("unkillable") == "1":
                b["n_unk"] += 1
            if r.get("matched") == "1":
                b["matched"] += 1
                if r.get("ref_class"):
                    b["cls"][r["ref_class"]] += 1
    out = []
    for nid, b in sorted(rows.items()):
        out.append({
            "npc_id": nid,
            "place_count": b["n"],
            "map_count": len(b["maps"]),
            "arena_min": min(b["arena"]) if b["arena"] else "",
            "arena_max": max(b["arena"]) if b["arena"] else "",
            "arena_places": b["n_arena"],
            "size_min": min(b["size"]) if b["size"] else "",
            "size_max": max(b["size"]) if b["size"] else "",
            "size_places": b["n_size"],
            "multi_places": b["n_multi"],
            "unkillable_places": b["n_unk"],
            "ref_classes": "/".join("%s×%d" % (k, v) for k, v in b["cls"].most_common(4)),
            "ref_names": "、".join(sorted(b["names"])[:3]),
            "matched_places": b["matched"],
        })
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    n_arena = sum(1 for r in out if r["arena_min"] != "")
    n_cls = sum(1 for r in out if r["ref_classes"])
    print("行（npc_id）%d 个 ｜ 有 arena 档的 %d 个 ｜ 有参考档位分布的 %d 个" % (len(out), n_arena, n_cls))
    print("→", OUT)
    print()
    print("举例（有 arena 档的行）：")
    print("%-10s %-6s %-6s %-8s %-26s %s" % ("npc_id", "arena", "放置", "图数", "参考档位分布", "名字"))
    for r in out:
        if r["arena_min"] != "":
            print("%-10s %-6s %-6d %-8d %-26s %s" % (
                r["npc_id"], "%s~%s" % (r["arena_min"], r["arena_max"]), r["place_count"],
                r["map_count"], r["ref_classes"][:26], r["ref_names"][:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
