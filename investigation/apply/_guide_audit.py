# _guide_audit.py — 说明书链路正则/字符串操作的系统审计
#   对每条不变量做自动检查，任何一条不成立都会明确报出来
import glob, os, re, sys
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)

ZW = "\u200b"
GIDS = [i for i in range(8800, 8827)] + [i for i in range(8870, 8896)]
TAG = re.compile(r"<[^>]+>")


def rows(p):
    d = {}
    for e in ET.parse(p).getroot().iter():
        i = e.get("id")
        if i is not None and e.tag.lower().endswith("text"):
            d[int(i)] = e.text or ""
    return d


def pairs(text):
    """取出 (物品名, 地点) 列表"""
    return re.findall(r'<font color="#FFA500">([^<]+)</font> - ([^\n<]*)', text)


def names(text):
    return re.findall(r'<font color="#FFA500">([^<]+)</font>', text)


def audit(base_xml, deploy_xml, fitted_xml=None, quiet=False):
    a, b = rows(base_xml), rows(deploy_xml)
    c = rows(fitted_xml) if fitted_xml and os.path.exists(fitted_xml) else b
    fails = []
    def chk(ok, msg):
        if not ok:
            fails.append(msg)

    # ── ① 标签结构必须与原版一致（字号/颜色的来源）──
    for i in GIDS:
        if not a.get(i):
            continue
        ta, tc = TAG.findall(a[i]), TAG.findall(c.get(i, ""))
        if ta != tc:
            fails.append(f"[标签] id={i} 标签数量或顺序与原版不同（原 {len(ta)} / 现 {len(tc)}）")

    # ── ② 长度不得超过原版（否则会被游戏截尾）──
    for i in GIDS:
        if not a.get(i):
            continue
        if len(c.get(i, "")) > len(a[i]):
            fails.append(f"[长度] id={i} 超过原版 {len(c.get(i,''))-len(a[i])} 字")
        if len(c.get(i, "")) < len(a[i]):
            fails.append(f"[长度] id={i} 短于原版 {len(a[i])-len(c.get(i,''))} 字（未补齐）")

    # ── ③ 物品名必须与原版完全一致（规则：物品名不动，只改地点）──
    for i in GIDS:
        if not a.get(i):
            continue
        na, nc = names(a[i]), names(c.get(i, ""))
        if na != nc:
            miss = [x for x in na if x not in nc]
            fails.append(f"[物品名] id={i} 物品名有变化，缺失 {miss[:3]}")

    # ── ④ 地点不得为空、不得含英文/符号（内部名）──
    for i in GIDS:
        for item, dest in pairs(c.get(i, "")):
            if not dest.strip():
                fails.append(f"[空地点] id={i} 物品「{item}」地点为空")
            if re.search(r"[A-Za-z]{2,}", dest):
                fails.append(f"[英文地点] id={i} 物品「{item}」地点含英文：{dest[:24]}")
            if re.search(r"[\[\]{}<>]", dest):
                fails.append(f"[符号地点] id={i} 物品「{item}」地点含符号：{dest[:24]}")

    # ── ⑤ 条目之间不得互相覆盖（两页首行相同也不能串）──
    seen = {}
    for i in GIDS:
        t = c.get(i, "")
        if not t:
            continue
        key = t
        if key in seen:
            fails.append(f"[串页] id={i} 与 id={seen[key]} 的正文完全相同（疑似被覆盖）")
        seen[key] = i
    # 首行相同的两页必须仍然不同
    heads = {}
    for i in GIDS:
        t = c.get(i, "")
        if not t:
            continue
        h = t.split("\n")[0]
        if h in heads:
            j = heads[h]
            if c[i] == c[j]:
                fails.append(f"[串页·首行相同] id={i} 与 id={j} 首行相同且正文相同")
        heads[h] = i

    # ── ⑥ 每条的“物品-地点”数量必须与原版一致（不丢行）──
    for i in GIDS:
        if not a.get(i):
            continue
        pa, pc = pairs(a[i]), pairs(c.get(i, ""))
        if len(pa) != len(pc):
            fails.append(f"[行数] id={i} 物品-地点对 原 {len(pa)} / 现 {len(pc)}")

    # ── ⑦ 零宽补齐必须只在行尾（不得插在文字中间）──
    for i in GIDS:
        t = c.get(i, "")
        for m in re.finditer(ZW, t):
            p = m.start()
            # 允许：ZW 后面是行尾或结尾
            if p + 1 < len(t) and t[p+1] not in ("\n", ZW):
                fails.append(f"[补齐位置] id={i} 零宽字符出现在文字中间（@{p}）")
                break

    if not quiet:
        n = len([i for i in GIDS if a.get(i)])
        print(f"  审计范围: {n} 条职业说明书 ｜ 检查 7 组不变量")
        if fails:
            print(f"  ✗ 发现 {len(fails)} 处问题：")
            for f in fails[:20]:
                print("     ", f)
        else:
            print("  ✓ 7 组不变量全部通过")
    return fails


