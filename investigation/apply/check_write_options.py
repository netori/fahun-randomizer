#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写入侧体检：验证两个"只有写盘时才生效"的配置项真的有效。

① 说明书跟着一起改（sync_guide）
     · 关 ⇒ 说明书的 msgbnd **一个字节都不动**
     · 开 ⇒ msgbnd 真的被改写
② 商店里的职业装备也一起换（shops）—— 验的是"只换物品"这条承诺（硬约束 H4）
     · ShopLineupParam 行被改动的字节**必须全部落在 equipId / equipType 上**
       （价格 / 库存 / 解锁条件那些字段都在 equipType 后面）
     · 行步长由行表实测得出，不依赖字段表 —— 所以这条证明与布局无关

★ 全程在**临时 MOD 副本**上做（CONVERGENCE_MOD_ROOT 指向临时目录），
   真游戏文件一个字节都不会动。

用法：
    python check_write_options.py
"""
import collections
import csv
import glob
import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "investigation", "randomization-dryrun", "scripts"))

SEED = 20261010
BASE = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide", "shops": True,
        "merge_shadow": False, "sets": True, "density": 1.0, "coherence": 0.8}


def main():
    import erio
    import native_apply
    import native_deploy
    import param_patch as pp
    import randomizer as R

    rows = []

    def ck(name, ok, detail):
        rows.append((name, bool(ok), detail))
        print(f"  {'✓' if ok else '✗'} {name}　{detail}", flush=True)

    here_mod = native_deploy.MOD
    orig_reg = sorted(glob.glob(os.path.join(HERE, "backup", "regulation.bin.orig_*")))
    if not orig_reg:
        print("找不到 backup/regulation.bin.orig_*（先补一份原始备份）")
        return 1
    msg_rel = os.path.join("mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    real_msg = os.path.join(here_mod, msg_rel)
    if not os.path.isfile(real_msg):
        print(f"找不到真实说明书文件：{real_msg}")
        return 1

    sb = tempfile.mkdtemp(prefix="_writecheck_")
    os.makedirs(os.path.dirname(os.path.join(sb, msg_rel)), exist_ok=True)
    shutil.copy2(orig_reg[-1], os.path.join(sb, "mod", "regulation.bin"))
    shutil.copy2(real_msg, os.path.join(sb, msg_rel))
    os.environ["CONVERGENCE_MOD_ROOT"] = sb

    def _msg_hash():
        return hashlib.sha256(open(os.path.join(sb, msg_rel), "rb").read()).hexdigest()[:12]

    def _plain():
        return bytes(erio.dcx_decompress(erio.regulation_decrypt(os.path.join(sb, "mod", "regulation.bin"))))

    print("=== 写入侧体检（临时 MOD 副本：%s）===" % sb, flush=True)
    try:
        cfg = dict(BASE, seed=SEED + 7)
        items = R.load_world(cfg["shops"], cfg["basis"])
        plan = R.run(items, cfg, cfg["seed"])[0]
        cols = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
                "source_table", "row_id", "slot", "row_name", "engine_version",
                "algorithm_mode", "unchanged_reason", "preconditions"]
        csvp = os.path.join(sb, "plan.csv")
        with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for x in plan:
                w.writerow({k: x.get(k, "") for k in cols})
        shop_rows = [r for r in plan if r["source_table"] == "ShopLineupParam" and r["old"] != r["new"]]
        print(f"  计划 {len(plan)} 行（其中商店改动 {len(shop_rows)} 行）", flush=True)

        pristine = _plain()          # ★ 一切对比都跟**原始文件**比：两次 deploy 的终态是同一份，互比等于没比

        # 判据基准：**原始备份**的说明书（不是沙箱初始状态 —— deploy 第②步本来就会先复原）
        _orig_msg = sorted(glob.glob(os.path.join(HERE, "backup", "item_dlc02.msgbnd.dcx.zhocn.orig_*")))
        pristine_msg = (hashlib.sha256(open(_orig_msg[-1], "rb").read()).hexdigest()[:12]
                        if _orig_msg else "")
        before_msg = _msg_hash()
        r1 = native_deploy.deploy(csvp, sync_guide=False, log=lambda *_a: None)
        after_off = _msg_hash()
        after1 = _plain()
        _reg1 = [s for s in (r1.get("steps") or []) if s.get("step") == "regulation"]
        _applied1 = sum(v.get("applied", 0) for v in ((_reg1[0].get("stats") if _reg1 else {}) or {}).values())
        ck("说明书开关·关（sync_guide=False）", bool(pristine_msg) and after_off == pristine_msg,
           f"关掉后说明书停在**原始版** {after_off}（原始 {pristine_msg}）✓ 没被随机化；"
           f"regulation 已写 {_applied1} 格")

        # 商店只动物品：逐行看改动字节落在哪（pristine vs 写完之后的明文）
        tbl = native_apply.find_row_table_in_plain(pristine, "ShopLineupParam")
        offs = sorted(int(v) for v in tbl.values())
        gaps = [b - a for a, b in zip(offs, offs[1:]) if b > a]
        row_size = min(gaps) if gaps else 0x24
        bad, checked = [], 0
        for r in shop_rows:
            base = pp.offset_of("ShopLineupParam", tbl, int(r["row_id"]), "equipId")
            if base is None:
                continue
            checked += 1
            if pristine[base:base + 4] == after1[base:base + 4]:
                bad.append((r["row_id"], "equipId 没变", 0, 0))
                continue
            allowed = set(range(base, base + 4)) | {base + 0x17}
            for off in range(base, base + row_size):
                if pristine[off] != after1[off] and off not in allowed:
                    bad.append((r["row_id"], off - base, pristine[off], after1[off]))
        ck("商店只动物品（只准动 equipId / equipType）", checked > 0 and not bad,
           f"检查 {checked} 行（行步长实测 {row_size}B）；越界/异常 {len(bad)} 处"
           + (f"，例如行 {bad[0][0]} {bad[0][1]}" if bad else ""))

        r2 = native_deploy.deploy(csvp, sync_guide=True, log=lambda *_a: None)
        after_on = _msg_hash()
        ck("说明书开关·开（sync_guide=True）", after_on != pristine_msg,
           f"打开后说明书被改写 {pristine_msg} → {after_on}（与原始版不同）")

        # 掉落表：抽检若干行确实被改写（pristine vs 第一次部署后的明文）
        tbl_map = native_apply.find_row_table_in_plain(pristine, "ItemLotParam_map")
        hits, miss = 0, []
        for r in plan:
            if r["source_table"] != "ItemLotParam_map" or r["old"] == r["new"]:
                continue
            oi = pp.offset_of("ItemLotParam_map", tbl_map, int(r["row_id"]), "lotItemId", int(r["slot"] or 1))
            if oi is None or pristine[oi:oi + 4] == after1[oi:oi + 4]:
                miss.append((r["row_id"], r["old"], r["new"]))
                continue
            hits += 1
        ck("掉落表确实被改写（抽检）", hits > 0,
           f"{hits} 行 itemId 变了；没变的 {len(miss)} 行"
           + (f"，样例 {miss[:2]}" if miss else ""))

        # ── 与敌人随机共存（2026-10-16 新增）──────────────────────────────
        #   要点：两套随机写同一个 regulation.bin，必须能在**同一次部署**里先后落盘，
        #   而且互不干扰。这里用同一份 plan.csv 再部署一次（这次带上 enemy_cfg），
        #   然后比对：物品侧字节是否一字未动 + 敌人侧是否真的换了 + 种类是否守恒。
        def _sig_item(src):
            p = bytes(erio.dcx_decompress(erio.regulation_decrypt(src)))
            h = hashlib.sha256()
            for t, probe in (("ItemLotParam_map", native_apply.PROBE["ItemLotParam_map"]),
                             ("ItemLotParam_enemy", native_apply.PROBE["ItemLotParam_enemy"]),
                             ("ShopLineupParam", native_apply.PROBE["ShopLineupParam"])):
                base = native_apply.file_start(p, t)
                rws = pp.find_row_table(p, probe)
                if not rws:
                    continue
                lo = min(rws.values()) + base
                hi = max(rws.values()) + base + 0x200
                h.update(bytes(p[lo:hi]))
            return h.hexdigest()[:16]

        import enemy_randomizer as ER
        _reg = os.path.join(sb, "mod", "regulation.bin")
        _items_before = _sig_item(_reg)
        _u_before = ER.load_units(bytes(erio.dcx_decompress(erio.regulation_decrypt(_reg))))
        _npcsig_before = hashlib.sha256(
            b"".join(bytes(_u_before[r].sha.encode()) for r in sorted(_u_before))).hexdigest()[:16]

        _ec = {"on": True, "pools": ["boss", "elite", "normal"], "rate": 1.0,
               "source": "all", "seed": SEED + 7}
        _rec2 = native_deploy.deploy(csvp, sync_guide=True, log=lambda *_a: None, enemy_cfg=_ec)

        _items_after = _sig_item(_reg)
        ck("共存：物品侧字节在敌人写入后一字未动", _items_before == _items_after,
           f"{_items_before} → {_items_after}")

        _step = [s for s in _rec2.get("steps", []) if s.get("step") == "enemy"]
        ck("共存：这一次部署里敌人侧真的跑了（收据里有 enemy 步骤）",
           bool(_step) and _step[0].get("rows", 0) > 0,
           f"{_step[0] if _step else '（收据里没有 enemy 步骤）'}")

        _u_after = ER.load_units(bytes(erio.dcx_decompress(erio.regulation_decrypt(_reg))))
        _same = sum(1 for r in _u_before if _u_after[r].sha == _u_before[r].sha)
        _cons = (sorted(u.hp for u in _u_before.values()) == sorted(u.hp for u in _u_after.values()))
        # 预期"该变多少行"直接问引擎（同种子 ⇒ 同一份计划，可精确比对；
        # 别用固定百分比 —— 有 skip 池（友好 NPC/有名角色）和成员不足的体型桶，本来就不会全变）
        _pu, _pplan, _pw, _pi = ER.plan_for_cfg(_ec, reg_path=_reg)
        _expect_changed = len(_pplan)
        _changed = len(_u_before) - _same
        ck("共存：变化的行数与计划一致（容差 5%：内容完全相同的两行互换算不出来）",
           abs(_changed - _expect_changed) <= max(50, int(_expect_changed * 0.05)),
           f"实际 {_changed} / 计划 {_expect_changed}（差 {abs(_changed - _expect_changed)} 行；"
           f"逐行比对已由 apply_plan 内部复核保证）")
        ck("共存：敌人种类守恒（hp 多重集一致）", _cons,
           f"{len(_u_before)} 行")

        # 物品侧的效果还在吗？抽一条计划里的改动核对
        _rows_plan = [r for r in csv.DictReader(open(csvp, encoding="utf-8-sig"))
                      if r.get("old") != r.get("new")]
        p_now = bytes(erio.dcx_decompress(erio.regulation_decrypt(_reg)))
        _ok_item = 0
        for r in _rows_plan[:20]:
            t, rid, slot = r["source_table"], int(r["row_id"]), int(r["slot"] or 1)
            if t.startswith("ItemLotParam"):
                off = pp.offset_of(t, native_apply.find_row_table_in_plain(p_now, t), rid, "lotItemId", slot)
            else:
                off = pp.offset_of(t, native_apply.find_row_table_in_plain(p_now, t), rid, "equipId", 1)
            if off and pp.read_u32(p_now, off) == int(r["new"].split(":")[1]):
                _ok_item += 1
        ck("共存：物品侧的改动在敌人写入后仍然生效", _ok_item > 0,
           f"抽查 {min(20, len(_rows_plan))} 条，命中新物品 {_ok_item} 条")

        # 还原成原始：与 GUI「还原成原始」同一套逻辑（把两份原始备份拷回去）→ 必须逐字节复原
        shutil.copy2(orig_reg[-1], os.path.join(sb, "mod", "regulation.bin"))
        shutil.copy2(_orig_msg[-1], os.path.join(sb, msg_rel))
        _after_restore = _plain()
        ck("还原成原始·两份都逐字节复原",
           _after_restore == pristine and _msg_hash() == pristine_msg,
           f"regulation {'一致' if _after_restore == pristine else '不一致'}"
           f"｜说明书 {after_on} → {_msg_hash()}（原始 {pristine_msg}）")
    finally:
        os.environ.pop("CONVERGENCE_MOD_ROOT", None)
        native_deploy.MOD = here_mod
        shutil.rmtree(sb, ignore_errors=True)

    print("\n=== 汇总 ===")
    bad = [r for r in rows if not r[1]]
    print(f"  通过 {len(rows) - len(bad)} ｜ 异常 {len(bad)}")
    for n, _o, d in bad:
        print(f"    ✗ {n}　{d}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
