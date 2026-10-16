# -*- coding: utf-8 -*-
"""寻址可达性统计：634 张图里，敌人 part 有多少能用 EntityID 唯一寻址 / part 名 / 条目序号。"""
import collections
import json
import os
import sys

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import msb_write as mw  # noqa: E402


def main():
    files = mw._maps()
    tot = eid_uniq = name_uniq = 0
    hist = collections.Counter()
    per_map = []
    for i, p in enumerate(files, 1):
        raw, _h = mw.dcx_unpack(open(p, "rb").read())
        en = mw.enemy_parts(raw)
        ce = collections.Counter(x["entity_id"] for x in en)
        cn = collections.Counter(x["name"] for x in en)
        u = sum(1 for x in en if ce[x["entity_id"]] == 1 and x["entity_id"] > 0)
        nu = sum(1 for x in en if cn[x["name"]] == 1)
        tot += len(en)
        eid_uniq += u
        name_uniq += nu
        hist[(len(en), u, nu)] += 1
        per_map.append({"map": os.path.basename(p), "enemies": len(en),
                        "eid_unique": u, "name_unique": nu})
        if i % 150 == 0:
            print("  ... %d/%d" % (i, len(files)))
    print("敌人 part 总数 = %d（%d 张图）" % (tot, len(files)))
    print("  可按 EntityID 唯一寻址（且 id>0）: %6d  = %.1f%%" % (eid_uniq, 100.0 * eid_uniq / tot))
    print("  可按 part 名唯一寻址          : %6d  = %.1f%%" % (name_uniq, 100.0 * name_uniq / tot))
    print("  只能按条目序号寻址            : %6d  = %.1f%%（= 100%% - 前两者都不可用的）"
          % (tot - max(eid_uniq, name_uniq), 100.0 * (tot - max(eid_uniq, name_uniq)) / tot))
    print("  （条目序号 ('idx',N) 永远可用：它就是 PARTS_PARAM_ST 的位置）")
    worst = sorted(per_map, key=lambda r: (r["eid_unique"] / max(r["enemies"], 1)))[:5]
    print("  EntityID 唯一率最低的 5 张图:")
    for r in worst:
        print("    %-24s enemies=%-4d eid_unique=%-4d name_unique=%-4d"
              % (r["map"], r["enemies"], r["eid_unique"], r["name_unique"]))
    with open(os.path.join(mw.PROBE_DIR, "_addressing.json"), "w", encoding="utf-8") as f:
        json.dump({"total_enemies": tot, "eid_unique": eid_uniq, "name_unique": name_uniq,
                   "per_map": per_map}, f, ensure_ascii=False)
    print("  明细 -> investigation/msb_write_probe/_addressing.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
