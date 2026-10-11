# build_catalog.py — 汇总生成 items.csv / reward_slots.csv / bundles.json / guide_entries.csv
# 输入（全部只读）：法魂资料整合表.xlsx（第1个工作表 + 职业初始套装位置表）、上一轮解包 XML、
#                   本目录 evidence/*.json
# 输出（本目录）：items.csv、reward_slots.csv、bundles.json、guide_entries.csv（CSV 均 UTF-8 BOM）
import csv, json, os, re, collections, sys
import xml.etree.ElementTree as ET
import openpyxl

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence")
WS = os.path.dirname(os.path.dirname(CAT))                     # ...\随机mod
XLSX = os.path.join(WS, "法魂资料整合表.xlsx")
MOD = r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"
EXPR = lambda rel: "investigation/randomization-catalog/" + rel.replace("\\", "/")
CAT_SHEET = "职业初始套装位置表"
FIRST_SHEET = "Sheet3 (2)"


def fmg_names(*paths):
    d = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        root = ET.parse(p).getroot()
        for e in root.findall(".//text"):
            if e.text:
                d[e.get("id")] = e.text
    return d


def load_param(fn):
    root = ET.parse(os.path.join(WB, "work2", "regulation-bin", fn + ".param.xml")).getroot()
    fd = {f.get("name"): f.get("defaultValue") for f in root.find("fields").findall("field")}
    return fd, root.find("rows").findall("row")


def part_of(a):
    for ki, k in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")):
        if a.get(k) == "1":
            return ki
    return ""


