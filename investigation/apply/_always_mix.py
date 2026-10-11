# _always_mix.py — 混池永远存在（近战护甲+卢恩始终自由互换）；合理度只控制"武器混入比例"和"档位混入比例"
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

old = '''    _mixed_ratio = max(0.0, min(0.66, (1.0 - _coh) * 0.66))
    if _cross_domain_ok(cfg) and _mixed_ratio > 0.0:'''
new = '''    # 武器混入比例：合理度 100% → 0（武器自己玩）；越低越多，上限 66%
    _mixed_ratio = max(0.0, min(0.66, (1.0 - _coh) * 0.66))
    # 混池（近战护甲 + 卢恩）**永远存在**：护甲↔卢恩从一开始就是完全随机的（用户规则）
    if _cross_domain_ok(cfg):'''
assert old in s, "找不到混池触发段"
s = s.replace(old, new, 1)
open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  混池已改为永远存在（武器比例仍受合理度控制）")
