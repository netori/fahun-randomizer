# audit_excluded_rows.py — 把被排除物品的"格子"摊开成原始 Lot 行，看看是不是真的两处
import collections, json, os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
REV = os.path.join(ROOT, "investigation", "randomization-catalog-review")
TREE = os.path.join(APPLY, "work", "orig", "regulation-bin")
CAP = {"1": "goods", "2": "weapon", "3": "protector"}


def main():
    ex = json.load(open(os.path.join(REV, "evidence", "multicopy_exclude.json"), encoding="utf-8"))["excluded"]
    import csv
    def olds(p):
        return {r["old"] for r in csv.DictReader(open(os.path.join(APPLY, "out", p), encoding="utf-8-sig")) if r["old"] != r["new"]}
    focus = olds("plan_guide_default.csv") - olds("plan_guide_v2.csv")   # 只关心"计划里被剔除"的
    ex = {k: v for k, v in ex.items() if k in focus}
    rows = {}
    for t in ("ItemLotParam_map", "ItemLotParam_enemy"):
        s = open(os.path.join(TREE, t + ".param.xml"), encoding="utf-8-sig").read()
        for m in re.finditer(r'<row\b([^>]*?)/>', s):
            a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            rows[(t, a.get("id", ""))] = a

    # 物品 → 出现在哪些 Lot 行（按行去重）
    src = collections.defaultdict(set)
    for (t, rid), a in rows.items():
        for n in range(1, 9):
            iid, cat = a.get(f"lotItemId{n:02d}"), a.get(f"lotItemCategory{n:02d}")
            if not iid or iid == "0" or not cat or cat == "0":
                continue
            c = CAP.get(cat)
            if c:
                src[f"{c}:{iid}"].add((t, rid, a.get("getItemFlagId", "0")))

    out = []
    print("=== 被排除物品的原始来源行（按行名去重）===")
    for item in sorted(ex, key=lambda x: (x.split(":")[0], int(x.split(":")[1]))):
        cells = sorted(src.get(item, []))
        names = collections.Counter()
        for t, rid, fl in cells:
            nm = rows[(t, rid)].get("name", "") or f"{t}:{rid}"
            names[nm] += 1
        uniq = len(names)
        flag = "⚠️ 同名重复" if uniq < len(cells) else ""
        out.append({"item": item, "rows": len(cells), "uniq_names": uniq,
                    "flags": sorted({fl for _t, _r, fl in cells}),
                    "names": dict(names)})
        mark = "⚠️" if uniq < len(cells) else "  "
        print(f"{mark} {item:<20} 行 {len(cells):<3} 不同行名 {uniq:<3} | {list(names)[0][:52]}")
    json.dump(out, open(os.path.join(APPLY, "logs", "excluded_rows.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    dup = [x for x in out if x["uniq_names"] < x["rows"]]
    print(f"\n  共 {len(out)} 件（计划里被剔除）| 其中同名重复 {len(dup)} 件")
    only_one_name = [x for x in out if x["uniq_names"] == 1]
    print(f"  只有一种行名的: {len(only_one_name)} 件 → {[x['item'] for x in only_one_name][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
