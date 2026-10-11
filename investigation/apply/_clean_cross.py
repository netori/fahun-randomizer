# _clean_cross.py — 跨档配对改为"落盘前写入 swaps"，删掉会破坏守恒的"删行重落盘"
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 删掉"跨档配对 + 删行重落盘"整段
a = s.index("    # 显式跨档配对（构造式：两两异档互换，永不失败）")
tail = [m for m in ("    # 守恒兜底", "    return plan, pools, seed") if m in s[a:]]
b = a + min(s[a:].index(m) for m in tail)
s = s[:a] + s[b:]

# ② 在池落盘之前先算好跨档互换（池循环会把它一并应用，守恒由 2-循环保证）
anchor = "    # ── 池内置换（原版：整体乱序；失败则保持原样）──"
s = s.replace(anchor,
              "    # 跨档配对：合理度越低，跨到别的档位的比例越高（0% → 尽量全跨；100% → 不跨）\n"
              "    swaps.update(_cross_tier_pair(pools, rng, max(0.0, min(1.0, 1.0 - _coh)), _f2, items))\n"
              + anchor, 1)

open(ENGINE, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已改为落盘前写入跨档互换；旧写法整段删除")
