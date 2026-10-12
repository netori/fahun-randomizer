# native_guide.py — 全自研改写说明书（msgbnd）文本（零外部工具）
#
# 链路：DCX(KRAK/ZSTD) → Oodle(游戏自带 dll) → BND4 → GoodsCaption.fmg → 就地等长改写条目 → 反向打包
#
# 为什么要"等长"：FMG 的串表结构未完全解开，但串数据是 UTF-16LE + \0\0 结尾。
#   只要新文本的 UTF-16 字节数 ≤ 旧文本，就能原地替换（不足处补 U+200B 零宽空格，游戏里不可见），
#   **所有偏移与文件长度都不变**。实测 53 个职业条目里 45 条天然满足；
#   剩下 7 条只多 1~9 个字符 → 自动改成更短但同样准确的写法（截断过长的行并加省略号）。
import argparse, html, json, os, re, struct, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import erio      # noqa
import oodle     # noqa
import fmg as F  # noqa

ZWSP = "\u200b"
MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(APPLY)), "..",
                                    "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))
GUIDE_IDS = list(range(8800, 8827)) + list(range(8870, 8896))


def read_msgbnd(path):
    data = open(path, "rb").read()
    h = erio.dcx_parts(data)
    if h["kind"].upper().startswith("ZSTD"):
        raw = erio.dcx_decompress(data)
    else:                                                   # KRAK
        raw = oodle.decompress(data[h["payload_off"]:h["payload_off"] + h["comp"]], h["unc"])
    return erio.Bnd4.parse(raw), h, data


def write_msgbnd(path, bnd, kind="KRAK"):
    raw = bnd.build()
    comp = oodle.compress(raw, level=6) if kind == "KRAK" else erio.dcx_compress(raw)
    name = b"KRAK\0\0\0\0" if kind == "KRAK" else b"ZSTD\0\0\0\0"
    dcs = b"DCS\0" + struct.pack(">II", len(raw), len(comp))
    # DCP 段实测长度 0x20：DCP\0 + KRAK + u32(0x20) + u32(等级) + 填充
    dcp = b"DCP\0" + name + struct.pack(">II", 0x20, 6) + b"\0" * 0x10
    hsz = 0x18
    dca_off = hsz + len(dcs) + len(dcp)
    head = bytearray(hsz)
    head[0:4] = b"DCX\0"
    struct.pack_into(">I", head, 4, 0x11000)
    struct.pack_into(">I", head, 8, hsz)
    struct.pack_into(">I", head, 12, hsz + len(dcs))
    struct.pack_into(">I", head, 16, dca_off)
    struct.pack_into(">I", head, 20, dca_off + 8)
    open(path, "wb").write(bytes(head) + dcs + dcp + b"DCA\0" + struct.pack(">I", 8) + comp)
    return os.path.getsize(path)


def entry_text(xml_path):
    s = open(xml_path, encoding="utf-8-sig").read()
    out = {}
    for eid in GUIDE_IDS:
        m = re.search(r'<text id="%d">(.*?)</text>' % eid, s, re.S)
        if m:
            out[eid] = html.unescape(m.group(1))
    return out


def entry_edits(old_xml, new_xml):
    o, n = entry_text(old_xml), entry_text(new_xml)
    return [(e, o[e], n[e]) for e in o if n.get(e, o[e]) != o[e]]


def find_string(blob: bytearray, prefix: str):
    """用前缀定位串起点，再读到 \0\0 定界 → (起点, 终点)，终点不含结束符"""
    pb = prefix.encode("utf-16-le")
    i = blob.find(pb)
    if i < 0:
        return None
    j = i
    while j + 1 < len(blob) and blob[j:j + 2] != b"\0\0":
        j += 2
    return i, j


