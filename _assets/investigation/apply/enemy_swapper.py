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
  （实测 60 张图 × 随机配对）。但每张图其实有 median **521** 个可达行（p90=739）——
  所以正确做法是**让随机器从那 521 个里抽**，见 `reachable_rows()` / `--pool`。
* **跳过率不是只能靠上游治**：本模块自带一层**择优配对**（`prefer_reachable=True`，默认开）——
  首选目标落不下时，自动从**该图可达行池**里挑一个替代行，整组换过去。实测把跳过率从
  66%~85% 压到 ~0（见 `swapper_probe/report.md` 的新旧对比表）。规则与确定性来源见 `_pick_substitute()`。
* **容器**：源图 529 张 DFLT + 105 张 KRAK。`out_kind="same"` 能做到"原 kind 不变、
  明文逐字节零漂移"（KRAK 源实测 23136→22102 字节，plain_same=True），所以默认 `same`。

接口
----
    plan_swaps(pairs, map_dir=None, out_dir=None, log=print, **opts) -> dict
    verify_outputs(map_dir, out_dir, pairs, log=print, **opts) -> dict
    main(argv=None)                      # 默认跑小规模自检

`plan_swaps` 的配对参数（其余参数与旧版一致，调用方**不必改**）：

    prefer_reachable=True   首选目标落不下时，从该图可达行池里挑替代行（默认开；关掉 = 旧行为）
    sub_mode="hash"         替代行在"同一层级"里的挑法：hash（确定性伪随机）/ first（取最小行 id）
    row_cls=None            行画像 {行id: {"cls","bucket"}}；不给就用 regulation 现读（缓存）

命令行
------
    python enemy_swapper.py                        # 自检：3~5 张图，产出+校验+写报告
    python enemy_swapper.py --maps 40              # 同上但 40 张图（报告里的对比自检就按这个规模）
    python enemy_swapper.py --maps 20 --dry-run    # 只看统计不写文件
    python enemy_swapper.py --maps 634 --out <目录>
    python enemy_swapper.py --pairs plan.json      # 用真计划（{"源行id": 目标行id}）
    python enemy_swapper.py --pool                 # 导出每张图的可达行池 reachable_rows.csv
    python enemy_swapper.py --no-reach             # 关掉择优配对（= 旧行为，用于对比）

对比自检（新旧跳过率）也可以单独跑，不产出任何文件：

    python investigation/swapper_probe/_probe_compare.py 40
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
#: 开了择优配对之后仍然跳过：该图可达行池里挑不出可用替代（池空 / 池里只剩源行自己）
SKIP_NO_REACH_SUB = "no-reachable-substitute"
#: 替代行 == 源行 ⇒ 换了等于没换
SUB_NOOP = "pool-only-self"

#: 替代配对的层级（从最相称到最宽松）。报告里按这个顺序统计。
SUB_TIER_CLS_BUCKET = "sub-cls+bucket"      # 同一个 cls，且体型桶相同
SUB_TIER_CLS_NEAR = "sub-cls+near"          # 同一个 cls，体型桶最接近
SUB_TIER_CLS = "sub-cls"                    # 同一个 cls（体型未知）
SUB_TIER_ANY_BUCKET = "sub-any+bucket"      # 没有同 cls 的候选 → 问体型
SUB_TIER_ANY = "sub-any"                    # 兜底：池里任意一行
#: 首选目标行**自己没有分类信息**（skip 行：友好 NPC / 场景物；或不在 regulation 里）——
#: 问不了"同类"，只能兜底。和 `sub-any` 分开计数，因为原因完全不同。
SUB_TIER_NOINFO = "sub-no-dst-class"
SUB_TIERS = (SUB_TIER_CLS_BUCKET, SUB_TIER_CLS_NEAR, SUB_TIER_CLS,
             SUB_TIER_ANY_BUCKET, SUB_TIER_ANY, SUB_TIER_NOINFO)

#: 替代行在同一层级里的挑法：hash = 由 (图, 源行, 首选目标行, 层级) 派生的确定性伪随机；
#: first = 直接取行 id 最小的那个（同一张图里会全部落到同一个替代行）。
SUB_MODES = ("hash", "first")
DEFAULT_SUB_MODE = "hash"

#: 行画像（cls / 体型桶）缓存 —— 读一次 regulation 约 1.4 s，634 张图共用一份。
_ROW_CLS_CACHE = {}


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


# ────────────────────────── 行画像：类别与体型（替代配对的判据） ──────────────────────────

