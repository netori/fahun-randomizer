# _patch_tier.py — 修正两处档位漏洞（用户实测：100% 仍跨档）
#   ① 武器一律被算成 2 档 → 改用「格子所在地区」的档位
#   ② 混池把所有档位并成一个池 → 按档位拆开
import ast, os, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
P = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")

print(f"  目标文件: {P}")
print(f"  存在: {os.path.exists(P)} ｜ 修改前 mtime: {os.path.getmtime(P):.0f} ｜ 大小: {os.path.getsize(P)}")
src = open(P, encoding="utf-8").read()
n0 = len(src)

# ① 武器按“格子所在地区”的档位
old1 = '''        dom, rank = _pool_rank(pk, meta.get("units") or [], items)'''
new1 = '''        dom, rank = _pool_rank(pk, meta.get("units") or [], items)
        if dom == "weapon":
            # 武器没有"部位/卢恩等级"，改用「该武器所在格子所处地区」的档位；
            # 否则所有武器都被算成同一个 2 档 → 连 100% 合理度也能任意跨档
            _ts = []
            for _u in (meta.get("units") or []):
                try:
                    _ts.append(_tier_of_unit(_u))
                except Exception:
                    pass
            if _ts:
                _ts.sort()
                rank = _ts[len(_ts) // 2]'''

# ② 混池按档位拆开
old2 = '''        if "混池" in pk:                      # 混池必须原样保留，不能被按大类重排
            merged[("mixed", 0)] = dict(meta)
            continue'''
new2 = '''        if "混池" in pk:
            # 混池必须原样保留（不能被按大类重排），但**必须按档位拆开**，
            # 否则所有档位并成一个池 → 连 100% 合理度都会跨档
            for _u in (meta.get("units") or []):
                try:
                    _t = bucket_of(_unit_tier(_u, items))
                except Exception:
                    _t = 2
                _slot = merged.setdefault(("mixed", _t),
                                          {"kind": meta.get("kind", "item"), "units": []})
                _slot["units"].append(_u)
            continue'''

changed = []
if new1.split("\n")[1].strip() in src:
    print("  ① 已打过，跳过")
else:
    assert old1 in src, "① 找不到 _pool_rank 调用"
    src = src.replace(old1, new1, 1)
    changed.append("① 武器按地区定档")

if "必须按档位拆开" in src:
    print("  ② 已打过，跳过")
else:
    assert old2 in src, "② 找不到混池合并处"
    src = src.replace(old2, new2, 1)
    changed.append("② 混池按档位拆分")

if changed:
    ast.parse(src)                       # 语法先校验，再落盘
    open(P, "w", encoding="utf-8").write(src)
    print(f"  已写入: {n0} → {len(src)} 字节 ｜ 改动: {changed}")
else:
    print("  无需改动")

now = open(P, encoding="utf-8").read()
print(f"  落盘核对: 大小 {len(now)} ｜ 含“必须按档位拆开”: {'必须按档位拆开' in now} ｜ 含“武器没有”: {'武器没有' in now}")
print(f"  新 mtime: {os.path.getmtime(P):.0f}")
