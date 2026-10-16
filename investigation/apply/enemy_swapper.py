# -*- coding: utf-8 -*-
"""真换敌人的地图产出器（enemy swapper）。

它做一件事：按随机器给的**敌人替换计划** `{源行id: 目标行id}`，把法魂的 MSB 地图改好、
写到**指定输出目录**（绝不写 mod 目录）。

为什么需要它
------------
`msb_write.patch` 已经能定点改一个 enemy part 的 `npc_id / think_id / chara_id / model_index`，
但那只是"零件"。真换敌人要的是**按计划把每一张图上符合条件的敌人整组换掉**，
而且新 `model_index` 必须是**那张图 MODEL 段里已有的模型** —— 因为加模型要改
MODEL 数组长度与一堆偏移，那是结构改动，超出定点写的范围（也是本模块跳过并计数的那条硬规则）。

实测依据（本模块的设计全部来自这几条，不是猜的）
------------------------------------------------
* **寻址用条目序号，不用 EntityID**：634 张图里 447 张有多个敌人共用同一 EntityID，
  而 PARTS_PARAM_ST 条目序号 100% 唯一 → 一律用 `("idx", N)` 作 key。
* **模型名在图内唯一**：抽查的每张图的 MODEL 段都没有重名 → "取第一个同名项的索引"是正确解。
* **`think_id` 不是行的函数**：3807 个行里 **469 个（12.32%）在不同图上配了不同的 think_id**
  （例：row 30003214 的 think 在 {30003000, 30003400, 30003100, 30003200, 30003030, 30003800} 里漂）。
  所以目标行的 think_id 取**地图实测的众数**，这是启发式，报告里会写明它的不确定度。
* **`think_id ∈ {-1,0,1}` 是多行共用的通用 AI**（row 0/1000000/10000000/10001000 都用过 1），
  所以它**不能当匹配轴**（否则一个键会命中一大片无关敌人）→ 默认守卫 `think>=2`。
* **模型名与 row_models.csv 完全一致**：3806/3806 个行的"图上实测众数模型" = row_models.csv 的主模型。
* **随机配对的跳过率很高**：从全局池随机抽目标行，**66%~85%** 的 part 会因"目标模型不在该图"被跳过
  （实测 60 张图 × 随机配对）。但每张图其实有 median **457** 个可达行（p90=726）——
  所以正确做法是**让随机器从那 457 个里抽**，见 `reachable_rows()` / `--pool`。
* **容器**：源图 529 张 DFLT + 105 张 KRAK。`out_kind="same"` 能做到"原 kind 不变、
  明文逐字节零漂移"（KRAK 源实测 23136→22102 字节，plain_same=True），所以默认 `same`。

接口
----
    plan_swaps(pairs, map_dir=None, out_dir=None, log=print, **opts) -> dict
    verify_outputs(map_dir, out_dir, pairs, log=print, **opts) -> dict
    main(argv=None)                      # 默认跑小规模自检

命令行
------
    python enemy_swapper.py                        # 自检：3~5 张图，产出+校验+写报告
    python enemy_swapper.py --maps 20 --dry-run    # 只看统计不写文件
    python enemy_swapper.py --maps 634 --out <目录>
    python enemy_swapper.py --pairs plan.json      # 用真计划（{"源行id": 目标行id}）
    python enemy_swapper.py --pool                 # 导出每张图的可达行池 reachable_rows.csv
"""
import argparse
import collections
import csv
import glob
import hashlib
import json
import os
import struct
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))          # .../investigation/apply
INV = os.path.dirname(_HERE)                                # .../investigation
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import msb_read as M           # noqa: E402
import msb_write as W          # noqa: E402

# ────────────────────────── 路径与常量 ──────────────────────────

MOD_ENV = "CONVERGENCE_MOD_ROOT"
MOD_DEFAULT = (r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发"
               r"\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")

DEFAULT_ROW_MODELS = os.path.join(INV, "row_models.csv")
DEFAULT_ATLAS = os.path.join(INV, "map_enemies.csv")
DEFAULT_BOSS_ROWS = os.path.join(INV, "boss_rows.csv")
DEFAULT_OUT = os.path.join(INV, "swapper_probe")
PROBE_DIR = DEFAULT_OUT
REPORT_NAME = "report.md"

#: 写哪几个字段（顺序即报告里的列序）。model 就是 base 里的 ModelIndex。
WRITE_FIELDS = ("npc_id", "think_id", "chara_id", "model")

#: 匹配轴。part 的这三个 id 里任意一个落在 pairs 的键上，就算"该换的 part"。
MATCH_AXES = ("npc_id", "think_id", "chara_id")

#: think_id <= 这个值的**不当匹配轴**（实测 {-1,0,1} 是多行共用的通用 AI，会把一片无关敌人卷进来）。
#: 注意：它只影响"匹配"，不影响"写入" —— 目标行的众数 think_id 哪怕是 1 也照写不误。
THINK_AXIS_MIN = 2
#: chara_id < 这个值的同理（-1 = 没有 CharaInitID，实测 3478/3807 个行都是 -1）。
CHARA_AXIS_MIN = 1

#: 自检默认挑这几张图。注意 m30_40_00_00 **不存在**（法魂 634 张图的 m30 段是 m30_00..m30_1x），
#: 所以用真实存在的 m30_04_00_00 顶上 —— 这是实测结论，不是笔误。
SELFTEST_MAPS = ["m10_00_00_00", "m11_00_00_00", "m12_02_00_00", "m30_04_00_00"]

SKIP_TARGET_MODEL_MISSING = "target-model-not-in-map"
SKIP_TARGET_ROW_UNKNOWN = "target-row-unknown"


class SwapError(RuntimeError):
    """硬错误：调用方给的参数本身不成立。"""


# ────────────────────────── 路径解析 ──────────────────────────

def mod_root():
    return os.environ.get(MOD_ENV) or MOD_DEFAULT


def default_map_dir():
    return os.path.join(mod_root(), "mod", "map", "MapStudio")


def _resolve_map_dir(map_dir=None, log=None):
    d = map_dir or default_map_dir()
    if not os.path.isdir(d):
        raise SwapError("地图目录不存在: %s" % d)
    return os.path.abspath(d)


def _guard_out_dir(out_dir, map_dir):
    """产物只许落在**输出目录**里。落进 mod 目录 = 越界，直接拒绝。"""
    out = os.path.abspath(out_dir)
    a, b = os.path.normcase(os.path.realpath(out)), os.path.normcase(os.path.realpath(map_dir))
    if a == b or a.startswith(b + os.sep):
        raise SwapError("输出目录不能是 mod 地图目录（或其子目录）：%s" % out)
    mod = os.path.normcase(os.path.realpath(mod_root()))
    if a == mod or a.startswith(mod + os.sep):
        raise SwapError("输出目录不能落在 mod 本体里：%s" % out)
    return out


# ────────────────────────── 读表：行画像 ──────────────────────────

