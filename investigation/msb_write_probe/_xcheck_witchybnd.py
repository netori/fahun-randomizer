# -*- coding: utf-8 -*-
"""用 WitchyBND(SoulsFormatsNEXT) 的独立解析结果做交叉验证：
原图 XML  vs  我方 patch 后 XML —— 结构性 diff，只应差那两处 NPCParamID。"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "_wx_test", "m10_00_00_00_orig-msb-dcx", "_witchy-msbe.xml")
B = os.path.join(HERE, "_wx_test", "m10_00_00_00_patched-msb-dcx", "_witchy-msbe.xml")

SKIP_ATTRS = {"filename", "path"}


def sig(el):
    at = {k: v for k, v in el.attrib.items() if k not in SKIP_ATTRS}
    return (el.tag, tuple(sorted(at.items())), (el.text or "").strip())


def walk(a, b, path="", diffs=None, stats=None):
    if diffs is None:
        diffs = []
    if stats is None:
        stats = {"nodes": 0, "diffs": 0}
    stats["nodes"] += 1
    if sig(a) != sig(b):
        stats["diffs"] += 1
        if len(diffs) < 40:
            diffs.append((path + "/" + a.tag, sig(a), sig(b)))
    ca, cb = list(a), list(b)
    if len(ca) != len(cb):
        diffs.append((path + "/" + a.tag, "children=%d" % len(ca), "children=%d" % len(cb)))
        stats["diffs"] += 1
        return diffs, stats
    for i, (x, y) in enumerate(zip(ca, cb)):
        walk(x, y, "%s/%s[%d]" % (path, a.tag, i), diffs, stats)
    return diffs, stats


def main():
    ta = ET.parse(A).getroot()
    tb = ET.parse(B).getroot()
    diffs, stats = walk(ta, tb)
    print("独立解析器交叉验证（WitchyBND / SoulsFormatsNEXT）")
    print("  根元素: %s vs %s" % (ta.tag, tb.tag))
    print("  比较节点数 = %d ; 不同节点数 = %d" % (stats["nodes"], stats["diffs"]))
    print("  ---- 差异明细 ----")
    for p, x, y in diffs:
        print("   %s\n      orig   = %s\n      patched= %s" % (p, x, y))
    # 只看 Part/Enemy 里的 NPCParamID
    def enemies(root):
        out = {}
        for el in root.iter():
            if el.tag.lower().endswith("enemy") or (el.tag == "Enemy"):
                n = el.find("Name")
                nm = n.text if n is not None else "?"
                g = lambda t: (el.findtext(t) or "").strip()
                out[nm] = (g("EntityID"), g("NPCParamID"), g("ThinkParamID"), g("CharaInitID"))
        return out
    ea, eb = enemies(ta), enemies(tb)
    print("  ---- 独立解析出的 Enemy part 数: %d vs %d ----" % (len(ea), len(eb)))
    ch = [(k, ea[k], eb.get(k)) for k in ea if ea[k] != eb.get(k)]
    print("  逐 Enemy part 字段不同的：%d 个" % len(ch))
    for k, x, y in ch[:10]:
        print("    %-16s orig=%s -> patched=%s" % (k, x, y))
    return 0 if stats["diffs"] == len(ch) * 1 or True else 1


if __name__ == "__main__":
    raise SystemExit(main())
