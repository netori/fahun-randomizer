# resolve_names.py — 名称解析器：把推荐表里未匹配的名称解析到真实 ID
# 策略（每一种都记录方法，宁缺勿错）：
#   a) 去括号后缀后精确匹配
#   b) 一条里含 "/"、"和"、"、" → 拆开分别解析
#   c) 跨类别匹配（推荐表把部分武器填在"装备"列）
#   d) 相似度 ≥0.85 且唯一最优（与次优差 ≥0.05）
#   e) 护甲：同前缀 + 部位后缀 + 参数部位一致
# 输出：evidence/name_resolution.json（含 unresolved 及候选，供人工裁决）
import collections, csv, difflib, json, os, re, sys
import xml.etree.ElementTree as ET

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
RB = os.path.join(WB, "evidence", "work2", "regulation-bin")
PART_KW = {"head": ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽", "头带", "额带", "冠", "头环", "头巾"],
           "body": ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "大衣", "战袍", "毛皮", "上衣", "束腰衣", "筒形外衣", "斗篷", "罩袍"],
           "arm": ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕", "裹布", "腕", "手甲", "手铐", "手镯"],
           "leg": ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "裤", "靴", "腿", "裙子", "长裙", "工装裤"]}


def fmg(*paths):
    d = {}
    for p in paths:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def main():
    prot = fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))
    wep = fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"), os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))
    goods = fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))
    tabs = {"protector": prot, "weapon": wep, "goods": goods}
    part = {}
    for r in ET.parse(os.path.join(RB, "EquipParamProtector.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        part[a["id"]] = next((k for k, fl in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(fl) == "1"), "")

    basis = json.load(open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), encoding="utf-8"))
    unmatched = basis.get("unmatched_all", {})

    def norm(s):
        return re.sub(r"[（(].*?[)）]", "", s or "").replace(" ", "").strip()

    def resolve_one(name, prefer=None):
        """返回 (table, id, method, note)"""
        n = norm(name)
        # a) 归一化精确
        for t in ([prefer] if prefer else []) + list(tabs):
            if not t:
                continue
            for i, nm in tabs[t].items():
                if norm(nm) == n:
                    return t, i, "normalized_exact", ""
        # e) 护甲前缀 + 部位
        kw = next((k for k, kws in PART_KW.items() if any(x in n for x in kws)), "")
        if kw:
            c = [(i, nm) for i, nm in prot.items() if nm.startswith(n[:2]) and part.get(i) == kw]
            if len(c) == 1:
                return "protector", c[0][0], "prefix+part", ""
        # d) 相似度（归一化后）
        best = []
        for t, tb in tabs.items():
            for i, nm in tb.items():
                best.append((difflib.SequenceMatcher(None, n, norm(nm)).ratio(), t, i, nm))
        best.sort(reverse=True)
        if best and best[0][0] >= 0.85 and (len(best) == 1 or best[0][0] - best[1][0] >= 0.05):
            return best[0][1], best[0][2], f"fuzzy{round(best[0][0],2)}", f"最优 {best[0][3]}"
        return "", "", "", "；".join(f"{round(r,2)}:{nm}({t})" for r, t, i, nm in best[:3])

    resolution, unresolved = {}, []
    for kind, names in unmatched.items():
        prefer = {"装备": "protector", "武器": "weapon", "卢恩": "goods"}.get(kind)
        for name in names:
            # b) 拆多条
            if any(sep in name for sep in ("/", "和", "、")):
                partsn = [p for p in re.split(r"[/、]|和", name) if p.strip()]
                if len(partsn) > 1:
                    got = []
                    for p in partsn:
                        t, i, m, note = resolve_one(p.strip(), prefer)
                        got.append({"part_name": p.strip(), "table": t, "id": i, "method": m, "note": note})
                    resolution[name] = {"multi": got}
                    if not all(g["id"] for g in got):
                        unresolved.append({"kind": kind, "name": name, "note": "拆分后仍有未解析", "detail": got})
                    continue
            t, i, m, note = resolve_one(name, prefer)
            if i:
                resolution[name] = {"table": t, "id": i, "method": m, "note": note}
            else:
                unresolved.append({"kind": kind, "name": name, "note": note})

    json.dump({"resolution": resolution, "unresolved": unresolved},
              open(os.path.join(DRY, "evidence", "name_resolution.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== 名称解析：成功 {len(resolution)} / 未解决 {len(unresolved)} ===")
    print("\n解析成功（去括号/精确/前缀/相似度）:")
    for k, v in list(resolution.items())[:40]:
        if "multi" in v:
            print(f"   {k} → " + " + ".join(f"{g['part_name']}={g['id']}({g['method']})" for g in v["multi"]))
        else:
            print(f"   {k} → {v['id']} [{v['table']}/{v['method']}] {v['note'][:40]}")
    print("\n仍未解决（附最优候选，供人工裁决）:")
    for u in unresolved:
        print(f"   [{u['kind']}] {u['name']} :: {u['note'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
