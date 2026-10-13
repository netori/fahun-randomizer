# _patch_modroot.py — 让写入管线不再依赖开发期的目录约定（v2，精简版）
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))


def patch(path, pairs):
    p = os.path.join(WS, path)
    s = open(p, encoding="utf-8").read()
    ok = miss = 0
    for old, new in pairs:
        if old in s:
            s = s.replace(old, new, 1)
            ok += 1
        else:
            miss += 1
            print(f"      未匹配: {old[:70]!r}")
    ast.parse(s)                       # 先验证，再写盘
    open(p, "w", encoding="utf-8").write(s)
    print(f"  {'✓' if not miss else '⚠'} {path}: {ok} 处修改" + (f"，{miss} 处未匹配" if miss else ""))
    return miss == 0


# ── ① randgui.py：解析到 MOD 后发布到环境变量 ──
patch("randgui.py", [
    ('def find_mod_root(start=None):',
     '''def publish_mod_root(root):
    """把确认过的 MOD 根目录告诉写入管线。

    打包发出去以后，玩家把 exe 放在自己的 MOD 目录里，管线必须按这个目录干活，
    而不是按开发期的目录约定去猜（被 import 的模块拿不到界面上的变量，所以用环境变量传）。
    """
    if root:
        os.environ["CONVERGENCE_MOD_ROOT"] = os.path.abspath(root)
        return True
    return False


def find_mod_root(start=None):'''),
    ('''    root = mod_root or find_mod_root()''',
     '''    root = mod_root or find_mod_root()
    publish_mod_root(root)'''),
    ('''        self.mod_root = find_mod_root()''',
     '''        self.mod_root = find_mod_root()
        publish_mod_root(self.mod_root)'''),
])

# ── ② native_apply.py：MOD 动态解析 ──
patch("investigation/apply/native_apply.py", [
    ('MOD = os.path.normpath(os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))',
     '''def _resolve_mod_root():
    """MOD 根目录（含 mod/regulation.bin 的那一层）。

    顺序：① 环境变量（界面解析并发布）→ ② exe 或脚本所在目录自己就是 MOD
         → ③ 同级的 法魂mod* → ④ 开发期默认路径。
    打包发给玩家走 ①②，在开发目录里走 ③④。
    """
    env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if env and os.path.isdir(os.path.join(env, "mod")):
        return os.path.normpath(env)
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
    bases.append(os.path.dirname(ROOT))
    for base in bases:
        if os.path.isfile(os.path.join(base, "mod", "regulation.bin")):
            return os.path.normpath(base)
        cand = [d for d in glob.glob(os.path.join(base, "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]
        if cand:
            return os.path.normpath(sorted(cand)[0])
    return os.path.normpath(os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))


MOD = _resolve_mod_root()'''),
    ('import csv, json, os, struct, sys, time',
     'import csv, glob, json, os, struct, sys, time'),
])

# ── ③ native_deploy.py：打包分支改用同一来源 ──
patch("investigation/apply/native_deploy.py", [
    ('''    if getattr(sys, "frozen", False):                       # 打包运行：MOD 取工作区旁边的法魂mod 目录
        _cand = [d for d in glob.glob(os.path.join(os.path.dirname(sys.executable), "..", "法魂mod*")) if os.path.isdir(d)]
        if _cand:
            MOD = os.path.normpath(_cand[0])          # …\\THE_COVERAGE-随机开发''',
     '''    _env = os.environ.get("CONVERGENCE_MOD_ROOT")           # 界面解析并发布的 MOD 目录（打包版走这条）
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        MOD = os.path.normpath(_env)
    elif getattr(sys, "frozen", False):                     # 没传就猜：exe 所在目录，或它同级的法魂mod*
        _base = os.path.dirname(sys.executable)
        if os.path.isfile(os.path.join(_base, "mod", "regulation.bin")):
            MOD = os.path.normpath(_base)
        else:
            _cand = [d for d in glob.glob(os.path.join(_base, "..", "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]
            if _cand:
                MOD = os.path.normpath(sorted(_cand)[0])'''),
])

print("\n  ── 核对 ──")
for f, key in (("randgui.py", "publish_mod_root"),
               ("investigation/apply/native_apply.py", "_resolve_mod_root"),
               ("investigation/apply/native_deploy.py", "CONVERGENCE_MOD_ROOT")):
    s = open(os.path.join(WS, f), encoding="utf-8").read()
    print(f"    {key:<24} {f}: {s.count(key)} 处")
