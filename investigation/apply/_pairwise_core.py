# _pairwise_core.py — 用"两两互换"替换原来的整体乱序（构造式：永不失败、天然守恒）
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# 找到池置换整段，整体替换为两两互换
start = s.index("    for pool, meta in sorted(pools.items()):")
end = s.index("    # 显式跨档配对：合理度越低，跨档比例越高")
new = '''    # ── 池内两两互换（构造式）：不合法的一对就跳过，合法的立刻换 ──
    #    每个互换都是 2-循环 → 守恒天然成立；不依赖"整体乱序"能否一次成功
    for pool, meta in sorted(pools.items()):
        units = list(meta["units"])
        if len(units) < 2:
            continue
        k_target = int(round(len(units) * min(1.0, max(0.0, density))))
        if k_target < 2:
            continue
        order = list(range(len(units)))
        rng.shuffle(order)
        done = set()
        i = 0
        while i < len(order) - 1 and len(done) < k_target:
            ia = order[i]
            if ia in done:
                i += 1
                continue
            matched = False
            for j in range(i + 1, len(order)):
                ib = order[j]
                if ib in done or ib == ia:
                    continue
                ua, ub = units[ia], units[ib]
                if not _pair_ok(ua, ub, _f2) or not _pair_ok(ub, ua, _f2):
                    continue
                swaps[ua["id"]] = ub
                swaps[ub["id"]] = ua
                done.add(ia); done.add(ib)
                matched = True
                break
            i += 1
        for u in units:
            if u["id"] in swaps:
                plan.extend(emit(u, swaps[u["id"]], pool, keep=False))
            else:
                plan.extend(emit(u, u, pool, keep=True))
'''
s = s[:start] + new + s[end:]
open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已换成两两互换核心")
