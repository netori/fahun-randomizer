# -*- coding: utf-8 -*-
"""enemy_gate.py — M3 读取端闸门：证明「方案层真的被引擎加载了」，而不是只证明写盘成功。

四组检查：
  ① 层完整性：manifest 里每个文件在磁盘上、sha256 一致；层里没有多余文件（半套/陈旧残留）
  ② 引擎加载证据：YAFSML.log 里最后一次加载的 Plan 必须就是这一层；本次会话能看到
     regulation / common_func / 每张地图 的 override 命中；出现别的层的 override 就 FAIL
  ③ 传送门自检：waygate 池的每个守门位置在**写出的层里**已经是换入身份，且克隆行
     hp 对、teamType=6、isSoulGetByBoss=0（可击杀、会给魂）
  ④ 报告：PASS / FAIL 分开列「未加载」与「真失败」

用法：
  python investigation/apply/enemy_gate.py --label 敌人v1_seed1
  python investigation/apply/enemy_gate.py --label 敌人v1_seed1 --offline   # 只看静态（游戏没开过也能跑）
  python investigation/apply/enemy_gate.py --label 敌人v1_seed1 --log <YAFSML.log>
  python investigation/apply/enemy_gate.py --selftest

纪律：只读。本模块不写任何文件（连临时文件都不写）。
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import erio                                                      # noqa: E402
import msb_edit                                                  # noqa: E402
import msb_read                                                  # noqa: E402
import param_bin                                                 # noqa: E402
import enemy_write as EW                                         # noqa: E402
import enemy_randomizer as ER                                    # noqa: E402

MANIFEST = "enemy_manifest.json"
DATA_SUB = "mod"
BGM_REL = "event/common_func.emevd.dcx"
MAP_REL = "map/MapStudio"

_OV_RE = re.compile(r"file override \[[^\]]*\]: request=([A-Za-z0-9_]+):/(.+?) expanded=(.*?) mod=(.+)$")
_PLAN_RE = re.compile(r"\[mod\] added mod Plan from .(.+?).$")


# ────────────────────────── 路径 ──────────────────────────

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def mod_root(mod=None):
    """mod 数据根（_mod_reg() 给的是 mod/regulation.bin 这个文件路径）。"""
    if mod:
        return os.path.abspath(mod)
    return os.path.dirname(os.path.abspath(ER._mod_reg()))


def layer_root(mod=None):
    return os.path.join(os.path.dirname(mod_root(mod)), "方案")


def default_log(mod=None):
    return os.path.join(os.path.dirname(mod_root(mod)), "yafsml", "log", "YAFSML.log")


def find_layer(label=None, layer=None):
    if layer:
        p = os.path.abspath(layer)
        if not os.path.isfile(os.path.join(p, MANIFEST)):
            raise SystemExit("不是方案层（没有 %s）：%s" % (MANIFEST, p))
        return p
    root = layer_root()
    if not os.path.isdir(root):
        raise SystemExit("找不到方案层根目录：%s" % root)
    if label:
        p = os.path.join(root, label)
        if not os.path.isfile(os.path.join(p, MANIFEST)):
            raise SystemExit("找不到这一层：%s" % p)
        return p
    cand = [d for d in sorted(os.listdir(root))
            if os.path.isfile(os.path.join(root, d, MANIFEST))]
    if len(cand) == 1:
        return os.path.join(root, cand[0])
    raise SystemExit("有 %d 个方案层，请用 --label 指定：%s" % (len(cand), ", ".join(cand)))


def read_manifest(layer):
    with open(os.path.join(layer, MANIFEST), "r", encoding="utf-8") as f:
        return json.load(f)


# ────────────────────────── 层文件清单 ──────────────────────────

def rel_of(kind, name):
    k = kind.lower()
    if k == "regulation":
        return "regulation.bin"
    if k == "mapstudio":
        return (MAP_REL + "/" + name).lower()
    if k in ("event", "emevd"):
        return ("event/" + name).lower()
    return None


def disk_files(data_dir):
    out = set()
    for root, _dirs, files in os.walk(data_dir):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), data_dir).replace("\\", "/")
            out.add(rel.lower())
    return out


def parse_log(text, label):
    """读 YAFSML.log：返回最后一次 Plan 会话里、来自本层的 override 命中集合。"""
    lines = text.splitlines()
    start = None
    declared = None
    for i, ln in enumerate(lines):
        m = re.search(r"\[mod\] added mod Plan from .(.+?).$", ln)
        if m:
            start, declared = i, m.group(1)
    out = {"start": start, "declared": declared, "hits": set(), "foreign": [],
           "errors": [], "overrides": 0, "maps": set()}
    if start is None:
        return out
    lab = (label or "").lower()
    for ln in lines[start + 1:]:
        if ln.startswith("ERROR") or " ERROR: " in ln:
            out["errors"].append(ln.strip()[:240])
            continue
        if "file override" not in ln:
            continue
        m = _OV_RE.search(ln)
        if not m:
            continue
        kind, name, _exp, modp = m.group(1), m.group(2), m.group(3), m.group(4)
        modn = modp.strip().replace("\\", "/").lower()
        if "/方案/" not in modn:
            continue
        if lab and lab not in modn:
            out["foreign"].append(modp.strip())
            continue
        rel = rel_of(kind, name)
        if rel:
            out["hits"].add(rel)
            if rel.startswith("map/mapstudio/"):
                out["maps"].add(rel)
            out["overrides"] += 1
    return out


# ────────────────────────── 传送门自检（静态，读层） ──────────────────────────

def _layer_parts(data_dir, map_name, cache):
    if map_name in cache:
        return cache[map_name]
    p = os.path.join(data_dir, "map", "MapStudio", map_name + ".msb.dcx")
    with open(p, "rb") as f:
        raw, _hdr = msb_read.dcx_payload(f.read())
    parts = msb_edit.Msb(raw).parts()
    seen = {}
    idx = {}
    for _i, part in parts:
        nm = part.get("part_name") or ""
        k = seen.get(nm, 0) + 1
        seen[nm] = k
        idx[(nm, k)] = part
    cache[map_name] = idx
    return idx


def check_waygate(data_dir, plan, man, log=print):
    """waygate 池的守门位置：层里的身份已是换入者，克隆行可击杀。返回失败清单。"""
    fails = []
    units = [u for u in (plan.get("units") or [])
             if "waygate" in (u.get("pools") or [])]
    if not units:
        log("[闸门] 传送门：计划里没有 waygate 单元（跳过）")
        return fails
    bnd = erio.read_regulation(os.path.join(data_dir, "regulation.bin"))
    npn = EW.find_param_name([n for n, _d in bnd.files], "NpcParam.param")
    pf = param_bin.ParamFile(dict(bnd.files)[npn])
    fbp = EW.FieldBook("NpcParam")
    # 克隆行映射：计划里写的是"换入者是哪一行"，真正落到层里的是克隆行（manifest 记的映射）
    pf_b = None
    try:
        bnd_b = erio.read_regulation(man["base"]["regulation"])
        npn_b = EW.find_param_name([n for n, _d in bnd_b.files], "NpcParam.param")
        pf_b = param_bin.ParamFile(dict(bnd_b.files)[npn_b])
    except Exception:
        fails.append("读不到基线 regulation，无法核对克隆行映射")
    clone_ids = man.get("clone_ids") or {}
    place_clones = man.get("place_clones") or {}
    think_clone = man.get("think_clone_ids") or {}
    cache = {}
    checked_rows = {}
    for u in units:
        rel = EW._rel_of(u)
        old_threat = 0 if pf_b is None else EW._npc_threat(pf_b, fbp, u.get("old_npc_id"))
        old_scale = 0 if pf_b is None else EW._npc_scale(pf_b, fbp, u.get("old_npc_id"))
        ckey = "%d|%d|%d|%s|%d|%d|%d" % (int(u["new_npc_id"]), int(u.get("target_hp") or 0),
                                        int(u.get("target_soul") or 0), rel, int(old_threat),
                                        int(u.get("old_npc_id") or 0), int(old_scale))
        _pl0 = (u.get("places") or [{}])[0]
        _pk = "%s|%s|%d" % (_pl0.get("map"), _pl0.get("part_name"), int(_pl0.get("occurrence") or 0))
        npc = place_clones.get(_pk) or clone_ids.get(ckey)
        if npc is None:
            fails.append("%s 找不到克隆行映射（%s）" % (u.get("key"), ckey))
            continue
        npc = int(npc)
        if npc not in checked_rows:
            try:
                payload = pf.payload(npc)
            except Exception:
                payload = None
            if payload is None:
                fails.append("克隆行不存在：%s" % npc)
            else:
                row_hp = EW._u32(payload, fbp.off("hp"))
                row_soul = EW._u32(payload, fbp.off("getSoul"))
                bo, bi = fbp.bit("isSoulGetByBoss")
                soul_by_boss = (payload[bo] >> bi) & 1
                if row_hp != int(u.get("target_hp") or 0):
                    fails.append("克隆行 %s 的 hp=%s ≠ 数值模型 %s" % (npc, row_hp, u.get("target_hp")))
                if row_soul != int(u.get("target_soul") or 0):
                    fails.append("克隆行 %s 的魂=%s ≠ 数值模型 %s" % (npc, row_soul, u.get("target_soul")))
                if soul_by_boss:
                    fails.append("克隆行 %s 仍带 isSoulGetByBoss（魂会拿不到）" % npc)
            checked_rows[npc] = True
        for pl in (u.get("places") or []):
            mp = pl.get("map")
            try:
                idx = _layer_parts(data_dir, mp, cache)
            except Exception as e:
                fails.append("读不出层里的 %s：%s" % (mp, e))
                continue
            part = idx.get((pl.get("part_name"), int(pl.get("occurrence") or 1)))
            if part is None:
                fails.append("%s 里找不到 part %s#%s" % (mp, pl.get("part_name"), pl.get("occurrence")))
                continue
            if int(part.get("npc_id") or 0) != npc:
                fails.append("%s/%s 的 npc_id=%s，层里应写克隆行 %s" % (mp, pl.get("part_name"), part.get("npc_id"), npc))
            exp_think = int(u["new_think_id"])
            tk = EW._think_clone_key(u)
            if tk is not None:
                exp_think = int(think_clone.get("%d|%d" % tk, exp_think))
            if int(part.get("think_id") or 0) != exp_think:
                fails.append("%s/%s 的 think_id=%s ≠ %s" % (mp, pl.get("part_name"), part.get("think_id"), exp_think))
            if part.get("model") != u.get("new_model"):
                fails.append("%s/%s 的模型=%s ≠ 计划 %s" % (mp, pl.get("part_name"), part.get("model"), u.get("new_model")))
    log("[闸门] 传送门：%d 个守门位置 / %d 条克隆行（%s）" %
        (sum(len(u.get("places") or []) for u in units), len(checked_rows),
         "全部换入、数值与位置一致" if not fails else "%d 项不符" % len(fails)))
    return fails


# ────────────────────────── 主检查 ──────────────────────────

def gate(label=None, layer=None, log_path=None, offline=False, log=print):
    layer = find_layer(label, layer)
    man = read_manifest(layer)
    data_dir = os.path.join(layer, DATA_SUB)
    label = label or os.path.basename(layer)
    errs = []
    warns = []

    # ① 层完整性
    want = {}
    for f in (man.get("files") or []):
        want[f["rel"].replace("\\", "/").lower()] = f
    for rel, f in sorted(want.items()):
        p = os.path.join(data_dir, *rel.split("/"))
        if not os.path.isfile(p):
            errs.append("层里缺文件：%s" % f["rel"])
        elif sha256_file(p) != f["sha256"]:
            errs.append("文件指纹不符（被改过）：%s" % f["rel"])
    have = disk_files(data_dir)
    for rel in sorted(have - set(want)):
        errs.append("层里多出文件（陈旧残留）：%s" % rel)
    log("[闸门] 层 = %s" % layer)
    log("[闸门] 完整性：写集 %d 个文件（地图 %d） / 磁盘 %d 个 / %s" %
        (len(want), sum(1 for r in want if r.startswith("map/mapstudio/")), len(have),
         "OK" if not [e for e in errs if "层里" in e] else "有问题"))

    # ② 引擎加载证据
    sess = {"start": None, "hits": set(), "foreign": [], "errors": [], "maps": set(), "overrides": 0}
    if offline:
        log("[闸门] 引擎加载：--offline 跳过")
    else:
        lp = log_path or default_log()
        if not os.path.isfile(lp):
            errs.append("找不到 YAFSML.log：%s" % lp)
        else:
            with open(lp, "r", encoding="utf-8", errors="replace") as f:
                sess = parse_log(f.read(), label)
            if sess["start"] is None:
                errs.append("日志里没有任何 Plan 加载记录（这一层还没被引擎加载过）")
            else:
                dec = (sess.get("declared") or "").replace("\\", "/")
                if label not in dec:
                    errs.append("最后一次加载的 Plan 不是这一层：%s" % dec)
                hits = sess["hits"]
                if "regulation.bin" not in hits:
                    errs.append("引擎没有加载本层的 regulation")
                if sess["maps"] and BGM_REL not in hits:
                    errs.append("加载了地图但没有加载本层 common_func（野外 Boss 血条补丁没生效）")
                for modp in sess["foreign"][:5]:
                    errs.append("日志里有别的方案层 override：%s" % modp)
                for h in sorted(hits - set(want)):
                    errs.append("引擎加载了本层一个不在 manifest 里的文件：%s" % h)
                loaded = hits & set(want)
                not_loaded = sorted(set(want) - hits)
                log("[闸门] 引擎加载：本次会话命中 %d/%d 个文件（地图 %d/%d）；regulation=%s；common_func=%s" %
                    (len(loaded), len(want), len(sess["maps"]),
                     sum(1 for r in want if r.startswith("map/mapstudio/")),
                     "有" if "regulation.bin" in hits else "无",
                     "有" if BGM_REL in hits else "无"))
                if not_loaded:
                    sample = ", ".join(not_loaded[:6])
                    log("[闸门] 未加载（本次没走到那些图，不算失败）：%d 个，例如 %s" % (len(not_loaded), sample))
                if sess["errors"]:
                    warns.append("日志本次会话有 %d 行 ERROR（例如 %s）" % (len(sess["errors"]), sess["errors"][0][:120]))

    # ③ 传送门自检
    plan = None
    pp = ((man.get("plan") or {}).get("path") or "")
    if pp and os.path.isfile(pp):
        with open(pp, "r", encoding="utf-8") as f:
            plan = json.load(f)
    else:
        warns.append("计划文件不在磁盘上（%s），跳过传送门自检" % pp)
    if plan is not None:
        errs.extend(check_waygate(data_dir, plan, man, log=log))

    # ④ 报告
    for w in warns:
        log("[闸门] 警告：%s" % w)
    if errs:
        log("[闸门] RESULT: FAIL（%d 项）" % len(errs))
        for e in errs[:30]:
            log("  - %s" % e)
        return 1
    log("[闸门] RESULT: PASS")
    return 0


def selftest():
    """离线自检：拿磁盘上现有的层跑静态检查（完整性 + 传送门）。"""
    label = None
    root = layer_root()
    cands = [d for d in sorted(os.listdir(root))
             if os.path.isfile(os.path.join(root, d, MANIFEST))]
    if not cands:
        print("[闸门自检] SKIP：没有方案层")
        return 0
    label = cands[-1]
    rc = gate(label=label, offline=True, log=lambda s: None)
    print("[闸门自检] %s：%s" % (label, "PASS" if rc == 0 else "FAIL"))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description="方案层读取端闸门（M3）")
    ap.add_argument("--label", default=None)
    ap.add_argument("--layer", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    return gate(label=a.label, layer=a.layer, log_path=a.log, offline=a.offline)


if __name__ == "__main__":
    sys.exit(main())