def main():
    prot_zh = fmg_names(os.path.join(EV, "xml", "ProtectorName.fmg.xml"), os.path.join(EV, "xml", "ProtectorName_dlc01.fmg.xml"))
    zh2id = collections.defaultdict(list)
    for i, n in prot_zh.items():
        zh2id[n].append(i)

    pfd, prows = load_param("EquipParamProtector")
    prot = {r.get("id"): dict(r.attrib) for r in prows}

    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    lots = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lots[s["item_id"]].append({"source_table": L["table"], "row_id": L["lot_id"], "slot": s["slot"],
                                       "category": s["category"], "num": s["num"], "base_point": s["base_point"],
                                       "cumulate_lot_point": s["cumulate_lot_point"], "slot_get_flag": s["get_item_flag_id"],
                                       "row_get_flag": L["getItemFlagId"], "row_name": L["row_name"],
                                       "gameclear": L["GameClearOffset"]})
    shops = collections.defaultdict(list)
    for s in idx["shops"]:
        shops[s["equipId"]].append(s)

    armor_leads = json.load(open(os.path.join(EV, "armor_id_candidates.json"), encoding="utf-8"))
    sets = json.load(open(os.path.join(EV, "set_candidates.json"), encoding="utf-8"))
    runes = json.load(open(os.path.join(EV, "goods_runes.json"), encoding="utf-8"))["runes"]
    guides = json.load(open(os.path.join(EV, "guide_entries.json"), encoding="utf-8"))["entries"]

    # ---- 职业说明条目：职业名 → 是否施法（用"主要使用智力/信仰"字样） ----
    class_info = {}
    for g in guides:
        if not g["fmg_file"].startswith("GoodsCaption"):
            continue
        first = g["text_plain"].strip().splitlines()[0] if g["text_plain"].strip() else ""
        m = re.match(r"^(.+?)主要使用(.+?)，造成(.+?)伤害", first)
        if m:
            klass, attrs, dmg = m.group(1), m.group(2), m.group(3)
            class_info[klass] = {"guide_entry_id": g["entry_id"], "guide_file": g["fmg_file"],
                                 "attrs": attrs, "damage": dmg,
                                 "caster": ("智力" in attrs or "信仰" in attrs or "感应" in attrs),
                                 "text_raw": g["text_raw"],
                                 "mentioned_goods": g["mentions_goods_names"], "mentioned_prot": g["mentions_protector_names"],
                                 "mentioned_weapon": g["mentions_weapon_names"]}
    print("职业说明条目解析出职业数:", len(class_info))

    # ---- 职业初始套装表（含单元格坐标） ----
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[CAT_SHEET]
    groups = []
    cur = None
    for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
        vals = ["" if c is None else str(c).strip() for c in row]
        if ri == 1:
            continue
        if not any(vals):
            continue
        if vals[0]:
            cur = {"class_name": vals[0], "class_cell": f"'{CAT_SHEET}'!A{ri}", "pieces": []}
            groups.append(cur)
        if cur is None:
            continue
        piece = {"name": vals[1], "effect": vals[2], "location": vals[3],
                 "cells": f"'{CAT_SHEET}'!B{ri}:D{ri}"}
        if piece["name"]:
            cur["pieces"].append(piece)
    print("职业初始套装组数:", len(groups), "| 总件数:", sum(len(g["pieces"]) for g in groups))

    # ---- 逐件匹配真实 ID/部位 ----
    for g in groups:
        ci = class_info.get(g["class_name"])
        g["class_info"] = ci
        g["class_caster"] = bool(ci and ci["caster"])
        for p in g["pieces"]:
            ids = zh2id.get(p["name"], [])
            cands = []
            for i in ids:
                a = prot.get(i)
                if not a:
                    continue
                cands.append({"id": i, "part": part_of(a), "sortId": a.get("sortId"),
                              "iconIdM": a.get("iconIdM"), "weight": a.get("weight"),
                              "lot_entrances": lots.get(int(i), []), "shop_entrances": shops.get(int(i), [])})
            p["candidates"] = cands
            p["match"] = cands[0] if len(cands) >= 1 else None
            p["ambiguous"] = len(cands) > 1

    # ---- Pool A 候选 Bundle ----
    bundle_list = []
    used_slots = collections.defaultdict(list)
    for g in groups:
        if not g["class_caster"]:
            continue
        parts = {}
        for p in g["pieces"]:
            m = p["match"]
            if m:
                parts.setdefault(m["part"], []).append((p, m))
        complete = all(k in parts for k in ("head", "body", "arm", "leg"))
        slots = []
        for k in ("head", "body", "arm", "leg"):
            if k in parts:
                p, m = parts[k][0]
                ent = m["lot_entrances"][0] if m["lot_entrances"] else None
                slots.append({"part": k, "piece_name_cn": p["name"], "piece_id": m["id"],
                              "effect": p["effect"], "xlsx_location": p["location"], "cells": p["cells"],
                              "entrance": ent, "all_entrances": m["lot_entrances"], "shop_entrances": m["shop_entrances"]})
        bundle_list.append({"class_name": g["class_name"], "class_cells": g["class_cell"],
                            "class_guide_entry": (g["class_info"] or {}).get("guide_entry_id"),
                            "class_attrs": (g["class_info"] or {}).get("attrs"),
                            "class_damage": (g["class_info"] or {}).get("damage"),
                            "four_parts_present": complete, "members": slots,
                            "n_members_with_entrance": sum(1 for s in slots if s["entrance"]),
                            "ambiguous_members": [s["piece_name_cn"] for k in parts for p, m in [(parts[k][0])] for s in slots if s["piece_name_cn"] == p["name"] and m["id"] != s["piece_id"]]})
    # 槽位冲突检测（同一目标槽不得属于两个 Bundle）
    for b in bundle_list:
        for s in b["members"]:
            e = s["entrance"]
            if e:
                used_slots[(e["source_table"], e["row_id"], e["slot"])].append(b["class_name"])
    for b in bundle_list:
        conflicts = []
        for s in b["members"]:
            e = s["entrance"]
            if e and len(used_slots[(e["source_table"], e["row_id"], e["slot"])]) > 1:
                conflicts.append({"part": s["part"], "slot": f"{e['source_table']}:{e['row_id']}:s{e['slot']}",
                                  "shared_with": [x for x in used_slots[(e["source_table"], e["row_id"], e["slot"])] if x != b["class_name"]]})
        b["slot_conflicts"] = conflicts
        b["approvable"] = bool(b["four_parts_present"] and b["n_members_with_entrance"] == 4 and not conflicts)
        for s in b["members"]:
            e = s["entrance"]
            if e:
                used_slots["x"] = used_slots["x"]

    bundles = {"note": "Pool A 候选：来源 = xlsx『职业初始套装位置表』(职业/初始套装/效果/获取位置) "
                       "+ zhocn ProtectorName FMG 名称 + EquipParamProtector 部位 + 奖励槽索引；"
                       "同槽冲突 = 同一 (表,行,slot) 被两个 Bundle 使用；approvable 仅表示结构上可用，仍需人工批准",
               "bundle_count": len(bundle_list), "bundles": bundle_list}
    json.dump(bundles, open(os.path.join(CAT, "bundles.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Pool A 候选 Bundle:", len(bundle_list), "| 可批准(结构上):", sum(1 for b in bundle_list if b["approvable"]))

    # ---- 写 CSV ----
    def w(path, cols, rows):
        with open(os.path.join(CAT, path), "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=cols)
            wr.writeheader()
            for r in rows:
                wr.writerow({k: r.get(k, "") for k in cols})
        print("写出", path, len(rows), "行")

    # items.csv
    lead_by_zh = {}
    for m in armor_leads["matched"]:
        lead_by_zh.setdefault(m["fmg_zhocn_name"], m)
    items = []
    for m in armor_leads["matched"]:
        rid = int(m["protector_id"])
        ent = lots.get(rid, [])
        items.append({
            "item_id": m["protector_id"], "category": "protector", "name_cn": m["fmg_zhocn_name"],
            "name_en_rowname": m["row_name"], "xlsx_lead_sheet": FIRST_SHEET,
            "xlsx_lead_cells": f"'{FIRST_SHEET}'!A{m['xlsx_row']}:C{m['xlsx_row']}",
            "xlsx_lead_effect": m["xlsx_text"], "xlsx_lead_location": m["xlsx_location"],
            "part": m["part"], "class_attribution_evidence": "(见 bundles.json / guide_entries.csv)",
            "rune_school": "", "rune_tier": "", "role": "", "suggested_pool": "poolB_candidate" if m["part"] else "",
            "status": "identity+part confirmed; reward slot:" + ("yes" if ent else "none_found"),
            "n_reward_entrances": len(ent),
            "evidence_path": EXPR("evidence/armor_id_candidates.json") + "; " + EXPR("evidence/lot_reward_index.json")})
    for r in runes:
        nm = r["name_zh"]
        if any(k in nm for k in ("黄金卢恩", "稀人卢恩", "英雄卢恩", "王之卢恩", "卢恩弯弧", "交界地卢恩")):
            pool, role = "out_of_scope", "普通经验卢恩"
        elif "碎片" in nm:
            pool, role = "excluded", "卢恩碎片(中间物)"
        elif re.match(r"^(微光|闪光|明亮|闪耀|辉光|幽影)", nm) and nm.endswith("卢恩"):
            pool, role = "poolB_candidate", "完整职业法术卢恩"
        else:
            pool, role = "", ""
        m = re.match(r"^(微光|闪光|明亮|闪耀|辉光|幽影)(.+?)卢恩", nm)
        tier = {"微光": "新手级", "闪光": "学徒级", "明亮": "熟练级", "闪耀": "精通级", "辉光": "大师级", "幽影": "大师级(幽影)"}.get(m.group(1), "") if m else ""
        school = m.group(2) if m else ""
        items.append({"item_id": r["goods_id"], "category": "goods", "name_cn": nm, "name_en_rowname": "",
                      "xlsx_lead_sheet": "", "xlsx_lead_cells": "", "xlsx_lead_effect": r["caption"][:120], "xlsx_lead_location": "",
                      "part": "", "class_attribution_evidence": "guide_entries/ GoodsCaption",
                      "rune_school": school, "rune_tier": tier, "role": role, "suggested_pool": pool,
                      "status": "identity confirmed (GoodsName+EquipParamGoods); reward slot:" + ("yes" if r["lot_entrances"] else "none_found"),
                      "n_reward_entrances": len(r["lot_entrances"]),
                      "evidence_path": EXPR("evidence/goods_runes.json")})
    for wid, wn, wen, ent in (("5100000", "女猎手的刺剑", "Huntress's Estoc", None),
                              ("18530000", "欺诈者的大戟", "Halberd of the Deceiver", None)):
        items.append({"item_id": wid, "category": "weapon", "name_cn": wn, "name_en_rowname": wen,
                      "xlsx_lead_sheet": "", "xlsx_lead_cells": "", "xlsx_lead_effect": "", "xlsx_lead_location": "",
                      "part": "", "class_attribution_evidence": "", "rune_school": "", "rune_tier": "", "role": "",
                      "suggested_pool": "pending_approval", "status": "上一轮已证实；本轮不自动入池",
                      "n_reward_entrances": "", "evidence_path": "investigation/weapon-baseline/REPORT.md"})
    w("items.csv", ["item_id", "category", "name_cn", "name_en_rowname", "xlsx_lead_sheet", "xlsx_lead_cells",
                    "xlsx_lead_effect", "xlsx_lead_location", "part", "class_attribution_evidence", "rune_school",
                    "rune_tier", "role", "suggested_pool", "status", "n_reward_entrances", "evidence_path"], items)

    # reward_slots.csv
    rs = []
    for it in items:
        iid = it["item_id"]
        if not str(iid).isdigit():
            continue
        cat = it["category"]
        for e in lots.get(int(iid), []):
            if cat == "protector" and e["category"] != 3:
                continue
            if cat == "goods" and e["category"] != 1:
                continue
            rs.append({"item_id": iid, "category": cat, "item_name_cn": it["name_cn"],
                       "source_table": e["source_table"], "row_id": e["row_id"], "slot": e["slot"],
                       "slot_item_category": e["category"], "quantity": e["num"], "base_point": e["base_point"],
                       "cumulate_lot_point": e["cumulate_lot_point"], "slot_get_flag": e["slot_get_flag"],
                       "row_get_flag": e["row_get_flag"], "row_name": e["row_name"], "gameclear_offset": e["gameclear"],
                       "shop_price": "", "shop_stock": "", "shop_stock_flag": "", "shop_release_flag": "",
                       "identity_confidence": "high", "reward_slot_confidence": "high",
                       "world_position_confidence": "lot_row_name_hint_only", "single_acquisition_confidence": "unverified",
                       "evidence_path": EXPR("evidence/lot_reward_index.json")})
        for s in shops.get(int(iid), []):
            rs.append({"item_id": iid, "category": cat, "item_name_cn": it["name_cn"],
                       "source_table": "ShopLineupParam", "row_id": s["shop_row_id"], "slot": "",
                       "slot_item_category": "", "quantity": s.get("setNum"), "base_point": "", "cumulate_lot_point": "",
                       "slot_get_flag": "", "row_get_flag": "", "row_name": s.get("row_name", ""), "gameclear_offset": "",
                       "shop_price": s.get("value"), "shop_stock": s.get("sellQuantity"),
                       "shop_stock_flag": s.get("eventFlag_forStock"), "shop_release_flag": s.get("eventFlag_forRelease"),
                       "identity_confidence": "high", "reward_slot_confidence": "high",
                       "world_position_confidence": "shop_row_only", "single_acquisition_confidence": "unverified",
                       "evidence_path": EXPR("evidence/lot_reward_index.json")})
    w("reward_slots.csv", ["item_id", "category", "item_name_cn", "source_table", "row_id", "slot",
                           "slot_item_category", "quantity", "base_point", "cumulate_lot_point", "slot_get_flag",
                           "row_get_flag", "row_name", "gameclear_offset", "shop_price", "shop_stock",
                           "shop_stock_flag", "shop_release_flag", "identity_confidence", "reward_slot_confidence",
                           "world_position_confidence", "single_acquisition_confidence", "evidence_path"], rs)

    # guide_entries.csv
    ge = []
    for g in guides:
        first = g["text_plain"].strip().splitlines()[0][:60] if g["text_plain"].strip() else ""
        ge.append({"fmg_file": g["fmg_file"], "entry_id": g["entry_id"], "first_line": first,
                   "mentioned_goods": "; ".join(f"{x['name']}({x['id']})" for x in g["mentions_goods_names"]),
                   "mentioned_protector": "; ".join(f"{x['name']}({x['id']})" for x in g["mentions_protector_names"]),
                   "mentioned_weapon": "; ".join(f"{x['name']}({x['id']})" for x in g["mentions_weapon_names"]),
                   "text_raw": g["text_raw"], "evidence_path": EXPR("evidence/guide_entries.json")})
    w("guide_entries.csv", ["fmg_file", "entry_id", "first_line", "mentioned_goods", "mentioned_protector",
                            "mentioned_weapon", "text_raw", "evidence_path"], ge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
