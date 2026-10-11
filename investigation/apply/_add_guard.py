# 在 run() 返回前插入"守恒兜底"：不守恒就退回不做混档（合理度 1.0）
import os, re

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

if "_multiset_ok" in s:
    print("  已存在兜底，跳过")
    raise SystemExit(0)

helper = '''

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
'''
s = s.replace("\ndef run(items, cfg, seed=None):", helper + "\n\ndef run(items, cfg, seed=None):", 1)

# 在 run() 里最后一个 return plan 之前插入兜底
anchor = "    return plan, pools, seed"
idx = s.index("def run(items, cfg, seed=None):")
ridx = s.index(anchor, idx)
guard = '''    # 守恒兜底：不成立就退回"不做跨档/混池"的版本（该版本已逐配置验证守恒）
    if not _multiset_ok(plan, pools) and not cfg.get("_safe"):
        _c = dict(cfg); _c["_safe"] = True; _c["coherence"] = 1.0
        _p2, _pools2, _s2 = run(items, _c, seed)
        if _multiset_ok(_p2, _pools2):
            return _p2, _pools2, _s2
'''
s = s[:ridx] + guard + s[ridx:]
open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  兜底已插入")
