# -*- coding: utf-8 -*-
"""整本摆放台账：634 张图 × 每个敌人 part → 一行。

有了它，第 1 件事（按场地档限制换怪）才有落点：
  * 我方事实：地图 / part 名 / 模型 / 实体 id / npc_id / 坐标
  * 参考实现的人工标注：（地图, part 名）能连上的部分 → Class / Tags（含 arena:N / size:N / multi / unkillable）

实测连接率（前 80 张图）：**64.5%**（4045/6272）——比按实体 id 的 29% 强得多；
未命中的多半是法魂自己加的命名 part（Storm NPC / Necro NPC），那部分本来就没有参考数据。

产出：investigation/placement_ledger.csv
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)
import msb_read as MR                                               # noqa: E402
import enemy_randomizer as ER                                       # noqa: E402

OUT = os.path.join(DATA, "placement_ledger.csv")


def load_ref_by_name():
    """(地图, part 名小写) → 参考实现那一条（含 Class/Tags）"""
    p = os.path.join(DATA, "enemy_ref_by_id.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = ((r.get("map") or "").strip(), (r.get("name") or "").strip().lower())
            if key[0] and key[1]:
                out[key] = r
    return out


def tagval(tags, name):
    m = re.search(r"(?:^|\s)%s:([^\s]+)" % name, tags or "")
    return m.group(1) if m else ""


def main():
    md = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(ER._mod_reg()))),
                      "mod", "map", "MapStudio")
    ref = load_ref_by_name()
    print("参考名单 (地图, 名字) 键:", len(ref))
    files = sorted(f for f in os.listdir(md) if f.endswith(".msb.dcx"))
    print("地图:", len(files))
    rows = []
    n_hit = n_all = 0
    for i, f in enumerate(files):
        mp = f[:-len(".msb.dcx")]
        try:
            msb = MR.read_msb(os.path.join(md, f))
        except Exception as e:
            print("  ✗ %s: %s" % (f, type(e).__name__))
            continue
        for p in msb.get("enemies") or []:
            nm = (p.get("part_name") or "")
            r = ref.get((mp, nm.lower()))
            n_all += 1
            n_hit += 1 if r else 0
            tags = (r or {}).get("tags") or ""
            rows.append({
                "map": mp, "part_name": nm, "model": p.get("model"),
                "entity_id": p.get("entity_id"), "npc_id": p.get("npc_id"),
                "think_id": p.get("think_id"), "chara_id": p.get("chara_id"),
                "x": round(p.get("x") or 0, 2), "y": round(p.get("y") or 0, 2), "z": round(p.get("z") or 0, 2),
                "ref_class": (r or {}).get("ref_class") or "",
                "ref_extra": (r or {}).get("extra_name") or "",
                "arena": tagval(tags, "arena"), "size": tagval(tags, "size"),
                "multi": 1 if "multi" in tags.split() else 0,
                "unkillable": 1 if "exclude:unkillable" in tags else 0,
                "matched": 1 if r else 0,
            })
        if (i + 1) % 100 == 0:
            print("  已读 %d/%d 张图，%d 行" % (i + 1, len(files), len(rows)))
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print()
    print("台账 %d 行 ｜ 连上参考标注 %d 行（%.1f%%）" % (n_all, n_hit, 100.0 * n_hit / max(1, n_all)))
    print("其中带 arena 档的 %d 行、带 size 档的 %d 行、multi %d 行、打不死 %d 行" % (
        sum(1 for r in rows if r["arena"]), sum(1 for r in rows if r["size"]),
        sum(1 for r in rows if r["multi"]), sum(1 for r in rows if r["unkillable"])))
    print("→", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
