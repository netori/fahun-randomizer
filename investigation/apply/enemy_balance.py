# -*- coding: utf-8 -*-
"""Boss 血量分布平衡（固定 LUT + 分层按位置强度分配）。

设计（与用户 2026-10-23 的讨论一致）：
- **函数固定**：目标分布 = 随机前这些位置的原始有效血量分布（法魂口径：raw hp ×
  自己 spEffectID3 档的 maxHpRate），由原始池一次性算出分位档（bin），与种子无关。
- **种子只负责抽**：位置按「原有效血量」排序后落档；每个位置用 (seed, key) 的
  确定性随机源在档内抽一个值（可选 ±jitter 档串门）。抽完不重新拟合。
- **写盘口径**：写盘层最终有效血量 = target_hp × 位置 dst 档倍率（engine 先乘克隆行
  自带档、再乘 area effect 的 dst/src）。所以这里 target_hp = 目标有效值 ÷ dst 倍率。
- 只处理 Boss→Boss（六类 Boss 互换）；普通敌人/多阶段组不动。
- 伤害（默认 --dmg-model position，即方案 A）：不写派生倍率，area effect 的 damage 组
  保持 dst/src。引擎里「有效伤害 = 换入者 raw 招式 × 捐赠者档攻击率 × dst/src」
  = 换入者 raw 招式 × 位置档攻击率 —— 与「原版该位置」的区域缩放完全一致（比值恒 1.00，
  可离线逐位置核对）；剩下的差异只有换入者自己的招式 raw（身份特征）。
- 备选 --dmg-model derived：M = (H*/换入者原有效血量)^alpha clamp 在 [0.5,2.0]，
  写盘层覆盖 area effect 的 damage 组（按换入者自己原强度对齐，不是按位置）。

CLI：
  python enemy_balance.py --plan <in.json> --out <out.json> [--k 10] [--jitter 0]
                          [--alpha 0.5] [--seed 20261010] [--report]
  python enemy_balance.py --selftest
"""
import argparse
import json
import io
import math
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
sys.path.insert(0, HERE)

REF_PATH = os.path.join(INV, "balance_ref.json")
BOSSISH = {"Boss", "MinorBoss", "Miniboss", "NightMiniboss", "DragonMiniboss", "Evergaol"}
DEFAULT_K = 10
DEFAULT_JITTER = 0
DEFAULT_ALPHA = 0.5
DEFAULT_DMG_CLAMP = (0.5, 2.0)
DEFAULT_HP_RATIO = (0.85, 1.25)   # 每个位置的有效血量 / 该位置原有效血量 允许的倍率窗口
DEFAULT_DMG_MODEL = "position"    # position = 伤害按位置档缩放（方案 A）；derived = 按血量派生倍率


def load_ref(path=REF_PATH):
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _num(d, key, default=0.0):
    try:
        return float(d.get(key))
    except (TypeError, ValueError):
        return float(default)


