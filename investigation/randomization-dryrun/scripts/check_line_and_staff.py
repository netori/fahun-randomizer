# check_line_and_staff.py — 只读：核实两件事
# ① 「法术线」整条置换是否可行：同一流派的 5 条（已批准部分）是否等长（决定能否整组互换）
# ② 法杖/圣印记是否带"流派亲和"字段（决定能否按流派亲和约束）
import collections, csv, json, os, sys
import xml.etree.ElementTree as ET

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
RB = os.path.join(WB, "evidence", "work2", "regulation-bin")


def main():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    slots = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            slots[str(s["item_id"])].append({"table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                             "category": str(s["category"]), "row_name": L.get("row_name", "")})
    ov = [x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig"))
          if x["row_kind"] == "item" and x["category"] == "goods" and x["final_decision"] == "approved"]
    lines = collections.defaultdict(list)
    for x in ov:
        for c in slots.get(x["item_id"], []):
            if c["category"] == "1":
                lines[x["rune_school"]].append({"id": x["item_id"], "tier": x["rune_tier"], "name": x["name_cn"],
                                                "table": c["table"], "row_id": c["row_id"], "slot": c["slot"]})
    print("=== ① 法术线（按流派）的格子数 ===")
    lens = collections.Counter(len(v) for v in lines.values())
    print(f"  流派人 {len(lines)} 条；每条线的格子数分布: {dict(lens)}")
    print(f"  → 全部等长（{list(lens)[0] if len(lens)==1 else '不等长'}）：{'可以整条互换' if len(lens)==1 else '需要按同长度配对'}")
    for school, items in sorted(lines.items())[:3]:
        tiers = [i["tier"] for i in items]
        print(f"    {school}: {len(items)} 格 / 等级 {tiers}")
    print()
    print("=== ② 法杖/圣印记是否带流派亲和字段 ===")
    staff_attrs = set()
    staff_examples = []
    for r in ET.parse(os.path.join(RB, "EquipParamWeapon.param.xml")).getroot().find("rows").findall("row"):
        a = dict(r.attrib)
        wc = a.get("weaponCategory", "")
        if wc in ("8", "13", "14"):        # 8=圣印记 13/14=其他法器类（按实际数据核对）
            staff_attrs.update(a.keys())
            if len(staff_examples) < 2:
                staff_examples.append((a.get("id"), wc, {k: v for k, v in a.items() if k in
                                                         ("weaponCategory", "wepType", "sorceryScaling", "incantationScaling",
                                                          "correctMagic", "correctFaith", "spEffectBehaviorId0", "spEffectBehaviorId1",
                                                          "spEffectBehaviorId2", "spEffectBehaviorId3", "resistMagic")}))
    kw = [k for k in sorted(staff_attrs) if any(t in k.lower() for t in ("scal", "school", "magic", "faith", "sorcery", "incant"))]
    print("  含 scaling/magic/faith/sorcery/incant 的字段:", kw)
    for e in staff_examples:
        print("   样例:", e)
    print("  说明：若字段里只有 'correctMagic/correctFaith' 之类，说明'这把法器强化哪一系'不存在单字段，")
    print("        需要靠 spEffect/被动文本（FMG 描述）另行取证——本脚本不臆测。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
