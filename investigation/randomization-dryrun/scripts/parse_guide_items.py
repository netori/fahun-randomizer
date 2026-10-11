# parse_guide_items.py — 解析局内《职业说明书》（GoodsCaption.fmg 8800-8895），得到权威的"职业专属物品"
# 说明书三组：
#   8800-8806 近战职业：只写护甲重量偏好（重甲/轻甲和中甲），不列具体件
#   8807-8825 法术职业：列卢恩（道具）+ 少量防具
#   8870-8895 全职业：列武器
# 输出：evidence/guide_exclusive_items.json + 屏幕对比表（与当前候选 basis 的差集）
import collections, csv, json, os, re

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(os.path.dirname(DRY), "randomization-catalog")
RE_ROWS = re.compile(r"([^;()]+?)\s*\((\d+)\)")


def parse_mentions(s):
    out = []
    for m in RE_ROWS.finditer(s or ""):
        out.append({"name": m.group(1).strip(), "id": m.group(2)})
    return out


def class_of(first_line):
    m = re.match(r"^\s*([^\s，,]+?)(?:主要|偏好|喜欢)", first_line or "")
    return m.group(1) if m else (first_line or "").split(" ")[0][:8]


def main():
    rows = list(csv.DictReader(open(os.path.join(CAT, "guide_entries.csv"), encoding="utf-8-sig")))
    by_class = collections.defaultdict(lambda: {"weapons": [], "goods": [], "protectors": [], "armor_style": "", "entries": []})
    for r in rows:
        cls = class_of(r["first_line"])
        eid = r["entry_id"]
        by_class[cls]["entries"].append(eid)
        if "喜欢" in (r["first_line"] or "") or "偏好" in (r["first_line"] or ""):
            by_class[cls]["armor_style"] = r["first_line"].strip()
        for col, key in (("mentioned_weapon", "weapons"), ("mentioned_goods", "goods"), ("mentioned_protector", "protectors")):
            for it in parse_mentions(r[col]):
                if it not in by_class[cls][key]:
                    by_class[cls][key].append(it)

    # 权威集合
    guide_items = collections.defaultdict(set)          # cat -> {id}
    for cls, d in by_class.items():
        for key, cat in (("weapons", "weapon"), ("goods", "goods"), ("protectors", "protector")):
            for it in d[key]:
                guide_items[cat].add(it["id"])

    # 与当前候选对比
    draft = [r for r in csv.DictReader(open(os.path.join(DRY, "class_candidate_draft.csv"), encoding="utf-8-sig"))]
    have = collections.defaultdict(set)
    for r in draft:
        if r["has_entrance"] == "yes":
            have[r["category"]].add(r["matched_id"])
    cmp = {}
    for cat, catname in (("weapon", "武器"), ("goods", "卢恩/道具"), ("protector", "防具")):
        g, h = guide_items[cat], have[cat]
        cmp[catname] = {"guide": len(g), "in_basis": len(h & g), "guide_missing_from_basis": sorted(g - h),
                        "basis_not_in_guide": len(h - g)}
        missing_names = []
        for r in draft:
            if r["matched_id"] in (g - h) and r["category"] == cat and r["has_entrance"] == "yes":
                missing_names.append(f"{r['matched_id']}:{r['sheet_name']}@{r['archetype']}")
        cmp[catname]["guide_missing_examples"] = sorted(set(missing_names))[:15]

    json.dump({"by_class": {k: v for k, v in by_class.items()}, "guide_ids": {k: sorted(v) for k, v in guide_items.items()},
               "comparison": cmp}, open(os.path.join(DRY, "evidence", "guide_exclusive_items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("=== 局内说明书（权威）===")
    print(f"  职业数: {len(by_class)}")
    print(f"  武器提及 {sum(len(d['weapons']) for d in by_class.values())} 条 / 去重 {len(guide_items['weapon'])} 件")
    print(f"  卢恩提及 {sum(len(d['goods']) for d in by_class.values())} 条 / 去重 {len(guide_items['goods'])} 件")
    print(f"  防具提及 {sum(len(d['protectors']) for d in by_class.values())} 条 / 去重 {len(guide_items['protector'])} 件")
    print()
    print("=== 与当前候选的对比 ===")
    for catname, v in cmp.items():
        print(f"  {catname}: 说明书 {v['guide']} 件 | 候选里已收录 {v['in_basis']} 件 | 说明书有但候选缺 {len(v['guide_missing_from_basis'])} 件 | 候选有但说明书没提 {v['basis_not_in_guide']} 件")
        if v["guide_missing_examples"]:
            print(f"     缺失例: {v['guide_missing_examples'][:6]}")
    print()
    print("=== 各职业（说明书条数 / 武器 / 卢恩 / 防具 / 护甲偏好）===")
    for cls, d in sorted(by_class.items(), key=lambda kv: kv[1]["entries"][0]):
        print(f"  {cls:<8} 条目{','.join(d['entries']):<22} 武器{len(d['weapons']):>2} 卢恩{len(d['goods']):>2} 防具{len(d['protectors']):>2}  {d['armor_style'][:26]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
