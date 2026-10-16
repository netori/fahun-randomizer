# -*- coding: utf-8 -*-
"""从 EMEVD 的 .js 反编译版里抽出"有血条的 Boss"名单（只读）

为什么可行：法魂自带 535 个事件脚本，每个 `.emevd.dcx` 旁边都有 `.js` 反编译版，
里面能直接搜到 `DisplayBossHealthBar(Enabled, <实体id>, <槽位>, <名字id>)`。
名字 id 在 NpcName.fmg 的 9 亿号段里（例如 904750000 → “接肢”葛瑞克），
而 NpcParam 里 Boss 行的 nameId 基本是 0 —— 所以**Boss 的显示名只能从这里拿**。

产出：investigation/boss_healthbar.csv（地图 / 实体 / 槽位 / 名字id / 名字）
"""
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER          # 复用它的 MOD 路径解析（别自己拼层级，容易差一层）

# _mod_reg() = <MOD>/mod/regulation.bin → 往上两级就是 <MOD>
MOD = os.environ.get("CONVERGENCE_MOD_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(ER._mod_reg())))
EVENT_DIR = os.path.join(MOD, "mod", "event")
OUT = os.path.join(HERE, "..", "boss_healthbar.csv")

RE_CALL = re.compile(r"DisplayBossHealthBar\(\s*(\w+)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)")
RE_PLACEHOLDER = re.compile(r"^X\d+_\d+$")


def main():
    import enemy_names as EN
    names = EN.load_names()
    flat = {}
    for k, tbl in names.items():
        for i, s in tbl.items():
            flat.setdefault(i, s)

    rows, files = [], 0
    for p in sorted(glob.glob(os.path.join(EVENT_DIR, "*.js"))):
        files += 1
        mapid = os.path.basename(p).split(".")[0]
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in RE_CALL.finditer(text):
            state, ent, slot, nid = m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()
            if state != "Enabled":
                continue
            if RE_PLACEHOLDER.match(ent) or RE_PLACEHOLDER.match(nid):
                continue                      # 模板（X0_4 之类），不是具体 Boss
            if not ent.isdigit():
                continue
            e = int(ent)
            n = int(nid) if nid.isdigit() else 0
            rows.append({"map": mapid, "entity": e, "slot": slot,
                         "name_id": n, "name": flat.get(n, "") if n else ""})
    print(f"扫了 {files} 个事件脚本，得到 {len(rows)} 条具体的血条调用")
    uniq = sorted({r["entity"] for r in rows})
    named = [r for r in rows if r["name"]]
    print(f"  唯一实体 {len(uniq)} ｜ 有名字的调用 {len(named)} ｜ 唯一名字 {len({r['name'] for r in named})}")

    # 按地图统计
    import collections
    per_map = collections.Counter(r["map"] for r in rows)
    print(f"  覆盖地图 {len(per_map)} 张（前 6：{per_map.most_common(6)}）")

    # 去重后写出
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: (x["map"], x["entity"], x["slot"])):
        key = (r["map"], r["entity"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["map", "entity", "slot", "name_id", "name"])
        w.writeheader()
        w.writerows(out)
    print(f"  → {os.path.abspath(OUT)}（{len(out)} 行，按 地图+实体 去重）")

    print("\n=== 样例（有名字的）===")
    for r in [x for x in out if x["name"]][:14]:
        print(f"  {r['map']:<14} {r['entity']:>10}  {r['name']}")
    print("\n=== 交叉验证：追忆名单里的 Boss 有没有出现在血条列表里 ===")
    want = ["葛瑞克", "玛尔基特", "拉塔恩", "玛莲妮亚", "梅瑟莫", "蒙格特", "玛利喀斯", "蕾娜菈"]
    allnames = {r["name"] for r in out}
    for w in want:
        hit = [n for n in allnames if w in n]
        print(f"  {w}: {'✓ ' + hit[0] if hit else '（没找到）'}")

    print("\n=== 反例：名字 id 是 0 的调用（血条不显示名字）===")
    z = [r for r in out if not r["name"]]
    print(f"  {len(z)} 条，样例 {[(r['map'], r['entity']) for r in z[:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
