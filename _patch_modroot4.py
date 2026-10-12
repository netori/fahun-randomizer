# _patch_modroot4.py — 在 relocate() 里于"真正写入前"重新确定 MOD
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "native_deploy.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

OLD = '''    def relocate(ws=None):
        """把各模块的路径常量改到真实工作区（打包成 exe 后 __file__ 指向临时目录，必须重定位）"""
        ws = ws or workspace_of()
        if not ws:
            raise FileNotFoundError("找不到工作区（请把 exe 放在 随机mod 目录下运行）")'''

NEW = '''    def relocate(ws=None):
        """把各模块的路径常量改到真实工作区（打包成 exe 后 __file__ 指向临时目录，必须重定位）

        同时在这里重新确定 MOD 根目录。原因：界面/命令行把解析结果放进
        CONVERGENCE_MOD_ROOT，但打包运行时模块往往在界面解析之前就被 import 了，
        那时读到的 MOD 是错的 —— 所以必须等到"真正要写入"这一刻再读一次。
        """
        _env = os.environ.get("CONVERGENCE_MOD_ROOT")
        if _env and os.path.isdir(os.path.join(_env, "mod")):
            globals()["MOD"] = os.path.normpath(_env)
        elif not os.path.isdir(os.path.join(globals().get("MOD", "") or "", "mod")):
            _base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
            for _c in (_base, os.path.dirname(_base)):
                if os.path.isfile(os.path.join(_c, "mod", "regulation.bin")):
                    globals()["MOD"] = os.path.normpath(_c)
                    break
        ws = ws or workspace_of()
        if not ws:
            raise FileNotFoundError("找不到工作区（请把 exe 放在 随机mod 目录下运行）")'''

if OLD not in s:
    print("  ✗ 未匹配到 relocate 原文，未改动")
    raise SystemExit(1)
s = s.replace(OLD, NEW, 1)
ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n"))
print("  ✓ relocate() 已加入「写入前重新确定 MOD」")

# 顺便：凡 targets 里的 MOD 都改用刚确定的值
s2 = open(p, encoding="utf-8").read()
n_mod = s2.count('"MOD": MOD')
print(f"    targets 里引用 MOD 的地方: {n_mod} 处（它们读的是 globals()['MOD']，已同步）")
print(f"    环境变量读取: {s2.count('CONVERGENCE_MOD_ROOT')} 处")
print(f"    exe 目录兜底: {s2.count('sys.executable if getattr(sys, \"frozen\", False)')} 处")
