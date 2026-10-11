# list25.py — 列出最终被剔除的 25 件，并给出"世界来源 + flag"证据（NPC/剧情行单列）
import csv, json, os, re
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
REV = os.path.join(ROOT, "investigation", "randomization-catalog-review")
WB = os.path.join(ROOT, "investigation", "weapon-baseline")
TREE = os.path.join(APPLY, "work", "orig", "regulation-bin")
CAP = {"1": "goods", "2": "weapon", "3": "protector"}
REGIONS = ("ld -", "limgrave", "weeping peninsula", "liurnia", "caelid", "altus plateau", "mt. gelmir",
           "mountaintops", "consecrated snowfield", "greyoll", "moonlight altar", "capital outskirts",
           "leyndell", "nokron", "ainsel", "deeproot", "mohgwyn", "farum azula", "elphael", "haligtree",
           "shadow keep", "devonia", "frenzy town", "subterranean", "volcano manor", "academy", "castle ",
           "church", "cave", "ruins", "catacomb", "depths", "dungeon", "manor", "keep", "fort ", "town",
           "grave ", "evergaol", "plateau", "sol", "aeonia", "sellia", "ordina", "divine tower",
           "sage's cave", "chapel", "stranded", "gaol", "forbidden lands", "murkwater", "seaside",
           "stormveil", "highroad", "dragonbarrow", "mistwood", "siofra", "auluria", "shunning-grounds",
           "belfries", "nokstella", "mausoleum", "tunnel", "mine", "lakes", "snowfield", "field -",
           "ruin-strewn", "bonny gaol", "belurat", "rauh", "scadu", "west of", "south of", "north of",
           "east of", "avenue", "terrace", "rooftop", "bridge", "gate", "cliffside", "woods", "highway",
           "resort", "library", "fissure", "midra")


def fmg(*ps):
    d = {}
    for p in ps:
        if os.path.exists(p):
            for e in ET.parse(p).getroot().findall(".//text"):
                if e.text:
                    d[e.get("id")] = e.text
    return d


def is_world(name):
    m = re.match(r"^\[([^\]]+)\]", (name or "").strip())
    if not m:
        return True
    head = " " + m.group(1).lower() + " "
    return any(r in head for r in REGIONS)


def main():
    names = {}
    for c, t in (("protector", fmg(os.path.join(CAT, "evidence", "xml", "ProtectorName.fmg.xml"),
                                   os.path.join(CAT, "evidence", "xml", "ProtectorName_dlc01.fmg.xml"))),
                 ("weapon", fmg(os.path.join(WB, "evidence", "xml", "WeaponName.fmg.xml"),
                                os.path.join(WB, "evidence", "xml", "WeaponName_dlc01.fmg.xml"))),
                 ("goods", fmg(os.path.join(CAT, "evidence", "xml", "GoodsName.fmg.xml"),
                               os.path.join(CAT, "evidence", "xml", "GoodsName_dlc01.fmg.xml")))):
        for i, n in t.items():
            names.setdefault(f"{c}:{i}", n)

    def olds(p):
        return {r["old"] for r in csv.DictReader(open(os.path.join(APPLY, "out", p), encoding="utf-8-sig"))
                if r["old"] != r["new"]}
    dropped = sorted(olds("plan_guide_default.csv") - olds("plan_guide_v2.csv"),
                     key=lambda x: (x.split(":")[0], int(x.split(":")[1])))

    src = {}
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
                src.setdefault(k, {}).setdefault(nm.lower(), {"show": nm, "flag": a.get("getItemFlagId", "0")})

    out = []
    print(f"=== 最终剔除 {len(dropped)} 件 ===")
    for k in dropped:
        world = {nm: d for nm, d in src.get(k, {}).items() if is_world(d["show"])}
        npc = {nm: d for nm, d in src.get(k, {}).items() if not is_world(d["show"])}
        wl = " ｜ ".join(f"{d['show'][:46]}（flag {d['flag']}）" for d in world.values())
        print(f"\n  {names.get(k, k)}  [{k}]  世界来源 {len(world)} 处" + (f" + NPC/剧情 {len(npc)} 行" if npc else ""))
        for d in world.values():
            print(f"      世界: {d['show'][:62]}  flag={d['flag']}")
        for d in list(npc.values())[:3]:
            print(f"      NPC : {d['show'][:62]}  flag={d['flag']}")
        out.append({"item": k, "name": names.get(k, k), "world": [d["show"] for d in world.values()],
                    "npc": [d["show"] for d in npc.values()],
                    "world_flags": [d["flag"] for d in world.values()]})
    json.dump(out, open(os.path.join(APPLY, "logs", "excluded25.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n  → logs/excluded25.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
