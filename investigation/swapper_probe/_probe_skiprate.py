# -*- coding: utf-8 -*-
"""READ-ONLY probe #3: the real skip rate of the hard rule.

The hard rule only bites when the *target* row's model is missing from the
source map.  Measure that on plausible randomizer pairs (boss->boss,
normal->normal), plus how much an `all_models` fallback chain rescues.
"""
import collections
import csv
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
APP = os.path.join(INV, "apply")
sys.path.insert(0, APP)

import msb_read as M           # noqa: E402

MAP_ENEMIES = os.path.join(INV, "map_enemies.csv")
ROW_MODELS = os.path.join(INV, "row_models.csv")
BOSS_ROWS = os.path.join(INV, "boss_rows.csv")


def mapdir():
    env = os.environ.get("CONVERGENCE_MOD_ROOT")
    mod = env or (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
                  r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
    return os.path.join(mod, "mod", "map", "MapStudio")


def load():
    allm, prim = {}, {}
    with open(ROW_MODELS, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = str(r.get("npc_id") or "").strip()
            if not rid.isdigit():
                continue
            rid = int(rid)
            prim[rid] = r.get("model") or ""
            allm[rid] = [x for x in (r.get("all_models") or "").split("|") if x]
    rows_on = collections.defaultdict(set)
    with open(MAP_ENEMIES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows_on[int(r["npc_id"])].add(r["map"])
    bosses = set()
    with open(BOSS_ROWS, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = str(r.get("npc_id") or "").strip()
            if rid.isdigit() and int(rid) > 0:
                bosses.add(int(rid))
    return prim, allm, rows_on, bosses


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    d = mapdir()
    files = sorted(f for f in os.listdir(d) if f.endswith(".msb.dcx"))[:lim]
    t0 = time.time()
    avail = {}
    for fn in files:
        raw, _h = M.dcx_payload(open(os.path.join(d, fn), "rb").read())
        by = {b["name"]: b for b in M.walk_params(raw)[1]}
        avail[fn[:-8]] = set(M.read_models(raw, by["MODEL_PARAM_ST"]))
    print("loaded %d maps in %.2fs" % (len(files), time.time() - t0))

    prim, allm, rows_on, bosses = load()
    rng = random.Random(20261016)

    def trial(pool, label):
        pool = sorted(p for p in pool if p in prim and prim[p])
        hit = miss_prim = rescue = 0
        for _ in range(300):
            a, b = rng.sample(pool, 2)
            for m in sorted(rows_on.get(a, ())):
                if m not in avail:
                    continue
                if prim[b] in avail[m]:
                    hit += 1
                elif any(x in avail[m] for x in allm.get(b, ())):
                    rescue += 1
                else:
                    miss_prim += 1
        tot = hit + rescue + miss_prim
        print("%-14s placements=%4d | primary ok %6.2f%% | rescued by all_models %5.2f%% | SKIP %5.2f%%"
              % (label, tot, 100.0 * hit / tot, 100.0 * rescue / tot, 100.0 * miss_prim / tot))

    normal = [r for r in rows_on if r not in bosses and prim.get(r)]
    trial(normal, "normal->normal")
    trial(bosses, "boss->boss")
    trial(list(rows_on), "any->any")

    # how big are the swap groups in practice?
    for name in sorted(rows_on)[:0]:
        pass
    print("\nrows_by_map: maps=%d ; rows per map avg %.1f"
          % (len(rows_on and collections.Counter(
              m for rs in rows_on.values() for m in [0]) or {}), 0))
    per_map = collections.Counter()
    with open(MAP_ENEMIES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            per_map[r["map"]] += 1
    vals = sorted(per_map.values())
    print("enemies per map: min=%d median=%d max=%d total=%d"
          % (vals[0], vals[len(vals) // 2], vals[-1], sum(vals)))


if __name__ == "__main__":
    main()
