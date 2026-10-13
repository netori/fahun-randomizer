# _patch_oodle_search2.py — 简化版：只替换 DLL_CANDIDATES 与 find_dll
import ast
import os

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "oodle.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

NEW_CONST = '''DLL_CANDIDATES = [
    # 常见 Steam / 常见安装位置（覆盖大多数玩家）
    r"C:\\Program Files (x86)\\Steam\\steamapps\\common\\ELDEN RING\\Game",
    r"D:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"E:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"F:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"C:\\Games\\ELDEN RING\\Game",
    r"D:\\Games\\ELDEN RING\\Game",
]


def _guess_game_dirs(start):
    """从工具所在位置向上找可能的游戏目录。

    汉化本体/整合包常与游戏本体并列放在同一个父目录下，所以每一层不仅看自己的
    Game/，也扫一遍同级目录下的 Game/。只探 8 层、每层最多扫 200 个同级目录，
    避免在大硬盘上卡住。
    """
    out, cur = [], os.path.abspath(start)
    for _ in range(8):
        for name in ("Game", "game"):
            q = os.path.join(cur, name)
            if os.path.isdir(q):
                out.append(q)
        try:
            for sib in sorted(os.listdir(cur))[:200]:
                sp = os.path.join(cur, sib)
                if os.path.isdir(sp):
                    for name in ("Game", "game"):
                        q = os.path.join(sp, name)
                        if os.path.isdir(q):
                            out.append(q)
        except OSError:
            pass
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return out'''

i = s.index("DLL_CANDIDATES = [")
j = s.index("]", i) + 1
s = s[:i] + NEW_CONST + s[j:]

NEW_FIND = '''def find_dll(extra_dirs=()):
    """找 oo2core*.dll（游戏自带的 Oodle 压缩库）。

    顺序：① 调用方给的目录 ② 环境变量 CONVERGENCE_GAME_DIR
         ③ 工具/exe 旁的 oodle/、game/、Game/、tools/oodle/
         ④ 从工具位置向上 8 层，逐层找 Game/ 以及同级目录下的 Game/
         ⑤ 上次找到的目录（记在 oodle_dir.txt，命中过就不用再搜）
         ⑥ 常见 Steam / 常见安装位置
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.environ.get("CONVERGENCE_RAND_ROOT") or ""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else here
    dirs = [d for d in extra_dirs if d]
    for d in [os.environ.get("CONVERGENCE_GAME_DIR")]:
        if d:
            dirs.append(d)
    for base in (root, exe_dir, here):
        if base:
            dirs += [os.path.join(base, "oodle"), os.path.join(base, "game"),
                     os.path.join(base, "Game"), os.path.join(base, "tools", "oodle")]
    for base in (exe_dir, root):
        if base:
            dirs += _guess_game_dirs(base)
    cache = os.path.join(root or here, "oodle_dir.txt")
    if os.path.isfile(cache):
        try:
            c = open(cache, encoding="utf-8").read().strip()
            if c:
                dirs.insert(0, c)
        except OSError:
            pass
    dirs += DLL_CANDIDATES

    seen = set()
    for d in dirs:
        if not d or d in seen or not os.path.isdir(d):
            continue
        seen.add(d)
        for name in ("oo2core_9_win64.dll", "oo2core_8_win64.dll", "oo2core_7_win64.dll", "oo2core_6_win64.dll"):
            q = os.path.join(d, name)
            if os.path.exists(q):
                try:
                    open(cache, "w", encoding="utf-8").write(os.path.dirname(q))
                except OSError:
                    pass
                return q
    return None


'''

i2 = s.index("def find_dll(")
j2 = s.index("def lib(")
s = s[:i2] + NEW_FIND + s[j2:]

if "import sys" not in s.split("def ")[0]:
    s = s.replace("import ctypes", "import ctypes, sys", 1)

ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n") if "\r\n" in raw else s)
print("  ✓ oodle.py 搜索逻辑已替换")
print(f"    _guess_game_dirs: {s.count('_guess_game_dirs')} 处 ｜ oodle_dir.txt 缓存: {s.count('oodle_dir.txt')} 处")
