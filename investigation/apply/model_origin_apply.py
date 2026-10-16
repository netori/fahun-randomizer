# -*- coding: utf-8 -*-
"""把"反推出来的原身"并回敌型表：新模型继承原身的敌型与（有的话）名字。

依据：investigation/models_to_review.csv 里的 `原身（贴图里留的）` 列
（来自贴图内部文件名 + 模型文件的材质路径/骨骼名 —— 见 model_origin.py）。
例：c8007 的贴图叫 c3251_* ⇒ 原身是**大树守卫**（Miniboss）⇒ c8007 也是「骑士/重甲」那一类。

产出：investigation/enemy_origin_map.csv（模型 → 原身 → 敌型/名字/依据）
     并把敌型写回 investigation/enemy_type_map.csv（新增列 origin / origin_type，enemy_type 补空）
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)


def main():
    # ① 原身表
    review = {r["model"]: r for r in csv.DictReader(
        open(os.path.join(DATA, "models_to_review.csv"), encoding="utf-8-sig"))}
    tm = {}
    with open(os.path.join(DATA, "enemy_type_map.csv"), encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        cols = list(rdr.fieldnames)
        for r in rdr:
            tm[r["model"]] = r

    # ② 逐个：挑一个"有敌型的原身"
    rows, filled = [], 0
    for m, rr in review.items():
        cands = [c for c in (rr.get("原身（贴图里留的）") or "").replace("、", ",").split(",") if c]
        base, bt, bn = "", "", ""
        for c in cands:
            t = tm.get(c, {}).get("enemy_type") or ""
            if t and t not in ("未分类", "体型·大/巨", "体型·小/中"):
                base, bt, bn = c, t, (tm.get(c, {}).get("model_name_en") or "")
                break
        if not base and cands:
            base = cands[0]
            bt = tm.get(base, {}).get("enemy_type") or ""
        rows.append({"model": m, "origin": base, "origin_type": bt, "origin_name": bn,
                     "placements": rr.get("placements", ""), "hp_median": rr.get("hp_median", ""),
                     "evidence": rr.get("依据", "")})
        if bt:
            filled += 1
    with open(os.path.join(DATA, "enemy_origin_map.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # ③ 写回敌型表：加两列 + 把空的 enemy_type 补上
    if "origin" not in cols:
        cols += ["origin", "origin_type"]
    o = {r["model"]: r for r in rows}
    n_fix = 0
    for m, r in tm.items():
        src = o.get(m)
        if not src:
            continue
        r["origin"] = src["origin"]
        r["origin_type"] = src["origin_type"]
        cur = (r.get("enemy_type") or "").strip()
        if (not cur or cur in ("未分类", "体型·大/巨", "体型·小/中")) and src["origin_type"]:
            r["enemy_type"] = src["origin_type"]
            n_fix += 1
    with open(os.path.join(DATA, "enemy_type_map.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(tm.values())

    print("反推出原身的模型: %d ｜ 其中拿到敌型的: %d ｜ 敌型表补上 %d 个" % (
        sum(1 for r in rows if r["origin"]), filled, n_fix))
    print()
    print("%-8s %-10s %-22s %-12s %s" % ("模型", "原身", "原身名字", "原身敌型", "放置"))
    for r in sorted(rows, key=lambda x: -int(x["placements"] or 0)):
        if r["origin"]:
            print("%-8s %-10s %-22s %-12s %s" % (
                r["model"], r["origin"], (r["origin_name"] or "")[:22], (r["origin_type"] or "")[:12], r["placements"]))
    print()
    left = [r["model"] for r in rows if not r["origin"]]
    print("仍然没有原身的:", left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