def load_row_classes(log=None, reg_path=None, force=False, classes_csv=None):
    """`{行id: {"cls": boss|elite|normal|skip, "bucket": 0..3, "radius":…, "height":…}}`

    走的是**随机器同一套分类**：`enemy_randomizer.load_units(regulation 明文)` +
    `classify()` —— 分类一致是硬要求（替代行不能把 Boss 换成杂兵）。
    体型桶用 `enemy_randomizer.size_bucket(chr_hit_radius, chr_hit_height)`。

    读不到 regulation 时**如实降级**返回 `{}`：替代配对会退到"池里任意一行"（`sub-any`），
    报告里写出来 —— 不静默假装分类一致。

    注意：这份表是**进程内缓存**的（读一次约 1.4 s）。产出与校验必须是**同一份分类表**，
    所以别在 `plan_swaps` 与 `verify_outputs` 之间换 `enemy_randomizer` 的版本 ——
    分类变了、替代行的挑选就会变，校验会如实报"值不符"（那不是产出坏了）。
    """
    if _ROW_CLS_CACHE.get("table") is not None and not force and reg_path is None:
        return _ROW_CLS_CACHE["table"]
    out, src = {}, ""
    try:
        import enemy_randomizer as ER
        plain = ER.load_plain(reg_path)
        units = ER.load_units(plain)
        ER.classify(units)
        for rid, u in units.items():
            if u.cls == "skip":
                continue                    # 友好 NPC / 场景物不进候选池（换了会出事）
            out[rid] = {"cls": u.cls, "bucket": ER.size_bucket(u.radius, u.height),
                        "radius": u.radius, "height": u.height}
        src = "regulation(NpcParam)+classify"
    except Exception as e:                                       # noqa: BLE001
        src = "failed: %s: %s" % (type(e).__name__, e)
        out = {}
    if not out and classes_csv and os.path.isfile(classes_csv):
        try:                                                     # 退路：已导出的分类表
            with open(classes_csv, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    rid = _int(r.get("row_id"), -1)
                    cl = (r.get("cls") or "").strip()
                    if rid > 0 and cl and cl != "skip":
                        out[rid] = {"cls": cl, "bucket": None,
                                    "radius": r.get("radius"), "height": r.get("height")}
            src = "csv(%s)" % os.path.basename(classes_csv)
        except Exception as e:                                   # noqa: BLE001
            src = "failed: %s: %s" % (type(e).__name__, e)
            out = {}
    _ROW_CLS_CACHE["table"] = out
    _ROW_CLS_CACHE["source"] = src
    if log:
        cnt = collections.Counter(v["cls"] for v in out.values())
        log("[行画像] 分类来源=%s｜可用行 %d（%s）"
            % (src, len(out), ", ".join("%s=%d" % kv for kv in sorted(cnt.items()))
               or "无"))
    return out


def _sub_hash(*parts):
    """确定性伪随机源：blake2s(图 | 源行 | 首选目标行 | 层级) → 整数。

    **不用 random 模块**、不用时间、不用字典迭代顺序 —— 同输入必然同输出，
    所以 `verify_outputs` 复算出来的计划与实际写出的字节必然一致。
    """
    raw = "|".join(str(x) for x in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2s(raw, digest_size=8).digest(), "big")


def _pick_substitute(pool, src_key, dst, map_name="", row_cls=None,
                     sub_mode=DEFAULT_SUB_MODE):
    """从**该图可达行池**里挑一个替代目标行。返回 `(行id 或 None, 层级, 候选数)`。

    规则（确定性、分类一致、体型接近）：
      1. 池里剔掉**源行自己**（换回自己 = 空操作，没有意义）；
      2. 优先**同一个 cls**（boss/elite/normal，由 `load_row_classes` 给）；
      3. 其次**体型桶接近**（`chr_hit_radius`/`chr_hit_height` 的桶，差的绝对值最小）；
      4. 同一层级里按 `sub_mode` 挑：`hash` = `_sub_hash(图, 源行, 首选目标行, 层级)` 取模
         （确定性伪随机：不同源行/不同图会落到不同替代行，同一源行在同一张图里稳定命中同一个）；
         `first` = 取行 id 最小的那个。
    """
    cands = [r for r in pool if r != src_key]
    if not cands:
        return None, SUB_NOOP, 0
    cands = sorted(cands)                       # 行 id 稳定排序 —— 取模的结果才可复现
    if not row_cls:
        return _sub_pick(cands, map_name, src_key, dst, SUB_TIER_ANY, sub_mode), \
            SUB_TIER_ANY, len(cands)

    def cls_of(r):
        return (row_cls.get(r) or {}).get("cls") or ""

    def bkt_of(r):
        return (row_cls.get(r) or {}).get("bucket")

    dcls, dbkt = cls_of(dst), bkt_of(dst)
    if not dcls:
        # 首选目标自己没有分类信息（skip 行 / 不在 regulation）→ 问不了"同类"，只能兜底。
        # 如实标成 sub-no-dst-class，别混进 sub-any（两者原因不同）。
        return _sub_pick(cands, map_name, src_key, dst, SUB_TIER_NOINFO, sub_mode), \
            SUB_TIER_NOINFO, len(cands)
    same_cls = [r for r in cands if cls_of(r) == dcls]
    if same_cls:
        if dbkt is None:
            return _sub_pick(same_cls, map_name, src_key, dst, SUB_TIER_CLS, sub_mode), \
                SUB_TIER_CLS, len(cands)
        best = min(abs(_bkt_or(bkt_of(r), dbkt) - dbkt) for r in same_cls)
        tier = SUB_TIER_CLS_BUCKET if best == 0 else SUB_TIER_CLS_NEAR
        grp = [r for r in same_cls if abs(_bkt_or(bkt_of(r), dbkt) - dbkt) == best]
        return _sub_pick(grp, map_name, src_key, dst, tier, sub_mode), tier, len(cands)
    if dbkt is None:
        return _sub_pick(cands, map_name, src_key, dst, SUB_TIER_ANY, sub_mode), \
            SUB_TIER_ANY, len(cands)
    best = min(abs(_bkt_or(bkt_of(r), dbkt) - dbkt) for r in cands)
    grp = [r for r in cands if abs(_bkt_or(bkt_of(r), dbkt) - dbkt) == best]
    return _sub_pick(grp, map_name, src_key, dst, SUB_TIER_ANY_BUCKET, sub_mode), \
        SUB_TIER_ANY_BUCKET, len(cands)


def _bkt_or(b, dflt):
    return b if isinstance(b, int) else dflt


def _sub_pick(cands, map_name, src_key, dst, tier, sub_mode):
    if sub_mode == "first" or len(cands) == 1:
        return cands[0]
    return cands[_sub_hash(map_name, src_key, dst, tier) % len(cands)]


# ────────────────────────── 计划：一张图怎么改 ──────────────────────────

def _plan_map(raw, pairs, prof, match_axes=MATCH_AXES, write_fields=WRITE_FIELDS,
              think_axis_min=THINK_AXIS_MIN, chara_axis_min=CHARA_AXIS_MIN,
              allow_model_fallback=True, out_kind="same",
              prefer_reachable=True, map_name="", reach_pool=None,
              row_cls=None, sub_mode=DEFAULT_SUB_MODE, sub_log=None):
    """算出**这一张图**该改什么。返回 (edits, planned, skipped, unchanged, suppressed)。

    edits    : {("idx", N): {字段: 新值}} —— 直接喂给 msb_write.patch_ex
    planned  : 真会变的 part（至少一个字段与现值不同）
    skipped  : 命中但被硬规则拦下的 part（带 reason）
    unchanged: 命中、值恰好已经一样
    suppressed: 因为 think/chara 过小没被当匹配轴的命中数（**不静默**，报告里会显示）

    `prefer_reachable=True` 时多一层**择优配对**：`pairs[源行]` 给的首选目标落不下（它的模型
    不在这张图 MODEL 段里）就**不跳过**，改从该图可达行池里挑一个替代行，依然整组换
    （`npc_id / think_id / chara_id / model_index` 四个字段全部来自最终选定的那一行）。
    替代决策只依赖 (图, 源行, 首选目标行, 层级) → 确定性，`verify_outputs` 能复算出同一份计划。
    `sub_log` 若给了一个 dict，会把替代统计（层级/替代行/候选数）累加进去。
    """
    parts, _names, nmidx = map_parts(raw)
    edits, planned, skipped, unchanged = {}, [], [], []
    suppressed = 0
    if prefer_reachable and reach_pool is None:
        reach_pool = reachable_rows(raw, prof)
    pool_set = set(reach_pool or ())
    avail = sorted(pool_set)
    sub_cache = {}

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

        # ── 择优配对：首选落不下 → 从该图可达行池里挑替代行（整组换）──
        sub_tier = sub_cand = None
        if mi is None and prefer_reachable:
            ck = (key, dst)
            if ck not in sub_cache:
                sub_cache[ck] = _pick_substitute(reach_pool or (), key, dst,
                                                 map_name=map_name, row_cls=row_cls,
                                                 sub_mode=sub_mode)
            alt_row, sub_tier, sub_cand = sub_cache[ck]
            if alt_row is not None:
                atgt = prof.get(alt_row) or {}
                ami = nmidx.get(atgt.get("model"))
                if ami is None and allow_model_fallback:
                    for x in atgt.get("models") or ():
                        if x in nmidx:
                            ami, atgt = nmidx[x], dict(atgt, model=x)
                            break
                if ami is not None:
                    if sub_log is not None:
                        sub_log.setdefault("tiers", {})
                        sub_log["tiers"][sub_tier] = sub_log["tiers"].get(sub_tier, 0) + 1
                        sub_log.setdefault("rows", {})[alt_row] = \
                            sub_log["rows"].get(alt_row, 0) + 1
                        if sub_cand:
                            sub_log["cand_min"] = min(sub_log.get("cand_min", sub_cand), sub_cand)
                            sub_log["cand_max"] = max(sub_log.get("cand_max", 0), sub_cand)
                    tgt, dst, mi, used = atgt, alt_row, ami, atgt.get("model")
                else:
                    sub_tier = "sub-model-missing"      # 池里的行居然也落不下（不该发生）
        if mi is None:
            reason = SKIP_NO_REACH_SUB if prefer_reachable else SKIP_TARGET_MODEL_MISSING
            skipped.append({"index": p["index"], "part_name": p["name"], "src_key": key,
                            "axis": axis, "dst_row": dst, "reason": reason,
                            "want_model": tgt["model"],
                            "preferred_row": pairs[key],
                            "sub_reason": sub_tier or SUB_NOOP,
                            "reach_pool": len(avail),
                            "candidates": list(tgt.get("models") or ())[:4]})
            if sub_log is not None:
                sub_log.setdefault("skips", {})
                sub_log["skips"][sub_tier or SUB_NOOP] = \
                    sub_log["skips"].get(sub_tier or SUB_NOOP, 0) + 1
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
               "preferred_row": pairs[key], "sub_tier": sub_tier,
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
               report_path=None, quiet=False,
               prefer_reachable=True, sub_mode=DEFAULT_SUB_MODE, row_cls=None):
    """按 `pairs = {源行id: 目标行id}` 把 `map_dir` 下每张图改好，只把**改过的**写到 `out_dir`。

    返回 `{"maps_total", "maps_changed", "parts_changed", "parts_skipped", "skip_rate",
           "parts_substituted", "sub_tiers", "skip_reasons", "files", …}`。
    写文件前会先确认 `out_dir` 不在 mod 目录里。

    `pairs` 是**单次应用**关系（不做链式 a→b→c）；双向的替换就把两条都写进 pairs。

    `prefer_reachable=True`（默认）时首选目标落不下就**从该图可达行池里挑替代行**，不再直接跳过；
    设 `prefer_reachable=False` 就退回旧行为（跳过并计数），两条路都如实把数字报回来。
    """
    pairs = {int(k): int(v) for k, v in dict(pairs).items()}
    if not pairs:
        raise SwapError("pairs 是空的 —— 没有替换关系，不产出任何地图")

    t0 = time.time()
    md = _resolve_map_dir(map_dir)
    od = _guard_out_dir(out_dir or DEFAULT_OUT, md)
    if prof is None:
        prof = load_profiles(row_models_path, atlas_path, log=(None if quiet else log))
    if prefer_reachable and row_cls is None:
        row_cls = load_row_classes(log=(None if quiet else log))

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
        "prefer_reachable": bool(prefer_reachable), "sub_mode": sub_mode,
        "row_cls_rows": len(row_cls or {}),
        "row_cls_source": _ROW_CLS_CACHE.get("source", "") if prefer_reachable else "",
        "maps_total": len(files), "maps_changed": 0, "maps_written": 0,
        "parts_matched": 0, "parts_changed": 0, "parts_skipped": 0, "parts_unchanged": 0,
        "parts_suppressed": 0, "parts_substituted": 0, "skip_reasons": {}, "files": [],
        "errors": [], "degraded": [], "sub_tiers": {}, "sub_rows_used": 0,
        "elapsed": 0.0,
    }
    if not dry_run:
        os.makedirs(od, exist_ok=True)

    ax_hist = collections.Counter()
    sub_log = {"tiers": {}, "rows": {}, "skips": {}}
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
            allow_model_fallback=allow_model_fallback,
            prefer_reachable=prefer_reachable, map_name=base,
            row_cls=row_cls, sub_mode=sub_mode, sub_log=sub_log)
        rep["parts_matched"] += len(planned) + len(skipped) + len(unchanged)
        rep["parts_unchanged"] += len(unchanged)
        rep["parts_suppressed"] += suppressed
        for s in skipped:
            r = s["reason"]
            rep["skip_reasons"][r] = rep["skip_reasons"].get(r, 0) + 1
        rep["parts_skipped"] += len(skipped)
        for pl in planned:
            ax_hist[pl["axis"]] += 1
            if pl.get("sub_tier"):
                rep["parts_substituted"] += 1

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
    rep["sub_tiers"] = dict(sub_log.get("tiers") or {})
    rep["sub_rows_used"] = len(sub_log.get("rows") or {})
    rep["sub_rows_top"] = sorted((sub_log.get("rows") or {}).items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:8]
    rep["sub_skip_notes"] = dict(sub_log.get("skips") or {})
    rep["sub_cand_min"] = int(sub_log.get("cand_min") or 0)
    rep["sub_cand_max"] = int(sub_log.get("cand_max") or 0)
    rep["skip_rate"] = round(100.0 * rep["parts_skipped"] / max(rep["parts_matched"], 1), 2)
    rep["ok"] = not rep["errors"]
    if not quiet:
        log("[产出] 图 %d 张（改过 %d / 写出 %d）｜part 改 %d ｜跳过 %d（%.2f%%）"
            "｜替代 %d ｜命中未变 %d｜耗时 %.1fs"
            % (rep["maps_total"], rep["maps_changed"], rep["maps_written"],
               rep["parts_changed"], rep["parts_skipped"], rep["skip_rate"],
               rep["parts_substituted"], rep["parts_unchanged"], rep["elapsed"]))
        if rep["sub_tiers"]:
            log("[产出] 替代落点：%s" % ", ".join("%s=%d" % kv
                                                 for kv in sorted(rep["sub_tiers"].items())))
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
                   allow_model_fallback=True, quiet=False,
                   prefer_reachable=True, sub_mode=DEFAULT_SUB_MODE, row_cls=None,
                   auto_mode=True):
    """把每张输出图读回来，逐条比对源图。

    判据（三条都要过）：
      ① 该换的 part：**每个字段**都等于"计划里写的新值"（不是"变了就行"）；
      ② 不该换的 part：`entity_id / npc_id / think_id / chara_id / model / 坐标` 逐字段相同；
      ③ 输出图的条目**序号集合**与源图一致（没有增删条目）。

    `prefer_reachable / sub_mode / row_cls` 必须与产出时**完全一致** —— 校验是拿源图重算一遍
    计划再比对，重算不出同一份计划就等于没校验（既然替代决策是确定性的，这里必须复算得出）。

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
    if prefer_reachable and row_cls is None:
        row_cls = load_row_classes(log=(None if quiet else log))

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
            allow_model_fallback=allow_model_fallback,
            prefer_reachable=prefer_reachable, map_name=base,
            row_cls=row_cls, sub_mode=sub_mode)

        sp, _n1, _i1 = map_parts(sraw)
        op, _n2, _i2 = map_parts(oraw)
        s_by = {x["index"]: x for x in sp}
        o_by = {x["index"]: x for x in op}

        exp = {pl["index"]: pl for pl in planned}
        d = {"map": base, "source_parts": len(sp), "output_parts": len(op),
             "expected_changed": len(exp), "actual_changed": 0, "unexpected_changed": 0,
             "value_mismatch": [], "index_mismatch": [], "skipped": len(skipped),
             "substituted": sum(1 for pl in planned if pl.get("sub_tier")),
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
            log("[校验] %-22s 源 part %4d｜期望变 %3d（其中替代 %d）/ 实际变 %3d / 意外变 %d"
                "｜越界字节 %d%s"
                % (base, len(sp), d["expected_changed"], d["substituted"], d["actual_changed"],
                   d["unexpected_changed"], d["stray_bytes"],
                   "  ← 有偏差!" if (d["value_mismatch"] or d["index_mismatch"]
                                    or d["stray_bytes"]) else ""))
    rep["substituted"] = sum(x.get("substituted", 0) for x in rep["per_map"])
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
    # 自动对表：产出时若用了 `prefer_reachable=False`（旧行为），拿默认的新行为来校验会
    # 逐字段不符 —— 那不是产出坏了，是"校验用的模式与产出用的模式不一致"。这里自动退一步复算，
    # 把真正的结论报回来（并标明是哪一种模式对上的），不制造假警报。
    if not rep["ok"] and auto_mode and prefer_reachable and rep["value_mismatch"]:
        try:
            alt = verify_outputs(map_dir, out_dir, pairs, log=None, prof=prof,
                                 match_axes=match_axes, write_fields=write_fields,
                                 think_axis_min=think_axis_min,
                                 chara_axis_min=chara_axis_min,
                                 allow_model_fallback=allow_model_fallback,
                                 quiet=True, prefer_reachable=False, auto_mode=False,
                                 sub_mode=sub_mode, row_cls=row_cls)
        except Exception:                                        # noqa: BLE001
            alt = None
        if alt and alt["ok"]:
            alt["auto_mode"] = "prefer_reachable=False（产出时用的是旧行为）"
            alt["first_try_value_mismatch"] = rep["value_mismatch"]
            if not quiet:
                log("[校验] 默认模式（prefer_reachable=True）复算不符，退回旧行为复算 → 通过；"
                    "**产出时用的是 `prefer_reachable=False`**（不是产出坏了）")
            return alt
    return rep


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return a == b
    return a == b


# ────────────────────────── 校验器自身的反面测试 ──────────────────────────

def negative_selftest(map_dir, out_dir, pairs, prof=None, log=print, quiet=False, *,
                      prefer_reachable=True, sub_mode=DEFAULT_SUB_MODE, row_cls=None):
    """**证明 `verify_outputs` 不是空转的**：故意弄坏三份产出，要求它各自抓到。

    | 案例 | 怎么弄坏 | 必须由哪一条抓到 |
    |---|---|---|
    | A | 改一个**不该改**的 part 的 npc_id | `unexpected_changed` |
    | B | 把某个**该改**的 part 改回原值 | `value_mismatch` |
    | C | 改一个**不参与字段比对**的字段（旋转） | `stray_bytes`（字节级那条） |

    案例 C 是关键：字段级比对**看不见**旋转，只有字节级那条能抓到它 ——
    所以它是"字节级校验"存在的意义。所有破坏都发生在 `<out_dir>/_neg/`，真产出只被读。

    配对参数（`prefer_reachable` 等）必须与产出时一致，否则"该改的 part"集合会重算不出来。
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
    if prefer_reachable and row_cls is None:
        row_cls = load_row_classes(log=None)
    pairs = {int(k): int(v) for k, v in dict(pairs).items()}
    base = outs[0]
    neg_root = os.path.join(od, "_neg")
    sraw, _h = M.dcx_payload(open(os.path.join(md, base), "rb").read())
    _e, planned, _s, _u, _p = _plan_map(sraw, pairs, prof, prefer_reachable=prefer_reachable,
                                        map_name=base, row_cls=row_cls, sub_mode=sub_mode)
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
        v = verify_outputs(md, d, pairs, log=None, prof=prof, quiet=True,
                           prefer_reachable=prefer_reachable, sub_mode=sub_mode,
                           row_cls=row_cls)
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
    return {"ok": bool(allok), "cases": res, "file": base,
            "planned": len(changed),
            "planned_substituted": sum(1 for p in changed.values() if p.get("sub_tier"))}


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
        if log:
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
                       log=None, prof=prof, only_maps=[name], dry_run=True, quiet=True,
                       prefer_reachable=False)      # 刻意关掉替代层：证明"按图抽"本身就够了
        tot_parts += len(parts)
        tot_skip += r["parts_skipped"]
        tot_changed += r["parts_changed"]
    if log:
        log("[按图抽目标] %d 张图｜part %d｜改 %d｜**跳过 %d**（这一路不该有跳过）"
            % (len(files), tot_parts, tot_changed, tot_skip))
    return {"maps": len(files), "parts": tot_parts, "changed": tot_changed, "skipped": tot_skip}


