#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敌人随机 v1 · 计划层（M1）

纯函数：不写盘（除 CLI 输出）。输入是 M0 的三张表（位置表 / 敌人数值表 / 分类 yaml），
输出是一份 plan.json：

    units[]      : 每个「替换单元」（重复 MSB 的两行合为一个单元）一条
    positions[]  : 每个位置一行，M2 写入层直接消费
    skips[]      : 负向账本 —— 这次没有替换的每个单元 + 原因

核心概念：
  * 替换单元，不是行：同一物理位置在「打开 / 封印」两张 MSB 里各有一份，
    link 组必须一起换（否则从不同状态进同一地点会看到两只不同的敌人）。
  * 候选是「捐赠单元」，不是 npc_id：同一个 npc 在不同位置可能带不同的
    think/chara，身份必须成套复制（npc + think + chara + model 都来自同一个捐赠位置）。
  * 池只决定「这个位置这次参不参与」，不决定候选是谁；池开关不进种子，
    所以关掉一个池只会让该池的位置跳过，别的位置一个字节都不变。
  * 抽样非双射：每单元独立 RNG（sha256(base_seed|unit_key)），同种子可复现，
    不需要全局随机流（M1 验收①）。

用法：
    python investigation/apply/enemy_plan.py --build [--seed 1] [--out PATH]
    python investigation/apply/enemy_plan.py --show [--plan PATH] [--limit N]
    python investigation/apply/enemy_plan.py --check [--plan PATH]
    python investigation/apply/enemy_plan.py --diff A.json B.json
    python investigation/apply/enemy_plan.py --selftest
    python investigation/apply/enemy_plan.py --pools keystone,remembrance   # 只开这两个池

