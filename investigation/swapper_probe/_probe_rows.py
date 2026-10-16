# -*- coding: utf-8 -*-
"""READ-ONLY probe: how reliable is an npc_id -> (think_id, chara_id, model) map?

Question 1: for a given npc_id seen on the maps, is think_id 1:1 or can it vary?
Question 2: is the model observed on the map the same as row_models.csv says?
Question 3: how many of the 27780 placements have a row that never appears in row_models.csv?
"""
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(os.path.dirname(HERE)), "investigation", "apply")
sys.path.insert(0, APP)

MAP_ENEMIES = os.path.join(os.path.dirname(APP), "map_enemies.csv")


def main():
    rows = collections.defaultdict(lambda: {"think": collections.Counter(),
                                            "chara": collections.Counter(),
                                            "model": collections.Counter(),
                                            "maps": set()})
    n = 0
    with open(MAP_ENEMIES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            n += 1
            rid = int(r["npc_id"])
            d = rows[rid]
            d["think"][r["think_id"]] += 1
            d["chara"][r["chara_id"]] += 1
            d["model"][r["model"]] += 1
            d["maps"].add(r["map"])

    multi_think = [r for r, d in rows.items() if len(d["think"]) > 1]
    multi_model = [r for r, d in rows.items() if len(d["model"]) > 1]
    print("placements=%d unique_rows=%d" % (n, len(rows)))
    print("rows with >1 think_id : %d (%.2f%%)" % (len(multi_think), 100.0 * len(multi_think) / len(rows)))
    print("rows with >1 model    : %d (%.2f%%)" % (len(multi_model), 100.0 * len(multi_model) / len(rows)))
    for r in multi_think[:8]:
        print("   row %d think=%s" % (r, dict(rows[r]["think"])))

    # how many rows are reachable from map_enemies.csv at all?
    import enemy_randomizer as ER
    rm = ER.load_row_models()
    print("row_models.csv rows=%d ; in map_enemies=%d" % (len(rm), len(rows)))
    only_rm = sorted(set(rm) - set(rows))
    print("rows in row_models.csv but NEVER placed on a map: %d (e.g. %s)"
          % (len(only_rm), only_rm[:8]))

    # model agreement between the atlas (observed) and row_models.csv (dominant)
    agree = dis = 0
    for r, d in rows.items():
        if r not in rm:
            continue
        top = d["model"].most_common(1)[0][0]
        if top == rm[r]:
            agree += 1
        else:
            dis += 1
    print("model: atlas-top == row_models.csv : %d ; differs : %d" % (agree, dis))

    # chara_id distribution sanity
    chara_neg = sum(1 for d in rows.values() if "-1" in d["chara"])
    print("rows whose chara_id is ever -1 : %d" % chara_neg)

    # all_models column coverage
    allm = {}
    with open(os.path.join(os.path.dirname(APP), "row_models.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = str(r.get("npc_id") or "").strip()
            if rid.isdigit():
                allm[int(rid)] = [x for x in (r.get("all_models") or "").split("|") if x]
    sizes = collections.Counter(len(v) for v in allm.values())
    print("all_models list length histogram (top):", sizes.most_common(6))


if __name__ == "__main__":
    main()
