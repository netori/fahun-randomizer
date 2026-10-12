# oodle.py — 通过游戏自带的 oo2core*.dll 做 Oodle(Kraken) 解压/压缩（ctypes，无需任何第三方工具）
import ctypes, glob, os, struct

DLL_CANDIDATES = [
    # 常见 Steam 安装位置（覆盖大多数玩家）
    r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game",
    r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game",
    r"E:\SteamLibrary\steamapps\common\ELDEN RING\Game",
    r"F:\SteamLibrary\steamapps\common\ELDEN RING\Game",
]
_lib = None
_dll_path = None


def find_dll(extra_dirs=()):
    """找 oo2core*.dll。

    搜索顺序：调用方给的目录 → exe 旁边的 oodle/ 与 game/ → 向上几层的 game/ →
    oodle.py 同级的 oodle/tools/oodle → 常见 Steam 安装位置。
    找不到也不要紧：会给出「把 DLL 复制到哪」的人话提示。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = list(extra_dirs)
    exe_dir = os.environ.get("CONVERGENCE_RAND_ROOT") or here
    for base in (exe_dir, here):
        dirs += [os.path.join(base, "oodle"),
                 os.path.join(base, "game"),
                 os.path.join(base, "Game"),
                 os.path.join(base, "tools", "oodle")]
    # 从 exe/脚本所在目录向上找 game/ 或 Game/（有些整合包把游戏放在 MOD 上一级）
    cur = exe_dir
    for _ in range(4):
        for sub in ("game", "Game"):
            dirs.append(os.path.join(cur, sub))
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    dirs += DLL_CANDIDATES
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in ("oo2core_9_win64.dll", "oo2core_8_win64.dll", "oo2core_7_win64.dll", "oo2core_6_win64.dll"):
            q = os.path.join(d, name)
            if os.path.exists(q):
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
