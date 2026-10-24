# -*- coding: utf-8 -*-
"""手动部署「敌人随机」到方案层（引擎直跑；**不写 mod 本体**）。

2026-10-17 审计后的口径（P0-2 / P0-3，方案 A）：
  * 以前这里用 `apply_plan(source=REG, out_path=REG)` **直接改 mod\\regulation.bin**，
    删掉 Plan= 也还原不回去（本体与原始备份 4660 行 NpcParam 不同）。
    现在所有写入只落到「临时副本 → 方案层」，mod 本体一个字节都不写。
  * 外观（visual）开启且 MSB 真产出地图 → 敌人身份只由 MSB 负责（写 npc/model/think/chara），
    regulation 保持原始（不做整行置换，否则是双重置换 = 模型/数值 65% 错位）。
  * 外观关闭/失败 → 降级为「只换数值」：整行置换但保留模型绑定字段（keep_model_rows 按行保留）。

用法：
    python investigation\\apply\\manual_deploy.py            # 产层 + 挂载（不动本体）
    python investigation\\apply\\manual_deploy.py --restore  # 把 mod 本体还原成原始（先备份当前）
"""
import argparse
import csv
import io
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enemy_randomizer as er                                          # noqa: E402
import enemy_swapper as ES                                             # noqa: E402
import plan_layer as PL                                                # noqa: E402

MOD = r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"
REG = os.path.join(MOD, "mod", "regulation.bin")
MAPS = os.path.join(MOD, "mod", "map", "MapStudio")
SEED = 20261010


def _cfg():
    """本次手动部署的敌人设置（与界面默认同口径：三类全随、外观开、方案乙开、不碰打不死的）"""
    return {"on": True, "pools": ["boss", "elite", "normal"],
            "rates": {"boss": 1.0, "elite": 1.0, "normal": 1.0},
            "rate": 1.0, "source": "all", "visual": True, "emevd": True,
            "allow_unkillable": False, "exclude_npc": True,
            "use_arena": True, "seed": SEED}


def _restore(log):
    """把 mod 本体还原成原始（先备份当前那份 —— 用户现在的文件不能丢）"""
    orig = PL.find_pristine_reg()
    if not orig:
        raise RuntimeError("找不到原始 regulation 备份（investigation/apply/backup/"
                           "regulation.bin.orig_*）")
    ts = time.strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(HERE, "backup", "restore_" + ts)
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(REG, os.path.join(bdir, "regulation.bin.before"))
    shutil.copy2(orig, REG)
    log("已还原 mod 本体：%s → %s" % (os.path.basename(orig), REG))
    log("还原前的本体已备份到：%s" % bdir)
    return bdir


