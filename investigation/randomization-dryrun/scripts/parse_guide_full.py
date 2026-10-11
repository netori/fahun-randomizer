# parse_guide_full.py — 全量解析局内《职业说明书》正文
# 说明书正文 = GoodsCaption.fmg：8800-8826（护甲 + 卢恩）、8870-8895（武器），其余条目（卷轴/祷告书）不是说明书
# 解析：逐条取「名称 - 地点」行，用名称表判定类别；名称对不上时按 套装表 / 前缀 / 相似度(≥0.85) 兜底
# 输出：evidence/guide_full_parse.json + guide_candidate_draft.csv（含护甲）
import collections, csv, difflib, json, os, re
import xml.etree.ElementTree as ET
import openpyxl

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.dirname(os.path.dirname(DRY))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
CATCODE = {"protector": "3", "weapon": "2", "goods": "1"}
SYN = {"冰霜巫师": "冰霜女巫", "古龙祀者": "龙信徒", "左道异端": "悖逆异端", "神皮庆典者": "神皮庆典司仪",
       "野兽宗徒": "野兽虔敬者", "鲜血新锐": "鲜血入道者", "风暴呼召者": "烈风召唤者"}
SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}
SUF3 = {"000": "head", "100": "body", "200": "arm", "300": "leg"}          # MOD 护甲 id 尾 3 位
SUF4 = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}      # 8 位 id 尾 4 位


def part_code_of(iid):
    """返回 (部位码, 套装基号)：兼容 6/7/8 位 id（例 5253000→head/5253、5230100→body/5230）"""
    i = str(iid)
    if i[-4:] in SUF4:
        return i[-4:], i[:-4]
    if i[-3:] in SUF3:
        return i[-3:], i[:-3]
    return "", ""


def part_of(iid):
    c, _ = part_code_of(iid)
    return SUF4.get(c) or SUF3.get(c) or ""

