# _compat_model.py — 把"合理度"改成"两个池子兼容度下限"模型
#   兼容度 = 1 - |档次差| / 4（档次：卢恩 5 档、装备 4 档=臂/腿/胸/头）
#   合理度滑块 = 允许的最小兼容度：1.0=只同档；0.75=相邻一档；0.5=两档；0.25=三档；0=全放开
import os, re, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 用兼容度模型替换原来的"池内置换"逻辑
old = '''        sub = [units[i] for i in idx]
        cand = None
        for _ in range(2000):
            trial = sub[:]
            rng.shuffle(trial)
            if not all(trial[i]["id"] != sub[i]["id"] for i in range(len(sub))):
                continue
            if all(_pair_ok(sub[i], trial[i], _f2) for i in range(len(sub))) and \\
               all(abs(int(sub[i].get("_tier", 2)) - int(trial[i].get("_tier", 2))) <= _allow_gap
                   for i in range(len(sub))):
                cand = trial
                break
        if cand is None:
            # 整体乱序找不到 → 按「同档次内两两互换」，保证同档、守恒、且换得尽量多
            cand = sub[:]
            for _t, grp in itertools.groupby(sorted(range(len(sub)), key=lambda i: sub[i].get("_tier", 2)),
                                             key=lambda i: sub[i].get("_tier", 2)):
                g = list(grp)
                rng.shuffle(g)
                for a, b in zip(g[0::2], g[1::2]):
                    if _pair_ok(sub[a], sub[b], _f2):
                        cand[a], cand[b] = sub[b], sub[a]'''
new = '''        sub = [units[i] for i in idx]
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
            cand = sub[:]'''
assert old in s, "找不到池内置换段"
s = s.replace(old, new, 1)

# ② 池级兼容度：把"池"按 档次 归位，然后按兼容度配对（跨池两两互换，天然守恒）
COMPAT = '''

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
        for k, v in (("学徒", 0), ("熟练", 1), ("精通", 2), ("大师", 3), ("幽影", 4)):
            if k in poolkey:
                return dom, v
        return dom, 2
    for name, v in _PART_RANK.items():
        if f":{name}" in poolkey:
            return dom, v
    return dom, 2


def _compat(r1, r2, n_max):
    """兼容度 = 1 - |档次差| / 4"""
    return max(0.0, 1.0 - abs(r1 - r2) / 4.0)


def _cross_domain_ok(cfg):
    return bool(cfg.get("cross_domain", False))
'''
s = s.replace("\ndef _pair_ok(", COMPAT + "\n\ndef _pair_ok(", 1)

# ③ run()：按兼容度把池配对，两两互换（守恒由 2-循环保证）
old2 = '''    density = float(cfg.get("density", 1.0))
    _coh = min(1.0, max(0.0, float(cfg.get("coherence", 1.0))))
    _f2 = _coh >= 0.5                                   # 低合理度时不要求倾向上的一致
    _allow_gap = int(round((1 - _coh) * 4.999))         # 允许跨多少档：1.0→0，0.0→5'''
new2 = '''    density = float(cfg.get("density", 1.0))
    _coh = min(1.0, max(0.0, float(cfg.get("coherence", 1.0))))
    _f2 = _coh >= 0.5
    _allow_gap = 5'''
assert old2 in s, "找不到 run 的密度段"
s = s.replace(old2, new2, 1)

# 在 run 里、生成 plan 之前插入"兼容度配对"阶段
old3 = '''    rng = random.Random(seed)
    plan = []'''
new3 = '''    rng = random.Random(seed)
    plan = []
    # ── 兼容度配对：把池按 (大类, 档次) 归位，按"兼容度 ≥ 合理度"把池两两配对互换 ──
    if _coh < 0.999:
        plist = []
        for pk, meta in pools.items():
            us = meta.get("units") or []
            if not us:
                continue
            for u in us:
                if "_dom" not in u:
                    d, _p, _a, t = _unit_info(u, items)
                    u["_dom"], u["_tier"] = d, t
            dom, rank = _pool_rank(pk, us, items)
            plist.append([pk, meta, dom, rank, list(us)])
        pairs = []
        for i in range(len(plist)):
            for j in range(i + 1, len(plist)):
                di, ri, ui = plist[i][2], plist[i][3], plist[i][4]
                dj, rj, uj = plist[j][2], plist[j][3], plist[j][4]
                same_dom = (di == dj)
                if not same_dom and not _cross_domain_ok(cfg):
                    continue
                compat = _compat(ri, rj, 4) if same_dom else max(0.0, _compat(ri, rj, 4) - 0.25)
                if compat + 1e-9 >= _coh:
                    pairs.append((compat, i, j))
        pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
        used = set()
        for compat, i, j in pairs:
            ui, uj = plist[i][4], plist[j][4]
            a_free = [u for u in ui if u["id"] not in used]
            b_free = [u for u in uj if u["id"] not in used]
            if len(a_free) < 1 or len(b_free) < 1:
                continue
            k = min(len(a_free), len(b_free))
            # 随机抽 k 对做互换（2-循环：天然守恒）
            ai = rng.sample(a_free, k)
            bj = rng.sample(b_free, k)
            for ua, ub in zip(ai, bj):
                if not _pair_ok(ua, ub, _f2) or not _pair_ok(ub, ua, _f2):
                    continue
                swaps[ua["id"]] = ub
                swaps[ub["id"]] = ua
                used.add(ua["id"]); used.add(ub["id"])'''
s = s.replace(old3, new3, 1)
# swaps 初始化 + 应用
s = s.replace('''    # ── 兼容度配对''', '''    swaps = {}
    # ── 兼容度配对''', 1)
s = s.replace('''        picked = {}
        for tgt, sco in zip(sub, cand):
            picked[tgt["id"]] = sco
        for u in units:
            if u["id"] in picked:
                plan.extend(emit(u, picked[u["id"]], pool, keep=False))
            else:
                plan.extend(emit(u, u, pool, keep=True))''',
'''        picked = {}
        for tgt, sco in zip(sub, cand):
            picked[tgt["id"]] = sco
        for u in units:
            if u["id"] in picked:
                plan.extend(emit(u, picked[u["id"]], pool, keep=False))
            elif u["id"] in swaps:
                plan.extend(emit(u, swaps[u["id"]], pool, keep=False))
            else:
                plan.extend(emit(u, u, pool, keep=True))''')
open(ENGINE, "w", encoding="utf-8").write(s)
print("  已写入兼容度模型 →", os.path.basename(ENGINE))
