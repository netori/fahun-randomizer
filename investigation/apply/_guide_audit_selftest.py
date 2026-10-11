# _guide_audit_selftest.py — 审计的“自我检验”（变异测试）
#   人为制造 4 类已知故障，确认 _guide_audit 全部能抓到；再用成品确认无“误报”。
#   用法: python _guide_audit_selftest.py
import glob, os, re, sys
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import _guide_audit as GA

BASE = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
MUT = os.path.join(APPLY, "work", "msg", "zh", "_mut.fmg.xml")

MUTATIONS = {
    "丢标签":   lambda i, t, allt: (t.replace('<font color="#FFA500">', "", 1) if i == 8800 else t),
    "超长":     lambda i, t, allt: (t + "额外内容" * 8 if i == 8802 else t),
    "串页":     lambda i, t, allt: (allt.get(8891, t) if i == 8821 else t),
    "空地点":   lambda i, t, allt: (re.sub(r"( - )[^\n]+", r"\1", t) if i == 8807 else t),
    "物品名改": lambda i, t, allt: (t.replace("葛瑞克骑士臂甲", "某某臂甲", 1) if i == 8800 else t),
}


def _latest():
    xs = sorted(glob.glob(os.path.join(APPLY, "work", "msg", "zh", "*.fmg.xml")), key=os.path.getmtime)
    depl = [x for x in xs if "deploy_" in x and "fitted" not in x and "_mut" not in x]
    fits = [x for x in xs if "fitted" in x and "audit" not in x and "_mut" not in x]
    return (depl[-1] if depl else None), (fits[-1] if fits else None)


def main():
    depl, fitted = _latest()
    if not depl:
        print("  找不到 deploy XML（先跑一次写入）"); return 1
    print(f"  中间产物: {os.path.basename(depl)}")
    print(f"  成品    : {os.path.basename(fitted) if fitted else '（无）'}\n")

    bad = 0
    print("  ① 变异测试（预期：全部被抓到）")
    for kind, fn in MUTATIONS.items():
        tree = ET.parse(depl)
        allt = {int(e.get("id")): (e.text or "") for e in tree.getroot().iter()
                if e.get("id") and e.tag.lower().endswith("text")}
        for e in tree.getroot().iter():
            i = e.get("id")
            if i is None or not e.tag.lower().endswith("text"):
                continue
            e.text = fn(int(i), e.text or "", allt)
        tree.write(MUT, encoding="utf-8", xml_declaration=True)
        fails = GA.audit(BASE, MUT, MUT, quiet=True)
        ok = len(fails) > 0
        bad += 0 if ok else 1
        print(f"     {kind:<8} → {'抓到 ✓' if ok else '**没抓到 ✗**'}（{len(fails)} 处）")

    print("\n  ② 误报检查（预期：成品 0 处、中间产物被拦）")
    if fitted:
        f = GA.audit(BASE, depl, fitted, quiet=True)
        bad += 0 if not f else 1
        print(f"     成品     → {'通过 ✓（0 处）' if not f else f'✗ 误报 {len(f)} 处'}")
    f2 = GA.audit(BASE, depl, depl, quiet=True)
    bad += 0 if f2 else 1
    print(f"     中间产物 → {'拦下 %d 处 ✓（符合预期）' % len(f2) if f2 else '✗ 未拦（有问题）'}")

    for x in glob.glob(os.path.join(APPLY, "work", "msg", "zh", "_mut*")):
        os.remove(x)
    print(f"\n  {'✓ 审计自检通过' if not bad else '✗ 自检失败 %d 项' % bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
