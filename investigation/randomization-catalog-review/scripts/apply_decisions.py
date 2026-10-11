# apply_decisions.py — 把用户决策 D1（微光不随）与 D5（初始套装不随）叠加到审计结果上
# 只读 randomization-catalog/ 与本目录既有产物；输出本目录 evidence/decisions_overlay.csv 与计数
import csv, json, os, collections

REV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(REV), "randomization-catalog")
EV = os.path.join(CAT, "evidence")


def main():
    review = [x for x in csv.DictReader(open(os.path.join(REV, "candidate_review.csv"), encoding="utf-8-sig"))]
    freeze = json.load(open(os.path.join(REV, "evidence", "starter_set_freeze.json"), encoding="utf-8"))
    starter_ids = {}
    for g in freeze["groups"]:
        for p in g["pieces"]:
            starter_ids[str(p["id"])] = {"class_name": g["class_name"], "part": p["part"],
                                         "match_method": p["match_method"], "fmg_name": p["fmg_name"]}
    starter_classes = {g["class_name"] for g in freeze["groups"]}

    out_rows = []
    stat = collections.Counter()
    for x in review:
        base = x["class_decision"]
        final, overlay = base, ""
        if x["row_kind"] == "bundle":
            if x["name_cn"] in starter_classes:
                final, overlay = "excluded", "D5_STARTER_SET_FROZEN"
        else:
            iid = x["item_id"]
            if x["category"] == "goods" and x.get("rune_tier") == "新手级":
                final, overlay = "excluded", "D1_USER_RULE_GLIMMER_RUNE"
            elif iid in starter_ids:
                final, overlay = "excluded", "D5_STARTER_SET_FROZEN"
        stat[(x["row_kind"], x["category"], final)] += 1
        out_rows.append({**x, "decision_before_user_rules": base, "final_decision": final, "user_rule_applied": overlay,
                         "starter_set_class": starter_ids.get(x["item_id"], {}).get("class_name", "") if x["row_kind"] == "item" else ""})

    cols = list(out_rows[0].keys())
    with open(os.path.join(REV, "evidence", "decisions_overlay.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, "") for k in cols})

    print("=== 叠加 D1+D5 后的最终分类 ===")
    for (kind, cat, dec), n in sorted(stat.items()):
        print(f"  {kind:<7} {cat:<10} {dec:<9} {n}")
    print()
    totals = collections.Counter()
    for (kind, cat, dec), n in stat.items():
        k = "bundle" if kind == "bundle" else {"protector": "装备", "weapon": "武器", "goods": "卢恩"}[cat]
        totals[(k, dec)] += n
    print("=== 类别 × 决策 ===")
    for k in ("装备", "武器", "卢恩", "bundle"):
        row = {d: totals[(k, d)] for d in ("approved", "pending", "excluded")}
        print(f"  {k:<8} approved={row['approved']:<4} pending={row['pending']:<4} excluded={row['excluded']}")
    print()
    print("=== 被 D5 冻结、且原本是 approved 的条目 ===")
    for r in out_rows:
        if r["user_rule_applied"].startswith("D5") and r["decision_before_user_rules"] == "approved":
            print(f"  {r['row_kind']:<7} {r['item_id'] or r['name_cn']:<9} {r['name_cn'][:14]:<15} {r['slot_keys'][:36]}")
    json.dump({"totals": {f"{k}|{d}": v for (k, d), v in totals.items()},
               "starter_set_classes": sorted(starter_classes),
               "starter_ids_identified": len(starter_ids)},
              open(os.path.join(REV, "evidence", "decisions_overlay_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
