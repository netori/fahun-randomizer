# native_deploy.py — 原生部署器（零外部工具）：把某个随机计划的 regulation + 说明书一起落盘
#
# 顺序：
#   ① 备份 MOD 当前的 regulation.bin 与 item_dlc02.msgbnd.dcx
#   ② 把两者**复原成原始版**（保证每次都从干净状态出发，不叠加）
#   ③ 说明书：fix_guide 按该计划生成新的 GoodsCaption XML
#   ④ regulation：native_apply 把计划写进 params
#   ⑤ 说明书：native_guide 把新 XML 全文写进 msgbnd
#   ⑥ 回读校验 + 收据
import glob, json, os, shutil, subprocess, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
sys.path.insert(0, APPLY)
import erio, native_apply, native_guide, oodle, fix_guide   # noqa

import modpaths   # noqa: E402
# MOD 目录来源：统一问 modpaths（环境变量 → 起点/父目录/同级目录），不再按目录名猜
MOD = modpaths.find_mod_root(APPLY) or native_guide.MOD
WS = os.path.dirname(ROOT)
CAT = os.path.join(WS, "investigation", "randomization-catalog-review")
LOG = os.path.join(APPLY, "logs")


def workspace_of(start=None):
    """定位工作区（…\\随机mod）：从 exe 或本文件位置向上找带 investigation/apply 的目录"""
    d = start or os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(d, "investigation", "apply")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def relocate(ws=None):
    """把各模块的路径常量改到真实工作区（打包成 exe 后 __file__ 指向临时目录，必须重定位）"""
    ws = ws or workspace_of()
    if not ws:
        raise FileNotFoundError("找不到工作区（请把 exe 放在 随机mod 目录下运行）")
    apply_dir = os.path.join(ws, "investigation", "apply")
    root = ws
    targets = {
        "native_guide": {"APPLY": apply_dir, "MOD": MOD},
        "native_apply": {"APPLY": apply_dir, "ROOT": root, "MOD": MOD},
        "erio": {"APPLY": apply_dir},
        "fix_guide": {"APPLY": apply_dir, "ROOT": root,
                      "CAT": os.path.join(root, "investigation", "randomization-catalog"),
                      "WB": os.path.join(root, "investigation", "weapon-baseline")},
    }
    for name, consts in targets.items():
        m = sys.modules.get(name)
        if m:
            for k, v in consts.items():
                setattr(m, k, v)
    globals()["WS"] = ws
    return ws


def find_original(pattern):
    hits = sorted(glob.glob(os.path.join(APPLY, "backup", pattern)))
    return hits[0] if hits else None


