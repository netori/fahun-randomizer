# _patch_joins.py — 混池改为按 joins 分组构造（支持"两个混合、一个独自"）
#   规则：
#     · joins = [["rune","weapon"], ["armor"]] 这类分组，每组内共用一个混池
#     · 只有 size>=2 的组才真正产生混池；单元素组 = 该域自己随
#     · 未出现在任何组里的域 = 完全不动（各自随机）
#     · 法祷护甲永不进混池
#     · 武器只有在"与某组同组"时才按 (1-合理度)*66% 掺入
#     · joins 为空时退回旧行为：cross_domain 为真 → 全部已勾选域合成一个混池
import ast, os

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
P = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")
src = open(P, encoding="utf-8").read()
before = src

old = '''    if _cross_domain_ok(cfg):
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
        pools = _newpools'''

new = '''    # ── 混池分组（joins）──
    _groups = [set(g) for g in (cfg.get("joins") or []) if len(set(g)) >= 2]
    if not _groups and _cross_domain_ok(cfg):
        # 旧行为（向后兼容）：cross_domain 为真 → 已勾选的域合成一个混池
        _groups = [set(cfg.get("domains") or ["rune", "armor", "weapon"])]
    if _groups:
        _pool_of_u = {}                       # 单元 -> 原池键
        for _pk, _meta in base_pools.items():
            for _u in (_meta.get("units") or []):
                _pool_of_u[_u["id"]] = _pk
        _mix_ids = set()
        _newpools = collections.OrderedDict()

        def _dom_of(_u):
            _pk = _pool_of_u.get(_u["id"], "")
            return _pool_rank(_pk, [_u], items)[0]

        for _gi, _g in enumerate(_groups):
            _mine, _runes, _weapons = [], [], []
            for _pk, _meta in base_pools.items():
                for _u in (_meta.get("units") or []):
                    if _u["id"] in _mix_ids:
                        continue
                    _dom = _dom_of(_u)
                    if _dom not in _g:
                        continue
                    _arch = _u.get("arch") or ""
                    _is_set = bool(_u.get("parts"))
                    if _dom == "armor":
                        # 法祷护甲（含套装）永不进混池；近战套装整组不拆
                        if _arch == "近战" and not _is_set:
                            _mine.append(_u)
                    elif _dom == "rune" and not _is_set:
                        _runes.append(_u)
                    elif _dom == "weapon" and not _is_set:
                        _weapons.append(_u)
            # 武器只在"该组含武器"时按比例掺入
            _win = []
            if "weapon" in _g and _weapons:
                _wsel = int(round(len(_weapons) * _mixed_ratio))
                rng.shuffle(_weapons)
                _win = _weapons[:_wsel]
            _mixed = _mine + _runes + _win
            if len(_mixed) >= 2:
                _nm = "混池·" + "+".join(sorted(_g))
                _newpools[_nm] = {"kind": "item", "units": _mixed}
                _mix_ids |= {u["id"] for u in _mixed}
        if _mix_ids:
            for _pk, _meta in base_pools.items():
                _keep = [u for u in (_meta.get("units") or []) if u["id"] not in _mix_ids]
                if _keep:
                    _newpools[_pk] = dict(_meta, units=_keep)
            pools = _newpools'''

assert old in src, "找不到混池构造段"
src = src.replace(old, new, 1)
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
now = open(P, encoding="utf-8").read()
print(f"  ✓ 已写入（{len(before)} → {len(src)} 字符）｜ 含 joins 分组: {'_groups' in now}")
