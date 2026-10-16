# -*- coding: utf-8 -*-
"""反推 BHD5 条目表的字段次序：判据是"哈希必须能在 Hash/DataN.txt 词典里命中"。

这是可判定的：只要字段对齐，一个桶里的条目**全部**能命中词典；错位则命中率为 0。
做法：在桶0 处按各种 (起点偏移, 记录长度, 哈希字段偏移) 组合试，取命中率最高的一组。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import er_data as ED                                                # noqa: E402


def main():
    pl = ED.decrypt_bhd(os.path.join(ED.GAME, "Data0.bhd"), os.path.join(ED.KEYS, "Key", "Data0.pem"))
    j = pl.find(b"BHD5")
    pl = pl[j - 1:]
    dic = ED.load_dict(os.path.join(ED.KEYS, "Hash", "Data0.txt"))
    keys = set(dic)          # 键是 32 位整数
    cnt, off = struct.unpack_from("<ii", pl, 0x25)
    print("桶0：条目 %d ｜ 表偏移 %d ｜ 词典 %d 条" % (cnt, off, len(dic)))
    print()
    best = []
    for stride in (0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x30):
        for hash_at in range(0, stride - 3, 4):
            for start in range(off - 8, off + 9, 4):
                hits = 0
                got = []
                for k in range(cnt):
                    q = start + k * stride + hash_at
                    if q + 4 > len(pl):
                        break
                    h = struct.unpack_from("<I", pl, q)[0]
                    if h in keys:
                        hits += 1
                        got.append("%08x" % h)
                if hits >= max(2, cnt - 1):
                    best.append((hits, stride, hash_at, start - off, got[:3]))
    best.sort(reverse=True)
    if not best:
        print("没找到命中组合 —— 把桶0 的 128 字节 dump 出来人工看：")
        print(pl[off:off + 128].hex())
        return 1
    for hits, stride, hash_at, dstart, sample in best[:5]:
        print("命中 %d/%d ｜ 记录长 0x%02x ｜ 哈希在记录内 +0x%02x ｜ 表起点相对偏移 %+d ｜ 样例 %s"
              % (hits, cnt, stride, hash_at, dstart, sample))
    hits, stride, hash_at, dstart, _ = best[0]
    base = off + dstart
    print()
    print("★ 采用：记录长 0x%02x，哈希 +0x%02x，表起点 %d" % (stride, hash_at, base))
    print("%-10s %-10s %-12s %-12s %s" % ("名字哈希", "大小", "文件偏移", "AES密钥偏移", "名字（词典）"))
    for k in range(min(cnt, 7)):
        q = base + k * stride
        h = struct.unpack_from("<I", pl, q + hash_at)[0]
        # 其余字段也按常见的 i32/i64 读出来看看
        nums = struct.unpack_from("<" + "I" * (stride // 4), pl, q)
        nm = dic.get(h, "（词典里没有）")
        print("%08x  %-10s %s" % (h, nums, nm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
