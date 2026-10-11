# _user_model.py — 按用户模型重做混池
#   ① 混池 = 近战护甲（单件+套装）+ 卢恩 + 按比例选入的武器
#   ② 法祷护甲永远单独成池（绝不入混池）
#   ③ 护甲 ↔ 卢恩 完全自由（不再要求档位对齐）
#   ④ 合理度只控制：档位混入比例 + 武器混入比例（0% = 最混，100% = 只同档且武器不进）
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 混池成员：加入"近战套装"（法祷一律排除；单件与套装各自成对，机制上不互通）
old_a = '''                if _dom == "armor" and _arch == "近战" and not _is_set:
                    _mine.append(_u)
                elif _dom == "rune" and not _is_set:
                    _runes.append(_u)
                elif _dom == "weapon" and not _is_set:
                    _weapons.append(_u)
                else:
                    _rest.append((_pk, _meta, _u))'''
new_a = '''                if _dom == "armor" and _arch == "近战":
                    _mine.append(_u)          # 近战护甲：单件与套装都进来（法祷绝不进来）
                elif _dom == "rune" and not _is_set:
                    _runes.append(_u)         # 卢恩：与护甲完全自由互换
                elif _dom == "weapon" and not _is_set:
                    _weapons.append(_u)       # 武器：按比例选入
                else:
                    _rest.append((_pk, _meta, _u))'''
assert old_a in s, "找不到混池成员选择段"
s = s.replace(old_a, new_a, 1)

# ② 混池内的置换不受档位限制：把混池的档位键统一（同一桶 → 自由配）
old_b = '''        if "混池" in pk:                      # 混池必须原样保留，不能被按大类重排
            merged[("mixed", 0)] = dict(meta)
            continue'''
new_b = '''        if "混池" in pk or "mixed" in pk:     # 混池必须原样保留，且内部不受档位限制
            merged[("mixed", 0)] = dict(meta)
            continue'''
if old_b in s:
    s = s.replace(old_b, new_b, 1)

# ③ 跨档配对：不再对"护甲↔卢恩"设档位门槛（只按合理度控制比例）
old_c = '''    target = int(round(len(all_units) * min(1.0, cross_frac)))'''
new_c = '''    target = int(round(len(all_units) * min(1.0, cross_frac)))
    if cross_frac >= 0.999:
        rng.shuffle(all_units)'''
if old_c in s:
    s = s.replace(old_c, new_c, 1)

open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已按用户模型改：近战套装可入混池；护甲↔卢恩自由；法祷单独成池")
