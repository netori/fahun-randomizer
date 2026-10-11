# bnd4_locate.py — 在 ER 的 BND4（regulation 明文）里按名字定位内部文件，并验证取出的内容正确
import os, struct, sys, hashlib

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import erio  # noqa


def entries(raw):
    """返回 [(name, offset, size, extra)] —— 条目 0x24 字节，name_off 在 +0x20"""
    _unk, _ver, cnt, hsz = struct.unpack_from("<IiII", raw, 4)
    fmt = struct.unpack_from("<I", raw, hsz)[0]
    out = []
    for i in range(cnt):
        e = fmt + 0x24 * i
        a = struct.unpack_from("<Q", raw, e + 0x08)[0]
        b = struct.unpack_from("<Q", raw, e + 0x10)[0]
        c = struct.unpack_from("<Q", raw, e + 0x18)[0]
        name_off = struct.unpack_from("<I", raw, e + 0x20)[0]
        j = name_off
        while j + 1 < len(raw) and raw[j:j + 2] != b"\0\0":
            j += 2
        name = raw[name_off:j].decode("utf-16-le", "replace")
        out.append((name, a, b, c))
    return out


def pick_off_size(raw, name, a, b, c):
    """(offset, size) 的两种可能写法，用文件头魔数自查"""
    for off, size in ((a, c), (a, b), (c, a)):
        if 0 <= off < len(raw) and 4 <= size <= len(raw) - off:
            head = raw[off:off + 4]
            if head in (b"PARAM", b"FMG ", b"FMG\0", b"DDS ", b"MD5\0", b"DCX\0", b"BND4") or head[:3] == b"FMG":
                return off, size, head
    return None, None, b""


def main():
    MOD = os.path.join(os.path.dirname(APPLY.rstrip("\\/")), "..", "..", "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
    MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(APPLY)), "..",
                                        "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))
    reg = os.path.join(MOD, "mod", "regulation.bin")
    raw = erio.dcx_decompress(erio.regulation_decrypt(reg))
    ents = entries(raw)
    print(f"  条目 {len(ents)} 个；前 5：")
    for n, a, b, c in ents[:5]:
        off, size, head = pick_off_size(raw, n, a, b, c)
        print(f"   {n[-52:]:<54} off={off if off is None else hex(off)} size={size} head={head}")

    # 与 WitchyBND 解出的目录比对（用 param 文件）
    tree = os.path.join(APPLY, "work", "orig", "regulation-bin")
    ok = bad = miss = 0
    for n, a, b, c in ents:
        base = os.path.basename(n.replace("\\", "/"))
        p = os.path.join(tree, base)
        if not os.path.exists(p):
            continue
        off, size, head = pick_off_size(raw, n, a, b, c)
        if off is None:
            miss += 1
            continue
        mine = hashlib.sha256(raw[off:off + size]).hexdigest()
        ref = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if mine == ref:
            ok += 1
        else:
            bad += 1
            if bad <= 5:
                print(f"   ✗ {base}: 我={size}B 参考={os.path.getsize(p)}B")
    print(f"\n  与 WitchyBND 解包目录逐字节比对：一致 {ok} | 不一致 {bad} | 定位失败 {miss}")
    return 0 if bad == 0 and miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
