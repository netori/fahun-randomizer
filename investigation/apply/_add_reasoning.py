# _add_reasoning.py — 给引擎加"合理度 0-100%"：在同域同部位的前提下，控制
#   · 跨档次（等级）允许程度
#   · 跨流派（近战/法师/祷告…）允许程度
#   100% = 只和"同流派 + 同档次"的换；0% = 无视流派与档次（仅保留大类与部位一致，保证不会把护甲换成卢恩）
import os, re, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()
if "_coherence_apply" in s:
    print("  引擎已含合理度支持，跳过"); sys.exit(0)

HELPER = '''

# ─────────────────────────────────────────────────────────────
# 合理度（coherence）：0~1
#   1.0 → 只在「同大类 + 同部位 + 同流派 + 同档次」之间互换（最合理）
#   0.0 → 无视流派与档次（仍保持大类与部位一致，避免把护甲换成卢恩）
# 档次来源：卢恩取草表档位（学徒/熟练/精通/大师…）；护甲/武器按掉落地区推进度推。
_REGION_TIER = {
    "limgrave": 0, "weeping peninsula": 0, "stormveil": 0, "castle morne": 0, "mistwood": 0,
    "murkwater": 0, "tombsward": 0, "highroad": 0, "groveside": 0, "dragon-burnt": 0,
    "liurnia": 1, "raya lucaria": 1, "ainsel": 1, "siofra": 1, "kingsrealm": 1, "caria": 1,
    "caelid": 2, "sellia": 2, "redmane": 2, "mt. gelmir": 2, "volcano manor": 2, "gelmir": 2,
    "altus plateau": 2, "shaded castle": 2, "leyndell": 3, "subterranean shunning": 3,
    "mountaintops": 3, "consecrated snowfield": 3, "mohgwyn": 3, "deeproot": 3, "nokron": 3,
    "haligtree": 4, "elphael": 4, "farum azula": 4, "ashen capital": 4, "miquella": 4,
}
_RUNE_TIER = [("微光", 0), ("新手", 0), ("学徒", 1), ("熟练", 2), ("精通", 3), ("大师", 4), ("幽影", 4)]


def _tier_of_unit(u):
    """0..4；取不到时给 2（中位）"""
    if u.get("domain") == "rune":
        sp = u.get("subpool", "")
        for name, t in _RUNE_TIER:
            if name in sp:
                return t
        # 草表没写档位时，用卢恩数值（id 段）粗分
        try:
            iid = int(u.get("id") or 0)
        except Exception:
            iid = 0
        return 0 if iid < 8300 else 1 + min(3, (iid - 8300) // 60)
    tiers = []
    for c in u.get("cells") or []:
        rn = (c.get("row_name") or "").lower()
        m = re.match(r"\\[([^\\]]+)\\]", rn)
        head = m.group(1) if m else rn
        best = None
        for k, t in _REGION_TIER.items():
            if k in head:
                best = t if best is None else max(best, t)
        if best is not None:
            tiers.append(best)
    if not tiers:
        return 2
    tiers.sort()
    return tiers[len(tiers) // 2]          # 取中位，避免被单个终盘格子拉高


def _coherence_apply(pools, cfg):
    """按合理度合并池：100% 严格同档同流派；越低越放开"""
    c = float(cfg.get("coherence", 1.0))
    c = min(1.0, max(0.0, c))
    if c >= 0.999:
        return pools
    # 档位合并跨度：c=1 → 0（不并档）；c=0 → 5（全并）
    span = int(round((1 - c) * 4)) + (1 if c < 0.5 else 0)
    merge_arch = c < 0.5
    out = {}
    for key, meta in pools.items():
        units = meta.get("units") or []
        if not units:
            out[key] = meta
            continue
        groups = {}
        for u in units:
            dom = u.get("domain")
            part = (u.get("subpool") or "").split("@")[0]
            arch = "any" if merge_arch else u.get("arch")
            tier = _tier_of_unit(u)
            tbucket = tier // max(1, span) if span else tier
            k2 = (dom, part, arch, tbucket)
            groups.setdefault(k2, []).append(u)
        for k2, us in groups.items():
            nk = f"{key}｜合理度{'并档' if span else '同档'}{k2[3]}{'·混流派' if merge_arch else ''}"
            if nk in out:
                out[nk]["units"].extend(us)
            else:
                out[nk] = {"units": us, "meta": meta.get("meta", {})}
    return out
'''
s = s.replace("\ndef run(items, cfg, seed=None):", HELPER + "\n\ndef run(items, cfg, seed=None):", 1)
s = s.replace("    pools = build_pools(items, cfg)", "    pools = _coherence_apply(build_pools(items, cfg), cfg)", 1)
# 给单元补 id/domain，方便 _tier_of_unit 用
s = s.replace('''        items[key] = {"name": name_of[key], "arch": v.most_common(1)[0][0], "cat": cat,''',
              '''        items[key] = {"name": name_of[key], "arch": v.most_common(1)[0][0], "cat": cat,
                      "id": key[1],''', 1)
open(ENGINE, "w", encoding="utf-8").write(s)
print("  已写入合理度支持 →", os.path.basename(ENGINE))

# 用 guide 草表补上卢恩档位（guide 表里被写成占位符 "tier"）
DRAFT = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "class_candidate_draft.csv")
GDRAFT = os.path.join(os.path.dirname(DRAFT), "guide_candidate_draft.csv")
if os.path.exists(GDRAFT) and os.path.exists(DRAFT):
    import csv
    tier_of = {}
    for r in csv.DictReader(open(DRAFT, encoding="utf-8-sig")):
        sp = r.get("subpool_proposal", "")
        if sp and ":" in sp and "@" in sp and "tier" not in sp and "?" not in sp:
            tier_of[(r["category"], r["matched_id"])] = sp
    rows = list(csv.DictReader(open(GDRAFT, encoding="utf-8-sig")))
    fixed = 0
    for r in rows:
        k = (r["category"], r["matched_id"])
        if "rune:tier@" in r.get("subpool_proposal", "") and k in tier_of:
            r["subpool_proposal"] = tier_of[k]; fixed += 1
    if fixed:
        with open(GDRAFT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    print(f"  guide 草表补档位 {fixed} 行")
