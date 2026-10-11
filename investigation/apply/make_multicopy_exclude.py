# make_multicopy_exclude.py — 生成"可同时拿多件"的排除表（用户规则）
#
# 判据（来自 Lot 表的 getItemFlagId）：
#   · 物品的多个格子**共用同一个非零 flag** → 互斥单件：拿了一个，其他地区就没了 → **保留随机**
#   · 物品的多个格子 flag 各不相同或为空     → 可以同时拿多件            → **排除，不随机**
#   · 只有一个格子的物品                                              → 保留
import collections, json, os, re, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
TREE = os.path.join(APPLY, "work", "orig", "regulation-bin")
CAP = {"1": "goods", "2": "weapon", "3": "protector"}


def main():
    cells = collections.defaultdict(list)
    for t in ("ItemLotParam_map", "ItemLotParam_enemy"):
        s = open(os.path.join(TREE, t + ".param.xml"), encoding="utf-8-sig").read()
        for m in re.finditer(r'<row\b([^>]*?)/>', s):
            a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            for n in range(1, 9):
                iid, cat = a.get(f"lotItemId{n:02d}"), a.get(f"lotItemCategory{n:02d}")
                if not iid or iid == "0" or not cat or cat == "0":
                    continue
                c = CAP.get(cat)
                if c:
                    cells[f"{c}:{iid}"].append({"t": t, "row": a.get("id", ""), "slot": n,
                                                "flag": a.get("getItemFlagId", "0"),
                                                "name": (a.get("name", "") or "").strip()})

    # 地区词表：世界拾取行的括号头里一定含地区名；NPC/Boss 行只有人名（注意 PlaceName.fmg 里也装 Boss 名，不能用它）
    REGIONS = ("ld -", "limgrave", "weeping peninsula", "liurnia", "caelid", "altus plateau", "mt. gelmir",
               "mountaintops", "consecrated snowfield", "greyoll", "moonlight altar", "capital outskirts",
               "leyndell", "nokron", "ainsel", "deeproot", "mohgwyn", "farum azula", "elphael", "haligtree",
               "shadow keep", "devonia", "frenzy town", "subterranean", "volcano manor", "academy", "castle ",
               "church", "cave", "ruins", "catacomb", "depths", "dungeon", "manor", "keep", "fort ", "town",
               "grave ", "evergaol", "plateau", "sol", "aeonia", "sellia", "ordina", "divine tower",
               "sage's cave", "chapel", "stranded", "gaol", "forbidden lands", "murkwater", "seaside",
               "stormveil", "highroad", "dragonbarrow", "mistwood", "siofra", "auluria", "shunning-grounds",
               "belfries", "nokstella", "mausoleum", "catacombs", "tunnel", "mine", "lakes", "snowfield",
               "field -", "ruin-strewn", "bonny gaol", "belurat", "rauh", "scadu", "church of", "west of",
               "south of", "north of", "east of", "avenue", "terrace", "rooftop", "bridge", "gate",
               "cliffside", "woods", "highway", "resort", "library", "library", "fissure", "midra")

    def is_world(name):
        """世界拾取行：括号头里含地区名 → True；否则（人名）→ False"""
        m = re.match(r"^\[([^\]]+)\]", (name or "").strip())
        if not m:
            return True                    # 无括号头（如 "Set of Solitude"、"ItemLotParam_map:106210"）按世界处理
        head = " " + m.group(1).lower() + " "
        return any(r in head for r in REGIONS)

    # 固定行（剧情给与/返还）不计入来源
    REV2 = os.path.join(ROOT, "investigation", "randomization-catalog-review", "evidence", "fixed_cells.json")
    fixed = set(json.load(open(REV2, encoding="utf-8"))["fixed"]) if os.path.exists(REV2) else set()

    # 来源 = Lot 行（不是槽位）；同一行名视为同一处（合并）
    exclude, keep_mutex, single = {}, {}, 0
    for item, cl in cells.items():
        cl = [x for x in cl if f"{x['t']}:{x['row']}" not in fixed]
        sources = {}
        for x in cl:
            nm = (x["name"] or f"{x['t']}:{x['row']}").strip().lower()   # 忽略大小写差异
            sources.setdefault(nm, {"t": x["t"], "rows": set(), "flags": set()})
            sources[nm]["rows"].add(x["row"])
            sources[nm]["flags"].add(x["flag"])
        # NPC/剧情行：只算作一个来源（用户指正：任务基本只在一个节点给装备）
        world = {k: v for k, v in sources.items() if is_world(k)}
        npc = {k: v for k, v in sources.items() if not is_world(k)}
        if len(world) + (1 if npc else 0) <= 1:
            single += 1
            continue
        if npc:                                   # NPC/剧情行不计入来源
            sources = dict(world)
            if len(sources) <= 1:
                single += 1
                continue
        flags = {f for v in sources.values() for f in v["flags"]}
        if len(flags) == 1 and next(iter(flags)) not in ("0", ""):
            keep_mutex[item] = {"sources": len(sources), "flag": next(iter(flags))}
        else:
            exclude[item] = {"sources": len(sources), "flags": sorted(flags),
                             "where": [(f"{v['t']}:{sorted(v['rows'])[0]}" if v.get("t") else "(NPC/剧情)")
                                       for v in list(sources.values())[:6]]}

    # 人工裁决：强制保留（放回池子）
    _fk = os.path.join(ROOT, "investigation", "randomization-catalog-review", "evidence", "force_keep.json")
    FK = set(json.load(open(_fk, encoding="utf-8"))["keep"]) if os.path.exists(_fk) else set()
    forced_back = sorted(set(exclude) & FK)
    for k in forced_back:
        exclude.pop(k, None)

    # 套装级传播：同套装（id 去掉后三位 = 同族）里只要有 1 件被排除，整套一起排除
    fam = collections.defaultdict(set)
    for k in list(keep_mutex) + list(exclude) + list(FK):
        cat, iid = k.split(":")
        if cat in ("protector", "weapon") and len(iid) >= 6:   # 只有护甲/武器才有套装族
            fam[f"{cat}:{iid[:-3]}"].add(k)
    set_excluded = []
    for f, members in fam.items():
        if any(m in exclude for m in members) and not (members & FK):
            for m in members:
                if m not in exclude:
                    exclude[m] = {"sources": 0, "flags": [], "where": ["(套装级传播：同套装的另一件被排除)"]}
                    set_excluded.append(m)

    out = {"rule": "多格物品若各格 getItemFlagId 不同或为空 → 可同时拿多件 → 排除",
           "generated_from": "work/orig/regulation-bin/{ItemLotParam_map,ItemLotParam_enemy}.param.xml",
           "counts": {"single": single, "mutex_kept": len(keep_mutex), "excluded": len(exclude)},
           "rule_detail": "来源按 Lot 行计并同名合并；NPC/剧情行合并为一个来源；固定行不计。排除 = 有效来源≥2 且 flag 不同或为空",
           "excluded": exclude, "mutex_kept": keep_mutex}
    os.makedirs(os.path.join(CAT, "evidence"), exist_ok=True)
    json.dump(out, open(os.path.join(CAT, "evidence", "multicopy_exclude.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("=== 可多件排除表 ===")
    print(f"  单一来源 {single} | 互斥多来源（保留） {len(keep_mutex)} | 可同时多件（排除） {len(exclude)} | 固定行 {len(fixed)}")
    print(f"  人工裁决放回 {len(forced_back)} 件 | 套装级传播新增排除 {len(set_excluded)} 件: {set_excluded}")
    print(f"  → evidence/multicopy_exclude.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
