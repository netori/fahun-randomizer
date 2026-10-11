# build_guide_basis.py — 用局内《职业说明书》建"权威候选基础"
# 说明书 = GoodsCaption.fmg 8800-8895（26 职业）：
#   8800-8806 近战职业护甲偏好（重甲/轻甲和中甲）  8807-8825 法术职业→卢恩+少量防具  8870-8895 全职业→武器
# 判定：说明书提到的物品 = 职业专属（权威）；职业倾向来自 初始套装表效果文本 / 同义名 / 用户指定（囚犯=近战）
# 输出：guide_candidate_draft.csv + evidence/guide_candidate_basis.json
import collections, csv, json, os, re
import xml.etree.ElementTree as ET

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
CATCODE = {"protector": "3", "weapon": "2", "goods": "1"}
SYN = {"冰霜巫师": "冰霜女巫", "古龙祀者": "龙信徒", "左道异端": "悖逆异端", "神皮庆典者": "神皮庆典司仪",
       "野兽宗徒": "野兽虔敬者", "鲜血新锐": "鲜血入道者", "风暴呼召者": "烈风召唤者"}
CASTER = ("法师", "祷告", "法师/祷告混合", "祷告/感应")


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def parse_mentions(s):
    return [{"name": m.group(1).strip(), "id": m.group(2)} for m in re.finditer(r"([^;()]+?)\s*\((\d+)\)", s or "")]


def class_of(first_line):
    m = re.match(r"^\s*([^\s，,]+?)(?:主要|偏好|喜欢)", first_line or "")
    return m.group(1) if m else (first_line or "").split(" ")[0][:8]


def main():
    basis_x = json.load(open(os.path.join(DRY, "evidence", "class_candidate_basis.json"), encoding="utf-8"))
    arch_of = dict(basis_x["archetype_by_class"])                      # 已含同义名与囚犯=近战
    rows = list(csv.DictReader(open(os.path.join(CAT, "guide_entries.csv"), encoding="utf-8-sig")))

    # 职业 → 物品
    per = collections.defaultdict(lambda: {"weapon": [], "goods": [], "protector": [], "style": ""})
    for r in rows:
        cls = class_of(r["first_line"])
        if "喜欢" in r["first_line"] or "偏好" in r["first_line"]:
            per[cls]["style"] = r["first_line"].strip()
        for col, cat in (("mentioned_weapon", "weapon"), ("mentioned_goods", "goods"), ("mentioned_protector", "protector")):
            for it in parse_mentions(r[col]):
                if it["id"] not in [x["id"] for x in per[cls][cat]]:
                    per[cls][cat].append(it)

    # 入口
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    lot = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot[(str(s["category"]), str(s["item_id"]))].append({"source_table": L["table"], "row_id": str(L["lot_id"]),
                                                                 "slot": str(s["slot"]), "category": str(s["category"]),
                                                                 "row_name": L.get("row_name", "")})
    shop = collections.defaultdict(list)
    for s in idx["shops"]:
        if str(s.get("value")) not in ("0", "1", "") and str(s.get("sellQuantity")) not in ("-1", ""):
            shop[(str(s["equipType"]), str(s["equipId"]))].append({"source_table": "ShopLineupParam", "row_id": str(s["shop_row_id"]),
                                                                   "slot": "", "category": str(s["equipType"]),
                                                                   "row_name": f"shop row {s['shop_row_id']}"})
    prot = fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))
    wcat = {}
    for r in ET.parse(os.path.join(WB, "evidence", "work2", "regulation-bin", "EquipParamWeapon.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        wcat[a["id"]] = a.get("weaponCategory", "")

    out, stat = [], collections.Counter()
    for cls, d in per.items():
        ncls = SYN.get(cls, cls)
        arch = arch_of.get(ncls, arch_of.get(cls, "未判定"))
        for cat in ("weapon", "goods", "protector"):
            for it in d[cat]:
                code = CATCODE[cat]
                cells = lot.get((code, it["id"]), []) + shop.get((code, it["id"]), [])
                if cat == "protector":
                    part = next((k for k, f in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip"))
                                 if False), "")
                    sub = "armor:?@" + arch
                    for k in ("head", "body", "arm", "leg"):
                        sub = f"armor:{k}@{arch}"      # 部位由 id 尾号决定，下面统一修正
                    tail = it["id"][-4:]
                    part = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}.get(tail, "")
                    sub = f"armor:{part}@{arch}" if part else f"armor:?@{arch}"
                elif cat == "weapon":
                    sub = f"weapon:cat{wcat.get(it['id'],'?')}@{arch}"
                else:
                    sub = f"rune:?@{arch}"
                stat[f"{cat}:{'有入口' if cells else '无入口'}"] += 1
                out.append({"class_name": ncls, "guide_class": cls, "archetype": arch, "category": cat,
                            "guide_name": it["name"], "matched_id": it["id"], "subpool_proposal": sub,
                            "lot_entrances": len(lot.get((code, it["id"]), [])), "shop_rows": len(shop.get((code, it["id"]), [])),
                            "has_entrance": "yes" if cells else "", "armor_style": d["style"],
                            "fmg_name": prot.get(it["id"], "") if cat == "protector" else "",
                            "cells": cells})
    with open(os.path.join(DRY, "guide_candidate_draft.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class_name", "guide_class", "archetype", "category", "guide_name", "matched_id",
                                          "subpool_proposal", "lot_entrances", "shop_rows", "has_entrance", "armor_style", "fmg_name"])
        w.writeheader()
        for r in out:
            w.writerow({k: r[k] for k in w.fieldnames})
    uniq = {(r["category"], r["matched_id"]) for r in out if r["has_entrance"] == "yes"}
    json.dump({"professions": len(per), "entries": len(out), "unique_with_entrance": len(uniq),
               "stats": dict(stat),
               "armor_styles": {k: v["style"] for k, v in per.items() if v["style"]},
               "by_category": {c: len([1 for r in out if r["has_entrance"] == "yes" and r["category"] == c]) for c in ("weapon", "goods", "protector")},
               "draft": [{k: v for k, v in r.items() if k != "cells"} for r in out]},
              open(os.path.join(DRY, "evidence", "guide_candidate_basis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("=== 说明书权威基础 ===")
    print(f"  职业 {len(per)} | 条目 {len(out)} | 有入口去重 {len(uniq)} 件")
    for k, v in sorted(stat.items()):
        print(f"   {k}: {v}")
    print("  各职业护甲偏好:", {k: v for k, v in list({r['guide_class']: r['armor_style'] for r in out if r['armor_style']}.items())[:8]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
