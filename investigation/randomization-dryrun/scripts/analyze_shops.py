# analyze_shops.py — 只读：清点商店（ShopLineupParam）里到底卖了什么，评估商店路径的价值
# 输入（只读）：investigation/randomization-catalog/evidence/lot_reward_index.json（含全部 1554 条商店行）
#               evidence/xml/ProtectorName*.fmg.xml、weapon-baseline/evidence/xml/WeaponName*.fmg.xml、GoodsName*.fmg.xml
#               weapon-baseline/evidence/work2/regulation-bin/EquipParamWeapon.param.xml（取 weaponCategory）
#               randomization-catalog-review/evidence/starter_set_freeze.json（判断是否属于被冻结的初始套装）
# 输出：investigation/randomization-dryrun/evidence/shop_analysis.json + 屏幕摘要
import csv, json, os, collections
import xml.etree.ElementTree as ET

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
RB = os.path.join(WB, "evidence", "work2", "regulation-bin")
EQUIPTYPE = {"0": "weapon", "1": "protector", "2": "accessory", "3": "goods", "4": "gem", "5": "customWeapon"}


def fmg_names(*paths):
    d = {}
    for p in paths:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def main():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    prot_zh = fmg_names(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                        os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))
    wep_zh = fmg_names(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                       os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))
    goods_zh = fmg_names(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                         os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))
    part = {}
    for r in ET.parse(os.path.join(RB, "EquipParamProtector.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        part[a["id"]] = next((k for k, fl in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(fl) == "1"), "")
    wcat = {}
    for r in ET.parse(os.path.join(RB, "EquipParamWeapon.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        wcat[a["id"]] = a.get("weaponCategory", "")
    starter = {str(p["id"]): g["class_name"] for g in json.load(open(os.path.join(REV, "evidence", "starter_set_freeze.json"), encoding="utf-8"))["groups"] for p in g["pieces"]}
    overlay = {x["item_id"]: x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig")) if x["row_kind"] == "item"}

    shops = idx["shops"]
    by_type = collections.Counter(EQUIPTYPE.get(s["equipType"], s["equipType"]) for s in shops)
    clean, susp = [], []
    rows = []
    for s in shops:
        et = EQUIPTYPE.get(s["equipType"], s["equipType"])
        iid = str(s["equipId"])
        name = {"weapon": wep_zh, "protector": prot_zh, "goods": goods_zh}.get(et, {}).get(iid, "")
        ok_price = s.get("value") not in ("0", "1", "")
        ok_stock = s.get("sellQuantity") not in ("-1", "")
        quality = "clean" if (ok_price and ok_stock) else "unverified"
        (clean if quality == "clean" else susp).append(s)
        rows.append({"shop_row_id": s["shop_row_id"], "equipId": iid, "equipType": s["equipType"], "equip_type_name": et,
                     "name_cn": name, "price": s.get("value"), "stock": s.get("sellQuantity"),
                     "stock_flag": s.get("eventFlag_forStock"), "release_flag": s.get("eventFlag_forRelease"),
                     "mtrlId": s.get("mtrlId"), "quality": quality,
                     "part": part.get(iid, "") if et == "protector" else "",
                     "weaponCategory": wcat.get(iid, "") if et == "weapon" else "",
                     "is_starter_set_piece": iid in starter, "starter_class": starter.get(iid, ""),
                     "in_catalog_final_decision": (overlay.get(iid, {}) or {}).get("final_decision", "")})

    # 专属度：同一 equipId 只在这条商店行出现
    cnt = collections.Counter(r["equipId"] for r in rows)
    for r in rows:
        r["shop_rows_for_same_item"] = cnt[r["equipId"]]

    print("=== 商店行总览 ===")
    print("  总行数:", len(shops), "|", dict(by_type))
    print("  形态：正常售价+有限库存 =", len(clean), " / 语义未确认 =", len(susp))
    for et in ("weapon", "protector", "goods", "accessory", "gem"):
        sub = [r for r in rows if r["equip_type_name"] == et]
        if not sub:
            continue
        distinct = len(set(r["equipId"] for r in sub))
        names = [(r["equipId"], f"{r['name_cn']}({r['part'] or r['weaponCategory']})", r["price"], r["stock"], r["quality"]) for r in sub[:8]]
        print(f"\n  [{et}] 行数 {len(sub)} / 不同物品 {distinct}")
        for n in names:
            print("     ", n)
    frozen_sold = [r for r in rows if r["is_starter_set_piece"]]
    print(f"\n  商店里卖'初始套装件'的行: {len(frozen_sold)}（这些按 D5 不得作为目标/来源）", [(r['equipId'], r['name_cn'], r['starter_class']) for r in frozen_sold[:6]])
    weapons_sold = [r for r in rows if r["equip_type_name"] == "weapon"]
    print(f"  商店里卖'武器'的行: {len(weapons_sold)}，不同武器 {len(set(r['equipId'] for r in weapons_sold))}")
    print(f"     例: {[(r['equipId'], r['name_cn'], 'cat=' + r['weaponCategory'], r['price'], r['stock']) for r in weapons_sold[:8]]}")
    excl = [r for r in rows if r["shop_rows_for_same_item"] == 1 and r["equip_type_name"] in ("weapon", "protector")]
    print(f"  只在这一家商店出现（较可能'专属'）: {len(excl)} 行", [(r['equipId'], r['name_cn'][:10]) for r in excl[:6]])

    os.makedirs(os.path.join(DRY, "evidence"), exist_ok=True)
    json.dump({"summary": {"rows": len(shops), "by_equip_type": dict(by_type), "clean": len(clean), "unverified": len(susp),
                           "weapon_rows": len(weapons_sold), "starter_set_rows": len(frozen_sold)},
               "rows": rows},
              open(os.path.join(DRY, "evidence", "shop_analysis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写出 evidence/shop_analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
