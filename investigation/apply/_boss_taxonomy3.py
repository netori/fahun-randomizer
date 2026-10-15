# -*- coding: utf-8 -*-
"""法魂 Boss 分类 · 第三轮（只读）

1) 每个 FMG 文件分别解析（避免合并时互相干扰）→ 追忆类物品的确切数量与名单
2) 大锅系列物品的**说明文本**（谁给的、怎么来的）
3) NpcName 全量导出 → 找出"法魂自定义"的条目（命名风格）
"""
import os
import sys
import importlib.util

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa
import native_guide as ng

spec = importlib.util.spec_from_file_location("bt", os.path.join(WS, "_boss_taxonomy.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)
MOD = bt.MOD


def main():
    msg = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    bnd, _h, _raw = ng.read_msgbnd(msg)
    files = {n.split("\\")[-1].replace(".fmg", ""): bt.fmg_parse(d) for n, d in bnd.files}

    print("=== 1) 逐文件的追忆类物品 ===")
    total = 0
    for fname in ("GoodsName", "GoodsName_dlc01", "GoodsName_dlc02"):
        tbl = files.get(fname, {})
        rem = [(i, s) for i, s in sorted(tbl.items()) if "追忆" in s]
        total += len(rem)
        print(f"\n  【{fname}】{len(tbl)} 条物品，其中追忆 {len(rem)}")
        for i, s in rem:
            print(f"    [{i}] {s}")
    print(f"\n  追忆合计: {total}")

    print("\n=== 2) 大锅系列：物品说明（找持有者）===")
    for tbl, cap, info in (("GoodsName", "GoodsCaption", "GoodsInfo"),) * 1:
        pass
    names = files.get("GoodsName", {})
    for i, s in sorted(names.items()):
        if "大锅" in s or "钥石" in s:
            desc = files.get("GoodsCaption", {}).get(i) or files.get("GoodsCaption_dlc01", {}).get(i)
            inf = files.get("GoodsInfo", {}).get(i)
            print(f"\n  [{i}] {s}")
            if inf:
                print(f"      效果: {inf[:110].replace(chr(10), ' / ')}")
            if desc:
                print(f"      说明: {desc[:200].replace(chr(10), ' / ')}")

    print("\n=== 3) NpcName 全量（%d 条）——按关键词分组" % len(files.get("NpcName", {})))
    npc = files.get("NpcName", {})
    buckets = {
        "追忆/Boss 相关（带引号称号）": [s for s in npc.values() if s.startswith("“")],
        "法魂风格（大锅/传送门/秘境）": [s for s in npc.values() if any(k in s for k in ("大锅", "传送门", "秘境", "祭坛"))],
        "普通": [s for s in npc.values() if not s.startswith("“") and not any(k in s for k in ("大锅", "传送门", "秘境", "祭坛"))],
    }
    for k, v in buckets.items():
        print(f"\n  【{k}】{len(v)} 条")
        print(f"    {v[:18]}")


if __name__ == "__main__":
    main()
