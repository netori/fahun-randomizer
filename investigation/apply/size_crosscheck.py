# -*- coding: utf-8 -*-
"""交叉核对：参考实现的 size:N（人工体型档） vs 我们按模型半径/高度算的 size_bucket。

为什么值得做：我们的体型护栏是"防大怪塞进小怪位"的唯一依据，全靠自己从
NpcParam 的 chrHitRadius/Height 推。参考实现另有一套人工档位（79 个模型带 size:N），
两边对不上的就是**可疑样本**，值得逐个看。

产出：investigation/size_crosscheck.md
"""
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
MD = os.path.join(DATA, "size_crosscheck.md")

sys.path.insert(0, HERE)


def main():
    import enemy_randomizer as ER
    ref = {}
    with open(os.path.join(DATA, "enemy_ref.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("size"):
                ref[r["model"]] = r
    units = ER.load_units(ER.load_plain())
    ER.classify(units, names=ER.load_name_table(), healthbar_ids=ER.load_healthbar_nameids())
    r2m = {}
    with open(os.path.join(DATA, "row_models.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("model") and str(r.get("npc_id", "")).isdigit():
                r2m[int(r["npc_id"])] = r["model"]

    by_model = collections.defaultdict(list)
    for rid, u in units.items():
        m = r2m.get(rid)
        if m in ref:
            by_model[m].append(u)

    tab = collections.Counter()
    rows = []
    for m, us in by_model.items():
        sz = ref[m]["size"]
        b = collections.Counter(ER.size_bucket(u.radius, u.height) for u in us)
        mine = b.most_common(1)[0][0]
        tab[(sz, mine)] += 1
        rows.append({"model": m, "ref_size": sz, "our_bucket": mine,
                     "radius": round(us[0].radius, 2), "height": round(us[0].height, 2),
                     "rows": len(us), "ref_places": ref[m]["n_entries"],
                     "ref_names": ref[m]["extra_names"][:40]})
    rows.sort(key=lambda r: (r["ref_size"], -r["rows"]))
    with open(MD, "w", encoding="utf-8") as f:
        f.write("# 体型档：参考实现 vs 我们\n\n")
        f.write("参考实现有 size 档的模型 %d 个（我们这边可比 %d 个）\n\n" % (len(ref), len(rows)))
        f.write("交叉表（行=参考 size:N，列=我们的桶 0/1/2）：\n\n| ref\\我们 | 0 | 1 | 2 | 合计 |\n|---|---|---|---|---|\n")
        for sz in sorted({k[0] for k in tab}):
            line = "| %s |" % sz
            tot = 0
            for b in (0, 1, 2):
                n = tab.get((sz, b), 0)
                tot += n
                line += " %d |" % n
            f.write(line + " %d |\n" % tot)
        f.write("\n逐模型：\n\n| 模型 | 参考 size | 我们桶 | 半径 | 高 | 行数 | 参考名 |\n|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write("| %s | %s | %s | %s | %s | %d | %s |\n" % (
                r["model"], r["ref_size"], r["our_bucket"], r["radius"], r["height"], r["rows"], r["ref_names"]))
    agree = sum(v for (sz, b), v in tab.items()
                if (sz, b) in (("1", 0), ("2", 1), ("3", 2)))
    print("参考有 size 档 %d 个模型 ｜ 我们可比 %d" % (len(ref), len(rows)))
    print("交叉表:", {"ref%s/我们%d" % k: v for k, v in sorted(tab.items())})
    print("按 1→0 / 2→1 / 3→2 的朴素映射，一致 %d / %d" % (agree, len(rows)))
    print("→", MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
