# -*- coding: utf-8 -*-
"""敌人随机修复后的只读核对工具（2026-10-17 审计的 P0-3 / P0-5 / P0-6 验收）。

所有子命令都**不写 MOD 目录**：需要落盘的一律写到系统临时目录（tempfile），跑完即弃。

用法：
    python investigation\\apply\\check_enemy_fix.py p05-keep
    python investigation\\apply\\check_enemy_fix.py p03-consistency --layer "<方案层目录>" [--limit 40]
    python investigation\\apply\\check_enemy_fix.py p06-coverage [--maps 60] [--own-reg <regulation>]
    python investigation\\apply\\check_enemy_fix.py p01-plan

判据：
  * p05-keep：降级模式下「模型没换的行」必须保留全部模型绑定字段（含位域），
    没保留的字段必须确实等于源行（整行置换的语义）。
  * p03-consistency：方案 A 的层里，被改 part 的新 npc 行内容必须与**原始 regulation**同 id 行一致，
    且 MSB 写的模型名与该行画像一致 —— 即"模型/HP/卢恩/名字都来自同一行"。
  * p06-coverage：60 图抽样 target-row-unknown 应为 0（修复前 2110 次）。
"""
import argparse
import csv
import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER       # noqa: E402
import enemy_swapper as ES          # noqa: E402
import msb_read as M                # noqa: E402
import plan_layer as PL             # noqa: E402

MOD = ER._mod_reg() and os.path.dirname(os.path.dirname(ER._mod_reg()))
MAPS = os.path.join(MOD, "mod", "map", "MapStudio")
ORIG = PL.find_pristine_reg()


def _norm_orig():
    if not ORIG:
        raise SystemExit("找不到原始 regulation 备份（investigation/apply/backup/regulation.bin.orig_*）")
    return ORIG


def _load_plain_units(reg_path):
    plain = ER.load_plain(reg_path)
    units = ER.load_units(plain)
    ER.classify(units, names=ER.load_name_table(),
                healthbar_ids=ER.load_healthbar_nameids())
    return plain, units


def _field_reader(plain, off, fields, bits):
    fmap = {f[0]: (f[2], f[1], f[3]) for f in fields}

    def read(name):
        if name in bits:
            o, b = bits[name]
            return (plain[off + o] >> b) & 1
        if name not in fmap:
            return None
        o, _t, sz = fmap[name]
        return bytes(plain[off + o:off + o + sz])

    return read


def p05_keep(args):
    """降级路径（只换数值）字段保留验收：keep_model_rows=set(plan) 时整行替换 + 模型字段保留。"""
    src = _norm_orig()
    plain0, units = _load_plain_units(src)
    plan, warn = ER.make_plan(units, {"seed": 20261015, "enemy_rate": 1.0,
                                      "allow_unkillable": False, "exclude_npc": True,
                                      "use_arena": True})
    tmpd = tempfile.mkdtemp(prefix="_p05_")
    try:
        reg = os.path.join(tmpd, "regulation.bin")
        shutil.copy2(src, reg)
        csvp = os.path.join(tmpd, "plan.csv")
        ER.write_plan(plan, units, csvp)
        # 模拟降级路径：所有行都按"模型没换"处理（按行集合真的传进去）
        res = ER.apply_plan(ER.read_plan(csvp), source=reg, out_path=reg, verify=True,
                            quiet=True, keep_model_rows=set(plan))
        plain1, _u1 = _load_plain_units(reg)
        fields, row_size = ER.paramdef_fields("NpcParam")
        bits = ER.bit_field_map(fields)
        bad = 0
        checked = 0
        import native_apply as na
        off0 = na.file_start(plain0, "NpcParam")
        off1 = na.file_start(plain1, "NpcParam")
        # 直接用 units 里记下的偏移（Unit.off 是明文绝对偏移）
        for rid, nid in plan.items():
            u = units[rid]
            r0 = _field_reader(plain0, u.off, fields, bits)
            r1 = _field_reader(plain1, u.off, fields, bits)
            src_u = units[nid]
            rs = _field_reader(plain0, src_u.off, fields, bits)
            for k in ER.SAFE_KEEP_FIELDS:
                want = r0(k)
                got = r1(k)
                if want is None:              # 本版本没有这个字段（Paramdex 版本差异）→ 跳过
                    continue
                checked += 1
                if got != want:
                    bad += 1
                    if bad <= 8:
                        print("   [X] 行%s 字段 %s 没保留：原=%r 现=%r"
                              % (rid, k, want, got))
        # 反向：非保留字段应等于源行（抽样确认整行置换确实发生；hp/getSoul 都不在 SAFE 集里）
        sample = ("hp", "getSoul")
        same = 0
        for rid, nid in list(plan.items())[:200]:
            u, su = units[rid], units[nid]
            ra = _field_reader(plain1, u.off, fields, bits)
            rb = _field_reader(plain0, su.off, fields, bits)
            if all(ra(k) == rb(k) for k in sample):
                same += 1
        print("[p05-keep] 行 %d｜保留字段检查 %d 次｜失败 %d ｜整行置换抽样 %d/200"
              % (len(plan), checked, bad, same))
        # 再测一次 keep_model_fields=True（native_deploy 降级路径用的口径）
        reg2 = os.path.join(tmpd, "regulation2.bin")
        shutil.copy2(src, reg2)
        ER.apply_plan(ER.read_plan(csvp), source=reg2, out_path=reg2, verify=True,
                      quiet=True, keep_model_fields=True)
        plain2, _ = _load_plain_units(reg2)
        bad2 = 0
        for rid in plan:
            u = units[rid]
            r0 = _field_reader(plain0, u.off, fields, bits)
            r2 = _field_reader(plain2, u.off, fields, bits)
            for k in ER.SAFE_KEEP_FIELDS:
                want = r0(k)
                if want is None:
                    continue
                if r2(k) != want:
                    bad2 += 1
        print("[p05-keep] keep_model_fields=True：失败 %d" % bad2)
        ok = (bad == 0 and bad2 == 0)
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _layer_units(layer):
    reg = os.path.join(layer, "mod", "regulation.bin")
    if not os.path.isfile(reg):
        raise SystemExit("方案层里没有 mod\\regulation.bin：%s" % layer)
    plain = ER.load_plain(reg)
    units = ER.load_units(plain)
    ER.classify(units, names=ER.load_name_table(),
                healthbar_ids=ER.load_healthbar_nameids())
    return plain, units