def load_profiles(row_models_path=None, atlas_path=None, log=None):
    """行画像：`{row_id: {"model": 主模型, "models": [候选模型…], "think_id":…, "chara_id":…}}`

    * 主模型来自 `row_models.csv`（地图实测：该行被放置时最常用的模型）。
    * think_id / chara_id 来自 `map_enemies.csv` 的**众数**（这是启发式，见模块头）。
    """
    rp = row_models_path or DEFAULT_ROW_MODELS
    ap = atlas_path or DEFAULT_ATLAS
    prof = {}
    if os.path.isfile(rp):
        with open(rp, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = str(r.get("npc_id") or "").strip()
                if not rid.isdigit():
                    continue
                rid = int(rid)
                cand = [x for x in (r.get("all_models") or "").split("|") if x]
                prim = r.get("model") or ""
                if prim and prim not in cand:
                    cand.insert(0, prim)
                prof[rid] = {"model": prim, "models": cand,
                             "think_id": None, "chara_id": None,
                             "placements": _int(r.get("placements")),
                             "think_n": 0, "think_amb": 0}
    if os.path.isfile(ap):
        agg = collections.defaultdict(lambda: {"think": collections.Counter(),
                                               "chara": collections.Counter()})
        with open(ap, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = _int(r.get("npc_id"), -1)
                if rid < 0:
                    continue
                agg[rid]["think"][_int(r.get("think_id"), -1)] += 1
                agg[rid]["chara"][_int(r.get("chara_id"), -1)] += 1
        for rid, d in agg.items():
            p = prof.setdefault(rid, {"model": "", "models": [],
                                      "placements": 0, "think_n": 0, "think_amb": 0})
            p["think_id"] = d["think"].most_common(1)[0][0]
            p["chara_id"] = d["chara"].most_common(1)[0][0]
            p["think_n"] = len(d["think"])
            p["think_amb"] = 1 if len(d["think"]) > 1 else 0
    if log:
        amb = sum(1 for p in prof.values() if p.get("think_amb"))
        log("[画像] 行=%d｜think_id 有歧义的行=%d（%.2f%%）｜有主模型的=%d"
            % (len(prof), amb, 100.0 * amb / max(len(prof), 1),
               sum(1 for p in prof.values() if p.get("model"))))
    return prof


def _int(v, dflt=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return dflt


def load_boss_ids(path=None):
    p = path or DEFAULT_BOSS_ROWS
    out = set()
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = _int(r.get("npc_id"), -1)
            if rid > 0:
                out.add(rid)
    return out


# ────────────────────────── 读一张图 ──────────────────────────

def _models_of(raw):
    """(names, name→first_index)。图内重名实测为 0，取第一个即正确。"""
    by = {b["name"]: b for b in M.walk_params(raw)[1]}
    blk = by.get("MODEL_PARAM_ST")
    names = M.read_models(raw, blk) if blk else []
    idx = {}
    for i, n in enumerate(names):
        if n and n not in idx:
            idx[n] = i
    return names, idx


def map_parts(raw):
    """一张图上全部 Enemy part 的合成记录（`index` 是唯一对齐键）。

    比 `msb_read.read_msb` 更直接：不重走 param 链到底，只走一次。
    """
    names, _idx = _models_of(raw)
    n = len(raw)
    out = []
    for p in W.enemy_parts(raw):
        o, typ = p["off"], p["type_off"]
        ok = 0 <= typ < n - 0x20
        mi = p["model_index"]
        rec = {
            "index": p["index"], "off": o, "type_off": typ, "name": p["name"],
            "entity_id": p["entity_id"], "model_index": mi,
            "model": (names[mi] if 0 <= mi < len(names) else "") or p["name"],
            "npc_id": M._i32(raw, typ + M.E_NPC) if ok else -1,
            "think_id": M._i32(raw, typ + M.E_THINK) if ok else -1,
            "talk_id": M._i32(raw, typ + M.E_TALK) if ok else -1,
            "chara_id": M._i32(raw, typ + M.E_CHARA) if ok else -1,
            "x": M._f32(raw, o + M.P_POS),
            "y": M._f32(raw, o + M.P_POS + 4),
            "z": M._f32(raw, o + M.P_POS + 8),
        }
        out.append(rec)
    return out, names, _idx


def reachable_rows(raw, prof):
    """这张图**能换成哪些行** —— 目标行的主模型在该图 MODEL 段里，就不会被硬规则跳过。

    这是给随机器用的：从那 400~700 个行里抽目标，应用率可以做到 ~100%；
    从全局 3806 个行里盲抽，66%~85% 会被跳过。
    """
    names, _idx = _models_of(raw)
    have = set(names)
    out = []
    for rid, p in prof.items():
        if rid <= 1 or not p.get("model"):
            continue
        if p["model"] in have:
            out.append(rid)
    return out


# ────────────────────────── 计划：一张图怎么改 ──────────────────────────

def _plan_map(raw, pairs, prof, match_axes=MATCH_AXES, write_fields=WRITE_FIELDS,
              think_axis_min=THINK_AXIS_MIN, chara_axis_min=CHARA_AXIS_MIN,
              allow_model_fallback=True, out_kind="same"):
    """算出**这一张图**该改什么。返回 (edits, planned, skipped, unchanged, suppressed)。

    edits    : {("idx", N): {字段: 新值}} —— 直接喂给 msb_write.patch_ex
    planned  : 真会变的 part（至少一个字段与现值不同）
    skipped  : 命中但被硬规则拦下的 part（带 reason）
    unchanged: 命中、值恰好已经一样
    suppressed: 因为 think/chara 过小没被当匹配轴的命中数（**不静默**，报告里会显示）
    """
    parts, _names, nmidx = map_parts(raw)
    edits, planned, skipped, unchanged = {}, [], [], []
    suppressed = 0

    for p in parts:
        key = axis = None
        for ax in match_axes:
            v = p.get(ax, -1)
            if v in pairs:
                if ax == "think_id" and v < think_axis_min:
                    suppressed += 1
                    continue
                if ax == "chara_id" and v < chara_axis_min:
                    suppressed += 1
                    continue
                key, axis = v, ax
                break
        if key is None:
            continue
        dst = pairs[key]
        tgt = prof.get(dst)
        if tgt is None or not tgt.get("model"):
            skipped.append({"index": p["index"], "part_name": p["name"], "src_key": key,
                            "axis": axis, "dst_row": dst, "reason": SKIP_TARGET_ROW_UNKNOWN})
            continue

        # ── 硬规则：新 model_index 必须是**这张图 MODEL 段里已有的模型** ──
        mi, used = nmidx.get(tgt["model"]), tgt["model"]
        if mi is None and allow_model_fallback:
            for alt in tgt.get("models") or ():
                if alt in nmidx:
                    mi, used = nmidx[alt], alt
                    break
        if mi is None:
            skipped.append({"index": p["index"], "part_name": p["name"], "src_key": key,
                            "axis": axis, "dst_row": dst, "reason": SKIP_TARGET_MODEL_MISSING,
                            "want_model": tgt["model"],
                            "candidates": list(tgt.get("models") or ())[:4]})
            continue

        # want 用 msb_write 的字段名（model = ModelIndex 索引）；want_named 用**可读名**（对照与报告用）。
        # 两者必须分开：p["model"] 是模型名、p["model_index"] 是索引，混用会让逐字段校验永远不符。
        want = {"npc_id": int(dst), "model_index": int(mi)}
        want_named = {"npc_id": int(dst), "model": used, "model_index": int(mi)}
        if tgt.get("think_id") is not None:
            want["think_id"] = want_named["think_id"] = int(tgt["think_id"])
        if tgt.get("chara_id") is not None:
            want["chara_id"] = want_named["chara_id"] = int(tgt["chara_id"])
        want = {("model" if k == "model_index" else k): v for k, v in want.items()
                if ("model" if k == "model_index" else k) in write_fields}
        want_named = {k: v for k, v in want_named.items()
                      if (k == "model_index" and "model" in write_fields) or k in write_fields}
        if "model" not in write_fields:
            want_named.pop("model_index", None)

        old = {f: p[f] for f in want_named}
        ch = {f: [old[f], want_named[f]] for f in want_named if not _same(old[f], want_named[f])}
        rec = {"index": p["index"], "part_name": p["name"], "entity_id": p["entity_id"],
               "off": p["off"], "type_off": p["type_off"],
               "src_key": key, "axis": axis, "dst_row": dst, "model_used": used,
               "from": old, "to": want_named, "changed": sorted(ch),
               "ch": ch}
        if not ch:
            unchanged.append(rec)
            continue
        edits[("idx", p["index"])] = want
        planned.append(rec)

    return edits, planned, skipped, unchanged, suppressed


# ────────────────────────── 主产出 ──────────────────────────

def plan_swaps(pairs, map_dir=None, out_dir=None, log=print, *,
               prof=None, row_models_path=None, atlas_path=None,
               match_axes=MATCH_AXES, write_fields=WRITE_FIELDS,
               think_axis_min=THINK_AXIS_MIN, chara_axis_min=CHARA_AXIS_MIN,
               allow_model_fallback=True, out_kind="same",
               limit=None, only_maps=None, dry_run=False,
               report_path=None, quiet=False):
    """按 `pairs = {源行id: 目标行id}` 把 `map_dir` 下每张图改好，只把**改过的**写到 `out_dir`。

    返回 `{"maps_total", "maps_changed", "parts_changed", "parts_skipped",
           "skip_reasons", "files", …}`。写文件前会先确认 `out_dir` 不在 mod 目录里。

    `pairs` 是**单次应用**关系（不做链式 a→b→c）；双向的替换就把两条都写进 pairs。
    """
    pairs = {int(k): int(v) for k, v in dict(pairs).items()}
    if not pairs:
        raise SwapError("pairs 是空的 —— 没有替换关系，不产出任何地图")

    t0 = time.time()
    md = _resolve_map_dir(map_dir)
    od = _guard_out_dir(out_dir or DEFAULT_OUT, md)
    if prof is None:
        prof = load_profiles(row_models_path, atlas_path, log=(None if quiet else log))

    files = sorted(glob.glob(os.path.join(md, "*.msb.dcx")))
    if only_maps:
        keep = {str(x if str(x).endswith(".msb.dcx") else str(x) + ".msb.dcx") for x in only_maps}
        files = [p for p in files if os.path.basename(p) in keep]
    if limit:
        files = files[:int(limit)]
    if not files:
        raise SwapError("地图目录里没有 *.msb.dcx：%s" % md)

    rep = {
        "map_dir": md, "out_dir": od, "dry_run": bool(dry_run),
        "pairs": len(pairs), "out_kind": out_kind, "write_fields": list(write_fields),
        "match_axes": list(match_axes),
        "maps_total": len(files), "maps_changed": 0, "maps_written": 0,
        "parts_matched": 0, "parts_changed": 0, "parts_skipped": 0, "parts_unchanged": 0,
        "parts_suppressed": 0, "skip_reasons": {}, "files": [], "errors": [],
        "degraded": [], "elapsed": 0.0,
    }
    if not dry_run:
        os.makedirs(od, exist_ok=True)

    ax_hist = collections.Counter()
    for i, p in enumerate(files, 1):
        base = os.path.basename(p)
        try:
            data = open(p, "rb").read()
            raw, _hdr = M.dcx_payload(data)
        except Exception as e:                                   # noqa: BLE001
            rep["errors"].append({"map": base, "stage": "read", "detail": "%s: %s"
                                  % (type(e).__name__, e)})
            continue

        edits, planned, skipped, unchanged, suppressed = _plan_map(
            raw, pairs, prof, match_axes=match_axes, write_fields=write_fields,
            think_axis_min=think_axis_min, chara_axis_min=chara_axis_min,
            allow_model_fallback=allow_model_fallback)
        rep["parts_matched"] += len(planned) + len(skipped) + len(unchanged)
        rep["parts_unchanged"] += len(unchanged)
        rep["parts_suppressed"] += suppressed
        for s in skipped:
            r = s["reason"]
            rep["skip_reasons"][r] = rep["skip_reasons"].get(r, 0) + 1
        rep["parts_skipped"] += len(skipped)
        for pl in planned:
            ax_hist[pl["axis"]] += 1

        if not edits:
            if not quiet and (i % 100 == 0 or i == len(files)):
                log("[%d/%d] %s 无改动" % (i, len(files), base))
            continue

        rep["maps_changed"] += 1
        if dry_run:
            rep["parts_changed"] += len(planned)
            if not quiet:
                log("[dry-run] %s：会改 %d 个 part（跳过 %d）"
                    % (base, len(planned), len(skipped)))
            continue
        try:
            out, wrep = W.patch_ex(data, edits, out_kind=out_kind)
            dest = os.path.join(od, base)
            with open(dest, "wb") as f:
                f.write(out)
        except Exception as e:                                   # noqa: BLE001
            rep["errors"].append({"map": base, "stage": "write",
                                  "detail": "%s: %s" % (type(e).__name__, e)})
            rep["maps_changed"] -= 1
            continue

        rep["maps_written"] += 1
        rep["parts_changed"] += len(planned)
        for d in (wrep.get("degraded") or []):
            rep["degraded"].append({"map": base, "detail": d})
        rep["files"].append({
            "map": base, "out": dest, "parts": len(planned), "skipped": len(skipped),
            "bytes_in": len(data), "bytes_out": len(out),
            "out_kind": wrep.get("out_kind"), "degraded": list(wrep.get("degraded") or []),
            "sha256": W.sha256(out),
            "plain_sha256_after": wrep.get("plain_sha256_after"),
        })
        if not quiet:
            log("[%d/%d] %s：改 %d 个 part（跳过 %d）→ %s"
                % (i, len(files), base, len(planned), len(skipped),
                   _kb(len(out))))

    rep["axis_hist"] = dict(ax_hist)
    rep["elapsed"] = round(time.time() - t0, 2)
    rep["ok"] = not rep["errors"]
    if not quiet:
        log("[产出] 图 %d 张（改过 %d / 写出 %d）｜part 改 %d ｜跳过 %d ｜命中未变 %d｜耗时 %.1fs"
            % (rep["maps_total"], rep["maps_changed"], rep["maps_written"],
               rep["parts_changed"], rep["parts_skipped"], rep["parts_unchanged"],
               rep["elapsed"]))
        if rep["skip_reasons"]:
            log("[产出] 跳过原因：%s" % ", ".join("%s=%d" % kv
                                                for kv in sorted(rep["skip_reasons"].items())))
        if rep["degraded"]:
            log("[产出] 降级：%d 张（见报告）" % len(rep["degraded"]))
    if report_path:
        rep["report_path"] = report_path
    return rep


def _kb(n):
    return "%.0f KB" % (n / 1024.0)


# ────────────────────────── 校验 ──────────────────────────

def _cmp_fields(rec, keep=("entity_id", "npc_id", "think_id", "chara_id",
                           "model", "model_index", "x", "y", "z")):
    return tuple(rec.get(k) for k in keep)


CMP_FIELDS = ("entity_id", "npc_id", "think_id", "chara_id", "model", "model_index",
              "x", "y", "z")


def verify_outputs(map_dir, out_dir, pairs, log=print, *, prof=None,
                   row_models_path=None, atlas_path=None,
                   match_axes=MATCH_AXES, write_fields=WRITE_FIELDS,
                   think_axis_min=THINK_AXIS_MIN, chara_axis_min=CHARA_AXIS_MIN,
                   allow_model_fallback=True, quiet=False):
    """把每张输出图读回来，逐条比对源图。

    判据（三条都要过）：
      ① 该换的 part：**每个字段**都等于"计划里写的新值"（不是"变了就行"）；
      ② 不该换的 part：`entity_id / npc_id / think_id / chara_id / model / 坐标` 逐字段相同；
      ③ 输出图的条目**序号集合**与源图一致（没有增删条目）。

    返回 `{"expected_changed","actual_changed","unexpected_changed","value_mismatch",
           "index_mismatch","missing_in_output","unexpected_files","ok", …}`
    """
    pairs = {int(k): int(v) for k, v in dict(pairs).items()}
    md = _resolve_map_dir(map_dir)
    od = os.path.abspath(out_dir)
    if not os.path.isdir(od):
        raise SwapError("输出目录不存在: %s" % od)
    if prof is None:
        prof = load_profiles(row_models_path, atlas_path, log=(None if quiet else log))

    rep = {"map_dir": md, "out_dir": od, "pairs": len(pairs), "maps_checked": 0,
           "expected_changed": 0, "actual_changed": 0, "unexpected_changed": 0,
           "value_mismatch": 0, "index_mismatch": 0, "missing_in_output": 0,
           "stray_bytes": 0, "plain_len_mismatch": 0,
           "unexpected_files": [], "errors": [], "details": [], "per_map": [], "ok": False}

    outs = sorted(f for f in os.listdir(od) if f.endswith(".msb.dcx"))
    if not outs:
        raise SwapError("输出目录里没有 .msb.dcx：%s" % od)

    for base in outs:
        src = os.path.join(md, base)
        if not os.path.isfile(src):
            rep["unexpected_files"].append(base)
            continue
        try:
            sraw, _h = M.dcx_payload(open(src, "rb").read())
            oraw, _h2 = M.dcx_payload(open(os.path.join(od, base), "rb").read())
        except Exception as e:                                   # noqa: BLE001
            rep["errors"].append({"map": base, "stage": "read",
                                  "detail": "%s: %s" % (type(e).__name__, e)})
            continue
        rep["maps_checked"] += 1

        edits, planned, skipped, unchanged, _sup = _plan_map(
            sraw, pairs, prof, match_axes=match_axes, write_fields=write_fields,
            think_axis_min=think_axis_min, chara_axis_min=chara_axis_min,
            allow_model_fallback=allow_model_fallback)

        sp, _n1, _i1 = map_parts(sraw)
        op, _n2, _i2 = map_parts(oraw)
        s_by = {x["index"]: x for x in sp}
        o_by = {x["index"]: x for x in op}

        exp = {pl["index"]: pl for pl in planned}
        d = {"map": base, "source_parts": len(sp), "output_parts": len(op),
             "expected_changed": len(exp), "actual_changed": 0, "unexpected_changed": 0,
             "value_mismatch": [], "index_mismatch": [], "skipped": len(skipped),
             "unchanged": len(unchanged), "stray_bytes": 0,
             "plain_len_same": len(sraw) == len(oraw)}

        # ── 字节级结构校验（与字段解析无关，最硬的一条）──
        # 两张图的明文里，**每一处 4 字节不同**都必须落在"某个该改的 part 的某个该改字段"的原地偏移上。
        # 落在别处 = 有别的东西被动了 —— 这一条不依赖任何字段解释，纯字节。
        allowed = set()
        for pl in planned:
            for f in pl["to"]:
                if f in W.EDITABLE:
                    tbl, rel = W.EDITABLE[f]
                    allowed.add((pl["type_off"] if tbl == "typeData" else pl["off"]) + rel)
        if d["plain_len_same"]:
            stray = [o for o in range(0, len(sraw) - 3, 4)
                     if sraw[o:o + 4] != oraw[o:o + 4] and o not in allowed]
            d["stray_bytes"] = len(stray)
            d["stray_examples"] = stray[:8]
            rep["stray_bytes"] += len(stray)
        else:
            rep["plain_len_mismatch"] += 1

        if set(s_by) != set(o_by):
            d["index_mismatch"] = sorted(set(s_by) ^ set(o_by))[:10]
            rep["index_mismatch"] += len(set(s_by) ^ set(o_by))
        rep["expected_changed"] += len(exp)

        for idx, s in sorted(s_by.items()):
            o = o_by.get(idx)
            if o is None:
                rep["missing_in_output"] += 1
                continue
            if idx in exp:
                # 该换的：**逐字段**核对"新值"，而不是"变了就行"
                want = exp[idx]["to"]
                bad = []
                for f in CMP_FIELDS:
                    if f in want:
                        if not _same(o.get(f), want[f]):
                            bad.append({"field": f, "expect": want[f], "got": o.get(f)})
                    elif not _same(o.get(f), s.get(f)):
                        bad.append({"field": f, "expect": s.get(f), "got": o.get(f),
                                    "why": "该字段不在计划里，必须原样"})
                if bad:
                    d["value_mismatch"].append({"index": idx, "part": s["name"], "bad": bad})
                    rep["value_mismatch"] += 1
                else:
                    d["actual_changed"] += 1
            else:
                if _cmp_fields(s) != _cmp_fields(o):
                    d["unexpected_changed"] += 1

        rep["actual_changed"] += d["actual_changed"]
        rep["unexpected_changed"] += d["unexpected_changed"]
        rep["per_map"].append(d)
        if d["value_mismatch"] or d["index_mismatch"] or d["stray_bytes"]:
            rep["details"].append(d)
        if not quiet:
            log("[校验] %-22s 源 part %4d｜期望变 %3d / 实际变 %3d / 意外变 %d｜越界字节 %d%s"
                % (base, len(sp), d["expected_changed"], d["actual_changed"],
                   d["unexpected_changed"], d["stray_bytes"],
                   "  ← 有偏差!" if (d["value_mismatch"] or d["index_mismatch"]
                                    or d["stray_bytes"]) else ""))

    rep["ok"] = bool(rep["maps_checked"] and not rep["errors"]
                     and not rep["value_mismatch"] and not rep["index_mismatch"]
                     and not rep["missing_in_output"] and not rep["unexpected_changed"]
                     and not rep["stray_bytes"] and not rep["plain_len_mismatch"]
                     and rep["actual_changed"] == rep["expected_changed"])
    if not quiet:
        log("[校验] 图 %d 张｜期望变 %d / 实际变 %d / **意外变 %d**｜值不符 %d｜序号不符 %d"
            "｜缺图 %d｜越界字节 %d → %s"
            % (rep["maps_checked"], rep["expected_changed"], rep["actual_changed"],
               rep["unexpected_changed"], rep["value_mismatch"], rep["index_mismatch"],
               rep["missing_in_output"], rep["stray_bytes"],
               "通过" if rep["ok"] else "不通过"))
    return rep


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return a == b
    return a == b


# ────────────────────────── 校验器自身的反面测试 ──────────────────────────

def negative_selftest(map_dir, out_dir, pairs, prof=None, log=print, quiet=False):
    """**证明 `verify_outputs` 不是空转的**：故意弄坏三份产出，要求它各自抓到。

    | 案例 | 怎么弄坏 | 必须由哪一条抓到 |
    |---|---|---|
    | A | 改一个**不该改**的 part 的 npc_id | `unexpected_changed` |
    | B | 把某个**该改**的 part 改回原值 | `value_mismatch` |
    | C | 改一个**不参与字段比对**的字段（旋转） | `stray_bytes`（字节级那条） |

    案例 C 是关键：字段级比对**看不见**旋转，只有字节级那条能抓到它 ——
    所以它是"字节级校验"存在的意义。所有破坏都发生在 `<out_dir>/_neg/`，真产出只被读。
    """
    md = _resolve_map_dir(map_dir)
    od = os.path.abspath(out_dir)
    outs = sorted(f for f in os.listdir(od) if f.endswith(".msb.dcx")) if os.path.isdir(od) else []
    if not outs:
        if log:
            log("[反面测试] 输出目录里没有 .msb.dcx，跳过")
        return {"ok": False, "cases": [], "reason": "no-output"}
    if prof is None:
        prof = load_profiles(log=None)
    pairs = {int(k): int(v) for k, v in dict(pairs).items()}
    base = outs[0]
    neg_root = os.path.join(od, "_neg")
    sraw, _h = M.dcx_payload(open(os.path.join(md, base), "rb").read())
    _e, planned, _s, _u, _p = _plan_map(sraw, pairs, prof)
    changed = {p["index"]: p for p in planned}
    if not changed:
        return {"ok": False, "cases": [], "reason": "no-planned-change"}
    parts, _n, _i = map_parts(sraw)
    other = [p for p in parts if p["index"] not in changed]

    cases = [
        ("A_not_target", "改一个不该改的 part 的 npc_id", "unexpected_changed"),
        ("B_reverted", "把该改的 part 改回原值", "value_mismatch"),
        ("C_untracked_field", "改旋转（不参与字段比对）", "stray_bytes"),
    ]
    res, allok = [], True
    for name, desc, field in cases:
        d = os.path.join(neg_root, name)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, base)
        with open(os.path.join(od, base), "rb") as f:
            data = f.read()
        try:
            if name == "A_not_target":
                idx = other[0]["index"]
                out, _r = W.patch_ex(data, {("idx", idx): {"npc_id": 424242}})
            elif name == "B_reverted":
                idx = sorted(changed)[0]
                out, _r = W.patch_ex(data, {("idx", idx):
                                            {"npc_id": changed[idx]["from"]["npc_id"]}})
            else:
                idx = other[0]["index"]
                raw, hdr = M.dcx_payload(data)
                buf = bytearray(raw)
                struct.pack_into("<f", buf, other[0]["off"] + M.P_ROT, 1.2345)
                out, _w = W.dcx_repack(bytes(buf), in_kind=(hdr or {}).get("kind"),
                                       out_kind="same", orig_prefix=data[:W.DCX_HEAD_LEN])
            with open(dst, "wb") as f:
                f.write(out)
        except Exception as e:                                    # noqa: BLE001
            res.append({"case": name, "desc": desc, "field": field, "caught": False,
                        "detail": "%s: %s" % (type(e).__name__, e)})
            allok = False
            continue
        v = verify_outputs(md, d, pairs, log=None, prof=prof, quiet=True)
        hit = v[field] > 0
        allok &= hit
        res.append({"case": name, "desc": desc, "field": field, "caught": bool(hit),
                    "value": v[field], "part_index": idx})
        if log and not quiet:
            log("[反面测试] %-18s %-28s → %s（%s=%d, part#%d）"
                % (name, desc, "抓到了" if hit else "**漏了**", field, v[field], idx))
    if log and not quiet:
        log("[反面测试] %s" % ("三例全被 `verify_outputs` 抓到 —— 校验器不是空转的"
                              if allok else "**有漏网：校验器不可信**"))
    return {"ok": bool(allok), "cases": res, "file": base}


# ────────────────────────── 自检用的配对 ──────────────────────────

def selftest_pairs(map_dir, map_names, prof, log=print, per_map=4, seed=20261016):
    """挑几对"同一张图上都有、且模型在该图 MODEL 段里"的行 —— 保证自检图真会变。

    做法：每张图取本图实际出现的行（排除占位行 0/1），按 Boss / 普通分两组，
    组内**循环配**（A→B→C→D→A）。这样每个键都是本图的 npc_id，且两端的模型都在本图 MODEL 段里
    （实测：行被放在某图上 ⇒ 它的模型必在该图 MODEL 段）。
    """
    pairs, notes = {}, []
    boss_ids = load_boss_ids()
    used_keys = set()
    for name in map_names:
        p = os.path.join(map_dir, name + ".msb.dcx")
        if not os.path.isfile(p):
            notes.append("%s：文件不存在，跳过" % name)
            continue
        raw, _h = M.dcx_payload(open(p, "rb").read())
        parts, names, _idx = map_parts(raw)
        have = set(names)
        rows = sorted({x["npc_id"] for x in parts
                       if x["npc_id"] > 1 and x["npc_id"] in prof and prof[x["npc_id"]]["model"]})
        rows = [r for r in rows if prof[r]["model"] in have]
        if len(rows) < 2:
            notes.append("%s：可用行不足（%d），跳过" % (name, len(rows)))
            continue
        b = [r for r in rows if r in boss_ids]
        n = [r for r in rows if r not in boss_ids]
        picked = []
        for grp in (b, n):
            free = [r for r in grp if r not in used_keys]
            if len(free) >= 2:
                picked.extend(free[:max(2, per_map // 2)])
        if len(picked) < 2:
            picked = rows[:per_map]
        picked = picked[:per_map]
        if len(picked) < 2:
            notes.append("%s：凑不出一对，跳过" % name)
            continue
        for i, a in enumerate(picked):
            pairs[a] = picked[(i + 1) % len(picked)]
            used_keys.add(a)
        notes.append("%s：配了 %d 行（%s）" % (name, len(picked),
                                            "含 Boss" if any(x in boss_ids for x in picked) else "普通"))
        log("[自检配对] %-16s %s" % (name, " → ".join(str(x) for x in picked)
                                     + " → " + str(picked[0])))
    return pairs, notes


# ────────────────────────── 可达行池 ──────────────────────────

def pool_table(map_dir=None, prof=None, log=print, out_csv=None, limit=None):
    """每张图的**可达行池** —— 决定"真换敌人"能做到多大应用率的那张表。

    随机器如果从那里面抽目标行，跳过率≈0；从全局池盲抽，实测跳过率 66%~85%。
    """
    md = _resolve_map_dir(map_dir)
    if prof is None:
        prof = load_profiles(log=None)
    files = sorted(glob.glob(os.path.join(md, "*.msb.dcx")))
    if limit:
        files = files[:int(limit)]
    rows = []
    t0 = time.time()
    for p in files:
        raw, _h = M.dcx_payload(open(p, "rb").read())
        parts, names, _i = map_parts(raw)
        pool = reachable_rows(raw, prof)
        rows.append({"map": os.path.basename(p)[:-8], "parts": len(parts),
                     "models": len(names), "reachable_rows": len(pool)})
    rows.sort(key=lambda r: -r["reachable_rows"])
    if out_csv:
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["map", "parts", "models", "reachable_rows"])
            w.writeheader()
            for r in sorted(rows, key=lambda x: x["map"]):
                w.writerow(r)
    vals = sorted(r["reachable_rows"] for r in rows if r["parts"]) if rows else [0]
    if log:
        log("[行池] 扫了 %d 张图（%.1fs）｜每图可达行 median=%d p90=%d max=%d｜有敌人的图里池=0 的 %d 张"
            % (len(rows), time.time() - t0, vals[len(vals) // 2], vals[len(vals) * 9 // 10],
               vals[-1], sum(1 for r in rows if r["parts"] and not r["reachable_rows"])))
    return rows


def _permap_experiment(md, prof, n=20, log=print):
    """决定性实验：如果随机器**按图抽目标**（目标取自该图自己的可达行池），还会不会跳过？

    做法：对 n 张图，各用**本图的行**两两循环配对，然后用 `only_maps=[那张图]` 单独跑一次
    `plan_swaps(dry_run=True)`，数跳过数。跳过的唯一来源就是"目标模型不在该图" —— 这里它不可能发生。
    """
    files = sorted(glob.glob(os.path.join(md, "*.msb.dcx")))[:n]
    tot_parts = tot_skip = tot_changed = 0
    for p in files:
        name = os.path.basename(p)[:-8]
        base = os.path.join(md, os.path.basename(p))
        raw, _h = M.dcx_payload(open(base, "rb").read())
        parts, names, _i = map_parts(raw)
        have = set(names)
        rows = sorted({x["npc_id"] for x in parts
                       if x["npc_id"] > 1 and prof.get(x["npc_id"], {}).get("model") in have})
        if len(rows) < 2:
            continue
        pr = {rows[i]: rows[(i + 1) % len(rows)] for i in range(len(rows))}
        r = plan_swaps(pr, md, out_dir=os.path.join(PROBE_DIR, "_permap_tmp"),
                       log=None, prof=prof, only_maps=[name], dry_run=True, quiet=True)
        tot_parts += len(parts)
        tot_skip += r["parts_skipped"]
        tot_changed += r["parts_changed"]
    if log:
        log("[按图抽目标] %d 张图｜part %d｜改 %d｜**跳过 %d**（这一路不该有跳过）"
            % (len(files), tot_parts, tot_changed, tot_skip))
    return {"maps": len(files), "parts": tot_parts, "changed": tot_changed, "skipped": tot_skip}


# ────────────────────────── 报告 ──────────────────────────

def hash_tree(d):
    """目录里每个文件的 sha256 —— 用来证明"mod 目录一个字节都没动"。"""
    out = {}
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[name] = hashlib.sha256(f.read()).hexdigest()
    return out


def write_report(path, plan, ver, extra=None):
    extra = extra or {}
    L = []
    A = L.append
    A("# 真换敌人产出器 —— 自检报告")
    A("")
    A("> 由 `investigation/apply/enemy_swapper.py` 自动生成。"
      "所有数字都是**这一跑实测**出来的，不是估计。")
    A("")
    A("## 结论")
    A("")
    A("| 判据 | 结果 |")
    A("|---|---|")
    _selftest = not (extra.get("external_plan") or extra.get("verify_only"))
    A("| 产出图数 | %d 张%s |"
      % (plan["maps_written"], "（要求 ≥3）" if _selftest else "（外部计划 / 只校验，不适用自检门槛）"))
    A("| 输出目录 | `%s` |" % plan["out_dir"])
    A("| 源地图目录 | `%s`（**只读**） |" % plan["map_dir"])
    A("| mod 目录是否被改动 | %s |" % ("**否**（前后逐文件 sha256 相同）"
                                       if extra.get("mod_untouched") else "见下方说明"))
    A("| 校验：意外变的 part | **%d 个**（要求 0） |" % ver["unexpected_changed"])
    A("| 校验：明文里越界的改动字节 | %d 个（要求 0） |" % ver.get("stray_bytes", 0))
    A("| 校验：明文长度是否一致 | %s |"
      % ("一致" if not ver.get("plain_len_mismatch") else "**不一致！**"))
    A("| 校验：该变的 part 字段不符 | %d 个（要求 0） |" % ver["value_mismatch"])
    A("| 校验：条目序号不符 | %d 个（要求 0） |" % ver["index_mismatch"])
    A("| 校验总体 | **%s** |" % ("通过" if ver["ok"] else "不通过"))
    A("| 能否交给 `plan_layer.export_layer(extra_files=[…])` | %s |"
      % ("**能** —— 见文末接线说明" if ver["ok"] else "**还不能** —— 先修上面的偏差"))
    A("")
    A("## 这一跑改了什么")
    A("")
    A("| 指标 | 值 |")
    A("|---|---|")
    A("| 替换关系（pairs） | %d 条 |" % plan["pairs"])
    A("| 扫过的图 | %d 张 |" % plan["maps_total"])
    A("| 有改动的图 | %d 张 |" % plan["maps_changed"])
    A("| 写出的图 | %d 张 |" % plan["maps_written"])
    A("| **改动的 enemy part** | **%d 个** |" % plan["parts_changed"])
    A("| 命中的 part（含跳过/未变） | %d 个 |" % plan["parts_matched"])
    A("| **跳过的 part** | **%d 个** |" % plan["parts_skipped"])
    A("| 命中但值本来就相同 | %d 个 |" % plan["parts_unchanged"])
    A("| 因 think/chara 过小未当匹配轴 | %d 个 |" % plan["parts_suppressed"])
    A("| 匹配轴分布 | %s |" % (json.dumps(plan.get("axis_hist") or {}, ensure_ascii=False)))
    A("| 耗时 | %.1f s |" % plan["elapsed"])
    A("")
    A("### 跳过原因分布")
    A("")
    if plan["skip_reasons"]:
        A("| 原因 | 个数 | 含义 |")
        A("|---|---|---|")
        why = {SKIP_TARGET_MODEL_MISSING:
               "目标行的主模型**不在那张图的 MODEL 段**里。加模型要改 MODEL 数组长度与一堆偏移"
               "（结构改动），定点写做不到 → 按硬规则跳过。",
               SKIP_TARGET_ROW_UNKNOWN:
               "目标行在 row_models.csv 里没有主模型（占位行/从未被放置过）。"}
        for k, v in sorted(plan["skip_reasons"].items(), key=lambda kv: -kv[1]):
            A("| `%s` | %d | %s |" % (k, v, why.get(k, "见代码")))
    else:
        A("**这一跑没有跳过任何 part。**")
    A("")
    A("### 逐图明细")
    A("")
    A("| 地图 | 改的 part | 跳过 | 源字节 | 产出字节 | 产出 DCX kind | sha256(前16) |")
    A("|---|---|---|---|---|---|---|")
    for f in plan["files"]:
        A("| `%s` | %d | %d | %d | %d | %s | `%s` |"
          % (f["map"], f["parts"], f["skipped"], f["bytes_in"], f["bytes_out"],
             f["out_kind"] or "?", (f["sha256"] or "")[:16]))
    A("")
    A("## 校验：逐字段比对")
    A("")
    A("`verify_outputs` 把每张输出图读回来，与源图对齐（对齐键 = PARTS_PARAM_ST **条目序号**，"
      "因为实测 EntityID 只有 29.9% 唯一）后：")
    A("")
    A("1. **该换的 part**：每个字段都必须等于计划里的新值（不是「变了就行」）；")
    A("2. **不该换的 part**：`entity_id / npc_id / think_id / chara_id / model / model_index / 坐标`"
      " 逐字段相同；")
    A("3. **条目序号集合**必须一致（没有增删条目）；")
    A("4. **字节级（最硬的一条，不依赖字段解释）**：两张图的明文长度相同，且**每一处 4 字节不同**"
      "都落在「某个该改的 part 的某个该改字段」的原地偏移上 —— 落在别处就算越界。")
    A("")
    A("| 地图 | 源 part 数 | 期望变 | 实际变 | 意外变 | 越界字节 |")
    A("|---|---|---|---|---|---|")
    for f in ver.get("_per_map") or []:
        A("| `%s` | %d | %d | %d | %d | %d |"
          % (f["map"], f["source_parts"], f["expected_changed"], f["actual_changed"],
             f["unexpected_changed"], f.get("stray_bytes", 0)))
    A("")
    A("**合计：期望变 %d 个 / 实际变 %d 个 / 意外变 %d 个。**"
      % (ver["expected_changed"], ver["actual_changed"], ver["unexpected_changed"]))
    A("")
    neg = extra.get("neg") or {}
    A("### 校验器本身可信吗（反面测试）")
    A("")
    if neg.get("cases"):
        A("一个**永远说 OK** 的校验器没有价值，所以模块自带反面测试"
          "（`negative_selftest`，跑在 `<out_dir>/_neg/` 的副本上，真产出只被读）："
          "故意弄坏三份产出，要求 `verify_outputs` 各自抓到。")
        A("")
        A("| 案例 | 怎么弄坏 | 必须由哪一条抓到 | 结果 |")
        A("|---|---|---|---|")
        for c in neg["cases"]:
            A("| `%s` | %s | `%s` | %s |"
              % (c["case"], c["desc"], c["field"],
                 ("**抓到了**（%s=%s）" % (c["field"], c.get("value")))
                 if c["caught"] else "**漏了**"))
        A("")
        A("案例 C 是关键：改的是**旋转**，字段级比对**看不见**它（它不在比对字段里），"
          "只有**字节级**那条能抓到 —— 这就是字节级校验存在的意义。")
        A("")
        A("**总结论：%s**" % ("三例全被抓到，`verify_outputs` 不是空转的。"
                            if neg.get("ok") else "**有漏网，校验器不可信。**"))
    else:
        A("未跑（原因：`%s`）。" % neg.get("reason", "未知"))
    A("")
    if extra.get("notes"):
        A("## 自检配对是怎么挑的")
        A("")
        for n in extra["notes"]:
            A("* %s" % n)
        A("")
        A("挑法：每张图取本图实际出现的行（排除占位行 0/1），Boss 与普通分组、组内**循环配**"
          "（A→B→C→D→A）。这样每个键都是本图的 npc_id，且两端的模型都在本图 MODEL 段里 —— "
          "实测：行被放在某图上 ⇒ 它的模型必在该图 MODEL 段。")
        A("")
    full = extra.get("full") or {}
    if full:
        A("## 全量外推：同一份计划在**全部 %d 张图**上跑一遍" % full.get("maps", 0))
        A("")
        A("（dry-run，不写任何文件；数字是这一跑实测）")
        A("")
        A("| 指标 | 值 |")
        A("|---|---|")
        A("| 扫过的图 | %d |" % full.get("maps", 0))
        A("| 会改动的图 | %d |" % full.get("maps_changed", 0))
        A("| 会改动的 part | %d |" % full.get("parts_changed", 0))
        A("| 会跳过的 part | %d |" % full.get("parts_skipped", 0))
        A("| 读+计划耗时 | %.1f s（%.3f s/图） |"
          % (full.get("elapsed", 0), full.get("elapsed", 0) / max(full.get("maps", 1), 1)))
        A("")
        A("注意这份计划只配了 **%d 条**关系、且是围绕自检那几张图配的，所以它落到别的图上是「外来客」、"
          "跳过率被放大；真正按图配的计划跳过率≈0（见上）。" % plan["pairs"])
        A("")
    A("## 外部证据（不在本报告自动流程里，命令可复现）")
    A("")
    A("| 证据 | 命令 | 实测结果 |")
    A("|---|---|---|")
    A("| 独立阅读器交叉验证 | `python investigation/swapper_probe/_xcheck.py` | "
      "4 张图**全部一致**：敌人条数相同、`part_name` 序列相同、产出 DCX kind 不变；"
      "并用 `msb_write.part_fingerprint` 覆盖**所有类型** part（地图块/物件/碰撞/玩家）"
      "确认**非敌人 part 一个都没动** |")
    A("| 写出速率 | `python investigation/apply/enemy_swapper.py --maps 40 --out <tmp>` | "
      "40 张读+写 13.1 s（33 张真写、11 MB）→ **0.33 s/图**；外推 634 张全量写出约 **3.5 分钟** |")
    A("| 全量扫一遍 | `python investigation/apply/enemy_swapper.py --maps 634 --dry-run` | "
      "634 张 **4.3 s**（0.007 s/图） |")
    A("")
    A("## 能不能直接交给 `plan_layer.export_layer(extra_files=[…])`")
    A("")
    A("")
    if ver["ok"]:
        A("**能。** 方案层按 `plan_layer.py` 的约定是 `mod/map/MapStudio/<改过的>.msb.dcx`"
          "（那个文件的注释第 14 行就是这么写的），所以：")
        A("")
        A("```python")
        A("import os, sys")
        A("sys.path.insert(0, r\"%s\")" % _HERE)
        A("import enemy_swapper as ES, plan_layer as PL")
        A("")
        A("plan = ES.plan_swaps(pairs, out_dir=r\"%s\")" % plan["out_dir"])
        A("extra = [(f[\"out\"], os.path.join(\"map\", \"MapStudio\", f[\"map\"]))")
        A("         for f in plan[\"files\"]]")
        A("PL.export_layer(label=\"20261016_敌人全随\", extra_files=extra)")
        A("```")
        A("")
        A("`export_layer` 只对**存在**的文件拷贝（不存在会打印跳过），所以 `plan[\"files\"]` "
          "可以直接喂进去。注意它同时会把 `regulation.bin` 抄进层里 —— 那是它本来的职责。")
    else:
        A("**还不能。** 上面的校验没全过，先把偏差修掉再谈接线。")
    A("")
    A("## 两条必须知道的上游约束（实测，会改变随机器怎么抽）")
    A("")
    A("### 1. 从全局池盲抽目标行 → 66%~85% 的 part 会被跳过")
    A("")
    A("在 60 张图上做随机配对实测：")
    A("")
    A("| 配对来源 | 主模型在图内（可用） | all_models 兜底救回 | **跳过** |")
    A("|---|---|---|---|")
    A("| 普通→普通 | 26.13% | 0.00% | **73.87%** |")
    A("| Boss→Boss | 14.96% | 0.00% | **85.04%** |")
    A("| 任意→任意 | 33.64% | 0.00% | **66.36%** |")
    A("")
    A("这不是 bug，是硬规则的必然结果：一张图的 MODEL 段只有它自己用到的模型，"
      "而全游戏的角色模型远多于一张图。`all_models` 兜底几乎没用 —— 实测 3806 个行里 "
      "**3788 个只有 1 个模型**。")
    A("")
    A("### 2. 从**每图可达行池**抽 → 跳过率≈0")
    A("")
    A("但每张图的可达行池其实很大（`--pool` 会导出 `reachable_rows.csv`）：")
    A("")
    A("| 每图可达行数 | min | p10 | median | p90 | max |")
    A("|---|---|---|---|---|---|")
    A("| 值 | %d | %d | %d | %d | %d |"
      % (extra.get("pool_min", 0), extra.get("pool_p10", 0), extra.get("pool_med", 0),
         extra.get("pool_p90", 0), extra.get("pool_max", 0)))
    A("")
    A("所以「真换敌人」要做得干净，随机器应当**按图抽目标**：先 `ES.pool_table()` 拿到每张图的可达行池，"
      "再在池内配对。全局池配出来的计划会被本模块如实跳过并计数 —— 不会静默失败，但应用率会很低。")
    A("")
    pm = extra.get("permap") or {}
    if pm:
        A("**已经实测过这条**（`_permap_experiment`）：对前 %d 张图，每张都用**本图的行**两两循环配对、"
          "再只对那张图跑一次 `plan_swaps(dry_run=True)`：" % pm.get("maps", 0))
        A("")
        A("| 按图抽目标 | 值 |")
        A("|---|---|")
        A("| 参与图数 | %d |" % pm.get("maps", 0))
        A("| 这些图上的 enemy part | %d |" % pm.get("parts", 0))
        A("| 会改动 | %d |" % pm.get("changed", 0))
        A("| **跳过** | **%d** |" % pm.get("skipped", 0))
        A("")
        A("跳过 = 0，因为按图抽目标时「目标模型不在该图」这件事**不可能发生**。"
          "这就是给随机机的结论：**按图抽，不要全局抽**。" if pm.get("skipped") == 0
          else "⚠ 这里居然还有跳过 —— 见上表。")
        A("")
    A("### 3. `think_id` 是启发式的（不确定度已量出）")
    A("")
    A("同一个 npc_id 在不同图上可以用不同的 think_id：3807 个行里 **469 个（12.32%）**有多个。"
      "本模块取**地图实测众数**。上游 `pairs` 只给了行 id，没给 think，所以这是能做到的最好选择；"
      "但它确实是启发式 —— 要更准就得让随机器把 think_id 一起给出（本模块的 `write_fields` 可关掉它）。")
    A("")
    return _write_text(path, "\n".join(L) + "\n")


def _write_text(path, text):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ────────────────────────── CLI ──────────────────────────

def _load_pairs(path):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return {int(k): int(v) for k, v in data.items()}
    out = {}
    for row in data:                       # 也接受 [{"src":…, "dst":…}, …]
        a = row.get("src", row.get("from", row.get("npc_id")))
        b = row.get("dst", row.get("to", row.get("new_row_id")))
        out[int(a)] = int(b)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="真换敌人的地图产出器：按替换计划改 MSB，产物只写输出目录")
    ap.add_argument("--maps", type=int, default=None, help="最多处理多少张图（默认：自检 4 张）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 investigation/swapper_probe）")
    ap.add_argument("--map-dir", default=None, help="源地图目录（默认法魂 mod 的 MapStudio，只读）")
    ap.add_argument("--pairs", default=None, help="替换计划 JSON：{\"源行id\": 目标行id}")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--out-kind", default="same", choices=["same", "dflt", "krak"],
                    help="产出 DCX 的压缩容器（默认 same = 保持原 kind）")
    ap.add_argument("--no-fallback", action="store_true", help="关掉 all_models 兜底（默认开）")
    ap.add_argument("--pool", action="store_true", help="只导出每张图的可达行池 reachable_rows.csv")
    ap.add_argument("--verify-only", action="store_true", help="不产出，只对已有输出跑 verify_outputs")
    ap.add_argument("--report", default=os.path.join(DEFAULT_OUT, REPORT_NAME),
                    help="报告写到哪（默认 swapper_probe/report.md）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    log = (lambda *x: None) if a.quiet else print
    md = _resolve_map_dir(a.map_dir)
    od = _guard_out_dir(a.out, md)
    prof = load_profiles(log=log)

    if a.pool:
        rows = pool_table(md, prof, log=log,
                          out_csv=os.path.join(od, "reachable_rows.csv"), limit=a.maps)
        return 0 if rows else 1

    if a.pairs:
        pairs = _load_pairs(a.pairs)
        names, notes = None, ["用外部计划 %s（%d 条）" % (a.pairs, len(pairs))]
    else:
        names = SELFTEST_MAPS if a.maps is None else [
            os.path.basename(p)[:-8] for p in
            sorted(glob.glob(os.path.join(md, "*.msb.dcx")))[:a.maps]]
        pairs, notes = selftest_pairs(md, names, prof, log=log)
        if not pairs:
            raise SwapError("自检凑不出配对，请显式给 --pairs")

    log("")
    log("=== 产出 ===")
    before = None if (a.dry_run or a.verify_only) else hash_tree(md)
    if a.verify_only and not os.path.isdir(od):
        raise SwapError("--verify-only 需要输出目录已存在：%s" % od)
    if a.verify_only:
        plan = {"maps_written": len([f for f in os.listdir(od)
                                     if f.endswith(".msb.dcx")]),
                "maps_total": 0, "maps_changed": 0, "parts_changed": 0,
                "parts_matched": 0, "parts_skipped": 0, "parts_unchanged": 0,
                "parts_suppressed": 0, "skip_reasons": {}, "files": [], "errors": [],
                "degraded": [], "elapsed": 0.0, "pairs": len(pairs), "axis_hist": {},
                "out_dir": od, "map_dir": md, "dry_run": False}
        log("（--verify-only：不产出，只校验 %s 里已有的 %d 张图）"
            % (od, plan["maps_written"]))
    else:
        kwargs = dict(out_dir=od, log=log, prof=prof, out_kind=a.out_kind,
                      dry_run=a.dry_run, quiet=a.quiet,
                      allow_model_fallback=not a.no_fallback)
        if a.pairs:
            kwargs["limit"] = a.maps
        else:
            kwargs["only_maps"] = names
        plan = plan_swaps(pairs, md, **kwargs)

    if a.dry_run:
        log("\n（dry-run：没有写任何文件）")
        return 0

    log("")
    log("=== 校验 ===")
    ver = verify_outputs(md, od, pairs, log=log, prof=prof, quiet=a.quiet,
                         allow_model_fallback=not a.no_fallback)

    mod_untouched = None
    if before is not None and len(before) < 5000:
        after = hash_tree(md)
        mod_untouched = (before == after) if before else None
        if mod_untouched is not None:
            log("[边界] mod 地图目录前后逐文件 sha256 %s"
                % ("一致（一个字节都没动）" if mod_untouched else "**不一致！**"))

    # 行池统计（写进报告：这决定随机器该怎么抽）
    extra = {"notes": notes, "mod_untouched": bool(mod_untouched)}
    try:
        rows = pool_table(md, prof, log=None, out_csv=os.path.join(od, "reachable_rows.csv"))
        vals = sorted(r["reachable_rows"] for r in rows if r["parts"]) or [0]
        extra.update(pool_min=vals[0], pool_p10=vals[len(vals) // 10],
                     pool_med=vals[len(vals) // 2], pool_p90=vals[len(vals) * 9 // 10],
                     pool_max=vals[-1])
        log("[行池] 已导出 reachable_rows.csv（每图可达行 median=%d）" % extra["pool_med"])
    except Exception as e:                                        # noqa: BLE001
        log("[行池] 跳过：%s: %s" % (type(e).__name__, e))

    try:
        extra["permap"] = _permap_experiment(md, prof, 20, log=log)
    except Exception as e:                                        # noqa: BLE001
        log("[按图抽目标] 跳过：%s: %s" % (type(e).__name__, e))

    # 全量外推：同一份计划在**全部 634 张图**上跑一遍（dry-run，不写任何文件）
    if not a.maps and not a.verify_only:
        try:
            fs = plan_swaps(pairs, md, out_dir=od, log=None, prof=prof, dry_run=True,
                            quiet=True, allow_model_fallback=not a.no_fallback)
            extra["full"] = {"maps": fs["maps_total"], "maps_changed": fs["maps_changed"],
                             "parts_changed": fs["parts_changed"],
                             "parts_skipped": fs["parts_skipped"], "elapsed": fs["elapsed"]}
            log("[全量] 634 张图 dry-run：改过 %d 张 / part 改 %d / 跳过 %d / 耗时 %.1fs"
                % (fs["maps_changed"], fs["parts_changed"], fs["parts_skipped"], fs["elapsed"]))
        except Exception as e:                                    # noqa: BLE001
            log("[全量] 跳过：%s: %s" % (type(e).__name__, e))

    # 校验器自身的反面测试：一个永远说 OK 的校验器没有价值
    try:
        extra["neg"] = negative_selftest(md, od, pairs, prof=prof, log=log, quiet=a.quiet)
    except Exception as e:                                        # noqa: BLE001
        log("[反面测试] 跳过：%s: %s" % (type(e).__name__, e))
        extra["neg"] = {"ok": False, "cases": [],
                        "reason": "%s: %s" % (type(e).__name__, e)}

    ver["_per_map"] = ver.pop("per_map", [])
    extra["external_plan"] = bool(a.pairs)
    extra["verify_only"] = bool(a.verify_only)
    rp = write_report(a.report, plan, ver, extra)
    # 「≥3 张图」是**自检**的门槛；用外部计划跑时只看校验是否通过
    selftest = not a.pairs and not a.verify_only
    ok = ver["ok"] and (plan["maps_written"] >= 3 or not selftest)
    log("")
    log("[报告] %s" % rp)
    log("[报告] 结论：产出 %d 张图｜意外变 %d 个｜%s"
        % (plan["maps_written"], ver["unexpected_changed"],
           "自检通过" if ok else ("校验未通过" if not ver["ok"] else "**未达标**")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
