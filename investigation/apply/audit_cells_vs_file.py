#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对账：世界里的每个格子 vs 原始 regulation.bin 的实际内容。

为什么需要：引擎的格子在 `lot_reward_index.json` 里（生成物），一旦索引和游戏文件
对不上（换过 MOD 版本、索引是旧文件建的、同一 lot 有两条来源），计划里就会带着
一个"文件里其实是空槽"的格子 —— **写前复核（H12）会因此中止整次写入**，
表现是"点了写入什么也没发生"。2026-10-14 就踩到一个（见 stale_cells.json 的 why）。

用法：
    python audit_cells_vs_file.py              # 对账并报告
    python audit_cells_vs_file.py --json       # 机器可读
    python audit_cells_vs_file.py --fix        # 把对不上的格子写进 stale_cells.json（需人工确认）
"""
import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(HERE))          # ...\随机mod
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "investigation", "randomization-dryrun", "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="把对不上的格子追加进 stale_cells.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    import erio
    import native_apply as na
    import param_patch as pp
    import randomizer as R

    pris = sorted(glob.glob(os.path.join(HERE, "backup", "regulation.bin.orig_*")))
    if not pris:
        print("找不到原始备份（backup/regulation.bin.orig_*）—— 先用「补一份原始备份」登记一份")
        return 1
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(pris[-1])))

    items = R.load_world(True, "guide")
    by_table = collections.defaultdict(list)
    for k, v in items.items():
        for c in v["cells"]:
            if c["source_table"].startswith("ItemLotParam"):
                by_table[c["source_table"]].append((c["row_id"], str(c["slot"] or 1), f"{k[0]}:{k[1]}",
                                                    int(k[1]), c.get("row_name", "")))
    n_all, bad = 0, []
    for table, rows in by_table.items():
        tbl = na.find_row_table_in_plain(plain, table)
        for rid, slot, key, want, row_name in rows:
            n_all += 1
            oi = pp.offset_of(table, tbl, int(rid), "lotItemId", int(slot))
            if oi is None:
                bad.append({"cell": f"{table}:{rid}:{slot}", "index": key, "file": None,
                            "why": "取不到偏移", "row_name": row_name})
                continue
            got = pp.read_u32(plain, oi)
            if got != want:
                bad.append({"cell": f"{table}:{rid}:{slot}", "index": key, "file": got,
                            "why": "文件里是空槽" if got == 0 else "文件里是别的物品",
                            "row_name": row_name})

    if a.json:
        print(json.dumps({"checked": n_all, "bad": bad}, ensure_ascii=False, indent=1))
    else:
        print(f"对账：{n_all} 个格子 vs {os.path.basename(pris[-1])}")
        print(f"  对不上的：{len(bad)} 个")
        for b in bad:
            print(f"    {b['cell']:<34} 索引={b['index']:<22} 文件={b['file']} ｜ {b['why']} ｜ {b['row_name'][:36]}")

    if a.fix and bad:
        p = os.path.join(HERE, "stale_cells.json")       # 与代码一起入库，别放 evidence/（那是本地生成物）
        doc = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"stale": []}
        old = list(doc.get("stale") or [])
        for b in bad:
            if b["cell"] not in old:
                old.append(b["cell"])
                doc.setdefault("why", {})[b["cell"]] = f"{b['why']}（索引={b['index']}），自动登记，请人工核对"
        doc["stale"] = old
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"\n已登记进 {p}（{len(old)} 条）")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
