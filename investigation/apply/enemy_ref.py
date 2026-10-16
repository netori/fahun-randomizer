# -*- coding: utf-8 -*-
"""参考实现的敌人标注 → 我们随包发的表（investigation/enemy_ref.csv）

来源：thefifthmatt 的 ER Randomizer 自带 `diste/Base/enemy.txt`（23173 条人工维护的条目）。
每条：ID / Map / Name(形如 c4280_9070，**带模型号**) / Class / Tags / ExtraName / BuddyGroup / ...
它不带源码，但数据可以读；我们**只把结论（模型 → 档位/标签）转成自己的表**，
运行时不依赖它那边任何文件（玩家机器上也不需要）。

它比我们自研分类强的地方：
  * Class 是人工档位（Basic / Miniboss / Boss / None / Helper / Evergaol），我们只有 boss/elite/normal
  * Tags 里带 `multi`（多阶段 Boss）、`size:N`（体型档）、`arena:N`（战斗场地）、
    `exclude:unkillable`（打不死的）、`perceptive`（会察觉）、`npcitem`（会给 NPC 物品）…
    —— `multi` 正是"多阶段整组换"缺的那份名单；`exclude:unkillable` 是安全项。

产出列：model, ref_class, ref_class_top, n_entries, tags, multi, unkillable, size, arena, extra_names
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
REF = (r"C:\Users\20905\Downloads\Elden Ring Randomizer 428 v0.12.2 "
       r"2026-09-09T07-25Z kRGZWDlvJ\randomizer\diste\Base\enemy.txt")
OUT = os.path.join(DATA, "enemy_ref.csv")
IDMAP = os.path.join(DATA, "enemy_ref_by_id.csv")


def parse_ref(path=REF):
    """→ 条目列表（每条一个 dict）"""
    entries, cur = [], None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if s.startswith("- ID:"):
                if cur:
                    entries.append(cur)
                cur = {"ID": s.split(":", 1)[1].strip()}
            elif s.startswith("  ") and ":" in s and cur is not None:
                k, v = s.strip().split(":", 1)
                if k in cur:                      # 同键多值 → 拼起来
                    cur[k] = cur[k] + ";" + v.strip()
                else:
                    cur[k] = v.strip()
    if cur:
        entries.append(cur)
    return entries


def build(entries):
    """→ (model → 汇总, id → 汇总)"""
    by_model = collections.defaultdict(lambda: {"cls": collections.Counter(), "tags": collections.Counter(),
                                                "extra": set(), "n": 0})
    by_id = {}
    for e in entries:
        m = re.match(r"(c[0-9]{3,4})_", e.get("Name", "") or "")
        rid = e.get("ID", "")
        tags = [t.strip() for t in (e.get("Tags") or "").replace(";", " ").split() if t.strip()]
        rec = {"model": m.group(1) if m else "",
               "ref_class": e.get("Class", "") or "",
               "tags": " ".join(tags),
               "map": e.get("Map", "") or "",
               "name": e.get("Name", "") or "",
               "extra_name": e.get("ExtraName", "") or "",
               "buddy": e.get("BuddyGroup", "") or ""}
        by_id[rid] = rec
        if not m:
            continue
        b = by_model[m.group(1)]
        b["n"] += 1
        if rec["ref_class"]:
            b["cls"][rec["ref_class"]] += 1
        for t in tags:
            b["tags"][t] += 1        # 存**完整**标签（size:2 / exclude:unkillable / arena:1 都要用）
        if rec["extra_name"]:
            b["extra"].add(rec["extra_name"])
    rows = []
    for mm, b in sorted(by_model.items()):
        top = b["cls"].most_common(1)[0][0] if b["cls"] else ""
        sizes = [t.split(":", 1)[1] for t in b["tags"] if t.startswith("size:")]
        arenas = [t.split(":", 1)[1] for t in b["tags"] if t.startswith("arena:")]
        percep = int(any(k == "perceptive" for k in b["tags"]))
        rows.append({
            "model": mm,
            "ref_class": "/".join("%s×%d" % (k, v) for k, v in b["cls"].most_common()),
            "ref_class_top": top,
            "n_entries": b["n"],
            "multi": int(b["tags"].get("multi", 0) > 0),
            "unkillable": int(any(k.startswith("exclude:unkillable") for k in b["tags"])),
            "size": sizes[0] if sizes else "",
            "arena": arenas[0] if arenas else "",
            "perceptive": percep,
            "extra_names": "、".join(sorted(b["extra"])[:3]),
        })
    return rows, by_id


def main():
    entries = parse_ref()
    rows, by_id = build(entries)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(IDMAP, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(by_id.values())).keys()))
        w.writeheader()
        for k, v in sorted(by_id.items(), key=lambda x: (len(x[0]), x[0])):
            w.writerow(v)
    n_multi = sum(r["multi"] for r in rows)
    n_unk = sum(r["unkillable"] for r in rows)
    print("条目 %d ｜ 模型 %d ｜ 带 multi 的模型 %d ｜ 带 exclude:unkillable 的 %d"
          % (len(entries), len(rows), n_multi, n_unk))
    print("→", OUT)
    print("→", IDMAP)
    import collections as C
    print("档位分布（模型数）:", dict(C.Counter(r["ref_class_top"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
