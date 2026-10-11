# probe9.py — 深挖剩下 9 件剔除物品的两个来源行：行名/flag/数量/同行槽位/说明书怎么写
import csv, json, os, re
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
TREE = os.path.join(APPLY, "work", "orig", "regulation-bin")
CAP = {"1": "goods", "2": "weapon", "3": "protector"}
TARGETS = ["protector:2000000", "protector:2000100", "protector:2000200", "protector:2000300",
           "protector:350000", "protector:350100", "protector:350200", "protector:350300",
           "weapon:66530000"]


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def main():
    WB = os.path.join(ROOT, "investigation", "weapon-baseline")
    names = {}
    for c, t in (("protector", fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                                   os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))),
                 ("weapon", fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                                os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))),
                 ("goods", fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                               os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml")))):
        for i, n in t.items():
            names.setdefault(f"{c}:{i}", n)

    rows = {}
    for t in ("ItemLotParam_map", "ItemLotParam_enemy"):
        s = open(os.path.join(TREE, t + ".param.xml"), encoding="utf-8-sig").read()
        for m in re.finditer(r'<row\b([^>]*?)/>', s):
            a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            rows[(t, a.get("id", ""))] = a

    # 说明书里每件物品的行
    guide = {}
    for path, tag in ((os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"), "原文"),):
        s = open(path, encoding="utf-8-sig").read()
        import html as _h
        for eid in list(range(8800, 8827)) + list(range(8870, 8896)):
            m = re.search(r'<text id="%d">(.*?)</text>' % eid, s, re.S)
            if not m:
                continue
            for x in re.finditer(r'<font color="#[0-9A-Fa-f]{6}">([^<]+)</font>\s*-\s*([^<\n]+)', _h.unescape(m.group(1))):
                guide.setdefault(x.group(1).strip(), []).append((eid, x.group(2).strip()))

    for key in TARGETS:
        cat, iid = key.split(":")
        print(f"\n{'='*78}\n{names.get(key, key)}  [{key}]")
        print(f"  说明书: {guide.get(names.get(key, ''), '（没有行）')}")
        for (t, rid), a in rows.items():
            hit = [n for n in range(1, 9)
                   if a.get(f"lotItemId{n:02d}") == iid and a.get(f"lotItemCategory{n:02d}") == {"protector": "3", "weapon": "2", "goods": "1"}[cat]]
            if not hit:
                continue
            slots = []
            for n in range(1, 9):
                ii, cc = a.get(f"lotItemId{n:02d}"), a.get(f"lotItemCategory{n:02d}")
                if ii and ii != "0" and cc and cc != "0":
                    slots.append(f"s{n}:{cc}:{ii}(x{a.get(f'lotItemNum{n:02d}','?')})")
            print(f"  ── {t}:{rid}  命中槽 {hit}")
            print(f"     行名    : {(a.get('name','') or '(无)')[:66]}")
            print(f"     flag    : getItemFlagId={a.get('getItemFlagId')}  eventFlagId={a.get('eventFlagId')}  "
                  f"clearedFlagId={a.get('clearedEventFlagId')}")
            print(f"     其他槽  : {slots if len(slots) > 1 else '（仅此一件）'}")
        # 该物品在计划里的行
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
