# list_excluded.py — 列出被"可同时拿多件"规则排除的物品
import collections, csv, json, os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
REV = os.path.join(ROOT, "investigation", "randomization-catalog-review")
WB = os.path.join(ROOT, "investigation", "weapon-baseline")


def fmg(*ps):
    import xml.etree.ElementTree as ET
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def main():
    ex = json.load(open(os.path.join(REV, "evidence", "multicopy_exclude.json"), encoding="utf-8"))["excluded"]
    names = {}
    for c, t in (("protector", fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                                   os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))),
                 ("weapon", fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                                os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))),
                 ("goods", fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                               os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml")))):
        for i, n in t.items():
            names.setdefault(f"{c}:{i}", n)

    # 计划里被剔除的物品
    def load(p):
        return {r["old"] for r in csv.DictReader(open(os.path.join(APPLY, "out", p), encoding="utf-8-sig"))
                if r["old"] != r["new"]}
    dropped = load("plan_guide_default.csv") - load("plan_guide_v2.csv")

    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    CAP = {"3": "protector", "2": "weapon", "1": "goods"}
    cells = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            c = CAP.get(str(s["category"]))
            if c:
                cells[f"{c}:{s['item_id']}"].append(L.get("row_name", "") or f"{L['table']}:{L['lot_id']}")

    print(f"=== 被排除的物品（计划里被剔除的 {len(dropped)} 个）===")
    rows = []
    for k in sorted(dropped, key=lambda x: (x.split(":")[0], int(x.split(":")[1]))):
        nm = names.get(k, k)
        cl = ex.get(k, {})
        locs = " ｜ ".join(x[:34] for x in cells.get(k, [])[:4])
        rows.append((nm, k, cl.get("cells", len(cells.get(k, []))), locs))
        print(f"  {nm:<18} {k:<18} {cl.get('cells','?'):>2} 格 | {locs}")
    json.dump(rows, open(os.path.join(APPLY, "logs", "excluded_items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n  → logs/excluded_items.json（{len(rows)} 条）")
    # 分类统计
    cat = collections.Counter(k.split(":")[0] for k in dropped)
    print(f"  类别分布: {dict(cat)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
