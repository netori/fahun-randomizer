# -*- coding: utf-8 -*-
"""封装不变量：我方产物前 76 字节 vs 原文件前 76 字节，逐字节列出差异偏移。

预期：out_kind="dflt"
  · 输入 DFLT 的文件 → 只有 [0x20,0x24) （comp）不同；unc 相同、kind/level/unk04 全同
  · 输入 KRAK 的文件 → [0x04,0x08) unk04 / [0x28,0x2c) kind / [0x30] level / [0x20,0x24) comp 不同
预期：out_kind="same" → DFLT 文件同上第一条；KRAK 文件只有 comp 不同（若 Oodle 产物长度恰好不同）
"""
import collections
import os
import sys

APPLY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apply"))
sys.path.insert(0, APPLY)
import msb_write as mw  # noqa: E402


def run(out_kind):
    files = mw._maps()
    dist = collections.Counter()
    examples = {}
    for i, p in enumerate(files, 1):
        data = open(p, "rb").read()
        out, rep = mw.patch_ex(data, {}, out_kind=out_kind)
        a, b = data[:76], out[:76]
        diff = tuple(k for k in range(76) if a[k] != b[k])
        key = (rep["in_kind"], rep["out_kind"], diff)
        dist[key] += 1
        examples.setdefault(key, (os.path.basename(p), a.hex(" "), b.hex(" ")))
        if i % 150 == 0:
            print("  ... %d/%d" % (i, len(files)))
    print("\n== out_kind=%s 时，76 字节 DCX 前缀的差异偏移分布 ==" % out_kind)
    labels = {0x04: "unk04", 0x20: "comp_lo", 0x21: "comp", 0x22: "comp", 0x23: "comp_hi",
              0x28: "kind", 0x30: "level"}
    for (ik, ok, diff), n in sorted(dist.items(), key=lambda x: -x[1]):
        ds = ",".join("%#04x(%s)" % (d, labels.get(d, "?")) for d in diff) or "无差异（逐字节相同！）"
        print("  输入 %-4s → 输出 %-4s  差异偏移: %-46s ×%d" % (ik, ok, ds, n))
    for (ik, ok, diff), (nm, a, b) in examples.items():
        print("   例 [%s→%s] %s" % (ik, ok, nm))
    return 0


def main():
    print("封装不变量检查（634 张）")
    run("dflt")
    run("same")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