def deploy(plan_csv, sync_guide=True, log=print, fingerprint=None, enemy_cfg=None,
           plan_label=None, plan_meta=None, enemy_merge=None, overlay=False, mount=True):
    """部署入口（带 **事务回滚**，P0-5）：出错时把 MOD 本体恢复成「部署前」的状态。

    为什么需要它：② 会先把本体复原成原始、④ 又写物品 —— 若 ④b/⑤/⑦ 中途抛异常，
    旧代码会留下「物品已随机 + 说明书旧/无层」的半套状态，且收据 ok 语义失真。
    这里在进入 _deploy_inner 之前先备份一份本体；任何异常都回滚到这份备份并写失败收据。

    enemy_merge（2026-10-22 一次写入）：
      {"plan_path": 敌人计划路径, "label": 层标签, "seed": ..., "options": ...}
      传了它 = 同一次调用里「先写物品（本体 + 说明书）→ 再从写好的本体构建敌人 v1 层 →
      挂载这个层」。不再单独产出物品层 —— 最终只有一个同时含物品与敌人的层，不会出现
      “后写的把先写的顶掉”。任何一步失败都回滚本体与 Plan=。

    overlay=True（2026-10-23「纯方案层」）：**法魂本体一个字节都不写**。
      ② 不再复原本体，而是把「原始 regulation + 原始说明书」复制到
      APPLY/work/overlay_<ts>/ 的工作副本；④⑤ 都写在这份副本上；⑦ 把副本
      整份打进方案层（regulation.bin + 说明书 + 地图/事件）。
      于是「启动器挂层开局」与「法魂本体」彻底解耦：删掉 Plan= 就是纯法魂。
      代价：层里多一份说明书（约 0.4 MB）；本体不再随写入变化。

    mount=False（2026-10-23 方案库流程）：只把覆盖层生成出来，**不动 YAFSML.ini**。
      由方案库的启动器在开玩时挂载（gamelib.launch 会 set_plan + 换档），
      这样「生成」与「挂载/开局」彻底分开：生成阶段不打扰当前正在玩的那一档。
    """
    relocate()
    _env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        _mod = os.path.normpath(_env)
    else:
        _mod = globals().get("MOD", MOD)
    if not _mod or not os.path.isdir(os.path.join(_mod, "mod")):
        _mod = modpaths.require_mod_root(APPLY)      # 找不到时给出「怎么办」
    reg = os.path.join(_mod, "mod", "regulation.bin")
    msg = os.path.join(_mod, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    ts = time.strftime("%Y%m%d_%H%M%S")
    if overlay and not (plan_label or enemy_merge):
        raise ValueError("overlay=True 需要 plan_label 或 enemy_merge（否则产物没有地方放）")
    pre = os.path.join(APPLY, "backup", "deploy_pre_" + ts)
    if not overlay:
        os.makedirs(pre, exist_ok=True)
        for src, nm in ((reg, "regulation.bin"), (msg, "item_dlc02.msgbnd.dcx")):
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(pre, nm))
    _old_plan = None
    if enemy_merge or overlay:
        try:
            import plan_layer as _PL0
            _old_plan = _PL0.current_plan_line()
        except Exception:
            _old_plan = None
    try:
        rec = _deploy_inner(plan_csv, sync_guide=sync_guide, log=log, fingerprint=fingerprint,
                            enemy_cfg=enemy_cfg,
                            plan_label=None if enemy_merge else plan_label,
                            plan_meta=plan_meta, overlay=overlay, mount=mount)
        rec["pre_backup"] = pre
        if enemy_merge:
            _w = rec.get("work") or {}
            _merge_enemy_layer(rec, enemy_merge, _w.get("reg") or reg, log=log,
                               msg_src=(_w.get("msg") if overlay else None))
        return rec
    except Exception as e:                                             # noqa: BLE001
        _rolled = []
        for nm, dst in (("regulation.bin", reg), ("item_dlc02.msgbnd.dcx", msg)):
            src = os.path.join(pre, nm)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                _rolled.append(nm)
        log("[回滚] 写入失败：%s" % e)
        log("[回滚] 已把 MOD 本体恢复成部署前状态：%s"
            % ("、".join(_rolled) if _rolled else "（没有可回滚的文件）"))
        if enemy_merge:
            try:
                import plan_layer as _PL1
                if _old_plan:
                    _old_abs = _old_plan
                    if not os.path.isabs(_old_abs):
                        _old_abs = os.path.normpath(os.path.join(
                            os.path.dirname(_PL1.ini_path()), _old_abs))
                    _PL1.set_plan(_old_abs)
                    log("[回滚] 已恢复原来的挂载：%s" % _old_plan)
                else:
                    _PL1.clear_plan()
                    log("[回滚] 已恢复成不挂方案层（法魂本体）")
            except Exception as _pe:
                log("[回滚] 恢复挂载没成功：%s（手工在 YAFSML.ini 检查 Plan=）" % _pe)
        try:
            with open(os.path.join(LOG, "deploy_error_" + ts + ".json"), "w",
                      encoding="utf-8") as _f:
                json.dump({"ts": ts, "ok": False, "error": str(e),
                           "rolled_back": _rolled, "pre_backup": pre},
                          _f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        raise


def _merge_enemy_layer(rec, spec, reg, log=print, msg_src=None):
    """一次写入的后半段：从**已经写好物品的**基底构建敌人 v1 层，并挂载。

    reg 在旧模式下是本体（物品已写进去）；overlay 模式下是 work/overlay_<ts>/ 里的
    工作副本 —— 那种情况下 msg_src 也一起传进来，说明书跟着进层（本体一个字节都没动）。

    这是 2026-10-22 对「为什么不能一次写入两个随机」的回答：
    物品写的是 regulation 里的物品表 + 说明书，敌人 v1 写的是 regulation 的敌人表
    + 地图/事件；两者最终都要落进同一个 regulation.bin 与同一个方案层。
    所以顺序必须是「物品先写进本体 → 敌人读这份本体再建层 → 挂载这个层」——
    中间不导出物品层，也就没有“后写的把先写的顶掉”。
    """
    import enemy_write as EW
    import plan_layer as PL
    plan_path = spec.get("plan_path")
    if not plan_path:
        import enemy_plan as EP
        plan = EP.build_plan(EP.load_data(), spec.get("options") or {}, spec.get("seed") or 1)
        plan_path = os.path.join(workspace_of() or WS, "investigation", "enemy_plan.json")
        EP.dump_plan(plan, plan_path)
        log("[合并] 敌人计划已生成：%s" % plan_path)
    label = spec.get("label") or time.strftime("敌人v1_物品+敌人_%Y%m%d_%H%M%S")
    log("[合并] 物品已写好，开始从这份本体构建敌人 v1 层：%s" % label)
    man = EW.build(plan_path=plan_path, label=label,
                   out_root=spec.get("out_root"), base_reg=reg,
                   limit=spec.get("limit"),
                   plans_dir=spec.get("plans_dir"), log=log)
    layer_dir = os.path.join(spec.get("out_root") or PL.plans_root(), label)
    if msg_src and os.path.isfile(msg_src):
        _mt = os.path.join(layer_dir, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
        os.makedirs(os.path.dirname(_mt), exist_ok=True)
        shutil.copy2(msg_src, _mt)
        log("[合并] 说明书已放进层：%.2f MB" % (os.path.getsize(msg_src) / 1048576.0))
        # 把它也记进 enemy_manifest 的写集 —— 否则闸门（enemy_gate）会把这份说明书
        # 当成「层里多出来的陈旧残留」判 FAIL（2026-10-23 实测过，别删这段）。
        try:
            import hashlib as _hl
            _mp = os.path.join(layer_dir, "enemy_manifest.json")
            _man = json.load(open(_mp, encoding="utf-8"))
            _rel = "msg/zhocn/item_dlc02.msgbnd.dcx"
            _man["files"] = [x for x in (_man.get("files") or [])
                             if x.get("rel") != _rel]
            _man["files"].append({"rel": _rel, "bytes": os.path.getsize(_mt),
                                  "sha256": _hl.sha256(open(_mt, "rb").read()).hexdigest()})
            _man["bytes"] = sum(int(x.get("bytes") or 0) for x in _man["files"])
            with open(_mp, "w", encoding="utf-8") as _f:
                json.dump(_man, _f, ensure_ascii=False, indent=1)
            log("[合并] manifest 已记上说明书（闸门/复验会把它算进写集）")
        except Exception as _e:
            log("[合并] manifest 记说明书失败（闸门会把它报成多余文件）：%s" % _e)
    try:
        PL.make_launchers(layer_dir, label, log=log)
        PL.write_info(layer_dir, {"种子": spec.get("seed"),
                                  "随机项目": "物品 + 敌人 v1（一次写入）",
                                  "说明": "同一层里同时含物品随机与敌人随机"},
                      log=log)
    except Exception as _e:
        log("[合并] 层说明/启动器没写全：%s" % _e)
    if spec.get("mount", True):
        _m = PL.set_plan(layer_dir)
        log("[合并] 已挂载这个层（YAFSML.ini 的 Plan= 已更新）—— 关掉游戏重进就生效")
        rec["steps"].append({"step": "plan_mount", "ok": True, "plan": _m})
    rec["steps"].append({"step": "plan_layer", "ok": True, "dir": layer_dir,
                         "files": len(man.get("files") or []),
                         "bytes": man.get("bytes") or 0,
                         "mode": "item+enemy-v1"})
    rec["steps"].append({"step": "enemy_merge", "ok": True, "label": label,
                         "plan": plan_path,
                         "counts": man.get("counts") or {}})
    rec["enemy_merge"] = {"label": label, "dir": layer_dir,
                          "plan": plan_path,
                          "counts": man.get("counts") or {}}
    return rec


def _deploy_inner(plan_csv, sync_guide=True, log=print, fingerprint=None, enemy_cfg=None,
                  plan_label=None, plan_meta=None, overlay=False, mount=True):
    relocate()
    # ── 打包版：把「所有会写文件的路径」重定位到 exe 旁边那份工作区 ──
    # 这些目录原本按"代码所在位置"拼，打包后那指向临时解包目录，
    # 于是它会去解包目录里找备份、写日志，而真正的备份在 exe 旁边 ——
    # 表现就是「系统找不到指定的路径」。relocate() 只覆盖了一部分模块，这里补齐。
    _env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        globals()["MOD"] = os.path.normpath(_env)
    if not os.path.isdir(os.path.join(globals().get("MOD") or "", "mod")):
        globals()["MOD"] = modpaths.require_mod_root(APPLY)
    _ws = workspace_of()
    if _ws:
        _ad = os.path.join(_ws, "investigation", "apply")
        _mod = globals().get("MOD")
        _targets = {
            "native_deploy": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod, "WS": _ws,
                              "LOG": os.path.join(_ad, "logs"),
                              "CAT": os.path.join(_ws, "investigation", "randomization-catalog-review")},
            "native_guide": {"APPLY": _ad, "MOD": _mod},
            "native_apply": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod},
            "_guide_rebuild": {"APPLY": _ad},
            "_guide_fit": {"APPLY": _ad},
            "_guide_audit": {"APPLY": _ad},
            "fix_guide": {"APPLY": _ad, "ROOT": _ws, "MOD": _mod},
        }
        for _n, _c in _targets.items():
            _m = sys.modules.get(_n)
            if _m:
                for _k, _v in _c.items():
                    try:
                        setattr(_m, _k, _v)
                    except Exception:
                        pass
        globals()["WS"] = _ws
        for _d in ("backup", "logs", "out", "work/msg/zh"):
            os.makedirs(os.path.join(_ad, _d), exist_ok=True)
        # Oodle 的 DLL 随游戏走：告诉 oodle 去工作区（= exe 旁边）找 oodle/ 或 game/
        os.environ["CONVERGENCE_RAND_ROOT"] = _ws
        os.environ.setdefault("CONVERGENCE_GAME_DIR", os.path.join(_ws, "game"))
        if callable(log):
            log(f"[定位] 工作区 {_ws} ｜ MOD {_mod}")
    ts = time.strftime("%Y%m%d_%H%M%S")
    reg = os.path.join(MOD, "mod", "regulation.bin")
    msg = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
    rec = {"ts": ts, "plan": os.path.basename(plan_csv), "steps": [],
           "ts_epoch": time.time(), "fingerprint": fingerprint}
    # ── overlay（纯方案层）：所有写入落在工作副本上，法魂本体一个字节都不碰 ──
    _wreg, _wmsg = reg, msg
    if overlay:
        _wdir = os.path.join(APPLY, "work", "overlay_" + ts)
        os.makedirs(_wdir, exist_ok=True)
        _wreg = os.path.join(_wdir, "regulation.bin")
        _wmsg = os.path.join(_wdir, "item_dlc02.msgbnd.dcx")
    rec["work"] = {"overlay": bool(overlay), "reg": _wreg, "msg": _wmsg}

    # ① 备份当前（overlay 不改本体，跳过）
    bdir = os.path.join(APPLY, "backup", f"deploy_{ts}")
    if not overlay:
        os.makedirs(bdir, exist_ok=True)
        for src, nm in ((reg, "regulation.bin"), (msg, "item_dlc02.msgbnd.dcx")):
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(bdir, nm))
        rec["backup_dir"] = bdir
        log(f"[①] 已备份当前文件到 backup/deploy_{ts}/")
    else:
        log("[①] 纯方案层模式：不备份、不改本体（产物写进 work/overlay_%s/）" % ts)

    # ② 复原原始
    o_reg, o_msg = find_original("regulation.bin.orig_*"), find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*")
    if not (o_reg and o_msg):
        raise FileNotFoundError("找不到原始备份（backup/regulation.bin.orig_* 与 item_dlc02.msgbnd.dcx.zhocn.orig_*）")
    if overlay:
        shutil.copy2(o_reg, _wreg)
        shutil.copy2(o_msg, _wmsg)
        log(f"[②] 基底：{os.path.basename(o_reg)} / {os.path.basename(o_msg)} → 工作副本（本体未动）")
    else:
        shutil.copy2(o_reg, reg)
        shutil.copy2(o_msg, msg)
        log(f"[②] 已复原原始：{os.path.basename(o_reg)} / {os.path.basename(o_msg)}")

    # ③ 说明书 XML
    guide_xml = os.path.join(APPLY, "work", "msg", "zh", f"GoodsCaption.deploy_{ts}.fmg.xml")
    if sync_guide:
        # 进程内调用（打包成 exe 后也能用，不依赖子进程）
        import fix_guide
        _argv = sys.argv
        try:
            sys.argv = ["fix_guide", "--plan", plan_csv, "--out", guide_xml,
                        "--report", os.path.join(LOG, f"guide_{ts}.json")]
            fix_guide.main()
        except Exception as e:
            log(f"[③] 说明书同步异常：{e}")
        finally:
            sys.argv = _argv
        # ③a 按正确方向重写地点：物品名不动，只换它现在所在的地点
        try:
            import _guide_rebuild, importlib.util
            _spec = importlib.util.spec_from_file_location(
                "_rand_engine", os.path.join(os.path.dirname(APPLY), "randomization-dryrun", "scripts", "randomizer.py"))
            _r = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_r)
            _items = _r.load_world(False, "guide")

            def _name_of(k):
                return (_items.get(k) or {}).get("name", "")

            _base = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
            _rb = guide_xml.replace(".fmg.xml", ".rebuilt.fmg.xml")
            if os.path.exists(_base):
                st_rb = _guide_rebuild.rewrite(guide_xml, _base, plan_csv, _rb, _name_of)
                if os.path.exists(_rb):
                    guide_xml = _rb
                log(f"[③a] 说明书地点重写：换上 {st_rb['换地点']} 处 / 地点未变 {st_rb['地点未变']} / 未动 {st_rb['未动/保持']}")
        except Exception as _e:
            log(f"[③a] 地点重写跳过：{_e}")
        # ③b 长度适配：新文本不得超过原版长度（否则游戏会把尾部截掉）
        try:
            import _guide_fit
            _base_xml = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
            _fitted = guide_xml.replace(".fmg.xml", ".fitted.fmg.xml")
            if os.path.exists(_base_xml) and os.path.exists(guide_xml):
                st = _guide_fit.rewrite(guide_xml, _base_xml, _fitted)
                if os.path.exists(_fitted):
                    guide_xml = _fitted
                log(f"[③b] 说明书长度适配：补齐 {st['padded']} 条 / 缩写 {st['shortened']} 条"
                    + (f" / 仍超长 {st['still_long']} 条" if st['still_long'] else ""))
        except Exception as _e:
            log(f"[③b] 长度适配跳过：{_e}")
        # ③c 说明书自动审计：标签/长度/物品名/空地点/串页/行数/幂等 + 落盘核对
        try:
            import _guide_audit
            _base_xml = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
            _fails = _guide_audit.audit(_base_xml, guide_xml, guide_xml, quiet=True)
            if _fails:
                log(f"[③c] [X] 说明书审计发现 {len(_fails)} 处问题：{_fails[:3]}")
                rec.setdefault("guide_audit", _fails)
            else:
                log("[③c] 说明书审计通过 [OK]（标签/长度/物品名/空地点/串页/行数 全部符合原版）")
        except Exception as _e:
            log(f"[③c] 审计跳过：{_e}")
        log(f"[③] 说明书同步：{'成功' if os.path.exists(guide_xml) else '失败'}")
        rec["steps"].append({"step": "guide_xml", "ok": os.path.exists(guide_xml), "out": guide_xml})
        if not os.path.exists(guide_xml):
            raise RuntimeError("说明书同步失败，已中止（未改 MOD）")

    # ④ regulation（物品随机；**敌人不再写本体**，见 ④a）
    rep = native_apply.apply_native(plan_csv, source=_wreg, out_path=_wreg, verify=True, quiet=True)
    log(f"[④] regulation：写入 {sum(v['applied'] for v in rep['stats'].values())} 格，跳过 {len(rep['skipped'])}；回读校验通过")

    # ④b 先做：真换外观（模型 + AI 的 think/chara 一起换，只写进方案层，不动 mod 本体）
    #     为什么放在 ④a **之前**：④a 要按"外观这步到底可靠地产出了没有"决定走视觉模式还是降级。
    #     2026-10-17 审计修（P0-3/P0-5）：ok 必须按**实际结果**记；`rep["ok"]` 为真且
    #     maps_written > 0 才算视觉成功，否则整批地图丢弃、走「只换数值」降级（绝不半套）。
    _msb_files = []
    _evd_files = []
    _plan_for_visual = None
    _units_for_visual = None
    _warn_for_visual = []
    _visual_ok = False
    if enemy_cfg and enemy_cfg.get("on") and enemy_cfg.get("visual"):
        try:
            import enemy_randomizer as _er0
            import enemy_swapper as ES
            _u0, _plan_for_visual, _w0, _i0 = _er0.plan_for_cfg(enemy_cfg)
            _units_for_visual, _warn_for_visual = _u0, list(_w0 or [])
            for _w in _warn_for_visual:
                log("[④b] 警告：%s" % _w)
            if _i0:
                log("[④b] [X] 计划自检问题：%s" % _i0[:3])
            # reg = <mod根>/mod/regulation.bin ⇒ 地图就在同级的 map/MapStudio
            # （2026-10-17 修：以前多 dirname 了一层，指到 <mod根>/map/MapStudio ⇒ 静默不跑）
            _mdir = os.path.join(os.path.dirname(os.path.abspath(reg)), "map", "MapStudio")
            if not os.path.isdir(_mdir):
                _alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(reg))),
                                    "map", "MapStudio")
                if os.path.isdir(_alt):
                    _mdir = _alt
            _odir = os.path.join(LOG, "msb_" + ts)
            _sres = ES.plan_swaps(dict(_plan_for_visual), map_dir=_mdir, out_dir=_odir, log=log)
            _maps = [d["map"] if isinstance(d, dict) else str(d) for d in (_sres.get("files") or [])]
            _visual_ok = bool(_sres.get("ok")) and int(_sres.get("maps_written") or 0) > 0
            if _visual_ok:
                _msb_files = [(os.path.join(_odir, m), os.path.join("map", "MapStudio", m))
                              for m in _maps]
                # 方案乙：血条名/BGM 跟随新 Boss（只改 EMEVD 的 int 参数槽，不动事件流）
                if enemy_cfg.get("emevd"):
                    try:
                        import enemy_emevd as EE
                        _ev_src = os.path.join(os.path.dirname(os.path.abspath(reg)), "event")
                        _ev_out = os.path.join(LOG, "evd_" + ts)
                        _changes = EE.collect_changes(_maps, _mdir, _odir)
                        _evd = EE.patch_layer_events(_ev_src, _ev_out, _changes, log=log)
                        _evd_files = list(_evd.get("files") or [])
                        rec["steps"].append({"step": "enemy_emevd", "ok": True,
                                             "name": _evd.get("name"), "bgm": _evd.get("bgm"),
                                             "maps": _evd.get("maps"),
                                             "skipped": len(_evd.get("skipped") or []),
                                             "partial_bgm": len(_evd.get("partial") or [])})
                    except Exception as _e:                    # noqa: BLE001
                        log("[④b] 方案乙（血条名/BGM）失败（外观不受影响）：%s" % _e)
                        rec["steps"].append({"step": "enemy_emevd", "ok": False,
                                             "error": str(_e)})
            else:
                # 半套比没有更糟：不完整/有错的外观产物一律不进层，改走「只换数值」降级
                log("[④b] 外观没有可靠产出（ok=%s, maps_written=%s, errors=%s）→ 丢弃本次地图，走降级"
                    % (_sres.get("ok"), _sres.get("maps_written"), len(_sres.get("errors") or [])))
            log("[④b] 真换外观：%s/%s 张图、%s 个敌人（跳过 %s）｜ok=%s"
                % (_sres.get("maps_changed"), _sres.get("maps_total"),
                   _sres.get("parts_changed"), _sres.get("parts_skipped"), _sres.get("ok")))
            if _sres.get("skip_reasons"):
                log("[④b] 跳过原因：%s" % ", ".join("%s=%d" % kv
                                                 for kv in sorted(_sres["skip_reasons"].items())))
            if _sres.get("errors"):
                log("[④b] [X] 外观错误 %d 条（前 3：%s）"
                    % (len(_sres["errors"]), [e.get("map") for e in _sres["errors"][:3]]))
            rec["steps"].append({"step": "enemy_visual", "ok": _visual_ok,
                                 "maps": _sres.get("maps_changed"),
                                 "maps_written": _sres.get("maps_written"),
                                 "parts": _sres.get("parts_changed"),
                                 "skipped": _sres.get("parts_skipped"),
                                 "skip_reasons": _sres.get("skip_reasons") or {},
                                 "errors": len(_sres.get("errors") or [])})
        except ImportError:
            log("[④b] 真换外观：引擎还没就绪（enemy_swapper.py 不在），这一次只换数值")
        except Exception as _e:                                       # noqa: BLE001
            log("[④b] 真换外观失败（走「只换数值」降级）：%s" % _e)
            rec["steps"].append({"step": "enemy_visual", "ok": False, "error": str(_e)})

    # ④a 敌人随机：方案 A（外观成功）**不做整行置换**；否则降级为只换数值（保留模型字段）。
    #     为什么降级写入不落本体：有方案层时写进「物品写完之后的本体临时副本」，层里拿这份；
    #     mod 本体只保留物品随机 —— 删掉 Plan= 就能把敌人还原（P0-2）。
    _enemy_mode = ""
    _layer_reg = None
    if enemy_cfg and enemy_cfg.get("on"):
        import enemy_randomizer as er
        if _plan_for_visual is not None and _units_for_visual is not None:
            _u, _plan = _units_for_visual, _plan_for_visual
            _warn, _issues = _warn_for_visual, []
        else:
            _u, _plan, _warn, _issues = er.plan_for_cfg(enemy_cfg)
        for _w in _warn:
            log("[④a] 警告：%s" % _w)
        if _issues:
            raise RuntimeError("敌人随机自检未通过（%d 项）：%s" % (len(_issues), _issues[:3]))
        _tmp = os.path.join(LOG, "enemy_plan_" + ts + ".csv")
        er.write_plan(_plan, _u, _tmp)
        if _visual_ok:
            _enemy_mode = "visual"
            # 关键（方案 A）：视觉已经由 MSB 负责，NpcParam 再按同一 plan 置换就是双重置换
            # （审计实测：被改 part 的模型 B 的原始 hp ≠ 实际生效 hp 的 65.2%）。
            log("[④a] 方案 A：敌人身份由 MSB 负责，跳过 NpcParam 整行置换（避免双重置换）")
            rec["steps"].append({"step": "enemy", "ok": True, "mode": "visual", "rows": 0,
                                 "plan": os.path.basename(_tmp)})
        else:
            _enemy_mode = "regulation-fallback"
            if plan_label:
                _layer_reg = os.path.join(LOG, "regulation_layer_" + ts + ".bin")
                shutil.copy2(_wreg, _layer_reg)
                _target = _layer_reg
            else:
                _target = _wreg if overlay else reg
                if not overlay:
                    log("[④a] 注意：没有方案层标签，降级的整行置换直接写 mod 本体（旧行为）")
            _res = er.apply_plan(er.read_plan(_tmp), source=_target, out_path=_target,
                                 verify=True, quiet=True,
                                 keep_rune=bool((enemy_cfg or {}).get("keep_rune")),
                                 keep_model_fields=True)
            log("[④a] 降级模式：整行置换 %s 行（%s，指纹 %s，已保留模型绑定字段）"
                % (_res["rows"], er.summarize(_u, _plan), _res["fingerprint"][:16]))
            rec["steps"].append({"step": "enemy", "ok": True, "mode": _enemy_mode,
                                 "rows": _res["rows"], "fingerprint": _res["fingerprint"],
                                 "plan": os.path.basename(_tmp), "target": _target})
    rec["enemy_mode"] = _enemy_mode

    rec["steps"].append({"step": "regulation", "ok": not rep["skipped"], "stats": rep["stats"],
                         "skipped": rep["skipped"], "bytes_changed": rep["changed_bytes"]})

    # ⑤ msgbnd
    if sync_guide:
        g = native_guide.apply_guide(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"),
                                     guide_xml, source=(o_msg if overlay else msg),
                                     out=_wmsg, quiet=True)
        log(f"[⑤] 说明书：改写 {len(g['entries'])} 条（全文），跳过 {len(g['skipped'])}")
        rec["steps"].append({"step": "msgbnd", "ok": bool(g["entries"]), "entries": len(g["entries"]),
                             "size": g["size"]})

    # ⑥ 校验
    plain = erio.dcx_decompress(erio.regulation_decrypt(_wreg))
    raw, kind, _d = native_guide.raw_and_bnd(_wmsg)
    bnd = erio.Bnd4.parse(raw)
    fmg = [d for n, d in bnd.files if n.endswith("GoodsCaption.fmg")]
    log(f"[⑥] 校验：regulation 明文 {len(plain)} B；说明书 {os.path.getsize(_wmsg)} B、{len(bnd.files)} 个 FMG")
    rec["verify"] = {"plain_len": len(plain), "msg_size": os.path.getsize(_wmsg), "fmg_count": len(bnd.files),
                     "fmg_len": len(fmg[0]) if fmg else 0}
    # ⑦ 方案层：把这次的产物抄成一个"覆盖层"，用 YAFSML 的 [mod] 列表挂载（法魂本体永不动）
    #    为什么放最后：层里放的是**部署完**的 regulation.bin，所以必须在所有写入之后。
    #    为什么有用：方案之间从此可以共存 —— 切换只是 ini 里一行 Plan=…，回滚就是删掉那行。
    #    视觉模式：层里是「物品随机后的本体 regulation（NpcParam 原始）+ 改过的地图」；
    #    降级模式：层里是「物品 + 敌人整行置换」的临时副本（本体只留物品）—— P0-2/P0-3。
    if plan_label:
        try:
            import plan_layer as PL
            _r = PL.export_layer(plan_label, extra_files=_msb_files + _evd_files, log=log,
                                 reg_src=(_layer_reg or _wreg),
                                 msg_src=(_wmsg if overlay else None))
            PL.make_launchers(_r["dir"], _r["label"], log=log)
            PL.write_info(_r["dir"], dict(plan_meta or {}), log=log)
            log(f"[⑦] 方案层：{_r['dir']}（{len(_r['files'])} 个文件，{_r['bytes']/1048576:.1f} MB）")
            # 2026-10-17 加：**写完自动挂载** —— 以前只在日志里写“想用就双击 bat”，
            # 作者没点 ⇒ 新层躺在磁盘上，游戏加载的还是旧层（“两个 Boss 没随机”就是这么来的）
            if not mount:
                log("     按调用方的安排：先不挂载（方案库开玩时会挂，生成阶段不打扰当前档）")
                rec["steps"].append({"step": "plan_mount", "ok": True, "mounted": False})
            else:
                try:
                    _m = PL.set_plan(_r["dir"])
                    log("     已**自动挂载**这个方案层（YAFSML.ini 里的 Plan= 已更新）—— 关掉程序重新进游戏就生效")
                    rec["steps"].append({"step": "plan_mount", "ok": True, "plan": _m,
                                         "mode": _enemy_mode})
                except Exception as _me:
                    log(f"     自动挂载失败（可手动双击「用这个方案启动.bat」）：{_me}")
                    rec["steps"].append({"step": "plan_mount", "ok": False, "error": str(_me)})
            rec["steps"].append({"step": "plan_layer", "ok": True, "dir": _r["dir"],
                                 "files": len(_r["files"]), "bytes": _r["bytes"],
                                 "mode": _enemy_mode,
                                 "overlay": bool(overlay),
                                 "reg_src": (_layer_reg or _wreg)})
        except Exception as _e:
            log(f"[⑦] 方案层产出失败（本体写入不受影响）：{_e}")
            rec["steps"].append({"step": "plan_layer", "ok": False, "error": str(_e)})

    with open(os.path.join(LOG, f"deploy_{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    log(f"     收据：logs/deploy_{ts}.json")
    return rec


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--no-guide", action="store_true")
    a = ap.parse_args()
    print("=== 原生部署 ===")
    deploy(os.path.abspath(a.plan), sync_guide=not a.no_guide)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
