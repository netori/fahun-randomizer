# _patch_tier2.py — 武器/混池改用单元自带的 _tier（更准，且武器单元没有 cells）
import ast, os

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
P = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")
src = open(P, encoding="utf-8").read()
before = src

# 统一的档位取值：单元自带 _tier 优先，其次按格子地区，最后 2
HELPER = '''
def _unit_tier_any(u, items):
    """取单元档位：优先用单元自带的 _tier，其次按格子所在地区，最后 2（中位）"""
    t = u.get("_tier")
    if isinstance(t, (int, float)):
        return int(t)
    try:
        return int(_tier_of_unit(u))
    except Exception:
        return 2

'''
if "_unit_tier_any" not in src:
    anchor = "def _unit_tier(u, items):"
    assert anchor in src
    src = src.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

# ① 武器池：用 _unit_tier_any
old1 = '''            _ts = []
            for _u in (meta.get("units") or []):
                try:
                    _ts.append(_tier_of_unit(_u))
                except Exception:
                    pass'''
new1 = '''            _ts = []
            for _u in (meta.get("units") or []):
                try:
                    _ts.append(_unit_tier_any(_u, items))
                except Exception:
                    pass'''
if old1 in src:
    src = src.replace(old1, new1, 1)

# ② 混池：同样用 _unit_tier_any
old2 = '''                try:
                    _t = bucket_of(_unit_tier(_u, items))
                except Exception:
                    _t = 2'''
new2 = '''                try:
                    _t = bucket_of(_unit_tier_any(_u, items))
                except Exception:
                    _t = 2'''
if old2 in src:
    src = src.replace(old2, new2, 1)

if src != before:
    ast.parse(src)
    open(P, "w", encoding="utf-8").write(src)
    print(f"  ✓ 已写入（{len(before)} → {len(src)} 字符）")
else:
    print("  无需改动")
now = open(P, encoding="utf-8").read()
print(f"  核对: _unit_tier_any 定义 {'有' if 'def _unit_tier_any' in now else '无'} ｜ "
      f"武器处用新函数 {'是' if '_unit_tier_any(_u, items)' in now else '否'}")
print(f"  mtime: {os.path.getmtime(P):.0f}")
