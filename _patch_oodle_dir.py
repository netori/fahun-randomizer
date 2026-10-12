# _patch_oodle_dir.py — 让 oodle 去 exe 旁边找 DLL（用 deploy 里那段重定位已经算好的工作区）
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "native_deploy.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

ANCHOR = '''        if callable(log):
            log(f"[定位] 工作区 {_ws} ｜ MOD {_mod}")'''
if ANCHOR not in s:
    print("  ✗ 锚点未匹配")
    raise SystemExit(1)

NEW = '''        # Oodle 的 DLL 随游戏走：告诉 oodle 去工作区（= exe 旁边）找 oodle/ 或 game/
        os.environ["CONVERGENCE_RAND_ROOT"] = _ws
        os.environ.setdefault("CONVERGENCE_GAME_DIR", os.path.join(_ws, "game"))
        if callable(log):
            log(f"[定位] 工作区 {_ws} ｜ MOD {_mod}")'''

s = s.replace(ANCHOR, NEW, 1)
ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n"))
print("  ✓ 已让 deploy 把工作区路径告诉 oodle")

# 顺便确认 oodle 会读这两个环境变量
q = os.path.join(WS, "investigation", "apply", "oodle.py")
o = open(q, encoding="utf-8").read()
if "CONVERGENCE_RAND_ROOT" not in o:
    o = o.replace('    exe_dir = os.environ.get("CONVERGENCE_RAND_ROOT") or here',
                  '    exe_dir = os.environ.get("CONVERGENCE_RAND_ROOT") or here\n'
                  '    dirs += [d for d in [os.environ.get("CONVERGENCE_GAME_DIR")] if d]')
    ast.parse(o)
    open(q, "w", encoding="utf-8").write(o)
    print("  ✓ oodle.py 也认 CONVERGENCE_GAME_DIR")
print(f"    oodle 里 CONVERGENCE_RAND_ROOT: {open(q, encoding='utf-8').read().count('CONVERGENCE_RAND_ROOT')} 处")
