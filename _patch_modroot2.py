# _patch_modroot2.py — 补齐上一轮没落的两处（glob 导入 + CRLF 文件）
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))


def patch(path, pairs, crlf=False):
    p = os.path.join(WS, path)
    raw = open(p, encoding="utf-8", newline="").read()
    s = raw.replace("\r\n", "\n") if crlf else raw
    ok = miss = 0
    for old, new in pairs:
        old_c = old.replace("\r\n", "\n") if crlf else old
        new_c = new.replace("\r\n", "\n") if crlf else new
        if old_c in s:
            s = s.replace(old_c, new_c, 1)
            ok += 1
        else:
            miss += 1
            print(f"      未匹配: {old_c.strip()[:70]!r}")
    out = s.replace("\n", "\r\n") if crlf else s
    ast.parse(out)
    open(p, "w", encoding="utf-8", newline="").write(out)
    print(f"  {'✓' if not miss else '⚠'} {path}: {ok} 处修改" + (f"，{miss} 处未匹配" if miss else ""))
    return miss == 0


# ① native_apply.py：把 glob 加进导入（_resolve_mod_root 里要用）
patch("investigation/apply/native_apply.py", [
    ("import argparse, csv, hashlib, json, os, struct, sys, time",
     "import argparse, csv, glob, hashlib, json, os, struct, sys, time"),
])

# ② native_deploy.py（CRLF）：打包分支改用环境变量优先
patch("investigation/apply/native_deploy.py", [
    ('''    if getattr(sys, "frozen", False):                       # 打包运行：MOD 取工作区旁边的法魂mod 目录''',
     '''    _env = os.environ.get("CONVERGENCE_MOD_ROOT")           # 界面解析并发布的 MOD 目录（打包版走这条）
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        MOD = os.path.normpath(_env)
    elif getattr(sys, "frozen", False):                     # 没传就猜：exe 所在目录，或它同级的法魂mod*'''),
    ('''            MOD = os.path.normpath(_cand[0])          # …\\THE_COVERAGE-随机开发''',
     '''            MOD = os.path.normpath(sorted(_cand)[0])'''),
    ('''    _cand = [d for d in glob.glob(os.path.join(os.path.dirname(sys.executable), "..", "法魂mod*")) if os.path.isdir(d)]''',
     '''        _base = os.path.dirname(sys.executable)
        if os.path.isfile(os.path.join(_base, "mod", "regulation.bin")):
            MOD = os.path.normpath(_base)
        _cand = [d for d in glob.glob(os.path.join(_base, "..", "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]'''),
], crlf=True)

print("\n  ── 核对 ──")
import sys
sys.path.insert(0, os.path.join(WS, "investigation", "apply"))
s1 = open(os.path.join(WS, "investigation/apply/native_apply.py"), encoding="utf-8").read()
print("    native_apply 里 glob 已导入:", "import argparse, csv, glob," in s1)
s2 = open(os.path.join(WS, "investigation/apply/native_deploy.py"), encoding="utf-8").read()
print("    native_deploy 读环境变量:", "CONVERGENCE_MOD_ROOT" in s2, f"({s2.count('CONVERGENCE_MOD_ROOT')} 处)")
print("    native_deploy 兜底分支:", "_base = os.path.dirname(sys.executable)" in s2)
