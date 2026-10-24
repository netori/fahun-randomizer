# oodle.py — 通过游戏自带的 oo2core*.dll 做 Oodle(Kraken) 解压/压缩（ctypes，无需任何第三方工具）
import ctypes, sys, glob, os, re, struct


def _fallback_dirs():
    """兜底用的常见安装位置 —— 全部从环境变量 / Steam 库列表推出来，不写死某台机器。"""
    out = []
    for ev in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        p = os.environ.get(ev)
        if p:
            out.append(os.path.join(p, "Steam", "steamapps", "common", "ELDEN RING", "Game"))
    # Steam 库列表：游戏装在别的盘也能推出来
    for base in list(out):
        # ...\Steam\steamapps\common\ELDEN RING\Game → ...\Steam
        steam = os.path.dirname(os.path.dirname(os.path.dirname(base)))
        try:
            txt = open(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
                       encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
            out.append(os.path.join(m.group(1).replace("\\\\", "\\"),
                                    "steamapps", "common", "ELDEN RING", "Game"))
    # 非 Steam 的常见搬法（绿色版 / 免安装版）
    for drv in ("C:", "D:", "E:", "F:", "G:"):
        for sub in ("SteamLibrary", "Games", "Game"):
            out.append(os.path.join(drv + os.sep, sub, "ELDEN RING", "Game"))
    return out


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
    return out
_lib = None
_dll_path = None


def find_dll(extra_dirs=()):
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
    # 统一解析器先找一遍（它认「旁边任意一层有 Game/eldenring.exe」）
    try:
        import modpaths
        _g = modpaths.find_game_dir(exe_dir)
    except Exception:
        _g = None
    if _g:
        dirs.append(_g)
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
    dirs += _fallback_dirs()

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


def lib(extra_dirs=()):
    global _lib, _dll_path
    if _lib is not None:
        return _lib
    p = find_dll(extra_dirs)
    if not p:
        raise FileNotFoundError("找不到 oo2core*.dll（请把 Elden Ring 的 Game 目录路径告诉本工具，或把 dll 放到 tools/oodle/）")
    _dll_path = p
    _lib = ctypes.WinDLL(p)
    _lib.OodleLZ_Decompress.restype = ctypes.c_longlong
    _lib.OodleLZ_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_longlong, ctypes.c_char_p, ctypes.c_longlong,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong,
                                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    _lib.OodleLZ_Compress.restype = ctypes.c_longlong
    _lib.OodleLZ_Compress.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_longlong, ctypes.c_char_p, ctypes.c_int,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_longlong, ctypes.c_int]
    return _lib


def decompress(data: bytes, raw_size: int, extra_dirs=()):
    """注意：rawSize 必须给**精确**的未压缩大小，多给会返回 0（实测）"""
    l = lib(extra_dirs)
    src = ctypes.create_string_buffer(bytes(data), len(data))
    out = ctypes.create_string_buffer(raw_size)
    l.OodleLZ_Decompress.restype = ctypes.c_ulonglong
    l.OodleLZ_Decompress.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_void_p, ctypes.c_ulonglong,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulonglong,
                                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_int]
    n = l.OodleLZ_Decompress(ctypes.cast(src, ctypes.c_void_p), len(data),
                             ctypes.cast(out, ctypes.c_void_p), raw_size, 1, 0, 0, None, 0, None, None, None, 0, 0)
    if n != raw_size:
        raise ValueError(f"Oodle 解压失败（返回 {n}，期望 {raw_size}）")
    return out.raw[:n]


def compress(data: bytes, level: int = 6, compressor: int = 8, extra_dirs=()):
    """compressor: 8 = Kraken（ER 的默认）；level 与 ER 一致用 6 hmm —— 任意合法流游戏都能读"""
    l = lib(extra_dirs)
    cap = len(data) + len(data) // 2 + 4096
    out = ctypes.create_string_buffer(cap)
    n = l.OodleLZ_Compress(compressor, data, len(data), out, level, None, None, None, None, 0, 0)
    if n <= 0:
        raise ValueError(f"Oodle 压缩失败（返回 {n}）")
    return out.raw[:n]
