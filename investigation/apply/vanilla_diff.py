# -*- coding: utf-8 -*-
"""原版 regulation vs 法魂 regulation 的差异（只读）

用途：作者说"缺的都可以去解包看看" —— 这里补的是「法魂新增敌人名单」。
思路：同一个 param 表，行 id 只出现在法魂那份里 = 法魂新增的东西。
产出：investigation/vanilla_vs_mod_diff.csv（表 / 原版行数 / 法魂行数 / 只在法魂里的行数 / 样例）
     investigation/convergence_new_rows.csv（只在法魂里的 NpcParam 行 + 它的属性）
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "apply"))

import erio                      # noqa: E402
import enemy_randomizer as ER    # noqa: E402
import native_apply as na        # noqa: E402
import param_patch as pp         # noqa: E402

VANILLA = r"F:\game\studygame\elden ring\ELDEN RING Tarnished Edition v1.17\Game\regulation.bin"
MOD = ER._mod_reg()
OUT1 = os.path.join(HERE, "vanilla_vs_mod_diff.csv")
OUT2 = os.path.join(HERE, "convergence_new_rows.csv")


def tables_of(path):
    """{表名: (基准偏移, 大小)}（只列我们关心的几张 + 全部 BND 里的 param）"""
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(path)))
    out = {}
    for name, off, size in na.bnd4_entries(plain):
        short = name.replace("\\", "/").split("/")[-1]
        if short.endswith(".param"):
            out[short[:-6]] = (off, size)
    return plain, out


def rows_of(plain, name, off, size):
    """先试物品侧的探针；不行就用引擎那套通用读法（按 paramdef 扫行表）"""
    base = na.file_start(plain, name)
    if name in getattr(na, "PROBE", {}):
        try:
            r = pp.find_row_table(plain, na.PROBE[name])
            if r:
                return set(r.keys())
        except Exception:
            pass
    try:
        fields, row_size = ER.paramdef_fields(name)
        r = ER.scan_rows(plain, base, size)
        if r:
            return set(r.keys())
    except Exception:
        return None
    return None


def main():
    print("原版:", VANILLA)
    print("法魂:", MOD)
    pv, tv = tables_of(VANILLA)
    pm, tm = tables_of(MOD)
    print("原版 param 表 %d 张｜法魂 %d 张" % (len(tv), len(tm)))

    common = [n for n in ("NpcParam", "NpcThinkParam", "CharaInitParam", "ItemLotParam_map",
                          "ItemLotParam_enemy", "ShopLineupParam") if n in tv and n in tm]
    print("要比的几张:", common)

    diffs = []
    for n in common:
        rv = rows_of(pv, n, *tv[n])
        rm = rows_of(pm, n, *tm[n])
        if not rv or not rm:
            diffs.append((n, len(rv or []), len(rm or []), "—", "（这套读法读不出行表）"))
            continue
        only_mod = sorted(rm - rv)
        only_van = sorted(rv - rm)
        samp = ", ".join(str(x) for x in only_mod[:5])
        diffs.append((n, len(rv), len(rm), len(only_mod), samp))
        print("  %-18s 原版 %5d ｜ 法魂 %5d ｜ 只在法魂 %4d ｜ 只在原版 %4d ｜ 例 %s"
              % (n, len(rv), len(rm), len(only_mod), len(only_van), samp[:60]))
    with open(OUT1, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["table", "vanilla_rows", "mod_rows", "only_in_mod", "sample_ids"])
        for row in diffs:
            w.writerow(row)
    print("→", OUT1)

    # 法魂新增的 NpcParam 行长什么样
    rv = rows_of(pv, "NpcParam", *tv["NpcParam"])
    rm = rows_of(pm, "NpcParam", *tm["NpcParam"])
    if rv and rm:
        new = sorted(rm - rv)
        units = ER.load_units(ER.load_plain())
        rows = []
        for rid in new:
            u = units.get(rid)
            rows.append({"row_id": rid, "hp": getattr(u, "hp", ""), "get_soul": getattr(u, "soul", ""),
                         "is_boss": int(getattr(u, "is_boss", 0)), "radius": getattr(u, "radius", ""),
                         "height": getattr(u, "height", ""), "npc_type": getattr(u, "npc_type", ""),
                         "team_type": getattr(u, "team_type", ""), "name_id": getattr(u, "name_id", "")})
        with open(OUT2, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["row_id"])
            w.writeheader()
            w.writerows(rows)
        import collections
        c = collections.Counter(("Boss" if r["is_boss"] else ("有名字" if r["name_id"] else "无名"))
                                for r in rows)
        print("法魂新增 NpcParam 行 %d 条：%s" % (len(rows), dict(c)))
        print("→", OUT2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
