# apply_swaps.py — 把随机化置换表写进解包出来的 PARAM XML（真机写回用）
#
# WitchyBND 的 PARAM XML 形态：<row id="..." name="..." 字段="值" ... />
#   ItemLotParam_map / ItemLotParam_enemy : lotItemIdNN + lotItemCategoryNN（NN=01..08）
#   ShopLineupParam                        : equipId + equipType
# 纪律：
#   * 只改目标字段，其它一个字节不动（属性级替换）
#   * 写前校验"当前值 == 置换表里的原值"，不一致就跳过并记冲突（防表/文件错位）
#   * --dry-run 只报不改
import argparse, collections, csv, json, os, re, sys

CAT_OF_TYPE = {"0": "weapon", "1": "protector", "2": "accessory", "3": "goods", "4": "gem"}
TYPE_OF_CAT = {"weapon": "0", "protector": "1", "accessory": "2", "goods": "3", "gem": "4"}
LOTCAT_OF_CAT = {"goods": "1", "weapon": "2", "protector": "3", "accessory": "4", "gem": "5"}
TABLE_FILE = {"ItemLotParam_map": "ItemLotParam_map.param.xml",
              "ItemLotParam_enemy": "ItemLotParam_enemy.param.xml",
              "ShopLineupParam": "ShopLineupParam.param.xml"}


def load_plan(path):
    todo = collections.defaultdict(list)
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["old"] == r["new"]:
            continue
        if r["source_table"] in TABLE_FILE:
            todo[r["source_table"]].append(r)
    return todo


def row_span(text, rid):
    m = re.search(r'<row\b[^>]*\bid="%s"[^>]*?/>' % re.escape(rid), text)
    return (m.start(), m.end(), m.group(0)) if m else None


def patch_rows(text, rows):
    """返回 (新文本, 改动明细, 未定位行)"""
    detail, missing = [], []
    by_row = collections.defaultdict(list)
    for r in rows:
        by_row[r["row_id"]].append(r)
    for rid, rs in by_row.items():
        sp = row_span(text, rid)
        if not sp:
            missing.append(rid)
            continue
        start, end, tag = sp
        new_tag = tag
        for r in rs:
            old_cat, new_cat = r["old"].split(":")[0], r["new"].split(":")[0]
            new_id = r["new"].split(":")[1]
            if r["source_table"] == "ShopLineupParam":
                want = {"equipId": (new_id, r["old"].split(":")[1]),
                        "equipType": (TYPE_OF_CAT[new_cat], TYPE_OF_CAT[old_cat])}
            else:
                m = re.search(r"^(?:s)?(\d+)$", (r["slot"] or "").strip())
                if not m:
                    missing.append(f"{rid}:{r['slot']}（无法解析槽号）")
                    continue
                n = int(m.group(1))
                want = {f"lotItemId{n:02d}": (new_id, r["old"].split(":")[1]),
                        f"lotItemCategory{n:02d}": (LOTCAT_OF_CAT[new_cat], LOTCAT_OF_CAT[old_cat])}
            for fld, (newv, oldv) in want.items():
                fm = re.search(r'(\b%s=")(-?\d+)(")' % fld, new_tag)
                if not fm:
                    missing.append(f"{rid}:{fld}（该行没有这个字段）")
                    continue
                if fm.group(2) != str(oldv):
                    detail.append({"row": rid, "field": fld, "expected_old": oldv, "actual": fm.group(2),
                                   "action": "skip_conflict", "npc_name": ""})
                    continue
                if str(newv) != str(oldv):
                    new_tag = new_tag[:fm.start()] + f'{fm.group(1)}{newv}"' + new_tag[fm.end():]
                    detail.append({"row": rid, "field": fld, "old": oldv, "new": newv, "action": "set"})
        if new_tag != tag:
            text = text[:start] + new_tag + text[end:]
            # 行长度变化后后面的偏移失效，但每次重新 search 定位，故安全
    return text, detail, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="")
    a = ap.parse_args()
    todo = load_plan(a.plan)
    print(f"=== 写回 {os.path.basename(a.plan)} → {a.tree} {'(dry-run)' if a.dry_run else ''} ===")
    rep = {}
    for table, rows in sorted(todo.items()):
        xml = os.path.join(a.tree, TABLE_FILE[table])
        if not os.path.exists(xml):
            print(f"  ❌ 缺 {TABLE_FILE[table]}")
            continue
        src = open(xml, encoding="utf-8-sig").read()
        text, detail, missing = patch_rows(src, rows)
        sets = [d for d in detail if d["action"] == "set"]
        conf = [d for d in detail if d["action"] == "skip_conflict"]
        print(f"  {table:<22} 计划 {len(rows):>4} 格 | 已改字段 {len(sets):>4} | 未定位 {len(missing)} | 原值不符 {len(conf)}")
        for x in missing[:3]:
            print(f"      缺失: {x}")
        for x in conf[:3]:
            print(f"      冲突: {x}")
        if not a.dry_run and text != src:
            open(xml, "w", encoding="utf-8-sig").write(text)
        rep[table] = {"planned_cells": len(rows), "changed_fields": len(sets), "missing": missing,
                      "conflicts": conf, "changes": sets}
    if a.report:
        json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  回执 → {a.report}")
    return 0 if not any(v["conflicts"] for v in rep.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
