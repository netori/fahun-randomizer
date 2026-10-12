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

MOD = native_guide.MOD
WS = os.path.dirname(ROOT)
# MOD 目录来源（按优先级）：
#   ① 界面/命令行解析并发布的 CONVERGENCE_MOD_ROOT —— 打包发出去以后走这条
#   ② exe 自己所在目录就是 MOD 根（玩家把 exe 放进 MOD 目录）
#   ③ exe 同级的 法魂mod* —— 开发期布局
_env = os.environ.get("CONVERGENCE_MOD_ROOT")
if _env and os.path.isdir(os.path.join(_env, "mod")):
    MOD = os.path.normpath(_env)
elif getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
    if os.path.isfile(os.path.join(_base, "mod", "regulation.bin")):
        MOD = os.path.normpath(_base)
    else:
        _cand = [d for d in glob.glob(os.path.join(_base, "..", "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]
        if _cand:
            MOD = os.path.normpath(sorted(_cand)[0])
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


def deploy(plan_csv, sync_guide=True, log=print):
    relocate()
    # ── 打包版：把「所有会写文件的路径」重定位到 exe 旁边那份工作区 ──
    # 这些目录原本按"代码所在位置"拼，打包后那指向临时解包目录，
    # 于是它会去解包目录里找备份、写日志，而真正的备份在 exe 旁边 ——
    # 表现就是「系统找不到指定的路径」。relocate() 只覆盖了一部分模块，这里补齐。
    _env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if _env and os.path.isdir(os.path.join(_env, "mod")):
        globals()["MOD"] = os.path.normpath(_env)
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
    rec = {"ts": ts, "plan": os.path.basename(plan_csv), "steps": []}

    # ① 备份当前
    bdir = os.path.join(APPLY, "backup", f"deploy_{ts}")
    os.makedirs(bdir, exist_ok=True)
    for src, nm in ((reg, "regulation.bin"), (msg, "item_dlc02.msgbnd.dcx")):
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(bdir, nm))
    rec["backup_dir"] = bdir
    log(f"[①] 已备份当前文件到 backup/deploy_{ts}/")

    # ② 复原原始
    o_reg, o_msg = find_original("regulation.bin.orig_*"), find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*")
    if not (o_reg and o_msg):
        raise FileNotFoundError("找不到原始备份（backup/regulation.bin.orig_* 与 item_dlc02.msgbnd.dcx.zhocn.orig_*）")
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

    # ④ regulation
    rep = native_apply.apply_native(plan_csv, source=reg, out_path=reg, verify=True, quiet=True)
    log(f"[④] regulation：写入 {sum(v['applied'] for v in rep['stats'].values())} 格，跳过 {len(rep['skipped'])}；回读校验通过")
    rec["steps"].append({"step": "regulation", "ok": not rep["skipped"], "stats": rep["stats"],
                         "skipped": rep["skipped"], "bytes_changed": rep["changed_bytes"]})

    # ⑤ msgbnd
    if sync_guide:
        g = native_guide.apply_guide(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"),
                                     guide_xml, source=msg, out=msg, quiet=True)
        log(f"[⑤] 说明书：改写 {len(g['entries'])} 条（全文），跳过 {len(g['skipped'])}")
        rec["steps"].append({"step": "msgbnd", "ok": bool(g["entries"]), "entries": len(g["entries"]),
                             "size": g["size"]})

    # ⑥ 校验
    plain = erio.dcx_decompress(erio.regulation_decrypt(reg))
    raw, kind, _d = native_guide.raw_and_bnd(msg)
    bnd = erio.Bnd4.parse(raw)
    fmg = [d for n, d in bnd.files if n.endswith("GoodsCaption.fmg")]
    log(f"[⑥] 校验：regulation 明文 {len(plain)} B；说明书 {os.path.getsize(msg)} B、{len(bnd.files)} 个 FMG")
    rec["verify"] = {"plain_len": len(plain), "msg_size": os.path.getsize(msg), "fmg_count": len(bnd.files),
                     "fmg_len": len(fmg[0]) if fmg else 0}
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
