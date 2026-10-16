# -*- coding: utf-8 -*-
"""用参考实现自带的敌人名单（Base/enemy.txt，23174 条）校准我们的模型分类。

那份名单每条是：ID / Map / Name(含模型号 cXXXX_YYYY) / Class / Tags / ExtraName / ...
—— Class 是它人工维护的（Basic/Boss/...），Tags 里还有 "Night"/"DLC" 这类。
我们自己的分类是靠"血量/血条/名字关键词"，两套可以互相印证。

产出：
  investigation/model_class_ref.csv    模型 → 参考实现的 Class/Tags + 我们自己的 cls + 是否一致
  investigation/enemy_ref_overview.md  报告：两边分类的一致率、不一致的清单、能补上的模型
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
OUT = os.path.join(DATA, "model_class_ref.csv")
MD = os.path.join(DATA, "enemy_ref_overview.md")


def parse_ref(path=REF):
    """→ {模型: {class: 次数}} 与 {模型: {字段: {值}}}"""
    classes = collections.defaultdict(collections.Counter)
    meta = collections.defaultdict(lambda: collections.defaultdict(set))
    cur, n = {}, 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if s.startswith("- ID:"):
                if cur:
                    _add(classes, meta, cur)
                    n += 1
                cur = {}
            elif s.startswith("  ") and ":" in s:
                k, v = s.strip().split(":", 1)
                cur.setdefault(k, v.strip())
    if cur:
        _add(classes, meta, cur)
        n += 1
    return classes, meta, n


def _add(classes, meta, e):
    m = re.match(r"(c[0-9]{3,4})_", e.get("Name", "") or "")
    if not m:
        return
    mm = m.group(1)
    if e.get("Class"):
        classes[mm][e["Class"]] += 1
    for k in ("Tags", "ExtraName", "Outfit", "MusicFlag", "BuddyGroup", "Important"):
        if e.get(k):
            meta[mm][k].add(e[k])


def main():
    classes, meta, n = parse_ref()
    print("参考名单条目 %d ｜ 覆盖模型 %d" % (n, len(classes)))

    import enemy_randomizer as ER
    units = ER.load_units(ER.load_plain())
    ER.classify(units, names=ER.load_name_table(), healthbar_ids=ER.load_healthbar_nameids())
    # 行→模型在 row_models.csv 里（Unit 上不带模型号）
    r2m = {}
    with open(os.path.join(DATA, "row_models.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("model") and str(r.get("npc_id", "")).isdigit():
                r2m[int(r["npc_id"])] = r["model"]
    by_model = collections.defaultdict(collections.Counter)
    for rid, u in units.items():
        m = r2m.get(rid)
        if m:
            by_model[m][u.cls] += 1
    # 模型名的来源：我们的 row_models 给出了行→模型
    ours_models = set(by_model) | set(classes)
    print("我们有数据的模型 %d ｜ 参考实现有 %d" % (len(by_model), len(classes)))

    rows = []
    both = agree = 0
    for m in sorted(ours_models):
        ref_c = classes.get(m)
        our = by_model.get(m)
        ref_txt = "/".join("%s×%d" % (k, v) for k, v in (ref_c or {}).items())
        our_txt = "/".join("%s×%d" % (k, v) for k, v in (our or {}).items())
        # 一致性：参考的 Basic 应对应我们的 normal/elite，Boss 对应 boss
        ref_is_boss = bool(ref_c) and any(("Boss" in k) for k in ref_c)
        our_is_boss = bool(our) and our.most_common(1)[0][0] == "boss"
        flag = ""
        if ref_c and our:
            both += 1
            if ref_is_boss == our_is_boss:
                agree += 1
            else:
                flag = "不一致"
        rows.append({"model": m, "ref_class": ref_txt, "ref_tags": ";".join(
            x for v in (meta.get(m) or {}).values() for x in sorted(v))[:80],
            "our_cls": our_txt, "一致": flag,
            "last_placements": ""})
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("→", OUT)
    print("两边都有的模型 %d ｜ Boss 判定一致 %d（%.1f%%）" % (
        both, agree, 100.0 * agree / both if both else 0))

    with open(MD, "w", encoding="utf-8") as f:
        f.write("# 与参考实现敌人名单的对照\n\n")
        f.write("来源：`%s`（%d 条，覆盖 %d 个模型，人工维护）\n\n" % (os.path.basename(REF), n, len(classes)))
        f.write("两边都有的模型 **%d**，其中 Boss 判定一致 **%d（%.1f%%）**\n\n" % (
            both, agree, 100.0 * agree / both if both else 0))
        bad = [r for r in rows if r["一致"] == "不一致"]
        f.write("不一致 %d 个（前 40）：\n\n| 模型 | 参考 | 我们 | Tags |\n|---|---|---|---|\n" % len(bad))
        for r in bad[:40]:
            f.write("| %s | %s | %s | %s |\n" % (r["model"], r["ref_class"], r["our_cls"], r["ref_tags"]))
        only_ref = [r for r in rows if r["ref_class"] and not r["our_cls"]]
        only_us = [r for r in rows if r["our_cls"] and not r["ref_class"]]
        f.write("\n只有参考实现有：%d 个；只有我们有：%d 个\n" % (len(only_ref), len(only_us)))
    print("→", MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
