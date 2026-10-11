# audit_candidates.py — 只读质量审计：候选资料能否进入随机化干跑（v2）
# 输入（只读）：investigation/randomization-catalog/ 的 items.csv / reward_slots.csv / bundles.json /
#               guide_entries.csv / evidence/lot_reward_index.json / evidence/source_integrity_final.json
#               + 被引用证据 investigation/weapon-baseline/weapon_mapping.csv（仅核对武器类别，见 REPORT 说明）
# 输出（本目录）：candidate_review.csv、slot_conflicts.csv、evidence/audit_findings.json
# 语义：approved 只表示"可以进入干跑"，不表示可直接写回 MOD；未知值留空，不用 0 代替。
import csv, json, os, re, collections, sys

REV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(REV), "randomization-catalog")
EV = os.path.join(CAT, "evidence")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline")
EXPR = lambda rel: "investigation/randomization-catalog/" + rel.replace("\\", "/")

PROFESSION_AFFINITY = {
    "5100000": "秘契职业",
    "18530000": "神皮流派",
}
PART_MAP = {"head": "head", "body": "chest", "arm": "arms", "leg": "legs"}


def rows(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def main():
    items = rows(os.path.join(CAT, "items.csv"))
    slots = rows(os.path.join(CAT, "reward_slots.csv"))
    bundles = json.load(open(os.path.join(CAT, "bundles.json"), encoding="utf-8"))["bundles"]
    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))

    # 一次建好索引：item_id -> 槽列表（避免逐物品扫描）
    idx_slots = collections.defaultdict(list)
    verify_map = {}
    for L in idx["lots"]:
        for sl in L["slots"]:
            rec = {"source_table": L["table"], "row_id": str(L["lot_id"]), "slot": str(sl["slot"]),
                   "slot_item_category": str(sl["category"]), "quantity": str(sl.get("num", "")),
                   "base_point": str(sl.get("base_point", "")), "cumulate_lot_point": str(sl.get("cumulate_lot_point", "")),
                   "row_get_flag": str(L.get("getItemFlagId", "")), "row_name": L.get("row_name", ""),
                   "evidence": "evidence/lot_reward_index.json"}
            idx_slots[str(sl["item_id"])].append(rec)
            if sl["slot"] is not None:
                verify_map[(L["table"], str(L["lot_id"]), str(sl["slot"]))] = (str(sl["item_id"]), str(sl["category"]))

    weapon_cat = {}
    wm = os.path.join(WB, "weapon_mapping.csv")
    if os.path.exists(wm):
        for r in rows(wm):
            m = re.search(r"weaponCategory=(\d+)", r.get("weapon_category", ""))
            if m and r["item_id"] not in weapon_cat:
                weapon_cat[r["item_id"]] = m.group(1)

    slots_by_item = collections.defaultdict(list)
    for s in slots:
        slots_by_item[(s["category"], s["item_id"])].append(s)

    bundle_of_item, bundle_slots, bundle_entr = {}, collections.defaultdict(list), {}
    for b in bundles:
        for m in b["members"]:
            if m.get("piece_id"):
                bundle_of_item.setdefault(str(m["piece_id"]), []).append(b["class_name"])
            if m.get("entrance"):
                e = m["entrance"]
                k = (e["source_table"], str(e["row_id"]), str(e["slot"]))
                bundle_slots[k].append(b["class_name"])
                bundle_entr.setdefault(b["class_name"], []).append((m["part"], str(m["piece_id"]), k))
    approved_bundles = {b["class_name"] for b in bundles if b["approvable"]}

    review, conflicts = [], []

    # ---------------- Bundle 级 ----------------
    for b in bundles:
        parts = [m["part"] for m in b["members"]]
        es = [m.get("entrance") for m in b["members"]]
        keys = [(e["source_table"], str(e["row_id"]), str(e["slot"])) for e in es if e]
        problems = []
        if len(set(parts)) != 4 or set(parts) != {"head", "body", "arm", "leg"}:
            problems.append("PARTS_NOT_EXACTLY_FOUR")
        if len(keys) != 4:
            problems.append("MISSING_TARGET_SLOT")
        if len(set(keys)) != len(keys):
            problems.append("DUPLICATE_TARGET_SLOT")
        if [k for k in keys if len(bundle_slots[k]) > 1]:
            problems.append("SLOT_SHARED_WITH_OTHER_BUNDLE")
        shared_members = [m["piece_id"] for m in b["members"]
                          if m.get("piece_id") and [x for x in bundle_of_item.get(str(m["piece_id"]), []) if x != b["class_name"] and x in approved_bundles]]
        if shared_members:
            problems.append("MEMBER_SHARED_WITH_APPROVED_BUNDLE")
        bad_verify = [p for (p, pid, k) in bundle_entr.get(b["class_name"], [])
                      if verify_map.get(k) != (pid, "3")]
        if bad_verify:
            problems.append("SLOT_INDEX_VERIFY_FAILED")
        missing_rows = [str(m["piece_id"]) for m in b["members"]
                        if m.get("piece_id") and not slots_by_item.get(("protector", str(m["piece_id"])))]
        if missing_rows:
            conflicts.append({"slot_key": "n/a", "source_table": "", "row_id": "", "slot": "",
                              "conflict_type": "INPUT_GAP_REWARD_SLOTS_MISSING", "severity": "medium",
                              "claimants": f"bundle:{b['class_name']} 成员 " + ",".join(missing_rows),
                              "resolution": "items.csv 含该防具行但 reward_slots.csv 无入口行；槽位以 bundles.json + evidence/lot_reward_index.json 复核（本次已逐条核对）",
                              "evidence_path": EXPR("reward_slots.csv") + "; " + EXPR("evidence/lot_reward_index.json")})
        dec = "approved" if (not problems and b["class_name"] in approved_bundles) else "pending"
        review.append({
            "row_kind": "bundle", "class_decision": dec,
            "reason_code": "OK_FOUR_PARTS_FOUR_SLOTS_INDEX_VERIFIED" if dec == "approved" else (";".join(problems) or "BUNDLE_INCOMPLETE"),
            "item_id": "", "category": "bundle", "name_cn": b["class_name"], "part": "", "pool_input": "poolA_bundle",
            "role": "", "rune_tier": "", "rune_school": "", "profession_affinity": "",
            "mechanical_subpool": "armor:set_bundle(4件)", "n_valid_slots": str(len(set(keys))),
            "slot_keys": " | ".join(f"{k[0]}:{k[1]}:s{k[2]}" for k in keys),
            "identity_evidence": f"xlsx {b['class_cells']} + zhocn ProtectorName FMG + EquipParamProtector 部位标志",
            "slot_evidence": EXPR("bundles.json") + " + " + EXPR("evidence/lot_reward_index.json"),
            "world_position_status": "hint_only(xlsx Location + lot 行名)", "single_acquisition_status": "unverified",
            "notes": "四件齐/四槽齐/无共享槽/槽位与索引一致" if dec == "approved" else "未批准：" + ",".join(problems),
            "evidence_path": EXPR("bundles.json")})
        for k in set(keys):
            if len(bundle_slots[k]) > 1:
                conflicts.append({"slot_key": f"{k[0]}:{k[1]}:s{k[2]}", "source_table": k[0], "row_id": k[1], "slot": k[2],
                                  "conflict_type": "BUNDLE_SLOT_SHARED", "severity": "high",
                                  "claimants": "; ".join(sorted(set(bundle_slots[k]))),
                                  "resolution": "同一目标槽不得同时归属两个 Bundle", "evidence_path": EXPR("bundles.json")})

    # ---------------- Item 级 ----------------
    for it in items:
        iid, cat, name = it["item_id"], it["category"], it["name_cn"]
        role, part = it["role"], it["part"]
        mine = slots_by_item.get((cat, iid), [])
        want = {"protector": "3", "goods": "1", "weapon": "2"}.get(cat)
        ok_slots = [s for s in mine if s["source_table"] != "ShopLineupParam" and s["slot_item_category"] == want]
        shop_slots = [s for s in mine if s["source_table"] == "ShopLineupParam"]
        bad_slots = [s for s in mine if s["source_table"] != "ShopLineupParam" and s["slot_item_category"] != want]
        slots_src = EXPR("reward_slots.csv") if mine else ""
        gap_note = ""
        if not ok_slots and want:
            aux = [x for x in idx_slots.get(iid, []) if x["slot_item_category"] == want]
            if aux:
                ok_slots, slots_src, gap_note = aux, EXPR("evidence/lot_reward_index.json") + "（reward_slots.csv 缺行，已用索引复核）", "INPUT_GAP_REWARD_SLOTS_MISSING"
        for s in bad_slots:
            conflicts.append({"slot_key": f"{s['source_table']}:{s['row_id']}:s{s['slot']}", "source_table": s["source_table"],
                              "row_id": s["row_id"], "slot": s["slot"], "conflict_type": "ITEM_CATEGORY_MISMATCH",
                              "severity": "high", "claimants": f"{cat}:{iid}({name})",
                              "resolution": "该槽 lotItemCategory 与物品类别不符（同名 ID 跨类别），不得作为本物品入口",
                              "evidence_path": EXPR("evidence/lot_reward_index.json")})

        sub = ""
        if cat == "protector" and part in PART_MAP:
            sub = "armor:" + PART_MAP[part]
        elif cat == "weapon":
            wc = weapon_cat.get(iid)
            sub = f"weapon:category={wc}" if wc else "weapon:category=UNKNOWN"
        elif cat == "goods" and it["rune_tier"]:
            sub = "rune:" + it["rune_tier"].replace("大师级(幽影系列)", "大师级(幽影)")
        elif cat == "goods" and role:
            sub = "goods:out_of_scope"

        attr = it["class_attribution_evidence"] or ""
        bnames = bundle_of_item.get(iid, [])
        if cat == "weapon":
            dec, rc = "pending", "WEAPON_PENDING_USER_APPROVAL"
        elif cat == "goods" and role == "普通经验卢恩":
            dec, rc = "excluded", "OUT_OF_SCOPE_EXP_RUNE"
        elif cat == "goods" and "碎片" in role:
            dec, rc = "excluded", "INTERMEDIATE_ITEM_EXCLUDED"
        elif cat == "goods" and role == "完整职业法术卢恩":
            if not ok_slots:
                dec, rc = "pending", "NO_REWARD_SLOT_EVIDENCE"
            elif attr:
                dec, rc = "approved", "RUNE_IDENTITY_TIER_SLOT_OK"
            else:
                dec, rc = "pending", "CLASS_AFFINITY_UNVERIFIED"
        elif cat == "goods":
            dec = "excluded"
            rc = "OUT_OF_SCOPE_EXP_RUNE" if "使用后能获得" in (it["xlsx_lead_effect"] or "") else "OUT_OF_SCOPE_KEY_OR_OTHER_RUNE"
        else:
            if not ok_slots:
                dec, rc = "pending", "NO_REWARD_SLOT_EVIDENCE"
            elif any(b in approved_bundles for b in bnames):
                dec, rc = "approved", "BUNDLE_MEMBER_APPROVED"
            elif bnames:
                dec, rc = "pending", "BUNDLE_MEMBER_BUNDLE_NOT_APPROVED"
            elif "职业说明 entry" in attr:
                dec, rc = "approved", "GUIDE_ATTRIBUTED_SINGLE_PIECE"
            elif attr:
                dec, rc = "pending", "CLASS_SHEET_ATTRIBUTED_NEEDS_POOL_DECISION"
            else:
                dec, rc = "pending", "POOL_ASSIGNMENT_UNSUPPORTED"

        notes = []
        if gap_note:
            notes.append(gap_note)
        if ok_slots and shop_slots:
            notes.append("同时存在商店入口")
        if len(ok_slots) > 1:
            notes.append(f"多入口({len(ok_slots)})")
        if bad_slots:
            notes.append(f"存在{len(bad_slots)}条类别不符入口（已剔除）")
        if cat == "goods" and role == "完整职业法术卢恩" and not attr:
            notes.append("身份/等级/槽位证据在，但职业说明书未点名")
        if cat == "weapon":
            notes.append("职业标签为会话给定的用户确认元数据，不作 ID/行/入口/FMG 证据；机械类别取自被引用证据 weapon_mapping.csv")
        review.append({
            "row_kind": "item", "class_decision": dec, "reason_code": rc, "item_id": iid, "category": cat,
            "name_cn": name, "part": part, "pool_input": it["suggested_pool"], "role": role,
            "rune_tier": it["rune_tier"], "rune_school": it["rune_school"],
            "profession_affinity": PROFESSION_AFFINITY.get(iid, ""), "mechanical_subpool": sub,
            "n_valid_slots": str(len(ok_slots)),
            "slot_keys": " | ".join(f"{s['source_table']}:{s['row_id']}:s{s['slot']}" for s in ok_slots[:4]),
            "identity_evidence": it["evidence_path"], "slot_evidence": slots_src,
            "world_position_status": "hint_only" if ok_slots else "", "single_acquisition_status": "unverified" if ok_slots else "",
            "notes": "; ".join(notes), "evidence_path": it["evidence_path"]})

    # ---------------- 槽级补充检查 ----------------
    claim = collections.defaultdict(set)
    for s in slots:
        if s["slot"]:
            claim[(s["source_table"], s["row_id"], s["slot"])].add(f"{s['category']}:{s['item_id']}")
    for k, v in claim.items():
        if len(v) > 1:
            conflicts.append({"slot_key": f"{k[0]}:{k[1]}:s{k[2]}", "source_table": k[0], "row_id": k[1], "slot": k[2],
                              "conflict_type": "SLOT_MULTI_CLAIM", "severity": "medium",
                              "claimants": "; ".join(sorted(v)),
                              "resolution": "同一槽出现在多个物品候选下，干跑时不得重复占用",
                              "evidence_path": EXPR("reward_slots.csv")})
    lotfull = {(L["table"], str(L["lot_id"])): L["slots"] for L in idx["lots"]}
    seen = set()
    for s in slots:
        if not s["slot"]:
            continue
        key = (s["source_table"], s["row_id"])
        if key in seen:
            continue
        seen.add(key)
        other = [x for x in lotfull.get(key, []) if str(x["slot"]) != s["slot"] and x.get("item_id")]
        if other:
            conflicts.append({"slot_key": f"{key[0]}:{key[1]}:s{s['slot']}", "source_table": key[0], "row_id": key[1], "slot": s["slot"],
                              "conflict_type": "LOT_OTHER_SLOTS_PRESENT", "severity": "info",
                              "claimants": "; ".join(f"s{x['slot']}:cat{x['category']}:id{x['item_id']}" for x in other),
                              "resolution": "目标 Lot 还有其它 slot，干跑/写回必须保留其原样",
                              "evidence_path": EXPR("evidence/lot_reward_index.json")})
    for s in slots:
        if s["source_table"] != "ShopLineupParam":
            continue
        if s["shop_price"] in ("1", "0") or s["shop_stock"] == "-1":
            conflicts.append({"slot_key": f"ShopLineupParam:{s['row_id']}", "source_table": "ShopLineupParam",
                              "row_id": s["row_id"], "slot": "", "conflict_type": "SHOP_SEMANTICS_UNVERIFIED",
                              "severity": "medium", "claimants": f"{s['category']}:{s['item_id']}",
                              "resolution": f"price={s['shop_price']} stock={s['shop_stock']} stockFlag={s['shop_stock_flag']} releaseFlag={s['shop_release_flag']}；行名可能为 Paramdex 回退，语义需人工确认后才可纳入干跑",
                              "evidence_path": EXPR("reward_slots.csv")})
    for it in items:
        if "碎片" in (it["role"] or ""):
            conflicts.append({"slot_key": "n/a", "source_table": "", "row_id": "", "slot": "",
                              "conflict_type": "INTERMEDIATE_IN_POOL", "severity": "info",
                              "claimants": f"goods:{it['item_id']}({it['name_cn']})",
                              "resolution": "中间物已排除；若将来启用须先取得合成引用证据", "evidence_path": EXPR("items.csv")})
        if it["item_id"] == "8460":
            conflicts.append({"slot_key": "n/a", "source_table": "", "row_id": "", "slot": "",
                              "conflict_type": "FINAL_PRODUCT_CRAFT_REF_MISSING", "severity": "medium",
                              "claimants": "goods:8460(幽影岩浆卢恩)",
                              "resolution": "碎片描述暗示合成关系，但候选资料无 EquipMtrlSetParam/事件引用证据；仅记录候选，不改合成逻辑",
                              "evidence_path": EXPR("evidence/goods_runes.json")})

    # ---------------- 写出 ----------------
    out_cols = ["row_kind", "class_decision", "reason_code", "item_id", "category", "name_cn", "part", "pool_input",
                "role", "rune_tier", "rune_school", "profession_affinity", "mechanical_subpool", "n_valid_slots",
                "slot_keys", "identity_evidence", "slot_evidence", "world_position_status", "single_acquisition_status",
                "notes", "evidence_path"]
    with open(os.path.join(REV, "candidate_review.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_cols)
        w.writeheader()
        for r in review:
            w.writerow({k: r.get(k, "") for k in out_cols})
    ccols = ["slot_key", "source_table", "row_id", "slot", "conflict_type", "severity", "claimants", "resolution", "evidence_path"]
    with open(os.path.join(REV, "slot_conflicts.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ccols)
        w.writeheader()
        for c in conflicts:
            w.writerow({k: c.get(k, "") for k in ccols})

    stat = collections.defaultdict(collections.Counter)
    for r in review:
        k = "bundle" if r["row_kind"] == "bundle" else {"protector": "装备", "weapon": "武器", "goods": "卢恩"}.get(r["category"], r["category"])
        stat[k][r["class_decision"]] += 1
    print("=== 分类统计 ===")
    for k, c in stat.items():
        print(f"  {k}: approved={c.get('approved',0)} pending={c.get('pending',0)} excluded={c.get('excluded',0)} (合计 {sum(c.values())})")
    print("=== reason_code ===")
    for rc, n in collections.Counter(r["reason_code"] for r in review).most_common():
        print(f"  {n:>5}  {rc}")
    print("=== conflict_type ===")
    for ct, n in collections.Counter(c["conflict_type"] for c in conflicts).most_common():
        print(f"  {n:>5}  {ct}")
    print("写出 candidate_review.csv", len(review), "行；slot_conflicts.csv", len(conflicts), "行")
    json.dump({"stats": {k: dict(v) for k, v in stat.items()},
               "reason_codes": dict(collections.Counter(r["reason_code"] for r in review)),
               "conflict_types": dict(collections.Counter(c["conflict_type"] for c in conflicts)),
               "weapon_category_from_cited_evidence": weapon_cat},
              open(os.path.join(REV, "evidence", "audit_findings.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
