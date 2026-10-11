# list_excluded2.py — 输出"被排除物品"的逐来源证据（含 flag）
import collections, csv, json, os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
REV = os.path.join(ROOT, "investigation", "randomization-catalog-review")
TREE = os.path.join(APPLY, "work", "orig", "regulation-bin")
CAP = {"1": "goods", "2": "weapon", "3": "protector"}


def main():
    ex = json.load(open(os.path.join(REV, "evidence", "multicopy_exclude.json"), encoding="utf-8"))["excluded"]

    def olds(p):
        return {r["old"] for r in csv.DictReader(open(os.path.join(APPLY, "out", p), encoding="utf-8-sig"))
                if r["old"] != r["new"]}
    dropped = olds("plan_guide_default.csv") - olds("plan_guide_v2.csv")
    recovered = olds("plan_guide_v2.csv") - olds("plan_guide_default.csv")

    sources = {}
    for t in ("ItemLotParam_map", "ItemLotParam_enemy"):
        s = open(os.path.join(TREE, t + ".param.xml"), encoding="utf-8-sig").read()
        for m in re.finditer(r'<row\b([^>]*?)/>', s):
            a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            for n in range(1, 9):
                iid, cat = a.get(f"lotItemId{n:02d}"), a.get(f"lotItemCategory{n:02d}")
                c = CAP.get(cat or "")
                if not c or not iid or iid == "0":
                    continue
                k = f"{c}:{iid}"
                nm = (a.get("name", "") or "").strip() or f"{t}:{a.get('id','')}"
                sources.setdefault(k, {})
                sources[k].setdefault(nm, {"flag": a.get("getItemFlagId", "0"), "t": t, "row": a.get("id", "")})

    print(f"=== 现被排除 {len(dropped)} 件（按来源行/行名去重）===")
    rows_out = []
    for k in sorted(dropped, key=lambda x: (x.split(":")[0], int(x.split(":")[1]))):
        src = sources.get(k, {})
        rows_out.append({"item": k, "sources": len(src),
                         "detail": [{"where": nm, **v} for nm, v in src.items()]})
        short = " ｜ ".join(list(src)[:3])
        flags = sorted({v["flag"] for v in src.values()})
        print(f"  {k:<20} {len(src)} 处 | flags={flags} | {short[:74]}")
    print(f"\n  恢复入池（原本被误剔，其实是同一处的重复行）: {sorted(recovered)}")
    json.dump(rows_out, open(os.path.join(APPLY, "logs", "excluded_evidence.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("  → logs/excluded_evidence.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