def main(argv=None):
    ap = argparse.ArgumentParser(description="敌人随机 → 方案层（不写 mod 本体）")
    ap.add_argument("--restore", action="store_true",
                    help="只把 mod\\regulation.bin 还原成原始备份（先备份当前）")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)                               # noqa: E731
    if a.restore:
        _restore(log)
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    log("=== 手动部署（引擎直跑，只写方案层）%s ===" % ts)
    cfg = _cfg()
    cfg["seed"] = a.seed

    # ① 备份本体（只是留凭据；本次不写它）
    bdir = os.path.join(HERE, "backup", "manual_" + ts)
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(REG, os.path.join(bdir, "regulation.bin.before"))
    log("① 本体当前状态已备份：%s（本次不写本体）" % bdir)

    # ② 以**原始 regulation** 为底生成计划（敌人层的基准永远是原始，不叠加上一次随机）
    orig = PL.find_pristine_reg()
    if not orig:
        raise RuntimeError("找不到原始 regulation 备份（investigation/apply/backup/regulation.bin.orig_*）")
    layer_reg = os.path.join(bdir, "regulation.layer.bin")
    shutil.copy2(orig, layer_reg)
    log("② 底层：%s" % os.path.basename(orig))

    u = er.load_units(er.load_plain(layer_reg))
    er.classify(u, names=er.load_name_table(), healthbar_ids=er.load_healthbar_nameids())
    plan, warn = er.make_plan(u, {"seed": cfg["seed"], "enemy_rate": 1.0,
                                  "allow_unkillable": False, "exclude_npc": True,
                                  "use_arena": True})
    for w in warn:
        log("   警告：" + str(w))
    log("   计划：%d 行" % len(plan))

    # ③ 真换外观（只写到 out/ 临时目录；成功与否决定用哪条路径）
    odir = os.path.join(HERE, "out", "msb_" + ts)
    sres = ES.plan_swaps(dict(plan), map_dir=MAPS, out_dir=odir,
                         log=lambda *a: None)
    visual_ok = bool(sres.get("ok")) and int(sres.get("maps_written") or 0) > 0
    maps = [d["map"] for d in (sres.get("files") or [])] if visual_ok else []
    log("③ 外观：改 %s/%s 张图、%s 个 part（跳过 %s，ok=%s）"
        % (sres.get("maps_changed"), sres.get("maps_total"),
           sres.get("parts_changed"), sres.get("parts_skipped"), sres.get("ok")))
    if sres.get("skip_reasons"):
        log("   跳过原因：" + "，".join("%s=%s" % kv for kv in sorted(sres["skip_reasons"].items())))
    if sres.get("errors"):
        log("   [X] 外观错误 %d 条（降级为只换数值）：%s"
            % (len(sres["errors"]), [e.get("map") for e in sres["errors"][:3]]))

    # ④ 依外观结果决定路径（方案 A / 降级路径）
    mode = "visual"
    rows = 0
    evd = {}
    if visual_ok:
        log("④ 方案 A：视觉成功 ⇒ NpcParam 不做整行置换（避免双重置换）")
        # 方案乙：血条名/BGM 跟随新 Boss（只写方案层里的 event/*.emevd.dcx）
        if cfg.get("emevd"):
            try:
                import enemy_emevd as EE
                ev_src = os.path.join(os.path.dirname(REG), "event")
                ev_out = os.path.join(HERE, "out", "evd_" + ts)
                changes = EE.collect_changes(maps, MAPS, odir)
                evd = EE.patch_layer_events(ev_src, ev_out, changes, log=log)
            except Exception as e:                                 # noqa: BLE001
                log("④b 方案乙（血条名/BGM）失败（外观不受影响）：%s" % e)
    else:
        mode = "regulation-fallback"
        log("④ 外观没有可靠产出 ⇒ 降级为「只换数值」（整行置换 + 保留模型绑定字段）")
        plan_csv = os.path.join(bdir, "enemy_plan.csv")
        er.write_plan(plan, u, plan_csv)
        # 降级路径：模型一个没换 ⇒ 每一行都退回安全模式；按行集合真的传进去（P0-5）
        res = er.apply_plan(er.read_plan(plan_csv), source=layer_reg, out_path=layer_reg,
                            verify=True, quiet=True, keep_model_rows=set(plan))
        rows = res["rows"]
        log("   整行置换 %d 行（%s）" % (rows, er.summarize(u, plan)))

    # ⑤ 方案层：原始 regulation（或降级版）+ 全部改过的地图 + 方案乙的事件脚本
    extra = [(os.path.join(odir, m), os.path.join("map", "MapStudio", m)) for m in maps]
    extra += list(evd.get("files") or [])
    lab = "手动_%s_%s" % (ts, "敌人+外观+血条名" if mode == "visual" else "敌人+数值")
    r = PL.export_layer(lab, extra_files=extra, log=lambda *a: None, reg_src=layer_reg)
    PL.make_launchers(r["dir"], r["label"], log=lambda *a: None)
    PL.write_info(r["dir"], {
        "seed": cfg["seed"],
        "模式": ("方案 A：外观由 MSB 负责，NpcParam 未置换" if mode == "visual"
               else "降级：只换数值（保留模型绑定字段）"),
        "enemy": "开（boss/elite/normal 100%）",
        "visual": "开" if mode == "visual" else "关/失败（降级）",
        "血条名/BGM（方案乙）": (
            "血条名 %d 处、BGM %d 处（事件 %d 张）"
            % (evd.get("name", 0), evd.get("bgm", 0), evd.get("maps", 0)))
            if evd else "关/失败",
        "改写行数": rows,
        "改过的地图": len(maps),
        "note": "引擎直跑的验证层；mod 本体未写入（P0-2）"}, log=lambda *a: None)
    log("⑤ 方案层：%s（%d 个文件，%.1f MB）"
        % (r["dir"], len(r["files"]), r["bytes"] / 1048576))

    # ⑥ 挂载（set_plan 会写 <层根>\mod —— P0-1）
    m = PL.set_plan(r["dir"])
    log("⑥ 已挂载：%s" % m["plan"])

    # ⑦ 名单 + 收据
    def show(rid):
        x = u.get(rid)
        if x is None:
            return "行%s" % rid
        return (getattr(x, "name", "") or getattr(x, "enemy_type", "")
                or getattr(x, "model", "") or ("行%s" % rid))
    rws = [(getattr(u.get(rid), "cls", "?"), rid, nid, show(rid), show(nid))
           for rid, nid in plan.items()]
    rws.sort(key=lambda x: ({"boss": 0, "elite": 1, "normal": 2}.get(x[0], 9), x[1]))
    csvp = os.path.join(bdir, "boss_swap_report.csv")
    with io.open(csvp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cls", "row_id", "new_row_id", "old", "new"])
        w.writerows(rws)
    bosses = [x for x in rws if x[0] == "boss"]
    log("⑦ Boss %d 行在计划里；名单：%s" % (len(bosses), csvp))
    for c, rid, nid, aa, bb in bosses[:12]:
        log("     %s  ⇒  %s" % (aa, bb))
    rec = {"ts": ts, "seed": cfg["seed"], "mode": mode, "rows": rows,
           "maps": len(maps), "layer": r["dir"], "backup": bdir,
           "visual": {"ok": bool(sres.get("ok")),
                      "maps_written": sres.get("maps_written"),
                      "parts_changed": sres.get("parts_changed"),
                      "parts_skipped": sres.get("parts_skipped"),
                      "skip_reasons": sres.get("skip_reasons") or {}},
           "emevd": {"name": evd.get("name", 0), "bgm": evd.get("bgm", 0),
                     "maps": evd.get("maps", 0),
                     "skipped": len(evd.get("skipped") or []),
                     "partial_bgm": len(evd.get("partial") or [])},
           "body_written": False}
    with io.open(os.path.join(bdir, "receipt.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    log("收据：%s" % os.path.join(bdir, "receipt.json"))
    log("注意：mod\\regulation.bin 本次没有被写（P0-2）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
