# residual_audit.py — 统计"真正可能说错"的说明书行：物品在计划里、行却没被改
import collections, csv, html, importlib.util, json, os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fg", os.path.join(APPLY, "fix_guide.py"))
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)


def main():
    plan = [r for r in csv.DictReader(open(os.path.join(APPLY, "out", "plan_guide_v2.csv"), encoding="utf-8-sig"))
            if r["old"] != r["new"]]
    old_xml = open(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"), encoding="utf-8-sig").read()
    new_xml = open(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.v2plan.fmg.xml"), encoding="utf-8-sig").read()
    go, gn = fg.guide_lines(old_xml), fg.guide_lines(new_xml)

    moved = {r["old"] for r in plan} | {r["new"] for r in plan}
    names = {}
    for cat, t in (("protector", fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "ProtectorName.fmg.xml"))),
                   ("weapon", fg.fmg(os.path.join(fg.WB, "evidence", "xml", "WeaponName.fmg.xml"))),
                   ("goods", fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "GoodsName.fmg.xml")))):
        for i, n in t.items():
            names.setdefault(f"{cat}:{i}", n)

    changed = same = 0
    risk = []
    for (e1, n1, l1), (e2, n2, l2) in zip(go, gn):
        if (n1, l1) != (n2, l2):
            changed += 1
            continue
        same += 1
        key = fg.name2id.get(n1) if hasattr(fg, "name2id") else None
        risk.append((e1, n1, l1))
    print(f"=== 说明书改动总账（完整包）===")
    print(f"  总行 {len(go)} | 已改 {changed} | 未改 {same}")
    # 未改的行里，哪些属于"被随机化动过的物品"
    id2name_needed = {}
    # 重建 name2id（复用 fix_guide 的构造逻辑）
    nm2id = {}
    for cat, t in (("protector", fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                                        os.path.join(fg.CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))),
                   ("weapon", fg.fmg(os.path.join(fg.WB, "evidence", "xml", "WeaponName.fmg.xml"),
                                     os.path.join(fg.WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))),
                   ("goods", fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                                    os.path.join(fg.CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml")))):
        for i, n in t.items():
            nm2id.setdefault(n, f"{cat}:{i}")
    risky = [(e, n, l) for e, n, l in risk if nm2id.get(n) in moved]
    print(f"  未改的行中，属于「被随机化动过的物品」: {len(risky)} 行  ← 这些可能说错")
    byitem = collections.Counter(n for _e, n, _l in risky)
    print(f"  涉及 {len(byitem)} 个物品；最多的: {byitem.most_common(8)}")
    for e, n, l in risky[:12]:
        print(f"     {e}  【{n}】 - {l}")
    json.dump({"total": len(go), "changed": changed, "risky": len(risky),
               "by_item": byitem.most_common(50)}, open(os.path.join(APPLY, "logs", "guide_residual_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
