# audit_guide_accuracy.py — 量化说明书改写的"准确/存疑"：哪些行现在可能说错
import collections, csv, html, importlib.util, json, os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ug", os.path.join(APPLY, "update_guide.py"))
ug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ug)


def main():
    plan_path = os.path.join(APPLY, "out", "plan_guide_default.csv")
    plan = [r for r in csv.DictReader(open(plan_path, encoding="utf-8-sig")) if r["old"] != r["new"]]
    src = open(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"), encoding="utf-8-sig").read()

    names = {"protector": ug.fmg(os.path.join(ug.CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                                 os.path.join(ug.CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
             "weapon": ug.fmg(os.path.join(ug.WB, "evidence", "xml", "WeaponName.fmg.xml"),
                              os.path.join(ug.WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
             "goods": ug.fmg(os.path.join(ug.CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                             os.path.join(ug.CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    name2id = {}
    for c, t in names.items():
        for i, n in t.items():
            name2id.setdefault(n, f"{c}:{i}")

    glines = ug.guide_lines(src)
    guide_loc = collections.defaultdict(set)
    for eid, nm, loc in glines:
        k = name2id.get(nm)
        if k:
            guide_loc[k].add(loc)

    pairs = ug.load_place_dict("zh")
    dict_zh = {en.lower(): zh for en, zh in pairs}
    names_en = list(dict_zh.keys())
    locs_in_guide = {loc for _e, _n, loc in glines}
    vocab = {en.lower() for en, zh in pairs if zh and any(zh in L for L in locs_in_guide)}

    new_locs = collections.defaultdict(list)
    unresolved = []
    for r in plan:
        zh, _ = ug.place_of(r["row_name"], dict_zh, vocab, names_en)
        if not zh:
            cand = sorted(guide_loc.get(r["old"], []))
            if len(cand) == 1:
                zh = cand[0]
        if zh:
            new_locs[r["new"]].append(zh)
        else:
            unresolved.append(r)

    # 每件物品：指南行数 vs 新地点数
    line_count = collections.Counter()
    for eid, nm, loc in glines:
        k = name2id.get(nm)
        if k:
            line_count[k] += 1

    ok_items, bad_items = [], []
    for k, cnt in line_count.items():
        locs = len(set(new_locs.get(k, [])))
        if k not in {r["old"] for r in plan} and k not in {r["new"] for r in plan}:
            continue
        (bad_items if locs != cnt else ok_items).append((k, cnt, locs))

    print(f"=== 说明书准确性审计（完整包 750 行）===")
    print(f"  说明书物品行 {len(glines)} 行（去重物品 {len(line_count)} 个）")
    print(f"  地点齐全、可安全改写: {len(ok_items)} 个物品")
    print(f"  地点不全（该物品的行保持原样，可能不准）: {len(bad_items)} 个物品")
    print()
    # 受影响的行数：这些物品在指南里各占几行
    lines_at_risk = sum(c for _k, c, _l in bad_items)
    print(f"  受影响指南行 ≈ {lines_at_risk} 行")
    print()
    print("  明细（前 20）：")
    for k, cnt, locs in sorted(bad_items, key=lambda x: -x[1])[:20]:
        nm = next((n for n, kk in name2id.items() if kk == k), k)
        print(f"     {nm:<22} 指南 {cnt} 行 / 新地点 {locs} 个")

    # 未解析格子的构成
    kinds = collections.Counter()
    for r in unresolved:
        rn = r["row_name"] or ""
        if r["source_table"] == "ShopLineupParam":
            kinds["商店格"] += 1
        elif not rn:
            kinds["行名为空"] += 1
        elif "[" not in rn:
            kinds["行名是物品名/敌人名(无地名)"] += 1
        else:
            kinds["括号里无地名"] += 1
    print(f"\n  未解析格子 {len(unresolved)} 个，构成: {dict(kinds)}")
    json.dump({"rows": len(plan), "unresolved": len(unresolved), "kinds": dict(kinds),
               "items_at_risk": [[k, c, l] for k, c, l in bad_items]},
              open(os.path.join(APPLY, "logs", "guide_accuracy.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
