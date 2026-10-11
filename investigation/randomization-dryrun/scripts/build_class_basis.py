# build_class_basis.py — 新口径候选基础 v2：只收「有职业归属」的装备/武器/卢恩，并按职业倾向分层
# 数据源（只读）：法魂资料整合表.xlsx 的 职业推荐道具表3.0 / 职业初始套装位置表 / 套装表
# v2 修正：① 职业名去「套装」后缀再对接  ② 推荐表里的"套装名"用《套装表》展开成件
#          ③ "与X相同，此处省略" 的行按继承处理  ④ 名称异写（先祖↔祖灵、石浆↔岩浆）用相似度匹配
import collections, csv, difflib, json, os, re, sys
import xml.etree.ElementTree as ET
import openpyxl

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.dirname(os.path.dirname(DRY))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
RB = os.path.join(WB, "evidence", "work2", "regulation-bin")
KIND = {"装备": "protector", "武器": "weapon", "卢恩": "goods"}
# 同义职业名（推荐表 ↔ 初始套装表）：用"卢恩流派"对齐后确认
#   冰霜巫师=冰霜女巫(冰霜) 古龙祀者=龙信徒(雷电) 左道异端=悖逆异端(荆棘) 神皮庆典者=神皮庆典司仪(黑焰)
#   野兽宗徒=野兽虔敬者(野兽) 鲜血新锐=鲜血入道者(血焰) 风暴呼召者=烈风召唤者(风暴)
SYN = {"冰霜巫师": "冰霜女巫", "古龙祀者": "龙信徒", "左道异端": "悖逆异端", "神皮庆典者": "神皮庆典司仪",
       "野兽宗徒": "野兽虔敬者", "鲜血新锐": "鲜血入道者", "风暴呼召者": "烈风召唤者"}
SORCERY = {"辉石", "黑夜", "冰霜", "岩浆", "重力", "死灵"}          # 魔法系流派（ER 分类，可核对）
INCANT = {"野兽", "律法", "恶焰", "雷电", "黑焰", "癫火", "血焰", "腐败", "祖灵", "龙人", "风暴", "荆棘"}
TIERS = ["微光", "闪光", "明亮", "闪耀", "辉光", "幽影"]
PART_KW = {"head": ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽", "头带", "额带", "冠", "头环", "头巾"],
           "body": ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "大衣", "战袍", "毛皮", "上衣", "束腰衣", "筒形外衣", "斗篷", "罩袍"],
           "arm": ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕", "裹布", "腕", "手甲", "手铐", "手镯"],
           "leg": ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "裤", "靴", "腿", "裙子", "长裙", "工装裤"]}


CURATED = {}
_p = os.path.join(DRY, "evidence", "name_resolution_curated.json")
if os.path.exists(_p):
    CURATED = json.load(open(_p, encoding="utf-8"))["entries"]
AUTO = {}          # 解析器（resolve_names.py）自动解析成功的（去括号/拆分/相似度）
OVERRIDE = {}      # 职业倾向人工指定
_p3 = os.path.join(DRY, "evidence", "archetype_overrides.json")
if os.path.exists(_p3):
    OVERRIDE = json.load(open(_p3, encoding="utf-8"))
_p2 = os.path.join(DRY, "evidence", "name_resolution.json")
if os.path.exists(_p2):
    AUTO = json.load(open(_p2, encoding="utf-8"))["resolution"]


def norm_name(s):
    """归一化名称：去括号后缀与空格（用于"燃炉拳套 "这类写法）"""
    return re.sub(r"[（(].*?[)）]", "", s or "").replace(" ", "").strip()


def norm_cls(n):
    return re.sub(r"套装?$", "", (n or "").strip())


def fmg_names(*paths):
    d = {}
    for p in paths:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def archetype_of(effect):
    e = effect or ""
    intel, faith, arc = "智力" in e, "信仰" in e, "感应" in e
    melee = any(k in e for k in ("力量", "敏捷", "耐力", "活力"))
    if intel and (faith or arc):
        return "法师/祷告混合"
    if intel:
        return "法师"
    if faith and arc:
        return "祷告/感应"
    if faith:
        return "祷告"
    if arc:
        return "感应"
    if melee:
        return "近战"
    return "未判定"


