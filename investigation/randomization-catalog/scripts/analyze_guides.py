# analyze_guides.py — 定位"职业路线/装备说明书"类 FMG 条目
# 只读。扫描 GoodsCaption（MOD 的说明书正文）与 GoodsInfo，找含职业/推荐/说明特征的条目，
# 并把条目正文里提到的物品名与已确认的名称表（武器/防具/道具）对齐。
# 输出：evidence/guide_entries.json
import xml.etree.ElementTree as ET
import os, json, re, collections, sys

CAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(CAT, "evidence")
WB = os.path.join(os.path.dirname(CAT), "weapon-baseline", "evidence")
RB = os.path.join(WB, "work2", "regulation-bin")

PATTERNS = ["值得注意的武器", "主要使用", "职业", "推荐", "配装", "路线", "攻略", "Build", "build"]


def fmg_map(*paths):
    d = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        root = ET.parse(p).getroot()
        for e in root.findall(".//text"):
            d[(os.path.basename(p), e.get("id"))] = (root.find("filename").text if root.find("filename") is not None else "",
                                                     e.text or "")
    return d


def names_from(paths):
    out = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        root = ET.parse(p).getroot()
        for e in root.findall(".//text"):
            if e.text:
                out[e.get("id")] = e.text
    return out


def main():
    gc = fmg_map(os.path.join(WB, "xml", "GoodsCaption.fmg.xml"), os.path.join(EV, "xml", "GoodsCaption_dlc01.fmg.xml"))
    gi = fmg_map(os.path.join(EV, "xml", "GoodsInfo.fmg.xml"), os.path.join(EV, "xml", "GoodsInfo_dlc01.fmg.xml"))
    print("GoodsCaption 条目:", len(gc), "| GoodsInfo 条目:", len(gi))

    weapon_zh = names_from([os.path.join(WB, "xml", "WeaponName.fmg.xml"), os.path.join(WB, "xml", "WeaponName_dlc01.fmg.xml")])
    prot_zh = names_from([os.path.join(EV, "xml", "ProtectorName.fmg.xml"), os.path.join(EV, "xml", "ProtectorName_dlc01.fmg.xml")])
    goods_zh = names_from([os.path.join(EV, "xml", "GoodsName.fmg.xml"), os.path.join(EV, "xml", "GoodsName_dlc01.fmg.xml")])
    print("名称表：武器", len(weapon_zh), "防具", len(prot_zh), "道具", len(goods_zh))

    w_names = {v: k for k, v in weapon_zh.items() if len(v) >= 3}
    p_names = {v: k for k, v in prot_zh.items() if len(v) >= 3}
    g_names = {v: k for k, v in goods_zh.items() if len(v) >= 3}

    hits = []
    for (fn, eid), (fname, text) in list(gc.items()) + list(gi.items()):
        if not text:
            continue
        if not any(p in text for p in PATTERNS):
            continue
        plain = re.sub(r"<[^>]+>", "", text)
        mentioned_w = sorted({n for n in w_names if n in plain})
        mentioned_p = sorted({n for n in p_names if n in plain})
        mentioned_g = sorted({n for n in g_names if n in plain})
        hits.append({"fmg_file": fname or fn, "entry_id": eid, "source_path": fn,
                     "text_raw": text, "text_plain": plain,
                     "mentions_weapon_names": [{"name": n, "id": w_names[n]} for n in mentioned_w],
                     "mentions_protector_names": [{"name": n, "id": p_names[n]} for n in mentioned_p],
                     "mentions_goods_names": [{"name": n, "id": g_names[n]} for n in mentioned_g]})
    print("命中职业/说明书类条目:", len(hits))
    by_file = collections.Counter(h["fmg_file"] for h in hits)
    print("按文件:", dict(by_file))
    for h in hits[:14]:
        first = h["text_plain"].strip().splitlines()[0][:46] if h["text_plain"].strip() else ""
        print("   %-26s id=%-12s 武器%d 防具%d 道具%d | %s" % (h["fmg_file"], h["entry_id"],
              len(h["mentions_weapon_names"]), len(h["mentions_protector_names"]), len(h["mentions_goods_names"]), first))
    json.dump({"patterns": PATTERNS,
               "note": "text_raw 为还原后的原文（含 <font> 等标记）；mentions_* 以 MOD 自身名称表逐字包含匹配，不做翻译猜测",
               "entries": hits}, open(os.path.join(EV, "guide_entries.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("写出 evidence/guide_entries.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
