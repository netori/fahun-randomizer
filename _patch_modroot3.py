# _patch_modroot3.py — 整段替换 native_deploy 的 MOD 解析（CRLF 安全）
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "native_deploy.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

OLD = '''    if getattr(sys, "frozen", False):                       # 打包运行：MOD 取工作区旁边的法魂mod 目录
        _cand = [d for d in glob.glob(os.path.join(os.path.dirname(sys.executable), "..", "法魂mod*")) if os.path.isdir(d)]
        if _cand:
            MOD = os.path.normpath(_cand[0])          # …\\THE_COVERAGE-随机开发'''

NEW = '''    # MOD 目录来源：① 界面/命令行解析并发布的（打包版走这条）
    #             ② exe 自己所在目录就是 MOD
    #             ③ exe 同级的 法魂mod*（开发期布局）
    _env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        MOD = os.path.normpath(_env)
    elif getattr(sys, "frozen", False):
        _base = os.path.dirname(sys.executable)
        if os.path.isfile(os.path.join(_base, "mod", "regulation.bin")):
            MOD = os.path.normpath(_base)
        else:
            _cand = [d for d in glob.glob(os.path.join(_base, "..", "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]
            if _cand:
                MOD = os.path.normpath(sorted(_cand)[0])'''

if OLD not in s:
    print("  ✗ 原文本没匹配到，未做任何修改")
    raise SystemExit(1)

s = s.replace(OLD, NEW, 1)
ast.parse(s)                                     # 验证通过才写盘
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n"))
print("  ✓ native_deploy.py 的 MOD 解析已整段替换")

# 核对
s2 = open(p, encoding="utf-8").read()
print("    读环境变量:", s2.count("CONVERGENCE_MOD_ROOT"), "处")
print("    exe 目录兜底:", "_base = os.path.dirname(sys.executable)" in s2)
print()
print("  ── 三个文件的最终状态 ──")
for f, key in (("randgui.py", "publish_mod_root"),
               ("investigation/apply/native_apply.py", "_resolve_mod_root"),
               ("investigation/apply/native_deploy.py", "CONVERGENCE_MOD_ROOT"),
               ("investigation/apply/oodle.py", "CONVERGENCE_RAND_ROOT")):
    t = open(os.path.join(WS, f), encoding="utf-8").read()
    print(f"    {key:<26} {f}: {t.count(key)} 处")
