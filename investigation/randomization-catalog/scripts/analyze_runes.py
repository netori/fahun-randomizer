# analyze_runes.py — 从 EquipParamGoods + FMG 识别"职业法术解锁卢恩"
# 只读。输出 evidence/goods_runes.json：全部名称含"卢恩"的道具（含描述、参数行、奖励入口）
import xml.etree.ElementTree as ET
import os, json, collections, sys

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")
RB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "work2", "regulation-bin")


def fmg(*paths):
    d = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        root = ET.parse(p).getroot()
        for e in root.findall(".//text"):
            d[e.get("id")] = e.text or ""
    return d


def load(fn):
    root = ET.parse(os.path.join(RB, fn + ".param.xml")).getroot()
    fd = {f.get("name"): f.get("defaultValue") for f in root.find("fields").findall("field")}
    return fd, root.find("rows").findall("row")


def main():
    names = fmg(os.path.join(EV, "xml", "GoodsName.fmg.xml"), os.path.join(EV, "xml", "GoodsName_dlc01.fmg.xml"))
    caps = fmg(os.path.join(EV, "xml", "GoodsCaption_dlc01.fmg.xml"),
               os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "xml", "GoodsCaption.fmg.xml"))
    infos = fmg(os.path.join(EV, "xml", "GoodsInfo.fmg.xml"), os.path.join(EV, "xml", "GoodsInfo_dlc01.fmg.xml"))
    print("GoodsName 条目:", len(names), "| GoodsCaption:", len(caps), "| GoodsInfo:", len(infos))

    fd, rows = load("EquipParamGoods")
    goods = {r.get("id"): dict(r.attrib) for r in rows}
    print("EquipParamGoods 行:", len(goods), "| 字段数:", len(fd))

    runes = []
    for gid, nm in names.items():
        if "卢恩" not in (nm or ""):
            continue
        a = goods.get(gid)
        ent = idx_lots.get(int(gid), []) if (gid or "").isdigit() else []
        runes.append({
            "goods_id": int(gid), "name_zh": nm,
            "caption": (caps.get(gid) or "")[:600], "info": (infos.get(gid) or "")[:300],
            "in_EquipParamGoods": a is not None,
            "sortId": (a or {}).get("sortId"), "iconId": (a or {}).get("iconId"),
            "goodsType": (a or {}).get("goodsType"), "maxNum": (a or {}).get("maxNum"),
            "isConsume": (a or {}).get("isConsume"), "basicPrice": (a or {}).get("basicPrice"),
            "sellValue": (a or {}).get("sellValue"), "rarity": (a or {}).get("rarity"),
            "lot_entrances": ent})
    print("名称含'卢恩'的道具:", len(runes))
    for r in runes:
        lots = ",".join("%s:%s" % (e["table"][-4:], e["lot_id"]) for e in r["lot_entrances"]) or "-"
        print("   id=%-9d %-28s lots=%s" % (r["goods_id"], r["name_zh"][:28], lots))
    json.dump({"source": "EquipParamGoods + GoodsName/GoodsCaption/GoodsInfo (zhocn, MOD V3.0.3)",
               "note": "role（完整/中间物）需人工按名称与描述判定，未判定者留空",
               "runes": runes}, open(os.path.join(EV, "goods_runes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("写出 evidence/goods_runes.json")
    return 0


# 需要在 main 之前定义：从奖励索引里取 goods 类入口
idx_lots = collections.defaultdict(list)
_p = os.path.join(EV, "lot_reward_index.json")
if os.path.exists(_p):
    _idx = json.load(open(_p, encoding="utf-8"))
    for L in _idx["lots"]:
        for s in L["slots"]:
            idx_lots[s["item_id"]].append({"table": L["table"], "lot_id": L["lot_id"], "slot": s["slot"],
                                           "category": s["category"], "row_name": L["row_name"],
                                           "num": s["num"], "base_point": s["base_point"],
                                           "get_item_flag_id": L["getItemFlagId"], "slot_flag": s["get_item_flag_id"]})
    for s in _idx["shops"]:
        if s.get("equipType") in ("3", 3):
            idx_lots[s["equipId"]].append({"table": "ShopLineupParam", "lot_id": s["shop_row_id"], "slot": "",
                                           "category": 1, "row_name": s.get("row_name", ""),
                                           "num": s.get("setNum"), "base_point": "", "get_item_flag_id": "",
                                           "slot_flag": "", "shop": {k: s[k] for k in ("value", "sellQuantity",
                                                                                       "eventFlag_forStock",
                                                                                       "eventFlag_forRelease",
                                                                                       "mtrlId", "costType")}})

if __name__ == "__main__":
    sys.exit(main())