def _load_row_model_sets():
    """{row_id: set(该行画像里出现过的模型)} —— row_models.csv 的 model + all_models。

    为什么要用集合：swapper 在首选模型不在图里时允许用该行的**候选模型**（all_models），
    只拿 model 列比会把这种"合法替代模型"误报成不一致。
    """
    p = os.path.join(HERE, "..", "row_models.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = str(r.get("npc_id") or "").strip()
                if not rid.isdigit() or int(rid) <= 0:
                    continue
                s = set(x for x in (r.get("all_models") or "").split("|") if x)
                if r.get("model"):
                    s.add(r["model"])
                if s:
                    out[int(rid)] = s
    except Exception:
        pass
    return out


def p03_consistency(args):
    """方案 A 一致性：层里被改 part 的新 npc 行 == 原始 regulation 同行；模型与行画像一致。"""
    layer = os.path.abspath(args.layer)
    src = _norm_orig()
    plain_o, units_o = _load_plain_units(src)
    plain_l, units_l = _layer_units(layer)
    maps_dir = os.path.join(layer, "mod", "map", "MapStudio")
    if not os.path.isdir(maps_dir):
        raise SystemExit("方案层里没有 mod\\map\\MapStudio：%s" % layer)
    row_models = _load_row_model_sets()
    files = sorted(os.listdir(maps_dir))
    if args.limit:
        files = files[:args.limit]
    boss_checked = boss_bad = other_checked = other_bad = 0
    doubl = 0
    model_bad = 0
    for fn in files:
        lp = os.path.join(maps_dir, fn)
        sp = os.path.join(MAPS, fn)
        if not os.path.isfile(sp):
            continue
        try:
            a = M.read_msb(sp).get("enemies") or []
            b = M.read_msb(lp).get("enemies") or []
        except Exception as e:                                # noqa: BLE001
            print("   [跳过] %s 读失败：%s" % (fn, e))
            continue
        if len(a) != len(b):
            print("   [X] %s part 数异常 %d != %d" % (fn, len(a), len(b)))
            continue
        for x, y in zip(a, b):
            if (x.get("model") == y.get("model") and x.get("npc_id") == y.get("npc_id")
                    and x.get("think_id") == y.get("think_id")):
                continue                                    # 没被改的 part
            B = int(y.get("npc_id") or -1)
            uo, ul = units_o.get(B), units_l.get(B)
            if uo is None or ul is None:
                continue
            cls = uo.cls
            checked_here = (cls == "boss")
            if checked_here:
                boss_checked += 1
            else:
                other_checked += 1
            bad = False
            # ① 方案 A：层里行 B 必须与原始行 B 完全一致（NpcParam 没被置换）
            if units_l[B].sha != units_o[B].sha:
                bad = True
                doubl += 1
            # ② 模型名必须在该行的画像集合里（首选或候选模型都行）
            mset = row_models.get(B)
            if mset and y.get("model") and y["model"] not in mset:
                bad = True
                model_bad += 1
            # ③ hp/getSoul/nameId 必须来自行 B 本身
            if (ul.hp != uo.hp) or (ul.soul != uo.soul) or (ul.name_id != uo.name_id):
                bad = True
            if bad:
                if checked_here:
                    boss_bad += 1
                else:
                    other_bad += 1
                if (boss_bad + other_bad) <= 10:
                    print("   [X] %s part=%s 新行=%s 模型=%s 画像=%s 层行sha=%s 原行sha=%s hp(层/原)=%s/%s"
                          % (fn, y.get("name"), B, y.get("model"),
                             sorted(mset or []), ul.sha, uo.sha, ul.hp, uo.hp))
    total = boss_checked + other_checked
    bad = boss_bad + other_bad
    print("[p03-consistency] 层=%s｜检查 %d 个被改 part（Boss %d）｜不一致 %d（Boss %d）"
          "｜双重置换残留 %d｜模型画像不符 %d"
          % (layer, total, boss_checked, bad, boss_bad, doubl, model_bad))
    ok = (total > 0 and bad == 0)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def p06_coverage(args):
    """60 图抽样：target-row-unknown 应接近 0。"""
    src = _norm_orig()
    units, plan, warn, issues = ER.plan_for_cfg(
        {"on": True, "pools": ["boss", "elite", "normal"], "rate": 1.0,
         "visual": True, "allow_unkillable": False}, reg_path=src)
    files = sorted(f for f in os.listdir(MAPS) if f.endswith(".msb.dcx"))
    step = max(1, len(files) // args.maps)
    only = files[::step][:args.maps]
    tmpd = tempfile.mkdtemp(prefix="_p06_")
    try:
        out = os.path.join(tmpd, "msb")
        rep = ES.plan_swaps(dict(plan), map_dir=MAPS, out_dir=out, only_maps=only, log=print)
        unk = rep["skip_reasons"].get(ES.SKIP_TARGET_ROW_UNKNOWN, 0)
        print("[p06-coverage] 图 %d｜plan %d 行｜part 改 %d｜跳过 %d（%s）｜target-row-unknown=%d｜替代 %d"
              % (len(only), len(plan), rep["parts_changed"], rep["parts_skipped"],
                 rep["skip_reasons"], unk, rep["parts_substituted"]))
        print("[p06-coverage] 按类别：%s" % rep["parts_by_cls"])
        ok = unk == 0 and rep["parts_changed"] > 0
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def p01_plan(args):
    st = PL.plan_status()
    print("[p01-plan] Plan 行：%r" % st.get("line"))
    print("[p01-plan] 数据根：%r ｜ valid=%s ｜ %s"
          % (st.get("target"), st.get("valid"), st.get("reason")))
    if st.get("valid"):
        print("PASS（ini 指向数据根）")
        return 0
    print("未挂载：下一次启动是纯本体（真实验收要进游戏看 YAFSML.log 里有没有 "
          "方案\\<层>\\mod\\map\\MapStudio 的 file override）")
    return 0


def _find_all(raw, pat):
    out, i = [], 0
    while True:
        j = raw.find(pat, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def p02_emevd(args):
    """方案乙验收：层里 event/*.emevd.dcx 的参数槽是否真的换成了新 Boss 的名字/BGM。

    做法：从层地图 vs MOD 原图推出「哪个实体换了哪一行」，再用 enemy_emevd 的定位数据
    在**原事件脚本**里找到旧参数、在**层事件脚本**里核对新参数 —— 只读，不写文件。
    """
    layer = os.path.abspath(args.layer)
    src = _norm_orig()
    maps_dir = os.path.join(layer, "mod", "map", "MapStudio")
    ev_dir = os.path.join(layer, "mod", "event")
    if not os.path.isdir(ev_dir):
        print("PASS（这一层没有 event/ —— 方案乙没开，不算失败）")
        return 0
    import enemy_emevd as EE
    mdata, bgm_npc = EE.build_map_data(EE.event_dir(), log=None)
    name_ids = EE.load_boss_name_ids()
    src_maps = os.path.join(MAPS)
    files = sorted(os.listdir(ev_dir))
    name_ok = name_bad = bgm_ok = bgm_bad = 0
    maps_checked = 0
    skipped_reasons = []
    for fn in files:
        mid = fn.split(".")[0]
        lp = os.path.join(ev_dir, fn)
        op = os.path.join(EE.event_dir(), fn)
        lay = os.path.join(maps_dir, mid + ".msb.dcx")
        sr = os.path.join(src_maps, mid + ".msb.dcx")
        if not (os.path.isfile(lay) and os.path.isfile(sr) and os.path.isfile(op)):
            continue
        changes = EE.collect_part_swaps(sr, lay)
        if not changes:
            skipped_reasons.append("%s（层里有事件但地图没差异）" % mid)
            continue
        try:
            lraw, _ = M.dcx_payload(open(lp, "rb").read())
        except Exception as e:                                 # noqa: BLE001
            name_bad += 1
            print("   [X] %s 读失败：%s" % (fn, e))
            continue
        maps_checked += 1
        d = mdata.get(mid) or {}
        for (ent, old_npc, new_npc) in changes:
            new_name = name_ids.get(new_npc)
            if new_name:
                for (slot, old_name) in (d.get("literal") or {}).get(ent, []):
                    if new_name == old_name:
                        name_ok += 1          # 新旧名字一样：本来就对，不算失败
                        continue
                    pat_old = struct.pack("<4I", 1, ent, slot, old_name)
                    pat_new = struct.pack("<4I", 1, ent, slot, new_name)
                    if pat_new in lraw and pat_old not in lraw:
                        name_ok += 1
                    elif pat_old in lraw or pat_new not in lraw:
                        name_bad += 1
                        if name_bad <= 6:
                            print("   [X] %s 实体%s 字面量血条名没换" % (fn, ent))
                for (eid, ni, old_name) in (d.get("templated") or {}).get(ent, []):
                    if new_name == old_name:
                        name_ok += 1
                        continue
                    found_old = found_new = False
                    for pos in _find_all(lraw, struct.pack("<2I", eid, ent)):
                        off = pos + 4 * (1 + ni)
                        if off + 4 > len(lraw):
                            continue
                        v = struct.unpack_from("<I", lraw, off)[0]
                        if v == old_name:
                            found_old = True
                        elif v == new_name:
                            found_new = True
                    if found_new and not found_old:
                        name_ok += 1
                    else:
                        name_bad += 1
                        if name_bad <= 6:
                            print("   [X] %s 实体%s 模板血条名没换（eid=%s ni=%s）"
                                  % (fn, ent, eid, ni))
            bgm_hit = (d.get("bgm") or {}).get(ent)
            new_bgm = bgm_npc.get(new_npc)
            if bgm_hit and new_bgm:
                eid, flag, old_bgm = bgm_hit
                if new_bgm == old_bgm:
                    bgm_ok += 1
                    continue
                p_old = struct.pack("<3I", eid, flag, old_bgm)
                p_new = struct.pack("<3I", eid, flag, new_bgm)
                if p_new in lraw and p_old not in lraw:
                    bgm_ok += 1
                elif p_old in lraw or p_new not in lraw:
                    bgm_bad += 1
                    if bgm_bad <= 6:
                        print("   [X] %s 实体%s BGM 参数没换" % (fn, ent))
    print("[p02-emevd] 层=%s｜事件脚本 %d 个｜核对地图 %d 张｜血条名换到 %d 处（失败 %d）"
          "｜BGM 换到 %d 处（失败 %d）"
          % (layer, len(files), maps_checked, name_ok, name_bad, bgm_ok, bgm_bad))
    if skipped_reasons:
        print("  （跳过：%s）" % "、".join(skipped_reasons[:5]))
    ok = (name_ok > 0 and name_bad == 0 and bgm_bad == 0)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="敌人随机修复后的只读核对")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("p05-keep", help="降级路径字段保留验收")
    s1.set_defaults(func=p05_keep)
    s2 = sub.add_parser("p03-consistency", help="方案 A 一致性验收")
    s2.add_argument("--layer", required=True)
    s2.add_argument("--limit", type=int, default=0)
    s2.set_defaults(func=p03_consistency)
    s3 = sub.add_parser("p06-coverage", help="60 图 target-row-unknown 验收")
    s3.add_argument("--maps", type=int, default=60)
    s3.set_defaults(func=p06_coverage)
    s4 = sub.add_parser("p01-plan", help="看当前 Plan= 是否指向数据根")
    s4.set_defaults(func=p01_plan)
    s5 = sub.add_parser("p02-emevd", help="方案乙：层里血条名/BGM 参数槽验收")
    s5.add_argument("--layer", required=True)
    s5.set_defaults(func=p02_emevd)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
