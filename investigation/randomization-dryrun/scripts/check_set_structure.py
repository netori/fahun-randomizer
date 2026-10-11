# check_set_structure.py — 只读：法术/祷告类"成套"结构到底长什么样
# 问题：一套 = 初始套装（已按 D5 冻结）？还是"同一流派的 6 条卢恩"？还是"法杖/圣印记按类别"？
# 做法：把"同一流派的 6 个等级卢恩"的 ID、等级、所在地点（lot 行名）列出来，看它们是"同一职业的里程碑线"还是"散在世界各处"。
import collections, json, os, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")


def main():
    import csv
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    slots = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            slots[str(s["item_id"])].append({"table": L["table"], "row_id": str(L["lot_id"]), "slot": str(s["slot"]),
                                             "row_name": L.get("row_name", "")})
    ov = [x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig"))
          if x["row_kind"] == "item" and x["category"] == "goods"]
    by_school = collections.defaultdict(list)
    for x in ov:
        if x["final_decision"] != "approved":
            continue
        by_school[x["rune_school"]].append({"id": x["item_id"], "name": x["name_cn"], "tier": x["rune_tier"],
                                            "slots": slots.get(x["item_id"], [])})
    print("=== 已批准的完整卢恩：每个流派的 6 个等级分别在哪 ===")
    for school, items in sorted(by_school.items()):
        tiers = {x["tier"] for x in items}
        print(f"\n-- {school}（{len(items)} 条 / 等级 {len(tiers)} 种）")
        order = {"新手级": 0, "学徒级": 1, "熟练级": 2, "精通级": 3, "大师级": 4}
        for x in sorted(items, key=lambda y: order.get(y["tier"], 9)):
            s = x["slots"][0] if x["slots"] else None
            loc = (s["row_name"][:56] if s else "（无槽）")
            print(f"     {x['tier']:<8} {x['id']:<6} {x['name'][:12]:<13} {s['table'].replace('ItemLotParam_','') if s else '':<6}:{s['row_id'] if s else '':<12} {loc}")
    print()
    # 地点是否"同族"：看 6 条的行名前 2 个词是否相同
    print("=== 同一流派 6 条的地点是否'同族' ===")
    same = 0
    for school, items in sorted(by_school.items()):
        prefixes = collections.Counter((x["slots"][0]["row_name"].split("]")[0] + "]") if x["slots"] and "]" in x["slots"][0]["row_name"] else "(无方括号)" for x in items)
        top, n = prefixes.most_common(1)[0]
        same += (n >= len(items) - 1)
        print(f"  {school:<6} 地点前缀: {dict(prefixes)}  → {'同族' if n >= len(items)-1 else '分散'}")
    print(f"\n  结论：{same} / {len(by_school)} 个流派的 6 条卢恩位于'同族地点'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
