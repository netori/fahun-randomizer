# _dedup_core.py — 删掉旧落盘块，把跨档配对移到新核心之前
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

# ① 删除从"显式跨档配对"到旧落盘块结束之间的整段
a = s.index("    # 显式跨档配对：合理度越低，跨档比例越高")
# 找到这一段结束：下一个 8 空格缩进的关键语句（守恒兜底 / return / def）
tail_markers = [m for m in ("    # 守恒兜底", "    return plan, pools, seed", "\n\ndef _multiset_ok") if m in s[a:]]
assert tail_markers, "找不到段尾标记"
b = a + min(s[a:].index(m) for m in tail_markers)
old_block = s[a:b]

# ② 从旧块里抽出跨档配对调用，放到新核心之前
call_line = "    swaps.update(_cross_tier_pair(pools, rng, max(0.0, min(1.0, 1.0 - _coh)), _f2, items))\n"
anchor = "    # ── 池内两两互换（构造式）"
s = s[:a] + s[b:]
s = s.replace(anchor, call_line + anchor, 1)
open(ENGINE, "w", encoding="utf-8").write(s)

import ast
ast.parse(s)
print("  已删除旧落盘块；跨档配对接入新核心")
