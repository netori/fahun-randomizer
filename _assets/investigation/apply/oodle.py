# oodle.py — 通过游戏自带的 oo2core*.dll 做 Oodle(Kraken) 解压/压缩（ctypes，无需任何第三方工具）
import ctypes, glob, os, struct

DLL_CANDIDATES = [
    r"F:\game\studygame\elden ring\ELDEN RING Tarnished Edition v1.17\Game",
    r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game",
    r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game",
    r"E:\SteamLibrary\steamapps\common\ELDEN RING\Game",
]
_lib = None
_dll_path = None


def find_dll(extra_dirs=()):
    """在游戏目录（以及调用方给的目录、本工具 tools/oodle/）里找 oo2core*.dll"""
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = list(extra_dirs) + [os.path.join(here, "oodle"), os.path.join(here, "tools", "oodle")] + DLL_CANDIDATES
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in ("oo2core_9_win64.dll", "oo2core_8_win64.dll", "oo2core_7_win64.dll", "oo2core_6_win64.dll"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
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
