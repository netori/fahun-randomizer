# fmg.py — 自研 FMG 读写（支持任意长度替换：新串追加到文件末尾 + 只改它自己的表项）
#
# 实测结构（ER GoodsCaption.fmg）：
#   [0x00] u32 = 0x00020000（版本）
#   [0x04] u32 = 文件大小（改完要更新）
#   [0x08] u32 / [0x0C] u32 / [0x10] u32 / [0x14] u32 / [0x18] u32 …（组信息等，保持不动）
#   偏移表：**u64 绝对偏移**数组，每组一张（实测 GoodsCaption 的两张起点：0x71A0 / 0x8C40）
#   数据区：各组字符串按序紧排，UTF-16LE、以 \0\0 结尾
#
# 替换策略（最小改动）：新串写到文件末尾（2 字节对齐 + \0\0 结尾），只把该串所属表项指向新位置。
import struct, sys

U64 = struct.Struct("<Q")


def file_size(fmg: bytes) -> int:
    return struct.unpack_from("<I", fmg, 4)[0]


def find_string(fmg: bytes, prefix: str, limit_len=0):
    """前缀定位 → 读到 \\0\\0 定界 → (起点, 终点)，终点不含结束符"""
    pb = prefix.encode("utf-16-le")
    i = fmg.find(pb)
    if i < 0:
        return None
    j = i
    while j + 1 < len(fmg) and fmg[j:j + 2] != b"\0\0":
        j += 2
    return i, j


def find_table_entry(fmg: bytes, off: int):
    """找"哪个 u64 表项等于 off" —— 并用相邻项也像字符串偏移来校验，避免误判"""
    pat = U64.pack(off)
    start = 0
    while True:
        i = fmg.find(pat, start)
        if i < 0:
            return None
        if i % 8 == 0 or True:
            ok = 0
            for d in (-16, -8, 8, 16):
                p = i + d
                if 0 <= p + 8 <= len(fmg):
                    v = U64.unpack_from(fmg, p)[0]
                    if 0x1000 < v < len(fmg):
                        ok += 1
            if ok >= 2:
                return i
        start = i + 1


def plan_edits(fmg: bytes, edits):
    """**在原始文件上**先把每条的目标确定下来：(旧串, 新串, 串起点, 表项位置)"""
    out, detail = [], []
    for old, new in edits:
        # 先用**整串**定位：同一职业的多个说明书页首行完全相同，用前缀会撞车
        span = find_string(fmg, old)
        if span is None:
            span = find_string(fmg, old[:20])
        if span is None:
            detail.append((old[:18], "没找到原串")); continue
        entry = find_table_entry(fmg, span[0])
        if entry is None:
            detail.append((old[:18], "没找到表项")); continue
        out.append((old, new, span[0], span[1], entry))
    return out, detail


def replace_strings(fmg: bytearray, edits, verbose=False):
    """edits: [(旧整串, 新整串)] → 新串追加到末尾，只改它自己的表项（其它偏移一律不动）"""
    plan, detail = plan_edits(bytes(fmg), edits)
    for old, new, i, j, entry in plan:
        nb = new.encode("utf-16-le")
        if len(fmg) % 2:
            fmg.append(0)
        new_off = len(fmg)
        fmg += nb + b"\0\0"
        U64.pack_into(fmg, entry, new_off)
        if verbose:
            print(f"   表项 @{hex(entry)}: {hex(i)} → {hex(new_off)}（{len(nb)}B）")
    struct.pack_into("<I", fmg, 4, len(fmg))
    return len(plan), detail


def read_all_strings(fmg: bytes):
    """按偏移表把某组的字符串全读出来（用于校验）：表起点靠调用方给"""
    out = []
    off = 0x71A0
    while off + 8 <= len(fmg):
        v = U64.unpack_from(fmg, off)[0]
        if not (0x1000 < v < len(fmg)):
            break
        s = find_string(bytes(fmg), fmg[v:v + 8].decode("utf-16-le", "ignore")[:4])
        i = v
        j = i
        while j + 1 < len(fmg) and fmg[j:j + 2] != b"\0\0":
            j += 2
        out.append((v, fmg[i:j].decode("utf-16-le", "ignore")))
        off += 8
    return out
