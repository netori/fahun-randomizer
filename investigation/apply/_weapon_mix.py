# _weapon_mix.py — 跨类混池改为"池合并"实现（构造性保证守恒），并按用户规则控制武器混入比例
#   规则：
#     · 混池成员 = 近战护甲单件 + 卢恩 + 一部分武器（比例随合理度上升，上限 66%）
#     · 合理度 100% → 武器混入比例 0%（武器只跟自己随机）
#     · 法祷护甲（含套装）一律不得进入混池
#     · 套装一律不参与混池（整套换进卢恩槽在机制上是空操作）
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 移除之前那套"显式配对"（它在自检下过不去）
a = s.index("    _coh = min(1.0, max(0.0, float(cfg.get(\"coherence\", 1.0))))\n    _f2 = _coh >= 0.5\n    swaps = {}")
b = s.index("    base_pools = collections.OrderedDict(pools)")
s = s[:a] + "    _coh = min(1.0, max(0.0, float(cfg.get(\"coherence\", 1.0))))\n    _f2 = _coh >= 0.5\n    swaps = {}\n" + s[b:]

# ② 在池合并处加入"混池"
old = s[s.index("    base_pools = collections.OrderedDict(pools)"):s.index("    density = float(cfg.get(\"density\", 1.0))")]
new = '''    base_pools = collections.OrderedDict(pools)
    _xd = False
    # ── 跨类混池（池合并实现 → 池内完整置换 → 守恒天然成立）──
    #    成员：近战护甲单件 + 卢恩 + 一部分武器（比例 = (1-合理度) × 66%，上限 66%）
    _mixed_ratio = max(0.0, min(0.66, (1.0 - _coh) * 0.66))
    if _cross_domain_ok(cfg) and _mixed_ratio > 0.0:
        _mine, _runes, _weapons, _rest = [], [], [], []
        for _pk, _meta in base_pools.items():
            for _u in (_meta.get("units") or []):
                _dom, _rank = _pool_rank(_pk, [_u], items)
                _arch = _u.get("arch") or ""
                _is_set = bool(_u.get("parts"))
                if _dom == "armor" and _arch == "近战" and not _is_set:
                    _mine.append(_u)
                elif _dom == "rune" and not _is_set:
                    _runes.append(_u)
                elif _dom == "weapon" and not _is_set:
                    _weapons.append(_u)
                else:
                    _rest.append((_pk, _meta, _u))
        _wsel = int(round(len(_weapons) * _mixed_ratio))
        rng.shuffle(_weapons)
        _win, _wout = _weapons[:_wsel], _weapons[_wsel:]
        _mixed = _mine + _runes + _win
        # 把混池成员从原池里摘掉，留下的原池继续各自置换
        _mix_ids = {u["id"] for u in _mixed}
        _newpools = collections.OrderedDict()
        _newpools["混池·近战护甲+卢恩+武器"] = {"kind": "item", "units": _mixed}
        for _pk, _meta in base_pools.items():
            _keep = [u for u in (_meta.get("units") or []) if u["id"] not in _mix_ids]
            if _keep:
                _newpools[_pk] = dict(_meta, units=_keep)
        pools = _newpools
    merged = collections.OrderedDict()
    for pk, meta, dom, rank in _plist if False else [(k, v, None, 0) for k, v in []]:
        pass
    for pk, meta in pools.items():
        dom, rank = _pool_rank(pk, meta.get("units") or [], items)
        key = (dom, bucket_of(rank))
        if key not in merged:
            merged[key] = dict(meta, units=[])
        _have = {u["id"] for u in merged[key]["units"]}
        merged[key]["units"].extend([u for u in (meta.get("units") or []) if u["id"] not in _have])
    pools = collections.OrderedDict((f"{k[0]}·档组{k[1]}", v) for k, v in merged.items())
'''
s = s.replace(old, new)

# ③ 兼容度判断：默认开启（仅近战护甲/卢恩/武器混池）
s = s.replace('''    if cfg.get("cross_domain") is False:
        return False
    return True      # 默认开启：仅"近战护甲 ↔ 卢恩"按档位对齐互换（法祷一律排除）''',
'''    if cfg.get("cross_domain") is False:
        return False
    return True      # 默认开启：近战护甲 + 卢恩 + 一部分武器 组成混池（法祷一律排除）''')
open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  weapon-mix 已写入")
