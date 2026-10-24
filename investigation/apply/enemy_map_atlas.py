# -*- coding: utf-8 -*-
"""读法魂自己的 634 张地图 → 产出三张表（只读）

产物（都在 investigation/ 下）：
1. `map_enemies.csv`  每张地图上的每个敌人：map, entity_id, npc_id, think_id, chara_id, model, x, y, z
2. `boss_rows.csv`    **有血条 Boss** 对应的 NpcParam 行：map, entity_id, boss_name, npc_id, model, in_regulation
3. `model_types.csv`  模型 → 用它的行数 / 敌型画像（同模型归一类，这是"敌型"的硬依据）

校验（必须打印）：
* 解析成功的地图数 / 敌人 part 总数
* `npc_id` 能在**法魂自己的** regulation 里找到的比例（目标 ≥ 90%）
* 血条名单（EMEVD）里的实体有多少能在法魂地图里找到（这是"精确 Boss 池"的关键）
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER          # noqa
import msb_read as M                   # noqa

def mapdir():
    """地图目录 —— 用到时才解析（import 时不要碰路径：打包版隔离自检没有法魂包）"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(ER._mod_reg()))),
                        "mod", "map", "MapStudio")
HB_CSV = os.path.join(HERE, "..", "boss_healthbar.csv")
OUT_ENEMIES = os.path.join(HERE, "..", "map_enemies.csv")
OUT_BOSS = os.path.join(HERE, "..", "boss_rows.csv")
OUT_TYPES = os.path.join(HERE, "..", "model_types.csv")


def main():
    plain = ER.load_plain()
    units = ER.load_units(plain)                      # 法魂自己的 NpcParam 行
    names = ER.load_name_table()
    etypes = {}
    try:
        import enemy_types as ET
        etypes = ET.enemy_type_of
    except Exception:
        pass
    _mapdir = mapdir()
    print(f"法魂 NpcParam 行：{len(units)}｜地图目录：{_mapdir}")

    maps = sorted(f for f in os.listdir(_mapdir) if f.endswith(".msb.dcx"))
    print(f"地图文件：{len(maps)} 张")

    rows, ok_npc, bad_npc, models = [], 0, [], {}
    failed = []
    for i, fn in enumerate(maps):
        try:
            d = M.read_msb(os.path.join(_mapdir, fn))
        except Exception as e:
            failed.append((fn, f"{type(e).__name__}: {e}"))
            continue
        for e in d.get("enemies", []):
            nid = int(e.get("npc_id") or 0)
            hit = nid in units
            if hit:
                ok_npc += 1
            elif len(bad_npc) < 12:
                bad_npc.append((fn, e.get("entity_id"), nid))
            rows.append({"map": fn[:-8], "entity_id": e.get("entity_id"), "npc_id": nid,
                         "think_id": e.get("think_id"), "chara_id": e.get("chara_id"),
                         "model": e.get("model", ""), "x": e.get("x"), "y": e.get("y"),
                         "z": e.get("z")})
            models.setdefault(e.get("model", ""), set()).add(nid)
        if (i + 1) % 100 == 0:
            print(f"   …{i+1}/{len(maps)}")
    tot = len(rows)
    print(f"\n=== 1) 地图扫描 ===")
    print(f"  成功 {len(maps)-len(failed)} 张｜失败 {len(failed)} 张")
    for fn, err in failed[:5]:
        print(f"    ✗ {fn}: {err}")
    print(f"  敌人 part 总数 {tot}")
    print(f"  npc_id 命中法魂 NpcParam：{ok_npc}/{tot} = {ok_npc/max(1,tot)*100:.1f}%")
    for fn, ent, nid in bad_npc[:6]:
        print(f"    未命中样例：{fn} 实体{ent} → npc_id {nid}")

    with open(OUT_ENEMIES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  → {os.path.abspath(OUT_ENEMIES)}")

    # ── 2) 血条 Boss 对上地图实体 ──
    hb = []
    if os.path.isfile(HB_CSV):
        with open(HB_CSV, encoding="utf-8-sig", newline="") as f:
            hb = [r for r in csv.DictReader(f) if (r.get("entity") or "").isdigit()]
    by_ent = {}
    for r in rows:
        by_ent.setdefault(int(r["entity_id"]), []).append(r)
    boss_rows, miss = [], []
    for r in hb:
        ent = int(r["entity"])
        for e in by_ent.get(ent, []):
            nid = int(e["npc_id"])
            boss_rows.append({"map": e["map"], "entity_id": ent, "boss_name": r.get("name", ""),
                              "name_id": r.get("name_id", ""), "npc_id": nid,
                              "model": e["model"], "in_regulation": nid in units,
                              "row_name": units[nid].name if nid in units else ""})
        if ent not in by_ent:
            miss.append((r.get("map"), ent, r.get("name", "")))
    print(f"\n=== 2) 血条 Boss → regulation 行 ===")
    print(f"  血条名单 {len(hb)} 条｜能在地图里找到实体的 {len(hb)-len(miss)} 条｜映射到行 {len(boss_rows)} 条")
    uniq_rows = sorted({b['npc_id'] for b in boss_rows if b['in_regulation']})
    print(f"  **唯一 Boss 行（去重）：{len(uniq_rows)}**｜不在 regulation 里的 {sum(1 for b in boss_rows if not b['in_regulation'])}")
    for m in miss[:6]:
        print(f"    地图里没这个实体：{m}")
    with open(OUT_BOSS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["map", "entity_id", "boss_name", "name_id",
                                          "npc_id", "model", "in_regulation", "row_name"])
        w.writeheader()
        w.writerows(boss_rows)
    print(f"  → {os.path.abspath(OUT_BOSS)}")

    # ── 3) 模型 → 敌型画像 ──
    trows = []
    for model, npcids in sorted(models.items(), key=lambda x: -len(x[1])):
        sample = [units[i] for i in list(npcids)[:3] if i in units]
        t = ""
        for u in sample:
            if etypes and u.name:
                t = etypes(u.name)
                if t and "其它" not in t:
                    break
        hp = [units[i].hp for i in npcids if i in units]
        trows.append({"model": model, "npc_rows": len(npcids),
                      "sample_row": sorted(npcids)[0] if npcids else "",
                      "sample_name": (units[sorted(npcids)[0]].name if npcids and sorted(npcids)[0] in units else ""),
                      "enemy_type_hint": t,
                      "hp_median": sorted(hp)[len(hp) // 2] if hp else ""})
    with open(OUT_TYPES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trows[0]))
        w.writeheader()
        w.writerows(trows)
    print(f"\n=== 3) 模型 → 敌型 ===")
    print(f"  唯一模型 {len(trows)} 个｜→ {os.path.abspath(OUT_TYPES)}")
    print("  最大的 8 个模型：")
    for t in trows[:8]:
        print(f"    {t['model']:<10} 行 {t['npc_rows']:>4}｜{t['sample_name'] or '（无名）'}｜{t['enemy_type_hint'] or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