def main():
    xlsx = os.path.join(WS, "法魂资料整合表.xlsx")
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = lambda ws: [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]

    # ① 职业推荐道具表3.0
    rec = collections.defaultdict(lambda: collections.defaultdict(list))
    notes = []
    cur_cls, cur_kind = "", ""
    for r in rows(wb["职业推荐道具表3.0"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_cls = r[0]
        if len(r) > 1 and r[1] and r[1] != "武器、装备、卢恩":
            cur_kind = r[1]
        nm = r[2] if len(r) > 2 else ""
        if not nm:
            continue
        if "相同" in nm and "省略" in nm:
            ref = next((c for c in rec if c and c in nm), None) or next((c for c in
                        ("扈从", "狂战士", "先锋", "无畏者", "神射手", "佣兵", "游荡者") if c in nm), None)
            notes.append({"class": cur_cls, "kind": cur_kind, "text": nm, "inherits": ref or ""})
            continue
        rec[cur_cls][cur_kind or "(未标类别)"].append({"name": nm, "where": r[3] if len(r) > 3 else ""})

    # ② 初始套装表（职业名归一 + 效果 → 倾向）
    starter, effect_of = collections.defaultdict(list), {}
    cur = ""
    for r in rows(wb["职业初始套装位置表"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur = norm_cls(r[0])
        if len(r) > 1 and r[1]:
            starter[cur].append({"name": r[1], "effect": r[2] if len(r) > 2 else "", "where": r[3] if len(r) > 3 else ""})
            if cur not in effect_of and (r[2] if len(r) > 2 else ""):
                effect_of[cur] = r[2]

    # ③ 套装表
    sets, cur_set = collections.defaultdict(list), ""
    for r in rows(wb["套装表"])[1:]:
        if not any(r):
            continue
        if r[0]:
            cur_set = r[0]
        if len(r) > 1 and r[1]:
            sets[cur_set].append(r[1])
    set_by_norm = {norm_cls(k): v for k, v in sets.items()}

    # 名称表 / 参数 / 入口
    prot = fmg_names(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))
    wep = fmg_names(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"), os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))
    goods = fmg_names(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))
    part, wcat = {}, {}
    for r in ET.parse(os.path.join(RB, "EquipParamProtector.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        part[a["id"]] = next((k for k, fl in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(fl) == "1"), "")
    for r in ET.parse(os.path.join(RB, "EquipParamWeapon.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        wcat[a["id"]] = {"cat": a.get("weaponCategory", ""), "wepType": a.get("wepType", "")}
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    lot = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot[str(s["item_id"])].append({"table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                           "category": str(s["category"]), "row_name": L.get("row_name", "")})
    shopok = collections.defaultdict(list)
    for s in idx["shops"]:
        if str(s.get("value")) not in ("0", "1", "") and str(s.get("sellQuantity")) not in ("-1", ""):
            shopok[str(s["equipId"])].append({"row_id": str(s["shop_row_id"]), "price": s.get("value"), "stock": s.get("sellQuantity")})
    overlay = {x["item_id"]: x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig")) if x["row_kind"] == "item"}
    starter_ids = {str(p["id"]) for g in json.load(open(os.path.join(REV, "evidence", "starter_set_freeze.json"), encoding="utf-8"))["groups"] for p in g["pieces"]}
    id2name = lambda cat: {"protector": prot, "weapon": wep, "goods": goods}[cat]

    def match(cat, name):
        table = id2name(cat)
        auto = AUTO.get(name)                                     # 解析器自动结果
        if auto and auto.get("id"):
            return auto["id"], "auto(" + auto["method"] + ")"
        auto_multi = AUTO.get(name, {}).get("multi") if auto else None
        if auto_multi:
            for g in auto_multi:
                if g.get("id") and g["part_name"] == name:
                    return g["id"], "auto_multi(" + g["method"] + ")"
        cur = CURATED.get(name)                                   # 人工核准的异名/异写映射
        if cur and cur.get("target"):
            for t in ("protector", "weapon", "goods"):
                for i, n in id2name(t).items():
                    if n == cur["target"]:
                        return i, "curated(" + cur["reason"][:20] + ")"
        if name in table.values():
            return next(i for i, n in table.items() if n == name), "exact_name"
        # 归一化精确匹配（去括号与空格）——覆盖"燃炉拳套 "这类带后缀/空格的写法
        nn = norm_name(name)
        for t in ("protector", "weapon", "goods"):
            for i, n in id2name(t).items():
                if norm_name(n) == nn:
                    return i, "normalized_exact"
        if cat == "protector":                                  # 同前缀 + 部位后缀
            kw = next((k for k, kws in PART_KW.items() if any(x in name for x in kws)), "")
            pref = name[:2]
            c = [(i, n) for i, n in table.items() if n.startswith(pref) and part.get(i) == kw]
            if len(c) == 1:
                return c[0][0], "prefix+part"
        if cat == "goods":                                      # 卢恩：等级前缀 + 相似度
            tier = next((t for t in TIERS if name.startswith(t)), "")
            if tier:
                c = [(i, n) for i, n in table.items() if n.startswith(tier) and n.endswith("卢恩")]
                c.sort(key=lambda x: difflib.SequenceMatcher(None, name, x[1]).ratio(), reverse=True)
                if c and difflib.SequenceMatcher(None, name, c[0][1]).ratio() >= 0.6:
                    return c[0][0], f"tier+similar({round(difflib.SequenceMatcher(None, name, c[0][1]).ratio(),2)})"
        # 通用相似度兜底
        c = difflib.get_close_matches(name, list(table.values()), n=1, cutoff=0.85)
        if c:
            return next(i for i, n in table.items() if n == c[0]), "similar"
        return "", ""

    out_rows, stat = [], collections.Counter()
    unmatched = collections.defaultdict(list)

    # 职业倾向：① 初始套装表的效果文本 ② 同义职业名 ③ 该职业卢恩流派推断
    def arch_of_class(cls, bykind):
        ov = OVERRIDE.get(norm_cls(cls))
        if ov:
            return ov["archetype"], "user_override"
        a = archetype_of(effect_of.get(norm_cls(cls), ""))
        if a != "未判定":
            return a, "effect_text"
        syn = SYN.get(norm_cls(cls))
        if syn:
            a = archetype_of(effect_of.get(syn, ""))
            if a != "未判定":
                return a, f"synonym→{syn}"
        sc = collections.Counter()
        for it in bykind.get("卢恩", []):
            for k in SORCERY | INCANT:
                if k in it["name"]:
                    sc[k] += 1
        if sc:
            s, n = sc.most_common(1)[0]
            return ("法师" if s in SORCERY else "祷告"), f"rune_school:{s}×{n}"
        return "未判定", "no_evidence"

    for cls, bykind in rec.items():
        ncls = norm_cls(cls)
        arch, arch_src = arch_of_class(cls, bykind)
        stat[f"倾向来源:{arch_src.split(':')[0].split('→')[0]}"] += 1
        if arch_src.startswith("synonym"):
            stat["同义职业映射"] += 1
        for kind_cn, items in bykind.items():
            cat = KIND.get(kind_cn)
            if not cat:
                stat[f"跳过类别:{kind_cn}"] += 1
                continue
            expanded = []
            for it in items:
                base = norm_cls(it["name"])
                cur = CURATED.get(it["name"])
                if cur and cur.get("expand_names"):                     # 一名多件（"A/B"、"A和B"）
                    for target in cur["expand_names"]:
                        for t in ("protector", "weapon", "goods"):
                            for i, n in id2name(t).items():
                                if norm_name(n) == norm_name(target):
                                    expanded.append({"name": n, "where": it["where"], "via_set": it["name"]})
                                    break
                    stat["多名条目展开(人工核准)"] += 1
                elif cur and cur.get("expand_prefix"):
                    hits = [(i, n) for i, n in prot.items() if n.startswith(cur["expand_prefix"]) and part.get(i)]
                    expanded += [{"name": n, "where": it["where"], "via_set": it["name"]} for i, n in hits]
                    stat["套装名展开(人工核准)"] += 1
                elif it["name"].endswith(("套装", "套")):
                    # 只有"看起来是套装名"才展开：① 套装表里有 ② FMG 前缀能命中 ≥2 件且都带部位
                    # 注意：以"套"结尾的普通物品（如 燃炉拳套）必须落到普通匹配，否则会被误判为套装名
                    if base in set_by_norm:
                        expanded += [{"name": p, "where": it["where"], "via_set": it["name"]} for p in set_by_norm[base]]
                        stat["套装名展开(套装表)"] += 1
                    else:
                        hits = [(i, n) for i, n in prot.items() if n.startswith(base) and part.get(i)]
                        need = 1 if it["name"].endswith("套装") else 2
                        if len(hits) >= need:
                            expanded += [{"name": n, "where": it["where"], "via_set": it["name"]} for i, n in hits]
                            stat["套装名展开(FMG前缀)"] += 1
                        else:
                            expanded.append(it)                      # 不是套装名 → 按普通物品处理
                else:
                    expanded.append(it)
            for it in expanded:
                cat = KIND.get(kind_cn)          # 每件都按表列重新取，避免被上一件的类别纠正污染
                stat[f"{kind_cn}:条目"] += 1
                iid, method = match(cat, it["name"])
                if not iid:
                    unmatched[kind_cn].append(it["name"])
                    stat[f"{kind_cn}:未匹配"] += 1
                    continue
                stat[f"{kind_cn}:匹配"] += 1
                # 类别纠正：推荐表把部分武器/道具填在"装备"列（如 象牙小镰刀、癫火圣印记）
                if iid in wep:
                    rcat = "weapon"
                elif iid in goods:
                    rcat = "goods"
                else:
                    rcat = "protector"
                if rcat != cat:
                    stat["类别纠正(表列与实际不符)"] += 1
                cat = rcat
                if cat == "protector":
                    sub, extra = f"armor:{part.get(iid,'?')}@{arch}", part.get(iid, "")
                elif cat == "weapon":
                    sub, extra = f"weapon:cat{wcat.get(iid,{}).get('cat','?')}@{arch}", f"cat={wcat.get(iid,{}).get('cat','')}/type={wcat.get(iid,{}).get('wepType','')}"
                else:
                    ov = overlay.get(iid, {})
                    sub, extra = f"rune:{ov.get('rune_tier','?')}@{arch}", f"{ov.get('rune_tier','')}/{ov.get('rune_school','')}"
                lots = [x for x in lot.get(iid, []) if x["category"] == {"protector": "3", "weapon": "2", "goods": "1"}[cat]]
                has = bool(lots or shopok.get(iid))
                stat["有入口" if has else "无入口"] += 1
                out_rows.append({"class_name": ncls, "archetype": arch, "kind": kind_cn, "category": cat,
                                 "sheet_name": it["name"], "via_set": it.get("via_set", ""), "matched_id": iid,
                                 "match_method": method, "subpool_proposal": sub, "param_extra": extra,
                                 "lot_entrances": len(lots), "clean_shop_rows": len(shopok.get(iid, [])),
                                 "has_entrance": "yes" if has else "",
                                 "in_current_catalog": overlay.get(iid, {}).get("final_decision", "(不在)"),
                                 "is_starter_set_piece": "yes" if iid in starter_ids else "",
                                 "sheet_location": it["where"][:60]})

    with open(os.path.join(DRY, "class_candidate_draft.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    json.dump({"archetype_by_class": {c: archetype_of(e) for c, e in effect_of.items()},
               "effect_by_class": effect_of, "inheritance_notes": notes,
               "set_table": {k: v for k, v in sets.items()},
               "stats": dict(stat), "unmatched_examples": {k: v[:20] for k, v in unmatched.items()},
               "unmatched_all": {k: v for k, v in unmatched.items()},
               "unmatched_by_class": {k: sorted({c for c in []}) for k in unmatched}},
              open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=== 新口径候选基础 v2 ===")
    print("  职业（推荐表）:", len(rec), "| 初始套装表:", len(starter), "| 套装表:", len(sets), "| 继承备注:", len(notes))
    for k, v in sorted(stat.items()):
        print(f"   {k}: {v}")
    print()
    print("  职业倾向 × 职业:", dict(collections.Counter(archetype_of(e) for e in effect_of.values())))
    for kind in ("装备", "武器", "卢恩"):
        rs = [r for r in out_rows if r["kind"] == kind]
        print(f"  {kind}: 匹配 {len(rs)} 条 / 有入口 {sum(1 for r in rs if r['has_entrance'])} 条 | 按倾向 {dict(collections.Counter(r['archetype'] for r in rs))}")
        if kind == "装备":
            print("     按部位池:", dict(collections.Counter(r["subpool_proposal"].split("@")[0] for r in rs)))
        if kind == "武器":
            print("     按类别池:", dict(collections.Counter(r["subpool_proposal"].split("@")[0] for r in rs)))
        if kind == "卢恩":
            print("     按等级池:", dict(collections.Counter(r["subpool_proposal"].split("@")[0] for r in rs)))
    print()
    print("  大山羊臂甲:", [(r["class_name"], r["archetype"], r["subpool_proposal"]) for r in out_rows if r["sheet_name"] == "大山羊臂甲"])
    print("  未匹配（每类前 8）:")
    for k, v in unmatched.items():
        print(f"    {k}: {v[:8]}")
    print("\n写出 class_candidate_draft.csv 与 evidence/class_candidate_basis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
