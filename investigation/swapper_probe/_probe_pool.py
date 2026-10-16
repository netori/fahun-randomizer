# -*- coding: utf-8 -*-
"""READ-ONLY probe #4: how big is the *achievable* swap pool per map?

If a pair is drawn at random, 66-85% of parts get skipped (probe #3) because
the target row's model is not in the source map's MODEL section.
But a map's MODEL section usually holds far more character models than the
map actually uses.  So the question that decides the design is:

    for map X, how many NpcParam rows have their model already in X's MODEL section?

If that number is large, "true enemy swap" is fully feasible -- the randomizer
just has to draw targets from that per-map pool instead of from the global pool.
"""
import collections
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
APP = os.path.join(INV, "apply")
sys.path.insert(0, APP)

import msb_read as M           # noqa: E402
import msb_write as W          # noqa: E402

ROW_MODELS = os.path.join(INV, "row_models.csv")
MAP_ENEMIES = os.path.join(INV, "map_enemies.csv")
BOSS_ROWS = os.path.join(INV, "boss_rows.csv")


def mapdir():
    env = os.environ.get("CONVERGENCE_MOD_ROOT")
    mod = env or (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
                  r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
    return os.path.join(mod, "mod", "map", "MapStudio")


def main():
    d = mapdir()
    prim = {}
    with open(ROW_MODELS, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = str(r.get("npc_id") or "").strip()
            if rid.isdigit() and (r.get("model") or ""):
                prim[int(rid)] = r["model"]
    # model -> rows that use it as primary
    by_model = collections.defaultdict(list)
    for rid, m in prim.items():
        by_model[m].append(rid)

    files = sorted(f for f in os.listdir(d) if f.endswith(".msb.dcx"))
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 634
    files = files[:lim]

    t0 = time.time()
    pools, chars, allnames = [], collections.Counter(), set()
    for fn in files:
        raw, _h = M.dcx_payload(open(os.path.join(d, fn), "rb").read())
        by = {b["name"]: b for b in M.walk_params(raw)[1]}
        models = M.read_models(raw, by["MODEL_PARAM_ST"])
        allnames.update(models)
        cm = [m for m in models if m.startswith("c")]
        chars[len(cm)] += 1
        n = sum(len(by_model.get(m, ())) for m in set(models))
        pools.append((fn[:-8], len(models), len(set(cm)), n))
    dt = time.time() - t0
    print("scanned %d maps in %.1fs (%.3fs/map)" % (len(files), dt, dt / len(files)))
    print("distinct model names across all maps: %d" % len(allnames))

    ns = sorted(p[3] for p in pools)
    print("rows reachable per map: min=%d p10=%d median=%d p90=%d max=%d"
          % (ns[0], ns[len(ns) // 10], ns[len(ns) // 2], ns[len(ns) * 9 // 10], ns[-1]))
    nz = [x for x in ns if x == 0]
    print("maps with ZERO reachable rows: %d" % len(nz))
    small = [p for p in pools if p[3] < 20]
    print("maps with <20 reachable rows: %d" % len(small))
    for p in small[:6]:
        print("   %s models=%d charmodels=%d reachable_rows=%d" % p)
    print("sample big:", sorted(pools, key=lambda x: -x[3])[:3])

    print("\ncharacter-model count per map histogram (top 8):",
          chars.most_common(8))

    # timing of a real write
    p0 = os.path.join(d, "m10_00_00_00.msb.dcx")
    t0 = time.time()
    data = open(p0, "rb").read()
    raw, _h = M.dcx_payload(data)
    parts = W.enemy_parts(raw)
    t1 = time.time()
    out, rep = W.patch_ex(data, {("idx", parts[0]["index"]): {"npc_id": 1}})
    t2 = time.time()
    print("\nread+parse %.3fs ; patch+repack %.3fs ; out %d bytes (in %d)"
          % (t1 - t0, t2 - t1, len(out), len(data)))


if __name__ == "__main__":
    main()
