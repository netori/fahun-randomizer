# build_shop_candidates.py — 生成「商店候选清单（草案）」：把只在商店出售的武器/防具做成可批准的正式候选
# 背景：干跑开 --with-shops 时，这些物品是"临时借入"的——没有经过审计的身份/入口/归属三关。
#       本清单把它们补齐证据，交人按批批准；批准后它们就成为正式池成员（不再依赖"顺手借入"）。
# 只读输入；写出 investigation/randomization-catalog-review/shop_candidate_draft.csv
import csv, json, os, collections, sys

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.path.join(os.path.dirname(DRY), "randomization-catalog-review")
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")


def main():
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    rn = {str(s["shop_row_id"]): s for s in idx["shops"]}
    shops = json.load(open(os.path.join(DRY, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]
    overlay = {x["item_id"]: x for x in csv.DictReader(open(os.path.join(REV, "evidence", "decisions_overlay.csv"), encoding="utf-8-sig"))
               if x["row_kind"] == "item"}
    starter = {str(p["id"]): g["class_name"] for g in
               json.load(open(os.path.join(REV, "evidence", "starter_set_freeze.json"), encoding="utf-8"))["groups"] for p in g["pieces"]}
    lot_slots = collections.Counter()
    for L in idx["lots"]:
        for s in L["slots"]:
            lot_slots[str(s["item_id"])] += 1

    by_item = collections.defaultdict(list)
    for r in shops:
        if r["equip_type_name"] in ("weapon", "protector") and r["quality"] == "clean":
            by_item[(r["equip_type_name"], r["equipId"])].append(r)

    rows, skipped = [], collections.Counter()
    for (et, iid), rs in sorted(by_item.items()):
        if starter.get(iid):
            skipped["初始套装件(按 D5 排除)"] += 1
            continue
        cat = "weapon" if et == "weapon" else "protector"
        part = rs[0]["part"] if cat == "protector" else ""
        wc = rs[0]["weaponCategory"] if cat == "weapon" else ""
        if cat == "protector" and not part:
            skipped["部位未知"] += 1
            continue
        if cat == "weapon" and not wc:
            skipped["武器类别未知"] += 1
            continue
        sub = ("armor:" + part) if cat == "protector" else ("weapon:category=" + wc)
        in_cat = overlay.get(iid, {})
        rows.append({
            "item_id": iid, "category": cat, "name_cn": rs[0]["name_cn"],
            "equip_type": rs[0]["equipType"], "part": part, "weaponCategory": wc,
            "shop_rows": len(rs), "shop_row_ids": " ".join(x["shop_row_id"] for x in rs),
            "prices": " ".join(str(x["price"]) for x in rs), "stocks": " ".join(str(x["stock"]) for x in rs),
            "exclusive_like": "yes" if len(rs) == 1 else "no",
            "has_lot_entrance": "yes" if lot_slots.get(iid) else "no",
            "in_catalog_decision": in_cat.get("final_decision", "(不在候选资料里)"),
            "proposed_subpool": sub,
            "identity_evidence": f"FMG 名称 {rs[0]['name_cn']} + ShopLineupParam 行 (equipType={rs[0]['equipType']}, " +
                                 (f"part={part}" if cat == "protector" else f"weaponCategory={wc}") + ")",
            "entrance_evidence": " ".join(f"ShopLineupParam:{x['shop_row_id']}" for x in rs) +
                                 ("；另有 Lot 入口" if lot_slots.get(iid) else "；仅商店入口"),
            "status": "pending_user_approval",
            "notes": ("多卖家/多行（同一物品 %d 行）" % len(rs)) if len(rs) > 1 else "专属性（只此一行）",
        })

    cols = list(rows[0].keys()) if rows else ["item_id"]
    out = os.path.join(REV, "shop_candidate_draft.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    stat = collections.Counter(r["category"] for r in rows)
    exc = collections.Counter(r["exclusive_like"] for r in rows)
    print("=== 商店候选清单（草案）===")
    print(f"  条目 {len(rows)} 件：武器 {stat['weapon']} / 防具 {stat['protector']}   行数合计 {sum(r['shop_rows'] for r in rows)}")
    print(f"  专属性（只此一行）{exc['yes']} 件 / 多行 {exc['no']} 件")
    print(f"  已在候选资料里的: {sum(1 for r in rows if r['in_catalog_decision'] != '(不在候选资料里)')} 件；不在的: {sum(1 for r in rows if r['in_catalog_decision'] == '(不在候选资料里)')} 件")
    print(f"  按子池: {dict(collections.Counter(r['proposed_subpool'] for r in rows))}")
    print(f"  跳过: {dict(skipped)}")
    print()
    print("=== 样例（前 8 条）===")
    for r in rows[:8]:
        print(f"  {r['item_id']:<9} {r['category']:<9} {r['name_cn'][:12]:<13} {r['proposed_subpool']:<20} "
              f"行{r['shop_rows']} 价{r['prices']:<12} 库存{r['stocks']:<8} 专属={r['exclusive_like']}")
    print(f"\n写出 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
