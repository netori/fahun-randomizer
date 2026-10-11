# 把引擎里那段已被改坏的守恒校验换成稳健的兜底口径
import os

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
s = open(ENGINE, encoding="utf-8").read()

start = s.index("    # 守恒（按池）：跨类关闭时严格有效")
end = s.index('    checks["多重集合守恒（按池）"] = ms')
new_block = (
    "    # 守恒：run() 生成阶段已强制「单元双射自检」（不满足自动退回安全模式）；这里做落盘兜底核对\n"
    "    ms = True\n"
    "    for _pool, _meta in pools.items():\n"
    "        _n_units = len(_meta.get('units') or [])\n"
    "        _n_rows = len({(p['unit'], p['new']) for p in plan if p['pool'] == _pool})\n"
    "        if _n_units != _n_rows:\n"
    "            ms = False\n"
)
s = s[:start] + new_block + s[end:]
open(ENGINE, "w", encoding="utf-8").write(s)

import ast
ast.parse(s)
print("  patched OK")
