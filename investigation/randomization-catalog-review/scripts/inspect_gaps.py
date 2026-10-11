# inspect_gaps.py — 只读：分析 9 个未批准 Bundle 的缺口性质（缺数据 vs 缺匹配）+ 幽影流派清单
import csv, json, os, collections, re
import xml.etree.ElementTree as ET

REV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(REV), "randomization-catalog")
EV = os.path.join(CAT, "evidence")

HEAD_KW = ["兜帽", "风帽", "头冠", "头盔", "面具", "眼罩", "头罩", "帽子", "帽"]
BODY_KW = ["长袍", "外衣", "铠甲", "胸甲", "袍", "服", "甲"]
ARM_KW = ["手套", "护手", "腕套", "护腕", "臂甲", "腕带", "手环", "袖套", "手腕", "裹布", "腕"]
LEG_KW = ["裤子", "靴子", "绑腿", "腿甲", "护胫", "长靴", "裤", "靴", "腿"]
PART_KW = {"head": HEAD_KW, "body": BODY_KW, "arm": ARM_KW, "leg": LEG_KW}


def main():
    # 1) FMG 名称 + 参数部位
    root = ET.parse(os.path.join(EV, "xml", "ProtectorName.fmg.xml")).getroot()
    zh = {e.get("id"): e.text for e in root.findall(".//text") if e.text}
    try:
        root2 = ET.parse(os.path.join(EV, "xml", "ProtectorName_dlc01.fmg.xml")).getroot()
        zh.update({e.get("id"): e.text for e in root2.findall(".//text") if e.text})
    except FileNotFoundError:
        pass
    RB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence", "work2", "regulation-bin")
    proot = ET.parse(os.path.join(RB, "EquipParamProtector.param.xml")).getroot()
    part = {}
    for r in proot.find("rows").findall("row"):
        a = dict(r.attrib)
        part[a["id"]] = next((k for k, f in (("head", "headEquip"), ("body", "bodyEquip"), ("arm", "armEquip"), ("leg", "legEquip")) if a.get(f) == "1"), "")

    bundles = json.load(open(os.path.join(CAT, "bundles.json"), encoding="utf-8"))["bundles"]
    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    slot_items = collections.Counter()
    shop_items = collections.Counter()
    for L in idx["lots"]:
        for s in L["slots"]:
            slot_items[str(s["item_id"])] += 1
    for s in idx["shops"]:
        shop_items[str(s["equipId"])] += 1

    print("=== 9 个未批准 Bundle：缺口性质 ===")
    for b in bundles:
        if b["approvable"]:
            continue
        miss = [m for m in b["members"] if not m.get("piece_id")]
        noslot = [m for m in b["members"] if m.get("piece_id") and not m.get("entrance")]
        print(f"-- {b['class_name']}（{b['class_attrs']}） 缺件 {len(miss)} / 有件无槽 {len(noslot)}")
        for m in miss:
            sn = m.get("sheet_piece_name", "")
            cands = [(i, n) for i, n in zh.items() if n and sn and (n.startswith(sn[:3]) or sn.startswith(n[:3]))]
            kw = next((p for p, kws in PART_KW.items() if any(k in sn for k in kws)), "")
            cands2 = sorted([(i, n) for i, n in zh.items() if n.startswith(b["class_name"]) and part.get(i) == kw],
                            key=lambda x: int(x[0]))
            print(f"     缺件「{sn}」→ 同前缀同部位候选: {[(i, n) for i, n in cands2]}")
            print(f"        其奖励槽: {[(i, slot_items.get(i, 0), 'shop:' + str(shop_items.get(i, 0))) for i, _ in cands2]}")
        for m in noslot:
            i = str(m["piece_id"])
            print(f"     有件无槽 {m['part']} {i} {zh.get(i, '')} → Lot槽={slot_items.get(i,0)} 商店行={shop_items.get(i,0)}")
    print()
    print("=== 幽影系列（approved 的 18 条）流派与槽 ===")
    rows = list(csv.DictReader(open(os.path.join(REV, "../randomization-catalog-review/candidate_review.csv"), encoding="utf-8-sig")))
    ys = [x for x in rows if x["row_kind"] == "item" and x["mechanical_subpool"] == "rune:大师级(幽影)"]
    print("  条数:", len(ys), "流派:", "、".join(x["rune_school"] for x in ys))
    print("  样例槽:", [(x["item_id"], x["slot_keys"][:38]) for x in ys[:4]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
