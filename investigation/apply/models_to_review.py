# -*- coding: utf-8 -*-
"""给"还没名字/还没敌型"的模型做一张**去看一眼**的表。

作者要人工看 36 个模型。为了让他少跑路，每个模型给：
  * 出现最多的几张图 + 一个**具体坐标**（拿去看最近的那个）
  * 放了多少个、用它的 NpcParam 行有多少、血量中位数、体型
  * 已经知道的一切上下文（有没有名字、是不是 Boss、是不是法魂新增）
  * 两列**空的**：中文名 / 敌型 —— 他填完，我再导回敌型表

产出：investigation/models_to_review.csv
"""
import csv
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "apply"))

DATA = os.path.normpath(os.path.join(HERE, os.pardir))   # 数据表在 investigation\ 下，脚本在 apply\ 下
OUT = os.path.join(DATA, "models_to_review.csv")



def hint(m, ps, us, maps):
    """一些不靠名字也能说出来的线索 —— 让作者少跑几趟路"""
    h = []
    hp = sorted(u.hp for u in us if u.hp)
    med = hp[len(hp) // 2] if hp else 0
    if med == 0:
        h.append("血量 0：像是场景物/道具，不是敌人")
    elif med == 1939 and len(us) >= 1:
        h.append("血量 1939：法魂里 NPC/人偶常见的默认值")
    elif med >= 2000:
        h.append("血量偏高：像 Boss/精英")
    if maps and all(k.startswith("m11_10") for k in maps):
        h.append("只出现在 m11_10（円桌）")
    if maps and all(k.startswith(("m40", "m60", "m61")) for k in maps):
        h.append("只在 DLC 图里")
    if len(us) == 0:
        h.append("地图上在用、但没有对应的 NpcParam 行（可能是环境/特效件）")
    if not h:
        h.append("")
    return "；".join(x for x in h if x)


def main():
    import enemy_randomizer as ER
    import enemy_type_map_v2 as T2          # 只为了拿它那份分类（表里已有就够，这里兜底）

    # ① 哪些模型还没具体敌型
    rows = list(csv.DictReader(open(os.path.join(DATA, "enemy_type_map.csv"), encoding="utf-8-sig")))
    bad_types = ("", "未分类", "体型·大/巨", "体型·小/中")
    todo = [r for r in rows if (r.get("enemy_type") or "").strip() in bad_types]
    models = {r["model"] for r in todo}
    print("没有具体敌型的模型:", len(models))

    # ② 地图放置（模型 → 图 / 坐标 / 数量）
    place = collections.defaultdict(list)
    with open(os.path.join(DATA, "map_enemies.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["model"] in models:
                place[r["model"]].append(r)

    # ③ 行级信息（模型 → 用它的行）
    row2model = {}
    with open(os.path.join(DATA, "row_models.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("model"):
                row2model[int(r["npc_id"])] = r["model"]
    units = ER.load_units(ER.load_plain())
    ER.classify(units, names=ER.load_name_table())
    by_model = collections.defaultdict(list)
    for rid, m in row2model.items():
        if m in models and rid in units:
            by_model[m].append(units[rid])

    out = []
    for m in sorted(models, key=lambda x: -len(place.get(x, []))):
        ps = place.get(m, [])
        maps = collections.Counter(p["map"] for p in ps)
        top = maps.most_common(3)
        one = ps[0] if ps else {}
        us = by_model.get(m, [])
        hp = sorted(u.hp for u in us if u.hp)
        out.append({
            "model": m,
            "placements": len(ps),
            "maps": len(maps),
            "top_maps": "、".join("%s(%d)" % (a, b) for a, b in top),
            "one_at": "%s @ (%s, %s, %s)" % (
                one.get("map", ""),
                *[("%.1f" % float(one.get(k))) if str(one.get(k, "")).strip() else "?"
                  for k in ("x", "y", "z")]),
            "npc_rows": len(us),
            "hp_median": hp[len(hp) // 2] if hp else "",
            "radius": us[0].radius if us else "",
            "height": us[0].height if us else "",
            "is_boss_row": sum(1 for u in us if u.is_boss),
            "mod_new": sum(1 for u in us if u.source == "new"),
            "known_rows": "、".join(sorted({u.name for u in us if u.name})[:3]),
            "备注（我猜的）": hint(m, ps, us, maps),
            "中文名（你来填）": "",
            "敌型（你来填）": "",
        })
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print("→", OUT, "｜%d 行" % len(out))
    print()
    print("%-9s %6s %5s %-28s %-9s %-6s %s" % ("模型", "放置", "图数", "最多的图", "血量中位", "法魂新", "位置（去看这个）"))
    for r in out:
        print("%-9s %6d %5d %-28s %-9s %-6s %s" % (
            r["model"], r["placements"], r["maps"], r["top_maps"][:28],
            r["hp_median"], r["mod_new"], r["one_at"][:44]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
