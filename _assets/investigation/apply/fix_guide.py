# fix_guide.py — 说明书地点同步 v2（锁死版）
#
# 与 v1 的差别：
#   1. 用**物品的全部拾取点**（来自 lot 索引，含计划没动过的那些），而不是只用计划里的 750 格；
#   2. 配对方式改为「指南行 (物品 X, 地点 L) ↔ 物品 X 的某个格子 C，且 loc(C) == L」——
#      地点字符串直接相等才认，认到就**保留地点、把物品换成 NEW(C)**（语句必真）；
#      C 不在计划里（没动过）→ 该行原样保留（也是对的）；
#   3. 多格/无地点的顽固情形，回落到 v1 的"整组换地点"（行数必须等于地点数）；
#   4. 商店格用商店行 name 里的商人名（"[Enia - …]" → 恩雅）补地点。
import argparse, collections, csv, html as _html, json, os, re
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
WB = os.path.join(ROOT, "investigation", "weapon-baseline")
GUIDE_ENTRIES = list(range(8800, 8827)) + list(range(8870, 8896))
LINE = re.compile(r'(<font color="#[0-9A-Fa-f]{6}">)([^<]+)(</font>)(\s*-\s*)([^<\n]+)')
CATCODE = {"protector": "3", "weapon": "2", "goods": "1"}
SHOP_OWNER = {"Enia": "恩雅", "Twin Maiden Husks": "双指侍女", "Merchant": "流浪商人",
              "Smithing Master Hewg": "铁匠胡格", "Roderika": "罗德里卡", "Gideon": "基甸",
              "Ranni": "菈妮", "Iji": "伊吉", "Sellen": "瑟琳", "Yura": "尤拉", "Bernahl": "贝尔纳尔",
              "Patches": "帕奇", "Nomadic Merchant": "流浪商人", "D": "D", "Fia": "菲雅", "Diallos": "迪亚罗斯"}


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def load_place_dict(lang="zh"):
    def all3(l):
        d = {}
        for suff in ("", "_dlc01", "_dlc02"):
            d.update(fmg(os.path.join(APPLY, "work", "msg", l, f"PlaceName{suff}.fmg.xml")))
        return d
    en, zh = all3("en"), all3(lang)
    return [(en[i], zh[i]) for i in sorted(set(en) & set(zh), key=lambda x: int(x)) if zh[i] and zh[i] != "%null%"]


def guide_lines(xml_text):
    out = []
    for eid in GUIDE_ENTRIES:
        m = re.search(r'<text id="%d">(.*?)</text>' % eid, xml_text, re.S)
        if not m:
            continue
        for x in LINE.finditer(_html.unescape(m.group(1))):
            out.append((eid, x.group(2).strip(), x.group(5).strip()))
    return out


def _resolve_seg(seg, dict_zh, names_en):
    k = seg.lower()
    if k in dict_zh:
        return dict_zh[k], seg
    pref = [n for n in names_en if n.startswith(k)]
    if pref:
        n = min(pref, key=len)
        return dict_zh[n], n
    return "", ""


def place_of(row_name, dict_zh, vocab, names_en):
    if not row_name:
        return "", ""
    m = re.search(r"\[([^\]]+)\]", row_name)
    if not m:
        return _resolve_seg(row_name.strip(), dict_zh, names_en)
    segs = [x.strip() for x in re.split(r"[-–/]", m.group(1)) if len(x.strip()) >= 4]
    v = [s for s in segs if s.lower() in vocab and s.lower() in dict_zh]
    if v:
        seg = max(v, key=len)
        return dict_zh[seg.lower()], seg
    for seg in list(reversed(segs)) + segs:
        zh, en = _resolve_seg(seg, dict_zh, names_en)
        if zh:
            return zh, en
    return "", ""


def item_vocab(guide_strs, pairs):
    """该物品在说明书里出现过的地点串 → 反查英文名，构成"专属词表" """
    out = set()
    for L in guide_strs:
        for en, zh in pairs:
            if zh and zh in L:
                out.add(en.lower())
    return out


def place_of_item(row_name, dict_zh, vocab_global, vocab_item, names_en):
    """先按该物品自己的词表挑段，再退化到全局词表/精确/前缀"""
    zh, en = "", ""
    m = re.search(r"\[([^\]]+)\]", row_name or "")
    if m and vocab_item:
        segs = [x.strip() for x in re.split(r"[-–/]", m.group(1)) if len(x.strip()) >= 4]
        for seg in segs:
            k = seg.lower()
            if k in vocab_item and k in dict_zh:
                return dict_zh[k], seg
    return place_of(row_name, dict_zh, vocab_global, names_en)


