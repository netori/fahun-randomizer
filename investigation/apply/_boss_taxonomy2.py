# -*- coding: utf-8 -*-
"""法魂 Boss 分类 · 第二轮（只读，复用 _boss_taxonomy 的读取器）

目标：把"类别凭证"摊成名单与数量
  A. 追忆 / 次级追忆 物品清单
  B. 大锅系列物品清单
  C. NpcName 里的 Boss 候选（含传送门等法魂自定义条目）
  D. 把追忆名字与 NpcName 做名字匹配 → 每类大概有几个 Boss
"""
import os
import sys

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa
import importlib.util

spec = importlib.util.spec_from_file_location("bt", os.path.join(WS, "_boss_taxonomy.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

MOD = bt.MOD


def load_fmgs():
    import native_guide as ng
    msg = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    bnd, _h, _raw = ng.read_msgbnd(msg)
    out = {}
    for n, d in bnd.files:
        short = n.split("\\")[-1].replace(".fmg", "")
        out[short] = bt.fmg_parse(d)
    return out


def main():
    fmgs = load_fmgs()
    goods = {}
    for k in ("GoodsName", "GoodsName_dlc01", "GoodsName_dlc02"):
        goods.update(fmgs.get(k, {}))
    npc = {}
    for k in ("NpcName", "NpcName_dlc01", "NpcName_dlc02"):
        npc.update(fmgs.get(k, {}))
    print(f"物品名 {len(goods)} 条｜敌人名 {len(npc)} 条\n")

    def pick(tbl, kws, exclude=()):
        out = []
        for i, s in sorted(tbl.items()):
            if any(k in s for k in kws) and not any(e in s for e in exclude):
                out.append((i, s))
        return out

    print("=== A. 追忆类物品 ===")
    rem = pick(goods, ["追忆"])
    print(f"  含「追忆」的物品: {len(rem)}")
    for i, s in rem[:40]:
        print(f"    [{i}] {s}")
    sec = pick(goods, ["次级"])
    print(f"\n  含「次级」的物品: {len(sec)}")
    for i, s in sec[:30]:
        print(f"    [{i}] {s}")

    print("\n=== B. 大锅 / 钥石 系列 ===")
    for i, s in pick(goods, ["大锅", "钥石"]):
        print(f"    [{i}] {s}")

    print("\n=== C. NpcName 里的「Boss 感」条目 ===")
    for kw in ("传送门", "大锅", "追忆", "黄金树", "女王", "王", "神", "龙", "领主", "骑士长"):
        hit = pick(npc, [kw])
        if hit:
            print(f"  【{kw}】{len(hit)}: {[s for _i, s in hit[:8]]}")

    print("\n=== D. 追忆 → Boss 名字匹配（用追忆名的关键词去 NpcName 里找）===")
    npc_names = list(npc.values())
    matched, unmatched = [], []
    for i, s in rem:
        stem = s.replace("的追忆", "").replace("追忆", "").strip("“”")
        if not stem:
            continue
        hit = [n for n in npc_names if stem and stem in n]
        if hit:
            matched.append((s, hit[:3]))
        else:
            unmatched.append(s)
    print(f"  匹配上 {len(matched)} / 没匹配上 {len(unmatched)}")
    for s, hit in matched[:20]:
        print(f"    {s}  →  {hit}")
    if unmatched:
        print(f"  未匹配的: {unmatched[:14]}")


if __name__ == "__main__":
    main()
