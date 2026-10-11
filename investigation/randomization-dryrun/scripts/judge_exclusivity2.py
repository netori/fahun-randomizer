# judge_exclusivity2.py — 用「位置证据」复核未解析名，并判定是否职业专属
# 位置证据：推荐表/套装表给了获取位置文本 → 在奖励槽索引里搜行名关键字 → 找到候选物品 ID → 用其 FMG 名回验
# 专属判定：① 直接出现在某职业推荐里（推荐表）→ 该职业绑定
#           ② 只作为"通用套装"的件被某职业整套推荐 → 非专属（通用套装）
#           ③ 套装表里查不到、推荐表里也没有 → 无归属
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


def main():
    tabs = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                             os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
            "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                          os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
            "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                         os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    lots = []
    for L in idx["lots"]:
        for s in L["slots"]:
            lots.append({"table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                         "category": str(s["category"]), "item_id": str(s["item_id"]), "row_name": L.get("row_name", "")})

    wb = openpyxl.load_workbook(os.path.join(WS, "法魂资料整合表.xlsx"), read_only=True, data_only=True)
    rows = lambda ws: [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]

    rec, cur_cls = collections.defaultdict(list), ""
    for r in rows(wb["职业推荐道具表3.0"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_cls = r[0]
        if len(r) > 2 and r[2]:
            rec[r[2]].append({"cls": cur_cls, "where": r[3] if len(r) > 3 else "", "kind": r[1]})

    sets, cur_set = collections.defaultdict(list), ""
    piece_where = {}
    for r in rows(wb["套装表"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_set = r[0]
        if len(r) > 1 and r[1]:
            sets[cur_set].append(r[1])
            piece_where[r[1]] = r[3] if len(r) > 3 else ""
    piece_set = {}
    for s, ps in sets.items():
        for p in ps:
            piece_set.setdefault(p, []).append(s)

    basis = json.load(open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), encoding="utf-8"))
    unresolved = sorted({n for names in basis.get("unmatched_all", {}).values() for n in names})

    # 位置关键字：地名 / BOSS 名 / 村庄等
    KW = ["Siofra", "Nokron", "Sellia", "Caria", "Ainsel", "Raya", "Leyndell", "Morne", "Stormveil", "Haligtree",
          "Miquella", "Elphael", "Farum", "Zamor", "Volcano", "Gelmir", "Caelid", "Liurnia", "Limgrave", "Altus",
          "Mohgwyn", "Deeproot", "Rot", "Dragonkin", "Blaidd", "Diallos", "Godskin", "Nox", "Mausoleum", "Jar"]
    CN2EN = {"希芙拉": "Siofra", "诺克隆恩": "Nokron", "瑟利亚": "Sellia", "卡利亚": "Caria", "安瑟尔": "Ainsel",
             "雷亚": "Raya", "王城": "Leyndell", "摩恩": "Morne", "史东薇尔": "Stormveil", "圣树": "Haligtree",
             "米凯拉": "Miquella", "法姆": "Farum", "萨米尔": "Zamor", "火山": "Volcano", "格密尔": "Gelmir",
             "盖利德": "Caelid", "利耶尼亚": "Liurnia", "宁姆格福": "Limgrave", "亚坛": "Altus", "蒙格温": "Mohgwyn",
             "深根": "Deeproot", "腐败": "Rot", "龙人": "Dragonkin", "布莱泽": "Blaidd", "迪亚洛": "Diallos",
             "神皮": "Godskin", "诺克斯": "Nox", "三姊妹": "Three Sisters", "玛莉卡第四教堂": "Church of Marika",
             "安堤": "Anti", "贤者": "Sage"}

    out = []
    for name in unresolved:
        direct = rec.get(name, [])
        classes = sorted({d["cls"] for d in direct})
        sets_of = piece_set.get(name, [])
        set_classes = sorted({d["cls"] for s in sets_of for d in rec.get(s, []) + rec.get(s + "套装", [])})
        where = (direct[0]["where"] if direct else piece_where.get(name, ""))
        # 位置证据
        keys = [en for cn, en in CN2EN.items() if cn in where] + [k for k in KW if k in where]
        cands = []
        for k in keys:
            for L in lots:
                if k.lower() in (L["row_name"] or "").lower():
                    nm = tabs.get({ "3": "protector", "2": "weapon", "1": "goods"}.get(L["category"], ""), {}).get(L["item_id"], "")
                    if nm:
                        cands.append({"kw": k, "row": f"{L['table']}:{L['row_id']}:s{L['slot']}", "row_name": L["row_name"][:60],
                                      "item_id": L["item_id"], "item_name": nm, "cat": L["category"],
                                      "ratio": round(difflib.SequenceMatcher(None, name, nm).ratio(), 3)})
        cands.sort(key=lambda c: -c["ratio"])
        best = cands[0] if cands else None
        # 判定
        if classes:
            kind = "直接推荐"
            excl = len(classes) == 1
        elif set_classes:
            kind = "通用套装件（某职业整套推荐）"
            excl = False
        else:
            kind = "无归属"
            excl = False
        accept = bool(best and best["ratio"] >= 0.8 and excl)
        out.append({"name": name, "source": kind, "direct_classes": classes, "set_of": sets_of, "set_classes": set_classes,
                    "where": where[:70], "location_candidates": cands[:4], "best": best, "exclusive": excl,
                    "accept": accept,
                    "verdict": ("职业专属 · 位置证据可定位 → 入池" if accept else
                                ("职业专属但位置证据不足 → 暂不入池" if excl else "非职业专属 → 不入池"))})
        print(f"  {name:<20} 来源={kind:<18} 职业={classes or set_classes or '—'} 位置={where[:26]:<28} "
              f"最优位置候选={(best['item_name'] + '(' + str(best['ratio']) + ')') if best else '—'} → {out[-1]['verdict']}")
    json.dump(out, open(os.path.join(DRY, "evidence", "exclusivity_judgement.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  入池: {sum(1 for o in out if o['accept'])} | 不入池: {sum(1 for o in out if not o['accept'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
