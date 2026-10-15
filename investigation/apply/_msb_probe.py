# -*- coding: utf-8 -*-
"""MSB 定点改写可行性探针（只读）

拿别的 mod 自带的 mod/map/mapstudio/*.msb.dcx 当样本，验证：
1) DCX 外层类型（KRAK / ZSTD）与大小
2) 能不能按 MSBE 的"头部 param 表"逐块走到 PARTS_PARAM_ST
3) PARTS 下面每个 Part 类型各有多少条（Enemy 应该是类型 2）
—— 目的：证明"只改 enemy 记录里的几个 int32、长度不变"这条路可行。
"""
import os
import struct
import sys

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa

SAMPLE_DIRS = [
    r"F:\game\studygame\elden ring\重回巅峰MOD v1.17.1(2026.10.5)\mod\map\mapstudio",
    r"F:\game\studygame\heiyejunlin\Daybreak 2.1.9 Beta2-Release\mod\map\mapstudio",
]


def find_samples(limit=3):
    out = []
    for d in SAMPLE_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".msb.dcx"):
                    out.append(os.path.join(root, f))
                    if len(out) >= limit:
                        return out
    return out


def decompress(path):
    data = open(path, "rb").read()
    h = erio.dcx_parts(data)
    kind = h["kind"]
    if kind.upper().startswith("DFLT"):
        import zlib
        raw = zlib.decompress(data[h["payload_off"]:h["payload_off"] + h["comp"]])
    elif kind.upper().startswith("ZSTD"):
        raw = erio.dcx_decompress(data)
    else:
        import oodle
        raw = oodle.decompress(data[h["payload_off"]:h["payload_off"] + h["comp"]], h["unc"])
    return raw, kind, len(data)


def walk_params(raw, max_blocks=40):
    """按 MSBE 头部表逐块走：magic + int32 ver + int32 count + int64 nameOff + int64[count] offsets"""
    print(f"    头部: {raw[:4]!r} ver={struct.unpack_from('<i', raw, 4)[0]}")
    pos = 0x0C
    blocks = []
    for i in range(max_blocks):
        if pos + 16 > len(raw):
            break
        ver, count = struct.unpack_from("<ii", raw, pos)
        if not (0 < count < 4096):
            break
        name_off = struct.unpack_from("<q", raw, pos + 8)[0]
        if not (0 < name_off < len(raw)):
            break
        name = raw[name_off:raw.find(b"\0", name_off)].decode("ascii", "ignore")
        offs_off = pos + 16
        offsets = struct.unpack_from(f"<{count}q", raw, offs_off) if count <= 512 else ()
        nxt = struct.unpack_from("<q", raw, offs_off + 8 * count)[0] if count <= 512 else 0
        blocks.append({"i": i, "pos": pos, "ver": ver, "count": count, "name": name,
                       "first": offsets[0] if offsets else 0})
        if name == "PARTS_PARAM_ST":
            return blocks, {"pos": pos, "count": count, "offsets": offsets}
        if not (0 < nxt < len(raw)) or nxt == pos:
            break
        pos = nxt
    return blocks, None


def main():
    samples = find_samples()
    if not samples:
        print("没找到样本 msb.dcx（样本目录不在）")
        return
    for p in samples:
        print(f"\n=== {os.path.basename(p)} ===")
        raw, kind, size = decompress(p)
        print(f"  DCX {kind}｜文件 {size/1048576:.2f} MB → 解压 {len(raw)/1048576:.2f} MB")
        blocks, parts = walk_params(raw)
        for b in blocks[:12]:
            print(f"    块{b['i']:>2} @{b['pos']:#09x} ver={b['ver']:<3} count={b['count']:<5} {b['name']}")
        if not parts:
            print("  ✗ 没走到 PARTS_PARAM_ST（结构假设不成立，二期要另想办法）")
            continue
        print(f"  ✓ PARTS_PARAM_ST @{parts['pos']:#x}，子表 {parts['count']} 个")
        # PARTS 的子表：每个子块内部应有 count+offsets；这里只按类型顺序打印各子表条目数
        for i, off in enumerate(parts["offsets"][:12]):
            if not (0 < off < len(raw) - 16):
                continue
            cnt = struct.unpack_from("<i", raw, off + 4)[0]
            nm_off = struct.unpack_from("<q", raw, off + 8)[0]
            try:
                nm = raw[nm_off:raw.find(b"\0", nm_off)].decode("ascii", "ignore") if 0 < nm_off < len(raw) else ""
            except Exception:
                nm = ""
            tag = " ← PartType 2 = Enemy" if i == 2 else ""
            print(f"    子表{i:>2} @{off:#09x} 条目 {cnt:<6} {nm}{tag}")


if __name__ == "__main__":
    main()
