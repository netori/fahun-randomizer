# -*- coding: utf-8 -*-
"""READ-ONLY probe #2: cost + skip-rate of the swap rule.

* How long does it take to read all 634 maps?
* Are model names unique inside one map's MODEL section?
* If we pick a target row, is its dominant model present in a given map?
  (this is exactly the "skip" rate of the hard rule)
"""
import collections
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)                     # .../investigation
APP = os.path.join(INV, "apply")
sys.path.insert(0, APP)

import msb_read as M          # noqa: E402
import enemy_randomizer as ER  # noqa: E402

MAP_ENEMIES = os.path.join(INV, "map_enemies.csv")


def mapdir():
    env = os.environ.get("CONVERGENCE_MOD_ROOT")
    mod = env or (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
                  r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
    return os.path.join(mod, "mod", "map", "MapStudio")


def main():
    d = mapdir()
    files = sorted(f for f in os.listdir(d) if f.endswith(".msb.dcx"))
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rm = ER.load_row_models()

    # per-map: models available
    dup_maps = 0
    t0 = time.time()
    avail = {}
    sizes = []
    for fn in files[:lim]:
        p = os.path.join(d, fn)
        sizes.append(os.path.getsize(p))
        raw, _h = M.dcx_payload(open(p, "rb").read())
        fver, blocks = M.walk_params(raw)
        by = {b["name"]: b for b in blocks}
        models = M.read_models(raw, by["MODEL_PARAM_ST"])
        if len(set(models)) != len(models):
            dup_maps += 1
        avail[fn[:-8]] = set(models)
    dt = time.time() - t0
    print("read %d maps in %.1fs  (%.3fs/map)  compressed avg %.0f KB"
          % (lim, dt, dt / lim, sum(sizes) / len(sizes) / 1024))
    print("maps whose MODEL section has duplicate names: %d" % dup_maps)

    # for each (map, row) how often is the row's dominant model available?
    rows_seen = collections.defaultdict(set)
    with open(MAP_ENEMIES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows_seen[r["map"]].add(int(r["npc_id"]))

    hit = miss = 0
    miss_examples = []
    for name, models in avail.items():
        for rid in sorted(rows_seen.get(name, ())):
            want = rm.get(rid)
            if want and want in models:
                hit += 1
            else:
                miss += 1
                if len(miss_examples) < 8:
                    miss_examples.append((name, rid, want))
    tot = hit + miss
    print("co-located (map,row) pairs: %d ; model present: %d (%.2f%%) ; absent: %d (%.2f%%)"
          % (tot, hit, 100.0 * hit / max(tot, 1), miss, 100.0 * miss / max(tot, 1)))
    print("absent examples:", miss_examples)

    # cross-check: is a model-name present in models iff the part exists there?
    # sanity: pick one map, compare MODEL names to part names
    fn = "m10_00_00_00"
    raw, _h = M.dcx_payload(open(os.path.join(d, fn + ".msb.dcx"), "rb").read())
    parts = M.read_msb(os.path.join(d, fn + ".msb.dcx"))
    ms = parts["models"]
    idx = {n: i for i, n in enumerate(ms)}
    bad = [(e["part_name"], e["model"], e["model_index"]) for e in parts["enemies"]
           if idx.get(e["model"]) != e["model_index"]]
    print("m10: enemies=%d ; model_index != first-index-of-name : %d" % (len(parts["enemies"]), len(bad)))
    print("     examples:", bad[:5])


if __name__ == "__main__":
    main()