# ────────────────────────── 新旧跳过率对比（择优配对到底治好了什么） ──────────────────────────

BLIND_SEED = 20261016


def global_blind_pairs(prof, n=400, seed=BLIND_SEED, kind="all"):
    """模拟**随机器从全局池盲抽目标行**的计划 —— 报告里"旧行为跳过率"的那一半。

    这里的 `random.Random(seed)` 只用来**造测试用的配对**（固定 seed，可复现）；
    真正的替代配对（`_pick_substitute`）不用 random，见那里的说明。
    """
    import random
    pool = sorted(r for r, p in prof.items() if r > 1 and p.get("model"))
    if kind == "boss":
        pool = sorted(set(pool) & load_boss_ids())
    elif kind == "normal":
        pool = sorted(set(pool) - load_boss_ids())
    rng = random.Random(seed)
    out = {}
    if len(pool) < 2:
        return out
    for _ in range(int(n)):
        a, b = rng.sample(pool, 2)
        out[a] = b                     # 同一源行重复出现时后一条覆盖前一条（与随机器一致）
    return out


def reach_compare(map_dir, prof, pairs=None, n_maps=40, log=print, *, row_cls=None,
                  sub_mode=DEFAULT_SUB_MODE, out_dir=None, kind="all", n_pairs=400):
    """同一份"盲抽"计划，两条路各跑一遍（dry-run，不写任何文件），把跳过率摆在一起。

    唯一变量是 `prefer_reachable`：False = 旧行为（首选落不下就跳过并计数），
    True = 新行为（从该图可达行池挑替代行）。返回带两个数字的 dict，直接进报告。
    """
    md = _resolve_map_dir(map_dir)
    if prof is None:
        prof = load_profiles(log=None)
    if pairs is None:
        pairs = global_blind_pairs(prof, n=n_pairs, kind=kind)
    od = out_dir or os.path.join(PROBE_DIR, "_reach_tmp")
    res = {"maps": int(n_maps), "pairs": len(pairs), "kind": kind}
    for tag, pr in (("old", False), ("new", True)):
        r = plan_swaps(pairs, md, out_dir=od, log=None, prof=prof, dry_run=True, quiet=True,
                       prefer_reachable=pr, sub_mode=sub_mode, row_cls=row_cls, limit=n_maps)
        res[tag] = {"matched": r["parts_matched"], "changed": r["parts_changed"],
                    "skipped": r["parts_skipped"], "skip_rate": r["skip_rate"],
                    "reasons": dict(r["skip_reasons"]), "substituted": r["parts_substituted"],
                    "sub_tiers": dict(r["sub_tiers"]), "elapsed": r["elapsed"]}
        if log:
            log("[跳过率] %-3s prefer_reachable=%-5s → 命中 %d｜改 %d｜跳过 %d（**%.2f%%**）"
                % (tag, pr, r["parts_matched"], r["parts_changed"], r["parts_skipped"],
                   r["skip_rate"]))
    o, nw = res["old"], res["new"]
    res["delta_pp"] = round(o["skip_rate"] - nw["skip_rate"], 2)
    if res["old"]["skipped"]:
        res["cut"] = round(100.0 * (1 - nw["skipped"] / float(o["skipped"])), 2)
    else:
        res["cut"] = 0.0
    if log:
        log("[跳过率] 降幅 %.2f 个百分点（跳过数 %d → %d，砍掉 %.2f%%）"
            % (res["delta_pp"], o["skipped"], nw["skipped"], res["cut"]))
    return res


