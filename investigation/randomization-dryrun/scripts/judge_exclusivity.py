# judge_exclusivity.py — 判定未解析名称是否「职业专属」，并给出入池/不入池结论
# 判定标准（可复算）：
#   ① 归属职业数：直接出现在《职业推荐道具表3.0》的职业 + 通过《套装表》展开（某职业推荐了该套装）的职业；去重计数
#   ② 匹配度：对 MOD 的四张名称表（Protector / Weapon / Goods）做归一化相似度，取最优
#   ③ 结论：n_cls == 1 → 职业专属；≥2 → 共享；0 → 无归属（不是职业装备）
#   ④ 入池条件：职业专属 且 能匹配到真实物品（相似度 ≥0.75 或有人工映射）
import collections, difflib, json, os, re, sys
import xml.etree.ElementTree as ET
import openpyxl

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.dirname(os.path.dirname(DRY))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def norm(s):
    return re.sub(r"[（(].*?[)）]", "", s or "").replace(" ", "").strip()


def main():
    tabs = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                             os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
            "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                          os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
            "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                         os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    wb = openpyxl.load_workbook(os.path.join(WS, "法魂资料整合表.xlsx"), read_only=True, data_only=True)
    rows = lambda ws: [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]

    # 推荐表：职业 → 名称（含类别）
    rec, cur_cls = collections.defaultdict(list), ""
    for r in rows(wb["职业推荐道具表3.0"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_cls = r[0]
        if len(r) > 2 and r[2]:
            rec[r[2]].append(cur_cls)

    # 套装表：套装名 → 件
    sets, cur_set = collections.defaultdict(list), ""
    for r in rows(wb["套装表"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_set = r[0]
        if len(r) > 1 and r[1]:
            sets[cur_set].append(r[1])
    setname_of_piece = {}
    for s, pieces in sets.items():
        for p in pieces:
            setname_of_piece.setdefault(p, []).append(s)

    basis = json.load(open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), encoding="utf-8"))
    unresolved = sorted({n for names in basis.get("unmatched_all", {}).values() for n in names})

    print(f"=== 未解析名称共 {len(unresolved)} 条 —— 判定 ===")
    out = []
    for name in unresolved:
        direct = sorted(set(rec.get(name, [])))
        via = set()
        for s in setname_of_piece.get(name, []):
            via |= set(rec.get(s, []))
            via |= set(rec.get(s + "套装", []))
            via |= set(rec.get(re.sub(r"套装?$", "", s) + "套装", []))
        cls_all = sorted(set(direct) | via)
        best = ("", "", 0.0, "")
        for t, tb in tabs.items():
            for i, nm in tb.items():
                r = difflib.SequenceMatcher(None, norm(name), norm(nm)).ratio()
                if r > best[2]:
                    best = (t, i, r, nm)
        excl = len(cls_all) == 1
        verdict = ("职业专属" if excl else ("共享装备" if cls_all else "无职业归属"))
        keep = excl and best[2] >= 0.75
        out.append({"name": name, "direct_classes": direct, "via_set_classes": sorted(via), "classes": cls_all,
                    "n_classes": len(cls_all), "verdict": verdict,
                    "best_table": best[0], "best_id": best[1], "best_ratio": round(best[2], 3), "best_name": best[3],
                    "in_pool": keep,
                    "reason": ("专属且可匹配" if keep else
                               ("专属但无法匹配到真实物品" if excl else
                                ("被多个职业共享（非专属）" if cls_all else "推荐表/套装表里都没有它作为独立件"))) })
        print(f"  {name:<20} 职业 {len(cls_all)}{cls_all} → {verdict:<6} | 最优匹配 {best[3][:14]}({best[0]},{best[2]:.2f}) | 入池={'✅' if keep else '❌'} {out[-1]['reason']}")
    json.dump(out, open(os.path.join(DRY, "evidence", "exclusivity_judgement.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  可入池: {sum(1 for o in out if o['in_pool'])} 条 | 不入池: {sum(1 for o in out if not o['in_pool'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