MELEE_ENTRY = {"8800": "扈从", "8801": "先锋", "8802": "神射手", "8803": "狂战士", "8804": "无畏者", "8805": "佣兵", "8806": "游荡者"}
GUIDE_ENTRIES = list(range(8800, 8827)) + list(range(8870, 8896))


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
    texts = {e.get("id"): (e.text or "") for e in ET.parse(os.path.join(WB, "evidence", "xml", "GoodsCaption.fmg.xml")).getroot().findall(".//text")}
    tables = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
              "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"), os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
              "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    by_norm, all_names = {c: collections.defaultdict(list) for c in tables}, {c: list(t.values()) for c, t in tables.items()}
    for c, t in tables.items():
        for i, n in t.items():
            by_norm[c][norm(n)].append(i)

    wb = openpyxl.load_workbook(os.path.join(WS, "法魂资料整合表.xlsx"), read_only=True, data_only=True)
    setmap, cur = {}, ""
    for r in wb["套装表"].iter_rows(values_only=True):
        v = ["" if x is None else str(x).strip() for x in r]
        if not any(v):
            continue
        if v[0]:
            cur = v[0]
        if len(v) > 1 and v[1]:
            base = norm(cur).rstrip("套").rstrip("装")
            for k in {norm(cur), base + "套装", base + "套", base}:
                setmap.setdefault(k, []).append(v[1])

    arch_of = dict(json.load(open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), encoding="utf-8"))["archetype_by_class"])
    CURATED = json.load(open(os.path.join(DRY, "evidence", "name_resolution_curated.json"), encoding="utf-8"))["entries"]
    for cls, ov in json.load(open(os.path.join(DRY, "evidence", "archetype_overrides.json"), encoding="utf-8")).items():
        arch_of.setdefault(cls, ov["archetype"] if isinstance(ov, dict) else ov)
    wcat = {}
    for row in ET.parse(os.path.join(WB, "evidence", "work2", "regulation-bin", "EquipParamWeapon.param.xml")).getroot().find("rows").findall("row"):
        wcat[row.attrib["id"]] = row.attrib.get("weaponCategory", "?")
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    lot, shop = collections.defaultdict(list), collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot[(str(s["category"]), str(s["item_id"]))].append({"source_table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                                                 "category": str(s["category"]), "row_name": L.get("row_name", "")})
    for s in idx["shops"]:
        if str(s.get("value")) not in ("0", "1", "") and str(s.get("sellQuantity")) not in ("-1", ""):
            shop[(str(s["equipType"]), str(s["equipId"]))].append({"source_table": "ShopLineupParam", "row_id": str(s["shop_row_id"]), "slot": "",
                                                                   "category": str(s["equipType"]), "row_name": f"shop row {s['shop_row_id']}"})

    def resolve_one(name):
        nn = norm(name)
        hits = []
        for c in ("protector", "weapon", "goods"):
            hits += [(c, i) for i in by_norm[c].get(nn, [])]
        if hits:
            return hits, "exact"
        # 套装名：先按《套装表》，再按 MOD 命名前缀（"拉塔恩套装" → 拉塔恩头盔/铠甲/臂甲/腿甲）
        for key in (nn, nn + "套装", nn.rstrip("套装") + "套装"):
            if key in setmap:
                out = []
                for piece in setmap[key]:
                    for c in ("protector", "weapon", "goods"):
                        out += [(c, i) for i in by_norm[c].get(norm(piece), [])]
                if out:
                    return out, "set_table"
        # 套装名 → 按 id 家族展开：先用「基名+件名」定位家族，再取该家族全部件
        if nn.endswith(("套装", "套")):
            base = nn.rstrip("套装").rstrip("套")
            if len(base) >= 2:
                PARTWORDS = ("头盔", "头冠", "双生冠", "面具", "风帽", "铠甲", "长袍", "上衣", "罩袍", "臂甲",
                             "手环", "腕带", "手套", "腿甲", "长裤", "靴子", "绑腿", "披风", "兜帽", "帽子")
                pref = [i for i, n in tables["protector"].items() if norm(n).startswith(base) and part_code_of(i)[0]]
                fam_exact = collections.Counter()
                for i in pref:                                     # 家族信号：件名恰好是「基名+部位词」（黑夜头盔→黑夜套装）
                    nm = norm(tables["protector"][i])
                    if nm.startswith(base) and nm[len(base):] in PARTWORDS:
                        fam_exact[part_code_of(i)[1]] += 1
                fam = fam_exact.most_common(1)[0][0] if fam_exact else ""
                if fam:
                    out = [("protector", i) for i, n in tables["protector"].items() if part_code_of(i)[1] == fam]
                    if 1 <= len(out) <= 12:
                        return out, f"set_family({fam})"
                if 1 <= len(pref) <= 12:
                    return [("protector", i) for i in pref], "set_prefix"
        # 人工映射（异名/前缀）
        cur = CURATED.get(name)
        if cur:
            if cur.get("target"):
                for c in ("protector", "weapon", "goods"):
                    for i, n in tables[c].items():
                        if n == cur["target"]:
                            return [(c, i)], "curated"
            if cur.get("expand_prefix"):
                out = [("protector", i) for i, n in tables["protector"].items()
                       if norm(n).startswith(cur["expand_prefix"]) and part_code_of(i)[0]]
                if out:
                    return out, "curated_prefix"
        # 部位后缀：名称"X+部位词" → 用部件编号筛（凯丹腿甲 → 凯丹*且 id 尾 0300）
        PART_OF = {"头盔": "0000", "头冠": "0000", "风帽": "0000", "面具": "0000", "面罩": "0000", "斗笠": "0000",
                   "铠甲": "0100", "长袍": "0100", "上衣": "0100", "罩袍": "0100", "衣服": "0100",
                   "臂甲": "0200", "腕套": "0200", "手套": "0200", "手甲": "0200",
                   "腿甲": "0300", "长裤": "0300", "靴子": "0300", "绑腿": "0300", "裤子": "0300"}
        for suf, code in PART_OF.items():
            if nn.endswith(suf) and len(nn) > len(suf):
                base = nn[:-len(suf)]
                out = [("protector", i) for i, n in tables["protector"].items()
                       if norm(n).startswith(base) and part_code_of(i)[0] == code]
                if len(out) == 1:
                    return out, f"prefix+part({suf})"
        # 单件：前缀唯一命中 / 相似度 ≥0.8
        for c in ("protector", "weapon", "goods"):
            pref = [i for n, ids in by_norm[c].items() if len(nn) >= 3 and n.startswith(nn) for i in ids]
            if len(pref) == 1:
                return [(c, pref[0])], "prefix"
        for c in ("protector", "weapon", "goods"):
            close = difflib.get_close_matches(nn, [norm(x) for x in all_names[c]], n=1, cutoff=0.8)
            if close:
                return [(c, by_norm[c][close[0]][0])], "similar"
        return [], "unresolved"

    def resolve(name):
        """支持一条多名（"石像鬼大剑/戟"、"死王子杖与家族头连枷"）"""
        parts = [x for x in re.split(r"[/、]|与|和", name) if x.strip()]
        if len(parts) > 1:
            out, methods = [], []
            for pn in parts:
                hits, how = resolve_one(pn if len(pn) >= 2 else pn)
                out += hits
                methods.append(how)
            if out:
                return out, "multi(" + ",".join(sorted(set(methods))) + ")"
            return [], "unresolved"
        return resolve_one(name)

    rows, unresolved, classes = [], collections.Counter(), {}
    for eid in GUIDE_ENTRIES:
        t = texts.get(str(eid))
        if not t:
            continue
        lines = [x for x in (re.sub(r"<[^>]+>", "", y).strip() for y in t.split("\n")) if x]
        if str(eid) in MELEE_ENTRY:
            cls = MELEE_ENTRY[str(eid)]
        else:
            m = re.match(r"^(.+?)(?:主要|偏好|喜欢|不偏向)", lines[0])
            cls = m.group(1).strip() if m else "?"
        ncls = SYN.get(cls, cls)
        arch = arch_of.get(ncls, arch_of.get(cls, "未判定"))
        d = classes.setdefault(ncls, {"entries": [], "first_line": lines[0][:40], "arch": arch, "counts": collections.Counter()})
        d["entries"].append(str(eid))
        for L in (lines if str(eid) in MELEE_ENTRY else lines[1:]):
            if L.endswith("：") or L.endswith(":") or L.startswith(("以下地点", "交给", "·")) or re.match(r"^[^\-–—]{0,12}(主要|偏好|喜欢|不偏向)", L):
                continue
            mm = re.match(r"^\s*(.+?)\s*[-–—]\s*(.+?)\s*$", L)
            if not mm:
                continue
            name, where = mm.group(1).strip(), mm.group(2).strip()
            hits, how = resolve(name)
            if not hits:
                unresolved[name] += 1
                continue
            for c, iid in hits:
                rows.append({"class_name": ncls, "guide_class": cls, "entry": str(eid), "archetype": arch, "category": c,
                             "guide_name": name, "matched_id": iid, "where": where, "how": how})
                d["counts"][c] += 1
    seen, uniq = set(), []
    for r in rows:
        k = (r["class_name"], r["category"], r["matched_id"])
        if k in seen:
            continue
        seen.add(k)
        r["cells"] = lot.get((CATCODE[r["category"]], r["matched_id"]), []) + shop.get((CATCODE[r["category"]], r["matched_id"]), [])
        r["has_entrance"] = "yes" if r["cells"] else ""
        if r["category"] == "protector":
            part = part_of(r["matched_id"])
            r["subpool_proposal"] = f"armor:{part}@{r['archetype']}" if part else f"armor:?@{r['archetype']}"
        elif r["category"] == "weapon":
            r["subpool_proposal"] = f"weapon:cat{wcat.get(r['matched_id'], '?')}@{r['archetype']}"
        else:
            r["subpool_proposal"] = f"rune:tier@{r['archetype']}"
        uniq.append(r)

    cols = ["class_name", "guide_class", "entry", "archetype", "category", "guide_name", "matched_id", "subpool_proposal", "has_entrance", "where", "how"]
    with open(os.path.join(DRY, "guide_candidate_draft.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in uniq:
            w.writerow({k: r.get(k, "") for k in cols})
    stats = collections.Counter()
    for r in uniq:
        stats[f"{r['category']}:{'有入口' if r['has_entrance'] else '无入口'}"] += 1
    uniqids = {(r["category"], r["matched_id"]) for r in uniq if r["has_entrance"] == "yes"}
    json.dump({"classes": {k: {"entries": v["entries"], "arch": v["arch"], "counts": dict(v["counts"])} for k, v in classes.items()},
               "stats": dict(stats), "unique_with_entrance": len(uniqids), "unresolved_names": dict(unresolved)},
              open(os.path.join(DRY, "evidence", "guide_full_parse.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("=== 说明书全量解析（8800-8826 + 8870-8895）===")
    print(f"  职业 {len(classes)} | 去重(职业×类别×id) {len(uniq)} | 有入口去重 {len(uniqids)}")
    for k, v in sorted(stats.items()):
        print(f"   {k}: {v}")
    print(f"  未解析名称 {len(unresolved)} 个: {list(unresolved)[:14]}")
    print()
    for c, d in sorted(classes.items(), key=lambda kv: -kv[1]["counts"]["protector"]):
        print(f"    {c:<10} 护甲 {d['counts']['protector']:>2} | 武器 {d['counts']['weapon']:>2} | 卢恩 {d['counts']['goods']:>2}  条目 {','.join(d['entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