手动指定：investigation/enemy_manual.csv（map,entity_id,npc_id,model,note），
只对 policy=randomize 的位置生效，优先级高于池/规则/比例。
"""
import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
PLACES = os.path.join(INV, "enemy_places.csv")
NPC = os.path.join(INV, "enemy_table.csv")
MODEL_NAMES = os.path.join(INV, "enemy_model_names.csv")
BAR_TABLE = os.path.join(INV, "enemy_bar_names.csv")
YAML_PATH = os.path.join(HERE, "data", "enemy_classes_v3.yaml")
DEFAULT_PLAN = os.path.join(INV, "enemy_plan.json")
MANUAL = os.path.join(INV, "enemy_manual.csv")

PLAN_VERSION = 1

DEFAULT_OPTIONS = {
    "pools": {"keystone": True, "remembrance": True, "waygate": True, "reliquary": True},
    # 百分比：规则给基数，这里只做全局倍率与逐类/逐 silo 覆盖（界面按类调百分比用）
    "rates": {"default": 0.0, "by_silo": {}, "by_class": {}, "multiplier": 1.0},
    "constraints": {
        "require_model_change": True,
        "size_max": 3.0, "size_max_height": 3.0,
        # 血量带：可选，默认关。开启后只从「血量在 原hp×[lo,hi] 内」的敌人里抽，
        # 用来避免把巨物放进小怪位这类观感问题；难度不靠它守恒（hp/魂是直接赋值，见下）。
        "hp_band": None,
        "include_keep_as_source": False,
        # 有 Boss 大血条的位置：只从「本身有血条名」的模型里抽（否则换完没有名字可写，
        # 血条会沿用原 Boss 的名字 —— 用户实测「一部分 boss 没换名字」）。
        "require_named_donor_for_bar": True,
        # v1.1：多阶段 Boss 整组替换（一阶段→一阶段，二阶段→二阶段）。
        # 默认关：只有显式打开时才处理 multiphase 组，其它单元一个字节都不受影响。
        "multiphase_swap": False,
        # 参考实现的放置安全项（默认按参考的 safe mode 走，可在界面关掉）
        "ignore_size": False,          # 忽略「场地档 vs 模型体型」限制
        "arena_safety": True,           # 位置有 arena 标签时，只允许 size <= arena 的换入者
        # v1.3.13：同一个 Boss 最多被随到几次（0 = 不限）。判定按换入的 npc_id，
        # 只对 Boss 六类（含 Evergaol）计数；多阶段/手动指定的开销也算进去。
        "boss_usage_cap": 5,
    },
    "clamp": {"hp": [0.6, 2.5], "soul": [0.6, 2.5]},
    "owner": "visual",
    # 演出与读取端选项（写盘层消费）
    "features": {"bar_names": True, "nightday": False, "rainbow": False,
                 "bgm_follow": False, "soul_follow": False,
                 # 参考实现的 Enemy Onslaught（实验）：1.0=关；1.5=普通敌人约 +50%。
                 # 只复制普通敌人的 MSB part，Boss/多阶段/传送门/有血条/事件位一律不动。
                 "onslaught": 1.0},
    # 全局数值倍率（参考实现的 Scale up/down enemy health/damage）：
    # hp 直接乘到克隆行的 target_hp；伤害/防御走位置档（spEffectID3），这里只放大生命值。
    "scaling": {"hp": 1.0},
    # 参考实现的 Oops All：所有可随机位置都换成同一个类别的敌人（None = 关闭）。
    "oops_all": None,

    # 逐类预设（编辑器产物）：None = 完全按 YAML 规则；有 classes 时，未列的类仍走 YAML。
    # 预设规则插在「特殊规则（多阶段/传送门/血条）」之后、普通类规则之前。
    "preset": None,
}

OWNER_VISUAL = "visual"

# 区域缩放/类别桥接用到的类集合（与 enemy_write.BOSSISH 同口径）。
AREA_BOSSISH = {"Boss", "MinorBoss", "Miniboss", "NightMiniboss", "DragonMiniboss", "Evergaol"}
# 2026-10-24：法魂无名杂兵（旧 Mob）并入 Basic、粪金龟/商队巨魔退出随机 —— 集合跟着收窄。
AREA_NORMALISH = {"Basic", "Wildlife", "HostileNPC"}


def _target_hp_for(old_hp, donor_hp, old_cls, new_cls, scale_hp=1.0):
    """参考语义的血量基数：换入者面板为主，只做两处类别桥接。

    * 同类/普通：换入者 hp（位置只通过区域 SpEffect 缩放，不再抄旧 hp）；
    * 普通→Boss：参考 `bosshp`，仅当旧 hp 更大时取 sqrt(old*donor)；
    * Boss→普通：换入者 hp，写盘层挂 0.25 血/魂的 SpEffect（参考 BossAsBasicScaling）。
    """
    old_hp = float(old_hp or 0)
    donor_hp = float(donor_hp or 0)
    if donor_hp <= 0:
        return max(1, int(round(old_hp * scale_hp)))
    base = donor_hp
    if old_hp > 0 and old_cls in AREA_NORMALISH and new_cls in AREA_BOSSISH and old_hp > donor_hp:
        base = math.sqrt(old_hp * donor_hp)
    return max(1, int(round(base * float(scale_hp or 1.0))))

# Enemy Onslaught（实验）：只让这些「普通敌人」类参与复制。
# Boss 六类、Helper/None/DupeOnly 以及商队巨魔/敌对 NPC 都有事件或场地依赖，
# 复制它们等于凭空多出一场 Boss 战/多一个入侵者，风险远高于收益。
ONSLAUGHT_CLASSES = {"Basic", "Wildlife"}
ONSLAUGHT_MAX = 3.0


# ---------------------------------------------------------------- 读入

def read_csv(path):
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _i(v):
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        return 0


def _f(v):
    try:
        return float(str(v).strip() or 0.0)
    except ValueError:
        return 0.0


def load_places(path=PLACES):
    rows = read_csv(path)
    if not rows:
        raise SystemExit("位置表是空的：%s" % path)
    out = []
    for r in rows:
        out.append({
            "map": r["map"], "part_name": r["part_name"], "occurrence": _i(r["occurrence"]),
            "entity_id": _i(r["entity_id"]), "npc_id": _i(r["npc_id"]),
            "think_id": _i(r["think_id"]), "chara_id": _i(r["chara_id"]), "model": r["model"],
            "x": _f(r["x"]), "y": _f(r["y"]), "z": _f(r["z"]),
            "cls": r["cls"], "cls_src": r["cls_src"], "area": r["area"],
            "silo": r["silo"], "tier": _i(r["tier"]), "policy": r["policy"],
            "pools": [p.strip() for p in re.split(r"[|;,]", r.get("pools") or "") if p.strip()],
            "note": r.get("note") or "", "link": r.get("link") or "",
            "bar": _i(r.get("bar") or 0),
            "ref_size": _i(r.get("ref_size") or 0), "ref_arena": _i(r.get("ref_arena") or 0),
        })
    return out


def load_bar_names(path=BAR_TABLE):
    """(位置 → 原血条名, 模型 → 血条名)。

    两张索引来自 enemy_bar_names.csv（扫 EMEVD 的 DisplayBossHealthBar/InitializeCommonEvent
    与 boss_healthbar.csv 合并）。模型→名字取出现最多的那个（tie 取较小 id）。
    """
    by_place, by_model, cnt = {}, {}, {}
    for r in read_csv(path):
        mid = _i(r.get("name_id"))
        if not mid:
            continue
        m, e = r.get("map") or "", _i(r.get("entity") or 0)
        if m and e:
            by_place[(m, e)] = mid
        mod = r.get("model") or ""
        if mod:
            c = cnt.setdefault(mod, {})
            c[mid] = c.get(mid, 0) + 1
    for mod, c in cnt.items():
        by_model[mod] = min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return by_place, by_model


def load_npc(path=NPC):
    out = {}
    for r in read_csv(path):
        out[_i(r["row_id"])] = {
            "hp": _i(r["hp"]), "soul": _i(r["get_soul"]),
            "radius": _f(r["chr_hit_radius"]), "height": _f(r["chr_hit_height"]),
            "name": r.get("name") or "", "is_boss": _i(r.get("is_boss") or 0),
        }
    return out


def load_yaml(path=YAML_PATH):
    import yaml
    with io.open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh), hashlib.sha256(open(path, "rb").read()).hexdigest()


def load_pools(cfg):
    pools = {}
    for p in cfg.get("pools") or []:
        pools[p["id"]] = {
            "status": p.get("status"),
            "members": set((m["map"], _i(m["entity"])) for m in (p.get("members") or [])),
        }
    return pools


def load_multiphase(cfg):
    """返回 (位置集合, 组列表)；位置集合用来在计划层硬拦。"""
    members, groups = set(), []
    for g in (cfg.get("multiphase") or {}).get("groups") or []:
        groups.append(g)
        for e in g["phases"]:
            members.add((g["map"], _i(e)))
    return members, groups


def load_rules(cfg):
    """读 yaml 的 randomization 段：有序规则表 + 兜底百分比。

    规则表是「任意类 → 任意类」的唯一开关：按顺序，**第一条命中的规则生效**；
    没命中任何规则 = 保持原样（default_rate 兜底，默认 0）。
    归一化后的规则是纯数据，会被写进 plan 的 meta["rules"]（校验与界面都读它）。
    """
    classes = set((cfg.get("l1_classes") or {}).keys())
    rnd = cfg.get("randomization") or {}
    default_rate = float(rnd.get("default_rate", 0.0))
    if not (0.0 <= default_rate <= 1.0):
        raise SystemExit("randomization.default_rate 必须在 0..1：%s" % default_rate)

    rules, seen = [], set()
    for i, raw in enumerate(rnd.get("rules") or []):
        rid = str(raw.get("id") or "rule%d" % (i + 1))
        if rid in seen:
            raise SystemExit("randomization.rules 里 id 重复：%s" % rid)
        seen.add(rid)

        m = raw.get("match") or {}
        t = raw.get("targets") or {}
        m_cls = [str(c) for c in (m.get("cls") or [])]
        t_cls = t.get("cls")
        if t_cls == "all":
            t_cls = sorted(classes)
        t_cls = [str(c) for c in (t_cls or [])]
        if not t_cls:
            raise SystemExit("规则 %s 没有 targets.cls（写 \"all\" 表示全部类）" % rid)
        for c in m_cls + t_cls:
            if c not in classes:
                raise SystemExit("规则 %s 引用了未定义的类：%s" % (rid, c))

        rate = raw.get("rate")
        rate = 1.0 if rate is None else float(rate)
        if not (0.0 <= rate <= 1.0):
            raise SystemExit("规则 %s 的 rate 必须在 0..1：%s" % (rid, rate))

        areas = t.get("areas", "same")
        if isinstance(areas, str):
            if areas == "same":
                pass
            elif areas in ("any", "base", "dlc"):
                areas = ["base", "dlc"] if areas == "any" else [areas]
            else:
                raise SystemExit("规则 %s 的 targets.areas 只能是 same/any/base/dlc：%s" % (rid, areas))
        else:
            areas = [str(a) for a in areas]
            bad = [a for a in areas if a not in ("base", "dlc")]
            if bad:
                raise SystemExit("规则 %s 的 targets.areas 里有非法区域：%s" % (rid, bad))

        m_area = str(m.get("area") or "any")
        if m_area not in ("any", "base", "dlc"):
            raise SystemExit("规则 %s 的 match.area 只能是 any/base/dlc：%s" % (rid, m_area))

        rule = {
            "id": rid,
            "name": str(raw.get("name") or rid),
            "match": {"cls": m_cls, "pools": [str(x) for x in (m.get("pools") or [])],
                      "area": m_area, "tier": [int(x) for x in (m.get("tier") or [])],
                      "bar": bool(m.get("bar")), "multiphase": bool(m.get("multiphase"))},
            "rate": rate,
            "targets": {"cls": t_cls, "areas": areas,
                        "tier": [int(x) for x in (t.get("tier") or [])],
                        "pools": [str(x) for x in (t.get("pools") or [])]},
            "size_max": raw.get("size_max"),
            "size_max_height": raw.get("size_max_height"),
            "clamp_hp": raw.get("clamp_hp"),
            "clamp_soul": raw.get("clamp_soul"),
            "note": str(raw.get("note") or ""),
        }
        for key in ("size_max", "size_max_height"):
            if rule[key] is not None and float(rule[key]) <= 0:
                raise SystemExit("规则 %s 的 %s 必须 > 0" % (rid, key))
        for key in ("clamp_hp", "clamp_soul"):
            v = rule[key]
            if v is None:
                continue
            if len(v) != 2 or float(v[0]) <= 0 or float(v[1]) < float(v[0]):
                raise SystemExit("规则 %s 的 %s 必须是 [下限, 上限] 且 0<下限<=上限：%s" % (rid, key, v))
        rules.append(rule)
    if not rules:
        raise SystemExit("randomization.rules 是空的：没有任何位置会被随机")
    return rules, default_rate


# ---------------------------------------------------------------- 逐类预设
# 预设是「用户改过的那份分类规则」：GUI 的逐类编辑器读写它，计划层把它合进规则表。
# 结构（JSON，enemy_presets/*.json）：
#   {"version":1,"name":"...","classes":{"Boss":{"enabled":true,"rate":0.8,
#     "targets":["Boss","MinorBoss"],"source_areas":["base","dlc"],
#     "target_areas":"same","size_max":3.0}, ...}}
# 没列的类 = 继续走 YAML 规则（兼容只改一两个类的局部预设）。

def visible_classes(cfg):
    """界面可见、可参与随机的类：l1_classes 里没标 ui:false 的那些。

    内部标记类（None/Helper/DupeOnly/Dummy/Scarab/CaravanTroll）只用来把
    「不能动」的位置分类，不出现在预设编辑器里，也不当来源。
    """
    return sorted(c for c, v in (cfg.get("l1_classes") or {}).items()
                  if (v or {}).get("ui", True))


def class_alias_map(cfg):
    return {str(k): str(v) for k, v in (cfg.get("class_aliases") or {}).items()}


# ---------------------------------------------------------------- 池（虚拟来源/目标）
# 2026-10-24 用户需求：四个特殊池既能当「来源」，也能让玩家给池内位置选来源。
# 做法：预设里池和类平级，来源引用统一写成 "pool:<池id>"；池条目展开成 match.pools 规则。
POOL_REF_PREFIX = "pool:"
# 「同类型 Boss」引用：Boss 类位置换成**同一类**的 Boss（老类别是杂兵/未知时，换成任意 Boss 级）。
# 用于「Boss 只和自己的种类互随」预设（07），血条位/池位置也能用。
SAME_BOSS_REF = "@sameboss"


def is_same_boss_ref(ref):
    return str(ref) == SAME_BOSS_REF


def is_pool_ref(ref):
    return str(ref).startswith(POOL_REF_PREFIX)


def pool_ref(pid):
    return POOL_REF_PREFIX + str(pid)


def pool_id_of(ref):
    return str(ref)[len(POOL_REF_PREFIX):] if is_pool_ref(ref) else ""


def pool_defs(cfg):
    """yaml 里的池定义 id → {id,name,status,default_on,note}（界面标签用）。"""
    out = {}
    for p in cfg.get("pools") or []:
        pid = str(p.get("id") or "").strip()
        if not pid or pid in out:
            continue
        out[pid] = {"id": pid, "name": str(p.get("name") or pid),
                    "status": p.get("status"),
                    "default_on": bool(p.get("default_on", True)),
                    "note": str(p.get("note") or "")}
    return out


def visible_pools(cfg):
    """可当来源/可单独配置来源的池（yaml pools 全量，按 id 排序）。"""
    return sorted(pool_defs(cfg))


def visible_sources(cfg):
    """预设里能当来源的引用：所有可见类 + 所有池（"pool:<id>"）。"""
    return list(visible_classes(cfg)) + [pool_ref(p) for p in visible_pools(cfg)]


def migrate_preset_classes(entries, cfg):
    """把旧预设迁到现行分类表（2026-10-24）：

    · class_aliases 合并：旧 Mob 的条目/目标/来源权重并进 Basic；
    · 内部标记类（ui:false）的条目直接丢掉 —— 它们不再当来源。
    单条目的数值字段按「合并」语义取：enabled 取或、weight 相加、rate 取大、
    size_max 取小、来源区域取并集、目标区域只要有一边 any 就是 any。
    """
    vis = set(visible_classes(cfg))
    alias = class_alias_map(cfg)

    def _m(c):
        c = str(c)
        seen = set()
        while c in alias and c not in seen:
            seen.add(c)
            c = alias[c]
        return c

    out = {}
    for cls, raw in (entries or {}).items():
        raw = raw or {}
        src = _m(cls)
        if src not in vis:
            continue
        e = out.setdefault(src, {
            "enabled": False, "rate": 0.0, "weight": 0.0, "targets": [],
            "donor_weights": None, "source_areas": [], "target_areas": "same",
            "size_max": None})
        e["enabled"] = e["enabled"] or bool(raw.get("enabled", True))
        try:
            e["rate"] = max(e["rate"], float(raw.get("rate", 1.0)))
        except (TypeError, ValueError):
            pass
        try:
            e["weight"] = e["weight"] + float(raw.get("weight", 0.0))
        except (TypeError, ValueError):
            pass
        # 池引用（"pool:<id>"）不参与类名迁移，原样保留（v1.3.13 起允许池当来源）。
        tg = set()
        for x in (raw.get("targets") or []):
            x = str(x)
            if is_pool_ref(x):
                tg.add(x)
                continue
            x = _m(x)
            if x in vis:
                tg.add(x)
        e["targets"] = sorted(set(e["targets"]) | tg)
        dw = raw.get("donor_weights")
        if isinstance(dw, dict):
            cur_dw = e["donor_weights"] or {}
            for c2, w in dw.items():
                c2 = str(c2)
                if not is_pool_ref(c2):
                    c2 = _m(c2)
                    if c2 not in vis:
                        continue
                try:
                    w = float(w)
                except (TypeError, ValueError):
                    continue
                if w > 0:
                    cur_dw[c2] = cur_dw.get(c2, 0.0) + w
            e["donor_weights"] = cur_dw or None
        sa = [str(x) for x in (raw.get("source_areas") or ["base", "dlc"])
              if str(x) in ("base", "dlc")]
        e["source_areas"] = sorted(set(e["source_areas"]) | set(sa))
        if str(raw.get("target_areas") or "same") == "any":
            e["target_areas"] = "any"
        sm = raw.get("size_max")
        if sm is not None:
            try:
                sm = float(sm)
            except (TypeError, ValueError):
                sm = None
        if sm is not None:
            e["size_max"] = sm if e["size_max"] is None else min(e["size_max"], sm)
    # 合并后 weight 可能超过 100（两类的权重相加）。weight 只按相对比例用，
    # 这里整体等比缩到 ≤100，保持各类之间的比例不变。
    _mx = max((float(e.get("weight") or 0.0) for e in out.values()), default=0.0)
    if _mx > 100.0:
        for e in out.values():
            e["weight"] = float(e.get("weight") or 0.0) * 100.0 / _mx
    return out


def _normalize_preset_pools(raw_pools, cfg, mode, allowed_refs, classes, entries, pools):
    """归一化预设里的池条目 —— 把池当成「虚拟类」：池内位置能从哪些类/池换进来。

    来源引用可以是类名，也可以是 "pool:<id>"（池成员也能当别的类的来源）。
    weight 模式的池条目默认不写 donor_weights：这样池规则回落到该位置所属类的
    全局权重（与内置的传送门/血条规则行为一致），显式写了才用池自己的组成。
    """
    out = {}
    for pid, raw in raw_pools.items():
        pid = str(pid)
        if pid not in pools:
            raise SystemExit("预设引用了未定义的池：%s（可选：%s）" % (
                pid, "、".join(sorted(pools))))
        raw = raw or {}
        rate = raw.get("rate", 1.0)
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise SystemExit("预设池 %s 的 rate 不是数字：%r" % (pid, rate))
        if not (0.0 <= rate <= 1.0):
            raise SystemExit("预设池 %s 的 rate 必须在 0..1：%s" % (pid, rate))
        enabled = bool(raw.get("enabled", True))
        targets = raw.get("targets")
        if targets in (None, "all"):
            targets = []
        targets = [str(x) for x in targets]
        for ref in targets:
            if ref not in allowed_refs:
                raise SystemExit("预设池 %s 的 targets 里有未定义的类/池：%s" % (pid, ref))
        donor_weights = None
        dw_raw = raw.get("donor_weights")
        if dw_raw is not None:
            if not isinstance(dw_raw, dict):
                raise SystemExit("预设池 %s 的 donor_weights 必须是对象" % pid)
            donor_weights = {}
            for ref, w in dw_raw.items():
                ref = str(ref)
                if ref not in allowed_refs:
                    raise SystemExit("预设池 %s 的 donor_weights 里有未定义的类/池：%s" % (pid, ref))
                try:
                    w = float(w)
                except (TypeError, ValueError):
                    raise SystemExit("预设池 %s 的 donor_weights.%s 不是数字：%r" % (pid, ref, w))
                if w < 0:
                    raise SystemExit("预设池 %s 的 donor_weights.%s 不能为负：%s" % (pid, ref, w))
                if w > 0:
                    donor_weights[ref] = w
            if enabled and not donor_weights:
                raise SystemExit("预设池 %s 的 donor_weights 没有任何正权重" % pid)
            if donor_weights:
                targets = sorted(donor_weights)
        if enabled and not targets:
            raise SystemExit("预设池 %s 没有 targets（编辑器里至少勾一个来源类/池）" % pid)
        src = raw.get("source_areas") or ["base", "dlc"]
        src = [str(x) for x in src]
        bad = [x for x in src if x not in ("base", "dlc")]
        if bad or not src:
            raise SystemExit("预设池 %s 的 source_areas 只能是 base/dlc：%s" % (pid, src))
        tgt_area = str(raw.get("target_areas") or "same")
        if tgt_area not in ("same", "any"):
            raise SystemExit("预设池 %s 的 target_areas 只能是 same/any：%s" % (pid, tgt_area))
        size_max = raw.get("size_max")
        if size_max is not None:
            try:
                size_max = float(size_max)
            except (TypeError, ValueError):
                raise SystemExit("预设池 %s 的 size_max 不是数字：%r" % (pid, size_max))
            if size_max <= 0:
                raise SystemExit("预设池 %s 的 size_max 必须 > 0：%s" % (pid, size_max))
        out[pid] = {
            "enabled": enabled,
            "rate": rate if enabled else 0.0,
            "weight": float(raw.get("weight") or 0.0) if enabled else 0.0,
            "targets": targets,
            "donor_weights": donor_weights,
            "source_areas": sorted(set(src)),
            "target_areas": tgt_area,
            "size_max": size_max,
        }
    return out


def _normalize_preset_bar(raw, allowed_refs):
    """归一化预设里的「血条位」条目（可选）。

    有血条的位置 = 真正的 Boss 战。普通预设不写这条，血条位仍走内置的
    bossbar_position 规则（Boss 六类互抽）；写了才覆盖 ——「Boss 只和自己种类
    互随」的预设用它把 141 个血条位也收进同类型语义（@sameboss）。
    """
    if not raw:
        return None
    rate = raw.get("rate", 1.0)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        raise SystemExit("预设血条位的 rate 不是数字：%r" % (rate,))
    if not (0.0 <= rate <= 1.0):
        raise SystemExit("预设血条位的 rate 必须在 0..1：%s" % rate)
    enabled = bool(raw.get("enabled", True))
    targets = raw.get("targets")
    if targets in (None, "all"):
        targets = []
    targets = [str(x) for x in targets]
    for ref in targets:
        if ref not in allowed_refs:
            raise SystemExit("预设血条位的 targets 里有未定义的类/池：%s" % ref)
    donor_weights = None
    dw_raw = raw.get("donor_weights")
    if dw_raw is not None:
        if not isinstance(dw_raw, dict):
            raise SystemExit("预设血条位的 donor_weights 必须是对象")
        donor_weights = {}
        for ref, w in dw_raw.items():
            ref = str(ref)
            if ref not in allowed_refs:
                raise SystemExit("预设血条位的 donor_weights 里有未定义的类/池：%s" % ref)
            try:
                w = float(w)
            except (TypeError, ValueError):
                raise SystemExit("预设血条位的 donor_weights.%s 不是数字：%r" % (ref, w))
            if w < 0:
                raise SystemExit("预设血条位的 donor_weights.%s 不能为负：%s" % (ref, w))
            if w > 0:
                donor_weights[ref] = w
        if enabled and not donor_weights:
            raise SystemExit("预设血条位的 donor_weights 没有任何正权重")
        if donor_weights:
            targets = sorted(donor_weights)
    if enabled and not targets:
        raise SystemExit("预设血条位没有 targets（编辑器里至少勾一个来源）")
    src = raw.get("source_areas") or ["base", "dlc"]
    src = [str(x) for x in src]
    bad = [x for x in src if x not in ("base", "dlc")]
    if bad or not src:
        raise SystemExit("预设血条位的 source_areas 只能是 base/dlc：%s" % (src,))
    tgt_area = str(raw.get("target_areas") or "same")
    if tgt_area not in ("same", "any"):
        raise SystemExit("预设血条位的 target_areas 只能是 same/any：%s" % tgt_area)
    size_max = raw.get("size_max")
    if size_max is not None:
        try:
            size_max = float(size_max)
        except (TypeError, ValueError):
            raise SystemExit("预设血条位的 size_max 不是数字：%r" % (size_max,))
        if size_max <= 0:
            raise SystemExit("预设血条位的 size_max 必须 > 0：%s" % size_max)
    return {"enabled": enabled, "rate": rate if enabled else 0.0,
            "targets": targets, "donor_weights": donor_weights,
            "source_areas": sorted(set(src)), "target_areas": tgt_area,
            "size_max": size_max}


def normalize_preset(preset, cfg):
    """校验并归一化预设；None/空 = 不用预设。

    2.0 起每类新增 donor_weights：{来源类: 权重}，表示「这一类的敌人换进来时，
    各来源类别占多少」。这是参考实现 ClassAssignment.Pools 的 Weight 语义的
    逐类版本；旧预设没有 donor_weights 时，按旧的全局 weight 推导，行为不变。
    2026-10-24 起先过 migrate_preset_classes：旧类名合并、内部类条目丢弃。
    """
    if not preset:
        return None
    if not isinstance(preset, dict):
        raise SystemExit("preset 必须是对象")
    classes = set(visible_classes(cfg))
    pools = set(visible_pools(cfg))
    allowed_refs = classes | {pool_ref(p) for p in pools} | {SAME_BOSS_REF}
    entries = migrate_preset_classes(preset.get("classes") or {}, cfg)
    raw_pools = preset.get("pools") or {}
    if not isinstance(raw_pools, dict):
        raise SystemExit("preset.pools 必须是对象")
    raw_bar = preset.get("bar") or {}
    if not isinstance(raw_bar, dict):
        raise SystemExit("preset.bar 必须是对象")
    if not entries and not raw_pools and not raw_bar:
        return None
    mode = str(preset.get("rate_mode") or "independent")
    if mode not in ("independent", "weight"):
        raise SystemExit("预设 rate_mode 只能是 independent / weight：%s" % mode)
    out = {}
    for cls, raw in entries.items():
        cls = str(cls)
        if cls not in classes:
            raise SystemExit("预设引用了未定义的类：%s" % cls)
        raw = raw or {}
        rate = raw.get("rate", 1.0)
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise SystemExit("预设 %s 的 rate 不是数字：%r" % (cls, rate))
        if not (0.0 <= rate <= 1.0):
            raise SystemExit("预设 %s 的 rate 必须在 0..1：%s" % (cls, rate))
        weight = raw.get("weight", rate * 100.0)
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            raise SystemExit("预设 %s 的 weight 不是数字：%r" % (cls, weight))
        if not (0.0 <= weight <= 100.0):
            raise SystemExit("预设 %s 的 weight 必须在 0..100：%s" % (cls, weight))
        enabled = bool(raw.get("enabled", True))
        targets = raw.get("targets")
        if targets in (None, "all"):
            targets = sorted(classes) if enabled else []
        targets = [str(x) for x in targets]
        for c in targets:
            if c not in allowed_refs:
                raise SystemExit("预设 %s 的 targets 里有未定义的类/池：%s" % (cls, c))

        # 逐类来源权重（参考实现的 ClassAssignment.Pools[i].Weight）
        dw_raw = raw.get("donor_weights")
        donor_weights = None
        if dw_raw is not None:
            if not isinstance(dw_raw, dict):
                raise SystemExit("预设 %s 的 donor_weights 必须是对象" % cls)
            donor_weights = {}
            for c, w in dw_raw.items():
                c = str(c)
                if c not in allowed_refs:
                    raise SystemExit("预设 %s 的 donor_weights 里有未定义的类/池：%s" % (cls, c))
                try:
                    w = float(w)
                except (TypeError, ValueError):
                    raise SystemExit("预设 %s 的 donor_weights.%s 不是数字：%r" % (cls, c, w))
                if w < 0:
                    raise SystemExit("预设 %s 的 donor_weights.%s 不能为负：%s" % (cls, c, w))
                if w > 0:
                    donor_weights[c] = w
            if enabled and not donor_weights:
                raise SystemExit("预设 %s 的 donor_weights 没有任何正权重" % cls)
            if donor_weights:
                targets = sorted(donor_weights)
        elif mode == "weight" and enabled and targets:
            # 旧预设兼容：把全局 weight 摊成这一类的来源权重。
            # 旧 pick_donor 是「按各来源类的全局 weight 抽」，摊到这里后行为完全一致。
            donor_weights = {}
            for c in targets:
                if is_pool_ref(c):
                    donor_weights[c] = 1.0
                    continue
                w = float((entries.get(c) or {}).get("weight") or 0)
                if w > 0:
                    donor_weights[c] = w
            if not donor_weights:
                donor_weights = {c: 1.0 for c in targets}
            targets = sorted(donor_weights)

        if enabled and not targets:
            raise SystemExit("预设 %s 没有 targets（编辑器里至少勾一个目标类）" % cls)
        src = raw.get("source_areas") or ["base", "dlc"]
        src = [str(x) for x in src]
        bad = [x for x in src if x not in ("base", "dlc")]
        if bad or not src:
            raise SystemExit("预设 %s 的 source_areas 只能是 base/dlc：%s" % (cls, src))
        tgt_area = str(raw.get("target_areas") or "same")
        if tgt_area not in ("same", "any"):
            raise SystemExit("预设 %s 的 target_areas 只能是 same/any：%s" % (cls, tgt_area))
        size_max = raw.get("size_max")
        if size_max is not None:
            try:
                size_max = float(size_max)
            except (TypeError, ValueError):
                raise SystemExit("预设 %s 的 size_max 不是数字：%r" % (cls, size_max))
            if size_max <= 0:
                raise SystemExit("预设 %s 的 size_max 必须 > 0：%s" % (cls, size_max))
        out[cls] = {
            "enabled": enabled,
            "rate": rate if enabled else 0.0,
            "weight": weight if enabled else 0.0,
            "targets": targets,
            "donor_weights": donor_weights,
            "source_areas": sorted(set(src)),
            "target_areas": tgt_area,
            "size_max": size_max,
        }
    out_pools = _normalize_preset_pools(raw_pools, cfg, mode, allowed_refs, classes,
                                        entries, pools)
    out_bar = _normalize_preset_bar(raw_bar, allowed_refs)
    return {"name": str(preset.get("name") or "自定义预设"),
            "rate_mode": mode, "classes": out, "pools": out_pools, "bar": out_bar}


def _preset_rule_targets(e, refs):
    """预设条目的 targets：cls 只放类，sources 放完整引用（类 + pool:<id> + @sameboss）。"""
    return {"cls": sorted(r for r in refs
                          if not is_pool_ref(r) and not is_same_boss_ref(r)),
            "areas": ("same" if e["target_areas"] == "same" else ["base", "dlc"]),
            "tier": [], "pools": [],
            "sources": list(refs)}


def preset_rules(preset, rules, cfg, rates=None):
    """把预设展开成规则。

    血条位条目（preset.bar）展开成 match.bar 规则，插在**最前面**（连传送门规则也优先）：
    血条位就是真正的 Boss 战，「Boss 只和自己种类互随」预设靠它覆盖内置的血条规则。
    池条目（preset.pools）展开成 match.pools 规则，插在**所有 YAML 规则之前**：
    池内位置的来源由玩家显式选定，优先于内置的传送门/血条规则。
    类条目（preset.classes）仍插在特殊规则之后（传送门/血条/多阶段优先，不被类预设抢走）。
    条目的 targets 里带 sources：来源可以是类名，也可以是 "pool:<id>"。

    rates 非空时覆盖每条的 rate（权重模式：按各类权重分配出来的实际替换率）。
    """
    if not preset:
        return rules
    pool_names = {p["id"]: p["name"] for p in (cfg.get("pools") or [])}
    made_bar = []
    bar = preset.get("bar")
    if bar and bar.get("enabled") and bar.get("targets"):
        refs = (sorted(bar["donor_weights"]) if bar.get("donor_weights")
                else list(bar["targets"]))
        area = "any" if len(bar["source_areas"]) > 1 else bar["source_areas"][0]
        made_bar.append({
            "id": "preset:bar", "name": "预设：血条位",
            "match": {"cls": [], "pools": [], "area": area, "tier": [],
                      "bar": True, "multiphase": False},
            "rate": (rates or {}).get("bar", bar["rate"]),
            "targets": _preset_rule_targets(bar, refs),
            "donor_weights": (dict(bar["donor_weights"])
                              if bar.get("donor_weights") else None),
            "size_max": bar["size_max"], "size_max_height": None,
            "clamp_hp": None, "clamp_soul": None,
            "note": "preset:bar",
        })
    made_pool = []
    for pid, e in sorted((preset.get("pools") or {}).items()):
        if not e.get("enabled") or not e.get("targets"):
            continue
        refs = (sorted(e["donor_weights"]) if e.get("donor_weights")
                else list(e["targets"]))
        area = "any" if len(e["source_areas"]) > 1 else e["source_areas"][0]
        made_pool.append({
            "id": "preset:pool:%s" % pid,
            "name": "预设：%s" % pool_names.get(pid, pid),
            "match": {"cls": [], "pools": [pid], "area": area, "tier": [],
                      "bar": False, "multiphase": False},
            "rate": (rates or {}).get(pool_ref(pid), e["rate"]),
            "targets": _preset_rule_targets(e, refs),
            "donor_weights": (dict(e["donor_weights"]) if e.get("donor_weights") else None),
            "size_max": e["size_max"], "size_max_height": None,
            "clamp_hp": None, "clamp_soul": None,
            "note": "preset:pool:%s" % pid,
        })
    special = [i for i, r in enumerate(rules)
               if (r["match"].get("pools") or r["match"].get("bar")
                   or r["match"].get("multiphase"))]
    at = (max(special) + 1) if special else 0
    made = []
    for cls, e in sorted(preset["classes"].items()):
        area = "any" if len(e["source_areas"]) > 1 else e["source_areas"][0]
        donor_weights = e.get("donor_weights")
        refs = sorted(donor_weights) if donor_weights else list(e["targets"])
        made.append({
            "id": "preset:%s" % cls, "name": "预设：%s" % cls,
            "match": {"cls": [cls], "pools": [], "area": area, "tier": [],
                      "bar": False, "multiphase": False},
            "rate": (rates or {}).get(cls, e["rate"]),
            "targets": _preset_rule_targets(e, refs),
            "donor_weights": (dict(donor_weights) if donor_weights else None),
            "size_max": e["size_max"], "size_max_height": None,
            "clamp_hp": None, "clamp_soul": None,
            "note": "preset:%s" % cls,
        })
    return made_bar + made_pool + list(rules[:at]) + made + list(rules[at:])


def default_preset(cfg, units=None):
    """编辑器打开时的初始值：把 YAML 规则按类摊平（不含传送门/血条/多阶段那几条）。

    权重默认按该类可随机位置数分配（这样「不改任何东西直接应用」≈ 原来的均匀抽法）；
    编辑器里调某一类的权重，就是调它「在换进来的敌人里占多少」。
    """
    rules, _default_rate = load_rules(cfg)
    classes = visible_classes(cfg)
    counts = {}
    if units:
        for u in units:
            if u.get("policy") == "randomize":
                counts[u["cls"]] = counts.get(u["cls"], 0) + 1
    total = sum(counts.values())
    out = {}
    for cls in classes:
        hit = None
        for r in rules:
            m = r["match"]
            if m.get("pools") or m.get("bar") or m.get("multiphase"):
                continue
            if cls in m.get("cls"):
                hit = r
                break
        if hit is None:
            out[cls] = {"enabled": False, "rate": 0.0, "weight": 0.0, "targets": [],
                        "source_areas": ["base", "dlc"],
                        "target_areas": "same", "size_max": None}
            continue
        area = hit["match"].get("area") or "any"
        src = ["base", "dlc"] if area == "any" else [area]
        tgt = hit["targets"].get("areas")
        w = round(100.0 * counts.get(cls, 0) / total, 3) if total else 100.0
        out[cls] = {
            "enabled": True,
            "rate": float(hit["rate"]),
            "weight": w,
            "targets": list(hit["targets"]["cls"]),
            "source_areas": src,
            "target_areas": "same" if tgt == "same" else "any",
            "size_max": hit.get("size_max"),
        }
    # 池条目：编辑器里同样可编辑（来源可以是类，也可以是别的池）。
    # 默认值照着「内置规则里命中该池的那条规则」摊平；拿不到就置灰，行为回落到 YAML。
    out_pools = {}
    pool_ids = visible_pools(cfg)
    for pid in pool_ids:
        hit = None
        for r in rules:
            if pid in (r["match"].get("pools") or []):
                hit = r
                break
        if hit is None and units:
            for u in units:
                if pid in (u.get("pools") or []):
                    hit = rule_for(u, rules)
                    break
        if hit is None:
            out_pools[pid] = {"enabled": False, "rate": 0.0, "weight": 0.0,
                              "targets": [], "donor_weights": None,
                              "source_areas": ["base", "dlc"],
                              "target_areas": "same", "size_max": None}
            continue
        area = hit["match"].get("area") or "any"
        src = ["base", "dlc"] if area == "any" else [area]
        tgt = hit["targets"].get("areas")
        out_pools[pid] = {
            "enabled": True, "rate": float(hit["rate"]),
            "weight": round(100.0 / max(1, len(pool_ids)), 3),
            "targets": list(hit["targets"]["cls"]),
            "donor_weights": None,
            "source_areas": src,
            "target_areas": "same" if tgt == "same" else "any",
            "size_max": hit.get("size_max"),
        }
    return {"version": 1, "name": "默认（内置规则）", "builtin": True,
            "rate_mode": "weight", "classes": out, "pools": out_pools}


def preset_digest(preset):
    blob = json.dumps(preset or {}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _special_rule(rule):
    """特殊规则：传送门 / 血条位 / 多阶段。它们先于逐类预设，不参与权重分总量。"""
    m = rule.get("match") or {}
    return bool(m.get("pools") or m.get("bar") or m.get("multiphase"))


def donor_weights(preset):
    """权重模式：每个类作为「换入来源」的权重（0 = 不从这里换）。

    参考实现里每个类别池有一个 Weight，实际占比 = 该类 Weight / 所有 Weight 之和。
    我们照同一套语义：权重只决定「换进来的敌人里各类占多少」，不决定有多少位置被换；
    有多少位置被换由底部的总比例（rates.multiplier）控制。
    """
    if not preset or preset.get("rate_mode") != "weight":
        return None
    out = {}
    for ref, e in list(preset["classes"].items()) + [
            (pool_ref(pid), x) for pid, x in (preset.get("pools") or {}).items()]:
        w = float(e.get("weight") or 0)
        if e.get("enabled") and w > 0:
            out[ref] = w
    return out


def class_donor_weights(preset):
    """每类自己的换入来源权重：{目标类: {来源类: 权重}}。

    与 donor_weights() 的全局权重不同：这里每一类可以有自己的组成
    （例如 Basic 80% Basic + 20% Boss，Boss 60% Boss + 40% MinorBoss）。
    """
    if not preset:
        return {}
    out = {}
    for ref, e in list(preset["classes"].items()) + [
            (pool_ref(pid), x) for pid, x in (preset.get("pools") or {}).items()]:
        dw = e.get("donor_weights")
        if dw:
            out[ref] = dict(dw)
    return out


def class_mix_info(preset):
    """给计划/界面看的逐类换入组成（权重与归一化占比）。"""
    if not preset:
        return None
    out = {}
    for cls, e in list(sorted(preset["classes"].items())) + [
            (pool_ref(pid), x) for pid, x in sorted((preset.get("pools") or {}).items())]:
        dw = e.get("donor_weights")
        if not dw:
            continue
        total = sum(float(w) for w in dw.values())
        out[cls] = {
            "weights": {c: round(float(w), 3) for c, w in sorted(dw.items())},
            "share": ({c: round(float(w) / total, 4) for c, w in sorted(dw.items())}
                      if total else {}),
        }
    return out


def weight_info(preset, units):
    """给计划/界面看的权重占比与可用位置数。"""
    if not preset or preset.get("rate_mode") != "weight":
        return None
    w = donor_weights(preset) or {}
    sw = sum(w.values())
    share = {c: round(w[c] / sw, 4) for c in sorted(w)} if sw else {}
    counts = {}
    pool_counts = {}
    for u in units:
        if u.get("policy") != "randomize":
            continue
        counts[u["cls"]] = counts.get(u["cls"], 0) + 1
        for pid in u.get("pools") or []:
            pool_counts[pid] = pool_counts.get(pid, 0) + 1
    eligible = {}
    for ref in sorted(w):
        if is_pool_ref(ref):
            eligible[ref] = pool_counts.get(pool_id_of(ref), 0)
        else:
            eligible[ref] = counts.get(ref, 0)
    return {"weights": {c: round(w[c], 3) for c in sorted(w)},
            "share": share, "eligible": eligible,
            "total_eligible": sum(counts.values())}

def load_donor_deny(cfg):
    """捐赠者黑名单：模型能被换掉，但不能推进别人的位置（换到别处会变成废人）。"""
    rnd = cfg.get("randomization") or {}
    out = {}
    for item in rnd.get("donor_deny") or []:
        model = str(item.get("model") or "").strip()
        if not model:
            raise SystemExit("randomization.donor_deny 里有一条没有 model")
        if model in out:
            raise SystemExit("randomization.donor_deny 里模型重复：%s" % model)
        out[model] = str(item.get("reason") or "")
    return out


def load_ai_fallback(cfg):
    """战斗 AI 兜底：这些模型被当来源时，克隆一份 think 行把 battleGoalID 换成通用 AI。

    用途：传送类敌人（唤声船）的传送是 AI goal 的行为、且依赖地图事件配合；
    换到没有配套事件的地图会原地循环。换 goal = 彻底不传送（实验性，可能改变整套招式）。
    """
    rnd = cfg.get("randomization") or {}
    out = {}
    for item in rnd.get("ai_fallback") or []:
        model = str(item.get("model") or "").strip()
        goal = item.get("goal")
        if not model:
            raise SystemExit("randomization.ai_fallback 里有一条没有 model")
        if model in out:
            raise SystemExit("randomization.ai_fallback 里模型重复：%s" % model)
        try:
            goal = int(goal)
        except (TypeError, ValueError):
            raise SystemExit("randomization.ai_fallback.%s 的 goal 必须是整数：%r" % (model, goal))
        if goal <= 0:
            raise SystemExit("randomization.ai_fallback.%s 的 goal 必须 > 0：%s" % (model, goal))
        out[model] = {"goal": goal, "reason": str(item.get("reason") or "")}
    return out


def load_model_names(path=MODEL_NAMES):
    out = {}
    if not os.path.exists(path):
        return out
    for r in read_csv(path):
        out[r["model"]] = r.get("display_name") or r["model"]
    return out


def load_manual(path=MANUAL):
    """手动指定表：map,entity_id,npc_id,model,note。

    参考实现的 Manual Placement：只对 policy=randomize 的位置生效（independently 不碰
    keep/脚本绑定位），目标用 npc_id 或 model 指定；找不到捐赠位置就跳过并记账。
    """
    if not path or not os.path.exists(path):
        return {}
    out = {}
    for r in read_csv(path):
        mp = (r.get("map") or "").strip()
        ent = _i(r.get("entity_id"))
        npc = _i(r.get("npc_id"))
        mdl = (r.get("model") or "").strip()
        if not mp or not ent or (not npc and not mdl):
            raise SystemExit("手动指定行缺少 map/entity_id 或 npc_id/model：%s" % r)
        out[(mp, ent)] = {"npc_id": npc, "model": mdl,
                          "note": (r.get("note") or "").strip()}
    return out


# ---------------------------------------------------------------- 单元化

def unit_key(row):
    if row["link"]:
        return "link:" + row["link"]
    return "place:%s|%s|%s" % (row["map"], row["part_name"], row["occurrence"])


def unitize(rows):
    """把位置行按 link 合并成替换单元。link 组内身份必须一致（数据校验也管这一条）。"""
    buckets = {}
    for r in rows:
        buckets.setdefault(unit_key(r), []).append(r)
    units = []
    for key in sorted(buckets):
        places = sorted(buckets[key], key=lambda r: (r["map"], r["part_name"], r["occurrence"]))
        head = places[0]
        if len({(p["npc_id"], p["think_id"], p["chara_id"], p["model"]) for p in places}) > 1:
            raise SystemExit("link 组内身份不一致：%s" % key)
        if len({p["policy"] for p in places}) > 1:
            raise SystemExit("link 组内政策不一致：%s" % key)
        if len({p["silo"] for p in places}) > 1:
            raise SystemExit("link 组内 silo 不一致：%s" % key)
        # pools 必须**并集**：同一物理位置的两份 MSB 里，池成员可能只登记在其中一张图上
        # （例：waygate 的 m60_45_37_10，事件却在 m60_45_37_00）。若只取 head 行，
        # 那个位置会丢掉池身份、掉到兜底规则（fauna）被换成普通杂兵 —— 实测踩过。
        pools = sorted(set(p for x in places for p in x["pools"]))
        units.append({
            "key": key, "places": places,
            "map": head["map"], "entity_id": head["entity_id"], "part_name": head["part_name"],
            "occurrence": head["occurrence"], "npc_id": head["npc_id"],
            "think_id": head["think_id"], "chara_id": head["chara_id"], "model": head["model"],
            "cls": head["cls"], "area": head["area"], "silo": head["silo"], "tier": head["tier"],
            "policy": head["policy"], "pools": pools,
            "bar": 1 if any(x.get("bar") for x in places) else 0, "note": head["note"],
            "ref_size": max([_i(x.get("ref_size") or 0) for x in places] or [0]),
            "ref_arena": max([_i(x.get("ref_arena") or 0) for x in places] or [0]),
            "radius": 0.0, "height": 0.0, "hp": 0, "soul": 0, "name": "",
        })
    return units


# ---------------------------------------------------------------- 选项与种子

def merge_options(over):
    opts = json.loads(json.dumps(DEFAULT_OPTIONS))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(opts.get(k), dict):
            opts[k].update(v)
        else:
            opts[k] = v
    try:
        hp_scale = float((opts.get("scaling") or {}).get("hp") or 1.0)
    except (TypeError, ValueError):
        raise SystemExit("scaling.hp 必须是数字")
    if hp_scale <= 0:
        raise SystemExit("scaling.hp 必须 > 0")
    opts["scaling"] = {"hp": hp_scale}
    feat = opts.setdefault("features", {})
    try:
        ons = float(feat.get("onslaught") or 1.0)
    except (TypeError, ValueError):
        raise SystemExit("features.onslaught 必须是数字")
    if ons < 1.0:
        ons = 1.0
    if ons > ONSLAUGHT_MAX:
        ons = ONSLAUGHT_MAX
    feat["onslaught"] = ons
    return opts


def seed_material(options, seed, data_hashes):
    """进种子的东西：只包含「会让全部单元重排」的项 —— 版本、种子、数据指纹。

    刻意**不进**：池开关、规则表、百分比、clamp。
    每个单元的 RNG 都是 sha256(base_seed+"|"+unit_key) 独立派生的，所以
    「关一个池」「改一条规则的百分比」只会动受它影响的那批单元，其它单元一个字节都不变
    （M1 验收①的第二种形态）；规则表或数据本身改了 → data_hashes 变 → 全量重排，这是有意的。
    """
    material = {"plan_version": PLAN_VERSION, "seed": seed, "data": data_hashes}
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unit_rng(base_seed, key):
    h = hashlib.sha256((base_seed + "|" + key).encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def rate_for(options, unit, rule):
    """生效百分比：规则给基数 → 逐类/逐 silo 绝对覆盖 → 全局倍率（乘完再夹到 0..1）。"""
    rates = options["rates"]
    base = float(rule["rate"]) if rule else float(rates.get("default", 0.0))
    if unit["cls"] in (rates.get("by_class") or {}):
        base = float(rates["by_class"][unit["cls"]])
    elif unit["silo"] in (rates.get("by_silo") or {}):
        base = float(rates["by_silo"][unit["silo"]])
    return clamp(base * float(rates.get("multiplier", 1.0)), 0.0, 1.0)


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ---------------------------------------------------------------- 候选

def _match(unit, rule):
    """这条规则管不管这个位置（match 全写 = 与关系）。"""
    m = rule["match"]
    if m["cls"] and unit["cls"] not in m["cls"]:
        return False
    if m["pools"] and not (set(m["pools"]) & set(unit["pools"])):
        return False
    if m["area"] not in ("any", "") and unit["area"] != m["area"]:
        return False
    if m["tier"] and unit["tier"] not in m["tier"]:
        return False
    if m.get("bar") and not unit.get("bar"):
        return False
    if m.get("multiphase") and not unit.get("multiphase"):
        return False
    return True


def rule_for(unit, rules):
    """有序规则表：第一条命中的生效；都没命中 → None（保持原样）。"""
    for r in rules:
        if _match(unit, r):
            return r
    return None


def _size_ok(unit, donor, rule, options):
    cons = options["constraints"]
    # 参考实现的 safe mode：位置有 arena 档、模型有 size 档时，size 不能超过场地档。
    # 缺任一档就不拦（法魂新增模型没有参考标注，不能因此把它们全挡掉）。
    if (cons.get("arena_safety", True) and not cons.get("ignore_size")
            and int(unit.get("ref_arena") or 0) > 0 and int(donor.get("ref_size") or 0) > 0
            and int(donor["ref_size"]) > int(unit["ref_arena"])):
        return False
    cap = rule.get("size_max")
    cap = float(cons.get("size_max", 3.0)) if cap is None else float(cap)
    cap_h = rule.get("size_max_height")
    cap_h = float(cons.get("size_max_height", cap)) if cap_h is None else float(cap_h)
    ur, uh = unit["radius"], unit["height"]
    dr, dh = donor["radius"], donor["height"]
    if ur > 0 and dr > 0 and dr > ur * cap + 1e-9:
        return False
    if uh > 0 and dh > 0 and dh > uh * cap_h + 1e-9:
        return False
    band = _hp_band(rule, options)
    if band:
        lo, hi = band
        uh_hp, d_hp = unit["hp"], donor["hp"]
        if uh_hp > 0 and d_hp > 0:
            if d_hp > uh_hp * hi + 1e-9 or d_hp < uh_hp * lo - 1e-9:
                return False
    return True


def _size_only_ok(unit, donor, rule, options):
    """只管体型、不管血量带 —— 用来分辨「没候选」是体型卡住还是血量带卡住。"""
    cons = options["constraints"]
    if (cons.get("arena_safety", True) and not cons.get("ignore_size")
            and int(unit.get("ref_arena") or 0) > 0 and int(donor.get("ref_size") or 0) > 0
            and int(donor["ref_size"]) > int(unit["ref_arena"])):
        return False
    cap = rule.get("size_max")
    cap = float(cons.get("size_max", 3.0)) if cap is None else float(cap)
    cap_h = rule.get("size_max_height")
    cap_h = float(cons.get("size_max_height", cap)) if cap_h is None else float(cap_h)
    ur, uh = unit["radius"], unit["height"]
    dr, dh = donor["radius"], donor["height"]
    if ur > 0 and dr > 0 and dr > ur * cap + 1e-9:
        return False
    if uh > 0 and dh > 0 and dh > uh * cap_h + 1e-9:
        return False
    return True


def _hp_band(rule, options):
    """候选血量带（相对原位置 hp），可选；没配就返回 None = 不限。

    注意：它只筛候选，不决定最终强度 —— 换完的 HP 走 _target_hp_for（默认换入者
    血量；普通→Boss 且原位置更厚时取 sqrt(原×换入)），魂默认保留位置原值。
    """
    v = (rule or {}).get("hp_band")
    if v:
        return float(v[0]), float(v[1])
    v = options["constraints"].get("hp_band")
    if v:
        return float(v[0]), float(v[1])
    return None


def _clamp_of(rule, which, options):
    v = rule.get("clamp_" + which)
    if v:
        return float(v[0]), float(v[1])
    lo, hi = options["clamp"][which]
    return float(lo), float(hi)


def _donor_group_key(unit, rule):
    return unit["area"] if rule["targets"]["areas"] == "same" else "*"


def donor_units(units, options, deny=None):
    """所有可当来源的单元（扁平，顺序固定 = (类, npc_id, key)）。

    只收 policy=randomize：keep 的位置不写，同模型在别处若仍是 randomize 就自然还在候选里
    —— 这是设计 §4「keep 可以作为源」的落地方式；要让 keep 也当源，
    把 constraints.include_keep_as_source 打开（多阶段 Boss 会被拉进来源池，默认关）。
    """
    include_keep = bool(options["constraints"].get("include_keep_as_source"))
    ok_policy = ("randomize", "keep", "source_only") if include_keep else ("randomize",)
    deny = deny or {}
    out = []
    for u in units:
        if u["policy"] not in ok_policy or not u["cls"]:
            continue
        if u["model"] in deny:
            continue          # 位置依赖型敌人：换到别处会不攻击/原地传送/只剩壳
        if u["npc_id"] == 0 or u["model"] == "c0000":
            continue          # 0 / 占位模型不是身份
        if int(u.get("think_id") or 0) <= 0:
            continue          # think=0 的捐赠者换过去没有 AI，换进战斗位会站桩
        if re.search(r"\bSound\b", u["part_name"], re.I):
            continue          # 声音/演出占位：它带 Boss 的 npc 但不战斗，不能当源
        if u["hp"] <= 0:
            continue          # 没有数值就没法算缩放系数，不能当源
        out.append(u)
    out.sort(key=lambda u: (u["cls"], u["npc_id"], u["key"]))
    return out


def build_rule_donors(rules, donors):
    """每条规则的来源池（按 targets 的类/区域/tier/池预筛）。

    返回 {rule_id: {组键: [单元…]}}；组键 = 单元自身区域（areas: same）或 "*"（明确指定了区域）。
    规则内顺序固定，抽样才可复现。
    """
    by_cls = {}
    for d in donors:
        by_cls.setdefault(d["cls"], []).append(d)
    by_pool = {}
    for d in donors:
        for pid in d.get("pools") or []:
            by_pool.setdefault(pid, []).append(d)
    out = {}
    for r in rules:
        t = r["targets"]
        lst = []
        sources = t.get("sources") or []
        if sources:
            # 预设规则：来源可以是类名，也可以是池（"pool:<id>"）。池里的成员当来源，
            # 不管它本身是什么类 —— 这正是「四个特殊池能当来源」的落地。
            seen = set()
            for ref in sources:
                if is_same_boss_ref(ref):
                    # 「同类型 Boss」：规则级只能先收六类 Boss 全部，具体同不同类
                    # 由 size_candidates 按单元自己的类别再筛（同一个位置只留同类）。
                    part = []
                    for c in sorted(AREA_BOSSISH):
                        part.extend(by_cls.get(c) or [])
                elif is_pool_ref(ref):
                    part = by_pool.get(pool_id_of(ref)) or []
                else:
                    part = by_cls.get(ref) or []
                for d in part:
                    if d["key"] in seen:
                        continue
                    seen.add(d["key"])
                    lst.append(d)
        else:
            for c in t["cls"]:
                lst.extend(by_cls.get(c, []))
        lst.sort(key=lambda d: (d["npc_id"], d["key"]))
        if t["tier"]:
            lst = [d for d in lst if d["tier"] in t["tier"]]
        if t["pools"]:
            want = set(t["pools"])
            lst = [d for d in lst if set(d["pools"]) & want]
        if t["areas"] == "same":
            groups = {a: [d for d in lst if d["area"] == a] for a in ("base", "dlc")}
        else:
            allowed = set(t["areas"])
            groups = {"*": [d for d in lst if d["area"] in allowed]}
        out[r["id"]] = groups
    return out


def _named_ok(unit, donor, options, named):
    """有血条的位置只接受「有血条名」的换入模型。

    has_bar_name 覆盖两种情况：EMEVD 里真有血条事件（bar=1），以及
    enemy_bar_names.csv 里记着这个名字（有些位置的血条调用藏在参数转交/别名里，
    bar 列没扫到，但换进无名模型同样会让血条显示错名字）。
    """
    if not (unit.get("bar") or unit.get("has_bar_name")):
        return True
    if not options["constraints"].get("require_named_donor_for_bar", True):
        return True
    return donor["model"] in (named or ())


def size_candidates(unit, rule, groups, options, cache, named=None):
    """体型过滤后的候选（按 (规则, 区域, 半径, 身高, 是否血条位) 缓存）。

    模型/身份排除不在这里做：同模型的捐赠者只占千分之几，用抽样拒绝处理即可，
    这样每个单元的成本和候选池大小无关。
    """
    # 缓存键按「规则实际产生的候选集合」算，而不是按 rule id：预设会给每个类各造一条规则，
    # 若按 id 缓存，同样的 targets/体型要重复扫 16 遍（22,000 条 × 16，实测能拖到数分钟）。
    sig = (tuple(rule["targets"]["cls"]), tuple(rule["targets"].get("sources") or ()),
           str(rule["targets"]["areas"]),
           rule.get("size_max"), rule.get("size_max_height"),
           tuple(rule.get("hp_band") or ()), bool(options["constraints"].get("ignore_size")),
           bool(options["constraints"].get("arena_safety", True)))
    same_boss = SAME_BOSS_REF in (rule["targets"].get("sources") or ())
    key = (sig, _donor_group_key(unit, rule),
           unit["radius"], unit["height"], round(unit["hp"], 3),
           unit.get("ref_arena") or 0,
           1 if (unit.get("bar") or unit.get("has_bar_name")) else 0,
           unit["cls"] if same_boss else "")
    hit = cache.get(key)
    if hit is None:
        hit = [d for d in (groups.get(_donor_group_key(unit, rule)) or [])
               if _size_ok(unit, d, rule, options) and _named_ok(unit, d, options, named)]
        if same_boss:
            # 「同类型 Boss」：Boss 类位置只换同类 Boss；老类别不是 Boss（参考数据把
            # 某些真 Boss 标成了杂兵）时换成任意 Boss 级，免得真 Boss 战变成杂兵。
            if unit["cls"] in AREA_BOSSISH:
                hit = [d for d in hit if d["cls"] == unit["cls"]]
            else:
                hit = [d for d in hit if d["cls"] in AREA_BOSSISH]
        cache[key] = hit
    return hit


def pick_donor(unit, cand, rng, require_model_change, weights=None,
               fallback_weights=None):
    """在 size-ok 候选里抽一个「身份不同」的捐赠者。

    给了 weights 就先按「来源类别」的权重抽一个类，再在该类里等概率抽；
    这样每类权重就是「换进来的敌人里这一类占多少」，与参考实现的 pool Weight 同义。
    weights 通常是「这一类自己的来源百分比」；若其中没有任何类落在候选里
    （例如特殊规则把目标池换掉了），用 fallback_weights 再试一次，最后才放弃。
    没给 weights 时仍是全体等概率（旧行为）。
    """
    if weights is not None:
        def _by_class(w):
            # 权重键可以是类名，也可以是 "pool:<id>"：同一只怪若同时命中类与池两个
            # 引用，会同时计入两组（各自按权重抽组，再组内等概率）——这是有意的：
            # 池身份比泛类更具体，玩家同时勾选时两边都应被抽到。
            groups = {}
            for d in cand:
                hit = []
                if float(w.get(d["cls"]) or 0) > 0:
                    hit.append(d["cls"])
                for pid in d.get("pools") or []:
                    ref = pool_ref(pid)
                    if float(w.get(ref) or 0) > 0:
                        hit.append(ref)
                if float(w.get(SAME_BOSS_REF) or 0) > 0:
                    if unit["cls"] in AREA_BOSSISH:
                        if d["cls"] == unit["cls"]:
                            hit.append(SAME_BOSS_REF)
                    elif d["cls"] in AREA_BOSSISH:
                        hit.append(SAME_BOSS_REF)
                for ref in hit:
                    groups.setdefault(ref, []).append(d)
            return groups
        by_cls = _by_class(weights)
        if not by_cls and fallback_weights:
            weights = fallback_weights
            by_cls = _by_class(weights)
        if not by_cls:
            # 来源组成里没有任何类落在候选池（典型：特殊规则把目标池换成了
            # 另一类）：退回候选池内等概率，而不是把整个位置跳过。
            weights = None
        if weights is not None:
            total = sum(float(weights[c]) for c in by_cls)
            pick = rng.random() * total
            chosen = None
            for c in sorted(by_cls):
                pick -= float(weights[c])
                if pick <= 0:
                    chosen = c
                    break
            cand = by_cls[chosen or sorted(by_cls)[-1]]
    n = len(cand)
    if n == 0:
        return None
    for _ in range(64):
        d = cand[rng.randrange(n)]
        if require_model_change and d["model"] == unit["model"]:
            continue
        if d["npc_id"] == unit["npc_id"]:
            continue
        return d
    allowed = [d for d in cand
               if (not require_model_change or d["model"] != unit["model"])
               and d["npc_id"] != unit["npc_id"]]
    if not allowed:
        return None
    return allowed[rng.randrange(len(allowed))]


# ---------------------------------------------------------------- 计划

def _place_out(p, npc):
    return {
        "map": p["map"], "part_name": p["part_name"], "occurrence": p["occurrence"],
        "entity_id": p["entity_id"], "old_npc_id": p["npc_id"],
        "old_think_id": p["think_id"], "old_chara_id": p["chara_id"], "old_model": p["model"],
    }


def _entry_for(u, d, rule, options, reasons, ai_fallback, extra=None):
    """由「目标单元 + 捐赠单元」生成一条计划条目与它覆盖的 positions。

    数值模型在这里统一：HP 默认写换入者（普通→Boss 且原位置更厚时取 sqrt），
    魂默认写位置原值；区域差由写盘层的 area SpEffect 负责。
    """
    constraints = options["constraints"]
    feat = options.get("features") or {}
    scale_hp = float((options.get("scaling") or {}).get("hp") or 1.0)
    target_hp = _target_hp_for(u["hp"], d["hp"], u["cls"], d["cls"], scale_hp)
    hp_model = ("bosshp" if (u["cls"] in AREA_NORMALISH and d["cls"] in AREA_BOSSISH
                             and u["hp"] > d["hp"] and d["hp"] > 0) else "donor")
    # 参考实现的 swaprewards：换 Boss 时卢恩跟换入者走（默认关 = 保留位置原值，F3 的掉落绑地点）
    target_soul = (d["soul"] if feat.get("soul_follow") and d["soul"] > 0 else
                   (u["soul"] if u["soul"] > 0 else None))
    coef_hp = (u["hp"] / float(d["hp"])) if d["hp"] > 0 else None
    coef_soul = (u["soul"] / float(d["soul"])) if (u["soul"] > 0 and d["soul"] > 0) else None

    reasons = list(reasons)
    reasons.append("target:%s→%s[%s]" % (u["cls"], d["cls"], d["area"]))
    fb = ai_fallback.get(d["model"])
    if fb:
        reasons.append("ai:goal=%d（%s）" % (fb["goal"], fb["reason"] or "去传送"))
    band = _hp_band(rule, options)
    reasons.append("guard:model_change=%s,size<=%sx/%sx,hp_band=%s" % (
        constraints.get("require_model_change"),
        rule.get("size_max") or constraints.get("size_max"),
        rule.get("size_max_height") or constraints.get("size_max_height"),
        "off" if not band else "%.2f-%.2f" % band))
    reasons.append("target:hp=%s,soul=%s（HP 模型%s直接写克隆行）" % (
        _fmt(target_hp), _fmt(target_soul),
        "" if abs(scale_hp - 1.0) < 1e-9 else " × %.2f 全局倍率" % scale_hp))
    reasons.append("coef:hp=%s,soul=%s（换入者原值 ÷ 位置值，仅记录）" % (
        _fmt(coef_hp), _fmt(coef_soul)))

    entry = {
        "key": u["key"], "rule": rule["id"],
        "silo": u["silo"], "cls": u["cls"], "tier": u["tier"], "area": u["area"],
        "pools": u["pools"], "policy": u["policy"],
        "places": [_place_out(p, None) for p in u["places"]],
        "old_npc_id": u["npc_id"], "old_model": u["model"], "old_cls": u["cls"],
        "new_npc_id": d["npc_id"], "new_think_id": d["think_id"],
        "new_chara_id": d["chara_id"], "new_model": d["model"], "new_cls": d["cls"],
        "new_area": d["area"], "donor_cls": d["cls"], "new_pools": list(d.get("pools") or []),
        "ai_goal": (ai_fallback.get(d["model"]) or {}).get("goal"),
        "donor_key": d["key"], "donor_map": d["map"], "donor_entity": d["entity_id"],
        "owner": options["owner"],
        "coef_hp": round(coef_hp, 6) if coef_hp is not None else None,
        "coef_soul": round(coef_soul, 6) if coef_soul is not None else None,
        "hp_model": hp_model,
        "target_hp": target_hp, "target_soul": target_soul,
        "reason": " | ".join(reasons),
    }
    if extra:
        entry.update(extra)
    pos_out = []
    for p in entry["places"]:
        item = {
            "map": p["map"], "part_name": p["part_name"], "occurrence": p["occurrence"],
            "entity_id": p["entity_id"], "unit": u["key"],
            "old_npc_id": p["old_npc_id"], "new_npc_id": d["npc_id"],
            "new_think_id": d["think_id"], "new_chara_id": d["chara_id"],
            "new_model": d["model"], "owner": options["owner"],
            "coef_hp": entry["coef_hp"], "coef_soul": entry["coef_soul"],
            "target_hp": entry["target_hp"], "target_soul": entry["target_soul"],
            "silo": u["silo"], "pools": u["pools"], "rule": rule["id"],
            "reason": entry["reason"],
        }
        if extra:
            for k in ("multiphase", "phase", "mp_policy", "donor_group"):
                if k in extra:
                    item[k] = extra[k]
        pos_out.append(item)
    return entry, pos_out


def _onslaught_ok(u, e):
    """一个替换单元能不能再复制出 1~2 个普通敌人（Enemy Onslaught 实验）。

    这是**加怪**，不是换人：只挑没有事件/血条/池/多阶段/重复 MSB 依赖的普通敌人。
    复制体沿用同一个克隆 NpcParam 行（数值、掉落、颜色完全一致），也不改 EMEVD ——
    所以原敌人的事件（如果有）不会作用到复制体；这也是为什么只放行普通敌人。
    """
    if e.get("manual") or u.get("policy") != "randomize":
        return False
    if u.get("cls") not in ONSLAUGHT_CLASSES:
        return False
    if u.get("pools") or u.get("bar") or u.get("evt") or u.get("link"):
        return False
    if len(u.get("places") or []) != 1:
        return False
    if int(u.get("npc_id") or 0) <= 0 or u.get("model") == "c0000":
        return False
    if int(u.get("think_id") or 0) <= 0 or float(u.get("hp") or 0) <= 0:
        return False
    p = u["places"][0]
    if int(p.get("entity_id") or 0) <= 0:
        return False
    if "Sound" in (p.get("part_name") or ""):
        return False
    return True


def _apply_onslaught(plan_units, by_key, options, base_seed):
    """给每个条目算 dup_count（0/1/2）。不消耗主抽样 RNG，改开关不会重排其它单元。"""
    factor = float((options.get("features") or {}).get("onslaught") or 1.0)
    if factor <= 1.0:
        return 0, 0
    whole = int(factor - 1.0)
    frac = (factor - 1.0) - whole
    n_units = n_dups = 0
    for e in plan_units:
        u = by_key.get(e["key"])
        if u is None or not _onslaught_ok(u, e):
            continue
        extra = whole
        if extra < int(ONSLAUGHT_MAX - 1.0) and frac > 0:
            rng = unit_rng(base_seed, "onslaught|" + u["key"])
            if rng.random() < frac:
                extra += 1
        # 3.0× 时 whole=2，正好是上限；小数部分不再额外加。
        extra = min(extra, int(ONSLAUGHT_MAX - 1.0))
        if extra > 0:
            e["dup_count"] = extra
            n_units += 1
            n_dups += extra
    return n_units, n_dups


def _boss_cap_filter(cand, boss_use, cap, stats):
    """Boss 使用上限：同一个 Boss（npc_id）最多被随到 cap 次（0 = 不限）。

    只对 Boss 六类计数；候选全被上限挡住时退回完整候选并记一次 relaxed
    （否则小池子/同区域约束下会出现「没得选就整片不换」）。
    """
    if not cap:
        return cand
    keep = [d for d in cand
            if not (d["cls"] in AREA_BOSSISH
                    and int(boss_use.get(int(d["npc_id"]), 0)) >= cap)]
    if keep:
        return keep
    if cand:
        stats["relaxed"] = stats.get("relaxed", 0) + 1
    return cand


def _multiphase_plan(units, groups, rules, options, ai_fallback, base_seed,
                     rule_donors=None, size_cache=None, named_models=None,
                     boss_use=None, boss_cap=0, cap_stats=None):
    """v1.2：多阶段 Boss 按「转阶段是否换模型」分流（只处理 kind=phase & swap=true 的组）。

    - 阶段模型相同（one_boss）：整场共用一个换入 Boss（各阶段同一 npc 行、同一份血量）；
    - 阶段模型不同（per_phase_model）：每阶段各换一个**不同的** Boss
      （换入模型互不相同、也都不等于任一阶段原模型，保证转阶段看得见变化）。
    - 有 CreateReferredDamagePair 绑定的组（swap=false）一律不动：拆开会坏档（H-034/H-039）。
    返回 (entries, positions, handled_keys, info, skipped_groups, skipped_units)；
    info[gid] = {"policy", "phases", "donors": [npc_id…]}（跳过时带 "skipped"）。
    """
    cons = options["constraints"]
    if not cons.get("multiphase_swap"):
        return [], [], set(), {}, [], []
    mp_rule = next((r for r in rules if r["id"] == "multiphase_boss"), None)
    if mp_rule is None:
        raise SystemExit("打开了 multiphase_swap，但 yaml 里没有 multiphase_boss 规则")
    rule_donors = rule_donors or {}
    size_cache = {} if size_cache is None else size_cache
    named_models = named_models or ()

    by_place = {}
    for u in units:
        for p in u["places"]:
            by_place[(p["map"], p["entity_id"])] = u

    swap = [g for g in groups
            if bool(g.get("swap")) and str(g.get("kind") or "phase") == "phase"]
    groups_units = {}
    for g in swap:
        us = [by_place.get((g["map"], _i(e))) for e in g["phases"]]
        if any(u is None for u in us):
            raise SystemExit("多阶段组 %s 有阶段不在位置表里：%s" % (
                g.get("id"), [e for e, u in zip(g["phases"], us) if u is None]))
        groups_units[g["id"]] = us

    donor_groups = rule_donors.get(mp_rule["id"]) or {}
    boss_use = {} if boss_use is None else boss_use
    cap_stats = {} if cap_stats is None else cap_stats

    def _cap_filter(cand):
        return _boss_cap_filter(cand, boss_use, boss_cap, cap_stats)

    def _cand_of(unit):
        cand = size_candidates(unit, mp_rule, donor_groups, options, size_cache, named_models)
        if mp_rule["targets"]["areas"] == "same":
            same = [d for d in cand if d["area"] == unit["area"]]
            return same
        return cand

    entries, positions, handled = [], [], set()
    info, skipped, skipped_units = {}, [], []
    require_model = bool(cons.get("require_model_change", True))

    for g in swap:
        tus = groups_units[g["id"]]
        models = {u["model"] for u in tus}
        policy = "one_boss" if len(models) == 1 else "per_phase_model"
        donors = []
        if policy == "one_boss":
            base_u = tus[0]
            cand = [d for d in _cand_of(base_u)
                    if all(_size_ok(x, d, mp_rule, options)
                           and _named_ok(x, d, options, named_models) for x in tus)]
            cand = _cap_filter(cand)
            if cand:
                d = pick_donor(base_u, cand, unit_rng(base_seed, "mp:%s:one" % g["id"]),
                               require_model)
                if d is not None:
                    donors = [d] * len(tus)
        else:
            used = set()
            for idx, tu in enumerate(tus):
                rng = unit_rng(base_seed, "mp:%s:phase%d" % (g["id"], idx + 1))
                cand = _cap_filter([d for d in _cand_of(tu)
                                    if d["model"] not in used and d["model"] not in models])
                d = pick_donor(tu, cand, rng, True)
                if d is None:
                    cand = _cap_filter([d for d in _cand_of(tu) if d["model"] not in used])
                    d = pick_donor(tu, cand, rng, require_model)
                if d is None:
                    donors = []
                    break
                donors.append(d)
                used.add(d["model"])
        if not donors:
            skipped.append(g["id"])
            info[g["id"]] = {"policy": policy, "phases": len(tus),
                             "skipped": "no_mp_donor"}
            for u in tus:
                skipped_units.append((u, g["id"]))
                handled.add(u["key"])
            continue
        for idx, (tu, du) in enumerate(zip(tus, donors)):
            reasons = ["rule:%s" % mp_rule["id"],
                       "multiphase:%s:phase%d" % (g["id"], idx + 1),
                       "mp_policy:%s" % policy]
            if tu["silo"]:
                reasons.append("silo:%s" % tu["silo"])
            extra = {"multiphase": g["id"], "phase": idx + 1, "mp_policy": policy}
            entry, pos = _entry_for(tu, du, mp_rule, options, reasons, ai_fallback, extra)
            entries.append(entry)
            positions.extend(pos)
            handled.add(tu["key"])
            if du["cls"] in AREA_BOSSISH:
                _n = int(du["npc_id"])
                boss_use[_n] = boss_use.get(_n, 0) + 1
        info[g["id"]] = {"policy": policy, "phases": len(tus),
                         "donors": [int(d["npc_id"]) for d in donors]}
    return entries, positions, handled, info, skipped, skipped_units


def build_plan(data, options=None, seed=1):
    """纯函数：data = {places, npc, cfg, pools, multiphase, hashes}。返回 plan dict。"""
    options = merge_options(options)
    units = unitize(data["places"])
    multiphase, groups = data["multiphase"]

    # 数值与名字回填
    bar_places = (data.get("bar") or ({}, {}))[0]
    for u in units:
        s = data["npc"].get(u["npc_id"])
        if s:
            u["hp"], u["soul"] = s["hp"], s["soul"]
            u["radius"], u["height"] = s["radius"], s["height"]
            u["name"] = s["name"]
        # 有血条名字的位置（不论 EMEVD 扫描是否标了 bar）：换入者必须有名字，否则血条会顶着原名
        u["has_bar_name"] = 1 if any(
            (p["map"], p["entity_id"]) in bar_places for p in u["places"]) else 0

    rules, default_rate = data["rules"]
    # 参考实现的 Oops All：所有可随机位置都换成同一个类别的敌人。
    # 它压过普通规则/预设（但仍然只作用于 policy=randomize 的位置，keep 一律不动）。
    oops_all = options.get("oops_all")
    if oops_all:
        oops_all = str(oops_all).strip()
        valid_cls = set(visible_classes(data["cfg"]))
        if oops_all not in valid_cls:
            raise SystemExit("oops_all 不是界面可见的类别：%s（可选：%s）" % (
                oops_all, "、".join(sorted(valid_cls))))
        rules = [{
            "id": "oops_all", "name": "全替换为 %s" % oops_all,
            "match": {"cls": [], "pools": [], "area": "any", "tier": [],
                      "bar": False, "multiphase": False},
            "rate": 1.0,
            "targets": {"cls": [oops_all], "areas": ["base", "dlc"], "tier": [], "pools": []},
            "size_max": 99.0, "size_max_height": 99.0,
            "clamp_hp": None, "clamp_soul": None,
            "note": "Oops All：所有可随机位置换成 %s" % oops_all,
        }]
        default_rate = 0.0
        # 全替换为某类时，有血条的位置也照换；没名字的换入者保留原血条名（写盘层会跳过）。
        options["constraints"]["require_named_donor_for_bar"] = False
    # Oops All 压过预设：否则界面上残留的逐类预设会把规则改回去。
    preset = None if oops_all else normalize_preset(options.get("preset"), data["cfg"])
    preset_info = None
    donor_weight_map = None
    preset_class_weights = {}
    if preset:
        # 每一类自己的换入来源百分比（2.0）：优先于旧的全局 weight。
        preset_class_weights = class_donor_weights(preset)
        if preset.get("rate_mode") == "weight":
            # 权重叠加（参考实现语义）：有多少位置被换由底部总比例（multiplier）控制；
            # 换进来的是谁由每一类自己的 donor_weights 决定。
            donor_weight_map = donor_weights(preset)
            rates = {c: (1.0 if e["enabled"] else 0.0)
                     for c, e in preset["classes"].items()}
            for pid, e in (preset.get("pools") or {}).items():
                rates[pool_ref(pid)] = 1.0 if e.get("enabled") else 0.0
            rules = preset_rules(preset, rules, data["cfg"], rates=rates)
            preset_info = {"mode": "weight",
                           "info": weight_info(preset, units),
                           "by_class": class_mix_info(preset)}
        else:
            rules = preset_rules(preset, rules, data["cfg"])
            preset_info = {"mode": "independent",
                           "by_class": class_mix_info(preset)}
    deny = data.get("donor_deny") or {}
    ai_fallback = data.get("ai_fallback") or {}
    manual = data.get("manual") or {}
    donors = donor_units(units, options, deny)
    manual_pool = [x for x in units
                   if x["npc_id"] and x["model"] != "c0000"
                   and int(x.get("think_id") or 0) > 0 and x["hp"] > 0]
    manual_hits = 0
    rule_donors = build_rule_donors(rules, donors)
    named_models = (data.get("bar") or ({}, {}))[1]
    size_cache = {}
    base_seed = seed_material(options, seed, data["hashes"])
    enabled_pools = {k for k, v in options["pools"].items() if v}
    constraints = options["constraints"]
    # v1.3.13：Boss 使用上限（同一个 Boss 最多被随到几次）。
    boss_cap = int(constraints.get("boss_usage_cap") or 0)
    boss_use = {}
    cap_stats = {"relaxed": 0}

    plan_units, skips, positions = [], [], []
    stats = {"clamped_hp": 0, "clamped_soul": 0, "no_candidate_units": 0}
    by_rule = {}

    # v1.2：先把多阶段 Boss 处理掉（默认关 = 空操作），主循环再跳过它们。
    mp_entries, mp_positions, mp_handled, mp_info, mp_skipped, mp_skip_units = _multiphase_plan(
        units, groups, rules, options, ai_fallback, base_seed,
        rule_donors=rule_donors, size_cache=size_cache, named_models=named_models,
        boss_use=boss_use, boss_cap=boss_cap, cap_stats=cap_stats)
    plan_units.extend(mp_entries)
    positions.extend(mp_positions)
    for e in mp_entries:
        by_rule[e["rule"]] = by_rule.get(e["rule"], 0) + 1
    for u in units:
        if u["key"] in mp_handled:
            u["multiphase"] = 1
    for u, gid in mp_skip_units:
        stats["no_candidate_units"] += 1
        skips.append(_skip(u, "no_candidate:no_mp_donor",
                           "多阶段组 %s 没有体型/名字合适的换入 Boss" % gid))

    for u in units:
        reasons = []
        if u["key"] in mp_handled:
            continue
        if u["policy"] != "randomize":
            skips.append(_skip(u, "policy:%s" % u["policy"], u["note"]))
            continue
        if (u["map"], u["entity_id"]) in multiphase:
            raise SystemExit("多阶段位置被标成 randomize（数据错误）：%s / %s" % (u["map"], u["entity_id"]))
        if u["hp"] <= 0:
            skips.append(_skip(u, "no_stats:hp", "取不到数值"))
            continue

        # 手动指定优先于池/规则/比例（参考 Manual Placement）：仍然只动 randomize 位置，
        # 找不到目标捐赠位置就如实跳过，不会退回随机 —— 否则"指定了却没生效"更难查。
        mm = None
        for _p in u["places"]:
            mm = manual.get((_p["map"], _p["entity_id"]))
            if mm:
                break
        if mm:
            _cand = [x for x in manual_pool
                     if ((mm["npc_id"] and x["npc_id"] == mm["npc_id"])
                         or (not mm["npc_id"] and mm["model"] and x["model"] == mm["model"]))]
            _cand.sort(key=lambda x: (x["npc_id"], x["key"]))
            if not _cand:
                skips.append(_skip(u, "manual:no_donor",
                                   "手动指定找不到 %s / %s" % (mm["npc_id"] or "-", mm["model"] or "-")))
                continue
            d = _cand[0]
            rule = rule_for(u, rules)
            if rule is None:
                skips.append(_skip(u, "manual:no_rule", "手动指定位置没有归属规则"))
                continue
            if d["model"] == u["model"] and constraints.get("require_model_change", True):
                skips.append(_skip(u, "manual:same_model", "手动指定换入模型与原模型相同"))
                continue
            entry, pos = _entry_for(u, d, rule, options, ["manual"], ai_fallback,
                                    extra={"manual": True})
            for _pos in pos:
                _pos["manual"] = True
            plan_units.append(entry)
            positions.extend(pos)
            by_rule[rule["id"]] = by_rule.get(rule["id"], 0) + 1
            if d["cls"] in AREA_BOSSISH:
                _n = int(d["npc_id"])
                boss_use[_n] = boss_use.get(_n, 0) + 1
            manual_hits += 1
            continue

        # 池开关是「这个位置要不要参与」，必须先于规则判定：关掉池 = 该池位置保持原样，
        # 不会因为它同时属于某个类规则又被换掉（M1 验收①）。
        if u["pools"] and not (set(u["pools"]) & enabled_pools):
            skips.append(_skip(u, "pool_off:%s" % "+".join(u["pools"])))
            continue
        rule = rule_for(u, rules)
        if rule is None:
            skips.append(_skip(u, "no_rule", u["cls"] or "?"))
            continue

        rng = unit_rng(base_seed, u["key"])
        rate = rate_for(options, u, rule)
        if rng.random() >= rate:
            skips.append(_skip(u, "rate:%s" % rate))
            continue

        groups = rule_donors.get(rule["id"]) or {}
        cand = size_candidates(u, rule, groups, options, size_cache, named_models)
        cand = _boss_cap_filter(cand, boss_use, boss_cap, cap_stats)
        # 逐类来源百分比：普通位置用「这一类自己的组成」；特殊规则（传送门/血条/
        # 多阶段）没有自己的组成时回落到规则/全局权重，不会因为目标池不同被抽空。
        _cw = preset_class_weights.get(u["cls"])
        _rw = rule.get("donor_weights")
        _fb = _rw or donor_weight_map
        if _cw and not _fb and not str(rule["id"]).startswith("preset:"):
            _weights = None
        else:
            _weights = _cw or _fb
        d = pick_donor(u, cand, rng, bool(constraints.get("require_model_change", True)),
                       weights=_weights, fallback_weights=_fb)
        if d is None:
            stats["no_candidate_units"] += 1
            why = _no_candidate_reason(u, groups.get(_donor_group_key(u, rule)) or [],
                                       options, cand, rule, named_models)
            skips.append(_skip(u, "no_candidate:%s" % why))
            continue
        reasons.append("rule:%s" % rule["id"])
        reasons.append("silo:%s" % u["silo"])
        if u["pools"]:
            reasons.append("pool:%s" % "+".join(u["pools"]))
        reasons.append("rate:%s" % rate)
        entry, pos = _entry_for(u, d, rule, options, reasons, ai_fallback)
        plan_units.append(entry)
        positions.extend(pos)
        by_rule[rule["id"]] = by_rule.get(rule["id"], 0) + 1
        if d["cls"] in AREA_BOSSISH:
            _n = int(d["npc_id"])
            boss_use[_n] = boss_use.get(_n, 0) + 1

    # Enemy Onslaught（实验）：给普通敌人算「再复制几个」。放在所有抽样之后，
    # 只写 dup_count，不影响 donor / 系数 / 其它单元。
    ons_units, ons_dups = _apply_onslaught(
        plan_units, {u["key"]: u for u in units}, options, base_seed)
    if ons_units:
        for e in plan_units:
            if e.get("dup_count"):
                e["reason"] += " | onslaught:dup=%d" % e["dup_count"]

    plan_units.sort(key=lambda e: e["key"])
    positions.sort(key=lambda e: (e["map"], e["part_name"], e["occurrence"]))
    skips.sort(key=lambda e: e["key"])

    by_reason = {}
    for s in skips:
        head = s["reason"].split(":")[0]
        by_reason[head] = by_reason.get(head, 0) + 1
    by_silo = {}
    for u in units:
        if not u["silo"]:
            continue
        b = by_silo.setdefault(u["silo"], {"units": 0, "replaced": 0})
        b["units"] += 1
    for e in plan_units:
        by_silo.setdefault(e["silo"], {"units": 0, "replaced": 0})["replaced"] += 1
    pool_counts = {}
    for pid, p in data["pools"].items():
        pool_counts[pid] = {"members": len(p["members"]), "replaced": 0}
    if pool_counts:
        for e in plan_units:
            for pid in e["pools"]:
                if pid in pool_counts:
                    pool_counts[pid]["replaced"] += 1

    meta = {
        "version": PLAN_VERSION,
        "seed": seed,
        "base_seed": base_seed,
        "options": options,
        "data": data["hashes"],
        "counts": {
            "places": len(data["places"]),
            "units": len(units),
            "replaced_units": len(plan_units),
            "replaced_places": len(positions),
            "skipped_units": len(skips),
            "skipped_places": len(data["places"]) - len(positions),
            "clamped": {"hp": stats["clamped_hp"], "soul": stats["clamped_soul"]},
            "no_candidate_units": stats["no_candidate_units"],
            "manual_units": manual_hits,
            "onslaught_units": ons_units,
            "onslaught_dups": ons_dups,
            "by_reason": by_reason,
            "by_silo": by_silo,
            "by_rule": by_rule,
            "pools": pool_counts,
            "boss_cap": {
                "cap": boss_cap,
                "relaxed": cap_stats.get("relaxed", 0),
                "max_used": max(boss_use.values()) if boss_use else 0,
            },
        },
        "rules": rules,
        "preset": ({"name": preset["name"], "classes": sorted(preset["classes"]),
                    "pools": sorted(preset.get("pools") or {}),
                    "sha256": preset_digest(preset),
                    "rate_mode": preset.get("rate_mode") or "independent",
                    "weights": (preset_info or {}).get("info", {}).get("weights"),
                    "share": (preset_info or {}).get("info", {}).get("share"),
                    "by_class": (preset_info or {}).get("by_class")}
                   if preset else None),
        "default_rate": default_rate,
        "manual": {"entries": len(manual), "applied_units": manual_hits,
                   "sha256": data.get("manual_sha256", "")},
        "donor_deny": deny,
        "ai_fallback": ai_fallback,
        "multiphase_groups": len(groups),
        "multiphase_swap": bool(constraints.get("multiphase_swap")),
        "multiphase_swapped": sum(len(v.get("donors") or [])
                                  for v in mp_info.values()),
        "multiphase_skipped": len(mp_skipped),
        "multiphase_policy": mp_info,
        "multiphase_donor": {gid: {"policy": v.get("policy"),
                                   "donors": v.get("donors")}
                             for gid, v in mp_info.items()},
    }
    return {"meta": meta, "units": plan_units, "positions": positions, "skips": skips}


def _skip(u, reason, note=""):
    return {
        "key": u["key"], "map": u["map"], "part_name": u["part_name"],
        "occurrence": u["occurrence"], "entity_id": u["entity_id"],
        "npc_id": u["npc_id"], "model": u["model"], "cls": u["cls"],
        "silo": u["silo"], "policy": u["policy"], "pools": u["pools"],
        "reason": reason, "note": note,
        "places": [{"map": p["map"], "entity_id": p["entity_id"]} for p in u["places"]],
    }


def _no_candidate_reason(unit, donors, options, cand=None, rule=None, named=None):
    if unit["model"] == "c0000":
        return "placeholder_model"      # 真身由事件/剧本生成，换 npc 只会换掉占位壳
    if not donors:
        return "empty_target"           # 规则的 targets 里没有任何可当来源的单元
    if cand is None:
        cand = [d for d in donors if _size_ok(unit, d, rule, options)
                and _named_ok(unit, d, options, named)]
    if not cand:
        band = _hp_band(rule, options)
        if band:
            size_ok = [d for d in donors if _size_only_ok(unit, d, rule, options)]
            if size_ok and unit["hp"] > 0:
                return "hp_band(%.2f-%.2f)" % band   # 体型放行，但血量全在带外
        return "size_or_hp"
    if (unit.get("bar") or unit.get("has_bar_name")) and not any(
            _named_ok(unit, d, options, named) for d in donors):
        return "no_bar_name"            # 该规则下没有任何带血条名的模型可换
    if all(d["model"] == unit["model"] for d in cand):
        return "single_model"
    if all(d["npc_id"] == unit["npc_id"] for d in cand):
        return "same_npc_only"
    return "no_rule"


def _fmt(v):
    return "-" if v is None else ("%.3f" % v)


# ---------------------------------------------------------------- 数据装载

def load_data(places=PLACES, npc=NPC, yaml_path=YAML_PATH, manual_path=MANUAL):
    rows = load_places(places)
    npc_map = load_npc(npc)
    cfg, yaml_hash = load_yaml(yaml_path)
    multiphase = load_multiphase(cfg)
    rules = load_rules(cfg)
    bar = load_bar_names(BAR_TABLE)
    manual = load_manual(manual_path)
    hashes = {
        "places_sha256": hashlib.sha256(open(places, "rb").read()).hexdigest()[:32],
        "npc_sha256": hashlib.sha256(open(npc, "rb").read()).hexdigest()[:32],
        "yaml_sha256": yaml_hash[:32],
        "bar_sha256": hashlib.sha256(open(BAR_TABLE, "rb").read()).hexdigest()[:32]
        if os.path.exists(BAR_TABLE) else "",
    }
    return {"places": rows, "npc": npc_map, "cfg": cfg, "pools": load_pools(cfg),
            "multiphase": multiphase, "rules": rules, "donor_deny": load_donor_deny(cfg),
            "ai_fallback": load_ai_fallback(cfg), "bar": bar, "manual": manual,
            "manual_sha256": hashlib.sha256(
                json.dumps([{"map": k[0], "entity_id": k[1], **v}
                            for k, v in sorted(manual.items())],
                           sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:32] if manual else "",
            "hashes": hashes}


# ---------------------------------------------------------------- 校验

def validate_plan(plan, data=None):
    """返回问题清单（空 = 通过）。检查 M1 五条验收里能离线证的部分。"""
    bad = []
    meta = plan["meta"]
    opts = meta["options"]
    cons = opts.get("constraints") or {}
    rule_by_id = {r["id"]: r for r in (meta.get("rules") or [])}
    keys = set()
    mp = data["multiphase"][0] if data else set()
    # v1.1：整组替换的位置单独放行（否则下面「命中多阶段 = 错」会把整组换掉判成失败）
    mp_swap = bool(cons.get("multiphase_swap"))
    mp_groups, mp_group_list = {}, []
    if data:
        for g in data["multiphase"][1]:
            if not (mp_swap and bool(g.get("swap"))
                    and str(g.get("kind") or "phase") == "phase"):
                continue
            mp_group_list.append(g)
            for idx, ent in enumerate(g["phases"]):
                mp_groups[(g["map"], _i(ent))] = (g["id"], idx + 1)
    for e in plan["units"]:
        k = e["key"]
        if k in keys:
            bad.append("重复单元 %s" % k)
        keys.add(k)
        if e["owner"] != OWNER_VISUAL:
            bad.append("%s owner=%s" % (k, e["owner"]))
        if e["new_model"] == e["old_model"] and cons.get("require_model_change"):
            bad.append("%s 换入模型与原模型相同" % k)
        rule = rule_by_id.get(e.get("rule") or "")
        if rule is None:
            bad.append("%s 没有归属规则（%s）" % (k, e.get("rule")))
            continue
        if e.get("manual"):
            # 手动指定是显式覆盖，允许跨类/跨区域；但仍然要求归属规则存在、目标/数值合法。
            pass
        else:
            # v1.3.13：预设规则的 targets 带 sources（类名或 "pool:<id>"）。
            srcs = rule["targets"].get("sources") or []
            if srcs:
                ok = (e.get("new_cls") in {r for r in srcs
                                           if not is_pool_ref(r)
                                           and not is_same_boss_ref(r)}
                      or any(pool_ref(p) in srcs for p in (e.get("new_pools") or [])))
                if not ok and SAME_BOSS_REF in srcs:
                    # 「同类型 Boss」：Boss 类位置必须换成同类；非 Boss 位置换成任意 Boss 级。
                    if e.get("old_cls") in AREA_BOSSISH:
                        ok = e.get("new_cls") == e.get("old_cls")
                    else:
                        ok = e.get("new_cls") in AREA_BOSSISH
                if not ok:
                    bad.append("%s 换入 %s%s 不在规则 %s 的来源里" % (
                        k, e.get("new_cls"),
                        ("（池 %s）" % "+".join(e.get("new_pools") or []))
                        if e.get("new_pools") else "", rule["id"]))
            elif e.get("new_cls") not in rule["targets"]["cls"]:
                bad.append("%s 换入类 %s 不在规则 %s 的 targets 里" % (
                    k, e.get("new_cls"), rule["id"]))
            if rule.get("donor_weights"):
                w = float(rule["donor_weights"].get(e.get("new_cls")) or 0)
                if w <= 0:
                    for p in e.get("new_pools") or []:
                        w = max(w, float(rule["donor_weights"].get(pool_ref(p)) or 0))
                if w <= 0:
                    w = float(rule["donor_weights"].get(SAME_BOSS_REF) or 0)
                if w <= 0:
                    bad.append("%s 换入 %s 在规则 %s 的 donor_weights 里权重为 0" % (
                        k, e.get("new_cls"), rule["id"]))
            if rule["targets"]["areas"] == "same" and e.get("new_area") != e.get("area"):
                bad.append("%s 跨区域换入（%s → %s），规则 %s 只允许同区域" % (
                    k, e.get("area"), e.get("new_area"), rule["id"]))
        # 数值语义：换入者整行 + 两处类别桥接（普通→Boss 的 bosshp；Boss→普通由写盘层挂 0.25）
        if e.get("target_hp") is None:
            bad.append("%s 缺 target_hp（M2 没法直接写克隆行）" % k)
        elif data is not None and not e.get("balance"):
            # 数值平衡层（enemy_balance）会把 target_hp 改成「位置原强度 × 分层抽值」，
            # 这时它不等于类别血量模型，跳过这条等式复核。
            old_hp = data["npc"].get(int(e["old_npc_id"]), {}).get("hp")
            donor_hp = data["npc"].get(int(e.get("new_npc_id") or 0), {}).get("hp")
            _scale = float((((plan.get("meta") or {}).get("options") or {})
                            .get("scaling") or {}).get("hp") or 1.0)
            _want = _target_hp_for(old_hp, donor_hp, e.get("old_cls"), e.get("new_cls"), _scale)
            if old_hp is not None and donor_hp is not None and abs(float(_want) - float(e["target_hp"])) > 1e-6:
                bad.append("%s target_hp=%s ≠ 类别血量模型=%s（旧 %s / 换入 %s ×%.2f）" % (
                    k, e["target_hp"], _want, old_hp, donor_hp, _scale))
        if e["coef_hp"] is not None and e["coef_hp"] <= 0:
            bad.append("%s coef_hp 非法 %s" % (k, e["coef_hp"]))
        if e["coef_soul"] is not None and e["coef_soul"] <= 0:
            bad.append("%s coef_soul 非法 %s" % (k, e["coef_soul"]))
        if len(e["places"]) not in (1, 2):
            bad.append("%s places 数=%s" % (k, len(e["places"])))
        if len(e["places"]) == 2:
            maps = {p["map"] for p in e["places"]}
            if len(maps) != 2:
                bad.append("%s link 组没有跨两张图" % k)
        for p in e["places"]:
            loc = (p["map"], p["entity_id"])
            if loc in mp_groups:
                gid, phase = mp_groups[loc]
                if e.get("multiphase") != gid or e.get("phase") != phase:
                    bad.append("%s 在多阶段组 %s 阶段 %d，但条目没标对（%s/%s）" % (
                        k, gid, phase, e.get("multiphase"), e.get("phase")))
                if e.get("rule") != "multiphase_boss":
                    bad.append("%s 属多阶段组 %s，规则却是 %s" % (k, gid, e.get("rule")))
            elif mp and loc in mp:
                bad.append("%s 命中了多阶段位置 %s/%s" % (k, p["map"], p["entity_id"]))
        nd = int(e.get("dup_count") or 0)
        if nd:
            f = float((((meta.get("options") or {}).get("features") or {})
                       .get("onslaught") or 1.0))
            if f <= 1.0:
                bad.append("%s 有 dup_count 但没开敌人倍增" % k)
            if nd > int(ONSLAUGHT_MAX - 1.0):
                bad.append("%s dup_count=%d 超过上限" % (k, nd))
            if e.get("cls") not in ONSLAUGHT_CLASSES:
                bad.append("%s 是 %s，不允许复制" % (k, e.get("cls")))
            if e.get("manual") or e.get("pools") or len(e.get("places") or []) != 1:
                bad.append("%s 手动/池/link 单元不允许复制" % k)
            for p in e["places"]:
                if int(p.get("entity_id") or 0) <= 0:
                    bad.append("%s 实体 ID 为 0，不能复制" % k)
    # v1.2：多阶段一致性（按「转阶段是否换模型」分流：模型变了每阶段各换一个 Boss，
    # 模型没变整场共用一个 Boss）
    if mp_group_list and data is not None:
        units_all = unitize(data["places"])
        by_place_unit = {}
        for u in units_all:
            for p in u["places"]:
                by_place_unit[(p["map"], p["entity_id"])] = u
        by_gid = {}
        for e in plan["units"]:
            if e.get("multiphase"):
                by_gid.setdefault(e["multiphase"], []).append(e)
        mp_policy = meta.get("multiphase_policy") or {}
        for g in mp_group_list:
            gid = g["id"]
            ens = sorted(by_gid.get(gid) or [], key=lambda e: e.get("phase") or 0)
            phases = [int(x) for x in g["phases"]]
            info = mp_policy.get(gid) or {}
            if not ens:
                if not info.get("skipped"):
                    bad.append("多阶段组 %s 一个阶段都没换" % gid)
                continue
            if len(ens) != len(phases):
                bad.append("多阶段组 %s 只换了 %d/%d 个阶段" % (gid, len(ens), len(phases)))
                continue
            want = info.get("policy")
            if want not in ("one_boss", "per_phase_model"):
                bad.append("多阶段组 %s 没有标明分流策略（%s）" % (gid, want))
                continue
            old_models = {by_place_unit[(g["map"], _i(x))]["model"]
                          for x in phases if (g["map"], _i(x)) in by_place_unit}
            want_old = "one_boss" if len(old_models) == 1 else "per_phase_model"
            if want != want_old:
                bad.append("多阶段组 %s 分流策略 %s 与阶段模型数（%d 种）不符，应为 %s" % (
                    gid, want, len(old_models), want_old))
            for idx, e in enumerate(ens):
                if e.get("phase") != idx + 1:
                    bad.append("多阶段组 %s 阶段序号乱：%s" % (gid, e.get("phase")))
                if e.get("mp_policy") != want:
                    bad.append("多阶段组 %s 阶段 %d 的分流标记 %s ≠ %s" % (
                        gid, idx + 1, e.get("mp_policy"), want))
            npcs = {int(e["new_npc_id"]) for e in ens}
            models_n = [e["new_model"] for e in ens]
            if want == "one_boss":
                if len(npcs) != 1:
                    bad.append("多阶段组 %s 模型没变，却换了 %d 个不同 Boss：%s" % (
                        gid, len(npcs), sorted(npcs)))
            else:
                if len(set(models_n)) != len(models_n):
                    bad.append("多阶段组 %s 每阶段该换不同 Boss，却有重复模型：%s" % (
                        gid, models_n))
                if old_models and (set(models_n) & old_models):
                    bad.append("多阶段组 %s 的换入模型与阶段原模型重合：%s" % (
                        gid, sorted(set(models_n) & old_models)))

    # link 组要么都在要么都不在：union 检查
    placed = set()
    for e in plan["units"]:
        for p in e["places"]:
            placed.add((p["map"], p["part_name"], p["occurrence"]))
    pos_keys = set((p["map"], p["part_name"], p["occurrence"]) for p in plan["positions"])
    if pos_keys != placed:
        bad.append("positions[] 与 units[].places 不一致")
    if len(plan["positions"]) != sum(len(e["places"]) for e in plan["units"]):
        bad.append("position 计数不一致")
    # v1.3.13：Boss 使用上限 —— 同一个 Boss 最多被随到 N 次（手动指定是显式覆盖，不计入）。
    _cap = int(cons.get("boss_usage_cap") or 0)
    if _cap:
        _use = {}
        for e in plan["units"]:
            if e.get("manual") or e.get("donor_cls") not in AREA_BOSSISH:
                continue
            _n = int(e.get("new_npc_id") or 0)
            _use[_n] = _use.get(_n, 0) + 1
        _mx = max(_use.values()) if _use else 0
        _relaxed = int((((meta.get("counts") or {}).get("boss_cap") or {})
                        .get("relaxed")) or 0)
        if _mx > _cap and not _relaxed:
            bad.append("Boss 使用超过上限：同一 Boss 被随到 %d 次（上限 %d）" % (_mx, _cap))
    return bad


def check_plan_file(path, data=None):
    plan = json.load(io.open(path, encoding="utf-8"))
    if data is None:
        data = load_data()
    bad = validate_plan(plan, data)
    return plan, bad


# ---------------------------------------------------------------- 输出

def dump_plan(plan, path):
    text = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return len(text.encode("utf-8"))


def show_plan(plan, names, limit=0):
    m = plan["meta"]
    c = m["counts"]
    print("计划 seed=%s base=%s" % (m["seed"], m["base_seed"][:16]))
    print("单元 %d → 替换 %d / 跳过 %d；位置 %d → 替换 %d" % (
        c["units"], c["replaced_units"], c["skipped_units"], c["places"], c["replaced_places"]))
    print("跳过原因：" + ", ".join("%s=%d" % (k, v) for k, v in sorted(c["by_reason"].items())))
    print("clamp：hp %d / soul %d；池：%s" % (
        c["clamped"]["hp"], c["clamped"]["soul"],
        ", ".join("%s %d/%d" % (k, v["replaced"], v["members"]) for k, v in sorted(c["pools"].items()))))
    print("规则命中：" + ", ".join("%s=%d" % (k, v) for k, v in sorted(c.get("by_rule", {}).items())))
    print("")
    print("%-46s %-14s %-22s %-24s %-16s %s" % ("位置", "原", "→ 换入", "系数", "silo", "规则"))
    shown = 0
    for e in plan["units"]:
        if limit and shown >= limit:
            break
        shown += 1
        p0 = e["places"][0]
        tag = p0["map"]
        if len(e["places"]) == 2:
            tag += "*"
        old = "%s %s" % (e["old_model"], names.get(e["old_model"], "")[:10])
        new = "%s %s" % (e["new_model"], names.get(e["new_model"], "")[:10])
        print("%-46s %-14s %-22s hp %-5s soul %-5s %-16s %s" % (
            tag + " " + str(p0["entity_id"]), old, new, _fmt(e["coef_hp"]), _fmt(e["coef_soul"]),
            e["silo"], e.get("rule", "")))
    if limit and len(plan["units"]) > limit:
        print("...（共 %d 个替换单元，用 --limit 0 看全部）" % len(plan["units"]))
    print("")
    print("跳过最多的原因（前 5）：")
    for e in plan["skips"][:5]:
        print("  %-12s %-40s %s" % (e["map"], e["key"][:38], e["reason"]))


def diff_plans(a, b):
    au = {e["key"]: e for e in a["units"]}
    bu = {e["key"]: e for e in b["units"]}
    only_a = sorted(set(au) - set(bu))
    only_b = sorted(set(bu) - set(au))
    changed = sorted(k for k in set(au) & set(bu) if au[k]["new_npc_id"] != bu[k]["new_npc_id"])
    print("A: %d 替换 / B: %d 替换" % (len(au), len(bu)))
    print("只在 A：%d，只在 B：%d，两边都在但换入不同：%d" % (len(only_a), len(only_b), len(changed)))
    by_pool = {}
    for k in only_a:
        for pid in au[k]["pools"]:
            by_pool[pid] = by_pool.get(pid, 0) + 1
    if by_pool:
        print("只在 A 的单元按池：" + ", ".join("%s=%d" % (k, v) for k, v in sorted(by_pool.items())))
    for k in only_a[:5]:
        print("  A-only", k, au[k]["old_model"], "->", au[k]["new_model"])
    for k in only_b[:5]:
        print("  B-only", k, bu[k]["old_model"], "->", bu[k]["new_model"])


# ---------------------------------------------------------------- 自检

def _selftest():
    print("== enemy_plan selftest ==")
    data = load_data()
    seed = 20261020
    t0 = load_time = None
    plan = build_plan(data, {}, seed)
    problems = validate_plan(plan, data)
    print("build: 单元 %d / 替换 %d / 跳过 %d" % (
        plan["meta"]["counts"]["units"], plan["meta"]["counts"]["replaced_units"],
        plan["meta"]["counts"]["skipped_units"]))
    assert not problems, problems[:5]

    # ① 同种子逐字节一致
    plan2 = build_plan(data, {}, seed)
    a = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    b = json.dumps(plan2, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert a == b, "同种子两次构建结果不同"
    print("PASS 同种子两次构建逐字节一致（%d 字符）" % len(a))

    # 换种子必须变（否则种子没接进抽样）
    plan3 = build_plan(data, {}, seed + 1)
    c = json.dumps(plan3, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert a != c, "换种子结果没变"
    print("PASS 换种子结果变（%d 个单元换入不同）" % sum(
        1 for x, y in zip(plan["units"], plan3["units"]) if x["new_npc_id"] != y["new_npc_id"]))

    # ② keep/hazard/story 不得出现在目标侧
    target_keys = {e["key"] for e in plan["units"]}
    keep_units = {u["key"] for u in unitize(data["places"]) if u["policy"] != "randomize"}
    assert not (target_keys & keep_units), "keep 单元出现在目标侧"
    print("PASS keep 单元零替换（%d 个）" % len(keep_units))

    # ③ link 组一致性：同 link 号的两行都在 positions 里
    by_link = {}
    for p in plan["positions"]:
        if p["unit"].startswith("link:"):
            by_link.setdefault(p["unit"], set()).add(p["map"])
    assert all(len(v) == 2 for v in by_link.values()), "link 组只写了一边"
    print("PASS link 组两行同进同出（%d 组）" % len(by_link))

    # ④ 多阶段零替换
    mp = data["multiphase"][0]
    hit = [p for p in plan["positions"] if (p["map"], p["entity_id"]) in mp]
    assert not hit, "多阶段位置被替换 %d 个" % len(hit)
    print("PASS 多阶段 %d 个位置零替换" % len(mp))

    # ⑤ 池开关：关掉某个池，只允许「只属于这个池」的单元消失，其它单元一个字节都不许变。
    # v1.3.13：Boss 使用上限是全局顺序统计，开关池会改变全局用量 → 局部性测试关掉上限再比。
    no_cap = merge_options({"constraints": {"boss_usage_cap": 0}})
    plan0 = build_plan(data, no_cap, seed)
    a_map = {e["key"]: e for e in plan0["units"]}
    enabled_all = set(merge_options({})["pools"])
    for pid in sorted(enabled_all):
        opts = merge_options({"constraints": {"boss_usage_cap": 0}})
        opts["pools"][pid] = False
        b_map = {e["key"]: e for e in build_plan(data, opts, seed)["units"]}
        off_keys = set(a_map) - set(b_map)
        bad = []
        for k in off_keys:
            pools = set(a_map[k]["pools"])
            still = {p for p in pools if p != pid and p in enabled_all}
            if not pools or still:
                bad.append(k)
        for k in set(a_map) & set(b_map):
            if a_map[k]["new_npc_id"] != b_map[k]["new_npc_id"]:
                bad.append(k)
        assert not bad, "关 %s 影响了不该变的单元：%s" % (pid, bad[:5])
        print("PASS 关 %-11s 只影响该池位置（%d 个跳过，其它零变化）" % (pid, len(off_keys)))

    # ⑥ 负向账本覆盖全部单元
    assert len(plan["units"]) + len(plan["skips"]) == plan["meta"]["counts"]["units"], "账本不完整"
    print("PASS 负向账本覆盖全部单元")

    # ⑦ 规则局部性：把某条规则的百分比改成 0，只有它管的单元消失，其它单元一个字节都不许变
    rules0, dr0 = data["rules"]
    for rid in [r["id"] for r in rules0]:
        d2 = dict(data)
        new_rules = []
        for r in rules0:
            r2 = json.loads(json.dumps(r))
            if r2["id"] == rid:
                r2["rate"] = 0.0
            new_rules.append(r2)
        d2["rules"] = (new_rules, dr0)
        p2 = build_plan(d2, {"constraints": {"boss_usage_cap": 0}}, seed)
        amap = {e["key"]: e for e in plan0["units"]}
        bmap = {e["key"]: e for e in p2["units"]}
        gone = set(amap) - set(bmap)
        wrong = [k for k in gone if amap[k].get("rule") != rid]
        shifted = [k for k in set(amap) & set(bmap) if amap[k]["new_npc_id"] != bmap[k]["new_npc_id"]]
        assert not wrong, "规则 %s 关掉后影响了别的规则的单元：%s" % (rid, wrong[:5])
        assert not shifted, "规则 %s 关掉后其它单元换入变了：%s" % (rid, shifted[:5])
        print("PASS 关规则 %-18s 只影响它管的 %d 个单元（其它零变化）" % (rid, len(gone)))

    # ⑧ 目标类约束：每个换入的类必须在它那条规则的 targets 里（validate 已查，这里再显式验一遍）
    rule_by_id = {r["id"]: r for r in plan["meta"]["rules"]}
    bad_target = [e["key"] for e in plan["units"]
                  if e.get("new_cls") not in rule_by_id[e["rule"]]["targets"]["cls"]]
    assert not bad_target, "换入了规则外的类：%s" % bad_target[:5]
    boss_cls = {"Boss", "MinorBoss", "Miniboss", "NightMiniboss", "DragonMiniboss", "Evergaol"}
    wg = [e for e in plan["units"] if "waygate" in (e["pools"] or [])]
    bad_wg = [e["key"] for e in wg if e["new_cls"] not in boss_cls]
    assert not bad_wg, "传送门守门位被换成了非 boss：%s" % bad_wg[:5]
    print("PASS 目标类约束（waygate %d 个守门位全是 boss 级）" % len(wg))

    # ⑨ HP 模型：默认换入者血量；普通→Boss 且原位置更厚时取 sqrt(原×换入)；魂默认位置原值
    bad_fid = []
    for e in plan["units"]:
        old = data["npc"].get(int(e["old_npc_id"])) or {}
        if old.get("hp") is None:
            continue
        donor = data["npc"].get(int(e["new_npc_id"]), {}) or {}
        want = _target_hp_for(old["hp"], donor.get("hp"), e.get("old_cls"), e.get("new_cls"), 1.0)
        if abs(float(want) - float(e["target_hp"])) > 1e-6:
            bad_fid.append((e["key"], old["hp"], donor.get("hp"), e["target_hp"], want))
        if old.get("soul"):
            if (not (plan["meta"]["options"].get("features") or {}).get("soul_follow")
                and (e["target_soul"] is None or abs(float(old["soul"]) - float(e["target_soul"])) > 1e-6)):
                bad_fid.append((e["key"], "soul", old["soul"], e["target_soul"]))
    assert not bad_fid, "target_hp/target_soul 不等于数值模型：%s" % bad_fid[:5]
    print("PASS HP 模型：%d 个替换单元的 hp 按换入者/普通→Boss sqrt；魂默认位置原值"
          % len(plan["units"]))

    # ⑩ v1.2 多阶段 Boss 分流：默认关；打开后按「阶段模型是否变化」两种策略，
    #    换入 Boss 在阶段之间不重复，其它单元一个字节都不变
    p_on = build_plan(data, {"constraints": {"multiphase_swap": True,
                                                "boss_usage_cap": 0}}, seed)
    bad_on = validate_plan(p_on, data)
    assert not bad_on, bad_on[:5]
    groups_sw = [g for g in data["multiphase"][1]
                 if bool(g.get("swap")) and str(g.get("kind") or "phase") == "phase"]
    want_units = sum(len(g["phases"]) for g in groups_sw)
    ents = [e for e in p_on["units"] if e.get("multiphase")]
    assert len(ents) <= want_units, "多阶段替换的单元数 %d > %d" % (len(ents), want_units)
    policy = p_on["meta"].get("multiphase_policy") or {}
    n_one = sum(1 for v in policy.values() if v.get("policy") == "one_boss")
    n_per = sum(1 for v in policy.values() if v.get("policy") == "per_phase_model")
    for g in groups_sw:
        es = [e for e in ents if e["multiphase"] == g["id"]]
        info = policy.get(g["id"]) or {}
        if info.get("skipped"):
            assert not es, "组 %s 标了跳过却有条目" % g["id"]
            continue
        assert len(es) == len(g["phases"]), "组 %s 阶段数不对" % g["id"]
        assert {e["phase"] for e in es} == set(range(1, len(g["phases"]) + 1)), \
            "组 %s 阶段序号不连续" % g["id"]
        if info["policy"] == "one_boss":
            assert len({int(e["new_npc_id"]) for e in es}) == 1, \
                "组 %s 模型没变却换了多个 Boss" % g["id"]
        else:
            models = [e["new_model"] for e in es]
            assert len(set(models)) == len(models), "组 %s 阶段之间换了同一个 Boss" % g["id"]
    off_map = {e["key"]: e for e in plan0["units"]}
    on_map = {e["key"]: e for e in p_on["units"]}
    shifted = [k for k in off_map if k in on_map and off_map[k]["new_npc_id"] != on_map[k]["new_npc_id"]]
    assert not shifted, "打开多阶段换 Boss 后不相关的单元变了：%s" % shifted[:5]
    assert not [k for k in off_map if k not in on_map], "打开多阶段换 Boss 后丢了普通单元"
    assert n_one and n_per, "两种分流策略没都覆盖到：整场=%d 每阶段=%d" % (n_one, n_per)
    print("PASS 多阶段 Boss 分流（开关默认关）：%d 组里整场共用一个 Boss %d 组、"
          "每阶段各换 %d 组；阶段间不重复，其它单元零变化" % (len(groups_sw), n_one, n_per))

    # ⑪ 逐类预设：只改 Boss 的目标类（只允许 Boss→Boss），其它单元的抽签结果一个字节都不变
    pr = default_preset(data["cfg"], unitize(data["places"]))
    pr["rate_mode"] = "independent"       # 这一项测「各自独立概率」的局部性
    pr["classes"]["Boss"] = dict(pr["classes"]["Boss"], enabled=True, rate=1.0,
                                targets=["Boss"], target_areas="same",
                                source_areas=["base", "dlc"], size_max=3.0)
    p_pre = build_plan(data, {"preset": pr,
                              "constraints": {"boss_usage_cap": 0}}, seed)
    bad_pre = validate_plan(p_pre, data)
    assert not bad_pre, bad_pre[:5]
    assert p_pre["meta"].get("preset", {}).get("sha256"), "计划没记预设指纹"
    assert any(r["id"] == "preset:Boss" for r in p_pre["meta"]["rules"]), "预设规则没进 meta"
    base_map = {e["key"]: e for e in plan0["units"]}
    pre_map = {e["key"]: e for e in p_pre["units"]}
    # 特殊规则（传送门 / 血条位）先于类别预设，所以只检查「真被 preset:Boss 接管」的条目
    boss_bad = [e["key"] for e in p_pre["units"]
                if e["rule"] == "preset:Boss" and e["new_cls"] != "Boss"]
    assert not boss_bad, "预设只允许 Boss→Boss，却换成了别的类：%s" % boss_bad[:5]
    assert any(e["rule"] == "preset:Boss" for e in p_pre["units"]), "Boss 预设一个单元都没接管"
    shifted_pre = [k for k in base_map
                   if base_map[k]["old_cls"] != "Boss" and k in pre_map
                   and base_map[k]["new_npc_id"] != pre_map[k]["new_npc_id"]]
    assert not shifted_pre, "改 Boss 预设后非 Boss 单元变了：%s" % shifted_pre[:5]
    print("PASS 逐类预设（独立概率）：Boss 只换 Boss（%d 个），非 Boss 单元零变化；预设指纹 %s…" % (
        sum(1 for e in p_pre["units"] if e["old_cls"] == "Boss"),
        p_pre["meta"]["preset"]["sha256"][:12]))

    # ⑫ 权重叠加：只让 Basic 与 Boss 当来源、各 50%，换入组成应接近 1:1（按类抽，再类内均匀）
    pr_w = default_preset(data["cfg"], unitize(data["places"]))
    for _c, _e in pr_w["classes"].items():
        _e["enabled"] = True
        _e["targets"] = ["Basic", "Boss"]
        _e["source_areas"] = ["base", "dlc"]
        _e["target_areas"] = "any"
        _e["weight"] = 50.0 if _c in ("Basic", "Boss") else 0.0
    p_w = build_plan(data, {"preset": pr_w,
                             "constraints": {"boss_usage_cap": 0}}, seed)
    assert not validate_plan(p_w, data), validate_plan(p_w, data)[:5]
    from collections import Counter
    mix = Counter(e["new_cls"] for e in p_w["units"])
    total_mix = sum(mix.values())
    share_boss = (mix.get("Boss", 0) / total_mix) if total_mix else 0.0
    assert 0.42 <= share_boss <= 0.58, "权重 50:50 时 Boss 占比异常：%.3f（%s）" % (share_boss, mix)
    assert total_mix == p_w["meta"]["counts"]["replaced_units"]
    print("PASS 逐类预设（权重叠加）：Basic:Boss=50:50 → 换入 Boss 占比 %.1f%%（%d 个）" % (
        share_boss * 100.0, total_mix))

    # ⑫b 逐类来源百分比：Basic 只由 Wildlife 供、Wildlife 只由 Basic 供；
    #     这与旧「全局一套权重」不同：两类各有一套自己的组成。
    pr_c = default_preset(data["cfg"], unitize(data["places"]))
    pr_c["rate_mode"] = "weight"
    for _c, _e in pr_c["classes"].items():
        _e["enabled"] = _c in ("Basic", "Wildlife")
        _e["rate"] = 1.0 if _c in ("Basic", "Wildlife") else 0.0
        _e["source_areas"] = ["base", "dlc"]
        _e["target_areas"] = "any"
        _e["size_max"] = 3.0
        if _c == "Basic":
            _e["donor_weights"] = {"Wildlife": 100.0}
            _e["targets"] = ["Wildlife"]
        elif _c == "Wildlife":
            _e["donor_weights"] = {"Basic": 100.0}
            _e["targets"] = ["Basic"]
        else:
            _e["donor_weights"] = None
            _e["targets"] = []
    p_c = build_plan(data, {"preset": pr_c}, seed)
    bad_c = validate_plan(p_c, data)
    assert not bad_c, bad_c[:5]
    _basic_units = [e for e in p_c["units"]
                    if e["rule"] == "preset:Basic" and e.get("new_npc_id")]
    _wild_units = [e for e in p_c["units"]
                   if e["rule"] == "preset:Wildlife" and e.get("new_npc_id")]
    assert _basic_units and _wild_units, "逐类来源百分比：两个方向都没有命中"
    assert all(e["new_cls"] == "Wildlife" for e in _basic_units), \
        "Basic 的来源被换成了非 Wildlife：%s" % [e["new_cls"] for e in _basic_units[:5]]
    assert all(e["new_cls"] == "Basic" for e in _wild_units), \
        "Wildlife 的来源被换成了非 Basic：%s" % [e["new_cls"] for e in _wild_units[:5]]
    _bmeta = (p_c["meta"].get("preset") or {}).get("by_class") or {}
    assert _bmeta.get("Basic", {}).get("share", {}).get("Wildlife") == 1.0, _bmeta
    assert _bmeta.get("Wildlife", {}).get("share", {}).get("Basic") == 1.0, _bmeta
    print("PASS 逐类来源百分比：Basic←Wildlife %d 个 / Wildlife←Basic %d 个，两套组成互不影响" % (
        len(_basic_units), len(_wild_units)))

    # ⑬ 全局生命值倍率：target_hp = 类别 HP 模型 × 倍率，其余不变
    p_s = build_plan(data, {"scaling": {"hp": 1.5}}, seed)
    bad_s = validate_plan(p_s, data)
    assert not bad_s, bad_s[:5]
    for _e in p_s["units"]:
        _old = data["npc"].get(int(_e["old_npc_id"]), {}).get("hp")
        _new = data["npc"].get(int(_e["new_npc_id"]), {}).get("hp")
        if _old is not None and _new is not None:
            assert abs(float(_e["target_hp"]) - _target_hp_for(
                _old, _new, _e.get("old_cls"), _e.get("new_cls"), 1.5)) < 1e-6
    assert len(p_s["units"]) == len(plan["units"])
    print("PASS 生命值倍率：%d 个替换单元的 target_hp = 类别 HP 模型 × 1.50（逐条核对）" % len(p_s["units"]))

    # ⑭ 全替换为：所有可随机位置都进同一个类，规则只剩 oops_all
    p_o = build_plan(data, {"oops_all": "Boss"}, seed)
    bad_o = validate_plan(p_o, data)
    assert not bad_o, bad_o[:5]
    assert all(_e["new_cls"] == "Boss" and _e["rule"] == "oops_all" for _e in p_o["units"])
    assert p_o["meta"]["counts"]["replaced_units"] > 0
    print("PASS 全替换为：%d 个替换单元全部换入 Boss（规则 oops_all）" % len(p_o["units"]))

    # ⑮ 手动指定：按 (map,entity) 覆盖成指定 npc，且带 manual 标记
    import copy
    _units = unitize(data["places"])
    _tgt = next(u for u in _units if u["policy"] == "randomize"
                and u["model"] != "c0000" and u["cls"])
    _don = next(u for u in _units if u["policy"] == "randomize" and u["npc_id"]
                and u["model"] != "c0000" and u["model"] != _tgt["model"]
                and int(u.get("think_id") or 0) > 0
                and data["npc"].get(int(u["npc_id"]), {}).get("hp", 0) > 0)
    _dm = copy.deepcopy(data)
    _dm["manual"] = {(_tgt["map"], _tgt["entity_id"]):
                     {"npc_id": _don["npc_id"], "model": "", "note": "selftest"}}
    _dm["manual_sha256"] = "selftest"
    p_m = build_plan(_dm, {}, seed)
    _hit = [e for e in p_m["units"] if e["key"] == _tgt["key"]]
    assert len(_hit) == 1 and _hit[0].get("manual"), "手动指定没生效：%s" % _tgt["key"]
    assert _hit[0]["new_npc_id"] == _don["npc_id"], "手动指定换入 npc 不对"
    assert not validate_plan(p_m, _dm), validate_plan(p_m, _dm)[:5]
    print("PASS 手动指定：%s → npc %s（带 manual 标记）" % (_tgt["key"], _don["npc_id"]))

    # ⑯ Enemy Onslaught（实验）：2.0× 时每个合格普通敌人正好 +1，Boss/池/血条/事件位一个都不加
    p_n = build_plan(data, {"features": {"onslaught": 2.0}}, seed)
    bad_n = validate_plan(p_n, data)
    assert not bad_n, bad_n[:5]
    _all_units = unitize(data["places"])
    for _u in _all_units:
        _s = data["npc"].get(_u["npc_id"])
        if _s:
            _u["hp"], _u["soul"] = _s["hp"], _s["soul"]
    _by_key = {u["key"]: u for u in _all_units}
    n_dup = sum(int(e.get("dup_count") or 0) for e in p_n["units"])
    n_units = sum(1 for e in p_n["units"] if e.get("dup_count"))
    assert n_units > 0 and n_dup == n_units, "2.0× 的 dup_count 不是每个合格单元 1"
    for e in p_n["units"]:
        u = _by_key[e["key"]]
        if _onslaught_ok(u, e):
            assert int(e.get("dup_count") or 0) == 1, "合格单元没加：%s" % e["key"]
        else:
            assert not e.get("dup_count"), "不合格单元被复制：%s（%s）" % (e["key"], e.get("cls"))
    p_off = build_plan(data, {}, seed)
    assert all(not e.get("dup_count") for e in p_off["units"]), "默认关闭时仍然有 dup_count"
    print("PASS 敌人倍增（实验）：2.0× → %d 个普通敌人位各 +1（共 %d 只），默认关闭时 0 个"
          % (n_units, n_dup))

    # ⑰ v1.3.13：池既能当来源，也能单独给池内位置选来源
    pr_pool = default_preset(data["cfg"], unitize(data["places"]))
    pr_pool["rate_mode"] = "independent"
    for _c, _e in pr_pool["classes"].items():
        _e["enabled"] = False
    _b = pr_pool["classes"]["Basic"]
    _b.update({"enabled": True, "rate": 1.0, "targets": ["pool:waygate"],
               "donor_weights": {"pool:waygate": 100.0},
               "source_areas": ["base", "dlc"], "target_areas": "same",
               "size_max": None})
    pr_pool["pools"]["waygate"] = {
        "enabled": True, "rate": 1.0, "weight": 0.0,
        "targets": ["Boss"], "donor_weights": {"Boss": 100.0},
        "source_areas": ["base", "dlc"], "target_areas": "same", "size_max": None}
    p_pool = build_plan(data, {"preset": pr_pool,
                               "constraints": {"boss_usage_cap": 0,
                                               "ignore_size": True}}, seed)
    bad_pool = validate_plan(p_pool, data)
    assert not bad_pool, bad_pool[:5]
    _by_pool = [e for e in p_pool["units"] if e["rule"] == "preset:Basic"]
    assert _by_pool, "池当来源：Basic 一个单元都没抽到"
    assert all("waygate" in (e.get("new_pools") or []) for e in _by_pool), \
        "池当来源：Basic 抽到了池外的敌人：%s" % [
            (e["key"], e.get("new_pools")) for e in _by_pool[:3] if "waygate" not in (e.get("new_pools") or [])]
    _in_pool = [e for e in p_pool["units"] if e["rule"] == "preset:pool:waygate"]
    assert _in_pool, "池内位置选来源：waygate 一个单元都没接管"
    assert all(e["new_cls"] == "Boss" for e in _in_pool), \
        "池内位置选来源：waygate 换入了非 Boss：%s" % [e["new_cls"] for e in _in_pool[:3]]
    print("PASS 池当来源/池内选来源：Basic←waygate 池 %d 个；waygate 池内 %d 个位只换 Boss"
          % (len(_by_pool), len(_in_pool)))

    # ⑱ v1.3.13：Boss 使用上限（同一个 Boss 最多被随到 cap 次）
    _cap_meta = plan["meta"]["counts"]["boss_cap"]
    assert _cap_meta["cap"] == int(DEFAULT_OPTIONS["constraints"]["boss_usage_cap"]), _cap_meta
    assert _cap_meta["max_used"] <= _cap_meta["cap"] or _cap_meta["relaxed"], _cap_meta
    p_cap3 = build_plan(data, {"constraints": {"boss_usage_cap": 3}}, seed)
    bad_cap3 = validate_plan(p_cap3, data)
    assert not bad_cap3, bad_cap3[:5]
    _use3 = {}
    for _e in p_cap3["units"]:
        if _e.get("manual") or _e.get("donor_cls") not in AREA_BOSSISH:
            continue
        _n = int(_e["new_npc_id"])
        _use3[_n] = _use3.get(_n, 0) + 1
    _mx3 = max(_use3.values()) if _use3 else 0
    _c3 = p_cap3["meta"]["counts"]["boss_cap"]
    assert _mx3 <= 3 or _c3["relaxed"], "Boss 上限 3 生效时仍有 Boss 被用了 %d 次：%s" % (
        _mx3, sorted((v, k) for k, v in _use3.items() if v > 3)[:3])
    _use0 = {}
    for _e in plan0["units"]:
        if _e.get("donor_cls") in AREA_BOSSISH:
            _n = int(_e["new_npc_id"])
            _use0[_n] = _use0.get(_n, 0) + 1
    _mx0 = max(_use0.values()) if _use0 else 0
    assert _mx0 > 3, "上限关掉后 Boss 复用次数没有变化（%d）—— 上限可能没生效" % _mx0
    print("PASS Boss 使用上限：默认上限 %d（实际最多 %d 次）；上限 3 时最多 %d 次、放宽 %d 个；不限时最多 %d 次"
          % (_cap_meta["cap"], _cap_meta["max_used"], _mx3, _c3["relaxed"], _mx0))

    # ⑲ v1.3.13：「血条位」条目 + 「同类型 Boss」引用（预设 07 的核心语义）
    pr_sb = default_preset(data["cfg"], unitize(data["places"]))
    pr_sb["rate_mode"] = "independent"
    for _e in pr_sb["classes"].values():
        _e["enabled"] = False
    for _e in pr_sb["pools"].values():
        _e["enabled"] = False
    pr_sb["bar"] = {
        "enabled": True, "rate": 1.0, "weight": 0.0,
        "targets": [SAME_BOSS_REF], "donor_weights": {SAME_BOSS_REF: 100.0},
        "source_areas": ["base", "dlc"], "target_areas": "same", "size_max": None}
    p_sb = build_plan(data, {"preset": pr_sb,
                             "constraints": {"boss_usage_cap": 0}}, seed)
    bad_sb = validate_plan(p_sb, data)
    assert not bad_sb, bad_sb[:5]
    _bar_units = [e for e in p_sb["units"] if e["rule"] == "preset:bar"]
    assert _bar_units, "血条位条目：一个血条位都没接管"
    _same_bad = [e["key"] for e in _bar_units
                 if e["cls"] in AREA_BOSSISH and e["new_cls"] != e["cls"]]
    _bossish_bad = [e["key"] for e in _bar_units
                    if e["cls"] not in AREA_BOSSISH and e["new_cls"] not in AREA_BOSSISH]
    assert not _same_bad, "同类型 Boss：Boss 类血条位换成了别的类：%s" % _same_bad[:5]
    assert not _bossish_bad, "同类型 Boss：非 Boss 类血条位换成了非 Boss：%s" % _bossish_bad[:5]
    print("PASS 血条位+同类型 Boss：%d 个血条位接管；Boss 类位置全部同类（%d 个），"
          "非 Boss 类位置换成任意 Boss 级（%d 个）"
          % (len(_bar_units),
             sum(1 for e in _bar_units if e["cls"] in AREA_BOSSISH),
             sum(1 for e in _bar_units if e["cls"] not in AREA_BOSSISH)))

    print("RESULT: PASS")



# ---------------------------------------------------------------- CLI

def main(argv):
    ap = argparse.ArgumentParser(description="敌人随机 v1 计划层")
    ap.add_argument("--build", action="store_true", help="构建计划并写盘")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=DEFAULT_PLAN)
    ap.add_argument("--pools", default=None, help="只开这些池（逗号分隔）")
    ap.add_argument("--no-pool", action="append", default=[], help="关掉某个池")
    ap.add_argument("--rate", type=float, default=None, help="全局参与率 0-1")
    ap.add_argument("--preset", default=None,
                    help="逐类预设 JSON（GUI 编辑器保存的那份）；省略 = 按 YAML 规则")
    ap.add_argument("--mp-swap", action="store_true",
                    help="v1.1：多阶段 Boss 整组替换（实验，只对 5 个无 pair 的组生效）")
    ap.add_argument("--onslaught", type=float, default=None,
                    help="Enemy Onslaught（实验）：1.0=关，1.5≈普通敌人 +50%%，2.0=+100%%")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--plan", default=DEFAULT_PLAN)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    if args.diff:
        a = json.load(io.open(args.diff[0], encoding="utf-8"))
        b = json.load(io.open(args.diff[1], encoding="utf-8"))
        diff_plans(a, b)
        return 0

    if args.check:
        plan, bad = check_plan_file(args.plan)
        m = plan["meta"]["counts"]
        print("plan %s：单元 %d / 替换 %d / 跳过 %d" % (
            args.plan, m["units"], m["replaced_units"], m["skipped_units"]))
        if bad:
            print("RESULT: FAIL（%d 项）" % len(bad))
            for x in bad[:20]:
                print("  -", x)
            return 1
        print("RESULT: PASS")
        return 0

    if args.show:
        path = args.plan
        if os.path.exists(path):
            plan = json.load(io.open(path, encoding="utf-8"))
        else:
            plan = build_plan(load_data(), {}, args.seed)
            print("（%s 不存在，用内存里现建的展示）" % path)
        show_plan(plan, load_model_names(), args.limit)
        return 0

    if args.build:
        data = load_data()
        options = {}
        if args.pools:
            want = {s.strip() for s in args.pools.split(",") if s.strip()}
            options["pools"] = {k: (k in want) for k in DEFAULT_OPTIONS["pools"]}
        for pid in args.no_pool:
            options.setdefault("pools", {})[pid] = False
        if args.rate is not None:
            options.setdefault("rates", {})["multiplier"] = args.rate
        if args.mp_swap:
            options.setdefault("constraints", {})["multiphase_swap"] = True
        if args.onslaught is not None:
            options.setdefault("features", {})["onslaught"] = args.onslaught
        if args.preset:
            with io.open(args.preset, encoding="utf-8") as fh:
                options["preset"] = json.load(fh)
        plan = build_plan(data, options, args.seed)
        bad = validate_plan(plan, data)
        if bad:
            print("RESULT: FAIL（校验不过，不写盘）")
            for x in bad[:20]:
                print("  -", x)
            return 1
        size = dump_plan(plan, args.out)
        c = plan["meta"]["counts"]
        print("写出 %s（%.1f MB）" % (args.out, size / 1048576.0))
        print("单元 %d → 替换 %d（位置 %d）/ 跳过 %d" % (
            c["units"], c["replaced_units"], c["replaced_places"], c["skipped_units"]))
        print("规则命中：" + ", ".join("%s=%d" % (k, v) for k, v in sorted(c["by_rule"].items())))
        print("跳过原因：" + ", ".join("%s=%d" % (k, v) for k, v in sorted(c["by_reason"].items())))
        print("RESULT: PASS")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
