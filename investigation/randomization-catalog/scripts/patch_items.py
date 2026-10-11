# patch_items.py — 用 bundles.json / guide_entries.json 补齐 items.csv 的「职业归属证据」与「建议池」
# 只改本目录 items.csv（本会话自建产物），不动其它文件；CSV 重写为 UTF-8 BOM
import csv, json, os, collections, sys

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")
EXPR = lambda rel: "investigation/randomization-catalog/" + rel.replace("\\", "/")


def main():
    items = list(csv.DictReader(open(os.path.join(CAT, "items.csv"), encoding="utf-8-sig")))
    fields = list(items[0].keys())
    bundles = json.load(open(os.path.join(CAT, "bundles.json"), encoding="utf-8"))["bundles"]
    guides = json.load(open(os.path.join(EV, "guide_entries.json"), encoding="utf-8"))["entries"]
    runes = {r["goods_id"]: r for r in json.load(open(os.path.join(EV, "goods_runes.json"), encoding="utf-8"))["runes"]}

    attr_prot = {}          # defender id -> 职业归属证据字符串
    for b in bundles:
        for m in b["members"]:
            if m.get("piece_id"):
                attr_prot[int(m["piece_id"])] = (
                    f"职业={b['class_name']}（xlsx {b['class_cells']} 初始套装；职业说明 entry {b['class_guide_entry']}，"
                    f"属性={b['class_attrs']}）；同名套装行名证据见 bundles.json")
    attr_goods = {}
    for g in guides:
        if not g["fmg_file"].startswith("GoodsCaption"):
            continue
        first = g["text_plain"].strip().splitlines()[0] if g["text_plain"].strip() else ""
        klass = first.split("主要使用")[0] if "主要使用" in first else ""
        for x in g["mentions_protector_names"]:
            attr_prot.setdefault(int(x["id"]), f"职业说明 entry {g['entry_id']}（{klass}）点名该装备")
        for x in g["mentions_goods_names"]:
            attr_goods.setdefault(int(x["id"]), f"职业说明 entry {g['entry_id']}（{klass}）点名该卢恩")

    n_prot = n_goods = 0
    for it in items:
        iid = it["item_id"]
        if not str(iid).isdigit():
            continue
        i = int(iid)
        if it["category"] == "protector" and i in attr_prot:
            it["class_attribution_evidence"] = attr_prot[i]
            it["suggested_pool"] = "poolA_member(职业套装)" if "初始套装" in attr_prot[i] else "poolB_candidate(职业说明书散件)"
            n_prot += 1
        elif it["category"] == "goods" and i in attr_goods:
            it["class_attribution_evidence"] = attr_goods[i]
            n_goods += 1


    # --- 补齐 items.csv 中缺失的 Bundle 成员 / 说明书点名件（来源=职业初始套装表 + FMG + 参数行） ---
    import xml.etree.ElementTree as ET
    WB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence")
    prot_rows = {}
    root = ET.parse(os.path.join(WB, "work2", "regulation-bin", "EquipParamProtector.param.xml")).getroot()
    for r in root.find("rows").findall("row"):
        a = dict(r.attrib)
        part = next((k for k, f in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(f) == "1"), "")
        prot_rows[int(a["id"])] = {"name": a.get("name") or a.get("paramdexName") or "", "part": part,
                                  "sortId": a.get("sortId"), "icon": a.get("iconIdM")}
    prot_zh = {}
    for f in ("ProtectorName.fmg.xml", "ProtectorName_dlc01.fmg.xml"):
        fp = os.path.join(EV, "xml", f)
        if os.path.exists(fp):
            for e in ET.parse(fp).getroot().findall(".//text"):
                if e.text:
                    prot_zh[e.get("id")] = e.text
    have = {it["item_id"] for it in items}
    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    lots = collections.defaultdict(list)
    for L in idx["lots"]:
        for sl in L["slots"]:
            if sl["category"] == 3:
                lots[sl["item_id"]].append(L["lot_id"])
    added = 0
    for i, a in attr_prot.items():
        if str(i) in have:
            continue
        pr = prot_rows.get(i, {})
        items.append({"item_id": i, "category": "protector", "name_cn": prot_zh.get(str(i), ""),
                      "name_en_rowname": pr.get("name", ""), "part": pr.get("part", ""),
                      "xlsx_lead_sheet": "职业初始套装位置表", "xlsx_lead_cells": "",
                      "xlsx_lead_effect": "", "xlsx_lead_location": "",
                      "class_attribution_evidence": a,
                      "rune_school": "", "rune_tier": "", "role": "",
                      "suggested_pool": "poolA_member(职业套装)" if "初始套装" in a else "poolB_candidate(职业说明书散件)",
                      "status": "identity+part 已确认（职业初始套装表 + zhocn FMG + EquipParamProtector 部位）；奖励槽=" + ("有" if lots.get(i) else "未找到"),
                      "n_reward_entrances": len(lots.get(i, [])),
                      "evidence_path": EXPR("evidence/armor_id_candidates.json") + "; bundles.json"})
        added += 1
    print("补入 items.csv 的防具行:", added)

    with open(os.path.join(CAT, "items.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for it in items:
            w.writerow({k: it.get(k, "") for k in fields})
    print("补齐职业归属证据：防具", n_prot, "件；卢恩", n_goods, "条；总行", len(items))
    print("按建议池:", dict(collections.Counter(i["suggested_pool"] for i in items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
