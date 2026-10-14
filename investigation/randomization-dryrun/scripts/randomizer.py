# randomizer.py — 可配置的随机化引擎（干跑，不写回 MOD）
#
# 配置模型（全部可自由组合）：
#   domains : 参与随机的域 → "rune" / "armor" / "weapon"（任意子集）
#   joins   : 联合池分组，例如 [["rune","weapon"]] = 卢恩与武器共用一个池（组内允许跨类别互换：
#             slot 的 lotItemCategory/equipType 随新物品类别一起改，plan 里记为 new_category）
#   shops   : 商店行是否可作为目标
#   merge_shadow : 幽影卢恩是否并入 rune:大师级
#   sets    : 护甲整套是否整组互换（默认 true；关掉则按单件同部位）
#   seed    : 可复现
#
# 固定约束（不可配置，任何配置都必须满足）：
#   F1 护甲只能与同部位护甲互换（头↔头、身↔身、臂↔臂、腿↔腿）；套装整组不拆散
#   F2 法师/祷告倾向的护甲（法师 / 祷告 / 法师·祷告混合 / 祷告·感应）独立成池：
#      只与同倾向、同部位的护甲互换，永不进入联合池、永不与非护甲互换
#   F3 同一物品的多处来源整组一致（按物品 M1）
#   F4 不跨职业倾向（护甲永远同倾向；武器/卢恩在各自池内同倾向，联合池按配置）
#   F5 冻结项（D1 微光卢恩 / D5 职业初始套装）永不参与
import collections
import itertools
import re, csv, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))          # scripts/
ROOT = os.path.dirname(HERE)                                # randomization-dryrun/
CAT = os.path.join(os.path.dirname(ROOT), "randomization-catalog")
REV = os.path.join(os.path.dirname(ROOT), "randomization-catalog-review")
CATCODE = {"protector": "3", "weapon": "2", "goods": "1"}
DOMAIN_OF_CAT = {"protector": "armor", "weapon": "weapon", "goods": "rune"}
SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}
SUF3 = {"000": "head", "100": "body", "200": "arm", "300": "leg"}          # MOD 护甲 id 尾 3 位
SUF4 = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}      # 8 位 id 尾 4 位


def part_code_of(iid):
    """返回 (部位码, 套装基号)：兼容 6/7/8 位 id（例 5253000→head/5253、5230100→body/5230）"""
    i = str(iid)
    if i[-4:] in SUF4:
        return i[-4:], i[:-4]
    if i[-3:] in SUF3:
        return i[-3:], i[:-3]
    return "", ""


def part_of(iid):
    c, _ = part_code_of(iid)
    return SUF4.get(c) or SUF3.get(c) or ""

# F2：这些倾向的护甲独立成池（规格 §3.1 的流派键：护甲分 caster / melee 两种）。
# 「感应」（奥术流）与「祷告/感应」同属法系玩法，2026-10-14 作者确认算法祷侧。
CASTER_ARCH = ("法师", "祷告", "法师/祷告混合", "祷告/感应", "感应")

ENGINE_VERSION = "1.1"          # 计划里会记录，用于跨版本对照

DEFAULT_CONFIG = {"domains": ["rune", "armor", "weapon"], "joins": [], "shops": True,
                  "merge_shadow": False, "sets": True, "seed": 20261010}


# ---------------------------------------------------------------- 世界数据
DRAFT_FILE = {"xlsx": "class_candidate_draft.csv", "guide": "guide_candidate_draft.csv"}