def shop_owner(shop_name):
    """从商店行 name 取商人名并译成中文（"[Enia - Elemer of the Briar] Briar Helm" → 恩雅）"""
    if not shop_name:
        return ""
    m = re.match(r"\[([^\-\]]+?)\s*-", shop_name)
    who = (m.group(1) if m else shop_name.split(" - ")[0]).strip().strip("[]")
    for en, zh in SHOP_OWNER.items():
        if en.lower() in who.lower():
            return f"由{zh}出售"
    return f"由{who}出售" if who and len(who) < 24 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", default="")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    plan = [r for r in csv.DictReader(open(a.plan, encoding="utf-8-sig")) if r["old"] != r["new"]]
    src = open(os.path.join(APPLY, "work", "msg", a.lang, "GoodsCaption.fmg.xml"), encoding="utf-8-sig").read()

    names = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                              os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
             "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                           os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
             "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                          os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    name2id = {}
    for cat, t in names.items():
        for i, n in t.items():
            name2id.setdefault(n, f"{cat}:{i}")

    glines = guide_lines(src)
    guide_loc = collections.defaultdict(set)
    for eid, nm, loc in glines:
        k = name2id.get(nm)
        if k:
            guide_loc[k].add(loc)

    pairs = load_place_dict(a.lang)
    dict_zh = {en.lower(): zh for en, zh in pairs}
    names_en = list(dict_zh.keys())
    vocab = {en.lower() for en, zh in pairs if zh and any(zh in L for L in {x[2] for x in glines})}

    # ① 计划：格子 → (old_item, new_item)；物品 → 新地点集合（v1 计数法用）
    plan_of = {}
    new_locs = collections.defaultdict(list)
    for r in plan:
        key = (r["source_table"], r["row_id"], r["slot"])
        plan_of[key] = (r["old"], r["new"])
        zh, _ = place_of(r["row_name"], dict_zh, vocab, names_en)
        if not zh:
            cand = sorted(guide_loc.get(r["old"], []))
            if len(cand) == 1:
                zh = cand[0]
        if zh:
            new_locs[r["new"]].append(zh)

    # ② 涉及物品的**全部格子**（来自 lot 索引，含计划没动的）
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    involved = {r["old"] for r in plan} | {r["new"] for r in plan}
    cells_of = collections.defaultdict(list)          # item -> [(key, row_name)]
    for L in idx["lots"]:
        for s in L["slots"]:
            cat = {v: k for k, v in CATCODE.items()}.get(str(s["category"]))
            if not cat:
                continue
            item = f"{cat}:{s['item_id']}"
            if item in involved:
                cells_of[item].append(((L["table"], str(L["lot_id"]), str(s["slot"])), L.get("row_name", "")))
    for s in idx.get("shops", []):
        cat = {"0": "weapon", "1": "protector", "2": "accessory", "3": "goods", "4": "gem"}.get(str(s["equipType"]))
        if not cat:
            continue
        item = f"{cat}:{s['equipId']}"
        if item in involved:
            owner = shop_owner(s.get("name") or s.get("row_name") or "")
            cells_of[item].append((("ShopLineupParam", str(s["shop_row_id"]), ""), owner or ""))

    # ③ 每格地点（行名 → 字典；商店 → 商人；实在没有 → 空）
    loc_of_cell, loc_inferred = {}, []
    for item, cells in cells_of.items():
        iv = item_vocab(guide_loc.get(item, set()), pairs)
        for key, rn in cells:
            if key in loc_of_cell:
                continue
            if key[0] == "ShopLineupParam":
                loc_of_cell[key] = rn or ""
            else:
                zh, _ = place_of_item(rn, dict_zh, vocab, iv, names_en)
                loc_of_cell[key] = zh or ""
        # ③ 一对一推断：该物品只有 1 个格子且说明书只有 1 行 → 那行写的地点就是该格子的地点
        lines = sorted(guide_loc.get(item, set()))
        unknown = [k for k, _ in cells if not loc_of_cell.get(k)]
        if len(unknown) == 1 and len(lines) == 1 and not any(loc_of_cell.get(k) for k, _ in cells):
            loc_of_cell[unknown[0]] = lines[0]
            loc_inferred.append((item, unknown[0], lines[0]))

    # ③a0 兜底：行名判不出地点时，用"这一格原本装的物品"在说明书里的那句话（唯一时才用）
    for r in plan:
        key = (r["source_table"], r["row_id"], r["slot"])
        if loc_of_cell.get(key):
            continue
        cand = sorted(guide_loc.get(r["old"], []))
        if len(cand) == 1:
            loc_of_cell[key] = cand[0]
            loc_inferred.append((r["old"], key, cand[0]))

    # ③a 对称推断：格子地点判不出、但"换进来的物品"只有 1 格 + 说明书只有 1 行 → 那行地点就是这格地点
    for r in plan:
        key = (r["source_table"], r["row_id"], r["slot"])
        if loc_of_cell.get(key):
            continue
        tgt = r["new"]
        tgt_cells = cells_of.get(tgt, [])
        tgt_lines = sorted(guide_loc.get(tgt, set()))
        if len(tgt_cells) == 1 and len(tgt_lines) == 1:
            loc_of_cell[key] = tgt_lines[0]
            loc_inferred.append((tgt, key, tgt_lines[0]))

    # ③b 该物品"现在所在的地点" = 没被随机到的格子（东西没动）+ 计划里换进来的格子
    plan_cell_keys = set(plan_of)
    for item, cells in cells_of.items():
        for key, _rn in cells:
            if key not in plan_cell_keys and loc_of_cell.get(key):
                new_locs[item].append(loc_of_cell[key])
            elif key in plan_cell_keys and plan_of[key][1] == item and loc_of_cell.get(key):
                new_locs[item].append(loc_of_cell[key])

    # ④ 直接匹配改写：行 (X, L) ↔ X 的格子 C 且 loc(C)==L
    #    C 在计划里 → 该行变成 (NEW(C), L)；C 不在计划里 → 保持不变
    direct_ok, direct_kept, unmatched, ambiguous = 0, 0, [], []
    rewrites = {}                                     # (eid, 行序号) -> 新物品名（用于替换）
    for eid, nm, loc in glines:
        item = name2id.get(nm)
        if not item:
            continue
        scored = []
        for k, _rn in cells_of.get(item, []):
            cl = loc_of_cell.get(k, "")
            if not cl:
                continue
            if cl == loc:
                scored.append((3, k))
            elif cl in loc:                       # 指南更具体（"史东薇尔城宝箱" ⊃ "史东薇尔城"）
                scored.append((2, k))
            elif loc in cl:
                scored.append((1, k))
        if not scored:
            unmatched.append((eid, nm, loc, item))
            continue
        best = max(x[0] for x in scored)
        top = [k for sc, k in scored if sc == best]
        moved = [k for k in top if k in plan_of and plan_of[k][0] == item]
        if len(moved) == 1:
            k = moved[0]
        elif len(top) == 1:
            k = top[0]
        elif moved:                               # 同级多个且都在计划里 → 取第一个（下面记账）
            k = moved[0]
        else:
            unmatched.append((eid, nm, loc, item))
            continue
        if len(top) > 1:
            ambiguous.append((eid, nm, loc, len(top)))
        if k in plan_of and plan_of[k][0] == item:
            newitem = plan_of[k][1]
            rewrites[(eid, nm, loc)] = newitem
            direct_ok += 1
        else:
            direct_kept += 1                          # 该地点没被动过，行不用改

    # ⑤ 顽固情形：走 v1 计数法（对"没有直接匹配上行"的物品）
    stats = collections.Counter()
    skipped = []
    stuck_items = {item for _e, _n, _l, item in unmatched}

    def fix_entry(m):
        eid, body = int(m.group(1)), m.group(2)
        if eid not in GUIDE_ENTRIES:
            return m.group(0)
        plain = _html.unescape(body)
        edits = []
        for lm in LINE.finditer(plain):
            nm, loc = lm.group(2).strip(), lm.group(5).strip()
        # 计数法兜底：整块换地点
        groups = collections.OrderedDict()
        for lm in LINE.finditer(plain):
            groups.setdefault(lm.group(2).strip(), []).append(lm)
        for nm, group in groups.items():
            key = name2id.get(nm)
            if not key:
                continue
            locs = sorted(set(new_locs.get(key, [])))
            if len(locs) < len(group):                 # 知道的地点比行数还少 → 只能不动
                stats["计数法未适用"] += 1
                continue
            for lm, loc in zip(group, locs[:len(group)]):
                if loc != lm.group(5).strip():
                    edits.append((lm.start(5), lm.end(5), loc))
                    stats["计数法·改地点"] += 1
        if not edits:
            return m.group(0)
        edits.sort()
        out, last = [], 0
        for s0, e0, txt in edits:
            out.append(plain[last:s0]); out.append(txt); last = e0
        out.append(plain[last:])
        return f'<text id="{eid}">' + _html.escape("".join(out), quote=True) + "</text>"

    new_xml = re.sub(r'<text id="(\d+)">(.*?)</text>', fix_entry, src, flags=re.S)
    dst = a.out or os.path.join(APPLY, "work", "msg", a.lang, "GoodsCaption.updated.fmg.xml")
    open(dst, "w", encoding="utf-8-sig").write(new_xml)

    print(f"=== 说明书同步 v2（{os.path.basename(a.plan)} / {a.lang}）===")
    print(f"  说明书行 {len(glines)} | 直接配对命中 {direct_ok} 行 | 地点未动过的行 {direct_kept} 行 | 未命中 {len(unmatched)} 行 | 同级歧义 {len(ambiguous)} 行")
    print(f"  改写统计 {dict(stats)}（规则：物品名不动、只换它现在所在的地点）")
    print(f"  牵涉物品 {len(involved)} 个 | 其中顽固物品 {len(stuck_items)} 个 | 一对一推断补地点 {len(loc_inferred)} 处")
    if unmatched[:5]:
        print(f"  未命中样例: {[(e, n, l) for e, n, l, _ in unmatched[:5]]}")
    print(f"  写出 → {dst}")
    if a.report:
        json.dump({"plan": a.plan, "lang": a.lang, "lines": len(glines), "direct": direct_ok,
                   "kept": direct_kept, "unmatched": [[e, n, l, i] for e, n, l, i in unmatched[:300]],
                   "stats": dict(stats)}, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
