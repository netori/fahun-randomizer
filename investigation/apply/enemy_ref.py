# -*- coding: utf-8 -*-
"""参考实现的敌人标注 → 我们随包发的表（investigation/enemy_ref.csv）

来源：thefifthmatt 的 ER Randomizer 自带 `diste/Base/enemy.txt`（23173 条人工维护的条目）。
每条：ID / Map / Name(形如 c4280_9070，**带模型号**) / Class / Tags / ExtraName / BuddyGroup / ...
它不带源码，但数据可以读；我们**只把结论（模型 → 档位/标签）转成自己的表**，
运行时不依赖它那边任何文件（玩家机器上也不需要）。

它比我们自研分类强的地方：
  * Class 是人工档位（Basic / Miniboss / Boss / None / Helper / Evergaol），我们只有 boss/elite/normal
  * Tags 里带 `multi`（多阶段 Boss）、`size:N`（体型档）、`arena:N`（战斗场地）、
    `perceptive`（会察觉）、`npcitem`（会给 NPC 物品）…
    —— `multi` 正是"多阶段整组换"缺的那份名单。

**unkillable 的口径**（2026-10-18 修正）：只认参考数据 `Groups:` 段里 `- Name: unkillable`
这一组 —— 该组 Models 是**显示名**（Lightning Ball / Eagle / Owl / Guillemot / Aging Untouchable），
必须拿 `Names/ModelName.txt` 的 `cXXXX 显示名` 反查成 c 模型（本机实测 9 个：
c2150/c5280/c5401/c5430/c5460/c6001/c6040/c6070/c6240）；另把带 `norandom` 标签的模型并入
（它明确不参与随机；实测 6 条标签全在 c5280，已在该集合里）。
**不要**拿 Tags 里的 `exclude:unkillable` 当"打不死"：它表示「从该保护里排除」（主 Boss 条目
自带它，例如 Margit / Godrick 的条目）；旧实现照它标，把 174 个模型误判成打不死，默认 Boss 池只剩 80 行。
`immortal` 标签也不用于排除（玛莲妮亚等真 Boss 带它）。

产出列：model, ref_class, ref_class_top, n_entries, multi, unkillable, size, arena, perceptive, extra_names
（逐条原始标签保留在 enemy_ref_by_id.csv 的 tags 列。）
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)
import modpaths          # noqa: E402
REF_DIR = modpaths.require_ref_dir()
REF = os.path.join(REF_DIR, "Base", "enemy.txt")
MODELNAME = os.path.join(REF_DIR, "Names", "ModelName.txt")
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


def parse_group_models(path=REF, name="unkillable"):
    """Groups: 段里某一组的 Models 清单。

    ⚠ 这里的条目是**显示名**（Lightning Ball / Eagle / Owl / Guillemot / Aging Untouchable），
    不是 c 模型号 —— 要查 `Names/ModelName.txt` 反查（见 parse_model_names）。
    """
    names, cur, in_groups = [], None, False
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if s.startswith("Groups:"):
                in_groups = True
                continue
            if not in_groups:
                continue
            if s and not s[0].isspace() and not s.startswith("-"):
                break                       # 下一个顶层段（Enemies: / PassiveAdjustments: …）
            m = re.match(r"^- Name:\s*(.+)$", s)
            if m:
                cur = m.group(1).strip()
                continue
            if cur == name:
                m = re.match(r"^\s+-\s+(.+)$", s)
                if m:
                    names.append(m.group(1).strip())
    return names


def parse_model_names(path=MODELNAME):
    """Names/ModelName.txt → {显示名: [c 模型]}（每行 `c2150 Lightning Ball`）"""
    out = collections.defaultdict(list)
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            parts = ln.strip().split(None, 1)
            if len(parts) == 2 and re.match(r"^c[0-9]{3,4}$", parts[0]):
                out[parts[1].strip()].append(parts[0])
    return out


def resolve_unkillable(entries):
    """参考口径的「打不死」模型集合 → (模型集合, 报告 dict)。

    来源两处（都**不是** Tags 里的 `exclude:unkillable`，那表示「从该保护里排除」）：
      ① Groups: 段 `- Name: unkillable` 的 Models（显示名）→ ModelName.txt 反查成 c 模型；
      ② Enemies: 段里带 `norandom` 标签的模型（明确不参与随机）。
    """
    group_names = parse_group_models(REF, "unkillable")
    name2models = parse_model_names()
    group_models, unmatched = set(), []
    for nm in group_names:
        got = name2models.get(nm) or []
        if not got:
            unmatched.append(nm)            # 查不到要如实报，不静默当空
        group_models.update(got)
    norandom = set()
    for e in entries:
        tags = [t.strip() for t in (e.get("Tags") or "").replace(";", " ").split() if t.strip()]
        if "norandom" in tags:
            m = re.match(r"(c[0-9]{3,4})_", e.get("Name", "") or "")
            if m:
                norandom.add(m.group(1))
    info = {"group_names": group_names, "group_models": sorted(group_models),
            "norandom": sorted(norandom), "unmatched": unmatched}
    return group_models | norandom, info


def build(entries, unk_models=None):
    """→ (model → 汇总, id → 汇总)"""
    unk_models = set(unk_models or ())
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
            # unkillable 只看参考 Groups.unkillable ∪ norandom —— **不再看 exclude:unkillable**
            # （后者语义是「从该保护里排除」，主 Boss 条目自带，旧实现据此误标了 174 个模型）
            "unkillable": int(mm in unk_models or b["tags"].get("norandom", 0) > 0),
            "size": sizes[0] if sizes else "",
            "arena": arenas[0] if arenas else "",
            "perceptive": percep,
            "extra_names": "、".join(sorted(b["extra"])[:3]),
        })
    return rows, by_id


def main():
    for p in (REF, MODELNAME):
        if not os.path.isfile(p):
            print("参考数据缺失，无法生成（不去猜）：%s" % p)
            return 2
    entries = parse_ref()
    unk_models, info = resolve_unkillable(entries)
    rows, by_id = build(entries, unk_models)
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
    print("条目 %d ｜ 模型 %d ｜ 带 multi 的模型 %d ｜ unkillable 模型 %d"
          % (len(entries), len(rows), n_multi, n_unk))
    print("  口径：Groups.unkillable 显示名 %s → 模型 %s"
          % (info["group_names"], info["group_models"]))
    if info["norandom"]:
        print("  另并入 norandom 模型（明确不参与随机）：%s" % info["norandom"])
    if info["unmatched"]:
        print("  !! 这些显示名在 ModelName.txt 里查不到（如实报，不静默当空）：%s" % info["unmatched"])
    print("  unkillable 模型：%s"
          % sorted(r["model"] for r in rows if r["unkillable"]))
    print("  Tags 里的 exclude:unkillable 只保留原始标签，不再驱动 unkillable")
    print("→", OUT)
    print("→", IDMAP)
    import collections as C
    print("档位分布（模型数）:", dict(C.Counter(r["ref_class_top"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
