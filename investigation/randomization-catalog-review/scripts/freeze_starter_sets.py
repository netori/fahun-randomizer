# freeze_starter_sets.py — 只读：定位「职业初始套装」的全部真实物品并生成冻结清单（D5）
# 输入（只读）：法魂资料整合表.xlsx『职业初始套装位置表』、randomization-catalog/evidence/xml/ProtectorName*.fmg.xml、
#               上一轮解包 EquipParamProtector.param.xml、evidence/lot_reward_index.json、bundles.json
# 方法（每条都记录 match_method）：
#   exact_name        : 资料表件名 与 FMG 名称逐字相同
#   prefix_part       : 同前缀 + 部位后缀 + 与 EquipParamProtector 部位标志一致
#   id_quadruple      : MOD 套装惯用连续四位 ID（x0000/x0100/x0200/x0300）且四件部位互补（head/body/arm/leg 各一）
#   variant_map       : 已在上轮缺口分析中确认的写法差异（裹布→腕带、诺克先知→诺克斯神谕官、死灵法师→死灵术士…）
# 输出：randomization-catalog-review/evidence/starter_set_freeze.json + evidence/frozen_items.csv
import csv, json, os, collections
import xml.etree.ElementTree as ET
import openpyxl

REV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(REV), "randomization-catalog")
EV = os.path.join(CAT, "evidence")
WS = os.path.dirname(os.path.dirname(CAT))
RB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "work2", "regulation-bin")

KW = {"head": ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽", "头带", "额带", "冠", "头环"],
      "body": ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "大衣", "战袍", "毛皮"],
      "arm": ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕", "裹布", "腕", "手甲", "手铐", "手镯"],
      "leg": ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "裤", "靴", "腿", "裙子", "长裙"]}
SUFFIXES = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}


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
    lot = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot[str(s["item_id"])].append({"table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                           "category": str(s["category"]), "row_name": L.get("row_name", "")})
    shop = collections.defaultdict(list)
    for s in idx["shops"]:
        shop[str(s["equipId"])].append(str(s["shop_row_id"]))

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
            cur["pieces"].append({"name": v[1], "cell": f"'职业初始套装位置表'!B{ri}"})

    bundles = {b["class_name"]: b for b in json.load(open(os.path.join(CAT, "bundles.json"), encoding="utf-8"))["bundles"]}
    out, frozen_ids = [], {}
    for g in groups:
        rec = {"class_name": g["cls"], "class_cell": g["cell"], "pieces": [], "method": [], "complete_quadruple": False}
        matched = {}
        # 1) 逐件：exact / prefix_part
        for p in g["pieces"]:
            n = p["name"]
            if n in zh.values():
                for i, nn in zh.items():
                    if nn == n:
                        matched[i] = {"sheet_name": n, "cell": p["cell"], "method": "exact_name", "fmg_name": nn, "part": part.get(i, "")}
            kw = next((k for k, kws in KW.items() if any(x in n for x in kws)), "")
            if kw and not any(m["sheet_name"] == n for m in matched.values()):
                for i, nn in sorted(zh.items(), key=lambda x: int(x[0])):
                    if nn.startswith(g["cls"]) and part.get(i) == kw:
                        matched[i] = {"sheet_name": n, "cell": p["cell"], "method": "prefix_part", "fmg_name": nn, "part": part.get(i, "")}
                        break
        # 2) id_quadruple：用已匹配到的 id 推导基址，补齐同族四位
        bases = collections.Counter()
        for i in list(matched):
            tail = str(i)[-4:]
            if tail in SUFFIXES:
                bases[int(str(i)[:-4] or 0)] += 1
        for base, _ in bases.most_common(1):
            quad = {int(str(base) + s): partk for s, partk in SUFFIXES.items()}
            if any(int(i) not in zh for i in quad):
                continue
            have = {int(i): v["part"] or part.get(i, "") for i, v in matched.items() if int(i) in quad}
            if len(set(have.values())) < 2:
                continue
            for i, partk in quad.items():
                if str(i) not in matched:
                    matched[str(i)] = {"sheet_name": "", "cell": g["cell"], "method": "id_quadruple",
                                       "fmg_name": zh[str(i)], "part": part.get(str(i), "")}
                elif matched[str(i)]["method"] == "id_quadruple":
                    pass
        # 3) 完整性判定
        parts_present = {v["part"] for v in matched.values() if v["part"]}
        rec["complete_quadruple"] = parts_present == {"head", "body", "arm", "leg"}
        for i, v in sorted(matched.items(), key=lambda x: int(x[0])):
            ent = lot.get(i, [])
            rec["pieces"].append({"id": i, "fmg_name": v["fmg_name"], "part": v["part"],
                                  "sheet_name": v["sheet_name"], "match_method": v["method"],
                                  "lot_entrances": ent, "shop_rows": shop.get(i, []),
                                  "bundle_class": [k for k, b in bundles.items() if any(m.get("piece_id") and str(m["piece_id"]) == i for m in b["members"])]})
            if ent or shop.get(i):
                frozen_ids[i] = {"class_name": g["cls"], "fmg_name": v["fmg_name"], "part": v["part"],
                                 "match_method": v["method"], "slots": [f"{e['table']}:{e['row_id']}:s{e['slot']}" for e in ent],
                                 "shop_rows": shop.get(i, [])}
            rec["method"].append(v["method"])
        out.append(rec)

    json.dump({"rule": "D5：职业初始套装（法魂资料整合表『职业初始套装位置表』所列）不参与随机（双向冻结）",
               "method_legend": {"exact_name": "资料表名与 FMG 名逐字相同",
                                 "prefix_part": "同前缀+部位后缀且与参数部位标志一致",
                                 "id_quadruple": "MOD 套装惯用连续四位 ID（x0000/0100/0200/0300）且四件部位互补",
                                 "variant_map": "上轮缺口分析确认的写法差异"},
               "groups": out, "frozen_ids_with_entrance": frozen_ids,
               "counts": {"classes": len(out), "matched_pieces": sum(len(g["pieces"]) for g in out),
                          "complete_quadruples": sum(1 for g in out if g["complete_quadruple"]),
                          "frozen_ids_with_entrance": len(frozen_ids)}},
              open(os.path.join(REV, "evidence", "starter_set_freeze.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    cols = ["item_id", "class_name", "fmg_name", "part", "match_method", "lot_slots", "shop_rows"]
    with open(os.path.join(REV, "evidence", "frozen_items.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, v in sorted(frozen_ids.items(), key=lambda x: int(x[0])):
            w.writerow({"item_id": i, "class_name": v["class_name"], "fmg_name": v["fmg_name"], "part": v["part"],
                        "match_method": v["match_method"], "lot_slots": " | ".join(v["slots"]), "shop_rows": " | ".join(v["shop_rows"])})

    print("=== 职业初始套装：逐组识别 ===")
    for g in out:
        flag = "四件齐" if g["complete_quadruple"] else "不齐"
        ids = "、".join(f"{p['id']}:{p['fmg_name']}({p['match_method'][:6]})" for p in g["pieces"])
        print(f"  {g['class_name']:<8} [{flag}] {ids}")
    print()
    stats = {"classes": len(out), "matched_pieces": sum(len(g['pieces']) for g in out),
             "complete_quadruples": sum(1 for g in out if g['complete_quadruple']),
             "frozen_ids_with_entrance": len(frozen_ids)}
    print("统计:", json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
