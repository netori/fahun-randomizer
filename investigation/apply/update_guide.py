# update_guide.py — 让局内《职业说明书》的"获取地区"跟着随机化一起变
#
# 思路：说明书里每行都是 <font>物品名</font> - 地点，而随机化是"拾取点换内容"：
#   格子 C 原本给 OLD(C)，现在给 NEW(C)。
#   · 物品 X 的说明书行数 == X 的格数；
#   · X 的**新地点集合** = { 地点(C) : NEW(C) == X }；
#   · 把 X 的那几行地点整组换成新集合（按序一对一）——语句永远为真。
#
# 地点串的三种来源（依次尝试）：
#   ① MOD 行名方括号里的段（"[Limgrave Tunnels - Stonedigger Troll]"）→ PlaceName 中英配对（base+dlc01+dlc02）
#      · 优先"说明书自己用过的词汇"，段名支持前缀命中（Stormveil → Stormveil Castle）
#   ② 没有方括号 → 整行匹配（"Midra's Gaze"）
#   ③ 行名里根本没有地点（Boss 掉落/事件/商店）→ **直接用该物品在说明书里的那句话**（行名没有地点时的权威来源）
#
# 用法: python update_guide.py --plan <置换表> --lang zh [--out xx.xml] [--report xx.json]
import argparse, collections, csv, html as _html, json, os, re
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
WB = os.path.join(ROOT, "investigation", "weapon-baseline")
GUIDE_ENTRIES = list(range(8800, 8827)) + list(range(8870, 8896))
LINE = re.compile(r'(<font color="#[0-9A-Fa-f]{6}">)([^<]+)(</font>)(\s*-\s*)([^<\n]+)')


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def load_place_dict(lang="zh"):
    """英文地名 → 目标语言地名（base + dlc01 + dlc02 三份，按条目 id 配对）"""
    def all3(l):
        d = {}
        for suff in ("", "_dlc01", "_dlc02"):
            d.update(fmg(os.path.join(APPLY, "work", "msg", l, f"PlaceName{suff}.fmg.xml")))
        return d
    en, zh = all3("en"), all3(lang)
    return [(en[i], zh[i]) for i in sorted(set(en) & set(zh), key=lambda x: int(x))
            if zh[i] and zh[i] != "%null%"]


def guide_lines(xml_text):
    """说明书里所有 (entry, 物品名, 地点串)"""
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
    """行名 → 中文地点（方括号分段 → 说明书词汇 → 前缀/精确；无方括号时整行匹配）"""
    if not row_name:
        return "", ""
    m = re.search(r"\[([^\]]+)\]", row_name)
    if not m:
        return _resolve_seg(row_name.strip(), dict_zh, names_en)
    segs = [x.strip() for x in re.split(r"[-–/]", m.group(1)) if len(x.strip()) >= 4]
    v_hits = [s for s in segs if s.lower() in vocab and s.lower() in dict_zh]
    if v_hits:
        seg = max(v_hits, key=len)
        return dict_zh[seg.lower()], seg
    for seg in list(reversed(segs)) + segs:
        zh, en = _resolve_seg(seg, dict_zh, names_en)
        if zh:
            return zh, en
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", default="")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    plan = [r for r in csv.DictReader(open(a.plan, encoding="utf-8-sig")) if r["old"] != r["new"]]
    src = open(os.path.join(APPLY, "work", "msg", a.lang, "GoodsCaption.fmg.xml"), encoding="utf-8-sig").read()

    # ① 名字表（先建，后面兜底要用）
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

    # ② 说明书自己：物品 → 地点串（兜底用）
    glines = guide_lines(src)
    guide_loc = collections.defaultdict(list)
    for eid, nm, loc in glines:
        k = name2id.get(nm)
        if k:
            guide_loc[k].append(loc)

    # ③ 地名对照 + 说明书词汇
    pairs = load_place_dict(a.lang)
    dict_zh = {en.lower(): zh for en, zh in pairs}
    names_en = list(dict_zh.keys())
    locs_in_guide = {loc for _e, _n, loc in glines}
    vocab = {en.lower() for en, zh in pairs if zh and any(zh in L for L in locs_in_guide)}
    print(f"  地名对照 {len(pairs)} 条 | 说明书词汇 {len(vocab)} 个 | 说明书行 {len(glines)}")

    # ④ 每格的地点
    new_locs = collections.defaultdict(list)
    miss, fb_used = [], []
    for r in plan:
        zh, src_kind = place_of(r["row_name"], dict_zh, vocab, names_en), "行名"
        if not zh[0]:
            cand = sorted(set(guide_loc.get(r["old"], [])))
            if len(cand) == 1:
                zh, src_kind = (cand[0], "(说明书兜底)"), "说明书兜底"
                fb_used.append((r["old"], cand[0]))
        if zh[0]:
            new_locs[r["new"]].append(zh[0])
        else:
            miss.append((r["old"], r["new"], r["source_table"], r["row_id"], r["row_name"][:44]))

    stats = collections.Counter()
    skipped = []

    def fix_entry(m):
        eid, body = int(m.group(1)), m.group(2)
        if eid not in GUIDE_ENTRIES:
            return m.group(0)
        plain = _html.unescape(body)
        lms = list(LINE.finditer(plain))
        if not lms:
            return m.group(0)
        groups = collections.OrderedDict()
        for lm in lms:
            groups.setdefault(lm.group(2), []).append(lm)
        edits = []
        for item_name, group in groups.items():
            key = name2id.get(item_name)
            if not key:
                skipped.append((eid, item_name, "非物品行(套装等)"))
                continue
            locs = sorted(set(new_locs.get(key, [])))
            if not locs:
                stats["未参与随机/无地点"] += 1
                continue
            if len(locs) != len(group):
                stats[f"行数{len(group)}≠地点数{len(locs)}(未改)"] += 1
                continue
            for lm, loc in zip(group, locs):
                edits.append((lm.start(5), lm.end(5), loc))
                stats["地点已改" if loc != lm.group(5).strip() else "地点未变"] += 1
        if not edits:
            return m.group(0)
        out, last = [], 0
        for s0, e0, loc in edits:
            out.append(plain[last:s0]); out.append(loc); last = e0
        out.append(plain[last:])
        return f'<text id="{eid}">' + _html.escape("".join(out), quote=True) + "</text>"

    new_xml = re.sub(r'<text id="(\d+)">(.*?)</text>', fix_entry, src, flags=re.S)
    dst = a.out or os.path.join(APPLY, "work", "msg", a.lang, "GoodsCaption.updated.fmg.xml")
    open(dst, "w", encoding="utf-8-sig").write(new_xml)

    print(f"=== 说明书更新（{os.path.basename(a.plan)} / {a.lang}）===")
    print(f"  置换行 {len(plan)} | 说明书兜底救回 {len(fb_used)} 行 | 仍无地点 {len(miss)} 行")
    print(f"  统计 {dict(stats)}")
    if miss[:5]:
        print(f"  仍无地点样例: {miss[:5]}")
    print(f"  写出 → {dst}")
    if a.report:
        json.dump({"plan": a.plan, "lang": a.lang, "rows": len(plan), "stats": dict(stats),
                   "fallback_used": [list(x) for x in fb_used[:200]],
                   "skipped": skipped[:200], "place_miss": [list(x) for x in miss[:200]]},
                  open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