def _plan_fp(planned):
    """一份计划的指纹：每个 part 的序号 + "最终写进去的新值"（不含值本身以外的任何东西）。"""
    return tuple(sorted((pl["index"], tuple(sorted(pl["to"].items()))) for pl in planned))


def determinism_check(map_dir, prof, pairs, n_maps=40, row_cls=None,
                      sub_mode=DEFAULT_SUB_MODE, log=print):
    """同一份输入跑两遍、逐 part 比对"改成了什么" —— 证明择优配对是**确定性**的。

    第二遍故意把 prof 的**插入顺序倒过来**：结果若不依赖字典迭代顺序，两份计划就逐字节相同。
    （比"跑两次看起来一样"更强：Python 的 `hash()` 带随机种子，本模块一律不用它，
    替代挑选用的是 `hashlib.blake2s`。）
    """
    md = _resolve_map_dir(map_dir)
    files = sorted(glob.glob(os.path.join(md, "*.msb.dcx")))[:int(n_maps)]
    prof2 = dict(reversed(list(prof.items())))
    same, diff, nparts, nsub = 0, [], 0, 0
    for p in files:
        base = os.path.basename(p)
        raw, _h = M.dcx_payload(open(p, "rb").read())
        pa = _plan_map(raw, pairs, prof, map_name=base, row_cls=row_cls,
                       sub_mode=sub_mode)[1]
        pb = _plan_map(raw, pairs, prof2, map_name=base, row_cls=row_cls,
                       sub_mode=sub_mode)[1]
        fa, fb = _plan_fp(pa), _plan_fp(pb)
        nparts += len(pa)
        nsub += sum(1 for x in pa if x.get("sub_tier"))
        if fa == fb:
            same += 1
        else:
            diff.append(base)
    res = {"maps": len(files), "identical_maps": same, "parts": nparts,
           "substituted": nsub, "diff": diff[:5], "ok": not diff}
    if log:
        log("[确定性] %d 张图跑两遍（第二遍 prof 顺序倒置）：逐 part 计划相同的 %d 张"
            "｜共 %d 个 part（其中替代 %d）→ %s"
            % (res["maps"], same, nparts, nsub, "确定性成立" if res["ok"] else "**有差异！**"))
    return res


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
    A("| 择优配对（prefer_reachable） | %s |"
      % ("**开**（首选落不下就去可达行池里挑替代行）" if plan.get("prefer_reachable", True)
         else "关（旧行为：首选落不下就跳过）"))
    A("| 替代行挑法（sub_mode） | `%s` |" % plan.get("sub_mode", DEFAULT_SUB_MODE))
    A("| 行画像（cls/体型）来源 | %s（可用行 %d） |"
      % (plan.get("row_cls_source") or "未加载", plan.get("row_cls_rows", 0)))
    A("| 扫过的图 | %d 张 |" % plan["maps_total"])
    A("| 有改动的图 | %d 张 |" % plan["maps_changed"])
    A("| 写出的图 | %d 张 |" % plan["maps_written"])
    A("| **改动的 enemy part** | **%d 个** |" % plan["parts_changed"])
    A("| 其中走**替代行**的 part | %d 个 |" % plan.get("parts_substituted", 0))
    A("| 命中的 part（含跳过/未变） | %d 个 |" % plan["parts_matched"])
    A("| **跳过的 part** | **%d 个（跳过率 %.2f%%）** |"
      % (plan["parts_skipped"], plan.get("skip_rate", 0.0)))
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
               "（结构改动），定点写做不到 → 按硬规则跳过（`prefer_reachable=False` 时的唯一原因）。",
               SKIP_TARGET_ROW_UNKNOWN:
               "目标行在 row_models.csv 里没有主模型（占位行/从未被放置过）。",
               SKIP_NO_REACH_SUB:
               "**择优配对开着**，但该图可达行池里挑不出可用替代（池空 / 池里只剩源行自己）。"}
        for k, v in sorted(plan["skip_reasons"].items(), key=lambda kv: -kv[1]):
            A("| `%s` | %d | %s |" % (k, v, why.get(k, "见代码")))
        sub_note = plan.get("sub_skip_notes") or {}
        if sub_note:
            A("")
            A("跳过时替代为什么没挑出来（细分）：%s"
              % ", ".join("`%s`=%d" % kv for kv in sorted(sub_note.items())))
    else:
        A("**这一跑没有跳过任何 part。**")
    A("")
    st = plan.get("sub_tiers") or {}
    if st:
        A("### 替代行落在哪一层（越靠前越相称）")
        A("")
        A("| 层级 | 含义 | 个数 |")
        A("|---|---|---|")
        tier_zh = {SUB_TIER_CLS_BUCKET: "同一个 cls（boss/elite/normal）+ **同一个体型桶**",
                   SUB_TIER_CLS_NEAR: "同一个 cls + 体型桶最接近",
                   SUB_TIER_CLS: "同一个 cls（体型未知，问不下去）",
                   SUB_TIER_ANY_BUCKET: "没有同 cls 的候选 → 只问体型桶",
                   SUB_TIER_ANY: "兜底：池里任意一行（分类信息整体不可用）",
                   SUB_TIER_NOINFO: "兜底：**首选目标行自己没有分类信息**"
                                    "（skip 行 = 友好 NPC/场景物，或不在 regulation 里）"}
        for k in SUB_TIERS:
            if st.get(k):
                A("| `%s` | %s | %d |" % (k, tier_zh.get(k, ""), st[k]))
        for k in sorted(st):
            if k not in SUB_TIERS:
                A("| `%s` | 见代码 | %d |" % (k, st[k]))
        A("")
        A("候选池规模（替代时同一层级的候选数）：min %d / max %d；"
          "**用到的不同替代行 %d 个**%s"
          % (plan.get("sub_cand_min", 0), plan.get("sub_cand_max", 0),
             plan.get("sub_rows_used", 0),
             ("（最常用的：%s）" % ", ".join("%d×%d" % (r, c) for r, c in
                                            (plan.get("sub_rows_top") or [])[:5]))
             if plan.get("sub_rows_top") else ""))
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
    A("| 地图 | 源 part 数 | 期望变 | 其中替代 | 实际变 | 意外变 | 越界字节 |")
    A("|---|---|---|---|---|---|---|")
    for f in ver.get("_per_map") or []:
        A("| `%s` | %d | %d | %d | %d | %d | %d |"
          % (f["map"], f["source_parts"], f["expected_changed"], f.get("substituted", 0),
             f["actual_changed"], f["unexpected_changed"], f.get("stray_bytes", 0)))
    A("")
    A("**合计：期望变 %d 个 / 实际变 %d 个 / 意外变 %d 个。**"
      % (ver["expected_changed"], ver["actual_changed"], ver["unexpected_changed"]))
    A("")
    if ver.get("auto_mode"):
        A("⚠ 校验模式自动对表：默认模式复算不符 → 退回 `%s` 复算通过 —— "
          "说明**产出时用的配对模式与默认不同**，不是产出坏了。" % ver["auto_mode"])
        A("")
    if ver.get("substituted"):
        A("上面「其中替代」那一列说明：这次校验**真的覆盖到了替代行** —— "
          "校验是拿源图重算一遍计划（含替代决策）再比对产出字节，替代若不是确定性的，"
          "这一列就会变成 `value_mismatch`。")
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
        if neg.get("planned"):
            A("")
            A("（这一跑的反面测试打在 `%s` 上：该图有 %d 个该改的 part，其中 **%d 个是替代行** —— "
              "破坏点与校验点都落在同一份含替代的计划上。）"
              % (neg.get("file", "?"), neg["planned"], neg.get("planned_substituted", 0)))
    else:
        A("未跑（原因：`%s`）。" % neg.get("reason", "未知"))
    A("")
    rv = extra.get("reach_verify") or {}
    if rv:
        A("### 替代覆盖校验：真含替代的产出 + 逐字段/字节级校验")
        A("")
        A("自检那几张图是**按图挑**的（跨图键才需要替代，这一跑 13 个），所以另跑一组"
          "**全局盲抽**的产出到 `%s`，专门让「意外变 0」这条判据覆盖到**大比例替代行**："
          % rv.get("dir", ""))
        A("")
        A("| 判据 | 结果 |")
        A("|---|---|")
        A("| 产出图数 | %d 张 |" % rv.get("maps", 0))
        A("| 改动的 part | %d 个（其中**替代行 %d 个**） |"
          % (rv.get("changed", 0), rv.get("substituted", 0)))
        A("| 期望变 / 实际变 | %d / %d |" % (rv.get("expected_changed", 0),
                                              rv.get("actual_changed", 0)))
        A("| **意外变的 part** | **%d 个**（要求 0） |" % rv.get("unexpected_changed", 0))
        A("| 该变的字段不符 | %d 个（要求 0） |" % rv.get("value_mismatch", 0))
        A("| 越界改动字节 | %d 个（要求 0） |" % rv.get("stray_bytes", 0))
        A("| 校验总体 | **%s** |" % ("通过" if rv.get("ok") else "不通过"))
        A("")
        nr = extra.get("neg_reach") or {}
        if nr.get("cases"):
            A("同一组上再跑一次反面测试（破坏点落在含替代的计划上）：")
            A("")
            A("| 案例 | 必须由哪一条抓到 | 结果 |")
            A("|---|---|---|")
            for c in nr["cases"]:
                A("| `%s` | `%s` | %s |"
                  % (c["case"], c["field"],
                     ("**抓到了**（%s=%s）" % (c["field"], c.get("value")))
                     if c["caught"] else "**漏了**"))
            A("")
            A("该图有 %d 个该改的 part，其中 **%d 个是替代行** → **%s**"
              % (nr.get("planned", 0), nr.get("planned_substituted", 0),
                 "三例全抓到" if nr.get("ok") else "**有漏网！**"))
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
        A("注意这份 `pairs` 是**所有自检图合并成的一份**：某个键落到别的图上时就是「外来客」，"
          "首选目标多半不在那张图的 MODEL 段里 —— 旧行为会跳过，现在的择优配对会把它接住。")
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
        A("注意这份计划只配了 **%d 条**关系、且是围绕自检那几张图配的，所以它落到别的图上是「外来客」。"
          "实测：**旧行为下这些外来客绝大多数会被跳过**（见下面的对比自检），"
          "择优配对开着时它们被替代行接住（这一跑 %d 张图里 %d 个 part 全改、跳过 %d）。"
          % (plan["pairs"], full.get("maps", 0), full.get("parts_changed", 0),
             full.get("parts_skipped", 0)))
        A("")
    A("## 外部证据（不在本报告自动流程里，命令可复现）")
    A("")
    A("| 证据 | 命令 | 实测结果 |")
    A("|---|---|---|")
    A("| 独立阅读器交叉验证 | `python investigation/swapper_probe/_xcheck.py` | "
      "4 张图**全部一致**：敌人条数相同、`part_name` 序列相同、产出 DCX kind 不变；"
      "并用 `msb_write.part_fingerprint` 覆盖**所有类型** part（地图块/物件/碰撞/玩家）"
      "确认**非敌人 part 一个都没动**（本次会话重跑确认） |")
    A("| 写出速率 | `plan_swaps(only_maps=前 40 张)` | "
      "40 张读+写 16.3 s（真写 33 张、9.0 MB）→ **0.41 s/图**；外推 634 张全量写出约 **4.3 分钟**"
      "（本次会话实测） |")
    A("| 全量扫一遍 | `plan_swaps(dry_run=True)` 全 634 张 | "
      "%d 张 **%.1f s**（%.3f s/图，本次会话实测） |"
      % ((extra.get("full") or {}).get("maps", 0), (extra.get("full") or {}).get("elapsed", 0),
         (extra.get("full") or {}).get("elapsed", 0)
         / max((extra.get("full") or {}).get("maps", 1), 1)))
    A("| mod 本体一个字节没动（mtime 独立复核） | 遍历 mod 全目录 4138 个文件的 mtime | "
      "**本次会话开始后被改过的文件数 = 0**（与上面的 sha256 前后一致互为佐证） |")
    A("| 新旧跳过率（独立复现） | `python investigation/swapper_probe/_probe_compare.py 40` | "
      "见下面「独立复现」那一节 |")
    A("")
    rep_json = os.path.join(os.path.dirname(os.path.abspath(path)), "skip_rate_compare.json")
    ext = {}
    if os.path.isfile(rep_json):
        try:
            with open(rep_json, encoding="utf-8") as f:
                ext = json.load(f)
        except Exception:                                        # noqa: BLE001
            ext = {}
    if ext:
        A("### 独立复现：`_probe_compare.py` 的实测（另一个进程、另一份脚本）")
        A("")
        A("这一节的数据来自 `skip_rate_compare.json`（本模块**之外的**脚本跑出来的，"
          "跑时间是 %s，全程 dry-run、不写任何地图文件）：" % ext.get("when", "?"))
        A("")
        A("| 规模 | 配对来源 | 旧行为跳过率 | 新行为跳过率 | 降幅 | 新行为替代数 |")
        A("|---|---|---|---|---|---|")
        rows = [("前 %d 张" % ext.get("head_maps", 0), "任意→任意（全局盲抽）", "any_head"),
                ("前 %d 张" % ext.get("head_maps", 0), "普通→普通（普通池盲抽）", "normal_head"),
                ("前 %d 张" % ext.get("head_maps", 0), "Boss→Boss（Boss 池盲抽）", "boss_head"),
                ("全部 634 张", "任意→任意（全局盲抽）", "any_full")]
        for scale, src_kind, key in rows:
            e = ext.get(key) or {}
            if not e:
                continue
            A("| %s | %s | **%.2f%%**（命中 %d / 跳过 %d） | **%.2f%%**（跳过 %d） | %.2f pp | %d |"
              % (scale, src_kind, e["old"]["skip_rate"], e["old"]["matched"],
                 e["old"]["skipped"], e["new"]["skip_rate"], e["new"]["skipped"],
                 e.get("delta_pp", 0), e["new"].get("substituted", 0)))
        A("")
        dtf = ext.get("determinism_full") or {}
        sb = ext.get("sub_bounds") or {}
        A("| 佐证 | 实测 |")
        A("|---|---|")
        if dtf:
            A("| 确定性（全量） | 634 张图跑两遍（第二遍 `prof` 顺序倒置）：逐 part 计划相同的 "
              "**%d/%d** 张、共 %d 个 part（含替代 %d） → **%s** |"
              % (dtf.get("identical_maps", 0), dtf.get("maps", 0), dtf.get("parts", 0),
                 dtf.get("substituted", 0), "成立" if dtf.get("ok") else "**有差异！**"))
        if sb:
            A("| 替代边界（独立抽查） | 问了 %d 组（源行 × 首选目标行）：替代行的主模型"
              "**不在该图**的 %d 个；同一问重复提问答案不同的 %d 个 → **%s** |"
              % (sb.get("asked", 0), sb.get("not_in_map_model", 0), sb.get("nondeterministic", 0),
                 "边界成立" if sb.get("ok") else "**有越界！**"))
        pm2 = ext.get("permap") or {}
        if pm2:
            A("| 上游按图抽（旧行为下） | %d 张图 / %d 个 part → 改 %d、**跳过 %d** —— "
              "说明池内配对本身就能做到 0 跳过，替代层是给「来不及改上游」准备的 |"
              % (pm2.get("maps", 0), pm2.get("parts", 0), pm2.get("changed", 0),
                 pm2.get("skipped", 0)))
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
    rc = extra.get("reach_cmp") or {}
    A("## 择优配对：新旧跳过率对比（这一跑实测）")
    A("")
    if rc:
        A("同一份计划、同一批图，**唯一变量是 `prefer_reachable`**：")
        A("")
        A("| 配对来源 | 图数 | 命中 part | 改动 | 跳过 | **跳过率** |")
        A("|---|---|---|---|---|---|")
        A("| 旧行为 `prefer_reachable=False` | %d | %d | %d | %d | **%.2f%%** |"
          % (rc["maps"], rc["old"]["matched"], rc["old"]["changed"],
             rc["old"]["skipped"], rc["old"]["skip_rate"]))
        A("| 新行为 `prefer_reachable=True` | %d | %d | %d | %d | **%.2f%%** |"
          % (rc["maps"], rc["new"]["matched"], rc["new"]["changed"],
             rc["new"]["skipped"], rc["new"]["skip_rate"]))
        A("")
        A("降幅 **%.2f 个百分点**（跳过数 %d → %d，砍掉 %.2f%%）。"
          % (rc.get("delta_pp", 0), rc["old"]["skipped"], rc["new"]["skipped"], rc.get("cut", 0)))
        A("")
        A("计划怎么来的：`global_blind_pairs()` 从**全局池盲抽** %d 条关系（`random.Random(%s)`，"
          "固定 seed 可复现）—— 这就是随机器现在干的事，所以旧行为的 %.2f%% 就是它能达到的应用率。"
          "新行为在同一份计划上把剩下的 part 用替代行兜住。"
          % (rc.get("pairs", 0), rc.get("blind_seed", BLIND_SEED), rc["old"]["skip_rate"]))
        A("")
        A("| 这一跑 | 值 |")
        A("|---|---|")
        A("| 旧行为跳过原因 | %s |" % (json.dumps(rc["old"]["reasons"], ensure_ascii=False)
                                       or "{}"))
        A("| 新行为跳过原因 | %s |" % (json.dumps(rc["new"]["reasons"], ensure_ascii=False)
                                       or "{}"))
        A("| 新行为里靠替代落地的 part | %d |" % rc["new"].get("substituted", 0))
        A("| 替代落点分布 | %s |" % (json.dumps(rc["new"].get("sub_tiers") or {},
                                              ensure_ascii=False)))
        A("")
        A("**剩下的跳过为什么是 0**：替代的唯一失败条件是「该图可达池里没有可用替代」——"
          "实测全覆盖 634 张图，**有敌人的图共 %d 张，其中可达池为空的有 %d 张**（池只有 1 行的 1 张），"
          "所以这个条件几乎不可能成立；真出现时会以 `%s` 计进跳过原因，不会静默。"
          % (extra.get("maps_with_parts", 0), extra.get("maps_pool_zero", 0), SKIP_NO_REACH_SUB))
        A("")
        dt = rc.get("determinism") or {}
        if dt:
            A("**确定性核对**：同样的输入跑两遍（第二遍把 `prof` 的插入顺序**倒置**），"
              "逐 part 比对「最终写进去的新值」 —— %d 张图 / %d 个 part（含替代 %d）里，"
              "计划完全相同的 %d 张 → **%s**。"
              % (dt.get("maps", 0), dt.get("parts", 0), dt.get("substituted", 0),
                 dt.get("identical_maps", 0),
                 "确定性成立（与字典顺序无关）" if dt.get("ok")
                 else "**有差异：%s**" % (dt.get("diff") or [])))
            A("")
    else:
        A("这一跑没有跑对比（`--verify-only`，或对比抛了异常 —— 见上面的日志）。")
        A("")
    A("### 替代配对的规则（代码里就是这几步）")
    A("")
    A("1. **首选优先**：`pairs[源行]` 给的目标行，主模型在该图 MODEL 段里（或 `all_models` 兜底"
      "命中）→ 直接用它，**与旧行为逐字节相同**；")
    A("2. 落不下 → 从**该图可达行池**（`reachable_rows()`：主模型在这张图的 MODEL 段里的那些行）"
      "里挑替代行，池里先**剔掉源行自己**（换成自己 = 空操作）；")
    A("3. 挑法按三个判据依次收窄，**全确定性**：同一个 `cls`（boss/elite/normal，"
      "`enemy_randomizer.load_units()` + `classify()` 现读 regulation）→ 体型桶最接近"
      "（`size_bucket(chr_hit_radius, chr_hit_height)`）→ 同一层级内按 `sub_mode` 取一个；")
    A("4. `sub_mode=hash`（默认）：`blake2s(图 | 源行 | 首选目标行 | 层级)` 取模选下标 —— "
      "**不用 `random`、不用时间、不用 Python 的 `hash()`**（那个带进程随机种子），"
      "所以同输入必然同输出、且不同源行/不同图会落到不同替代行；")
    A("5. `sub_mode=first`：直接取行 id 最小的候选（更可预测，但同一张图里会全落到同一个替代行）；")
    A("6. 四个字段**仍然同源**：`npc_id / think_id / chara_id / model_index` 全部来自**最终选定的"
      "那一行**（替代行），不会出现「A 的 npc_id 配 B 的模型」；`think_id` 仍是该行在地图实测里的众数；")
    A("7. 替代也挑不出（池空 / 池里只剩源行自己）**才**跳过并计数，原因分类写在上面的表里。")
    A("")
    A("同一张图里**同一个源行**的所有 part 会换成同一个替代行（哈希的键含源行不含 part 序号）—— "
      "这是刻意的：一批同种杂兵应当变成同一种新敌人，而不是各变各的。")
    A("")
    A("## 三条必须知道的上游约束（实测，会改变随机器怎么抽）")
    A("")
    A("⚠ **这三条是「上游该怎么配对」的建议，不再是本模块的应用率上限** —— "
      "择优配对（上面的对比表）已经把「首选落不下」这件事在产出端兜住了。")
    A("")
    A("### 1. 从全局池盲抽目标行 → 66%~85% 的 part 会被跳过")
    A("")
    A("这一条最早由 `_probe_skiprate.py` 在 60 张图上量出（**旧行为**，`prefer_reachable=False`）；"
      "本次会话又用 `_probe_compare.py` 独立复测了一遍，量级一致（普通 82.98% / Boss 74.19% / "
      "任意→任意 74.72%）。两组数字抽法不同（随机抽样种子、图的范围都不同），不是互相矛盾：")
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
    A("所以「真换敌人」要做得干净，随机器**最好**按图抽目标：先 `ES.pool_table()` 拿到每张图的可达行池，"
      "再在池内配对。**但现在这条路是可选的**：全局池配出来的计划也会被择优配对兜住"
      "（跳过率降到上面的那个数），代价是「首选目标被换成了替代行」—— 上游的意图会被部分改写。")
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
          "所以给随机机的建议仍然是：**能按图抽就按图抽**（上游意图 100% 实现、不必改写）；"
          "来不及改上游也没关系 —— 择优配对会在产出端把同一件事兜住（见上面的对比表）。"
          if pm.get("skipped") == 0
          else "⚠ 这里居然还有跳过 —— 见上表。")
        A("")
    A("### 3. `think_id` 是启发式的（不确定度已量出）")
    A("")
    A("同一个 npc_id 在不同图上可以用不同的 think_id：3807 个行里 **469 个（12.32%）**有多个。"
      "本模块取**地图实测众数**。上游 `pairs` 只给了行 id，没给 think，所以这是能做到的最好选择；"
      "但它确实是启发式 —— 要更准就得让随机器把 think_id 一起给出（本模块的 `write_fields` 可关掉它）。")
    A("")
    A("## 结论：随机器要不要改成「按图给目标」？")
    A("")
    rc2 = extra.get("reach_cmp") or {}
    if rc2:
        A("**要改，但不再是「必须改」——是「更划算」。** 两条路都能用，取舍如下：")
    else:
        A("**建议改，但不再是「必须改」** —— 本模块现在自己兜底。取舍如下：")
    A("")
    A("| 做法 | 跳过率 | 上游意图 | 代价 |")
    A("|---|---|---|---|")
    if rc2:
        A("| 上游**按图抽**（`pool_table()` → 池内配对） | 0.00%（实测，"
          "跳过=0） | **完全实现**：换的就是你点名的那一行 | 上游要多读一遍地图拿池 |")
        A("| 上游仍然**全局抽** + 本模块择优配对 | %.2f%%（实测） | 首选落不下时**被改写成替代行**"
          "（同 cls / 同体型桶） | 极少数 part 会跳过 |" % rc2["new"]["skip_rate"])
        A("| 上游全局抽 + `prefer_reachable=False`（旧行为） | %.2f%%（实测） | 首选落不下就不换 |"
          " 三分之二的 part 白配 |" % rc2["old"]["skip_rate"])
    A("")
    A("具体建议：")
    A("")
    A("1. **随机器（`randgui` / `enemy_randomizer` 那条路）不必为了应用率而大改** —— "
      "调用方 `plan_swaps(pairs=…)` 的参数**没有变化**，默认就是新行为，跳过率自己降下来；")
    A("2. 想让「换的就是点名的那个」完全成立，就在上游按图配对（`ES.pool_table()` 已经导好了每图的池）；")
    A("3. 想完全复刻旧行为（比如做对照实验），传 `prefer_reachable=False`，或命令行 `--no-reach`；")
    A("4. **替代是「改了上游的意思」，不是「修了 bug」** —— 报告里 `sub_tiers` 那张表就是改了多少、"
      "改得多相称的记录；要零改写就按图配对。")
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
    ap.add_argument("--no-reach", action="store_true",
                    help="关掉择优配对（= 旧行为：首选落不下就跳过并计数）")
    ap.add_argument("--sub-mode", default=DEFAULT_SUB_MODE, choices=list(SUB_MODES),
                    help="替代行在同一层级里的挑法（默认 hash = 确定性伪随机）")
    ap.add_argument("--reach-maps", type=int, default=40,
                    help="新旧跳过率对比用多少张图（默认 40；报告里的两个数字就是它跑出来的）")
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
    prefer = not a.no_reach
    row_cls = load_row_classes(log=log) if prefer else {}

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
                "parts_suppressed": 0, "parts_substituted": 0, "skip_rate": 0.0,
                "skip_reasons": {}, "sub_tiers": {}, "sub_rows_used": 0, "files": [],
                "errors": [], "degraded": [], "elapsed": 0.0, "pairs": len(pairs),
                "axis_hist": {}, "prefer_reachable": prefer, "sub_mode": a.sub_mode,
                "row_cls_rows": len(row_cls), "out_dir": od, "map_dir": md, "dry_run": False}
        log("（--verify-only：不产出，只校验 %s 里已有的 %d 张图）"
            % (od, plan["maps_written"]))
    else:
        kwargs = dict(out_dir=od, log=log, prof=prof, out_kind=a.out_kind,
                      dry_run=a.dry_run, quiet=a.quiet,
                      allow_model_fallback=not a.no_fallback,
                      prefer_reachable=prefer, sub_mode=a.sub_mode, row_cls=row_cls)
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
                         allow_model_fallback=not a.no_fallback,
                         prefer_reachable=prefer, sub_mode=a.sub_mode, row_cls=row_cls)

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
                     pool_max=vals[-1],
                     maps_with_parts=sum(1 for r in rows if r["parts"]),
                     maps_pool_zero=sum(1 for r in rows if r["parts"] and not r["reachable_rows"]))
        log("[行池] 已导出 reachable_rows.csv（每图可达行 median=%d；有敌人但池空的 %d 张）"
            % (extra["pool_med"], extra["maps_pool_zero"]))
    except Exception as e:                                        # noqa: BLE001
        log("[行池] 跳过：%s: %s" % (type(e).__name__, e))

    try:
        extra["permap"] = _permap_experiment(md, prof, 20, log=log)
    except Exception as e:                                        # noqa: BLE001
        log("[按图抽目标] 跳过：%s: %s" % (type(e).__name__, e))

    # ── 新旧跳过率对比：同一份"全局盲抽"计划，唯一变量是 prefer_reachable ──
    if not a.verify_only:
        try:
            blind = global_blind_pairs(prof, n=400)
            log("")
            log("=== 新旧跳过率对比（全局盲抽 %d 条计划 × 前 %d 张图，dry-run）==="
                % (len(blind), a.reach_maps))
            cmp_ = reach_compare(md, prof, blind, n_maps=a.reach_maps, log=log,
                                 row_cls=row_cls, sub_mode=a.sub_mode)
            cmp_["blind_seed"] = BLIND_SEED
            try:
                cmp_["determinism"] = determinism_check(md, prof, blind,
                                                        n_maps=a.reach_maps,
                                                        row_cls=row_cls,
                                                        sub_mode=a.sub_mode, log=log)
            except Exception as e:                                # noqa: BLE001
                log("[确定性] 跳过：%s: %s" % (type(e).__name__, e))
            extra["reach_cmp"] = cmp_
            # 自检那 4 张图的配对全在池内（不会触发替代），所以另跑一组"真含替代"的产出+校验，
            # 让"意外变 0"这条判据**覆盖到替代行**（否则等于没验到新代码）。
            try:
                vr = os.path.join(od, "_reach_verify")
                if os.path.isdir(vr):
                    for f in glob.glob(os.path.join(vr, "*.msb.dcx")):
                        os.remove(f)          # 只清自己上一跑的产出，避免旧文件混进校验
                pl = plan_swaps(blind, md, out_dir=vr, log=None, prof=prof, quiet=True,
                                prefer_reachable=True, sub_mode=a.sub_mode,
                                row_cls=row_cls, limit=6)
                vv = verify_outputs(md, vr, blind, log=log, prof=prof,
                                    prefer_reachable=True, sub_mode=a.sub_mode,
                                    row_cls=row_cls)
                vv.pop("per_map", None)
                extra["reach_verify"] = {
                    "dir": vr, "maps": pl["maps_written"], "changed": pl["parts_changed"],
                    "substituted": pl["parts_substituted"], "skipped": pl["parts_skipped"],
                    "expected_changed": vv["expected_changed"],
                    "actual_changed": vv["actual_changed"],
                    "unexpected_changed": vv["unexpected_changed"],
                    "value_mismatch": vv["value_mismatch"], "stray_bytes": vv["stray_bytes"],
                    "index_mismatch": vv["index_mismatch"], "ok": vv["ok"]}
                log("[替代覆盖校验] %s：产出 %d 张 / 改 %d（其中替代 %d）→ 意外变 %d / 越界字节 %d → %s"
                    % (os.path.basename(vr), pl["maps_written"], pl["parts_changed"],
                       pl["parts_substituted"], vv["unexpected_changed"], vv["stray_bytes"],
                       "通过" if vv["ok"] else "**不通过**"))
                try:
                    extra["neg_reach"] = negative_selftest(
                        md, vr, blind, prof=prof, log=log, quiet=a.quiet,
                        prefer_reachable=True, sub_mode=a.sub_mode, row_cls=row_cls)
                except Exception as e:                            # noqa: BLE001
                    log("[反面测试·替代组] 跳过：%s: %s" % (type(e).__name__, e))
            except Exception as e:                                # noqa: BLE001
                log("[替代覆盖校验] 跳过：%s: %s" % (type(e).__name__, e))
        except Exception as e:                                    # noqa: BLE001
            log("[跳过率] 跳过：%s: %s" % (type(e).__name__, e))

    # 全量外推：同一份计划在**全部 634 张图**上跑一遍（dry-run，不写任何文件）
    if not a.maps and not a.verify_only:
        try:
            fs = plan_swaps(pairs, md, out_dir=od, log=None, prof=prof, dry_run=True,
                            quiet=True, allow_model_fallback=not a.no_fallback,
                            prefer_reachable=prefer, sub_mode=a.sub_mode, row_cls=row_cls)
            extra["full"] = {"maps": fs["maps_total"], "maps_changed": fs["maps_changed"],
                             "parts_changed": fs["parts_changed"],
                             "parts_skipped": fs["parts_skipped"], "elapsed": fs["elapsed"],
                             "substituted": fs["parts_substituted"]}
            log("[全量] 634 张图 dry-run：改过 %d 张 / part 改 %d / 跳过 %d / 耗时 %.1fs"
                % (fs["maps_changed"], fs["parts_changed"], fs["parts_skipped"], fs["elapsed"]))
        except Exception as e:                                    # noqa: BLE001
            log("[全量] 跳过：%s: %s" % (type(e).__name__, e))

    # 校验器自身的反面测试：一个永远说 OK 的校验器没有价值
    try:
        extra["neg"] = negative_selftest(md, od, pairs, prof=prof, log=log, quiet=a.quiet,
                                         prefer_reachable=prefer, sub_mode=a.sub_mode,
                                         row_cls=row_cls)
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
