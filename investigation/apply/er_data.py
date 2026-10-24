# -*- coding: utf-8 -*-
"""ER 本体归档（BHD5 + BDT）的**按需**读取器 —— 只取需要的文件，不解 50 GB。

为什么之前卡住：ER 的 .bhd 索引是 **RSA 加密**的，游戏社区把密钥放在 BinderKeys 仓库
（JKAnderson，与 Nuxe/WitchyBND 同源）。拿到钥匙后：
  .bhd  → 每 256 字节一块用 RSA 公钥解 → 明文 BHD5（注意：文件开头有 1 个 \\x00）
  BHD5  → 桶目录 → 每条记录：名字哈希(64位) + 偏移 + 大小 + 该文件的 AES 密钥与区间
  名字  → Hash/DataN.txt（哈希 → 路径 的词典，就是"本体文件名"）
  内容  → 直接从 .bdt 里 seek + 读那段 → 按区间 AES 解密 → 再用我们现成的 DCX 解压

只读，不改游戏目录。
"""
import hashlib
import io
import os
import struct
import sys

from cryptography.hazmat.primitives.serialization import load_pem_public_key

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _find_dirs():
    """找游戏目录与钥匙/词典目录（都能用环境变量覆盖；没给就按相对位置找）"""
    game = os.environ.get("ER_GAME_DIR") or os.environ.get("CONVERGENCE_GAME_DIR")
    if not game:
        try:
            import modpaths
            game = modpaths.find_game_dir(HERE) or ""
        except Exception:
            game = ""
    keys = os.environ.get("ER_KEYS_DIR")
    if not keys:
        for c in (os.path.join(os.environ.get("TEMP", ""), "binderkeys", "EldenRing_PC"),
                  os.path.join(HERE, "..", "..", "..", "binderkeys", "EldenRing_PC")):
            if os.path.isdir(c):
                keys = c
                break
    return game, keys


GAME, KEYS = _find_dirs()


def decrypt_bhd(path, pem_path):
    """整个 .bhd 用 RSA 公钥逐块解 → 明文（BHD5 从偏移 1 开始）"""
    pub = load_pem_public_key(io.open(pem_path, "rb").read())
    nums = pub.public_numbers()
    n = (nums.n.bit_length() + 7) // 8
    d = open(path, "rb").read()
    out = bytearray()
    for off in range(0, len(d) - n + 1, n):
        out += pow(int.from_bytes(d[off:off + n], "big"), nums.e, nums.n).to_bytes(n, "big")
    return bytes(out)


def parse_bhd(plain):
    """→ {version, buckets, entries}。实测布局（照 BinderTool 的 Bhd5BucketEntry）：

        每条 0x20 字节（非 DS3）：u32 名字哈希 ｜ u32 paddedSize ｜ i64 偏移 ｜
                                  i64 盐哈希偏移 ｜ i64 AES 密钥偏移 ｜（DS3 再多一个 i64 文件大小）
        AES 密钥块（在它自己的偏移处）：key[16] ｜ i32 区间数 ｜ [i64 start, i64 end] × n
        哈希是 **32 位**，正对应 Hash/DataN.txt 词典里的 8 位十六进制。
    """
    assert plain[:5] == b"\x00BHD5", "不是 BHD5（先是 %r）" % plain[:8]
    # 实测头（Data0.bhd，解密后逐字段对出来的；BinderTool 那套是 DS2/DS3 的排法，ER 不同）：
    #   +0x00 1 字节 \x00 ｜ +0x01 'BHD5' ｜ +0x05 i32 版本(511) ｜ +0x09 i32 未知(1)
    #   +0x0d i32 大小 ｜ +0x11 i32 桶数 ｜ +0x15 i32 桶目录偏移 ｜ +0x19 i32 盐长度 ｜ 盐…
    version = struct.unpack_from("<i", plain, 5)[0]
    _size, bucket_count, _bo, salt_len = struct.unpack_from("<iiii", plain, 0x0d)
    salt = plain[0x1d:0x1d + salt_len]
    bucket_off = 0x1d + salt_len          # 实测：盐之后就是桶目录（Data0 = 0x25）
    buckets, entries = [], []
    stride = 0x28 if version == 0x1FF else 0x20
    for i in range(bucket_count):
        cnt, off = struct.unpack_from("<ii", plain, bucket_off + i * 8)   # 每桶 8 字节
        buckets.append((cnt, off))
        for k in range(cnt):
            q = off + k * stride
            h, padded, foff = struct.unpack_from("<IIq", plain, q)
            _sh_off, aes_off = struct.unpack_from("<qq", plain, q + 16)
            fsize = struct.unpack_from("<q", plain, q + 32)[0] if stride == 0x28 else padded
            key = None
            if aes_off:
                rcnt = struct.unpack_from("<i", plain, aes_off + 16)[0]
                rng = [struct.unpack_from("<qq", plain, aes_off + 20 + r * 16) for r in range(rcnt)]
                key = {"key": plain[aes_off:aes_off + 16], "ranges": rng}
            entries.append({"hash": h, "size": fsize, "padded": padded, "offset": foff, "aes": key})
    return {"version": version, "salt": salt, "buckets": buckets, "entries": entries}


def path_hash(file_path, prime=37):
    """FromSoft 的路径哈希：h = h*37 + char（小写、反斜杠转正斜杠；BinderTool 同款）

    Hash/DataN.txt 里只有**路径**（一行一个），哈希是算出来的 —— 这就是"本体文件名"能对上的原因。
    """
    h = 0
    for ch in file_path.replace("\\", "/").lower():
        h = (h * prime + ord(ch)) & 0xFFFFFFFF
    return h


def load_dict(hash_txt):
    """Hash/DataN.txt → {32 位哈希: 路径}（路径前加 '/' 后算哈希，与工具一致）"""
    out = {}
    if not os.path.isfile(hash_txt):
        return out
    with io.open(hash_txt, encoding="utf-8-sig", errors="ignore") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            out[path_hash("/" + ln.lstrip("/"))] = ln
    return out


def main():
    print("游戏目录:", GAME)
    print("钥匙目录:", KEYS)
    if not (GAME and os.path.isdir(GAME) and KEYS and os.path.isdir(KEYS)):
        print("目录不对，设 ER_GAME_DIR / ER_KEYS_DIR")
        return 2
    for name in ("Data0", "Data1", "Data2", "Data3", "DLC"):
        bhd = os.path.join(GAME, name + ".bhd")
        pem = os.path.join(KEYS, "Key", name + ".pem")
        if not (os.path.isfile(bhd) and os.path.isfile(pem)):
            continue
        plain = decrypt_bhd(bhd, pem)
        j = plain.find(b"BHD5")
        info = parse_bhd(plain[j - 1:]) if j > 0 else None
        d = load_dict(os.path.join(KEYS, "Hash", name + ".txt"))
        print("%-6s 明文 %9d 字节 ｜ 版本 %s ｜ 词典 %d 条" % (
            name, len(plain), info["version"] if info else "?", len(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
