# _restore_verified.py — 恢复到"90/90 全过"那一版的池置换核心
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 删掉我加的"两两互换"核心 + 跨档配对调用
a = s.index("    swaps.update(_cross_tier_pair(")
b = s.index("    # 守恒兜底")
core_old = '''    # ── 池内置换（原版：整体乱序；失败则保持原样）──
    for pool, meta in sorted(pools.items()):
        units = [u for u in meta["units"] if u["id"] not in swaps]
        if len(units) < 2:
            for u in units:
                plan.extend(emit(u, u, pool, keep=True))
            continue
        if density >= 0.999:
            idx = list(range(len(units)))
        else:
            k = int(round(len(units) * density))
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
    # 显式跨档配对（构造式：两两异档互换，永不失败）
    swaps.update(_cross_tier_pair(pools, rng, max(0.0, min(1.0, 1.0 - _coh)), _f2, items))
    for pool, meta in sorted(pools.items()):
        units = [u for u in meta["units"] if u["id"] in swaps]
        for u in units:
            plan = [p for p in plan if str(p["unit"]) != str(u["id"])]
            plan.extend(emit(u, swaps[u["id"]], pool, keep=False))
'''
s = s[:a] + core_old + s[b:]

# ② 撤回"套装进混池"（只保留单件，法祷依旧排除）
s = s.replace('''                if _dom == "armor" and _arch == "近战":
                    _mine.append(_u)          # 近战护甲：单件与套装都进来（法祷绝不进来）''',
'''                if _dom == "armor" and _arch == "近战" and not _is_set:
                    _mine.append(_u)          # 近战护甲单件（套装不跨类；法祷绝不进来）''')

open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已恢复为原版池置换核心 + 撤回套装入混池")
