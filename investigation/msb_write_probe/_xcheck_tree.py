# -*- coding: utf-8 -*-
"""WitchyBND 独立解析结果 —— **整棵解包目录**逐文件、逐 XML 节点比对。"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "_wx_test", "m10_00_00_00_orig-msb-dcx")
B = os.path.join(HERE, "_wx_test", "m10_00_00_00_patched-msb-dcx")
SKIP_ATTRS = {"filename", "path"}


def rel(root):
    out = {}
    for d, _s, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = p
    return out


def sig(el):
    at = {k: v for k, v in el.attrib.items() if k not in SKIP_ATTRS}
    return (el.tag, tuple(sorted(at.items())), (el.text or "").strip())


def walk(a, b, path, diffs, stats):
    stats["nodes"] += 1
    if sig(a) != sig(b):
        stats["diffs"] += 1
        if len(diffs) < 30:
            diffs.append((path + "/" + a.tag, sig(a), sig(b)))
    ca, cb = list(a), list(b)
    if len(ca) != len(cb):
        stats["diffs"] += 1
        diffs.append((path + "/" + a.tag, "children=%d" % len(ca), "children=%d" % len(cb)))
        return
    for i, (x, y) in enumerate(zip(ca, cb)):
        walk(x, y, "%s/%s[%d]" % (path, a.tag, i), diffs, stats)


def main():
    fa, fb = rel(A), rel(B)
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    both = sorted(set(fa) & set(fb))
    print("独立解析器（WitchyBND / SoulsFormatsNEXT）整树比对")
    print("  文件数: 原图 %d / patch 后 %d ；同名可比 %d" % (len(fa), len(fb), len(both)))
    print("  只在原图有: %d %s" % (len(only_a), only_a[:5]))
    print("  只在 patch 后有: %d %s" % (len(only_b), only_b[:5]))
    byte_diff = [f for f in both if open(fa[f], "rb").read() != open(fb[f], "rb").read()]
    print("  字节不同的文件: %d / %d" % (len(byte_diff), len(both)))
    print("  ---- 字节不同的文件（前 20）----")
    for f in byte_diff[:20]:
        print("   ", f)
    stats = {"nodes": 0, "diffs": 0}
    diffs = []
    for f in byte_diff:
        if not f.lower().endswith(".xml"):
            continue
        ta = ET.parse(fa[f]).getroot()
        tb = ET.parse(fb[f]).getroot()
        walk(ta, tb, f, diffs, stats)
    print("  ---- 这些 XML 的节点比对: 比较 %d 节点，不同 %d 节点 ----" % (stats["nodes"], stats["diffs"]))
    for p, x, y in diffs[:30]:
        print("   %s\n      orig   = %s\n      patched= %s" % (p, x, y))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
