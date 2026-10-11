# inspect_gaps2.py — 只读：回到资料表原文，判定 9 个未批准套装的缺口是「缺数据」还是「缺匹配」
# 读取：investigation/randomization-catalog/evidence/xml/ProtectorName*.fmg.xml（已解析产物，未重新解包）
#       EquipParamProtector（上一轮解包 XML）、evidence/lot_reward_index.json
#       法魂资料整合表.xlsx『职业初始套装位置表』（只读，与被审资料同一来源）
import csv, json, os, collections
import xml.etree.ElementTree as ET
import openpyxl

REV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(REV), "randomization-catalog")
EV = os.path.join(CAT, "evidence")
WS = os.path.dirname(os.path.dirname(CAT))
RB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "work2", "regulation-bin")

KW = {"head": ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽", "额带", "冠"],
      "body": ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "大衣", "战袍"],
      "arm": ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕", "裹布", "腕", "手甲"],
      "leg": ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "裤", "靴", "腿"]}


def main():
    zh = {}
    for f in ("ProtectorName.fmg.xml", "ProtectorName_dlc01.fmg.xml"):
        p = os.path.join(EV, "xml", f)
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    zh[e.get("id")] = e.text
    part = {}
    for r in ET.parse(os.path.join(RB, "EquipParamProtector.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        part[a["id"]] = next((k for k, fl in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(fl) == "1"), "")
    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    lot = collections.Counter()
    for L in idx["lots"]:
        for s in L["slots"]:
            lot[str(s["item_id"])] += 1
    shop = collections.Counter(str(s["equipId"]) for s in idx["shops"])

    wb = openpyxl.load_workbook(os.path.join(WS, "法魂资料整合表.xlsx"), read_only=True, data_only=True)
    ws = wb["职业初始套装位置表"]
    groups, cur = [], None
    for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
        v = ["" if c is None else str(c).strip() for c in row]
        if ri == 1 or not any(v):
            continue
        if v[0]:
            cur = {"cls": v[0], "cell": f"'职业初始套装位置表'!A{ri}", "pieces": []}
            groups.append(cur)
        if cur is not None and v[1]:
            cur["pieces"].append(v[1])

    bundles = {b["class_name"]: b for b in json.load(open(os.path.join(CAT, "bundles.json"), encoding="utf-8"))["bundles"]}
    print("=== 未批准套装：逐件核对（资料表件名 → FMG/参数 候选）===")
    for g in groups:
        b = bundles.get(g["cls"])
        if not b or b["approvable"]:
            continue
        have = {m["part"]: m for m in b["members"] if m.get("piece_id")}
        print(f"-- {g['cls']}（{b['class_attrs']}，{g['cell']}）")
        for name in g["pieces"]:
            kw = next((p for p, kws in KW.items() if any(k in name for k in kws)), "")
            cands = sorted([(i, n) for i, n in zh.items() if n.startswith(g["cls"]) and part.get(i) == kw], key=lambda x: int(x[0]))
            matched = have.get(kw)
            tag = f"已匹配 {matched['piece_id']}" if matched else ("候选 " + str([(i, n, f"lot{lot.get(i,0)}/shop{shop.get(i,0)}") for i, n in cands]) if cands else "无同前缀同部位候选")
            print(f"     [{kw or '?'}] 资料表「{name}」 → {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
