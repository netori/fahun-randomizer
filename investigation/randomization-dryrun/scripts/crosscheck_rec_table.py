# crosscheck_rec_table.py — 用《职业推荐道具表3.0》交叉核对说明书里未解析的 15 个名称
# 思路：① 推荐表里有同名/近名 → 看它的职业与地点；② 地点文本高度重合 → 认为两表指的是同一样东西
#       ③ 对推荐表那一侧的"名字"再做一次名称表解析（含套装表/前缀+部位），拿到 ID
import collections, csv, difflib, json, os, re
import xml.etree.ElementTree as ET
import openpyxl

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.dirname(os.path.dirname(DRY))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}
PART_OF = {"头盔": "0000", "头冠": "0000", "风帽": "0000", "面具": "0000", "斗笠": "0000", "罩": "0000",
           "铠甲": "0100", "长袍": "0100", "上衣": "0100", "罩袍": "0100",
           "臂甲": "0200", "腕套": "0200", "手套": "0200",
           "腿甲": "0300", "长裤": "0300", "靴子": "0300", "绑腿": "0300"}


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
    # 1) 说明书里未解析名称 + 它们的地点
    texts = {e.get("id"): (e.text or "") for e in ET.parse(os.path.join(WB, "evidence", "xml", "GoodsCaption.fmg.xml")).getroot().findall(".//text")}
    unresolved = json.load(open(os.path.join(DRY, "evidence", "guide_full_parse.json"), encoding="utf-8"))["unresolved_names"]
    guide_lines = collections.defaultdict(list)
    for eid in list(range(8800, 8827)) + list(range(8870, 8896)):
        t = texts.get(str(eid))
        if not t:
            continue
        for L in (re.sub(r"<[^>]+>", "", y).strip() for y in t.split("\n")):
            m = re.match(r"^\s*(.+?)\s*[-–—]\s*(.+?)\s*$", L) if L else None
            if m and m.group(1).strip() in unresolved:
                guide_lines[m.group(1).strip()].append({"entry": str(eid), "where": m.group(2).strip()})

    # 2) 推荐表
    wb = openpyxl.load_workbook(os.path.join(WS, "法魂资料整合表.xlsx"), read_only=True, data_only=True)
    rec, cur_cls, cur_kind = [], "", ""
    for r in wb["职业推荐道具表3.0"].iter_rows(values_only=True):
        v = ["" if x is None else str(x).strip() for x in r]
        if not any(v):
            continue
        if v[0]:
            cur_cls = v[0]
        if len(v) > 1 and v[1] and v[1] != "武器、装备、卢恩":
            cur_kind = v[1]
        if len(v) > 2 and v[2]:
            rec.append({"cls": cur_cls, "kind": cur_kind, "name": v[2], "where": v[3] if len(v) > 3 else ""})

    # 3) 名称表（用于把推荐表那侧的名字解析成 ID）
    tables = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
              "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"), os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
              "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    by_norm = {c: collections.defaultdict(list) for c in tables}
    for c, t in tables.items():
        for i, n in t.items():
            by_norm[c][norm(n)].append(i)

    def resolve(name):
        nn = norm(name)
        hits = []
        for c in ("protector", "weapon", "goods"):
            hits += [(c, i) for i in by_norm[c].get(nn, [])]
        if hits:
            return hits, "exact"
        for suf, code in PART_OF.items():
            if nn.endswith(suf) and len(nn) > len(suf):
                base = nn[:-len(suf)]
                out = [("protector", i) for i, n in tables["protector"].items() if norm(n).startswith(base) and i[-4:] == code]
                if len(out) == 1:
                    return out, f"prefix+part({suf})"
        if nn.endswith(("套装", "套")):
            base = nn.rstrip("套装").rstrip("套")
            out = [("protector", i) for i, n in tables["protector"].items() if norm(n).startswith(base) and i[-4:] in SUF]
            if 1 <= len(out) <= 12:
                return out, "set_prefix"
        for c in ("protector", "weapon", "goods"):
            close = difflib.get_close_matches(nn, [norm(x) for x in tables[c].values()], n=1, cutoff=0.7)
            if close:
                return [(c, by_norm[c][close[0]][0])], "similar(0.7)"
        return [], "unresolved"

    print("=== 说明书未解析名称 × 推荐表交叉核对 ===")
    out = []
    for name in sorted(unresolved):
        gl = guide_lines.get(name, [])
        gw = " / ".join(g["where"] for g in gl)
        # 推荐表：同名/近名
        same = [r for r in rec if norm(r["name"]) == norm(name)]
        near = [r for r in rec if not same and difflib.SequenceMatcher(None, norm(name), norm(r["name"])).ratio() >= 0.7]
        # 推荐表：地点重合（取最长公共子串长度 ≥4）
        byloc = []
        for r in rec:
            if not r["where"] or not gw:
                continue
            sm = difflib.SequenceMatcher(None, norm(gw), norm(r["where"]))
            blk = sm.find_longest_match(0, len(norm(gw)), 0, len(norm(r["where"])))
            if blk.size >= 4:
                byloc.append({**r, "overlap": norm(gw)[blk.a:blk.a + blk.size], "size": blk.size})
        byloc.sort(key=lambda x: -x["size"])
        cand = []
        for r in same + near[:4]:
            hid, how = resolve(r["name"])
            cand.append({"src": "推荐表同名/近名", "rec_name": r["name"], "cls": r["cls"], "kind": r["kind"], "where": r["where"][:40],
                         "resolved": [f"{c}:{i}" for c, i in hid], "how": how})
        for r in byloc[:3]:
            hid, how = resolve(r["name"])
            cand.append({"src": f"地点重合({r['overlap']})", "rec_name": r["name"], "cls": r["cls"], "kind": r["kind"], "where": r["where"][:40],
                         "resolved": [f"{c}:{i}" for c, i in hid], "how": how})
        out.append({"name": name, "guide_where": gw, "guide_entries": [g["entry"] for g in gl], "candidates": cand})
        print(f"\n  【{name}】说明书地点: {gw[:60]}")
        if not cand:
            print("     推荐表里没有任何同名/近名/地点重合的条目")
        for c in cand:
            print(f"     ← {c['src']}: 推荐表「{c['rec_name']}」({c['cls']}/{c['kind']}) 地点「{c['where']}」 → {c['resolved'] or '未解析'} [{c['how']}]")
    json.dump(out, open(os.path.join(DRY, "evidence", "rec_table_crosscheck.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  写出 evidence/rec_table_crosscheck.json（{len(out)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
