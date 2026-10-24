# -*- coding: utf-8 -*-
"""方案层（plan layer）：把一次随机的产物做成"覆盖层"，用 YAFSML 的 [mod] 列表挂载。

为什么这么做（本机实测的依据）：
* `yafsml\\YAFSML.ini` 的 `[mod]` 段原文：“扫描并覆盖游戏数据的模组目录；
  **后声明的模组覆盖先声明的模组中的同名文件**” → 加一行就是覆盖层。
* YAFSML 是**运行时注入**式加载器（`使用说明.md`：游戏目录里的文件一个都不会被改）。
* 关键体积：`regulation.bin` 只有 ~2.9 MB → 每个方案存一份完全可行；
  地图是按**文件**覆盖，所以方案层只放**改过的那几张**（每张 ~0.4 MB）。

于是：
    方案/<标签>/
      mod/regulation.bin                      ← 部署完的那份（物品+敌人一起）
      mod/map/MapStudio/<改过的>.msb.dcx       ← 只有二期真换敌人时才有
      mod/msg/zhocn/item_dlc02.msgbnd.dcx      ← 只有同步了说明书时才有
      用这个方案启动.bat / 切回法魂本体.bat / 方案信息.txt

切换 = 在 ini 的 [mod] 段里加/删一行 `Plan=...`；法魂本体（`Convergence=../mod`）**永不动**。

命令行：
    python plan_layer.py --export --label 20261016_2030_敌人全随     # 产出方案层
    python plan_layer.py --activate <方案目录>                        # 把该方案挂上去
    python plan_layer.py --deactivate                                 # 切回法魂本体
    python plan_layer.py --list                                       # 看现有方案与当前挂载
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER          # noqa: E402

PLAN_LINE = "Plan="
SECTION_MOD = "[mod]"


# ────────────────────────── 路径 ──────────────────────────

def mod_root():
    """法魂包的 mod 目录 —— 就是 regulation.bin 所在的那个目录。

    ⚠️ ER._mod_reg() 返回的是 `<法魂包>/mod/regulation.bin` 这个**文件**路径，
    所以只要 **一次** dirname。这里带自检，免得又差一层（本会话在这上面栽过两次）。
    """
    d = os.path.dirname(os.path.abspath(ER._mod_reg()))
    assert os.path.isfile(os.path.join(d, "regulation.bin")), f"mod_root 不对：{d}"
    return d


def pack_root():
    """法魂包根目录（yafsml/ 与 启动法魂.bat 所在处）"""
    d = os.path.dirname(mod_root())
    if not os.path.isdir(os.path.join(d, "yafsml")):
        raise RuntimeError(
            "法魂包根目录不对（没有 yafsml\\）：%s\n"
            "  方案层要靠 YAFSML 挂载，所以随机器要和法魂整合包放在一起；\n"
            "  如果这个 MOD 目录里确实没有 yafsml/，请在界面「指定 MOD 目录…」里重新选。" % d)
    return d


def ini_path():
    return os.path.join(pack_root(), "yafsml", "YAFSML.ini")


def plans_root():
    return os.path.join(pack_root(), "方案")


def layer_mod_dir(path):
    """把「方案层」路径统一成 **mod 数据根**（YAFSML `[mod]` 的值要的就是它）。

    为什么必须这么绕（2026-10-17 审计的 P0-1）：
      * `[mod]` 的值是**数据根**：目录里直接有 `regulation.bin` / `map/`（对照 `Convergence=../mod`）；
      * 方案层的游戏数据在 `<层根>\\mod\\`，**层根下什么都没有** ——
        以前 set_plan 把层根原样写进 `Plan=`，YAFSML 于是 "added mod Plan" 成功、却一条覆盖都没加载
        （日志 19556 行里来自 `方案\\...` 的 file override = 0）。
    所以：传层根 → 自动补 `/mod`；传进来的已经是数据根（或裸目录里就有 regulation/map）→ 原样返回。
    两者都不是就**拒绝**（宁可报错，也不写出一个永远不会生效的 Plan=）。
    """
    p = os.path.normpath(os.path.abspath(path))
    if os.path.isfile(os.path.join(p, "regulation.bin")) or os.path.isdir(os.path.join(p, "map")):
        return p
    m = os.path.join(p, "mod")
    if os.path.isdir(m) and (os.path.isfile(os.path.join(m, "regulation.bin"))
                             or os.path.isdir(os.path.join(m, "map"))):
        return m
    raise RuntimeError(f"{p} 不是方案层：它下面既没有 regulation.bin/map，也没有 mod\\ 数据目录")


# ────────────────────────── ini 读写（保留注释，只动 [mod] 段）──────────────────────────

def _read_text(p):
    """按字节判编码，**并且记住有没有 BOM** —— 写回时要一模一样。

    （踩过：原文件没有 BOM，我却按 utf-8-sig 写回，多出 3 个字节 → 还原后不是逐字节一致。）
    同时按字节判行尾（CRLF/LF），写回时保持一致。
    """
    raw = open(p, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    for enc in (("utf-8-sig" if bom else "utf-8"), "utf-8", "gbk"):
        try:
            t = raw.decode(enc)
            eol = "\r\n" if b"\r\n" in raw[:4096] else "\n"
            return t, enc, bom, eol
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8", False, "\n"


def read_ini():
    """按**实际行尾**切分（CRLF 文件里若按 "\n" 切，行尾会变成 \r\r\n —— 踩过）。"""
    t, enc, bom, eol = _read_text(ini_path())
    return t.split(eol), (enc, bom, eol)


def write_ini(lines, meta):
    """写回时保持：编码、BOM 有无、行尾风格 —— 目标是"除了我们改的那行，逐字节不变"。"""
    enc, bom, eol = meta
    p = ini_path()
    bak = p + ".bak_planlayer_" + time.strftime("%Y%m%d_%H%M%S")
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    text = eol.join(lines)
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    elif enc == "gbk":
        data = text.encode("gbk", "replace")
    with open(p, "wb") as f:
        f.write(data)
    return bak


def current_plan_line():
    lines, _m = read_ini()
    for ln in lines:
        if ln.strip().startswith(PLAN_LINE):
            return ln.strip()[len(PLAN_LINE):]
    return None


def plan_status():
    """当前 `Plan=` 是否**真的能被 YAFSML 看见**（P0-1 的可视化判据，只读）。

    判据不是"ini 里有一行"，而是"这一行指向的数据根里真的有游戏数据"。
    以前把层根写进 Plan= 时，YAFSML 日志里 added mod 成功、但 file override 一条都没有 ——
    所以必须在这里如实报「无效 + 原因」，别让界面显示"已挂载"。
    """
    line = current_plan_line()
    out = {"line": line or "", "target": "", "valid": False, "reason": ""}
    if not line:
        out["reason"] = "未挂载（跑的是纯法魂本体）"
        return out
    p = line
    if not os.path.isabs(p):
        p = os.path.normpath(os.path.join(os.path.dirname(ini_path()), p))
    out["target"] = p
    if not os.path.isdir(p):
        out["reason"] = "目标目录不存在"
        return out
    if not (os.path.isfile(os.path.join(p, "regulation.bin")) or os.path.isdir(os.path.join(p, "map"))):
        out["reason"] = "不是数据根（缺 regulation.bin/map；层根后面要再加 \\mod）"
        return out
    out["valid"] = True
    return out


def set_plan(rel_or_abs):
    """把 [mod] 段的 Plan=... 设成**数据根**（相对 yafsml/ 或绝对路径）。

    2026-10-17 审计修（P0-1）：YAFSML 的 `[mod]` 要的是 `<层根>\\mod`，不是层根。
    传层根也收（内部自动补），写进去的一定是数据根 —— 否则层永远挂不上。

    2026-10-18 实测修（P0-1 的第二个坑）：YAFSML 读 ini 的 Plan 值有**长度上限**
    （绝对路径 132 字符时被截断成 126 字符 + 乱码 → 日志报
    `cannot find mod Plan in directory ...`，层仍然没挂上）。所以只要目标在法魂包内，
    一律写**相对 yafsml/ 的路径**（`../方案/<层>/mod`，和 `Convergence=../mod` 同一口径）——
    既短又不怕以后换目录。

    规则：`Convergence=../mod` 必须是**第一层**（保持不动）；我们只在它**之后**加一行。
    已有的 Plan= 行会被换成新的（保证同时只有一个方案生效）。
    """
    target = layer_mod_dir(rel_or_abs)
    pr = pack_root()
    if target == pr or target.startswith(pr + os.sep):
        new_val = os.path.relpath(target, os.path.dirname(ini_path())).replace("\\", "/")
    else:
        new_val = target
    lines, meta = read_ini()
    # 找 [mod] 段范围
    try:
        i = next(k for k, ln in enumerate(lines) if ln.strip().lower() == SECTION_MOD)
    except StopIteration:
        raise RuntimeError("YAFSML.ini 里找不到 [mod] 段，先手工确认模板是否被改过")
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith("["):
        j += 1
    seg = lines[i + 1:j]
    seg = [ln for ln in seg if not ln.strip().startswith(PLAN_LINE)]
    # 插在 Convergence 行之后（没有就追加到段尾）
    pos = None
    for k, ln in enumerate(seg):
        if ln.strip().lower().startswith("convergence="):
            pos = k + 1
    new_line = PLAN_LINE + new_val
    seg.insert(pos if pos is not None else len(seg), new_line)
    lines[i + 1:j] = seg
    bak = write_ini(lines, meta)
    # 层在别的盘上时 relpath 会抛 ValueError（2026-10-23 自检踩到）—— 那就把绝对路径原样报回去
    try:
        _rel = os.path.relpath(target, os.path.dirname(ini_path()))
    except ValueError:
        _rel = target
    return {"ini": ini_path(), "backup": bak, "plan": new_val,
            "dir": os.path.dirname(target), "abs": target,
            "rel": _rel if os.path.isabs(target) else target}


def clear_plan():
    lines, meta = read_ini()
    out = [ln for ln in lines if not ln.strip().startswith(PLAN_LINE)]
    if len(out) == len(lines):
        return {"ini": ini_path(), "changed": False}
    bak = write_ini(out, meta)
    return {"ini": ini_path(), "backup": bak, "changed": True}


# ────────────────────────── 产出方案层 ──────────────────────────

def _sha(p, n=16):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:n] if os.path.isfile(p) else ""


def export_layer(label=None, extra_files=None, log=print, reg_src=None, msg_src=None):
    """把**当前已部署**的 mod 产物抄进一个方案层目录。

    extra_files：额外要进层的东西（二期换敌人的地图），给 [(源绝对路径, 层内相对路径), …]
    reg_src / msg_src：覆盖层里放的 regulation.bin / 说明书。给了就从这两个文件拿 ——
    「只进方案层、不写本体」的模式下（native_deploy.deploy(overlay=True)）产物不在本体里，
    而在 APPLY/work/overlay_<ts>/ 的工作副本里。
    """
    mr, pr = mod_root(), plans_root()
    label = label or time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(pr, label)
    dest_mod = os.path.join(dest, "mod")
    os.makedirs(dest_mod, exist_ok=True)
    log(f"[方案层] 法魂包 = {pack_root()}")
    log(f"[方案层] 目录   = {dest}")

    got = []
    # ① regulation.bin（默认是已部署的那份；只写入敌人时由调用方传入自己打好的一份）
    src = reg_src or os.path.join(mr, "regulation.bin")
    if not os.path.isfile(src):
        raise RuntimeError(f"找不到 {src}")
    shutil.copy2(src, os.path.join(dest_mod, "regulation.bin"))
    got.append(("regulation.bin", 1, _sha(src), os.path.getsize(src)))

    # ② 说明书（只有跟原始备份不同才放 —— 不然白占 16 MB）
    rel_msg = os.path.join("msg", "zhocn", "item_dlc02.msgbnd.dcx")
    cur_msg = msg_src or os.path.join(mr, rel_msg)
    orig_msg = _newest_orig("item_dlc02.msgbnd.dcx")
    if os.path.isfile(cur_msg) and (orig_msg or msg_src):
        if not orig_msg or _sha(cur_msg) != _sha(orig_msg):
            os.makedirs(os.path.dirname(os.path.join(dest_mod, rel_msg)), exist_ok=True)
            shutil.copy2(cur_msg, os.path.join(dest_mod, rel_msg))
            got.append((rel_msg, 1, _sha(cur_msg), os.path.getsize(cur_msg)))
            log(f"[方案层] 说明书与原始不同 → 已放入（{os.path.getsize(cur_msg)/1048576:.1f} MB）")
        else:
            log("[方案层] 说明书与原始一致 → 不放（省 16 MB）")

    # ③ 额外文件（二期：改动过的地图）
    n = 0
    for s, rel in (extra_files or []):
        if not os.path.isfile(s):
            log(f"[方案层] 跳过不存在的：{s}")
            continue
        t = os.path.join(dest_mod, rel)
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(s, t)
        got.append((rel, 1, _sha(s), os.path.getsize(s)))
        n += 1
    if n:
        log(f"[方案层] 额外文件 {n} 个（地图等）")

    total = sum(g[3] for g in got)
    log(f"[方案层] 共 {len(got)} 个文件、{total/1048576:.1f} MB")
    return {"dir": dest, "mod": dest_mod, "files": got, "bytes": total, "label": label}


def find_pristine_reg():
    """找一份**原始** regulation 备份（apply/backup/regulation.bin.orig_*）"""
    bak = os.path.join(HERE, "backup")
    if not os.path.isdir(bak):
        return None
    cand = sorted((os.path.join(bak, f) for f in os.listdir(bak)
                   if f.startswith("regulation.bin.orig_")), reverse=True)
    return cand[0] if cand else None


def make_enemy_layer(label, enemy_cfg, log=print):
    """**只写入敌人**：以原始 regulation 为底，只套一遍敌人随机，产出方案层。

    方案 A（2026-10-17 审计定案，见 docs/敌人随机_修复_交接提示词.md §3）：
      * 外观（visual）开启且 MSB 真的产出了地图 → 敌人身份**只由 MSB 负责**
        （写每个 part 的 npc_id/model/think/chara，目标行保持原始内容 ⇒ 模型=数值=AI=掉落自洽）；
        此时**不再对 NpcParam 做整行置换**（两层各做一遍同一个置换 = 双重置换，实测 65% 错位）。
        层里放「原始 regulation + 改过的地图」。
      * 外观关闭 / 外观这步失败 → 退回一期「只换数值」：整行置换 + 保留模型绑定字段。
        这是明确的降级路径，不是 bug。
    **不写 mod 本体**（P0-2）：本体只会在 app 的完整部署里被物品随机写；敌人层只落在方案层里。
    返回 export_layer 的结果（额外带 mode / maps）。
    """
    import tempfile
    import shutil
    import enemy_randomizer as ER

    src = find_pristine_reg()
    if not src:
        raise RuntimeError("找不到原始 regulation 备份（investigation/apply/backup/"
                           "regulation.bin.orig_*）—— 先在主界面刷一遍「还原成原始」或做过一次写入")
    tmpd = tempfile.mkdtemp(prefix="_enemylayer_")
    tmpreg = os.path.join(tmpd, "regulation.bin")
    shutil.copy2(src, tmpreg)
    log("[\u53ea\u5199\u5165\u654c\u4eba] \u5e95\u5c42\uff1a" + os.path.basename(src))

    units, plan, warn, issues = ER.plan_for_cfg(enemy_cfg, reg_path=tmpreg)
    for w in warn:
        log("[\u53ea\u5199\u5165\u654c\u4eba] \u8b66\u544a\uff1a" + str(w))
    if issues:
        raise RuntimeError("\u654c\u4eba\u968f\u673a\u81ea\u68c0\u672a\u901a\u8fc7\uff1a" + str(issues[:3]))

    mode = "regulation-fallback"
    extra = []
    evd_stat = {}
    if (enemy_cfg or {}).get("visual"):
        try:
            import enemy_swapper as ES
            mdir = os.path.join(mod_root(), "map", "MapStudio")
            odir = os.path.join(tmpd, "msb")
            sres = ES.plan_swaps(dict(plan), map_dir=mdir, out_dir=odir, log=log)
            ok = bool(sres.get("ok")) and int(sres.get("maps_written") or 0) > 0
            log("[\u53ea\u5199\u5165\u654c\u4eba] \u771f\u6362\u5916\u89c2\uff1a%d \u5f20\u56fe\u3001%d \u4e2a\u654c\u4eba"
                "\uff08\u8df3\u8fc7 %d\uff0cok=%s\uff09"
                % (sres.get("maps_changed", 0), sres.get("parts_changed", 0),
                   sres.get("parts_skipped", 0), ok))
            if ok:
                mode = "visual"
                # sres["files"] 是 [{map, out, …}]（dict），不是文件名 —— 以前这里直接
                # os.path.join(odir, dict) 会抛 TypeError，然后被 except 吞成"外观失败"，
                # 于是 GUI「只写入敌人」永远只换数值（P0-3 测试当场抓到）。按 map 字段取文件名。
                _map_names = [d["map"] if isinstance(d, dict) else str(d)
                              for d in (sres.get("files") or [])]
                extra = [(os.path.join(odir, m), os.path.join("map", "MapStudio", m))
                         for m in _map_names]
                # 方案乙：血条名/BGM 跟随新 Boss（只改 EMEVD 的 int 参数槽）
                if (enemy_cfg or {}).get("emevd"):
                    try:
                        import enemy_emevd as EE
                        ev_src = os.path.join(mod_root(), "event")
                        ev_out = os.path.join(tmpd, "event")
                        changes = EE.collect_changes(_map_names, mdir, odir)
                        evd_stat = EE.patch_layer_events(ev_src, ev_out, changes, log=log)
                        extra += evd_stat.get("files") or []
                    except Exception as e:                        # noqa: BLE001
                        log("[\u53ea\u5199\u5165\u654c\u4eba] \u65b9\u6848\u4e59\uff08\u8840\u6761\u540d/BGM\uff09\u5931\u8d25\uff1a" + str(e))
            else:
                # 外观没可靠产出就整批丢（绝不把"部分地图 + 数值置换"混在一起 = 半换）
                log("[\u53ea\u5199\u5165\u654c\u4eba] \u5916\u89c2\u6ca1\u6709\u53ef\u9760\u4ea7\u51fa \u2192 \u964d\u7ea7\u4e3a\u300c\u53ea\u6362\u6570\u503c\u300d")
        except Exception as e:
            log("[\u53ea\u5199\u5165\u654c\u4eba] \u771f\u6362\u5916\u89c2\u5931\u8d25 \u2192 \u964d\u7ea7\u4e3a\u300c\u53ea\u6362\u6570\u503c\u300d\uff1a" + str(e))
    else:
        log("[\u53ea\u5199\u5165\u654c\u4eba] \u672c\u6b21\u672a\u5f00\u5916\u89c2 \u2192 \u53ea\u6362\u6570\u503c")

    res_rows = 0
    if mode == "visual":
        # 方案 A：regulation 保持原始（NpcParam 一个字节都不动）
        log("[\u53ea\u5199\u5165\u654c\u4eba] \u89c6\u89c9\u6a21\u5f0f\uff1aNpcParam \u4e0d\u505a\u6574\u884c\u7f6e\u6362\uff08\u907f\u514d\u53cc\u91cd\u7f6e\u6362\uff09")
    else:
        plan_csv = os.path.join(tmpd, "enemy_plan.csv")
        ER.write_plan(plan, units, plan_csv)
        # 降级路径：模型一个都没换 ⇒ 所有行都退回安全模式（保留全部模型绑定字段）。
        # 按行机制（keep_model_rows）走一遍：以后做「部分行换、部分行不换」的混合模式也用它。
        res = ER.apply_plan(ER.read_plan(plan_csv), source=tmpreg, out_path=tmpreg,
                            verify=True, quiet=True, keep_model_rows=set(plan),
                            keep_rune=bool((enemy_cfg or {}).get("keep_rune")))
        res_rows = res["rows"]
        log("[\u53ea\u5199\u5165\u654c\u4eba] \u6574\u884c\u7f6e\u6362 %d \u884c\uff08%s\uff0c\u5df2\u4fdd\u7559\u6a21\u578b\u7ed1\u5b9a\u5b57\u6bb5\uff09"
            % (res["rows"], ER.summarize(units, plan)))

    r = export_layer(label, extra_files=extra, log=log, reg_src=tmpreg)
    make_launchers(r["dir"], r["label"], log=log)
    write_info(r["dir"], {
        "\u7c7b\u578b": "\u53ea\u5199\u5165\u654c\u4eba\uff08\u7269\u54c1\u672a\u52a8\uff09",
        "\u7b56\u7565": ("\u65b9\u6848 A\uff1a\u5916\u89c2\u7531 MSB \u8d1f\u8d23\uff0cNpcParam \u4e0d\u6574\u884c\u7f6e\u6362"
                      if mode == "visual"
                      else "\u964d\u7ea7\uff1a\u53ea\u6362\u6570\u503c\uff08\u4fdd\u7559\u6a21\u578b\u7ed1\u5b9a\u5b57\u6bb5\uff09"),
        "\u79cd\u5b50": enemy_cfg.get("seed"),
        "\u53c2\u4e0e\u7c7b\u522b": "\u3001".join(enemy_cfg.get("pools") or []),
        "\u6bd4\u4f8b": enemy_cfg.get("rate"),
        "\u6765\u6e90": enemy_cfg.get("source"),
        "\u8fde\u5916\u89c2": "\u662f" if mode == "visual" else "\u5426\uff08\u964d\u7ea7\uff09",
        "\u8840\u6761\u540d/BGM\uff08\u65b9\u6848\u4e59\uff09": (
            ("\u8840\u6761\u540d %d \u5904\u3001BGM %d \u5904\uff08\u4e8b\u4ef6\u811a\u672c %d \u5f20\uff09"
             % (evd_stat.get("name", 0), evd_stat.get("bgm", 0), evd_stat.get("maps", 0)))
            if evd_stat else ("\u672a\u5f00/\u5931\u8d25" if (enemy_cfg or {}).get("emevd") else "\u672a\u5f00")),
        "\u6539\u5199\u884c\u6570": res_rows,
        "\u6539\u8fc7\u7684\u5730\u56fe": len(extra)}, log=log)
    try:
        shutil.rmtree(tmpd, ignore_errors=True)
    except Exception:
        pass
    r["mode"] = mode
    r["maps"] = len(extra)
    return r


def _newest_orig(name):
    """找 apply/backup 下最新的一份原始备份（说明书/regulation 都有约定命名）"""
    bak = os.path.join(HERE, "backup")
    if not os.path.isdir(bak):
        return None
    cand = sorted((os.path.join(bak, f) for f in os.listdir(bak)
                   if f.startswith(name + ".orig_")), reverse=True)
    return cand[0] if cand else None


# ────────────────────────── 两个 .bat ──────────────────────────

BAT_LAUNCH = """@echo off
chcp 65001 > nul
title 用方案启动 - {label}
echo.
echo   方案：{label}
echo   覆盖层：{dest_mod}
echo   本体：{mod_root}   （永不动）
echo.
echo   这个方案有自己的存档：启动前换进来，退出游戏后进度存回它的槽。
echo.
start "" {cmd} --play "{dest_mod}"
if errorlevel 1 (
    echo.
    echo   [x] 启动器没起来，请把上面的报错发我。
    pause
    exit /b 1
)
echo   已交给启动器（可能会先问：游戏在跑要不要关掉 / 没有存档要不要开新角色）。
echo   启动日志：{log_path}
timeout /t 3 > nul
"""

BAT_REVERT = """@echo off
chcp 65001 > nul
title 切回法魂本体
{cmd} --plan-off
echo.
echo   已切回法魂本体（下一次启动就是纯法魂）。
pause
"""


def launcher_cmd():
    """bat 里的启动器命令行前缀。

    * 打包版（sys.frozen）：就是随机器 exe 自己；
    * 源码运行：pythonw + 工作区里的 randgui.py（以前依赖系统 python，玩家机器上没有）。
    """
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    exe = sys.executable or "python.exe"
    _pw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(_pw):
        exe = _pw
    gui = os.path.join(os.path.dirname(os.path.dirname(HERE)), "randgui.py")
    if not os.path.isfile(gui):
        gui = os.path.join(os.getcwd(), "randgui.py")
    return '"%s" "%s"' % (exe, gui)


def make_launchers(dest, label, log=print):
    """写两个 bat：用这个方案启动（带它自己的存档）/ 切回法魂本体。

    2026-10-23 作者反馈：从方案目录里启动时用的是**当前**存档 —— 因为老 bat 只挂 Plan= 再
    call 启动法魂.bat，绕过了存档库。现在改成调随机器自己的 --play / --plan-off。
    """
    cmd = launcher_cmd()
    d1 = os.path.join(dest, "用这个方案启动.bat")
    d2 = os.path.join(dest, "切回法魂本体.bat")
    with open(d1, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(BAT_LAUNCH.format(label=label, dest_mod=os.path.join(dest, "mod"),
                                  dest=dest, cmd=cmd, mod_root=mod_root(),
                                  log_path=os.path.join(dest, "启动日志.txt")))
    with open(d2, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(BAT_REVERT.format(cmd=cmd))
    log(f"[方案层] 启动器：{os.path.basename(d1)} / {os.path.basename(d2)}")
    return d1, d2


def write_info(dest, meta, log=print):
    p = os.path.join(dest, "方案信息.txt")
    with open(p, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("法魂随机 · 方案层\r\n")
        f.write("生成时间：%s\r\n\r\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        for k, v in (meta or {}).items():
            f.write("%s：%s\r\n" % (k, v))
        f.write("\r\n挂载方式：在 yafsml\\YAFSML.ini 的 [mod] 段里加一行\r\n")
        # ⚠️ 2026-10-17 审计：`[mod]` 的值必须是**数据根**（层根\\mod），层根本身没有游戏数据。
        f.write("    Plan=../方案/%s/mod\r\n" % os.path.basename(dest))
        f.write("（后声明的层覆盖先声明的 —— 法魂本体那行 Convergence=../mod 必须在前）\r\n")
    return p


# ────────────────────────── 命令行 ──────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="法魂随机的方案层工具")
    ap.add_argument("--export", action="store_true", help="把当前已部署的产物产出成方案层")
    ap.add_argument("--label", help="方案名（默认时间戳）")
    ap.add_argument("--activate", metavar="DIR", help="挂载某个方案目录")
    ap.add_argument("--deactivate", action="store_true", help="切回法魂本体")
    ap.add_argument("--list", action="store_true", help="列出方案与当前挂载")
    ap.add_argument("--launchers", action="store_true",
                    help="给已有方案层重写两个启动器（改成走存档库的 --play）")
    a = ap.parse_args(argv)

    if a.launchers:
        pr = plans_root()
        n = 0
        if os.path.isdir(pr):
            for name in sorted(os.listdir(pr)):
                d = os.path.join(pr, name)
                if os.path.isdir(os.path.join(d, "mod")):
                    make_launchers(d, name)
                    n += 1
        print("重写了 %d 个方案层的启动器（现在走随机器 --play：换档 + 退出回存）" % n)
        return 0

    if a.export:
        r = export_layer(a.label)
        make_launchers(r["dir"], r["label"])
        meta = {"标签": r["label"], "文件数": len(r["files"]),
                "体积(MB)": round(r["bytes"] / 1048576, 1)}
        write_info(r["dir"], meta)
        print("方案层已生成：", r["dir"])
        return 0

    if a.activate:
        d = os.path.abspath(a.activate)
        try:
            target = layer_mod_dir(d)          # 传层根会在这里补 /mod；不是方案层就报错
        except RuntimeError as e:
            print(f"[x] {e}")
            return 2
        r = set_plan(target)
        print("已挂载：", r["plan"])
        print("  层根：", r.get("dir"))
        print("  写进 ", r["ini"], "（备份 ", r["backup"], "）")
        print("  下一次启动游戏就生效；切回本体用 --deactivate")
        return 0

    if a.deactivate:
        r = clear_plan()
        if not r["changed"]:
            print("本来就没有挂载方案（ini 里没有 Plan= 行）")
            return 0
        print("已移除 Plan= 行（备份 ", r["backup"], "）→ 下一次启动就是纯法魂本体")
        return 0

    # 默认：列出
    print("法魂包：", pack_root())
    print("ini   ：", ini_path())
    cur = current_plan_line()
    print("当前挂载：", cur or "（没有，跑的是纯法魂本体）")
    pr = plans_root()
    if os.path.isdir(pr):
        ds = sorted(os.listdir(pr), reverse=True)
        print("现有方案（%d 个）：" % len(ds))
        for d in ds[:12]:
            p = os.path.join(pr, d)
            sz = sum(os.path.getsize(os.path.join(r, f)) for r, _s, fs in os.walk(p) for f in fs)
            print("   %-34s %6.1f MB" % (d, sz / 1048576))
    else:
        print("还没有方案目录（%s）" % pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
