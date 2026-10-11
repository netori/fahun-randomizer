# analyze_sets.py — 从 xlsx 线索(已匹配真实 ID)中筛"四部位套装"与"近战散件"候选
# 只读：读取 evidence/armor_id_candidates.json（xlsx+真表匹配结果）与 evidence/lot_reward_index.json（奖励槽索引）
# 输出：evidence/set_candidates.json + 屏幕摘要
import json, os, re, collections, sys

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")

HEAD = ["helm", "helmet", "hood", "mask", "circlet", "hat", "crown", "cowl", "head"]
BODY = ["armor", "robe", "garb", "raiment", "chestplate", "cloak", "tunic", "mail"]
ARM = ["gauntlets", "gloves", "bracers", "bracelets", "manchettes", "sleeves", "arms"]
LEG = ["trousers", "greaves", "leggings", "skirt", "legs", "pants"]
CASTER = ["int", "fth", "arc", "mnd", "mind", "cast", "spell", "sorcer", "incantation", "glintstone",
          "faith", "intelligence", "fp ", "focus", "magic", "holy", "rot", "frenzy", "dragon"]
MELEE = ["str", "dex", "end", "weapon damage", "stamina", "attack", "poise", "guard", "block", "thrust", "slash"]


def norm_name(n):
    s = (n or "").strip().lower()
    for w in ["+", "’", "'"]:
        s = s.replace(w, "")
    return re.sub(r"\s+", " ", s)


def stem_of(name):
    """去掉部位后缀得到套装词干"""
    s = norm_name(name)
    for suf in sorted(HEAD + BODY + ARM + LEG, key=len, reverse=True):
        if s.endswith(" " + suf) or s.endswith(suf):
            base = s[: len(s) - len(suf)].strip()
            if base:
                return base
    return None


def flavor(text):
    t = (text or "").lower()
    c = sum(1 for k in CASTER if k in t)
    m = sum(1 for k in MELEE if k in t)
    return ("caster" if c > m else "melee" if m > c else "mixed"), c, m


def main():
    alp = json.load(open(os.path.join(EV, "armor_id_candidates.json"), encoding="utf-8"))["matched"]
    idx = json.load(open(os.path.join(EV, "lot_reward_index.json"), encoding="utf-8"))
    lot_by_item = collections.defaultdict(list)
    for L in idx["lots"]:
        for s in L["slots"]:
            lot_by_item[s["item_id"]].append({"table": L["table"], "lot_id": L["lot_id"], "slot": s["slot"],
                                              "category": s["category"], "row_name": L["row_name"],
                                              "num": s["num"], "base_point": s["base_point"],
                                              "get_item_flag_id": L["getItemFlagId"],
                                              "slot_flag": s["get_item_flag_id"], "cumulate": s["cumulate_lot_point"]})
    shop_by_item = collections.defaultdict(list)
    for s in idx["shops"]:
        shop_by_item[s["equipId"]].append(s)

    # 去重（xlsx 同名行可能重复）
    seen = {}
    for m in alp:
        k = (m["xlsx_name"], m["protector_id"])
        if k not in seen:
            seen[k] = m
    pieces = list(seen.values())
    for p in pieces:
        p["flavor"], p["c"], p["m"] = flavor(p["xlsx_text"])
        rid = int(p["protector_id"])
        p["lot_entrances"] = lot_by_item.get(rid, [])
        p["shop_entrances"] = shop_by_item.get(rid, [])
    print("去重后防具件数:", len(pieces))

    groups = collections.defaultdict(lambda: {"head": [], "body": [], "arm": [], "leg": []})
    for p in pieces:
        st = stem_of(p["xlsx_name"])
        if st and p["part"] in ("head", "body", "arm", "leg"):
            groups[st][p["part"]].append(p)

    full = {k: v for k, v in groups.items() if all(v[p] for p in ("head", "body", "arm", "leg"))}
    print("四部位齐全的套装词干:", len(full))

    cands = []
    for st, g in sorted(full.items()):
        fl = collections.Counter(p["flavor"] for p in sum(g.values(), []))
        texts = [p["xlsx_text"] for p in [g["head"][0], g["body"][0], g["arm"][0], g["leg"][0]]]
        n_with_lot = sum(1 for p in sum(g.values(), []) if p["lot_entrances"])
        cands.append({"stem": st, "flavor_counts": dict(fl), "n_pieces": sum(len(v) for v in g.values()),
                      "n_pieces_with_lot": n_with_lot,
                      "pieces": {k: [{"xlsx_name": p["xlsx_name"], "id": p["protector_id"],
                                      "zh": p["fmg_zhocn_name"], "part": p["part"], "text": p["xlsx_text"],
                                      "location": p["xlsx_location"],
                                      "lot_entrances": p["lot_entrances"], "shop_entrances": p["shop_entrances"]}
                                     for p in v] for k, v in g.items()},
                      "texts": texts})
    cands.sort(key=lambda c: (-(c["flavor_counts"].get("caster", 0)), -c["n_pieces_with_lot"]))
    json.dump({"note": "stem 由名称后缀（Helm/Armor/Gauntlets/Greaves 等）去除后得到；仅供候选，不构成套装证据",
               "caster_sets": [c for c in cands if c["flavor_counts"].get("caster", 0) >= 2],
               "all_full_sets": cands},
              open(os.path.join(EV, "set_candidates.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n=== 四部位齐全且偏施法的套装（前 12）===")
    for c in [x for x in cands if x["flavor_counts"].get("caster", 0) >= 2][:12]:
        print(f"  * {c['stem']:<26} caster={c['flavor_counts'].get('caster',0)} pieces={c['n_pieces']} with_lot={c['n_pieces_with_lot']}")
        for part in ("head", "body", "arm", "leg"):
            for p in c["pieces"][part]:
                lots = ",".join(f"{e['table'][-4:]}:{e['lot_id']}s{e['slot']}" for e in p["lot_entrances"]) or "-"
                print(f"      {part:<5} {p['xlsx_name'][:30]:<31} id={p['id']:<8} zh={p['zh'][:12]:<13} lots={lots}")

    print("\n=== 近战散件样例（效果偏 STR/DEX/END，且四部位不成套）===")
    melee = [p for p in pieces if p["flavor"] == "melee"]
    print("  近战风味件数:", len(melee))
    for p in melee[:10]:
        lots = ",".join(f"{e['lot_id']}s{e['slot']}" for e in p["lot_entrances"][:3]) or "-"
        print(f"     {p['xlsx_name'][:30]:<31} id={p['protector_id']:<8} part={p['part']:<5} text={p['xlsx_text'][:44]:<45} lots={lots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
