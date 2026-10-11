# build_catalog2.py — 第二版：更稳的套装成员匹配 + 职业说明→物品/卢恩 关联
# 匹配方法（每条都记录 match_method，供人工复核）：
#   exact_name             : xlsx 件名 与 zhocn ProtectorName 完全同名
#   class_prefix+suffix    : 同职业前缀 + 部位后缀（帽/兜帽/风帽/袍/手套/腕套/靴子/绑腿…）且
#                            与 EquipParamProtector 的真实部位标志(headEquip/…)一致 → 双信号一致
# 输出覆盖 items.csv / reward_slots.csv / bundles.json / guide_entries.csv
import csv, json, os, re, collections, sys
import xml.etree.ElementTree as ET
import openpyxl

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence")
WS = os.path.dirname(os.path.dirname(CAT))
XLSX = os.path.join(WS, "法魂资料整合表.xlsx")
FIRST_SHEET, CAT_SHEET = "Sheet3 (2)", "职业初始套装位置表"
EXPR = lambda rel: "investigation/randomization-catalog/" + rel.replace("\\", "/")

HEAD_KW = ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽", "额冠", "冠"]
BODY_KW = ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "甲"]
ARM_KW = ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕"]
LEG_KW = ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "短裤", "裤", "靴", "腿"]
PART_KW = {"head": HEAD_KW, "body": BODY_KW, "arm": ARM_KW, "leg": LEG_KW}


