# -*- coding: utf-8 -*-
"""验证「多阶段整组换」：同组必须一起动、阶段对阶段、且换到另一个完整组。

用文件而不是 heredoc —— 之前 heredoc 里的正则 `$` 被 shell 转义吃掉，测试本身是错的。
"""
import collections
import re
import sys

sys.path.insert(0, ".")
import enemy_randomizer as er                                     # noqa: E402


def base_name(u):
    for n in [y.strip() for y in (u.ref_names or "").replace("、", ",").split(",") if y.strip()]:
        b = re.sub(r"\s*\d+$", "", n).strip()
        if b:
            return b
    return ""


def main():
    units = er.load_units(er.load_plain())
    er.classify(units, names=er.load_name_table(), healthbar_ids=er.load_healthbar_nameids())
    cfg = {"enemy_pools": ["boss", "elite", "normal"], "enemy_source": "all"}
    for label, extra in (("默认（不打不死的）", {}), ("放开打不死的", {"allow_unkillable": True})):
        c = dict(cfg, seed=1, enemy_rate=1.0, **extra)
        plan, warn = er.make_plan(units, c)
        # 校验要用**与生成完全相同**的 cfg（之前这里传了不带 allow_unkillable 的那份，
        # 池子重算结果不同，白报了两千多条"池外成员"）
        issues = er.verify_plan(units, plan, c)
        grp = collections.defaultdict(list)
        for rid, u in units.items():
            if u.multi:
                grp[base_name(u) or ("model:" + str(u.model or rid))].append(rid)
        total = whole = split = 0
        ex = []
        for k, ms in grp.items():
            if len(ms) < 2:
                continue
            total += 1
            moved = [m for m in ms if m in plan]
            if not moved:
                continue
            tg = set(plan[m] for m in ms if m in plan)
            if len(moved) != len(ms):
                split += 1
                continue
            if any(set(v) == tg for kk, v in grp.items() if kk != k and len(v) == len(ms)):
                whole += 1
                if len(ex) < 3:
                    ex.append((k, ms, sorted(tg)))
            else:
                split += 1
        print("【%s】计划 %d 行｜自检问题 %d｜警告 %d" % (label, len(plan), len(issues), len(warn)))
        print("   多阶段组(≥2 阶段) %d 个：整组换到另一个完整组 %d ｜ 被拆散/换到不完整组 %d"
              % (total, whole, split))
        for k, ms, tg in ex:
            print("   例：%s  %s  →  %s" % (
                k, [units[m].ref_names[:20] for m in ms], [units[t].ref_names[:20] for t in tg]))
        if issues:
            print("   自检问题明细:", issues[:4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
