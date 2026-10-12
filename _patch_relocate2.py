# _patch_relocate2.py — 用短锚点，在 deploy() 开头插入「重定位所有会写文件的路径」
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "native_deploy.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

ANCHOR = "    def deploy(plan_csv, sync_guide=True, log=print):\n        relocate()"
if ANCHOR not in s:
    # 退一步：只锚 def deploy 这一行，看看它后面到底是什么
    i = s.find("def deploy(plan_csv")
    print("  ✗ 锚点未匹配。实际内容如下（repr）:")
    print(repr(s[i:i + 160]))
    raise SystemExit(1)

BLOCK = '''    def deploy(plan_csv, sync_guide=True, log=print):
        relocate()
        # ── 打包版：把「所有会写文件的路径」重定位到 exe 旁边那份工作区 ──
        # 原因：这些目录是按"代码所在位置"拼的，打包后那指向临时解包目录，
        # 于是它会去解包目录里找备份/写日志，而真正的备份在 exe 旁边 —— 表现就是
        # 「系统找不到指定的路径」。relocate() 只覆盖了一部分模块，这里补齐。
        _env = os.environ.get("CONVERGENCE_MOD_ROOT")
        if _env and os.path.isdir(os.path.join(_env, "mod")):
            globals()["MOD"] = os.path.normpath(_env)
        _ws = workspace_of()
        if _ws:
            _ad = os.path.join(_ws, "investigation", "apply")
            _mod = globals().get("MOD")
            _targets = {
                "native_deploy": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod, "WS": _ws,
                                  "LOG": os.path.join(_ad, "logs"),
                                  "CAT": os.path.join(_ws, "investigation", "randomization-catalog-review")},
                "native_guide": {"APPLY": _ad, "MOD": _mod},
                "native_apply": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod},
                "_guide_rebuild": {"APPLY": _ad},
                "_guide_fit": {"APPLY": _ad},
                "_guide_audit": {"APPLY": _ad},
                "fix_guide": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod},
            }
            for _n, _c in _targets.items():
                _m = sys.modules.get(_n)
                if _m:
                    for _k, _v in _c.items():
                        try:
                            setattr(_m, _k, _v)
                        except Exception:
                            pass
            globals()["WS"] = _ws
            for _d in ("backup", "logs", "out", "work/msg/zh"):
                os.makedirs(os.path.join(_ad, _d), exist_ok=True)
            if callable(log):
                log(f"[定位] 工作区 {_ws} ｜ MOD {_mod}")

        t = time.strftime("%Y%m%d_%H%M%S")'''

s = s.replace(ANCHOR, BLOCK, 1)
ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n"))
print("  ✓ 已插入重定位块")

s2 = open(p, encoding="utf-8").read()
for k in ("native_deploy", "_guide_rebuild", "_guide_audit", "[定位]", "work/msg/zh"):
    print(f"    {k:<20} {s2.count(k)} 处")