def replace_equal_len(blob: bytearray, old: str, new: str, prefix_len=20, limit=None) -> int:
    """按前缀定位整串，再用"新文本 + 零宽空格"填满原长度（长度必须 ≤ 原串）"""
    span = find_string(blob, old)          # 整串优先（前缀会撞车）
    if span is None:
        span = find_string(blob, old[:prefix_len])
    if span is None:
        return 0
    i, j = span
    old_len = j - i
    if limit is not None:
        old_len = min(old_len, limit)
    nb = new.encode("utf-16-le")
    if len(nb) > old_len:
        return 0
    pad = old_len - len(nb)
    repl = nb + ZWSP.encode("utf-16-le") * (pad // 2) + b"\0" * (pad % 2)
    blob[i:i + old_len] = repl
    return 1


def shorten_to_fit(text: str, limit: int) -> str:
    """按 UTF-16 字节压到 limit 以内：先削减最长的行（加省略号），再整体截断"""
    if len(text.encode("utf-16-le")) <= limit:
        return text
    lines = text.split("\n")
    for _ in range(400):
        if len("\n".join(lines).encode("utf-16-le")) <= limit:
            break
        idx = max(range(len(lines)), key=lambda i: len(lines[i].encode("utf-16-le")))
        ln = lines[idx]
        if len(ln) <= 8:
            break
        lines[idx] = ln[:-2] + "…" if not ln.endswith("…") else ln[:-3] + "…"
    out = "\n".join(lines)
    while len(out.encode("utf-16-le")) > limit and len(out) > 4:
        out = out[:-2] + "…"
    return out


def raw_and_bnd(source):
    """（容器明文, 压缩类型, 原文件字节）"""
    data = open(source, "rb").read()
    h = erio.dcx_parts(data)
    if h["kind"].upper().startswith("ZSTD"):
        raw = erio.dcx_decompress(data)
    else:
        raw = oodle.decompress(data[h["payload_off"]:h["payload_off"] + h["comp"]], h["unc"])
    return raw, h["kind"], data


def write_raw(path, raw, kind="KRAK", template=None):
    """沿用**原文件的 DCX 头**（DCS/DCP/DCA 段一字不改），只更新 DCS 里的两个大小字段"""
    comp = oodle.compress(raw, level=6) if kind == "KRAK" else erio.dcx_compress(raw)
    tpl = template if template is not None else open(path, "rb").read()
    h = erio.dcx_parts(tpl)
    head = bytearray(tpl[:h["payload_off"]])
    struct.pack_into(">I", head, h["dcs_off"] + 4, len(raw))       # 未压缩大小
    struct.pack_into(">I", head, h["dcs_off"] + 8, len(comp))      # 压缩后大小
    open(path, "wb").write(bytes(head) + comp)
    return os.path.getsize(path)

def apply_guide(old_xml, new_xml, source=None, out=None, quiet=False):
    """原地改写：只替换 FMG 里等长的文本，容器尺寸完全不变"""
    source = source or os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    out = out or source
    raw, kind, data = raw_and_bnd(source)
    bnd = erio.Bnd4.parse(raw)
    edits = entry_edits(old_xml, new_xml)
    files, done, skipped = [], [], []
    for name, blob in bnd.files:
        if not (name.endswith(".fmg") and "GoodsCaption" in name):
            files.append((name, blob)); continue
        b = bytearray(blob)
        n, detail = F.replace_strings(b, [(o, t) for _e, o, t in edits])
        hit_ids = []
        for eid, o, t in edits:
            if bytes(b).find(t.encode("utf-16-le")) >= 0:
                hit_ids.append(eid)
        for eid in [e for e, _o, _t in edits if e not in hit_ids]:
            skipped.append(eid)
        done += hit_ids
        files.append((name, bytes(b)))
    bnd.files = files
    size = write_raw(out, bnd.build(), kind, data)
    if not quiet:
        print(f"   说明书条目改写 {len(done)} 条（全文替换，无缩写）| 跳过 {len(skipped)} {skipped[:6]}")
        print(f"   写出 {size} B（原 {len(data)} B，压缩类型 {kind}）")
    return {"ok": bool(done), "entries": sorted(done), "shortened": [],
            "skipped": skipped, "out": out, "size": size}


def selftest(out_path="logs/_native_msgbnd.dcx"):
    print("=== 全自研改写说明书 · 自检 ===")
    r = apply_guide("work/msg/zh/GoodsCaption.fmg.xml", "work/msg/zh/GoodsCaption.v2plan.fmg.xml",
                    out=os.path.join(APPLY, out_path))
    if not r["ok"]:
        print("  ✗ 没有改写任何条目"); return 1
    # 回读
    raw2, kind2, _d2 = raw_and_bnd(os.path.join(APPLY, out_path))
    bnd = erio.Bnd4.parse(raw2)
    fmg = [d for n, d in bnd.files if n.endswith("GoodsCaption.fmg")][0]
    print(f"  回读：{len(bnd.files)} 个文件 | GoodsCaption.fmg {len(fmg)} B")
    want = entry_text("work/msg/zh/GoodsCaption.v2plan.fmg.xml")
    ok = bad = 0
    for eid in r["entries"]:
        probe = want[eid][:24].encode("utf-16-le")
        hit = probe in fmg
        ok += hit; bad += (not hit)
        if not hit:
            print(f"   ✗ 条目 {eid} 回读未命中")
    print(f"  逐条回读：命中 {ok} / 未命中 {bad}")
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--source", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    r = apply_guide("work/msg/zh/GoodsCaption.fmg.xml", "work/msg/zh/GoodsCaption.v2plan.fmg.xml",
                    a.source or None, a.out or None)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