def audit_fmg(fitted_xml, base_xml, quiet=False):
    """⑧ 直接核对写进游戏的 FMG：每条新文本都必须在文件里，且不覆盖别人"""
    import erio, oodle, native_deploy as nd
    import fmg as F
    fails = []
    msg = os.path.join(nd.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    d = open(msg, "rb").read()
    pp = erio.dcx_parts(d)
    blob = oodle.decompress(d[pp["payload_off"]:], pp["unc"])
    b = erio.Bnd4.parse(blob)
    # 在所有内部文件里找**真正含有说明书正文**的那一个（同名 GoodsCaption 有多个，尺寸差很多）
    cap = None
    for (name, off, size) in b.spans:
        if "GoodsCaption" not in name:
            continue
        cand = blob[off:off + size]
        if cand.count("癫火狂徒".encode("utf-16-le")) or (
                cand.decode("utf-16-le", "ignore").find("职业") >= 0 and size > 100000):
            if cap is None or size > len(cap):
                cap = cand
    if cap is None:
        return ["[FMG] 没找到含说明书的 GoodsCaption"]
    a = rows(base_xml)
    c = rows(fitted_xml)
    txt = cap.decode("utf-16-le", "replace")
    for i in GIDS:
        t = c.get(i, "")
        if not t:
            continue
        if t not in txt:
            fails.append(f"[FMG] id={i} 的正文没有出现在游戏文件里（可能没写入或被覆盖）")
        elif a.get(i) and a[i] != t and a[i] in txt and i >= 8800 and i <= 8826:
            # 原版文本还在是正常的（未改动的行），这里只提示
            pass
    if not quiet:
        print(f"  FMG 核对: {'✓ 全部写入且未互相覆盖' if not fails else f'✗ {len(fails)} 处'}")
    return fails


def main():
    xs = sorted(glob.glob(os.path.join(APPLY, "work", "msg", "zh", "*.fmg.xml")), key=os.path.getmtime)
    base = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
    depl = [x for x in xs if "deploy_" in x and "fitted" not in x]
    # 审计用的适配结果每次都重新生成（避免用到陈旧文件）
    fit = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.audit.fitted.fmg.xml")
    if not depl:
        print("  没有找到 deploy XML"); return 1
    print(f"  基准: {os.path.basename(base)}")
    print(f"  生成: {os.path.basename(depl[-1])}")
    import _guide_fit
    _guide_fit.rewrite(depl[-1], base, fit)
    f1 = audit(base, depl[-1], fit)
    f1 += audit_fmg(fit, base)
    # 幂等性：再适配一次，结果必须一致
    import _guide_fit
    fit2 = fit.replace(".fmg.xml", ".2.fmg.xml")
    _guide_fit.rewrite(fit, base, fit2)
    d1, d2 = rows(fit), rows(fit2)
    idem = all(d1.get(i) == d2.get(i) for i in GIDS)
    print(f"\n  幂等性（再适配一次结果不变）: {'✓' if idem else '✗'}")
    if not idem:
        f1.append("[幂等] 二次适配结果不同")
    return 1 if f1 else 0


if __name__ == "__main__":
    raise SystemExit(main())
