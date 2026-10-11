# _melee_singles.py — 用户规则：近战护甲全是单件；只有法祷护甲才是"套装+散件"并单独成池
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

old = '''    complete = {kk: m for kk, m in sets.items() if len(m) == 4}
    set_pieces = {x for m in complete.values() for x in m.values()}

    if cfg.get("sets", True):
        for (base, arch), m in complete.items():'''
new = '''    complete = {kk: m for kk, m in sets.items() if len(m) == 4}
    # 用户规则：**只有法祷护甲**才做"套装"捆绑；近战护甲一律按单件处理
    #（所以近战护甲每一件都能自由地和卢恩互换）
    _bundled = {kk: m for kk, m in complete.items() if kk[1] in CASTER_ARCH} if cfg.get("sets", True) else {}
    set_pieces = {x for m in _bundled.values() for x in m.values()}

    if cfg.get("sets", True):
        for (base, arch), m in _bundled.items():'''
assert old in s, "找不到套装捆绑段"
s = s.replace(old, new, 1)
open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已改：只对法祷护甲做套装捆绑，近战护甲全部按单件")
