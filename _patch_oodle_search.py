# _patch_oodle_search.py — 让工具自己找到游戏的 Oodle DLL（不再要求玩家手动放）
import ast
import os
import re

WS = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(WS, "investigation", "apply", "oodle.py")
raw = open(p, encoding="utf-8", newline="").read()
s = raw.replace("\r\n", "\n")

# 找到 DLL_CANDIDATES 那段，整体替换搜索逻辑
i = s.index("DLL_CANDIDATES = [")
j = s.index("]", i) + 1
OLD_CONST = s[i:j]

NEW_CONST = '''DLL_CANDIDATES = [
    # 常见 Steam 安装位置（覆盖大多数玩家）
    r"C:\\Program Files (x86)\\Steam\\steamapps\\common\\ELDEN RING\\Game",
    r"D:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"E:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"F:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
    r"C:\\Games\\ELDEN RING\\Game",
    r"D:\\Games\\ELDEN RING\\Game",
]


def _guess_game_dirs(exe_dir):
    """从工具所在位置向上找可能的游戏目录。

    整合包/汉化本体常和游戏本体放在同一个父目录下（例如
    `<某目录>/法魂mod…/` 与 `<某目录>/ELDEN RING …/Game/` 并列），
    所以每一层除了看自己的 Game/，也扫一遍同级目录下的 Game/。
    只探 8 层、每层只扫一层子目录，避免在大硬盘上卡住。
    """
    out = []
    cur = os.path.abspath(exe_dir)
    for _ in range(8):
        for name in ("Game", "game"):
            q = os.path.join(cur, name)
            if os.path.isdir(q):
                out.append(q)
        try:
            for sib in sorted(os.listdir(cur))[:200]:
                sp = os.path.join(cur, sib)
                if not os.path.isdir(sp):
                    continue
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

s = s[:i] + NEW_CONST + s[j:]

# 替换 find_dll：把它们串起来
i2 = s.index("def find_dll(")
j2 = s.index("def lib(")
NEW_FIND = '''def find_dll(extra_dirs=()):
    """找 oo2core*.dll（游戏自带的 Oodle 压缩库）。

    搜索顺序：
      ① 调用方指定的目录
      ② 环境变量指定的游戏目录（CONVERGENCE_GAME_DIR）
      ③ exe/工具旁：oodle/ 、game/ 、Game/ 、tools/oodle/
      ④ 从工具位置向上最多 8 层，逐层找 Game/ 以及同级目录下的 Game/（整合包常见布局）
      ⑤ 常见 Steam / 常见安装位置

    找不到时给出**可操作**的提示（告诉玩家把 dll 放哪），而不是只说"没找到"。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.environ.get("CONVERGENCE_RAND_ROOT") or ""
    dirs = []
    dirs += [d for d in extra_dirs if d]
    dirs += [d for d in [os.environ.get("CONVERGENCE_GAME_DIR")] if d]
    for base in [root, os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else "", here]:
        if not base:
            continue
        dirs += [os.path.join(base, "oodle"),
                 os.path.join(base, "game"), os.path.join(base, "Game"),
                 os.path.join(base, "tools", "oodle")]
    # ④ 向上找（含同级目录里的 Game/）
    for base in [os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else here, root]:
        if base:
            dirs += _guess_game_dirs(base)
    # 记下过上次找到的目录，下次直接命中
    cache = os.path.join(root or here, "oodle_dir.txt")
    if os.path.isfile(cache):
        try:
            cached = open(cache, encoding="utf-8").read().strip()
            if cached:
                dirs.insert(0, cached)
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
                try:                     # 记住它，下次不必再搜
                    os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
                    open(cache, "w", encoding="utf-8").write(os.path.dirname(q))
                except OSError:
                    pass
                return q
    return None


'''
s = s[:i2] + NEW_FIND + s[j2:]

# 确保 sys / glob 已导入（新代码用到 sys）
if "import ctypes, glob, os, struct" in s:
    s = s.replace("import ctypes, glob, os, struct", "import ctypes, glob, os, struct, sys")
elif "import sys" not in s.split("def ")[0]:
    s = s.replace("import ctypes", "import ctypes, sys", 1)

# 找不到时的提示更像"照做就行"
s = s.replace('raise FileNotFoundError("找不到 oo2core*.dll（请把 Eld Ring 的 Game 目录路径告诉本工具，或把 dll 放到 tools/oodle/）")',
              'raise FileNotFoundError("PLACEHOLDER")')
s = re.sub(r'raise FileNotFoundError\("找不到 oo2core\*\.dll[^"]*"\)',
           'raise FileNotFoundError(\n'
           '            "找不到 oo2core*.dll（游戏自带的 Oodle 压缩库，说明书改写要用它）。\\n"\n'
           '            "  做法：打开你游戏安装目录里的 Game 文件夹，把里面的 oo2core_*_win64.dll 复制到\\n"\n'
           '            f"  {os.path.join(os.path.dirname(os.path.abspath(__file__)), \\"oodle\\")}\\n"\n'
           '            "  （没有 oodle 文件夹就新建一个）"\n'
           '        )', s)

ast.parse(s)
open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n") if "\r\n" in raw else s)
print("  ✓ oodle.py：搜索范围扩大到「向上 8 层 + 同级目录的 Game/」，并记住上次命中的目录")
print("    也认环境变量 CONVERGENCE_GAME_DIR，找不到时给可操作提示")
