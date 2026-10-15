# -*- coding: utf-8 -*-
"""敌人随机 · 配置矩阵模拟 + 与物品随机的兼容性验证（只写临时副本，不动真 MOD）

跑法：
    python enemy_config_matrix.py            # 全跑（约几分钟）
    python enemy_config_matrix.py --quick    # 只跑 2 个种子

它做四件事：
 ① 每种配置：生成计划 → 生成侧自检（池内/体型/双射）→ 打印"会改什么"
 ② 每种配置：应用到**临时 regulation 副本** → 写后回读 → 种类守恒
 ③ 确定性：同种子两次结果一致；换种子结果不同
 ④ **兼容性**：先应用一份"物品侧改动"，再应用敌人计划，检查
    (a) 物品侧的字节没被动过  (b) 物品侧的写前复核仍然通过
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import erio                     # noqa
import native_apply as na       # noqa
import param_patch as pp        # noqa
import enemy_randomizer as er   # noqa

REG = er._mod_reg()            # 复用引擎里的权威路径解析（别自己拼层级，容易差一层）
MOD = os.path.dirname(os.path.dirname(REG))

CONFIGS = [
    ("全随机（默认）",            {"enemy_rate": 1.0, "enemy_pools": er.CLASS_ORDER, "enemy_source": "all"}),
    ("只换 Boss",                 {"enemy_rate": 1.0, "enemy_pools": ["boss"], "enemy_source": "all"}),
    ("只换精英",                  {"enemy_rate": 1.0, "enemy_pools": ["elite"], "enemy_source": "all"}),
    ("只换普通敌人",              {"enemy_rate": 1.0, "enemy_pools": ["normal"], "enemy_source": "all"}),
    ("精英+Boss",                 {"enemy_rate": 1.0, "enemy_pools": ["elite", "boss"], "enemy_source": "all"}),
    ("全随机 · 五成",             {"enemy_rate": 0.5, "enemy_pools": er.CLASS_ORDER, "enemy_source": "all"}),
    ("全随机 · 三成",             {"enemy_rate": 0.3, "enemy_pools": er.CLASS_ORDER, "enemy_source": "all"}),
    ("只随机法魂敌人",            {"enemy_rate": 1.0, "enemy_pools": er.CLASS_ORDER, "enemy_source": "new"}),
]
SEEDS = [20261010, 20261015, 42]


def load_plain(path):
    return bytes(erio.dcx_decompress(erio.regulation_decrypt(path)))


def item_bytes_signature(plain):
    """物品侧两张表的字节指纹（用来证明敌人写入没碰它们）"""
    import hashlib
    h = hashlib.sha256()
    for t, probe in (("ItemLotParam_map", na.PROBE["ItemLotParam_map"]),
                     ("ItemLotParam_enemy", na.PROBE["ItemLotParam_enemy"]),
                     ("ShopLineupParam", na.PROBE["ShopLineupParam"])):
        base = na.file_start(plain, t)
        rows = pp.find_row_table(plain, probe)
        if not rows:
            continue
        lo = min(rows.values()) + base
        hi = max(rows.values()) + base + 0x200
        h.update(bytes(plain[lo:hi]))
    return h.hexdigest()[:16]


def main(argv):
    quick = "--quick" in argv
    seeds = SEEDS[:2] if quick else SEEDS
    print(f"=== 读 regulation：{REG}")
    plain0 = load_plain(REG)
    units0 = er.load_units(plain0)
    er.classify(units0)
    import collections
    cls_cnt = collections.Counter(u.cls for u in units0.values())
    print(f"    敌人行 {len(units0)}｜{ {er.CLASS_ZH[k]: v for k, v in cls_cnt.items()} }")
    sig_items = item_bytes_signature(plain0)
    print(f"    物品侧两张表指纹（原始）：{sig_items}")

    results = []
    tmpdir = tempfile.mkdtemp(prefix="enemy_matrix_")
    for name, base_cfg in CONFIGS:
        for seed in seeds:
            cfg = dict(base_cfg, seed=seed)
            t0 = time.time()
            plan, warn = er.make_plan(units0, cfg)
            issues = er.verify_plan(units0, plan, cfg)
            plan2, _ = er.make_plan(units0, cfg)
            det = (plan == plan2)
            row = {"配置": name, "种子": seed, "改行数": len(plan),
                   "自检问题": len(issues), "同种子可复现": det,
                   "按类别": er.summarize(units0, plan), "警告": warn,
                   "耗时秒": round(time.time() - t0, 1)}
            results.append(row)
            print(f"  · {name:<16} seed={seed:<9} 改 {len(plan):>5} 行"
                  f" | 问题 {len(issues)} | 可复现 {det}"
                  + (f" | 警告 {len(warn)}" if warn else ""))

    # ── 写盘 + 回读 + 兼容性（每种配置只跑一个种子，省时间）──
    print("\n=== 应用测试（临时副本）===")
    apply_rows = []
    for name, base_cfg in CONFIGS:
        seed = seeds[0]
        cfg = dict(base_cfg, seed=seed)
        plan, _ = er.make_plan(units0, cfg)
        tgt = os.path.join(tmpdir, f"reg_{len(apply_rows)}.bin")
        shutil.copy2(REG, tgt)
        pcsv = os.path.join(tmpdir, f"enemy_{len(apply_rows)}.csv")
        er.write_plan(plan, units0, pcsv)
        if plan:
            er.apply_plan(er.read_plan(pcsv), tgt, quiet=True)
        p1 = load_plain(tgt)
        u1 = er.load_units(p1)
        # 写后回读：每行现在的血量 == 源行原始血量
        ok = sum(1 for t, s in plan.items() if u1[t].hp == units0[s].hp)
        cons = sorted(u.hp for u in units0.values()) == sorted(u.hp for u in u1.values())
        # 兼容性：物品侧字节没被动 & 写前复核仍可用
        sig_after = item_bytes_signature(p1)
        item_untouched = (sig_after == sig_items)
        # 拿一条真实的物品行做个合成计划，验证写前复核仍能通过
        pre_ok = None
        try:
            rows = pp.find_row_table(p1, na.PROBE["ItemLotParam_map"])
            rid = sorted(rows)[0]
            base = na.file_start(p1, "ItemLotParam_map")
            off = pp.offset_of("ItemLotParam_map", rows, rid, "lotItemId", 1)
            cur = pp.read_u32(p1, (off or 0) + base) if off else None
            synth = os.path.join(tmpdir, f"item_{len(apply_rows)}.csv")
            with open(synth, "w", encoding="utf-8", newline="\n") as f:
                f.write("source_table,row_id,slot,old,new,old_cat,new_cat\n")
                f.write(f"ItemLotParam_map,{rid},1,material:{cur},material:{cur},,\n")
            na.check_preconditions(synth, tgt, quiet=True)
            pre_ok = True
        except Exception as e:
            pre_ok = f"{type(e).__name__}: {e}"
        apply_rows.append({"配置": name, "置换行": len(plan), "写后一致": ok,
                           "种类守恒": cons, "物品侧字节未动": item_untouched,
                           "物品写前复核": pre_ok})
        print(f"  · {name:<16} 置换 {len(plan):>5}｜写后一致 {ok}/{len(plan)}"
              f"｜守恒 {cons}｜物品侧未动 {item_untouched}｜写前复核 {pre_ok}")

    # 换种子必须不同
    p_a, _ = er.make_plan(units0, dict(CONFIGS[0][1], seed=1))
    p_b, _ = er.make_plan(units0, dict(CONFIGS[0][1], seed=2))
    print(f"\n换种子结果不同：{p_a != p_b}")

    out = os.path.join(HERE, "..", "enemy_matrix_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"plan": results, "apply": apply_rows,
                   "换种子结果不同": p_a != p_b,
                   "敌人行数": len(units0),
                   "类别分布": {er.CLASS_ZH[k]: v for k, v in cls_cnt.items()}},
                  f, ensure_ascii=False, indent=1)
    print(f"\n结果已写：{os.path.abspath(out)}｜临时目录：{tmpdir}")
    bad = [r for r in results if r["自检问题"]] + \
          [r for r in apply_rows if not r["种类守恒"] or r["物品侧字节未动"] is False]
    print(f"MATRIX {'PASS' if not bad else 'FAIL'}（{len(results)} 组计划 / {len(apply_rows)} 组应用）")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
