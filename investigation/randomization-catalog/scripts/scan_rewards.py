# scan_rewards.py — 建立奖励槽索引（只读解析，不改任何原文件）
# 输入：上一轮已解包的 regulation XML（weapon-baseline/evidence/work2/regulation-bin/）
#       + 本目录 evidence/armor_id_candidates.json（xlsx 线索 → 真实防具 ID）
# 输出：evidence/lot_reward_index.json
#   * lots[]：ItemLotParam_map / ItemLotParam_enemy 每一行的全部 slot 快照（非默认槽）
#   * shops[]：ShopLineupParam 每一行的字段快照
#   * category_table_derivation：lotItemCategory 取值 ↔ 该 id 实际出现在哪张 EquipParam 表（用真表反推语义）
import xml.etree.ElementTree as ET
import os, json, collections, sys

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "work2", "regulation-bin")


def load(fn):
    root = ET.parse(os.path.join(RB, fn + ".param.xml")).getroot()
    fd = {f.get("name"): f.get("defaultValue") for f in root.find("fields").findall("field")}
    return fd, root.find("rows").findall("row")


def ids(fn):
    p = os.path.join(RB, fn + ".param.xml")
    if not os.path.exists(p):
        return set()
    return {int(r.get("id")) for r in load(fn)[1] if (r.get("id") or "").lstrip("-").isdigit()}


def main():
    tbl = {k: ids(v) for k, v in {
        "weapon": "EquipParamWeapon", "protector": "EquipParamProtector", "goods": "EquipParamGoods",
        "accessory": "EquipParamAccessory", "gem": "EquipParamGem"}.items()}
    print("EquipParam 表规模:", {k: len(v) for k, v in tbl.items()})

    alp_p = os.path.join(CAT, "evidence", "armor_id_candidates.json")
    want = set()
    if os.path.exists(alp_p):
        for m in json.load(open(alp_p, encoding="utf-8"))["matched"]:
            want.add(int(m["protector_id"]))
    print("xlsx 线索对应的防具 id 数:", len(want))

    out = {"category_table_derivation": {}, "lots": [], "shops": [], "target_protector_ids": sorted(want)}
    cat_map = collections.defaultdict(collections.Counter)

    for fn in ("ItemLotParam_map", "ItemLotParam_enemy"):
        fd, rows = load(fn)
        for r in rows:
            a = r.attrib
            slots = []
            for i in range(1, 9):
                iid = a.get("lotItemId%02d" % i, fd.get("lotItemId%02d" % i))
                cat = a.get("lotItemCategory%02d" % i, fd.get("lotItemCategory%02d" % i))
                if not iid or not iid.lstrip("-").isdigit():
                    continue
                iv = int(iid)
                if iv == 0:
                    continue
                c = int(cat) if cat and cat.lstrip("-").isdigit() else None
                where = sorted(k for k, v in tbl.items() if iv in v)
                if c is not None:
                    cat_map[c][tuple(where)] += 1
                slots.append({"slot": i, "item_id": iv, "category": c, "tables_containing_id": where,
                              "num": a.get("lotItemNum%02d" % i, fd.get("lotItemNum%02d" % i)),
                              "base_point": a.get("lotItemBasePoint%02d" % i, fd.get("lotItemBasePoint%02d" % i)),
                              "cumulate_lot_point": a.get("cumulateLotPoint%02d" % i, fd.get("cumulateLotPoint%02d" % i)),
                              "get_item_flag_id": a.get("getItemFlagId%02d" % i, fd.get("getItemFlagId%02d" % i))})
            if not slots:
                continue
            out["lots"].append({"table": fn, "lot_id": a.get("id"),
                                "row_name": a.get("name") or a.get("paramdexName") or "",
                                "getItemFlagId": a.get("getItemFlagId", fd.get("getItemFlagId")),
                                "GameClearOffset": a.get("GameClearOffset", fd.get("GameClearOffset")),
                                "slots": slots})

    fd, rows = load("ShopLineupParam")
    for r in rows:
        a = dict(r.attrib)
        eid = a.get("equipId")
        if not eid or not eid.lstrip("-").isdigit():
            continue
        iv = int(eid)
        out["shops"].append({
            "shop_row_id": a["id"], "equipId": iv, "equipType": a.get("equipType", fd.get("equipType")),
            "tables_containing_id": sorted(k for k, v in tbl.items() if iv in v),
            "value": a.get("value", fd.get("value")), "mtrlId": a.get("mtrlId", fd.get("mtrlId")),
            "sellQuantity": a.get("sellQuantity", fd.get("sellQuantity")),
            "eventFlag_forStock": a.get("eventFlag_forStock", fd.get("eventFlag_forStock")),
            "eventFlag_forRelease": a.get("eventFlag_forRelease", fd.get("eventFlag_forRelease")),
            "costType": a.get("costType", fd.get("costType")), "setNum": a.get("setNum", fd.get("setNum")),
            "row_name": a.get("name") or a.get("paramdexName") or ""})

    for c, cnt in sorted(cat_map.items()):
        out["category_table_derivation"][str(c)] = [[list(k), v] for k, v in cnt.most_common(4)]

    p = os.path.join(CAT, "evidence", "lot_reward_index.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("lotItemCategory ↔ 命中表（用真表反推）:")
    for c, v in out["category_table_derivation"].items():
        print("   cat", c, ":", v)
    print("已索引 lot 行:", len(out["lots"]), "| 商店行:", len(out["shops"]))
    print("写出:", p)

    by_item = collections.defaultdict(list)
    for L in out["lots"]:
        for s in L["slots"]:
            by_item[s["item_id"]].append((L["table"], L["lot_id"], s["slot"], s["category"]))
    hit = {i: v for i, v in by_item.items() if i in want}
    print("xlsx 线索防具中有 >=1 个 Lot 入口的:", len(hit), "/", len(want))
    multi = {i: v for i, v in hit.items() if len(v) > 1}
    print("其中多入口的件数:", len(multi))
    for i, v in list(multi.items())[:10]:
        print("   id", i, "->", v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