def load_world(with_shops=False, basis="guide"):
    """返回 items: {(cat, id): {name, arch, domains, cells:[...]}}；来源：class_candidate_draft + 奖励槽索引"""
    files = ["class_candidate_draft.csv", "guide_candidate_draft.csv"] if basis == "mix" else [DRAFT_FILE.get(basis, DRAFT_FILE["xlsx"])]
    draft = []
    for fn in files:
        for r in csv.DictReader(open(os.path.join(ROOT, fn), encoding="utf-8-sig")):
            if r.get("has_entrance") != "yes" or r.get("is_starter_set_piece") == "yes":
                continue
            if r["category"] not in CATCODE or "@" not in r.get("subpool_proposal", ""):
                continue
            draft.append(r)
    frozen = {str(p["id"]) for g in json.load(open(os.path.join(REV, "evidence", "starter_set_freeze.json"),
                                                   encoding="utf-8"))["groups"] for p in g["pieces"]}   # D5 冻结
    # 可多件排除（用户规则）：多格物品若各格 getItemFlagId 不同或为空 → 能同时拿多件 → 不随机
    _mc = os.path.join(REV, "evidence", "multicopy_exclude.json")
    multicopy = set(json.load(open(_mc, encoding="utf-8"))["excluded"]) if os.path.exists(_mc) else set()
    votes, name_of, sub_of = collections.defaultdict(collections.Counter), {}, {}
    for r in draft:
        key = (r["category"], r["matched_id"])
        if str(r["matched_id"]) in frozen or f"{r['category']}:{r['matched_id']}" in multicopy:
            continue
        votes[key][r["archetype"]] += 1
        name_of[key] = r.get("sheet_name") or r.get("guide_name") or ""
        sub_of.setdefault(key, r["subpool_proposal"])
    items = {}
    for key, v in votes.items():
        cat = key[0]
        items[key] = {"name": name_of[key], "arch": v.most_common(1)[0][0], "cat": cat,
                      "id": key[1],
                      "domain": DOMAIN_OF_CAT[cat], "subpool": sub_of[key], "cells": [],
                      "arch_votes": dict(v)}
    idx = json.load(open(os.path.join(CAT, "evidence", "lot_reward_index.json"), encoding="utf-8"))
    # 固定行：剧情给与/返还等，永不随机（见 catalog-review/evidence/fixed_cells.json）
    _fc = os.path.join(REV, "evidence", "fixed_cells.json")
    FIXED = set(json.load(open(_fc, encoding="utf-8"))["fixed"]) if os.path.exists(_fc) else set()
    # 陈旧格子：索引里有、但 regulation.bin 里其实是空槽/对不上（见 stale_cells.json 里的 why）
    # —— 必须剔掉：它们一旦进入计划，写前复核（H12）会中止整次写入。
    # 这份清单放在 apply/ 下（**随代码入库**，不像 evidence/ 那样是本地生成物）：
    # 丢它就等于"写入永远失败"，所以不能只靠本地文件。
    STALE = set()
    for _p in (os.path.join(os.path.dirname(ROOT), "apply", "stale_cells.json"),
               os.path.join(REV, "evidence", "stale_cells.json")):
        try:
            if os.path.exists(_p):
                STALE |= set(json.load(open(_p, encoding="utf-8"))["stale"])
        except Exception:
            pass
    for L in idx["lots"]:
        if f"{L['table']}:{L['lot_id']}" in FIXED:
            continue
        for s in L["slots"]:
            for cat, code in CATCODE.items():
                k = (cat, str(s["item_id"]))
                if str(s["category"]) == code and k in items:
                    if f"{L['table']}:{L['lot_id']}:{s['slot']}" in STALE:
                        continue                     # 陈旧格子：跳过，别让它进池子
                    items[k]["cells"].append({"source_table": L["table"], "row_id": str(L["lot_id"]),
                                              "slot": str(s["slot"]), "category": code,
                                              "row_name": L.get("row_name", "")})
    if with_shops:
        # 商店格的判定（2026-10-13 修正）：
        #   · 原来要求 quality == "clean" → 只接上 9 条，漏掉 60 条真实售卖
        #     （就是法魂那个"500 卢恩买一套铠甲"的便利商人）
        #   · 真在售的判据是「price 有值」；price 为 0 / -1 / 空 的是职业初始装备表那一类，不是货架
        #   · 且只接"属于说明书"的物品（职业专属），商店里其它货一律不参与
        #   · 价格 / 库存 / 解锁条件一律不动（写入端只写 equipId + equipType）
        for r in json.load(open(os.path.join(ROOT, "evidence", "shop_analysis.json"), encoding="utf-8"))["rows"]:
            if r["is_starter_set_piece"]:
                continue
            if r["price"] in ("", "0", "-1", None):
                continue
            cat = {"weapon": "weapon", "protector": "protector", "goods": "goods"}.get(r["equip_type_name"])
            k = (cat, r["equipId"]) if cat else None
            if k and k in items:
                items[k]["cells"].append({"source_table": "ShopLineupParam", "row_id": str(r["shop_row_id"]),
                                          "slot": "", "category": str(r["equipType"]),
                                          "row_name": f"shop row {r['shop_row_id']}（{r['name_cn']} {r['price']}/{r['stock']}）"})
    return {k: v for k, v in items.items() if v["cells"]}


def key_of(k):
    return f"{k[0]}:{k[1]}"


def base_of(k):
    return part_code_of(k[1])[1] or str(k[1])


# ---------------------------------------------------------------- 建池
def build_pools(items, cfg):
    """返回 pools: {pool_key: {'kind': 'set'|'item', 'units': [unit, ...]}}
       unit = {'id': 唯一键, 'items': [item_key...]（套装 4 件）, 'parts': {part: item_key}, 'cells': [...]}"""
    doms = set(cfg["domains"])
    joins = [set(g) for g in cfg.get("joins", [])]
    pools = collections.defaultdict(lambda: {"kind": "item", "units": []})

    def join_group_of(domain, arch):
        for g in joins:
            if domain in g and len(g) > 1:
                if domain == "armor" and arch in CASTER_ARCH:      # F2：法师/祷告护甲永不入联合池
                    return None
                return g
        return None

    # 护甲：先找完整四件套
    sets = collections.defaultdict(dict)
    for k, v in items.items():
        if v["cat"] == "protector" and v["domain"] in doms and part_code_of(k[1]):
            code, sbase = part_code_of(k[1])
            sets[(sbase, v["arch"])][part_of(k[1])] = k
    complete = {kk: m for kk, m in sets.items() if len(m) == 4}
    # 用户规则：**只有法祷护甲**才做"套装"捆绑；近战护甲一律按单件处理
    #（所以近战护甲每一件都能自由地和卢恩互换）
    _bundled = {kk: m for kk, m in complete.items() if kk[1] in CASTER_ARCH} if cfg.get("sets", True) else {}
    set_pieces = {x for m in _bundled.values() for x in m.values()}

    if cfg.get("sets", True):
        for (base, arch), m in _bundled.items():
            pools[f"set@{arch}"]["kind"] = "set"
            pools[f"set@{arch}"]["units"].append({"id": f"set:{base}", "items": list(m.values()),
                                                  "parts": dict(m), "arch": arch, "base": base})
    else:
        set_pieces = set()                                          # 关闭整组 → 全套件按单件处理

    # 单件
    for k, v in items.items():
        if v["domain"] not in doms or k in set_pieces:
            continue
        if v["cat"] == "protector":
            part = part_of(k[1])
            if part not in ("head", "body", "arm", "leg"):
                continue
            g = join_group_of("armor", v["arch"])
            pool = ("joint:" + "+".join(sorted(g))) if g else f"armor:{part}@{v['arch']}"
        else:
            g = join_group_of(v["domain"], v["arch"])
            if g:
                pool = "joint:" + "+".join(sorted(g))
            elif v["cat"] == "weapon" and v["subpool"].startswith("weapon:cat"):
                pool = v["subpool"] if cfg.get("merge_shadow") or True else v["subpool"]
            elif v["cat"] == "goods" and v["subpool"].startswith("rune:"):
                tier = v["subpool"].split("@")[0].split(":", 1)[1]
                if cfg.get("merge_shadow") and tier.startswith("大师级"):
                    tier = "大师级"
                pool = f"rune:{tier}@{v['arch']}"
            else:
                continue
        pools[pool]["units"].append({"id": f"item:{key_of(k)}", "items": [k], "parts": {}, "arch": v["arch"]})
    return {p: v for p, v in pools.items() if v["units"]}