def fmg_names(*paths):
    d = {}
    for p in paths:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
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
    _, prows = load_param("EquipParamProtector")
    prot = {r.get("id"): dict(r.attrib) for r in prows}
    prot_parts = {i: part_of(a) for i, a in prot.items()}

    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    lots = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lots[s["item_id"]].append({"source_table": L["table"], "row_id": L["lot_id"], "slot": s["slot"],
                                       "category": s["category"], "num": s["num"], "base_point": s["base_point"],
                                       "cumulate_lot_point": s["cumulate_lot_point"], "slot_get_flag": s.get("get_item_flag_id"),
                                       "row_get_flag": L["getItemFlagId"], "row_name": L["row_name"], "gameclear": L["GameClearOffset"]})
    shops = collections.defaultdict(list)
    for s in idx["shops"]:
        shops[s["equipId"]].append(s)

    leads = json.load(open(os.path.join(EV, "armor_id_candidates.json"), encoding="utf-8"))
    runes = json.load(open(os.path.join(EV, "goods_runes.json"), encoding="utf-8"))["runes"]
    guides = json.load(open(os.path.join(EV, "guide_entries.json"), encoding="utf-8"))["entries"]

    # 职业说明（GoodsCaption 8807+）
    class_info = {}
    for g in guides:
        if not g["fmg_file"].startswith("GoodsCaption"):
            continue
        first = g["text_plain"].strip().splitlines()[0] if g["text_plain"].strip() else ""
        m = re.match(r"^(.+?)主要使用(.+?)，造成(.+?)伤害", first)
        if m:
            a = m.group(2)
            class_info[m.group(1)] = {"guide_entry_id": g["entry_id"], "attrs": a, "damage": m.group(3),
                                      "caster": any(k in a for k in ("智力", "信仰", "感应")),
                                      "text_raw": g["text_raw"],
                                      "goods": g["mentions_goods_names"], "prot": g["mentions_protector_names"],
                                      "weapon": g["mentions_weapon_names"]}
    print("职业说明条目:", len(class_info))

    # 读职业初始套装表
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[CAT_SHEET]
    groups, cur = [], None
    for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
        v = ["" if c is None else str(c).strip() for c in row]
        if ri == 1 or not any(v):
            continue
        if v[0]:
            cur = {"class_name": v[0], "class_cell": f"'{CAT_SHEET}'!A{ri}", "pieces": []}
            groups.append(cur)
        if cur is None:
            continue
        if v[1]:
            cur["pieces"].append({"name": v[1], "effect": v[2], "location": v[3], "cells": f"'{CAT_SHEET}'!B{ri}:D{ri}"})

    def match_piece(class_name, piece_name):
        """返回 (id, method, part) 或 None；只用可复核的信号"""
        if piece_name in zh2id:
            for i in zh2id[piece_name]:
                return i, "exact_name", prot_parts.get(i, "")
        if not piece_name.startswith(class_name):
            return None
        suffix = piece_name[len(class_name):]
        kw_part = None
        for p, kws in PART_KW.items():
            if any(suffix.startswith(k) or k in suffix for k in kws):
                kw_part = p
                break
        if not kw_part:
            return None
        cands = [i for n, ids in zh2id.items() if n.startswith(class_name) for i in ids]
        for i in sorted(cands):
            if prot_parts.get(i) == kw_part:
                return i, "class_prefix+suffix", kw_part
        return None

    print("职业组:", len(groups), "件数:", sum(len(g['pieces']) for g in groups))

    bundle_list = []
    slot_owner = collections.defaultdict(list)
    for g in groups:
        ci = class_info.get(g["class_name"], {})
        if not ci.get("caster"):
            continue
        members = {}
        for p in g["pieces"]:
            mm = match_piece(g["class_name"], p["name"])
            if not mm:
                p["match"] = None
                continue
            i, method, part = mm
            p["match"] = {"id": i, "method": method, "part": part or prot_parts.get(i, ""),
                          "lots": lots.get(int(i), []), "shops": shops.get(int(i), [])}
            members.setdefault(p["match"]["part"], []).append(p)
        order = ("head", "body", "arm", "leg")
        ms = []
        for k in order:
            if k in members:
                p = members[k][0]
                e = p["match"]["lots"][0] if p["match"]["lots"] else None
                ms.append({"part": k, "sheet_piece_name": p["name"], "fmg_piece_name": prot_zh.get(p["match"]["id"], ""),
                           "piece_id": p["match"]["id"], "match_method": p["match"]["method"],
                           "effect": p["effect"], "xlsx_location": p["location"], "xlsx_cells": p["cells"],
                           "entrance": e, "all_lot_entrances": p["match"]["lots"], "shop_entrances": p["match"]["shops"]})
            else:
                ms.append({"part": k, "sheet_piece_name": [x for x in g["pieces"] if False] or "", "piece_id": "",
                           "match_method": "unmatched", "entrance": None})
        b = {"class_name": g["class_name"], "class_cells": g["class_cell"], "class_guide_entry": ci.get("guide_entry_id"),
             "class_attrs": ci.get("attrs"), "class_damage": ci.get("damage"),
             "four_parts_present": all(m["piece_id"] for m in ms),
             "n_members_with_entrance": sum(1 for m in ms if m["entrance"]), "members": ms}
        bundle_list.append(b)
        for m in ms:
            if m["entrance"]:
                slot_owner[(m["entrance"]["source_table"], m["entrance"]["row_id"], m["entrance"]["slot"])].append(g["class_name"])
    for b in bundle_list:
        conf = []
        for m in b["members"]:
            e = m["entrance"]
            if e:
                key = (e["source_table"], e["row_id"], e["slot"])
                if len(slot_owner[key]) > 1:
                    conf.append({"part": m["part"], "slot": f"{key[0]}:{key[1]}:s{key[2]}",
                                 "shared_with": [x for x in slot_owner[key] if x != b["class_name"]]})
        b["slot_conflicts"] = conf
        b["approvable"] = bool(b["four_parts_present"] and b["n_members_with_entrance"] == 4 and not conf)
    print("Pool A 候选(施法职业):", len(bundle_list), "| 四件齐且四槽齐且无冲突:", sum(1 for b in bundle_list if b["approvable"]))
    for b in bundle_list:
        print(f"   {b['class_name']:<8} 四件={b['four_parts_present']} 槽={b['n_members_with_entrance']}/4 冲突={len(b['slot_conflicts'])} approvable={b['approvable']}")
    json.dump({"note": "来源=xlsx『职业初始套装位置表』+zhocn ProtectorName FMG+EquipParamProtector 部位+奖励槽索引；"
                       "match_method 记录每件的匹配依据；approvable 仅代表结构可批准(仍需人工确认)",
               "bundles": bundle_list}, open(os.path.join(CAT, "bundles.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- items.csv ----
    guide_class_of_piece = {}
    for cn, ci in class_info.items():
        for x in ci["prot"]:
            guide_class_of_piece[int(x["id"])] = cn
    items = []
    for m in leads["matched"]:
        rid = int(m["protector_id"])
        ent = lots.get(rid, [])
        gc = guide_class_of_piece.get(rid, "")
        items.append({"item_id": rid, "category": "protector", "name_cn": m["fmg_zhocn_name"],
                      "name_en_rowname": m["row_name"], "part": m["part"],
                      "xlsx_lead_sheet": FIRST_SHEET, "xlsx_lead_cells": f"'{FIRST_SHEET}'!A{m['xlsx_row']}:C{m['xlsx_row']}",
                      "xlsx_lead_effect": m["xlsx_text"], "xlsx_lead_location": m["xlsx_location"],
                      "class_attribution_evidence": (f"职业说明 entry {class_info[gc]['guide_entry_id']}（{gc}）提到该装备" if gc else ""),
                      "rune_school": "", "rune_tier": "", "role": "",
                      "suggested_pool": ("poolB_candidate(职业说明书散件)" if gc else "poolB_candidate") if m["part"] else "",
                      "status": ("identity+part 已确认；奖励槽=" + ("有" if ent else "未找到")) + ("；职业归属有说明书证据" if gc else ""),
                      "n_reward_entrances": len(ent), "evidence_path": EXPR("evidence/armor_id_candidates.json")})
    # 卢恩
    rune_class = {}
    for cn, ci in class_info.items():
        for x in ci["goods"]:
            rune_class[int(x["id"])] = cn
    for r in runes:
        nm = r["name_zh"]
        mm = re.match(r"^(微光|闪光|明亮|闪耀|辉光|幽影)(.+?)卢恩$", nm)
        if any(k in nm for k in ("黄金卢恩", "稀人卢恩", "英雄卢恩", "王之卢恩", "卢恩弯弧", "交界地卢恩", "卢恩魔砾")):
            pool, role, tier, school = "out_of_scope", "普通经验卢恩", "", ""
        elif "碎片" in nm:
            pool, role, tier, school = "excluded", "卢恩碎片(中间物，按约束排除)", "", "岩浆"
        elif mm:
            pool, role = "poolB_candidate", "完整职业法术卢恩"
            tier = {"微光": "新手级", "闪光": "学徒级", "明亮": "熟练级", "闪耀": "精通级", "辉光": "大师级", "幽影": "大师级(幽影系列)"}[mm.group(1)]
            school = mm.group(2)
        else:
            pool, role, tier, school = "", "", "", ""
        cls = rune_class.get(r["goods_id"], "")
        items.append({"item_id": r["goods_id"], "category": "goods", "name_cn": nm, "name_en_rowname": "",
                      "part": "", "xlsx_lead_sheet": "（说明文字来自 MOD 内 FMG，非 xlsx）", "xlsx_lead_cells": "",
                      "xlsx_lead_effect": (r["caption"] or "")[:150], "xlsx_lead_location": "",
                      "class_attribution_evidence": (f"职业说明 entry {class_info[cls]['guide_entry_id']}（{cls}）列出该卢恩" if cls else ""),
                      "rune_school": school, "rune_tier": tier, "role": role, "suggested_pool": pool,
                      "status": ("identity 已确认(GoodsName+EquipParamGoods)；奖励槽=" + ("有" if r["lot_entrances"] else "未找到")),
                      "n_reward_entrances": len(r["lot_entrances"]), "evidence_path": EXPR("evidence/goods_runes.json")})
    for wid, wn, wen in (("5100000", "女猎手的刺剑", "Huntress's Estoc"), ("18530000", "欺诈者的大戟", "Halberd of the Deceiver")):
        items.append({"item_id": wid, "category": "weapon", "name_cn": wn, "name_en_rowname": wen, "part": "",
                      "xlsx_lead_sheet": "", "xlsx_lead_cells": "", "xlsx_lead_effect": "", "xlsx_lead_location": "",
                      "class_attribution_evidence": "", "rune_school": "", "rune_tier": "", "role": "",
                      "suggested_pool": "pending_approval", "status": "上一轮已证实；按本次约束不自动入池",
                      "n_reward_entrances": 1, "evidence_path": "investigation/weapon-baseline/REPORT.md"})

    def w(path, cols, rows):
        with open(os.path.join(CAT, path), "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=cols)
            wr.writeheader()
            for r in rows:
                wr.writerow({k: r.get(k, "") for k in cols})
        print("写出", path, len(rows), "行")

    w("items.csv", ["item_id", "category", "name_cn", "name_en_rowname", "part", "xlsx_lead_sheet", "xlsx_lead_cells",
                    "xlsx_lead_effect", "xlsx_lead_location", "class_attribution_evidence", "rune_school", "rune_tier",
                    "role", "suggested_pool", "status", "n_reward_entrances", "evidence_path"], items)

    rs = []
    for it in items:
        if not str(it["item_id"]).isdigit():
            continue
        iid, cat = int(it["item_id"]), it["category"]
        for e in lots.get(iid, []):
            if cat == "protector" and e["category"] != 3:
                continue
            if cat == "goods" and e["category"] != 1:
                continue
            rs.append({"item_id": iid, "category": cat, "item_name_cn": it["name_cn"], "source_table": e["source_table"],
                       "row_id": e["row_id"], "slot": e["slot"], "slot_item_category": e["category"], "quantity": e["num"],
                       "base_point": e["base_point"], "cumulate_lot_point": e["cumulate_lot_point"],
                       "slot_get_flag": e["slot_get_flag"], "row_get_flag": e["row_get_flag"], "row_name": e["row_name"],
                       "gameclear_offset": e["gameclear"], "shop_price": "", "shop_stock": "", "shop_stock_flag": "",
                       "shop_release_flag": "", "identity_confidence": "high", "reward_slot_confidence": "high",
                       "world_position_confidence": "lot_row_name_hint_only", "single_acquisition_confidence": "unverified",
                       "evidence_path": EXPR("evidence/lot_reward_index.json")})
        for s in shops.get(iid, []):
            rs.append({"item_id": iid, "category": cat, "item_name_cn": it["name_cn"], "source_table": "ShopLineupParam",
                       "row_id": s["shop_row_id"], "slot": "", "slot_item_category": "", "quantity": s.get("setNum"),
                       "base_point": "", "cumulate_lot_point": "", "slot_get_flag": "", "row_get_flag": "",
                       "row_name": s.get("row_name", ""), "gameclear_offset": "", "shop_price": s.get("value"),
                       "shop_stock": s.get("sellQuantity"), "shop_stock_flag": s.get("eventFlag_forStock"),
                       "shop_release_flag": s.get("eventFlag_forRelease"), "identity_confidence": "high",
                       "reward_slot_confidence": "high", "world_position_confidence": "shop_row_only",
                       "single_acquisition_confidence": "unverified", "evidence_path": EXPR("evidence/lot_reward_index.json")})
    w("reward_slots.csv", ["item_id", "category", "item_name_cn", "source_table", "row_id", "slot", "slot_item_category",
                           "quantity", "base_point", "cumulate_lot_point", "slot_get_flag", "row_get_flag", "row_name",
                           "gameclear_offset", "shop_price", "shop_stock", "shop_stock_flag", "shop_release_flag",
                           "identity_confidence", "reward_slot_confidence", "world_position_confidence",
                           "single_acquisition_confidence", "evidence_path"], rs)

    ge = []
    for g in guides:
        first = g["text_plain"].strip().splitlines()[0][:80] if g["text_plain"].strip() else ""
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
