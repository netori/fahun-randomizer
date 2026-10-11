# _patch_tier3.py — 武器池按“逐单元档位”拆分（build_pools 只给了武器一个整池，取中位数拆不开）
import ast, os

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
P = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")
src = open(P, encoding="utf-8").read()
before = src

old = '''        dom, rank = _pool_rank(pk, meta.get("units") or [], items)
        if dom == "weapon":
            # 武器没有"部位/卢恩等级"，改用「该武器所在格子所处地区」的档位；
            # 否则所有武器都被算成同一个 2 档 → 连 100% 合理度也能任意跨档
            _ts = []
            for _u in (meta.get("units") or []):
                try:
                    _ts.append(_unit_tier_any(_u, items))
                except Exception:
                    pass
            if _ts:
                _ts.sort()
                rank = _ts[len(_ts) // 2]'''
new = '''        dom, rank = _pool_rank(pk, meta.get("units") or [], items)
        if dom == "weapon":
            # build_pools 把**全部武器**放在一个池里，取中位数拆不开 →
            # 这里逐单元按档位分桶（档位 = 格子所在地区），否则 100% 也会跨档
            _wunits = meta.get("units") or []
            _wdone = False
            for _u in _wunits:
                try:
                    _t = bucket_of(_unit_tier_any(_u, items))
                except Exception:
                    _t = 2
                _wkey = ("weapon", _t, "any")
                _slot = merged.setdefault(_wkey, {"kind": meta.get("kind", "item"), "units": []})
                _slot["units"].append(_u)
                _wdone = True
            if _wdone:
                continue'''

assert old in src, "找不到武器档位段落"
src = src.replace(old, new, 1)
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
now = open(P, encoding="utf-8").read()
print(f"  ✓ 已写入（{len(before)} → {len(src)} 字符）｜ 含新逻辑: {'_wdone' in now} ｜ mtime: {os.path.getmtime(P):.0f}")