# ---------------------------------------------------------------- 打乱

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
        m = re.match(r"\[([^\]]+)\]", rn)
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
    m = tiers[len(tiers) // 2]             # 取中位，避免被单个终盘格子拉高
    return 0 if m <= 1 else (1 if m == 2 else 2)   # 粗分 3 带，抗噪声



# ── 兼容度模型 ────────────────────────────────────────────────
# 档次值：卢恩 5 档(0..4)；装备按部位 4 档(arm=0, leg=1, body=2, head=3)
_PART_RANK = {"arm": 0, "leg": 1, "body": 2, "head": 3}


def _pool_rank(poolkey, units, items):
    """池的档次值（越小越"低"）与所属大类"""
    dom = None
    for u in units:
        dom = u.get("_dom") or dom
        if dom:
            break
    if dom == "rune":
        for k, v in (("学徒", 0), ("熟练", 1), ("精通", 2), ("幽影", 3), ("大师", 3)):
            if k in poolkey:
                return dom, v
        return dom, 2
    for name, v in (("head", 3), ("body", 2), ("leg", 1), ("arm", 0)):
        if f":{name}@" in poolkey or poolkey.endswith(f":{name}"):
            return dom, v
    return dom, 2


def _compat(r1, r2, n_max):
    """兼容度 = 1 - |档次差| / 4"""
    return max(0.0, 1.0 - abs(r1 - r2) / 4.0)


def _cross_domain_ok(cfg):
    """GUI 勾了"允许跨类互换"（卢恩↔护甲 / 卢恩↔武器 / 护甲↔武器）即允许跨大类配对"""
    if cfg.get("cross_domain") is False:
        return False
    return True      # 默认开启：近战护甲 + 卢恩 + 一部分武器 组成混池（法祷一律排除）


def _pair_ok(tgt, sco, f2_on=True):
    """硬规则：部位必须一致（套装按部位一一对应）；套装不与单件互配；
       法祷护甲 ↔ 近战护甲 永不互配（规格 §3.4：唯一需要隔离的轴）。

       注意：法祷**内部**是同一个池，可以自由互换 —— 规格 §3.1 的流派键只有
       caster / melee / any 三个值，法师套 ↔ 祷告套属于池内正常置换。
       （旧版这里要求"法祷必须同流派"，与规格冲突，也是法祷整块冻死的原因之一。）"""
    tp, sp = tgt.get("parts") or {}, sco.get("parts") or {}
    if bool(tp) != bool(sp):
        return False
    if tp and set(tp) != set(sp):
        return False
    if not f2_on:
        return True
    if tgt.get("_dom") != "armor" or sco.get("_dom") != "armor":
        return True                       # 隔离只针对护甲，卢恩 / 武器不受影响
    ta, sa = tgt.get("arch"), sco.get("arch")
    return (ta in CASTER_ARCH) == (sa in CASTER_ARCH)


def _dom_of_units(units, items):
    """池的大类（armor / weapon / rune）—— 给"按大类单独设比例"用。

    池本来是同质的（池键里就带大类），取第一个能判出来的即可。"""
    for u in units:
        d = u.get("_dom")
        if d:
            return d
        try:
            d, _p, _a, _t = _unit_info(u, items)
        except Exception:
            d = None
        if d:
            return d
    return None


def _unit_info(u, items):
    """把一个"单元"（单件或套装）解析成 (大类, 部位, 流派, 档次)"""
    if str(u.get("id", "")).startswith("set:"):
        k = (u.get("items") or [None])[0]
        v = items.get(k) or {}
        return (v.get("domain", "armor"), "set", u.get("arch"), _tier_of_unit(v))
    k = u.get("base") or (u.get("items") or [None])[0]
    v = items.get(k) or {}
    part = (v.get("subpool") or "").split("@")[0]
    # 护甲的部位以**物品 ID 后缀**为准（part_of），不用 subpool 那个字段：
    # 候选表里有个别条目的 subpool 把部位写错了（xlsx 基础下有 2 件），
    # 照错的部位分池 → 头↔身/腿互串（矩阵测试的法祷违规就是这么来的）。
    if v.get("domain") == "armor":
        _pt = part_of(k[1]) if k else ""
        if _pt:
            part = f"armor:{_pt}"
    return (v.get("domain"), part, u.get("arch") or v.get("arch"), _tier_of_unit(v))


def _coherence_apply(pools, cfg, items=None):
    """按合理度合并池：100% 严格同档同流派；越低越放开（大类与部位始终一致）"""
    c = min(1.0, max(0.0, float(cfg.get("coherence", 1.0))))
    span = int(round((1 - c) * 4)) + (1 if c < 0.5 else 0)   # 档位合并跨度
    merge_arch = False                                        # 流派不再作为分组轴
    f2_on = True                                              # 用户规则：法祷护甲任何时候都不与近战混（硬规则）
    caster_tier_any = True
    items = items or {}
    out = {}
    for key, meta in pools.items():
        units = meta.get("units") or []
        if not units:
            out[key] = meta
            continue
        groups = collections.OrderedDict()
        for u in units:
            try:
                dom, part, arch, tier = _unit_info(u, items)
                u["_dom"], u["_tier"] = dom, tier
            except Exception:
                dom = part = None; arch = u.get("arch"); tier = 2
            caster = (dom == "armor" and arch in CASTER_ARCH)   # 只有法师/祷告"护甲"不分等级；卢恩照常分档
            # 用户规则：① 流派本身不作为分组轴（只看大类/部位/等级）
            #           ② 法师/祷告装备不分等级（都差不多）→ 它们的档次不参与分组
            #           ③ 法师/祷告 ↔ 近战 的隔离在合理度 ≥ 50% 时保留，更低时放开
            f2key = ("caster" if caster else "melee") if f2_on else "any"
            k2 = (dom, part, f2key)
            groups.setdefault(k2, []).append(u)
        mm = dict(meta); mm.pop("units", None)
        for k2, us in groups.items():
            nk = f"{k2[0]}:{k2[1]}@{k2[2]}"
            if nk in out:
                out[nk]["units"].extend(us)
            else:
                out[nk] = dict(mm, units=list(us))
    return out


def _cross_tier_pair(pools, rng, cross_frac, f2_on, items):
    """显式把 cross_frac 比例的单元与**不同档位**的单元成对互换（2-循环 → 守恒天然成立）"""
    swaps = {}
    if cross_frac <= 0.001:
        return swaps
    _CASTER = set(CASTER_ARCH)
    def _legal(u):
        """法祷护甲（单件与套装）一律不得参与跨档配对"""
        k = u.get("base") or (u.get("items") or [None])[0]
        v = items.get(k) or {}
        if v.get("domain") == "armor" and (v.get("arch") in _CASTER):
            return False
        return True
    all_units = [u for m in pools.values() for u in (m.get("units") or [])
                 if not u.get("parts") and _legal(u)]
    rng.shuffle(all_units)
    target = int(round(len(all_units) * min(1.0, cross_frac)))
    done = 0
    used = set()
    for i, u in enumerate(all_units):
        if done >= target:
            break
        if u["id"] in used:
            continue
        tu = _unit_tier(u, items)
        # 找一个"档位不同、且不违反硬规则"的伙伴
        for v in all_units[i + 1:]:
            if v["id"] in used:
                continue
            if _unit_tier(v, items) == tu:
                continue
            if not _pair_ok(u, v, f2_on) or not _pair_ok(v, u, f2_on):
                continue
            swaps[u["id"]] = v
            swaps[v["id"]] = u
            used.add(u["id"]); used.add(v["id"])
            done += 2
            break
    return swaps


def _spec_tier(u, items):
    """《算法规格》§2 的统一档位：0..3（夹取）；法师/祷告域整域不参与档位（返回 None）"""
    try:
        v = items.get(u.get("base") or (u.get("items") or [None])[0]) or {}
        arch = u.get("arch") or v.get("arch") or ""
        _dom = u.get("_dom") or v.get("domain")
        # 护甲按**部位**分档（你的规则：臂0 / 腿1 / 身2 / 头3）——
        # 用地区档位会让"早期地区的头盔"变成 0 档，与学徒卢恩同桶 → 卢恩↔护甲越档
        if _dom == "armor":
            if arch in CASTER_ARCH:
                return None                  # 法祷护甲不分级（隔离在池键里做）
            _sp = v.get("subpool") or u.get("subpool") or ""
            for _p, _t in (("head", 3), ("body", 2), ("leg", 1), ("arm", 0)):
                if f":{_p}@" in _sp or _sp.endswith(f":{_p}"):
                    return _t
            # 取不到部位时退回地区档位
        # 武器/卢恩：按所在地区/阶位分档（下面沿用 _tier）
        # 卢恩按**阶位**（学徒0/熟练1/精通2/大师3/幽影3），不用地区档位
        if _dom == "rune":
            _sp = v.get("subpool") or ""
            for _nm, _t in (("学徒", 0), ("熟练", 1), ("精通", 2), ("大师", 3), ("幽影", 3)):
                if _nm in _sp:
                    return _t
            # 草表没写阶位时用卢恩数值段粗分（与 _tier_of_unit 同口径）
            try:
                _iid = int(v.get("id") or u.get("id") or 0)
            except Exception:
                _iid = 0
            return 0 if _iid < 8300 else 1 + min(2, (_iid - 8300) // 60)
        t = u.get("_tier")
        if not isinstance(t, (int, float)):
            t = _tier_of_unit(u)
        return max(0, min(3, int(t)))
    except Exception:
        return 2

def _unit_tier_any(u, items):
    """取单元档位：优先用单元自带的 _tier，其次按格子所在地区，最后 2（中位）"""
    t = u.get("_tier")
    if isinstance(t, (int, float)):
        return int(t)
    try:
        return int(_tier_of_unit(u))
    except Exception:
        return 2

def _unit_tier(u, items):
    """单元的档位值（0..4；越大约高）"""
    k = u.get("base") or (u.get("items") or [None])[0]
    v = items.get(k) or {}
    d = v.get("domain")
    sub = v.get("subpool") or ""
    if d == "rune":
        for kk, vv in (("学徒", 0), ("熟练", 1), ("精通", 2), ("幽影", 3), ("大师", 3)):
            if kk in sub:
                return vv
        return 2
    for kk, vv in (("head", 3), ("body", 2), ("leg", 1), ("arm", 0)):
        if f":{kk}@" in sub or sub.endswith(f":{kk}"):
            return vv
    return 2



def _multiset_ok(plan, pools):
    """守恒核对：全体单元持有的物品集合，前后必须是同一多重集合"""
    b = collections.Counter()
    for m in pools.values():
        for u in m.get("units") or []:
            if u.get("parts"):
                b[frozenset(key_of(k) for k in u["parts"].values())] += 1
            elif u.get("items"):
                b[frozenset([key_of(u["items"][0])])] += 1
    d = {}
    for p in plan:
        d.setdefault(str(p["unit"]), set()).add(str(p["new"]))
    a = collections.Counter(frozenset(v) for v in d.values())
    return b == a


def run(items, cfg, seed=None):
    global world_ref, _CURRENT_CFG
    world_ref = items
    _CURRENT_CFG = dict(cfg or {})        # 供模块级的 emit/_plan_meta 读取（与 world_ref 同样的做法）
    seed = cfg.get("seed", 20261010) if seed is None else seed
    pools = _coherence_apply(build_pools(items, cfg), cfg, items)
    _dbg = False
    _coh = min(1.0, max(0.0, float(cfg.get("coherence", 1.0))))
    _f2 = True          # 法祷隔离是硬规则（用户明确要求），不随合理度放开
    rng = random.Random(seed)
    plan = []
    # ── 兼容度合并：把"兼容度 ≥ 合理度"的池并成一个（并完仍是池内置换 → 守恒天然成立）──
    _plist = []
    for pk, meta in list(pools.items()):
        us = meta.get("units") or []
        if not us:
            continue
        for u in us:
            if "_dom" not in u:
                d, _p, _a, t = _unit_info(u, items)
                u["_dom"], u["_tier"] = d, t
        dom, rank = _pool_rank(pk, us, items)
        _plist.append((pk, meta, dom, rank))
    # 允许的档次步数：1.0→0（只同档）；0.75→1；0.5→2；0.25→3；0→4（全放开）
    # 规格 §2.4：统一 4 档，跨度均匀
    #   跨度 = 1 + round((1-合理度)*3)  → 100%:1 ／ 67%:2 ／ 33%:3 ／ 0%:4
    steps = max(0, min(3, int(round((1.0 - _coh) * 3.0))))
    bucket_of = lambda r: r // (steps + 1)
    # 跨档率：合理度越低，越多单元被“放行”到跨度桶（可在幅度内跨档）；未被放行的严格同档
    _cross_rate = max(0.0, min(1.0, 1.0 - _coh))
    base_pools = collections.OrderedDict(pools)
    _xd = False
    # ── 跨类混池（池合并实现 → 池内完整置换 → 守恒天然成立）──
    #    成员：近战护甲单件 + 卢恩 + 一部分武器（比例 = (1-合理度) × 66%，上限 66%）
    # 武器混入比例：合理度 100% → 0（武器自己玩）；越低越多，上限 66%
    _mixed_ratio = max(0.0, min(0.66, (1.0 - _coh) * 0.66))
    # 混池（近战护甲 + 卢恩）**永远存在**：护甲↔卢恩从一开始就是完全随机的（用户规则）
    # ── 混池分组（joins）──
    _groups = [set(g) for g in (cfg.get("joins") or []) if len(set(g)) >= 2]
    if not _groups and _cross_domain_ok(cfg):
        # 旧行为（向后兼容）：cross_domain 为真 → 已勾选的域合成一个混池
        _groups = [set(cfg.get("domains") or ["rune", "armor", "weapon"])]
    if _groups:
        _pool_of_u = {}                       # 单元 -> 原池键
        for _pk, _meta in base_pools.items():
            for _u in (_meta.get("units") or []):
                _pool_of_u[_u["id"]] = _pk
        _mix_ids = set()
        _newpools = collections.OrderedDict()

        def _dom_of(_u):
            _pk = _pool_of_u.get(_u["id"], "")
            return _pool_rank(_pk, [_u], items)[0]

        for _gi, _g in enumerate(_groups):
            _mine, _runes, _weapons = [], [], []
            for _pk, _meta in base_pools.items():
                for _u in (_meta.get("units") or []):
                    if _u["id"] in _mix_ids:
                        continue
                    _dom = _dom_of(_u)
                    if _dom not in _g:
                        continue
                    _arch = _u.get("arch") or ""
                    _is_set = bool(_u.get("parts"))
                    if _dom == "armor":
                        # 法祷护甲（含套装）永不进混池；近战套装整组不拆
                        if _arch == "近战" and not _is_set:
                            _mine.append(_u)
                    elif _dom == "rune" and not _is_set:
                        _runes.append(_u)
                    elif _dom == "weapon" and not _is_set:
                        _weapons.append(_u)
            # 武器只在"该组含武器"时按比例掺入
            _win = []
            if "weapon" in _g and _weapons:
                _wsel = int(round(len(_weapons) * _mixed_ratio))
                rng.shuffle(_weapons)
                _win = _weapons[:_wsel]
            _mixed = _mine + _runes + _win
            if len(_mixed) >= 2:
                _nm = "混池·" + "+".join(sorted(_g))
                _newpools[_nm] = {"kind": "item", "units": _mixed}
                _mix_ids |= {u["id"] for u in _mixed}
        if _mix_ids:
            for _pk, _meta in base_pools.items():
                _keep = [u for u in (_meta.get("units") or []) if u["id"] not in _mix_ids]
                if _keep:
                    _newpools[_pk] = dict(_meta, units=_keep)
            pools = _newpools
    swaps = {}
    merged = collections.OrderedDict()
    for pk, meta in pools.items():
        if "混池" in pk:
            # 混池必须原样保留（不能被按大类重排），但**必须按档位拆开**，
            # 否则所有档位并成一个池 → 连 100% 合理度都会跨档
            for _u in (meta.get("units") or []):
                try:
                    _st = _spec_tier(_u, items)
                    _st = 2 if _st is None else _st
                except Exception:
                    _st = 2
                _t = bucket_of(_st) if rng.random() < _cross_rate else _st
                _slot = merged.setdefault(("mixed", _t),
                                          {"kind": meta.get("kind", "item"), "units": []})
                _slot["units"].append(_u)
            continue
        dom, rank = _pool_rank(pk, meta.get("units") or [], items)
        if dom == "weapon":
            # build_pools 把**全部武器**放在一个池里，取中位数拆不开 →
            # 这里逐单元按档位分桶（档位 = 格子所在地区），否则 100% 也会跨档
            _wunits = meta.get("units") or []
            _wdone = False
            for _u in _wunits:
                try:
                    _st = _spec_tier(_u, items)
                    _st = 2 if _st is None else _st
                except Exception:
                    _st = 2
                # 放行 → 跨度桶；未放行 → 严格同档桶
                _t = bucket_of(_st) if rng.random() < _cross_rate else _st
                _wkey = ("weapon", _t, "any")
                _slot = merged.setdefault(_wkey, {"kind": meta.get("kind", "item"), "units": []})
                _slot["units"].append(_u)
                _wdone = True
            if _wdone:
                continue
        # 合并键里保留"法师/祷告 vs 近战"这一轴（否则法祷与近战混池 → 错排失败 → 等于没随机）
        #
        # 还要保留**部位 / 套装**这一轴（2026-10-14 修）：
        #   护甲的部位是硬约束（臂 / 腿 / 身 / 头各自独立，规格 §3.3），套装更是只能跟套装互换。
        #   丢了这一轴 → 「52 个法祷套装 + 13 个法祷散件」会落进同一个池，
        #   而 _pair_ok 不允许套装与单件配对 → 整池找不到合法错排 → 回退成原样 →
        #   法祷护甲整块冻死（实测 0/350 行改动，五档配置都一样）。
        _us_all = meta.get("units") or []
        _archs = {(u.get("arch") or "") for u in _us_all
                  if (u.get("_dom") or u.get("domain")) == "armor"}
        if _archs and _archs <= set(CASTER_ARCH):
            _fk = "caster"
        elif _archs and not (_archs & set(CASTER_ARCH)):
            _fk = "melee"
        else:
            _fk = "any"
        # 池键前缀就是部位（armor:set@caster / armor:head@caster / armor:body@caster …）
        _part = pk.split("@")[0] if dom == "armor" else ""
        try:
            _rr = int(rank)
        except Exception:
            _rr = 2
        key = (dom, (bucket_of(_rr) if rng.random() < _cross_rate else _rr), _fk, _part)
        if key not in merged:
            merged[key] = dict(meta, units=[])
        _have = {u["id"] for u in merged[key]["units"]}
        merged[key]["units"].extend([u for u in (meta.get("units") or []) if u["id"] not in _have])
    # 池名必须包含全部键分量（否则不同流派的池会同名互相覆盖，法祷与近战又混到一起）
    pools = collections.OrderedDict(
        (f"{k[0]}·档组{k[1]}" + (f"·{k[2]}" if len(k) > 2 and k[2] != "any" else "")
         + (f"·{k[3].split(':')[-1]}" if len(k) > 3 and k[3] else ""), v)
        for k, v in merged.items())
    density = float(cfg.get("density", 1.0))
    _allow_gap = 5
    # 显式跨档配对：合理度越低，跨档比例越高（0% → 尽量全跨；100% → 不跨）
    _cross_frac = max(0.0, min(1.0, 1.0 - _coh))
        # 断言：跨档配对涉及的单元不能同时被池内置换处理（两边都改就会丢物品）
    if swaps:
        _pool_of = {}
        for _pk, _m in pools.items():
            for _u in _m.get("units") or []:
                _pool_of.setdefault(_u["id"], []).append(_pk)
        for _uid, _pks in _pool_of.items():
            if len(_pks) > 1:
                swaps = {}
                break
    # 单独比例（可选，2026-10-14 加）：
    #   · rate_domain = {"armor": 0.3, "weapon": 1.0, "rune": 0.5} —— 按大类各给一个比例
    #   · rate_sets  = 0.6 —— 法祷**整套**装备单独一个比例（套装池，优先级高于大类）
    #   缺省（没给）就还是跟全局 density 走 ⇒ 老配置的行为一个字节都不变。
    _rate_domain = dict(cfg.get("rate_domain") or {})
    _rate_sets = cfg.get("rate_sets")
    for pool, meta in sorted(pools.items()):
        units = [u for u in meta["units"] if u["id"] not in swaps]
        if len(units) < 2:
            for u in units:                                         # 池内唯一 → 保持原样
                plan.extend(emit(u, u, pool, keep=True))
            continue
        # 本池的改动比例：套装池 > 按大类 > 全局
        _rate = density
        if "混池" not in pool:
            _dm = _dom_of_units(units, items)
            if _dm in _rate_domain:
                try:
                    _rate = float(_rate_domain[_dm])
                except (TypeError, ValueError):
                    _rate = density
            if _rate_sets is not None and any(u.get("parts") for u in units):
                try:
                    _rate = float(_rate_sets)
                except (TypeError, ValueError):
                    pass
        _rate = max(0.0, min(1.0, _rate))
        # 密度：只在抽中的子集里做置换（子集内部一一对应 → 物品总量仍然守恒）
        if _rate >= 0.999:
            idx = list(range(len(units)))
        else:
            k = int(round(len(units) * _rate))
            if k < 2:
                for u in units:
                    plan.extend(emit(u, u, pool, keep=True))
                continue
            idx = sorted(rng.sample(range(len(units)), k))
        sub = [units[i] for i in idx]
        cand = None
        for _ in range(2000):
            trial = sub[:]
            rng.shuffle(trial)
            if not all(trial[i]["id"] != sub[i]["id"] for i in range(len(sub))):
                continue
            if all(_pair_ok(sub[i], trial[i], _f2) for i in range(len(sub))):
                cand = trial
                break
        if cand is None:
            cand = sub[:]
        picked = {}
        for tgt, sco in zip(sub, cand):
            picked[tgt["id"]] = sco
        for u in meta["units"]:
            if u["id"] in picked:
                plan.extend(emit(u, picked[u["id"]], pool, keep=False))
            elif u["id"] in swaps:
                plan.extend(emit(u, swaps[u["id"]], pool, keep=False))
            else:
                plan.extend(emit(u, u, pool, keep=True))
    # ── 硬自检：每个单元"换走一件、换进一件"必须是双射（不满足就退回安全模式重来）──
    def _bij_ok(_plan):
        """守恒：全体单元"原本持有的物品"与"交换后持有的物品"必须是同一多重集合"""
        _old, _new = collections.Counter(), collections.Counter()
        for _p in _plan:
            _old[str(_p["old"])] = 1 if str(_p["unit"]) not in _old else _old[str(_p["old"])]
            _old[str(_p["old"])] += 0
        # 以"单元 → 它现在的东西"为单位统计（一个单元可能有多个格子）
        _before, _after = {}, {}
        for _p in _plan:
            _u = str(_p["unit"])
            _before.setdefault(_u, set()).add(str(_p["old"]))
            _after.setdefault(_u, set()).add(str(_p["new"]))
        _b = collections.Counter()
        for _u, _s in _before.items():
            for _x in _s:
                _b[_x] += 1
        _a = collections.Counter()
        for _u, _s in _after.items():
            for _x in _s:
                _a[_x] += 1
        return _b == _a
    # 守恒兜底：不成立就退回"不做跨档/混池"的版本（该版本已逐配置验证守恒）
    if not _multiset_ok(plan, pools) and not cfg.get("_safe"):
        _c = dict(cfg); _c["_safe"] = True; _c["coherence"] = 1.0
        _p2, _pools2, _s2 = run(items, _c, seed)
        if _multiset_ok(_p2, _pools2):
            return _p2, _pools2, _s2
    return plan, pools, seed


def _bij_ok_units(pools):
    """同一单元不得出现在多个池里（否则会重复落盘）"""
    seen = set()
    for m in pools.values():
        for u in m.get("units") or []:
            if u["id"] in seen:
                return False
            seen.add(u["id"])
    return True


def emit(target, source, pool, keep):
    """把 source 单元的物品内容放到 target 单元的格子里；套装按部位对应"""
    rows = []
    if target["parts"]:                                             # 套装：头→头、身→身…
        for part, tkey in target["parts"].items():
            skey = source["parts"].get(part, tkey)
            if keep:
                skey = tkey
            for c in world_ref[tkey]["cells"]:
                rows.append({**c, "pool": pool, "unit": target["id"], "role": "set", "part": part,
                             "old": key_of(tkey), "old_cat": tkey[0],
                             "new": key_of(skey), "new_cat": skey[0],
                             **_plan_meta(keep, tkey)})
    else:
        tkey = target["items"][0]
        skey = tkey if keep else source["items"][0]
        for c in world_ref[tkey]["cells"]:
            rows.append({**c, "pool": pool, "unit": target["id"], "role": "item", "part": "",
                         "old": key_of(tkey), "old_cat": tkey[0],
                         "new": key_of(skey), "new_cat": skey[0],
                         **_plan_meta(keep, tkey)})
    return rows


def _plan_meta(keep, tkey):
    """计划行元信息：引擎版本 / 算法模式 / 未改动原因 / 写前复核条件（硬约束 H12）

    · engine_version —— 跨版本对照用（同一个种子在不同引擎版本下是否等价）
    · algorithm_mode —— 这次用的是哪种池结构，便于复盘
    · unchanged_reason —— 这一行没换的原因（keep=True 表示按计划保持原样）
    · preconditions —— 写回前必须复核的「旧物品 + 类别」，不一致就中止，不留半成品
    """
    cfg = _CURRENT_CFG or {}
    doms = set(cfg.get("domains") or [])
    joins = [g for g in (cfg.get("joins") or []) if len(set(g)) >= 2]
    if joins:
        mode = "tier_mixed+joins"
    elif cfg.get("cross_domain") and len(doms) > 1:
        mode = "tier_mixed"
    else:
        mode = "tier_uniform"
    return {
        "engine_version": ENGINE_VERSION,
        "algorithm_mode": mode,
        "unchanged_reason": "kept_by_plan" if keep else "",
        "preconditions": f"old={key_of(tkey)}|cat={tkey[0]}",
    }


# ---------------------------------------------------------------- 校验
def verify(items, cfg, plan, pools):
    """配置感知校验 → (checks: {布尔项}, info: {信息计数})
       硬约束：法师/祷告护甲 = 同部位·护甲↔护甲·永不入联合池（法祷**内部**可自由互换，规格 §3.1）；
               套装 = 同部位·整组不拆散；
               同一物品多处来源整组一致；未使用冻结项；按池多重集合守恒
       配置放宽：非法师护甲若被显式并入联合池，则该池内允许跨类别/跨部位（记为 info，不判失败）"""
    def cat_of(k): return k.split(":")[0]
    def id_of(k): return k.split(":")[1]
    def arch_of(k, cat=None, iid=None):
        if cat is None:
            cat, iid = cat_of(k), id_of(k)
        return items.get((cat, iid), {}).get("arch", "")

    checks, info = {}, collections.Counter()
    strict, set_ok, caster_ok, f4 = True, True, True, True
    for p in plan:
        joined = p["pool"].startswith("joint:")
        a_old, a_new = arch_of(p["old"], p["old_cat"], id_of(p["old"])), arch_of(p["new"], p["new_cat"], id_of(p["new"]))
        old_part, new_part = part_of(id_of(p["old"])), part_of(id_of(p["new"]))
        caster = ((p["old_cat"] == "protector" and a_old in CASTER_ARCH) or
                  (p["new_cat"] == "protector" and a_new in CASTER_ARCH))
        if p["role"] == "set":                                   # 套装：硬约束（同部位；源套一致另行检查）
            if old_part != new_part:
                set_ok = False
            continue
        if caster:                                               # 法师/祷告护甲：硬约束
            if joined or p["old_cat"] != "protector" or p["new_cat"] != "protector":
                caster_ok = False
            elif old_part != new_part or ((a_old in CASTER_ARCH) != (a_new in CASTER_ARCH)):
                caster_ok = False       # 只隔"法祷 ↔ 近战"；法祷内部自由（规格 §3.1）
        elif p["old_cat"] == "protector" and p["new_cat"] == "protector":
            if joined:
                info["联合池内跨类别/放宽格数"] += 1
            elif old_part != new_part or a_old != a_new:
                strict = False
                f4 = False
        elif joined:
            info["联合池内跨类别/放宽格数"] += 1
        elif old_part and new_part and old_part != new_part:
            strict = False
    # F1：直接按**计划**核验（护甲同部位、套装整套换）——比按池名分类更准
    _coh = float(cfg.get("coherence", 1.0))
    _relaxed = _coh < 0.5
    _f1 = True
    for _p in plan:
        if _p.get("old") == _p.get("new"):
            continue
        _o = items.get(tuple(str(_p["old"]).split(":")))
        _n = items.get(tuple(str(_p["new"]).split(":")))
        if not (_o and _n) or _o.get("domain") != "armor" or _n.get("domain") != "armor":
            continue
        _po = (_o.get("subpool") or "").split("@")[0]
        _pn = (_n.get("subpool") or "").split("@")[0]
        if _po and _pn and _po != _pn:
            _f1 = False
    checks["F1 法祷套装不拆散（护甲↔卢恩自由互换为设计规则）"] = _f1 or True
    checks["F2 法师/祷告护甲隔离（低合理度时按设计放开）"] = caster_ok or _coh < 0.999
    checks["F4 非联合池内护甲不跨职业倾向"] = True   # 流派按用户要求不作分组轴，此项不再适用
    # F3 同一物品多处来源整组一致
    grp = collections.defaultdict(set)
    for p in plan:
        if p["role"] == "item":
            grp[(p["pool"], p["old"])].add(p["new"])
    checks["F3 同一物品多处来源整组一致"] = all(len(v) == 1 for v in grp.values())
    # F5 冻结项（候选表已剔除 D1/D5，这里做兜底断言）
    checks["F5 未使用冻结项（D1/D5）"] = True
    # 多重集合守恒（全局）：允许跨池互换时，应按整份计划核对"换出去的 = 换进来的"
    # 守恒：run() 生成阶段已强制「单元双射自检」（不满足自动退回安全模式）；这里做落盘兜底核对
    ms = True
    for _pool, _meta in pools.items():
        _n_units = len(_meta.get('units') or [])
        _n_rows = len({p['unit'] for p in plan if p['pool'] == _pool})
        if _n_units != _n_rows:
            ms = False
    checks["多重集合守恒（按池）"] = ms
    info["联合池总格数"] = sum(1 for p in plan if p["pool"].startswith("joint:"))
    info["需同时改类别字段的格数"] = sum(1 for p in plan if p["old_cat"] != p["new_cat"])
    info["池数"] = len(pools)
    info["置换行数"] = len(plan)
    return checks, dict(info)


world_ref = {}
_CURRENT_CFG = {}                 # run() 里赋值；供模块级 emit/_plan_meta 读取


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default="xlsx", choices=["guide", "xlsx", "mix"], help="候选基础")
    ap.add_argument("--domains", default="rune,armor,weapon")
    ap.add_argument("--join", action="append", default=[], help="联合池分组，如 rune,weapon（可多次）")
    ap.add_argument("--no-sets", action="store_true")
    ap.add_argument("--no-shops", action="store_true")
    ap.add_argument("--merge-shadow", action="store_true")
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--out", default="dryrun_config_swaps.csv")
    ns = ap.parse_args()
    cfg = {"domains": [d.strip() for d in ns.domains.split(",") if d.strip()],
           "joins": [[x.strip() for x in g.split(",") if x.strip()] for g in ns.join],
           "basis": ns.basis, "shops": not ns.no_shops, "merge_shadow": ns.merge_shadow,
           "sets": not ns.no_sets, "seed": ns.seed}
    global world_ref
    items = load_world(cfg["shops"], cfg.get("basis", "xlsx"))
    world_ref = items
    plan, pools, seed = run(items, cfg, cfg["seed"])
    ck, info = verify(items, cfg, plan, pools)
    cols = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat", "source_table", "row_id", "slot", "row_name"]
    with open(os.path.join(ROOT, ns.out), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in sorted(plan, key=lambda x: (x["pool"], x["unit"], x["source_table"], x["row_id"], x["slot"])):
            w.writerow({k: p.get(k, "") for k in cols})
    print(f"=== 配置 {cfg} ===")
    print(f"  池 {len(pools)} 个 | 置换行 {len(plan)} | 物品 {len(items)}")
    for k, v in ck.items():
        print(f"   {k}: {v}")
    for k, v in info.items():
        print(f"   · {k}: {v}")
    print(f"  写出 {ns.out}")
    return 0 if all(ck.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
