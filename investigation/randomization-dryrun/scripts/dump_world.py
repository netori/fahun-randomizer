# dump_world.py — 导出 GUI 用的世界数据（三套基础 × 商店开/关）
import json, os, sys
DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import randomizer as R

out = {"generated_by": "dump_world.py", "bases": {}, "rules": {
    "caster_arch": list(R.CASTER_ARCH), "suf": R.SUF, "catcode": R.CATCODE,
    "basis_doc": {"guide": "局内职业说明书（GoodsCaption 8800-8895）",
                  "xlsx": "资料表·职业推荐道具表3.0",
                  "mix": "说明书 ∪ 推荐表"}}}
for basis in ("guide", "xlsx", "mix"):
    for shops in (True, False):
        items = R.load_world(shops, basis)
        out["bases"].setdefault(basis, {})["items" if shops else "items_noshop"] = {
            f"{cat}:{iid}": {"name": v["name"], "arch": v["arch"], "cat": cat, "domain": v["domain"],
                             "subpool": v["subpool"], "cells": v["cells"]}
            for (cat, iid), v in items.items()}
    print(f"  {basis}: 有商店 {len(out['bases'][basis]['items'])} / 无商店 {len(out['bases'][basis]['items_noshop'])}")
json.dump(out, open(os.path.join(DRY, "world.json"), "w", encoding="utf-8"), ensure_ascii=False)
with open(os.path.join(DRY, "world.js"), "w", encoding="utf-8") as f:
    f.write("/* world.js — 自动生成（dump_world.py），供 GUI 以 file:// 打开 */\nwindow.WORLD = ")
    json.dump(out, f, ensure_ascii=False)
    f.write(";\n")
print("world.json / world.js 写出:", os.path.getsize(os.path.join(DRY, "world.js")), "B")
