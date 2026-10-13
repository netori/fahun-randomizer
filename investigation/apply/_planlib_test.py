#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案库自测：把每个操作都真跑一遍，并故意放坏文件看会不会拖垮整库"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, "investigation/apply")
import planlib as pl

OK = FAIL = 0


def ck(cond, what, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"    ✓ {what}")
    else:
        FAIL += 1
        print(f"    ✗ {what} {extra}")


def main():
    ws = tempfile.mkdtemp(prefix="_planlib_")
    os.makedirs(os.path.join(ws, "investigation", "apply"), exist_ok=True)

    rows = []
    for i in range(12):
        rows.append({"pool": "p", "role": "r", "unit": f"u{i}", "part": "", "old": f"weapon:{100+i}",
                     "old_cat": "weapon", "new": f"weapon:{200+i}", "new_cat": "weapon",
                     "source_table": "ItemLotParam_map", "row_id": str(700000 + i), "slot": "1",
                     "row_name": f"箱{i}", "engine_version": "1.1", "algorithm_mode": "guide",
                     "unchanged_reason": "", "preconditions": "old=weapon"})

    print("  ═══ ① 保存 ═══")
    m = pl.save_plan(rows, "第一次测试", cfg={"shops": False, "coherence": 0.8}, seed=20261012,
                     note="拿来试的", tags=["测试", "种子2026"], ws=ws)
    ck(m["rows"] == 12 and m["changed"] == 12, "保存 12 行 / 12 行有改动")
    ck(bool(m["fingerprint"]) and len(m["fingerprint"]) == 64, "记下了 64 位指纹")
    ck(os.path.isfile(os.path.join(ws, "plans", m["id"] + ".json")), "文件已落地")

    print("  ═══ ② 列表 / 读取 ═══")
    lst = pl.list_plans(ws=ws)
    ck(len(lst) == 1 and lst[0]["name"] == "第一次测试", "列了出来", lst)
    doc = pl.get_plan(m["id"], ws=ws)
    ck(len(doc["rows"]) == 12 and doc["seed"] == 20261012, "读回内容完整")
    ck(doc["cfg"]["coherence"] == 0.8, "配置也存下来了")

    print("  ═══ ③ 重命名 / 收藏 / 备注 / 标签 ═══")
    pl.rename_plan(m["id"], "改过名的方案", ws=ws)
    pl.set_meta(m["id"], star=True, note="这是收藏的", tags=["主力"], ws=ws)
    d = pl.get_plan(m["id"], ws=ws)
    ck(d["name"] == "改过名的方案", "名字改了")
    ck(d["id"] == m["id"], "**id 没变**（换名不会生成新文件）")
    ck(d["star"] and d["note"] == "这是收藏的" and d["tags"] == ["主力"], "收藏/备注/标签都写进去了")
    ck(pl.list_plans(ws=ws)[0]["star"] is True, "列表里能看到收藏")

    print("  ═══ ④ 复制 ═══")
    m2 = pl.duplicate_plan(m["id"], ws=ws)
    ck(m2["id"] != m["id"] and "副本" in m2["name"], "复制出独立的一份")
    ck(len(pl.list_plans(ws=ws)) == 2, "现在有两份")

    print("  ═══ ⑤ 导出 / 导入 ═══")
    exp = os.path.join(ws, "导出.json")
    pl.export_plan(m["id"], exp, ws=ws)
    ck(os.path.getsize(exp) > 100, "导出成功")
    m3 = pl.import_plan(exp, ws=ws, new_name="从文件导入的")
    ck(len(pl.list_plans(ws=ws)) == 3 and m3["name"] == "从文件导入的", "导入成功且是独立一份")

    print("  ═══ ⑥ 导出成写入链认识的 CSV ═══")
    csvp = os.path.join(ws, "plan.csv")
    pl.write_csv(m["id"], csvp, ws=ws)
    import csv as _csv
    got = list(_csv.DictReader(open(csvp, encoding="utf-8-sig")))
    ck(len(got) == 12, "CSV 12 行")
    ck(list(got[0].keys()) == pl.PLAN_FIELDS, "字段顺序与写入链一致（16 列）", list(got[0].keys())[:3])

    print("  ═══ ⑦ 坏文件不影响整库 ═══")
    bad = os.path.join(ws, "plans", "坏掉的.json")
    open(bad, "w", encoding="utf-8").write("{这不是 JSON")
    lst = pl.list_plans(ws=ws)
    ck(len(lst) == 4, "坏文件被列出来（不是让整库报错）", len(lst))
    ck(any(x.get("broken") for x in lst), "并且标了 broken")
    ck(any(not x.get("broken") for x in lst), "好的方案照常可用")
    try:
        pl.get_plan("坏掉的", ws=ws)
        ck(False, "读坏文件应当报错")
    except Exception:
        ck(True, "读坏文件会报错（不是静默返回空）")
    os.remove(bad)

    print("  ═══ ⑧ 删除 → 回收站 ═══")
    before = len(pl.list_plans(ws=ws))
    pl.delete_plan(m["id"], ws=ws)
    ck(len(pl.list_plans(ws=ws)) == before - 1, "列表少了一份")
    ck(len(os.listdir(os.path.join(ws, "plans", ".trash"))) >= 1, "**回收站里有一份**（手滑能找回）")

    print("  ═══ ⑨ id 安全 ═══")
    try:
        pl.get_plan("../../etc/passwd", ws=ws)
        ck(False, "非法 id 应被拒")
    except Exception:
        ck(True, "非法 id（含路径穿越）被拒")
    m4 = pl.save_plan(rows, "带 空格/斜杠\\的名字:测试*", ws=ws)
    ck(os.path.isfile(os.path.join(ws, "plans", m4["id"] + ".json")), "怪名字也能安全落盘")
    ck(m4["name"] == "带 空格/斜杠\\的名字:测试*", "但显示名保持原样")

    print("  ═══ ⑩ 指纹稳定性 ═══")
    f1 = pl.fingerprint(rows)
    f2 = pl.fingerprint(list(reversed(rows)))          # 行序换了
    ck(f1 == f2, "行序变化不影响指纹（避免假不一致）")
    rows2 = [dict(r) for r in rows]
    rows2[3]["new"] = "weapon:99999"
    ck(pl.fingerprint(rows2) != f1, "内容变了指纹就变")
    same, a, b = pl.verify_plan_rows(m2["id"], rows, ws=ws)
    ck(same, "方案与当前行一致时返回 True")

    print("  ═══ ⑪ 原子写（不留半截文件）═══")
    d = os.path.join(ws, "plans")
    ck(not [f for f in os.listdir(d) if f.endswith(".tmp")], "没有残留 .tmp")

    shutil.rmtree(ws, ignore_errors=True)
    print(f"\n  ══ 结果：{OK} 通过 / {FAIL} 失败 ══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
