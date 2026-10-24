# -*- coding: utf-8 -*-
"""出“哪个 Boss 变成了哪个”的名单 —— 用我们已有的表，不猜。

名字来源优先级：
  1) boss_healthbar.csv 里的中文名（从 EMEVD + FMG 收集来的血条名）
  2) enemy_type_names_zh.csv 的敌型中文名（模型层）
  3) 行号兜底
"""
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enemy_randomizer as er                                          # noqa: E402


def _load(path, key, val):
    out = {}
    p = os.path.join(HERE, "..", path)
    if not os.path.isfile(p):
        return out
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            k = (r.get(key) or "").strip()
            v = (r.get(val) or "").strip()
            if k and v:
                out.setdefault(k, v)
    return out


def name_of_row(rid, models, healthbar, zh_models):
    """→ (显示名, 依据)"""
    m = models.get(str(rid)) or models.get(rid)
    if m:
        if m in zh_models:
            return zh_models[m], "模型中文名"
        n = healthbar.get(str(rid)) or healthbar.get(rid)
        if n:
            return n, "血条名"
        return m, "模型号"
    n = healthbar.get(str(rid)) or healthbar.get(rid)
    if n:
        return n, "血条名"
    return "行%s" % rid, "行号"


def main():
    u = er.load_units(er.load_plain())
    er.classify(u, names=er.load_name_table(), healthbar_ids=er.load_healthbar_nameids())
    plan, warn = er.make_plan(u, {"seed": 20261010, "enemy_rate": 1.0})

    def show(rid):
        x = u.get(rid) or u.get(str(rid))
        if x is None:
            return "行%s" % rid
        nm = getattr(x, "name", "") or ""
        ty = getattr(x, "enemy_type", "") or ""
        md = getattr(x, "model", "") or ""
        tag = nm or ty or md or ("行%s" % rid)
        return "%s%s" % (tag, ("(%s)" % md) if (md and tag != md) else "")

    order = {"boss": 0, "elite": 1, "normal": 2}
    rows = []
    for rid, nid in plan.items():
        c = getattr(u.get(rid), "cls", "?")
        rows.append((c, rid, nid, show(rid), show(nid)))
    rows.sort(key=lambda x: (order.get(x[0], 9), x[1]))
    bosses = [x for x in rows if x[0] == "boss"]
    print("计划 %d 行 ｜ Boss %d 行 ｜ 精英 %d ｜ 普通 %d"
          % (len(rows), len(bosses), len([x for x in rows if x[0] == "elite"]),
             len([x for x in rows if x[0] == "normal"])))
    print()
    print("=== Boss 换成谁（前 25 条）===")
    for c, rid, nid, a, b in bosses[:25]:
        print("  %-9s → %-9s   %s  ⇒  %s" % (rid, nid, a, b))
    out = os.path.join(HERE, "..", "boss_swap_report.csv")
    with io.open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cls", "row_id", "new_row_id", "old", "new"])
        w.writerows(rows)
    print()
    print("完整名单:", os.path.abspath(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
