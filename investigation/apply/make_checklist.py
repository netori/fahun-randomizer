# make_checklist.py — 生成游戏内核对清单（中文名 + 位置 + 原本是什么→现在是什么）
import csv, os, re, sys
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
WB = os.path.join(ROOT, "investigation", "weapon-baseline")
TREE = os.path.join(APPLY, "work", "pilot", "regulation-bin")
TABLE_FILE = {"ItemLotParam_map": "ItemLotParam_map.param.xml",
              "ItemLotParam_enemy": "ItemLotParam_enemy.param.xml",
              "ShopLineupParam": "ShopLineupParam.param.xml"}


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def main():
    names = {"protector": fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml")),
             "weapon": fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"), os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml")),
             "goods": fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"), os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml"))}
    def cn(key):
        cat, iid = key.split(":")
        return names.get(cat, {}).get(iid, f"<{key} 无中文名>")

    # XML 行名（位置）
    rowname = {}
    for table, f in TABLE_FILE.items():
        p = os.path.join(TREE, f)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8-sig").read()
        for m in re.finditer(r'<row\b[^>]*\bid="([^"]+)"[^>]*?(?:\bname="([^"]*)")?[^>]*?/>', s):
            pass
        for m in re.finditer(r'<row\b([^>]*?)/>', s):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            rowname[(table, attrs.get("id", ""))] = attrs.get("name", "")

    rows = [r for r in csv.DictReader(open(os.path.join(APPLY, "out", "plan_pilot.csv"), encoding="utf-8-sig"))]
    bypool = {}
    for r in rows:
        bypool.setdefault(r["pool"], []).append(r)
    out = ["# 法魂随机化 · 首测核对清单", "",
           f"- 来源置换表：`out/plan_pilot.csv`（{len(rows)} 行 / {len(bypool)} 个池）",
           "- 判定方式：进游戏到对应位置，看拿到的是不是「现在」这一列的东西。",
           "- 说明：首测只应用了这 4 个池；同一个池里的格子是**整池互换**的（排列有效），其余格子这次不动。", ""]
    for pool, rs in sorted(bypool.items()):
        out.append(f"## {pool}（{len(rs)} 格）")
        out.append("")
        out.append("| 位置（游戏内） | 原本是 | 现在应该是 | 表/行 |")
        out.append("|---|---|---|---|")
        for r in sorted(rs, key=lambda x: (x["source_table"], x["row_id"])):
            loc = rowname.get((r["source_table"], r["row_id"]), r["row_name"]) or "（无位置名）"
            if r["source_table"] == "ShopLineupParam":
                loc = "商店：" + loc
            out.append(f"| {loc} | {cn(r['old'])} | **{cn(r['new'])}** | {r['source_table']}:{r['row_id']}{(':' + r['slot']) if r['slot'] else ''} |")
        out.append("")
    txt = "\n".join(out)
    dst = os.path.join(APPLY, "out", "首测核对清单.md")
    open(dst, "w", encoding="utf-8").write(txt)
    print(f"清单写出 → {dst}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