def tier_hp_rate(ref, tier):
    if not tier:
        return 1.0
    try:
        return float((ref.get("tier_hp") or {}).get(str(int(tier))) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def tier_atk_rate(ref, tier):
    if not tier:
        return 1.0
    try:
        return float((ref.get("tier_atk") or {}).get(str(int(tier))) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def npc_tier(ref, npc_id):
    try:
        return int((ref.get("npc_tier") or {}).get(str(int(npc_id))) or 0)
    except (TypeError, ValueError):
        return 0


def dst_tier(ref, npc_id, map_name):
    """位置原行的档：自己带可用档 → 自己的；否则同地图标准档众数（写盘层同口径）。"""
    t = npc_tier(ref, npc_id)
    if t:
        return t
    try:
        return int((ref.get("map_tier") or {}).get(map_name or "") or 0)
    except (TypeError, ValueError):
        return 0


def build_lut(pool, k=DEFAULT_K):
    """把原始池切成 k 个分位档，返回 [sorted(values)…]，每档样本数尽量相等。"""
    sp = sorted(float(v) for v in pool if float(v) > 0)
    n = len(sp)
    k = max(1, min(int(k or DEFAULT_K), max(1, n)))
    bins = [[] for _ in range(k)]
    for j, v in enumerate(sp):
        bins[min(k - 1, j * k // n)].append(v)
    return bins


def _ks(a, b):
    a = sorted(a)
    b = sorted(b)
    i = j = 0
    d = 0.0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            i += 1
        else:
            j += 1
        d = max(d, abs(i / float(len(a)) - j / float(len(b))))
    return d


def _quant(v, f):
    if not v:
        return 0.0
    s = sorted(v)
    return s[min(len(s) - 1, max(0, int(round(f * (len(s) - 1)))))]


def _rank_corr(x, y):
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            a = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                r[s[t]] = a
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def plan_seed(plan, seed=None):
    if seed is not None:
        return str(seed)
    meta = plan.get("meta") or {}
    return str(meta.get("base_seed") or meta.get("seed") or 1)


def eligible_units(plan):
    """换入身份是 Boss 级、且不是多阶段组条目的位置（这些才能按分布重写血量）。

    原位置不要求是 Boss：黄金树传送门守门位在参考表里是 Basic（野外精英），
    但规则强制换入 Boss 级身份，它们同样要用「位置原强度」锚住 —— 否则会走
    「换入者 raw hp × 位置档」的老口径，实测漂移 0.39x~3.24x。
    """
    out = []
    for e in plan.get("units") or []:
        if e.get("new_cls") not in BOSSISH:
            continue
        if e.get("multiphase"):
            # 多阶段：每阶段各换一个 Boss 的组，各阶段单独参与平衡；
            # 整场共用一个 Boss 的组只平衡第一阶段，其余阶段在下面跟着第一阶段统一。
            pol = e.get("mp_policy")
            if pol == "one_boss":
                if int(e.get("phase") or 0) != 1:
                    continue
            elif pol != "per_phase_model":
                continue
        if not e.get("old_npc_id") or not e.get("new_npc_id"):
            continue
        try:
            if int(e.get("target_hp") or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        out.append(e)
    return out


def apply_to_plan(plan, ref=None, npc=None, seed=None, k=DEFAULT_K, jitter=DEFAULT_JITTER,
                  alpha=DEFAULT_ALPHA, dmg_clamp=DEFAULT_DMG_CLAMP,
                  hp_ratio=DEFAULT_HP_RATIO, dmg_model=DEFAULT_DMG_MODEL, log=print):
    """就地改写 plan 里 Boss→Boss 单元的 target_hp，并记 balance 元数据。返回统计摘要。"""
    ref = ref if ref is not None else load_ref()
    if not ref:
        log("[平衡] 缺少 %s，跳过（先跑 balance_ref.py）" % REF_PATH)
        return None
    if npc is None:
        import enemy_plan
        npc = enemy_plan.load_npc()
    seed = plan_seed(plan, seed)
    sel = eligible_units(plan)
    rows = []
    for e in sel:
        oid = int(e["old_npc_id"])
        did = int(e["new_npc_id"])
        ohp = int((npc.get(oid) or {}).get("hp") or 0)
        dhp = int((npc.get(did) or {}).get("hp") or 0)
        if ohp <= 0 or dhp <= 0:
            continue
        mp = ((e.get("places") or [{}])[0].get("map")) or ""
        d_tier = dst_tier(ref, oid, mp)
        d_rate = tier_hp_rate(ref, d_tier)
        s_tier = npc_tier(ref, did)
        s_rate = tier_hp_rate(ref, s_tier)
        rows.append({"e": e, "old_hp": ohp, "donor_hp": dhp, "map": mp,
                     "dst_tier": d_tier, "dst_rate": d_rate,
                     "src_tier": s_tier, "src_rate": s_rate,
                     "orig_eff": ohp * d_rate, "donor_eff": dhp * s_rate})
    n = len(rows)
    if n < 10:
        log("[平衡] 只有 %d 个 Boss→Boss 单元，不够分层，跳过" % n)
        return None
    pool = [r["orig_eff"] for r in rows]
    bins = build_lut(pool, k)
    kn = len(bins)
    order = sorted(range(n), key=lambda i: rows[i]["orig_eff"])
    assigned = [0.0] * n
    clamped = 0
    for rank, i in enumerate(order):
        r = rows[i]
        b = min(kn - 1, rank * kn // n)
        rng = random.Random("gfb|%s|%s" % (seed, r["e"]["key"]))
        s = min(kn - 1, max(0, b + rng.randint(-int(jitter), int(jitter)))) if jitter else b
        h = rng.choice(bins[s])
        # 数值收束：每个位置的有效血量相对它原有效血量的倍率必须落在窗口内
        if hp_ratio:
            _lo = r["orig_eff"] * float(hp_ratio[0])
            _hi = r["orig_eff"] * float(hp_ratio[1])
            h = max(_lo, min(_hi, h))
        assigned[i] = h
        # 写盘口径：有效 = target × dst 档倍率（有 dst 档时）；无 dst 档 = 无 area effect，
        # 有效 = target × 换入者自己的档倍率（克隆行保留捐赠者 spEffectID3）。
        if r["dst_tier"]:
            target = int(round(h / (r["dst_rate"] or 1.0)))
        else:
            target = int(round(h / (r["src_rate"] or 1.0)))
        target = max(1, target)
        if str(dmg_model) == "position":
            # 方案 A：不碰伤害组，写盘层用 dst/src（= 位置档缩放）
            m2 = 1.0
        elif alpha and alpha > 0:
            base = r["donor_eff"] or 1.0
            m = (h / base) ** float(alpha)
            lo, hi = dmg_clamp
            m2 = max(float(lo), min(float(hi), m))
            if abs(m2 - m) > 1e-9:
                clamped += 1
        else:
            m2 = 1.0
        e = r["e"]
        e["target_hp"] = target
        e["balance"] = {
            "hp_eff": int(round(h)), "hp_orig_eff": int(round(r["orig_eff"])),
            "bin": b, "draw_bin": s, "dmg_mult": round(m2, 4),
            "hp_ratio": round(h / (r["orig_eff"] or 1.0), 4),
            "dst_tier": r["dst_tier"], "dst_rate": round(r["dst_rate"], 6),
            "src_tier": r["src_tier"], "src_rate": round(r["src_rate"], 6),
        }
    # 多阶段「整场共用一个 Boss」：二阶段起跟随第一阶段的分层结果（同一个 Boss 同一份血量）
    groups_one = {}
    for _e in plan.get("units") or []:
        if _e.get("multiphase") and _e.get("mp_policy") == "one_boss":
            groups_one.setdefault(_e["multiphase"], []).append(_e)
    harmonized = 0
    for _gid, _es in groups_one.items():
        _es.sort(key=lambda x: int(x.get("phase") or 0))
        _lead = _es[0]
        _bal = _lead.get("balance")
        if not _bal:
            continue
        for _e in _es[1:]:
            if _e.get("target_hp") == _lead["target_hp"]:
                continue
            _e["target_hp"] = _lead["target_hp"]
            _b = dict(_bal)
            if _b.get("dst_tier"):
                _b["hp_eff"] = int(round(int(_lead["target_hp"]) * float(_b.get("dst_rate") or 1.0)))
            _e["balance"] = _b
            harmonized += 1

    # positions 跟着改（含被「整场共用一个 Boss」带过去的阶段）
    by_key = {_e["key"]: _e for _e in plan.get("units") or [] if _e.get("balance")}
    touched = 0
    for p in plan.get("positions") or []:
        e = by_key.get(p.get("unit"))
        if e is not None:
            p["target_hp"] = e["target_hp"]
            touched += 1
    dmg = [r["e"]["balance"]["dmg_mult"] for r in rows]
    summary = {
        "model": "quantile-lut",
        "source": ref.get("source"),
        "seed": seed, "k": kn, "jitter": int(jitter), "alpha": float(alpha),
        "dmg_model": str(dmg_model),
        "dmg_clamp": list(dmg_clamp) if str(dmg_model) != "position" else None,
        "hp_ratio": list(hp_ratio) if hp_ratio else None,
        "units": n, "positions": touched,
        "pool": {"mean": round(statistics.mean(pool), 1),
                 "p10": round(_quant(pool, .1), 1), "p50": round(_quant(pool, .5), 1),
                 "p90": round(_quant(pool, .9), 1), "max": round(max(pool), 1)},
        "assigned": {"mean": round(statistics.mean(assigned), 1),
                     "p10": round(_quant(assigned, .1), 1), "p50": round(_quant(assigned, .5), 1),
                     "p90": round(_quant(assigned, .9), 1), "max": round(max(assigned), 1)},
        "ks": round(_ks(assigned, pool), 4),
        "tail_gt_1_5x": round(sum(1 for a, o in zip(assigned, pool)
                                  if abs(math.log2(a / o)) > 0.5) / float(n), 4),
        "rank_corr": round(_rank_corr(assigned, pool), 4),
        "ratio": {"min": round(min(a / o for a, o in zip(assigned, pool)), 4),
                  "p10": round(_quant([a / o for a, o in zip(assigned, pool)], .1), 4),
                  "p50": round(_quant([a / o for a, o in zip(assigned, pool)], .5), 4),
                  "p90": round(_quant([a / o for a, o in zip(assigned, pool)], .9), 4),
                  "max": round(max(a / o for a, o in zip(assigned, pool)), 4)},
        "dmg_mult": {"p10": round(_quant(dmg, .1), 3), "p50": round(_quant(dmg, .5), 3),
                     "p90": round(_quant(dmg, .9), 3), "clamped": clamped,
                     "model": str(dmg_model)},
        "target_hp": {"min": min(r["e"]["target_hp"] for r in rows),
                      "p50": int(_quant([r["e"]["target_hp"] for r in rows], .5)),
                      "max": max(r["e"]["target_hp"] for r in rows)},
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if isinstance(plan.get("meta"), dict):
        plan["meta"]["balance"] = summary
    log("[平衡] %d 个 Boss→Boss 单元：KS=%.4f 逐位>1.5x=%.1f%% 秩相关=%+.3f；"
        "有效血量 mean %.0f（原 %.0f）；写盘 raw hp %d..%d；伤害倍率 %.2f/%.2f/%.2f"
        % (n, summary["ks"], summary["tail_gt_1_5x"] * 100, summary["rank_corr"],
           summary["assigned"]["mean"], summary["pool"]["mean"],
           summary["target_hp"]["min"], summary["target_hp"]["max"],
           summary["dmg_mult"]["p10"], summary["dmg_mult"]["p50"], summary["dmg_mult"]["p90"]))
    return summary


def report(summary):
    if not summary:
        return "（没有平衡摘要）"
    lines = [
        "模型      = %s（k=%d jitter=%d alpha=%.2f）" % (
            summary["model"], summary["k"], summary["jitter"], summary["alpha"]),
        "单元      = %d（positions %d）" % (summary["units"], summary["positions"]),
        "原始池    = mean %.0f p10 %.0f p50 %.0f p90 %.0f max %.0f" % (
            summary["pool"]["mean"], summary["pool"]["p10"], summary["pool"]["p50"],
            summary["pool"]["p90"], summary["pool"]["max"]),
        "分配后    = mean %.0f p10 %.0f p50 %.0f p90 %.0f max %.0f" % (
            summary["assigned"]["mean"], summary["assigned"]["p10"], summary["assigned"]["p50"],
            summary["assigned"]["p90"], summary["assigned"]["max"]),
        "KS        = %.4f / 逐位>1.5x = %.1f%% / 秩相关 = %+.3f" % (
            summary["ks"], summary["tail_gt_1_5x"] * 100, summary["rank_corr"]),
        "血量倍率  = min %.2f / p10 %.2f / p50 %.2f / p90 %.2f / max %.2f（窗口 %s）" % (
            summary["ratio"]["min"], summary["ratio"]["p10"], summary["ratio"]["p50"],
            summary["ratio"]["p90"], summary["ratio"]["max"],
            "%s~%s" % tuple(summary["hp_ratio"]) if summary.get("hp_ratio") else "关闭"),
        "写盘 raw  = %d .. %d（p50 %d）" % (
            summary["target_hp"]["min"], summary["target_hp"]["max"], summary["target_hp"]["p50"]),
        ("伤害口径  = 位置档缩放（dst/src；区域缩放比恒 1.00，不写派生倍率）"
         if summary.get("dmg_model", "position") == "position" else
         "伤害倍率  = p10 %.2f / p50 %.2f / p90 %.2f（被夹 %d）" % (
             summary["dmg_mult"]["p10"], summary["dmg_mult"]["p50"],
             summary["dmg_mult"]["p90"], summary["dmg_mult"]["clamped"])),
    ]
    return "\n".join(lines)


def _selftest():
    ref = {"version": 1, "tier_hp": {"7000": 2.0, "7010": 3.0},
           "npc_tier": {"1": 7000, "2": 7000},
           "map_tier": {"m1": 7000, "m2": 7010}}
    npc = {}
    for i in range(1, 41):
        # 偏态分布（乘性增长）：更接近真实 Boss 血量池，用于验证分层是否保住难度序
        npc[i] = {"hp": int(round(180.0 * (1.18 ** i)))}
        npc[100 + i] = {"hp": int(round(260.0 * (1.15 ** i)))}
    units, positions = [], []
    for i in range(1, 31):
        e = {"key": "u%02d" % i, "old_cls": "Boss", "new_cls": "Boss",
             "old_npc_id": i, "new_npc_id": 100 + i,
             "places": [{"map": "m1" if i % 2 else "m2"}], "target_hp": 999}
        units.append(e)
        positions.append({"unit": "u%02d" % i, "map": e["places"][0]["map"], "target_hp": 999})
    # 非 Boss 位置换入 Boss：也必须被平衡锚住（黄金树传送门守门位那一类）
    units.append({"key": "wg", "old_cls": "Basic", "new_cls": "Boss",
                  "old_npc_id": 5, "new_npc_id": 105, "places": [{"map": "m1"}],
                  "target_hp": 999})
    units.append({"key": "keep", "old_cls": "Basic", "new_cls": "Basic",
                  "old_npc_id": 1, "new_npc_id": 2, "places": [{"map": "m1"}], "target_hp": 7})
    plan = {"meta": {"seed": 3, "base_seed": "abc"}, "units": units, "positions": positions}
    s1 = apply_to_plan(plan, ref=ref, npc=npc, seed="abc", k=10, jitter=1, alpha=0.5, log=lambda *a: None)
    snap1 = [(e["key"], e["target_hp"], e["balance"]["hp_eff"]) for e in units[:-1]]
    s2 = apply_to_plan(plan, ref=ref, npc=npc, seed="abc", k=10, jitter=1, alpha=0.5, log=lambda *a: None)
    snap2 = [(e["key"], e["target_hp"], e["balance"]["hp_eff"]) for e in units[:-1]]
    assert s1 and s2 and snap1 == snap2, "同种子两次结果不一致"
    assert plan["units"][-1]["target_hp"] == 7, "非 Boss 单元被改了"
    assert all(e["target_hp"] > 0 for e in units[:-1]), "target_hp 非正"
    assert all(p["target_hp"] > 0 for p in positions), "positions 没跟上"
    assert s1["ks"] < 0.2, "分配分布偏差过大：%.3f" % s1["ks"]
    assert s1["rank_corr"] > 0.9, "难度序没保住：%.3f" % s1["rank_corr"]
    # 伤害口径 A（默认）：位置档缩放，计划里不写派生倍率
    assert s1.get("dmg_model") == "position", "默认伤害口径不是位置档"
    assert all(abs(e["balance"]["dmg_mult"] - 1.0) < 1e-9
               for e in units if e.get("balance")), "位置档口径仍写了派生伤害倍率"
    # 备选口径 derived 仍可用（派生倍率 + clamp）
    plan_d = {"meta": {"base_seed": "abc"}, "units": [dict(e) for e in units], "positions": []}
    for _e in plan_d["units"]:
        _e.pop("balance", None)
    sd = apply_to_plan(plan_d, ref=ref, npc=npc, seed="abc", k=10, jitter=1, alpha=0.5,
                       dmg_model="derived", log=lambda *a: None)
    assert sd and sd["dmg_model"] == "derived" and sd["dmg_mult"]["p50"] > 0.2, "派生伤害口径异常"
    wg = next(e for e in units if e["key"] == "wg")
    assert wg.get("balance"), "非Boss→Boss 位置没被平衡"
    assert all(0.85 - 1e-9 <= e["balance"]["hp_ratio"] <= 1.25 + 1e-9
               for e in units if e.get("balance")), "有位置的血量倍率越窗"
    # 多阶段「整场共用一个 Boss」：二阶段跟随第一阶段（同一个 Boss、同一份血量）
    mp_units = [
        {"key": "mp1", "old_cls": "Boss", "new_cls": "Boss", "multiphase": "g",
         "mp_policy": "one_boss", "phase": 1, "old_npc_id": 1, "new_npc_id": 101,
         "places": [{"map": "m1"}], "target_hp": 999},
        {"key": "mp2", "old_cls": "Boss", "new_cls": "Helper", "multiphase": "g",
         "mp_policy": "one_boss", "phase": 2, "old_npc_id": 1, "new_npc_id": 101,
         "places": [{"map": "m1"}], "target_hp": 999},
    ]
    mp_pos = [{"unit": "mp1", "map": "m1", "target_hp": 999},
              {"unit": "mp2", "map": "m1", "target_hp": 999}]
    plan3 = {"meta": {"base_seed": "abc"}, "units": mp_units + units[:-1],
             "positions": mp_pos + positions}
    s4 = apply_to_plan(plan3, ref=ref, npc=npc, seed="abc", log=lambda *a: None)
    assert s4 and mp_units[0]["target_hp"] == mp_units[1]["target_hp"], \
        "共用 Boss 的两阶段血量不一致"
    assert all(p["target_hp"] == mp_units[0]["target_hp"] for p in mp_pos), \
        "共用 Boss 的 positions 没跟上"
    plan2 = {"meta": {"base_seed": "abc"}, "units": [dict(e) for e in units], "positions": []}
    for e in plan2["units"]:
        e.pop("balance", None)
    s3 = apply_to_plan(plan2, ref=ref, npc=npc, seed="zzz", log=lambda *a: None)
    assert s3 and any((a["target_hp"] != b["target_hp"]) for a, b in zip(plan2["units"], units)), \
        "换种子后血量完全没变"
    print("PASS 平衡 LUT：同种子可复现 / 换种子有变化 / 非 Boss→Boss 也平衡 / "
          "血量倍率 %.2f~%.2f 窗口内 / 伤害=位置档（比值 1.00）/ KS %.3f / 秩相关 %.2f"
          % (s1["ratio"]["min"], s1["ratio"]["max"], s1["ks"], s1["rank_corr"]))


def main(argv):
    ap = argparse.ArgumentParser(description="Boss 血量分布平衡（固定 LUT）")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--ref", default=REF_PATH)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--jitter", type=int, default=DEFAULT_JITTER)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--dmg-clamp", nargs=2, type=float, default=list(DEFAULT_DMG_CLAMP))
    ap.add_argument("--hp-ratio", nargs=2, type=float, default=list(DEFAULT_HP_RATIO),
                    help="有效血量 / 位置原有效血量 的允许窗口（默认 0.85 1.25）")
    ap.add_argument("--dmg-model", choices=["position", "derived"], default=DEFAULT_DMG_MODEL,
                    help="伤害口径：position=位置档缩放（默认，方案 A）；derived=血量派生倍率")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        _selftest()
        return 0
    if not a.plan:
        ap.error("需要 --plan（或 --selftest）")
    ref = load_ref(a.ref)
    if not ref:
        raise SystemExit("缺少参考表：%s（先跑 balance_ref.py）" % a.ref)
    plan = json.load(io.open(a.plan, encoding="utf-8"))
    summ = apply_to_plan(plan, ref=ref, seed=a.seed, k=a.k, jitter=a.jitter,
                         alpha=a.alpha, dmg_clamp=tuple(a.dmg_clamp),
                         hp_ratio=tuple(a.hp_ratio) if a.hp_ratio else None,
                         dmg_model=a.dmg_model)
    if summ is None:
        raise SystemExit("没有可平衡的单元")
    out = a.out or a.plan
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(plan, f, ensure_ascii=False, separators=(",", ":"))
    print("[平衡] 已写 %s" % out)
    if a.report:
        print(report(summ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
