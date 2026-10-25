# enemy_write.py — M2 写盘层：把 plan.json 变成方案层里真能加载的产物。
#
# 输入：investigation/enemy_plan.json（enemy_plan.py 产出）
# 输出：<法魂包>\方案\<label>\mod\
#         regulation.bin                      （NpcParam/NpcThinkParam 克隆行 + 整包重建）
#         map\MapStudio\<map>.msb.dcx         （换 npc/think/chara/model + 必要时追加模型）
#         enemy_manifest.json                 （这次写了什么、基线是谁、校验结果）
#
# 三条纪律（来自 docs/敌人随机_重制_v1实施计划.md）：
#   1. 身份只有一个写者：每个 (map, part) 只允许一个 owner；冲突直接 raise，一个字节都不写。
#   2. 先写临时目录、全部成功且读回校验通过之后才整体换上去（中断不留半套）。
#   3. 数值落点是"每个位置一条克隆行"：hp/魂直接写位置原值，不靠倍率近似。
#
# 基线：默认用当前 <mod>\ 下的文件（实测与 THE_COVERAGE 原包逐字节一致）；重跑时会把
# 上一轮自己加的克隆行（名字以 CLONE_NAME 开头）先删掉 —— 所以同一 label 反复构建不会叠加。
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bar_names                                                 # noqa: E402
import enemy_balance as balance_model                            # noqa: E402
import erio                                                      # noqa: E402
import evd_edit                                                  # noqa: E402
import msb_edit                                                   # noqa: E402
import msb_read                                                   # noqa: E402
import msb_write                                                  # noqa: E402
import param_bin                                                  # noqa: E402
import plan_layer                                                 # noqa: E402
import enemy_randomizer as ER                                    # noqa: E402

WORKSPACE = os.path.dirname(os.path.dirname(HERE))
PLAN_DEFAULT = os.path.join(WORKSPACE, "investigation", "enemy_plan.json")
PLANS_DIR = os.path.join(WORKSPACE, "investigation", "plans")   # 每层写盘时用的计划快照（默认计划会被重建）
BAR_TABLE = os.path.join(WORKSPACE, "investigation", "enemy_bar_names.csv")
# 基础本体事件补充：有些地图（如封印监牢）mod 没覆盖 event，血条名写在 Data0 的原始事件里。
# 这里放的是「名字 id + 本体事件文件」的兜底，不参与计划抽样（不改 plan/种子）。
BAR_FALLBACK = os.path.join(WORKSPACE, "investigation", "enemy_bar_fallback.csv")
VANILLA_EVENT_DIR = os.path.join(WORKSPACE, "investigation", "vanilla_events")
# 来源模型的「专属加护」：按模型人工登记 → 克隆行自动挂上。
# 换的是模型，但有些模型的战斗方式还依赖位置事件套的 SpEffect（目前只有劳弗仪卫 c2195：
# 圣龛事件套 18781..9 之一才有完整招式/数值）。不补这类 effect，换到别处就是缺招/缺数值的废人。
# 格式 model,sp_effect_id,note；文件可选，不进计划/种子（改它只影响写盘）。
DONOR_EFFECTS = os.path.join(WORKSPACE, "investigation", "enemy_donor_effects.csv")
MANIFEST_NAME = "enemy_manifest.json"
WRITE_VERSION = 9        # 9 = 来源模型专属加护（劳弗仪卫 c2195）；8 = 法魂放宽多阶段血量 clamp 上限（火焰巨人 5045 生效）；7 = 多阶段 Boss 血量（参考实现 5 组）；6 = 敌人倍增；5 = 敌人颜色；4 = 血条名随换入者
CLONE_NAME = "gfE:"                     # 克隆行的名字前缀（重跑时据此清理）
MAP_REL = os.path.join("map", "MapStudio")
DATA_SUB = "mod"        # 方案层根只放说明书，游戏数据在 <层根>/mod/（YAFSML 的 [mod] 要的是数据根）

# 参考实现的口径（EldenEnemyEditor.InitialNpcPass / EnemyRandomizer）：
BOSSISH = {"Boss", "MinorBoss", "Miniboss", "NightMiniboss", "DragonMiniboss", "Evergaol"}
TEAM_SIX = {"Basic", "Wildlife", "Mob", "HostileNPC", "Miniboss",
            "NightMiniboss", "DragonMiniboss", "Evergaol"}
SHRINK_RADIUS, SHRINK_HEIGHT = 2.5, 5.1
SHRINK_SKIP_NPC = {52300596, 52300496, 52300196}      # 幽影树化身：参考实现也跳过
THINK_NOSE_MAX, THINK_EYE_MAX = 5, 30
# 参考实现 EldenMiscSetup 的 "rainbow"：给 MaterialExParam 追加几行纯色，
# 再把 NpcParam 里第一个空着的 residentMaterialExParamId 指过去（换色不换模型）。
RAINBOW_NAME = "gfRainbow:"
RAINBOW_COLORS = ((255, 0, 0), (255, 128, 0), (255, 255, 0), (128, 255, 0),
                  (0, 200, 0), (0, 255, 255), (0, 128, 255), (80, 0, 255),
                  (255, 0, 255), (255, 0, 128), (255, 200, 0), (255, 255, 255))
RAINBOW_FIELDS = tuple("residentMaterialExParamId0%d" % i for i in range(5))
RAINBOW_BASE_ROW = 20300
RAINBOW_ID_BASE = 992000

# 参考实现的 Enemy Onslaught（实验）：复制 MSB 里的普通敌人 part。
# 复制体沿用同一个克隆行（数值/掉落/颜色都一致），只换 EntityID / PartID / 坐标；
# 不改 EMEVD —— 原敌人的事件不会作用到复制体，所以只让普通敌人参与（见计划层）。
ONSLAUGHT_OFFSET = 2.5      # 复制体相对原位偏移（米），绕一圈摆开
ONSLAUGHT_MAX_DUP = 2       # 1.0×=0，2.0×=1，3.0×=2

# M4 的掉落绑定：itemLotId_* 按位置原行抄 —— 掉落是 F3 的硬语义（绑地点，不跟换入者走）。
# v2 区域缩放后，防御/韧性/抗性不再抄位置原值：换入者保留自己整行，位置差由 area SpEffect
# 的 defense/buildup 倍率承担；攻击同理由 area SpEffect 的 attack 倍率承担。
# STAT_COPY_FIELDS 只留给旧层复验（manifest 里有这个字段时才检查）。
STAT_COPY_FIELDS = (
    # ① 固定值防御（数值型，不是倍率）
    "def_phys", "def_slash", "def_blow", "def_thrust", "def_mag",
    "def_fire", "def_thunder", "def_dark", "defFlickPower",
    # ② 防御/格挡（持盾时用）：四个元素 cut rate + 三个物理动作 cut rate + 防御等级/耐力
    "physGuardCutRate", "magGuardCutRate", "fireGuardCutRate", "thunGuardCutRate",
    "slashGuardCutRate", "blowGuardCutRate", "thrustGuardCutRate",
    "guardLevel", "staminaGuardDef",
    # ③ 受击伤害倍率（**这个位置原来挨打是几倍，换来的就几倍**；实测 72–78% 的单元
    #    与原位置不同，不抄就等于把"位置难度"换成"捐赠者难度"）
    "neutralDamageCutRate", "slashDamageCutRate", "blowDamageCutRate", "thrustDamageCutRate",
    "magicDamageCutRate", "fireDamageCutRate", "thunderDamageCutRate", "darkDamageCutRate",
    # ④ 异常状态抗性（毒/腐败/出血/诅咒/冻伤/发狂/睡眠）
    "resist_poison", "resist_desease", "resist_blood", "resist_curse",
    "resist_freeze", "resist_madness", "resist_sleep",
    # ⑤ 韧性（硬直/削韧恢复）：直接抄比用 SpEffect 代理省一层
    "superArmorDurability", "superArmorRecoverCorrection", "superArmorBrakeKnockbackDist",
)
LOT_COPY_FIELDS = ("itemLotId_enemy", "itemLotId_map")

# 本体自带的「等级缩放」：NpcParam.spEffectID3 指向 SpEffectParam 的 5 档之一，
# 每档同时乘 hp / 攻击 / 防御 / 耐力 / 抗性（7040：hp×5.2758、攻击×2.5817；
# 7000：hp×2.6951、攻击×1.6901）。克隆行整行照抄会**继承捐赠者的档位**，而 hp/防御
# 写的是位置原值 → 实际血量 = 位置基数 × 捐赠者档位倍率（实测 45.3% 的单元与原位置
# 不一致，最坏差 4 倍）。所以克隆行的这个槽必须写成**位置原行的那个值**（原行没有就
# 清 0）：换来的敌人"这个位置原本多强就多强"，攻击缩放也一并解决，不需要自造
# SpEffect、也不需要 clamp。
SCALE_SLOT = "spEffectID3"
SCALING_TIERS = (7000, 7010, 7020, 7030, 7040)

# 参考式区域缩放：用本体/DLC 的标准十步档（7000..7120、20007000..20007130），
# 按 SpEffectParam 的实际字段算 source→target 倍率，写进克隆行空着的 spEffectIDN。
# 特殊档（7130..7151、1935x、200072xx）不作地区档；0/异常走同地图标准档众数。
PLACES_TABLE = os.path.join(WORKSPACE, "investigation", "enemy_places.csv")
AREA_BASE_TIERS = tuple(7000 + 10 * i for i in range(13))
AREA_DLC_TIERS = tuple(20007000 + 10 * i for i in range(14))
AREA_SECTION_TIERS = {i + 1: t for i, t in enumerate(AREA_BASE_TIERS + AREA_DLC_TIERS)}
AREA_RANK = {t: r for r, t in AREA_SECTION_TIERS.items()}
AREA_BASE_ROW = 7000
AREA_EFFECT_ID_BASE = 7800000
AREA_EFFECT_ID_LIMIT = 7900000
AREA_FIELDS = (
    ("health", ("maxHpRate",)),
    ("stamina", ("maxStaminaRate",)),
    ("staminadamage", ("staminaAttackRate",)),
    ("damage", ("physicsAttackPowerRate", "magicAttackPowerRate", "fireAttackPowerRate",
                "thunderAttackPowerRate", "darkAttackPowerRate")),
    ("damagerate", ("physicsAttackRate", "magicAttackRate", "fireAttackRate",
                    "thunderAttackRate", "darkAttackRate")),
    ("defense", ("physicsDiffenceRate", "magicDiffenceRate", "fireDiffenceRate",
                 "thunderDiffenceRate", "darkDiffenceRate")),
    ("buildup", ("registPoizonChangeRate", "registDiseaseChangeRate", "registBloodChangeRate",
                 "registFreezeChangeRate", "registSleepChangeRate", "registMadnessChangeRate")),
    ("xp", ("haveSoulRate",)),
)
AREA_FIELD_NAMES = tuple(f for _g, fs in AREA_FIELDS for f in fs)
# Boss 进杂兵位（b2m）的"降级"倍率：血量/魂 ×0.25 = 按杂兵量级看（原有）；
# 攻击力 ×0.5 = 伤害砍半（2026-10-23 用户反馈"打你还是很疼"后加）。
# 只动 damage 组（*AttackPowerRate）：十步档本身只缩放这一组，damagerate /
# defense / buildup 在所有标准档里恒为 1.0，动它们等于凭空造一条游戏里不存在的规则。
# 调参入口就是这张表：太软调到 0.6，还是一招带走调到 0.35。
# 数值的**单一来源**在 enemy_balance（平衡层要靠它把 target_hp 预先除回来，否则
# b2m 的有效血量会被写盘层再砍一刀，v1.4.0 实测只有位置原值的 0.21~0.31）。
AREA_BOSS_AS_BASIC_FACTORS = {
    "health": balance_model.B2M_HP_FACTOR,
    "xp": balance_model.B2M_XP_FACTOR,
    "damage": balance_model.B2M_DAMAGE_FACTOR,
}

# 参考实现的多阶段 Boss 血量修正（SoulsRandomizers EldenEnemyEditor.cs 第 961–1018 行，
# InitialNpcPass 里的 CreatedReferredDamagePair 段）。参考实现没有通用比例，而是这 5 组
# **按实体硬编码**的 p1/p2 血量关系（p1 = 一阶段行，p2 = 二阶段行）：
#   Godfrey   p2 = p2 - p1                    （clamp 500..5000）
#   Maliketh  p1 = p1 * 45%，p2 = p2 - p1      （clamp 500..5000）
#   FireGiant p2 = (p2 - p1) * 90%             （参考 clamp 500..5000；法魂放宽见下）
#   Messmer   p1 = p1 * 50%，p2 = p2 - p1      （clamp 500..5000）
#   PCR       p1 = p1 * 35%，p2 = p2 - p1      （clamp 500..5000）
# 参考实现里 Messmer / PCR 包在 if (opt["dlc"]) 内；这里按行是否存在决定，不额外加开关。
# 参考原版的 p2 clamp 是 500..5000；法魂的 p2 基数普遍更高（火焰巨人 9095），
# 用户同意放宽到 500..6000，只让火焰巨人的 5045 生效。
PHASE_PAIR_CLAMP = (500, 6000)

PHASE_PAIR_FIXES = (
    {"id": "hoarah_loux", "mode": "diff_p2",
     "phase1": (11050801, 47200070), "phase2": (11050800, 47210070)},
    {"id": "maliketh", "mode": "p1_pct_sub", "pct": 45,
     "phase1": (13000801, 21100072), "phase2": (13000800, 21101072)},
    {"id": "fire_giant", "mode": "diff_pct_p2", "pct": 90,
     "phase1": (1052520801, 47600050), "phase2": (1052520800, 47601050)},
    {"id": "messmer", "mode": "p1_pct_sub", "pct": 50,
     "phase1": (21010801, 51300099), "phase2": (21010800, 51301099)},
    {"id": "pcr", "mode": "p1_pct_sub", "pct": 35,
     "phase1": (20010801, 52200089), "phase2": (20010800, 52201089)},
)
_TSIZE = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "i32": 4, "f32": 4}


class WriteError(Exception):
    pass


# ────────────────────────── 小工具 ──────────────────────────

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def _put(b, o, value, typ):
    if typ in ("u32", "i32", "s32"):
        struct.pack_into("<I", b, o, int(value) & 0xFFFFFFFF)
    elif typ == "f32":
        struct.pack_into("<f", b, o, float(value))
    elif typ in ("u16", "i16", "s16"):
        struct.pack_into("<H", b, o, int(value) & 0xFFFF)
    elif typ in ("u8", "i8", "s8"):
        struct.pack_into("<B", b, o, int(value) & 0xFF)
    else:
        raise WriteError("不认识的字段类型 %r" % (typ,))


def _get(b, o, typ):
    if typ == "u8":
        return b[o]
    if typ == "s8":
        return struct.unpack_from("<b", b, o)[0]
    if typ == "u16":
        return struct.unpack_from("<H", b, o)[0]
    if typ == "s16":
        return struct.unpack_from("<h", b, o)[0]
    if typ == "u32":
        return struct.unpack_from("<I", b, o)[0]
    if typ in ("s32", "i32"):
        return struct.unpack_from("<i", b, o)[0]
    if typ == "f32":
        return struct.unpack_from("<f", b, o)[0]
    raise WriteError("不认识的字段类型 %r" % (typ,))


def _same_bytes(a, b, off, typ):
    n = _TSIZE[typ]
    return a[off:off + n] == b[off:off + n]


def _get_bit(buf, byte_off, bit):
    return (buf[byte_off] >> bit) & 1


def _set_bit(buf, byte_off, bit, val):
    cur = buf[byte_off]
    buf[byte_off] = (cur | (1 << bit)) if val else (cur & ~(1 << bit))


# ────────────────────────── param 表 ──────────────────────────

class FieldBook(object):
    """按 paramdef 现算字段偏移（不写死数字，paramdef 换了也不至于静默写错位置）。"""

    def __init__(self, param_name):
        fields, size = ER.paramdef_fields(param_name)
        if not fields:
            raise WriteError("找不到 %s 的 paramdef（Paramdex 缺失）" % param_name)
        self.fields = {nm: (typ, off, sz) for nm, typ, off, sz in fields}
        self.bits = ER.bit_field_map(fields)
        self.size = size

    def off(self, name):
        if name not in self.fields:
            raise WriteError("paramdef 里没有字段 %s" % name)
        return self.fields[name][1]

    def typ(self, name):
        return self.fields[name][0]

    def bit(self, name):
        if name not in self.bits:
            raise WriteError("paramdef 里没有位域 %s" % name)
        return self.bits[name]


def row_names(pf):
    """{行 id: 名字}（重复 id 时后者覆盖；只用来认上一轮的克隆行）"""
    out = {}
    for rid, _dd, nm in pf.entries:
        end = nm
        while end + 1 < len(pf.data) and pf.data[end:end + 2] != b"\0\0":
            end += 2
        out[rid] = pf.data[nm:end].decode("utf-16-le", "replace")
    return out


def apply_phase_pair_fixes(npc_pf, fbn, enabled=True, log=print):
    """按参考实现修多阶段 Boss 的 p1/p2 血量（直接改 NpcParam 里那两行的 hp 字段）。

    参考实现不是「总血量守恒后按比例分」，而是 EldenEnemyEditor.cs:961-1018 的 5 组硬编码
    修正。这里照抄公式与参考 clamp（原版 500 < hp < 5000，法魂放宽为 500..6000），
    并把 before/after 记进 manifest，
    供 verify_layer 复验。返回 (可能已改的 ParamFile, 记录字典)。
    """
    rows = []
    res = {"enabled": bool(enabled),
           "source": "SoulsRandomizers/EldenEnemyEditor.cs:961-1018",
           "clamp": list(PHASE_PAIR_CLAMP), "clamp_reference": [500, 5000], "rows": rows}
    if not enabled:
        return npc_pf, res
    hp_off = fbn.off("hp")
    hp_typ = fbn.typ("hp")
    if hp_typ not in ("u32", "s32", "i32"):
        raise WriteError("NpcParam.hp 的类型是 %r，不能按参考实现直接改" % (hp_typ,))
    raw = bytearray(npc_pf.data)
    changed = False

    def hp_of(nid):
        o = npc_pf.offset_of(nid)
        return None if o is None else _get(npc_pf.data, o + hp_off, hp_typ)

    def add(role, entity, nid, before, after, applied, note=""):
        rows.append({"group": spec["id"], "role": role, "entity": entity,
                     "npc_id": nid, "before": before, "after": after,
                     "applied": bool(applied), "note": note})

    for spec in PHASE_PAIR_FIXES:
        e1, n1 = spec["phase1"]
        e2, n2 = spec["phase2"]
        b1, b2 = hp_of(n1), hp_of(n2)
        if b1 is None:
            add("phase1", e1, n1, None, None, False, "NpcParam 里没有这一行")
        if b2 is None:
            add("phase2", e2, n2, None, None, False, "NpcParam 里没有这一行")
        if b1 is None or b2 is None:
            log("[写盘] 多阶段血量（参考实现）%s：缺行，跳过" % spec["id"])
            continue

        new1 = b1
        if spec["mode"] == "p1_pct_sub":
            new1 = b1 * int(spec["pct"]) // 100
            o1 = npc_pf.offset_of(n1)
            _put(raw, o1 + hp_off, new1, hp_typ)
            changed = True
            add("phase1", e1, n1, b1, new1, True,
                "p1 = p1 * %d%%（参考实现无条件写）" % spec["pct"])
        elif spec["mode"] not in ("diff_p2", "diff_pct_p2"):
            raise WriteError("不认识的多阶段血量模式 %r" % (spec["mode"],))

        if spec["mode"] == "diff_p2":
            new2 = b2 - b1
            formula = "p2 = p2 - p1"
        elif spec["mode"] == "diff_pct_p2":
            new2 = (b2 - b1) * int(spec["pct"]) // 100
            formula = "p2 = (p2 - p1) * %d%%" % spec["pct"]
        else:
            new2 = b2 - new1
            formula = "p2 = p2 - p1'"
        ok = PHASE_PAIR_CLAMP[0] < new2 < PHASE_PAIR_CLAMP[1]
        if ok:
            o2 = npc_pf.offset_of(n2)
            _put(raw, o2 + hp_off, new2, hp_typ)
            changed = True
            add("phase2", e2, n2, b2, new2, True, formula)
        else:
            add("phase2", e2, n2, b2, b2, False,
                "%s = %d，超出法魂放宽后的 clamp %d..%d，保持原值" % (formula, new2, PHASE_PAIR_CLAMP[0], PHASE_PAIR_CLAMP[1]))
        log("[写盘] 多阶段血量（参考实现）%s：p1 %s→%s；p2 %s→%s%s"
            % (spec["id"], b1, new1, b2, new2 if ok else b2,
               "" if ok else "（clamp 不通过，p2 不改）"))

    res["changed"] = changed
    res["applied"] = sum(1 for r in rows if r["applied"])
    return (param_bin.ParamFile(bytes(raw)) if changed else npc_pf), res


def find_param_name(names, suffix):
    for n in names:
        if n.endswith(suffix):
            return n
    raise WriteError("regulation 里找不到 %s" % suffix)


def load_donor_effects(path=DONOR_EFFECTS):
    """读来源模型的专属加护表 → {model: sp_effect_id}。文件不存在返回空表。"""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            model = (row.get("model") or "").strip()
            try:
                eff = int(row.get("sp_effect_id") or 0)
            except (TypeError, ValueError):
                continue
            if model and eff > 0:
                out[model] = eff
    return out


def load_bar_fallback(path=BAR_FALLBACK):
    """读「mod 没覆盖的地图」的旧血条名（来自本体 EMEVD）。

    返回 {(map, entity): [old_name_id, …]}；文件不存在返回空表。
    只影响写盘时的名字替换，**不进入计划/种子** —— 改这张表不会重排其它位置。
    """
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                ent = int(row["entity"])
                nid = int(row["name_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if ent and nid:
                out.setdefault((row["map"], ent), []).append(nid)
    return out


def _rel_of(unit):
    """位置与捐赠者的 boss 属性关系：same / b2m（boss 进杂兵位）/ m2b

    v1.4.0：双人 Boss 的第二只数据层是 Helper，但它站在**boss 侧**（有血条、有
    事件死亡条件）。不把它算成 boss 侧的话会被判成 m2b，克隆行写
    disableInitializeDead=1（「不按事件 flag 初始化死亡」），第二只可能出场即死/不生成。
    """
    # v1.4.1：多阶段组的各阶段实体原类可能是 Helper（如女武神二阶段、幽影树
    # 化身 2~6 阶），但它们站在 boss 侧，不是「Boss 进杂兵位」—— 漏这一个判断会让
    # 这些行白吃 health×0.25（只有原强度的 1/4），对齐 enemy_balance.rel_of。
    p = (unit.get("cls") in BOSSISH or bool(unit.get("duo"))
         or bool(unit.get("multiphase")))
    d = (unit.get("new_cls") or unit.get("donor_cls")) in BOSSISH
    if p == d:
        return "same"
    return "b2m" if d else "m2b"


def _clone_key(unit, rel=None):
    """克隆行去重键：(捐赠行, 血量, 魂, 关系, 位置原威胁等级, 位置原行 id)。

    第五维是 M2.1 修的「野外 Boss 血条」：EMEVD 模板 90005870 用
    IF Field Battle BGM Active(<threatLv>) 把大血条卡住，换人后若克隆行沿用
    捐赠者的 threatLv，条件永远不成立 → 血条与 BGM 一起丢。把威胁等级设回
    **这个位置原本那只**的值，条件就恢复成立、BGM 也还是原 Boss 的。

    第六维是 M4 的掉落绑定：同一只会被多个位置用到，但每个位置的**掉落**必须跟着
    位置走（F3：绑地点，不跟 boss 走），所以原行 id 也是键的一部分。

    第七维是原位置档位：用于复验/统计（克隆行本身保留捐赠者的 spEffectID3）。

    第八维是区域 SpEffect id：同一换入者落到不同区域档，挂的 area effect 不同，
    伤害/防御/血量倍率也不同，所以 effect id 也必须是键的一部分。
    """
    return (int(unit["new_npc_id"]), int(unit.get("target_hp") or 0),
            int(unit.get("target_soul") or 0), rel or _rel_of(unit),
            int(unit.get("target_threat") or unit.get("old_threat") or 0),
            int(unit.get("old_npc_id") or 0),
            int(unit.get("old_scale") or 0),
            int(unit.get("area_effect") or 0))


def _npc_threat(npc_pf, fbp, npc_id):
    """读某个 NpcParam 行的 threatLv；行不存在返回 0。"""
    if not npc_id:
        return 0
    try:
        p = npc_pf.payload(int(npc_id))
    except Exception:
        return 0
    return 0 if p is None else _u32(p, fbp.off("threatLv"))


def _npc_scale(npc_pf, fbp, npc_id):
    """读某行 NpcParam 的等级缩放槽（spEffectID3）；行不存在返回 0。"""
    if not npc_id:
        return 0
    try:
        p = npc_pf.payload(int(npc_id))
    except Exception:
        return 0
    return 0 if p is None else _u32(p, fbp.off(SCALE_SLOT))


def _area_rank(npc_pf, fbp, npc_id):
    """NpcParam.spEffectID3 → 标准档的 section 序号；非标准返回 0。"""
    return AREA_RANK.get(_npc_scale(npc_pf, fbp, npc_id), 0)


def load_area_map_modes(places_csv, npc_pf, fbp):
    """同地图标准档众数（返回**档位 id**）：只给 0/缺行的位置兜底，不覆盖实体自己的档位。"""
    counts = {}
    if not places_csv or not os.path.isfile(places_csv):
        return {}
    with open(places_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row.get("npc_id") or 0)
            except (TypeError, ValueError):
                continue
            t = _npc_scale(npc_pf, fbp, nid)
            if t not in AREA_RANK:
                continue
            m = row.get("map") or ""
            c = counts.setdefault(m, {})
            c[t] = c.get(t, 0) + 1
    out = {}
    for m, c in counts.items():
        out[m] = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return out


def _area_tier_ok(sp_pf, sp_fb, tier):
    """这一档的 SpEffectParam 行**能不能当缩放档**用。

    标准十步档一律可用；特殊档（法魂 7131..7151、人类 1935x、DLC 200072xx）只要
    行存在且 maxHpRate 落在合理区间**也当档用** —— 蒙格这类 Boss 的 spEffectID3 是
    7144（maxHpRate=6.6261、攻击 ×2.6991），旧写法把它当"无档 = 1.0"，于是它自带的
    ×6.63 血量与 ×2.70 攻击**再加上**目标区域的倍率（盖利德 7040：×5.28 / ×2.58），
    有效血量直接 ×2.9、攻击约 ×7（2026-10-23 实测：大壶传送门蒙格 26,778 HP）。
    7130（maxHpRate=0.1 的占位效果）这类不合理值仍然退回"无档"。
    """
    if tier in AREA_RANK:
        return True
    try:
        p = sp_pf.payload(int(tier))
    except Exception:
        return False
    hp = _f32(p, sp_fb.off("maxHpRate"))
    atk = _f32(p, sp_fb.off("physicsAttackPowerRate"))
    return 0.5 <= hp <= 20.0 and atk > 0.0


def _area_section(npc_id, map_name, npc_pf, fbp, map_modes, sp_pf, sp_fb, allow_map=True):
    """返回 (档位 id / 0 = 无档, 来源)：direct / map / none。

    档位 id 是 SpEffectParam 里的**真实行**（标准十步档与特殊档都算），下游直接按行取值。
    allow_map=False 用于**换入者自己**的源档：换入者 spEffectID3=0 或行不存在时倍率就是 1.0，
    不能拿地图档替它"补"一个不存在的源档；否则 area effect 会除以一个换入者没有的档。
    """
    t = _npc_scale(npc_pf, fbp, npc_id)
    if t and _area_tier_ok(sp_pf, sp_fb, t):
        return t, "direct"
    if allow_map:
        t = map_modes.get(map_name or "")
        if t:
            return t, "map"
    return 0, "none"


def _area_values(sp_pf, sp_fb, tier):
    if not tier:
        return {name: 1.0 for name in AREA_FIELD_NAMES}
    try:
        p = sp_pf.payload(int(tier))
    except Exception:
        return {name: 1.0 for name in AREA_FIELD_NAMES}
    return {name: _f32(p, sp_fb.off(name)) for name in AREA_FIELD_NAMES}


def _area_factors(src_vals, dst_vals, boss_as_basic=False):
    """source section → target section 的倍率；同 section 为 1。

    boss_as_basic（Boss 换进杂兵位）再叠一组"降级"倍率：血量/魂 ×0.25、
    攻击力 ×0.5。见 AREA_BOSS_AS_BASIC_FACTORS。
    """
    out = {}
    for group, fields in AREA_FIELDS:
        gfac = AREA_BOSS_AS_BASIC_FACTORS.get(group, 1.0) if boss_as_basic else 1.0
        for name in fields:
            s, d = src_vals.get(name, 0.0), dst_vals.get(name, 0.0)
            val = (d / s) if s else 1.0
            out[name] = val * gfac
    return out


def _make_area_effect(base_payload, sp_fb, factors):
    b = bytearray(base_payload)
    for name, val in factors.items():
        _put(b, sp_fb.off(name), val, sp_fb.typ(name))
    return bytes(b)


def _attach_area_effect(payload, fbp, effect_id):
    """把区域 SpEffect 写进克隆行第一个空着的 spEffectIDN（跳过 spEffectID3）。"""
    b = bytearray(payload)
    for i in range(32):
        name = "spEffectID%d" % i
        if name == SCALE_SLOT:
            continue
        off, typ = fbp.off(name), fbp.typ(name)
        if _get(b, off, typ) in (0, -1):
            _put(b, off, effect_id, typ)
            return bytes(b), name
    return None, None


def collect_clones(units, npc_pf, fbp):
    """给每个 (捐赠行, hp, 魂, 关系, 原威胁, 原行) 分配一条新行 id（去重）。"""
    keys = []
    for u in units:
        if u.get("new_npc_id") is None:
            continue
        keys.append(_clone_key(u))
    uniq = sorted(set(keys))
    used = set(npc_pf.ids)
    alloc = {}
    for k in uniq:
        nid = k[0]
        while nid in used:
            nid += 1
        if nid >= 0x7FFFFFFF:
            raise WriteError("NpcParam 行 id 用尽")
        used.add(nid)
        alloc[k] = nid
    return alloc


def _rainbow_index(donor, old_npc, n):
    """同一个捐赠者+位置原行固定用同一种颜色（可复现，不依赖全局随机流）。"""
    return (int(donor) * 131 + int(old_npc) * 17) % max(1, n)


def make_npc_clone(base_payload, key, fbp, src_payload=None, rainbow_ids=None,
                   donor_effects=None):
    """复制捐赠行 → 改 hp/魂/威胁等级/必改位 → 抄位置掉落 + 挂区域 effect。

    src_payload 是**这个位置原本那只**的 NpcParam 行，只用来抄 itemLotId_*（F3：掉落
    绑地点）；防御/韧性/抗性保留捐赠者整行，区域差由 area SpEffect 承担。
    """
    donor, hp, soul, rel, old_threat, old_npc, old_scale, area_effect = key
    b = bytearray(base_payload)
    if len(b) < fbp.size:
        raise WriteError("捐赠行 %s 只有 %d 字节 < paramdef 行大小 %d" % (donor, len(b), fbp.size))
    _put(b, fbp.off("hp"), hp, fbp.typ("hp"))
    _put(b, fbp.off("getSoul"), soul, fbp.typ("getSoul"))

    bo, bi = fbp.bit("isSoulGetByBoss")
    _set_bit(b, bo, bi, 0)                       # 魂不依赖"Boss 击杀"判定
    bo, bi = fbp.bit("disableRespawn")
    _set_bit(b, bo, bi, 0)
    if rel == "b2m":
        bo, bi = fbp.bit("disableInitializeDead")
        _set_bit(b, bo, bi, 0)                   # 参考实现：Boss 当杂兵要能被事件唤醒
    elif rel == "m2b":
        bo, bi = fbp.bit("disableInitializeDead")
        _set_bit(b, bo, bi, 1)                   # 参考实现：杂兵当 Boss 不自动死

    # 威胁等级：野外 Boss 的 EMEVD 用 IF Field Battle BGM Active(threatLv) 卡血条，
    # 换人后必须沿用**位置原本那只**的 threatLv，血条与 BGM 才会正常（M2.1）。
    donor_threat = _u32(b, fbp.off("threatLv"))
    threat = old_threat if old_threat > 0 else donor_threat
    if threat == 0:
        threat = 1
    _put(b, fbp.off("threatLv"), threat, fbp.typ("threatLv"))

    notes = {"rel": rel}
    if threat != donor_threat:
        notes["threatLv"] = (donor_threat, threat)

    # 等级缩放：保留**捐赠者自己的** spEffectID3；区域的相对强度由克隆行上另挂的
    # area SpEffect 负责（参考实现也是换入者整行 + 区域 effect，不把旧档抄到换入者身上）。
    donor_scale = _u32(b, fbp.off(SCALE_SLOT))
    notes["donor_scale"] = donor_scale
    notes["old_scale"] = old_scale

    # 掉落仍绑地点（F3）；防御/韧性/抗性不再从旧位置抄 —— 换入者保留自己整行，
    # 区域差由 area SpEffect 的 defense/buildup 倍率承担。
    if src_payload is not None and len(src_payload) >= fbp.size:
        copied = []
        for name in LOT_COPY_FIELDS:
            off, typ = fbp.off(name), fbp.typ(name)
            val = _get(src_payload, off, typ)
            if not _same_bytes(b, src_payload, off, typ):
                _put(b, off, val, typ)
                copied.append(name)
        if copied:
            notes["from_src"] = copied
        notes["src_npc"] = old_npc
    elif old_npc:
        notes["src_missing"] = old_npc

    if area_effect:
        new_b, slot = _attach_area_effect(b, fbp, area_effect)
        if new_b is not None:
            b = bytearray(new_b)
            notes["area_effect"] = (slot, area_effect)
    donor_model = donor // 10000
    _deff = (donor_effects or {}).get("c%d" % donor_model)
    if _deff:
        # 来源模型自带的加护（如劳弗仪卫的圣龛变体 SpEffect）：写进下一个空槽。
        new_b, slot = _attach_area_effect(b, fbp, _deff)
        if new_b is not None:
            b = bytearray(new_b)
            notes["donor_effect"] = (slot, _deff)
    if rainbow_ids:
        # 参考实现只填第一个 -1 的槽；克隆行沿用捐赠者的材质槽，所以有 -1 才染色。
        for name in RAINBOW_FIELDS:
            off, typ = fbp.off(name), fbp.typ(name)
            if _get(b, off, typ) == -1:
                cid = rainbow_ids[_rainbow_index(donor, old_npc, len(rainbow_ids))]
                _put(b, off, cid, typ)
                notes["rainbow"] = (name, cid)
                break
        else:
            notes["rainbow_skipped"] = True
    if donor not in SHRINK_SKIP_NPC:
        r, h = _f32(b, fbp.off("hitRadius")), _f32(b, fbp.off("hitHeight"))
        if r > SHRINK_RADIUS:
            _put(b, fbp.off("hitRadius"), SHRINK_RADIUS, "f32")
            notes["hitRadius"] = (r, SHRINK_RADIUS)
        if h > SHRINK_HEIGHT:
            _put(b, fbp.off("hitHeight"), SHRINK_HEIGHT, "f32")
            notes["hitHeight"] = (h, SHRINK_HEIGHT)
    return bytes(b), notes


def make_think_clone(base_payload, fbp_t, goal=None):
    """复制 think 行：压小视野/嗅觉（bossAsBasic），可选把 battleGoalID 换成通用 AI。

    battleGoalID 是怪物的「战斗 AI 脚本」编号：传送类敌人（唤声船、蕾菈娜）的传送是
    脚本内的行为，且需要地图事件配合；换到没有配套事件的地图就会原地循环。把它们换成
    通用近战 goal 可以彻底去掉传送（实验性，见 yaml randomization.ai_fallback）。
    """
    b = bytearray(base_payload)
    notes = {}
    if goal:
        off = fbp_t.off("battleGoalID")
        cur = struct.unpack_from("<i", b, off)[0]
        struct.pack_into("<i", b, off, int(goal))
        notes["battleGoalID"] = (cur, int(goal))
    for name, cap in (("nose_dist", THINK_NOSE_MAX), ("eye_dist", THINK_EYE_MAX)):
        off = fbp_t.off(name)
        cur = struct.unpack_from("<H", b, off)[0]
        if cur > cap:
            struct.pack_into("<H", b, off, cap)
            notes[name] = (cur, cap)
    return bytes(b), notes


# ────────────────────────── MSB 写 ──────────────────────────

def part_index(m):
    """{(part_name, occurrence): 条目下标} —— 与 enemy_data_build 的扫描顺序一致。"""
    seen, out = {}, {}
    for i, p in m.parts():
        if p["type"] != msb_read.PART_TYPE_ENEMY:
            continue
        k = p["part_name"]
        seen[k] = seen.get(k, 0) + 1
        out[(k, seen[k])] = i
    return out


def _think_clone_key(u):
    """需要 think 克隆的单元 → 键；否则 None。rel=b2m 压视野；ai_goal 换战斗 AI。"""
    goal = int(u.get("ai_goal") or 0)
    base = int(u.get("new_think_id") or 0)
    if base <= 0:
        return None          # 没有 think 的捐赠者：保留原 ThinkParamID，别写 0
    if _rel_of(u) == "b2m" or goal:
        return (base, goal)
    return None


def patch_map(raw, units, clone_of, think_of, map_name=None, log=None):
    """把一张图的替换全打上，返回 (新明文, 统计)。"""
    m = msb_edit.Msb(raw)
    idx = part_index(m)
    parts = dict(m.parts())
    changed, models_added = {}, []
    for u in units:
        nid = clone_of[_clone_key(u)]
        think = int(u["new_think_id"]) or int(u.get("think_id") or 0)
        tk = _think_clone_key(u)
        if tk is not None:
            think = think_of.get(tk, think)
        model = u["new_model"]
        mi = m.model_entry(model)
        if mi < 0:
            mi = m.add_model(model, msb_edit.chr_sib_path(model))
            models_added.append(model)
        for pl in u["places"]:
            if map_name and pl["map"] != map_name:
                continue                      # 跨图 link 组：这张图只改属于它自己的那份
            k = (pl["part_name"], int(pl["occurrence"]))
            if k not in idx:
                raise WriteError("图里找不到 part %s#%s（%s）" % (k[0], k[1], pl["map"]))
            i = idx[k]
            cur = parts[i]
            if int(cur["npc_id"]) != int(pl["old_npc_id"]) or cur["model"] != pl["old_model"]:
                raise WriteError(
                    "身份对不上：%s %s#%s 现在是 npc=%s model=%s，计划说 npc=%s model=%s"
                    % (pl["map"], k[0], k[1], cur["npc_id"], cur["model"],
                       pl["old_npc_id"], pl["old_model"]))
            m.set_part_int(i, msb_read.P_MODELIDX, mi)
            m.set_part_typedata(i, msb_read.E_NPC, nid)
            m.set_part_typedata(i, msb_read.E_THINK, think)
            m.set_part_typedata(i, msb_read.E_CHARA, int(u["new_chara_id"]))
            m.set_part_typedata(i, 0x15, 0, "u8")              # UnkT15 = false
            m.set_part_typedata(i, 0x38, -1)                   # BackupEventAnimID = -1
            changed[i] = (pl, nid, think)
            if log:
                log("    %s#%s → npc %s/%s think %s chara %s model %s" % (
                    k[0], k[1], cur["npc_id"], nid, think, u["new_chara_id"], model))

    # Enemy Onslaught（实验）：复制普通敌人的 part。复制体沿用同一个克隆行，
    # 只改 EntityID / PartID / InstanceID 与坐标；事件不复制（只让普通敌人参与）。
    dups = []
    want = sum(int(u.get("dup_count") or 0) for u in units)
    if want:
        pb = m.block("PARTS_PARAM_ST")
        if pb is None:
            raise WriteError("这张图没有 PARTS_PARAM_ST，不能复制敌人")
        # EntityID 是 u32；0xFFFFFFFF 是「无实体」哨兵，不能拿它 +1。
        ents = [int(parts[i]["entity_id"]) for i in parts
                if 0 < int(parts[i].get("entity_id") or 0) < 0xFFFFFF00]
        next_ent = (max(ents) + 1) if ents else 1000000
        if next_ent >= 0xFFFFFF00:
            next_ent = 1000000
        ids = [struct.unpack_from("<i", e, msb_read.P_ID)[0] for e in pb["entries"] if len(e) > msb_read.P_ID + 4]
        insts = [struct.unpack_from("<i", e, msb_read.P_INSTANCEID)[0]
                 for e in pb["entries"] if len(e) > msb_read.P_INSTANCEID + 4]
        next_pid = (max(ids) + 1) if ids else 1
        next_inst = (max(insts) + 1) if insts else 1
        for u in units:
            n = int(u.get("dup_count") or 0)
            if n <= 0:
                continue
            n = min(n, ONSLAUGHT_MAX_DUP)
            nid = clone_of[_clone_key(u)]
            think = int(u["new_think_id"]) or int(u.get("think_id") or 0)
            tk = _think_clone_key(u)
            if tk is not None:
                think = think_of.get(tk, think)
            model = u["new_model"]
            for pl in u["places"]:
                if map_name and pl["map"] != map_name:
                    continue
                k = (pl["part_name"], int(pl["occurrence"]))
                i = idx[k]
                source = bytes(pb["entries"][i])
                base_x = struct.unpack_from("<f", source, msb_read.P_POS)[0]
                base_z = struct.unpack_from("<f", source, msb_read.P_POS + 8)[0]
                for j in range(n):
                    e = bytearray(source)
                    ent = next_ent
                    next_ent += 1
                    ent_rel = struct.unpack_from("<q", e, msb_read.P_ENTITY_DATA_OFF)[0]
                    struct.pack_into("<I", e, ent_rel, ent)
                    struct.pack_into("<i", e, msb_read.P_ID, next_pid)
                    next_pid += 1
                    struct.pack_into("<i", e, msb_read.P_INSTANCEID, next_inst)
                    next_inst += 1
                    ang = 2.0 * math.pi * (j + 1) / max(n, 1) + 0.6
                    x = base_x + ONSLAUGHT_OFFSET * math.cos(ang)
                    z = base_z + ONSLAUGHT_OFFSET * math.sin(ang)
                    struct.pack_into("<f", e, msb_read.P_POS, x)
                    struct.pack_into("<f", e, msb_read.P_POS + 8, z)
                    pb["entries"].append(bytes(e))
                    dups.append({"index": len(parts) + len(dups), "source_index": i,
                                 "source_entity": int(parts[i].get("entity_id") or 0),
                                 "entity": ent, "part_id": next_pid - 1,
                                 "instance_id": next_inst - 1,
                                 "npc": nid, "think": think, "model": model,
                                 "x": x, "z": z})
    out = m.assemble()
    return out, {"changed": changed, "models_added": models_added,
                 "dups": dups, "msb": m}


# ────────────────────────── 校验 ──────────────────────────

def verify_map(base_raw, out_raw, stat):
    """读回校验：part 数不变；只有目标 part 的身份字段变了；新模型已登记。"""
    a, b = msb_edit.Msb(base_raw), msb_edit.Msb(out_raw)
    pa = dict(a.parts())
    pb = dict(b.parts())
    dups = stat.get("dups") or []
    if len(pa) + len(dups) != len(pb):
        raise WriteError("读回校验：part 数 %d + 复制 %d → %d" % (len(pa), len(dups), len(pb)))
    for i, x in pa.items():
        y = pb[i]
        if i in stat["changed"]:
            pl, nid, think = stat["changed"][i]
            if int(y["npc_id"]) != nid or int(y["think_id"]) != think:
                raise WriteError("读回校验：%s 的 npc/think 没写进去" % pl["part_name"])
        elif x != y:
            raise WriteError("读回校验：非目标 part %s 被动了" % x["part_name"])
    for d in dups:
        i = d["index"]
        if i not in pb:
            raise WriteError("读回校验：复制体 #%d 不存在" % i)
        y = pb[i]
        if (int(y.get("entity_id") or 0) != int(d["entity"])
                or int(y.get("npc_id") or 0) != int(d["npc"])
                or int(y.get("think_id") or 0) != int(d["think"])
                or y.get("model") != d["model"]):
            raise WriteError("读回校验：复制体 #%d 的身份不对\n  期望 %s\n  实际 %s" % (i, d, y))
        if abs(float(y.get("x") or 0.0) - float(d["x"])) > 0.01 or \
           abs(float(y.get("z") or 0.0) - float(d["z"])) > 0.01:
            raise WriteError("读回校验：复制体 #%d 的位置不对" % i)
    extra = [x for x in stat["models_added"] if x not in b.models()]
    if extra:
        raise WriteError("读回校验：新模型没登记进 MSB：%s" % extra)
    return {"parts": len(pb), "changed": len(stat["changed"]),
            "models": len(a.models()), "models_after": len(b.models()),
            "dup_count": len(dups)}


# ────────────────────────── 主流程 ──────────────────────────

def check_owners(units):
    """身份所有权：一个 (map, part) 只能有一个写者。冲突直接 raise —— 早于任何写盘动作。"""
    seen = {}
    for u in units:
        for pl in u["places"]:
            k = (pl["map"], pl["part_name"], int(pl["occurrence"]))
            if k in seen:
                raise WriteError("owner 冲突：%s#%s（%s）同时被 %s 与 %s 改"
                                 % (k[1], k[2], k[0], seen[k], u["key"]))
            seen[k] = u["key"]
    return len(seen)


def build(plan_path=PLAN_DEFAULT, label=None, out_root=None, base_reg=None,
          limit=None, dry_run=False, log=print, plans_dir=None):
    plan = json.load(open(plan_path, encoding="utf-8"))
    features = ((plan.get("meta") or {}).get("options") or {}).get("features") or {}
    units = [u for u in plan["units"] if u.get("new_npc_id") is not None]
    if not units:
        raise WriteError("计划里没有任何替换单元")
    n_places = check_owners(units)
    label = label or time.strftime("敌人_%Y%m%d_%H%M%S")
    out_root = out_root or plan_layer.plans_root()
    stage = os.path.join(out_root, ".stage_" + label)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    stage_data = os.path.join(stage, DATA_SUB)

    mod = plan_layer.mod_root()
    base_reg = base_reg or os.path.join(mod, "regulation.bin")
    log("[写盘] 计划  = %s" % plan_path)
    log("[写盘] 基线  = %s" % base_reg)
    log("[写盘] 输出  = %s" % os.path.join(out_root, label))

    bnd = erio.read_regulation(base_reg)
    reg_sha = sha256_file(base_reg)
    # 参考实现的 nightday：ChrActivateConditionParam 的 101000 行控制夜间 Boss 出现
    # 时间（20:00-05:59）；把四个 time 字段清零 = 白天也出现。这是全局参数，改一次即可。
    night_meta = None
    if features.get("nightday"):
        night_name = find_param_name([n for n, _ in bnd.files], "ChrActivateConditionParam.param")
        if not night_name:
            raise WriteError("开了夜间BOSS全天，但基线里没有 ChrActivateConditionParam")
        npf = param_bin.ParamFile(bnd.get(night_name))
        no = npf.offset_of(101000)
        if no is None:
            raise WriteError("ChrActivateConditionParam 里没有夜间条件行 101000")
        nb = bytearray(npf.data)
        old_times = bytes(nb[no + 2:no + 6])
        nb[no + 2:no + 6] = b"\x00\x00\x00\x00"
        bnd.set(night_name, bytes(nb))
        night_meta = {"param": night_name, "row": 101000, "old": list(old_times)}
    npc_name = find_param_name([n for n, _ in bnd.files], "NpcParam.param")
    think_name = find_param_name([n for n, _ in bnd.files], "NpcThinkParam.param")
    fbn, fbt = FieldBook("NpcParam"), FieldBook("NpcThinkParam")

    # 参考实现 EldenMiscSetup 的 "rainbow"：给 MaterialExParam 追加纯色行，
    # 克隆行再把第一个空着的 residentMaterialExParamId 指过去（change color, not model）。
    mat_name, mat_pf, mat_extra, rainbow_ids = None, None, [], []
    if features.get("rainbow"):
        mat_name = find_param_name([n for n, _ in bnd.files], "MaterialExParam.param")
        mat_pf = param_bin.ParamFile(bnd.get(mat_name))
        mat_fb = FieldBook("MaterialEx")
        try:
            base_mat = mat_pf.payload(RAINBOW_BASE_ROW)
        except Exception:
            raise WriteError("开了敌人颜色，但基线里没有 MaterialExParam 行 %d" % RAINBOW_BASE_ROW)
        used_mat = set(mat_pf.ids)
        for i, rgb in enumerate(RAINBOW_COLORS):
            rid = RAINBOW_ID_BASE + i
            while rid in used_mat:
                rid += 1
            p = bytearray(base_mat)
            for k, val in ((0, rgb[0] / 255.0), (1, rgb[1] / 255.0),
                           (2, rgb[2] / 255.0), (4, 1.0)):
                _put(p, mat_fb.off("materialParamValue%d" % k), val, "f32")
            mat_extra.append((rid, bytes(p), "%s%d" % (RAINBOW_NAME, i)))
            rainbow_ids.append(rid)
            used_mat.add(rid)
        log("[写盘] 敌人颜色：追加 %d 行 MaterialExParam（%d…%d）"
            % (len(rainbow_ids), rainbow_ids[0], rainbow_ids[-1]))

    # ① 清掉上一轮自己加的克隆行（幂等）
    npc_pf = param_bin.ParamFile(bnd.get(npc_name))
    names = row_names(npc_pf)
    old_clones = sorted(rid for rid, nm in names.items() if nm.startswith(CLONE_NAME))
    if old_clones:
        log("[写盘] 上一轮的克隆行 %d 条 → 先删掉" % len(old_clones))
        npc_pf = param_bin.ParamFile(npc_pf.rebuild(drop=old_clones))
    think_pf = param_bin.ParamFile(bnd.get(think_name))
    tnames = row_names(think_pf)
    old_tclones = sorted(rid for rid, nm in tnames.items() if nm.startswith(CLONE_NAME))
    if old_tclones:
        think_pf = param_bin.ParamFile(think_pf.rebuild(drop=old_tclones))

    # ①.5 多阶段 Boss 血量：按参考实现的 5 组硬编码关系改原始 p1/p2 行。
    # 必须在 collect_clones 之前改：这些行如果同时是别人的捐赠行，克隆时要拿到修正后的值。
    phase_fix = {"enabled": False, "source": "SoulsRandomizers/EldenEnemyEditor.cs:961-1018",
                 "clamp": list(PHASE_PAIR_CLAMP), "clamp_reference": [500, 5000], "rows": [], "changed": False, "applied": 0}
    if features.get("phase_pair_fix", True):
        npc_pf, phase_fix = apply_phase_pair_fixes(npc_pf, fbn, True, log=log)
    else:
        log("[写盘] 多阶段血量：设置里关了（phase_pair_fix=false），跳过")

    # ①.7 Boss 数值平衡（方案 A）：血量 = 位置分位 LUT + 0.85–1.25 硬夹，
    # 伤害 = 位置档缩放（不写派生倍率）。GUI 随机出来的计划通常没有 balance 字段，
    # 这里在内存里补算一次（参考表也从这份 baseline regulation 现场生成），
    # 保证「点随机」和「手动跑 enemy_balance.py」产出同一个口径。
    # 计划里已带 balance（离线跑过）→ 直接用；features.balance=false → 跳过。
    balance_in_memory = False
    _meta0 = plan.get("meta") or {}
    if _meta0.get("balance"):
        log("[写盘] 数值平衡：计划里已带 balance（dmg_model=%s）"
            % str((_meta0.get("balance") or {}).get("dmg_model")))
    elif features.get("balance", True) is False:
        log("[写盘] 数值平衡：设置里关了（features.balance=false），跳过")
    else:
        try:
            import balance_ref as _BR
            import enemy_balance as _EB
            _t0 = time.time()
            _ref = _BR.build_from(bnd, places=PLACES_TABLE, log=None)
            _hp_off = fbn.off("hp")
            _hp_typ = fbn.typ("hp")
            _fmt = {"s8": "<b", "u8": "<B", "s16": "<h", "u16": "<H",
                    "s32": "<i", "u32": "<I", "f32": "<f"}.get(_hp_typ)
            if not _fmt:
                raise WriteError("NpcParam.hp 的类型不认识：%s" % _hp_typ)
            _npc = {}
            for _rid in npc_pf.ids:
                try:
                    _npc[int(_rid)] = {"hp": int(round(
                        struct.unpack_from(_fmt, npc_pf.payload(_rid), _hp_off)[0]))}
                except Exception:
                    pass
            _br = (((_meta0.get("options") or {}).get("balance")) or {})
            _summ = _EB.apply_to_plan(
                plan, ref=_ref, npc=_npc, seed=None,
                k=int(_br.get("k") or _EB.DEFAULT_K),
                jitter=int(_br.get("jitter") or 0),
                alpha=float(_br.get("alpha") or _EB.DEFAULT_ALPHA),
                hp_ratio=tuple(_br.get("hp_ratio") or _EB.DEFAULT_HP_RATIO),
                dmg_model=str(_br.get("dmg_model") or _EB.DEFAULT_DMG_MODEL),
                log=log)
            if _summ:
                balance_in_memory = True
                log("[写盘] 数值平衡：内存里补算 %.1fs（随机口径见 meta.balance）"
                    % (time.time() - _t0))
        except Exception as _e:
            log("[写盘] 数值平衡跳过（不影响出层）：%s" % _e)

    # ①.8 区域缩放：换入者整行 + source→target 区域的 SpEffect。
    # 参考实现是在 EMEVD 里挂；这里每个位置本来就有独立克隆行，直接写进空着的
    # spEffectIDN 槽即可（spEffectID3 本身也走这个机制，实测每行至少 3 个空槽）。
    sp_name = find_param_name([n for n, _ in bnd.files], "SpEffectParam.param")
    sp_pf = param_bin.ParamFile(bnd.get(sp_name))
    # 幂等：上一轮自己追加的区域行（22,000,000 ≤ id < 23,000,000）先删掉，否则每次重建都堆一批。
    # 注意不能写成 id >= BASE：表里还有 999,999,999 这样的哨兵行，误删会直接让游戏起不来。
    old_area = sorted(r for r in sp_pf.ids if AREA_EFFECT_ID_BASE <= int(r) < AREA_EFFECT_ID_LIMIT)
    if old_area:
        log("[写盘] 上一轮的区域缩放行 %d 条 → 先删掉" % len(old_area))
        sp_pf = param_bin.ParamFile(sp_pf.rebuild(drop=old_area))
    sp_fb = FieldBook("SpEffectParam")
    area_map_modes = load_area_map_modes(PLACES_TABLE, npc_pf, fbn)
    area_extra = []
    area_cache = {}
    area_used = set(sp_pf.ids)
    area_stats = {"direct": 0, "map": 0, "none": 0, "effect_units": 0,
                  "effects": 0, "boss_as_basic": 0, "skipped_slot": 0,
                  "balance_units": 0}
    # 伤害口径两种（见 plan.meta.balance.dmg_model）：
    #  position（默认，方案 A）：不动 damage 组，保持 dst/src ⇒ 有效伤害 = 换入者 raw 招式
    #    × 位置档攻击率，与「原版该位置」的区域缩放一致（比值恒 1.00，可离线逐位置核对）。
    #  derived：balance.dmg_mult ≠ 1 时把 damage 组写成该倍率 ⇒ 有效伤害 = 捐赠者原位有效
    #    伤害 × dmg_mult（按换入者自己的原强度对齐，不是按位置）。
    # 两种口径都保留捐赠者自己的 spEffectID3（绝对数值的锚）。
    _DMG_FIELDS = tuple(f for _g, fs in AREA_FIELDS if _g == "damage" for f in fs)

    def area_effect_for(src_r, dst_r, boss_as_basic, dmg_mult=1.0):
        if not dst_r:
            return 0
        if src_r == dst_r and not boss_as_basic and dmg_mult == 1.0:
            return 0
        key = (src_r, dst_r, bool(boss_as_basic),
               float(dmg_mult) if dmg_mult != 1.0 else 1.0)
        if key in area_cache:
            return area_cache[key]
        src_vals = _area_values(sp_pf, sp_fb, src_r)
        dst_vals = _area_values(sp_pf, sp_fb, dst_r)
        factors = _area_factors(src_vals, dst_vals, boss_as_basic)
        if dmg_mult != 1.0:
            for _name in _DMG_FIELDS:
                factors[_name] = float(dmg_mult)
        rid = AREA_EFFECT_ID_BASE
        while rid in area_used:
            rid += 1
        if rid >= AREA_EFFECT_ID_LIMIT:
            raise WriteError("SpEffectParam 行 id 用尽")
        area_used.add(rid)
        payload = _make_area_effect(sp_pf.payload(AREA_BASE_ROW), sp_fb, factors)
        area_extra.append((rid, payload, "gfScale:%d>%d%s%s" % (
            src_r, dst_r, ":b2m" if boss_as_basic else "",
            (":dmg%.3f" % dmg_mult) if dmg_mult != 1.0 else "")))
        area_cache[key] = rid
        return rid

    # ② 分配克隆行（先把"位置原本的 threatLv"挂到单元上：血条/BGM 靠它）
    bgm_follow = bool(features.get("bgm_follow"))
    for u in units:
        u["old_threat"] = _npc_threat(npc_pf, fbn, u.get("old_npc_id"))
        u["old_scale"] = _npc_scale(npc_pf, fbn, u.get("old_npc_id"))
        # 参考实现的 bossbgm：BGM 跟换入的 Boss 走（threatLv 就是 BGM 选择键）。
        # 默认关 = 保留位置原 BGM（安全；大血条已由条件组 15 解耦）。
        u["target_threat"] = u["old_threat"]
        if bgm_follow and u.get("new_npc_id"):
            u["target_threat"] = _npc_threat(npc_pf, fbn, u["new_npc_id"]) or u["old_threat"]

        target_map = (u.get("places") or [{}])[0].get("map") or ""
        src_map = u.get("donor_map") or target_map
        # 源档只看换入者自己的 spEffectID3（0/行不存在 = 1.0），不拿地图兜底；
        # 特殊档（7131..7151 等）按它的真实行取值，不能当 1.0（见 _area_tier_ok）。
        src_r, src_kind = _area_section(u.get("new_npc_id"), src_map, npc_pf, fbn,
                                        area_map_modes, sp_pf, sp_fb, allow_map=False)
        dst_r, dst_kind = _area_section(u.get("old_npc_id"), target_map, npc_pf, fbn,
                                        area_map_modes, sp_pf, sp_fb, allow_map=True)
        area_stats[src_kind] = area_stats.get(src_kind, 0) + 1
        area_stats[dst_kind] = area_stats.get(dst_kind, 0) + 1
        rel = _rel_of(u)
        boss_as_basic = rel == "b2m"
        # 平衡模型只给 Boss→Boss 单元算伤害倍率；其它单元 / 没跑平衡的计划一律 1.0
        # = 保持原来的 dst/src 口径（Boss→杂兵的降级倍率另由 b2m 那条走）。
        dmg_mult = float((u.get("balance") or {}).get("dmg_mult") or 1.0)
        if boss_as_basic:
            dmg_mult = 1.0
        eff = area_effect_for(src_r, dst_r, boss_as_basic, dmg_mult)
        u["area_effect"] = eff
        u["area_dmg_mult"] = dmg_mult
        u["area_src"], u["area_dst"] = src_r, dst_r
        u["area_src_kind"], u["area_dst_kind"] = src_kind, dst_kind
        u["area_rule"] = ("boss" if boss_as_basic else ("basic" if rel == "m2b" else "same"))
        if eff:
            area_stats["effect_units"] += 1
            if boss_as_basic:
                area_stats["boss_as_basic"] += 1
            if u.get("balance") and not boss_as_basic:
                area_stats["balance_units"] += 1
    area_stats["effects"] = len(area_extra)
    n_old = sum(1 for u in units if int(u.get("old_threat") or 0) > 0)
    log("[写盘] 位置原威胁等级：%d/%d 个单元有值（克隆行沿用，修野外 Boss 血条）"
        % (n_old, len(units)))
    replaced = [u for u in units if u.get("new_npc_id") is not None]
    log("[写盘] 区域缩放：%d/%d 个替换单元挂 area SpEffect（%d 条自定义行；"
        "档位直取 %d 侧 / 地图兜底 %d 侧（target）/ 无档 %d 侧；Boss→杂兵 %d；"
        "平衡单元 %d）"
        % (area_stats["effect_units"], len(units), area_stats["effects"],
           area_stats["direct"], area_stats["map"], area_stats["none"],
           area_stats["boss_as_basic"], area_stats["balance_units"]))
    alloc = collect_clones(units, npc_pf, fbn)
    place_clones = {}
    for u in units:
        _nid = alloc.get(_clone_key(u))
        if _nid is None:
            continue
        for pl in u["places"]:
            place_clones["%s|%s|%d" % (pl["map"], pl["part_name"], int(pl["occurrence"]))] = _nid
    think_alloc = {}
    for u in units:
        tk = _think_clone_key(u)
        if tk is None or tk in think_alloc:
            continue
        nid = tk[0]
        used = set(think_pf.ids) | set(think_alloc.values())
        while nid in used:
            nid += 1
        think_alloc[tk] = nid
    log("[写盘] 身份所有权：%d 个位置、无冲突" % n_places)
    log("[写盘] 克隆行：NpcParam %d 条 / NpcThinkParam %d 条" % (len(alloc), len(think_alloc)))

    donor_effects = load_donor_effects()
    if donor_effects:
        missing = sorted(set(donor_effects.values()) - set(sp_pf.ids))
        if missing:
            raise WriteError("来源加护不在 SpEffectParam 里：%s（检查 %s）"
                             % ("、".join(str(x) for x in missing), DONOR_EFFECTS))
    npc_extra, npc_notes = [], {}
    donor_effect_units = 0
    n_with_src = 0
    for key in sorted(alloc):
        nid = alloc[key]
        src = None
        if key[5]:
            try:
                src = npc_pf.payload(key[5])
            except Exception:
                src = None
        if src is not None and len(src) >= fbn.size:
            n_with_src += 1
        payload, notes = make_npc_clone(npc_pf.payload(key[0]), key, fbn, src,
                                        rainbow_ids=rainbow_ids,
                                        donor_effects=donor_effects)
        nm = "%s%d:%d:%d:%s:t%d:p%d:e%d:a%d" % (
            CLONE_NAME, key[0], key[1], key[2], key[3], key[4], key[5], key[6], key[7])
        npc_extra.append((nid, payload, nm))
        npc_notes[nid] = notes
        if "donor_effect" in notes:
            donor_effect_units += 1
    think_extra = []
    for (base_t, goal), nid in sorted(think_alloc.items()):
        payload, notes = make_think_clone(think_pf.payload(base_t), fbt, goal or None)
        think_extra.append((nid, payload, "%s%d:think:g%d" % (CLONE_NAME, base_t, goal)))
        npc_notes[("think", nid)] = notes
    log("[写盘] 位置数值对齐：%d/%d 条克隆行抄了原位置的掉落（%d 个单元没有原行）"
        % (n_with_src, len(alloc), sum(1 for k in alloc if not k[5])))
    if donor_effect_units:
        log("[写盘] 来源专属加护：%d 条克隆行挂了模型自带的 SpEffect（%s）"
            % (donor_effect_units, "、".join(sorted(donor_effects))))

    # ③ 按图分组
    by_map = {}
    for u in units:
        for pl in u["places"]:
            by_map.setdefault(pl["map"], []).append(u)
    maps = sorted(by_map)
    if limit:
        maps = maps[:limit]
        keep = set(maps)
        units = [u for u in units if any(p["map"] in keep for p in u["places"])]
        by_map = {k: v for k, v in by_map.items() if k in keep}
    # 统计按真正要写的图算（--limit 冒烟时不要拿全量数字骗人）
    ons_units = sum(1 for u in units if int(u.get("dup_count") or 0) > 0)
    ons_dups = sum(min(int(u.get("dup_count") or 0), ONSLAUGHT_MAX_DUP) for u in units)
    if ons_units:
        log("[写盘] 敌人倍增（实验）：%d 个普通敌人位 → 复制 %d 个 part"
            % (ons_units, ons_dups))
    total_bytes = 0
    for m in maps:
        p = os.path.join(mod, MAP_REL, m + ".msb.dcx")
        if not os.path.isfile(p):
            raise WriteError("基线里没有这张图：%s" % p)
        total_bytes += os.path.getsize(p)
    log("[写盘] 地图：%d 张 / %.2f GB（要整文件覆盖）" % (len(maps), total_bytes / 1073741824.0))
    if dry_run:
        return {"dry_run": True, "label": label, "maps": len(maps),
                "units": len(units), "places": sum(len(u["places"]) for u in units),
                "clone_rows": len(alloc), "think_rows": len(think_alloc),
                "map_bytes": total_bytes, "npc_extra": len(npc_extra)}

    # ④ 写地图到临时目录
    t0 = time.time()
    os.makedirs(os.path.join(stage_data, MAP_REL), exist_ok=True)
    files = []
    msb_stats = {}
    for n, mname in enumerate(maps, 1):
        src = os.path.join(mod, MAP_REL, mname + ".msb.dcx")
        data = open(src, "rb").read()
        raw, hdr = msb_read.dcx_payload(data)
        out_raw, stat = patch_map(raw, by_map[mname], alloc, think_alloc, map_name=mname)
        kind = (hdr or {}).get("kind")
        dcx, rep = msb_write.dcx_repack(out_raw, in_kind=kind, out_kind="same",
                                        orig_prefix=data[:76] if hdr else None)
        v = verify_map(raw, msb_read.dcx_payload(dcx)[0], stat)
        rel = os.path.join(MAP_REL, mname + ".msb.dcx")
        dst = os.path.join(stage_data, rel)
        with open(dst, "wb") as f:
            f.write(dcx)
        files.append({"rel": rel.replace("\\", "/"), "bytes": len(dcx),
                      "sha256": sha256_bytes(dcx)})
        msb_stats[mname] = dict(v, degraded=rep.get("degraded"), kind=kind,
                                out_kind=rep.get("out_kind"),
                                dups=stat.get("dups") or [])
        if log and (n % 25 == 0 or n == len(maps)):
            log("    地图 %d/%d（%.1fs）" % (n, len(maps), time.time() - t0))
    msb_bytes = sum(x["bytes"] for x in files)
    log("[写盘] 地图写完：%d 张 / %.2f GB（%.1fs）" % (len(files), msb_bytes / 1073741824.0,
                                                 time.time() - t0))

    # ④b common_func：删掉野外 Boss 血条模板里的 BGM 判定（M2.2）
    # 模板 90005870/871 用 FieldBattleBGMActive(threatLv) 卡住大血条；换人后 BGM 等级
    # 对不上就永远不显示。删掉这条条件（参考实现 events.txt 的 Removes 第一条同款）。
    EVD_REL = "event/common_func.emevd.dcx"
    evd_src = os.path.join(mod, EVD_REL)
    evd_meta = None
    if os.path.isfile(evd_src):
        evd_dst = os.path.join(stage_data, EVD_REL)
        evd_meta = evd_edit.patch_file(evd_src, evd_dst, log=log)
        evd_ok, evd_msgs = evd_edit.verify_patch(evd_src, evd_dst)
        if not evd_ok:
            raise WriteError("common_func 复验失败：%s" % "; ".join(evd_msgs))
        with open(evd_dst, "rb") as f:
            evd_bytes = f.read()
        files.append({"rel": EVD_REL, "bytes": len(evd_bytes),
                      "sha256": sha256_bytes(evd_bytes)})
        log("[写盘] common_func：%s" % "；".join(evd_msgs))
    else:
        log("[写盘] 基线里没有 %s，跳过血条模板处理" % EVD_REL)

    # ④c 血条名：有血条的位置，把 EMEVD 里的 Name ID 换成换入者的名字（M2.3 / v1.2）
    # 参考实现把「改Boss名」做成开关；这里同样允许关掉（保留原名）。
    # 大血条名字属于位置事件，不属于模型 —— 换人不改它的话，血条会顶着一只别的 Boss
    # 的名字（实测：大树守卫位换成"风暴呼召者塔兰"，血条仍写"大树守卫"）。
    bar_map, bar_sources = {}, {}
    bar_stats = {"targets": 0, "patched": 0, "maps": 0, "placeholder": 0,
                 "placeholder_targets": 0, "no_slot": 0, "vanilla": 0}
    if features.get("bar_names", True) and os.path.isfile(BAR_TABLE):
        old_names, model_names = bar_names.load_tables(BAR_TABLE)
        name_overrides = bar_names.load_name_overrides()
        # 补上「mod 没覆盖 event」的本体名字 id（封印监牢等），只给写盘用。
        fallback_names = load_bar_fallback(BAR_FALLBACK)
        for k, ids in fallback_names.items():
            old_names.setdefault(k, [])
            for nid in ids:
                if nid not in old_names[k]:
                    old_names[k].append(nid)
        for mname in maps:
            tgts, placeholders = bar_names.targets_for_map(
                units, old_names, model_names, mname, name_overrides)
            if not tgts:
                continue
            esrc = os.path.join(mod, "event", mname + ".emevd.dcx")
            src_kind = "mod"
            if not os.path.isfile(esrc):
                # 这张图 mod 没有 event 覆盖：用本体原始事件（只改血条名，整文件写进层里）
                esrc = os.path.join(VANILLA_EVENT_DIR, mname + ".emevd.dcx")
                src_kind = "vanilla"
            if not os.path.isfile(esrc):
                continue
            edst = os.path.join(stage_data, "event", mname + ".emevd.dcx")
            info = bar_names.patch_file(esrc, edst, tgts, log=lambda *_a: None)
            okb, msgs = bar_names.verify_file(esrc, edst, tgts)
            if not okb:
                raise WriteError("血条名复验失败（%s）：%s" % (mname, "; ".join(msgs)))
            with open(edst, "rb") as fh:
                eb = fh.read()
            files.append({"rel": "event/%s.emevd.dcx" % mname, "bytes": len(eb),
                          "sha256": sha256_bytes(eb)})
            bar_map[mname] = {str(k): [v[0], v[1]] for k, v in tgts.items()}
            bar_sources[mname] = src_kind
            if src_kind == "vanilla":
                bar_stats["vanilla"] += 1
            hits = set(info["hits"])
            bar_stats["targets"] += len(hits)
            bar_stats["patched"] += info["changed"]
            bar_stats["no_slot"] += len(tgts) - len(hits)
            bar_stats["placeholder_targets"] += placeholders
            bar_stats["placeholder"] += sum(
                1 for e in hits if tgts.get(e, (None, None))[1] == bar_names.PLACEHOLDER_NAME_ID)
            bar_stats["maps"] += 1
        log("[写盘] 血条名：%d 张图 / %d 个位置实际改名（共 %d 处指令）"
            "；%d 个目标没有独立名字槽（旧名字与同图另一实体共用）"
            "；%d 个无名字目标，其中 %d 个真正写进 ?NpcName? 占位"
            % (bar_stats["maps"], bar_stats["targets"], bar_stats["patched"],
               bar_stats["no_slot"], bar_stats["placeholder_targets"],
               bar_stats["placeholder"]))
    elif not features.get("bar_names", True):
        log("[写盘] 血条名：按设置保留原名")
    else:
        log("[写盘] 没有 %s，跳过血条名处理" % BAR_TABLE)

    # ⑤ regulation
    npc_new = npc_pf.rebuild(extra=npc_extra)
    think_new = think_pf.rebuild(extra=think_extra) if think_extra else think_pf.data
    sp_new = sp_pf.rebuild(extra=area_extra) if area_extra else sp_pf.data
    npc_pf2, think_pf2 = param_bin.ParamFile(npc_new), param_bin.ParamFile(think_new)
    bnd2 = erio.Bnd4(list(bnd.files))
    bnd2.dcx_template = getattr(bnd, "dcx_template", None)
    # BND4 重建要沿用原文件的头部/名字区/条目非几何字段 —— 只传 files 会丢 MAGIC 与名字区
    for attr in ("header", "raw_names", "raw_entries", "name_start", "data_start"):
        if hasattr(bnd, attr):
            setattr(bnd2, attr, getattr(bnd, attr))
    mat_new = None
    if mat_pf is not None and mat_extra:
        mat_new = mat_pf.rebuild(extra=mat_extra)
        bnd2.set(mat_name, mat_new)
    bnd2.set(sp_name, sp_new)
    bnd2.set(npc_name, npc_new)
    bnd2.set(think_name, think_new)
    reg_out = os.path.join(stage_data, "regulation.bin")
    erio.write_regulation(reg_out, bnd2, encrypt=True)
    log("[写盘] regulation：%d → %d 行（+%d），%.1f MB" % (
        len(npc_pf.ids), len(npc_pf2.ids), len(npc_extra),
        os.path.getsize(reg_out) / 1048576.0))

    # ⑥ regulation 读回校验
    chk = erio.read_regulation(reg_out)
    for n, d in bnd.files:
        if n in (npc_name, think_name, mat_name, sp_name):
            continue
        if chk.get(n) != d:
            raise WriteError("读回校验：regulation 里 %s 被动了" % n)
    cp = param_bin.ParamFile(chk.get(npc_name))
    if len(cp.ids) != len(npc_pf.ids) + len(npc_extra):
        raise WriteError("读回校验：NpcParam 行数不对")
    for rid in npc_pf.ids:
        if cp.payload(rid) != npc_pf.payload(rid):
            raise WriteError("读回校验：旧行 %s 变了" % rid)
    for rid, payload, _nm in npc_extra:
        if cp.payload(rid) != payload:
            raise WriteError("读回校验：新行 %s 内容不对" % rid)
    ct = param_bin.ParamFile(chk.get(think_name))
    for rid, payload, _nm in think_extra:
        if ct.payload(rid) != payload:
            raise WriteError("读回校验：think 新行 %s 内容不对" % rid)
    if mat_new is not None:
        cm = param_bin.ParamFile(chk.get(mat_name))
        if len(cm.ids) != len(mat_pf.ids) + len(mat_extra):
            raise WriteError("读回校验：MaterialExParam 行数不对")
        for rid, payload, _nm in mat_extra:
            if cm.payload(rid) != payload:
                raise WriteError("读回校验：颜色新行 %s 内容不对" % rid)
    if area_extra:
        cs = param_bin.ParamFile(chk.get(sp_name))
        if len(cs.ids) != len(sp_pf.ids) + len(area_extra):
            raise WriteError("读回校验：SpEffectParam 行数不对")
        for rid, payload, _nm in area_extra:
            if cs.payload(rid) != payload:
                raise WriteError("读回校验：区域缩放行 %s 内容不对" % rid)
    files.insert(0, {"rel": "regulation.bin", "bytes": os.path.getsize(reg_out),
                     "sha256": sha256_file(reg_out)})

    # 计划快照：默认计划 investigation/enemy_plan.json 会被下次重建覆盖，而这一层的
    # 复验需要"写盘时那一份"。所以每次构建把计划复制到 investigation/plans/<label>.json，
    # manifest 指向快照（复核时不会再拿错计划 —— 2026-10-21 踩过一次，71,712 项假报错）。
    plans_dir = plans_dir or PLANS_DIR
    os.makedirs(plans_dir, exist_ok=True)
    plan_snap = os.path.join(plans_dir, label.replace(os.sep, "_") + ".json")
    if balance_in_memory:
        # 计划是在内存里补的 balance → 快照必须写「实际用来建层的那一份」，
        # 否则复验会拿回原计划，target_hp 对不上（2026-10-21 踩过同类坑）。
        with open(plan_snap, "w", encoding="utf-8", newline="\n") as _f:
            json.dump(plan, _f, ensure_ascii=False, separators=(",", ":"))
    elif os.path.abspath(plan_path) != os.path.abspath(plan_snap):
        shutil.copy2(plan_path, plan_snap)
    manifest = {
        "version": WRITE_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "data_sub": DATA_SUB,
        "plan": {"path": os.path.abspath(plan_snap), "sha256": sha256_file(plan_snap),
                 "seed": plan.get("meta", {}).get("seed"),
                 "base_seed": plan.get("meta", {}).get("base_seed"),
                 "source": os.path.abspath(plan_path)},
        "base": {"regulation": os.path.abspath(base_reg), "regulation_sha256": reg_sha,
                 "maps_dir": os.path.join(mod, MAP_REL),
                 "mod": os.path.abspath(mod),
                 "bar_table": os.path.abspath(BAR_TABLE) if os.path.isfile(BAR_TABLE) else None,
                 "event": os.path.abspath(evd_src) if os.path.isfile(evd_src) else None},
        "features": {"bar_names": bool(features.get("bar_names", True)),
                      "nightday": bool(features.get("nightday")),
                      "rainbow": bool(features.get("rainbow")),
                      "bgm_follow": bgm_follow,
                      "onslaught": float(features.get("onslaught") or 1.0),
                      "phase_pair_fix": bool(features.get("phase_pair_fix", True)),
                      "balance": bool(balance_in_memory or _meta0.get("balance")),
                      "area_scaling": True},
        "nightday": night_meta,
        "counts": {"units": len(units), "places": sum(len(u["places"]) for u in units),
                   "maps": len(maps), "npc_clone_rows": len(npc_extra),
                   "think_clone_rows": len(think_extra),
                   "npc_rows_before": len(npc_pf.ids), "npc_rows_after": len(npc_pf2.ids),
                   "material_rows": len(mat_extra),
                   "sp_effect_rows": len(area_extra),
                   "sp_effect_rows_after": len(sp_pf.ids) + len(area_extra),
                   "area_effect_units": area_stats["effect_units"],
                   "area_boss_as_basic": area_stats["boss_as_basic"],
                   "area_balance_units": area_stats["balance_units"],
                   "onslaught_units": ons_units, "onslaught_dups": ons_dups,
                   "npc_clone_with_src": n_with_src,
                   "donor_effect_units": donor_effect_units,
                   "bar_name_maps": bar_stats["maps"],
                   "bar_name_targets": bar_stats["targets"],
                   "bar_name_patched": bar_stats["patched"],
                   "bar_name_no_donor_name": 0,
                   "bar_name_no_slot": bar_stats["no_slot"],
                   "bar_name_placeholder": bar_stats["placeholder"],
                   "bar_name_placeholder_targets": bar_stats["placeholder_targets"],
                   "phase_pair_fix_rows": phase_fix["applied"]},
         "phase_pair_fix": phase_fix,
        "area_scaling": {
            "base_row": AREA_BASE_ROW,
            "stats": area_stats,
            "effects": [{"id": rid, "payload_sha1": hashlib.sha1(payload).hexdigest(),
                         "src": int(name.split(":")[1].split(">")[0]),
                         "dst": int(name.split(":")[1].split(">")[1].split(":")[0]),
                         "boss_as_basic": name.endswith(":b2m")}
                        for rid, payload, name in area_extra],
        },
        "stat_copy_fields": [],
        "balance": (plan.get("meta") or {}).get("balance"),
        "lot_copy_fields": list(LOT_COPY_FIELDS),
        "npc_clone_notes": {str(k): v for k, v in npc_notes.items()},
        "clone_ids": {"%d|%d|%d|%s|%d|%d|%d|%d" % k: v for k, v in alloc.items()},
        "place_clones": place_clones,
        "think_clone_ids": {"%d|%d" % k: v for k, v in think_alloc.items()},
        "maps": msb_stats,
        "evd": evd_meta,
        "rainbow": ({"param": mat_name, "ids": rainbow_ids,
                     "colors": [list(c) for c in RAINBOW_COLORS]} if mat_extra else None),
        "bar_names": bar_map,
        "bar_sources": bar_sources,
        "files": files,
        "bytes": sum(x["bytes"] for x in files),
    }
    mpath = os.path.join(stage, MANIFEST_NAME)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # ⑦ 原子换上
    dest = os.path.join(out_root, label)
    old = None
    if os.path.isdir(dest):
        old = dest + ".old_" + time.strftime("%Y%m%d_%H%M%S")
        os.rename(dest, old)
    os.rename(stage, dest)
    if old:
        shutil.rmtree(old, ignore_errors=True)
    log("[写盘] 已换上新方案层：%s（%.2f GB）" % (dest, manifest["bytes"] / 1073741824.0))
    return manifest



# ────────────────────────── 读回校验 / 自检 ──────────────────────────

def verify_layer(layer_dir, plan_path=None, log=print):
    """独立复验一个已写好的方案层（不依赖构建时的内存状态）。"""
    man = json.load(open(os.path.join(layer_dir, MANIFEST_NAME), encoding="utf-8"))
    pth = plan_path or (man.get("plan") or {}).get("path")
    if not pth or not os.path.isfile(pth):
        raise WriteError("这一层的 manifest 没记计划路径或计划已不在：%s" % pth)
    want = (man.get("plan") or {}).get("sha256")
    got = sha256_file(pth)
    if want and got != want:
        raise WriteError(
            "这一层写盘时用的计划已被替换（sha256 %s… ≠ %s…）。\n"
            "  manifest 指向的是写盘时的计划快照；快照被覆盖说明有人用同一个 label 重建过。\n"
            "  要复验旧层，请用 --plan 指定当时那份计划（investigation/plans/ 下有快照）。"
            % (got[:12], want[:12]))
    plan = json.load(open(pth, encoding="utf-8"))
    data_dir = os.path.join(layer_dir, man.get("data_sub") or "")
    bad = []
    # 基线 regulation：复验克隆行的 threatLv 时要查"位置原本那只"的威胁等级
    pf_b = fbn_b = None
    try:
        bnd_b = erio.read_regulation(man["base"]["regulation"])
        npn_b = find_param_name([n for n, _ in bnd_b.files], "NpcParam.param")
        pf_b, fbn_b = param_bin.ParamFile(bnd_b.get(npn_b)), FieldBook("NpcParam")
    except Exception as _exc:                      # 基线没了：只报 threatLv 检查跳过
        log("    [基线] 读不到 %s，跳过 threatLv 复验" % man["base"]["regulation"])

    def _base_threat(npc_id):
        return 0 if pf_b is None else _npc_threat(pf_b, fbn_b, npc_id)

    def _base_scale(npc_id):
        return 0 if pf_b is None else _npc_scale(pf_b, fbn_b, npc_id)
    for f in man["files"]:
        p = os.path.join(data_dir, f["rel"].replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append("缺文件 %s" % f["rel"])
        elif sha256_file(p) != f["sha256"]:
            bad.append("指纹不符 %s" % f["rel"])
    if bad:
        raise WriteError("复验失败：%s" % "; ".join(bad[:5]))

    # 基线漂移：这一层是拿哪份基线写的，基线现在还是不是那副样子
    drift = []
    bmaps = man.get("base", {}).get("maps_dir")
    for n, info in man.get("maps", {}).items():
        want_h = info.get("base_sha256")
        if not want_h or not bmaps:
            continue
        bp = os.path.join(bmaps, n + ".msb.dcx")
        if os.path.isfile(bp) and sha256_file(bp) != want_h:
            drift.append(n)
    breg = man.get("base", {}).get("regulation")
    if breg and os.path.isfile(breg) and man["base"].get("regulation_sha256"):
        if sha256_file(breg) != man["base"]["regulation_sha256"]:
            drift.append("<regulation.bin>")
    if drift:
        log("    [基线漂移] %d 个文件与写盘时不同：%s"
            % (len(drift), ", ".join(drift[:5])))
    else:
        log("    [基线] 与写盘时一致")

    # 克隆行映射（按前 7 段；第 8 段是区域 effect，写盘时才知道）
    clone7 = {}
    for _k, _rid in man.get("clone_ids", {}).items():
        _p = _k.split("|")
        clone7.setdefault("|".join(_p[:7]), _rid)

    # 每张图：目标 part 的身份字段必须等于计划值；其它 part 必须与"基线图"一致
    maps = man["maps"]
    want = {}
    for u in plan["units"]:
        if u.get("new_npc_id") is None:
            continue
        for pl in u["places"]:
            if pl["map"] in maps:
                want[(pl["map"], pl["part_name"], int(pl["occurrence"]))] = u
    for mname in maps:
        p = os.path.join(data_dir, MAP_REL, mname + ".msb.dcx")
        raw, _h = msb_read.dcx_payload(open(p, "rb").read())
        m = msb_edit.Msb(raw)
        idx = part_index(m)
        parts = dict(m.parts())
        for (mm, pn, occ), u in want.items():
            if mm != mname:
                continue
            i = idx.get((pn, occ))
            if i is None:
                bad.append("%s 缺 part %s#%s" % (mname, pn, occ))
                continue
            rel = _rel_of(u)
            tgt_threat = _base_threat(u.get("old_npc_id"))
            if (man.get("features") or {}).get("bgm_follow") and u.get("new_npc_id"):
                tgt_threat = _base_threat(u.get("new_npc_id")) or tgt_threat
            ckey = "%d|%d|%d|%s|%d|%d|%d" % (int(u["new_npc_id"]), int(u.get("target_hp") or 0),
                                           int(u.get("target_soul") or 0), rel,
                                           tgt_threat,
                                           int(u.get("old_npc_id") or 0),
                                           _base_scale(u.get("old_npc_id")))
            _pk = "%s|%s|%d" % (mname, pn, occ)
            exp_npc = (man.get("place_clones") or {}).get(_pk) or \
                man.get("clone_ids", {}).get(ckey) or clone7.get(ckey)
            exp_think = int(u["new_think_id"])
            tk = _think_clone_key(u)
            if tk is not None:
                exp_think = man.get("think_clone_ids", {}).get("%d|%d" % tk, exp_think)
            got = parts[i]
            if exp_npc is None:
                bad.append("%s %s#%s 找不到克隆行映射" % (mname, pn, occ))
            elif int(got["npc_id"]) != int(exp_npc):
                bad.append("%s %s#%s npc %s ≠ 克隆行 %s"
                           % (mname, pn, occ, got["npc_id"], exp_npc))
            if int(got["think_id"]) != int(exp_think):
                bad.append("%s %s#%s think %s ≠ %s" % (mname, pn, occ, got["think_id"], exp_think))
            if int(got["chara_id"]) != int(u["new_chara_id"]):
                bad.append("%s %s#%s chara %s ≠ %s" % (mname, pn, occ, got["chara_id"], u["new_chara_id"]))
            if got["model"] != u["new_model"]:
                bad.append("%s %s#%s 模型 %s ≠ 计划 %s"
                           % (mname, pn, occ, got["model"], u["new_model"]))
        info = maps[mname]
        if info.get("parts") and len(parts) != int(info["parts"]):
            bad.append("%s 的 part 数 %d ≠ manifest %s" % (mname, len(parts), info["parts"]))
        for d in info.get("dups") or []:
            i = int(d.get("index") or 0)
            if i not in parts:
                bad.append("%s 缺复制体 #%d" % (mname, i))
                continue
            y = parts[i]
            if (int(y.get("entity_id") or 0) != int(d.get("entity") or 0)
                    or int(y.get("npc_id") or 0) != int(d.get("npc") or 0)
                    or int(y.get("think_id") or 0) != int(d.get("think") or 0)
                    or y.get("model") != d.get("model")):
                bad.append("%s 复制体 #%d 的身份不对" % (mname, i))
        log("    复验图 %s：%d 个 part%s" % (
            mname, len(parts),
            "（复制 %d）" % len(info.get("dups") or []) if info.get("dups") else ""))

    # common_func：模板里的 BGM 判定必须已删掉，其余事件逐条一致
    base_evd = (man.get("base") or {}).get("event")
    layer_evd = os.path.join(data_dir, "event", "common_func.emevd.dcx")
    if base_evd and os.path.isfile(layer_evd):
        evd_ok, evd_msgs = evd_edit.verify_patch(base_evd, layer_evd)
        if not evd_ok:
            bad.append("common_func 复验失败：%s" % "; ".join(evd_msgs))
        else:
            log("    复验 common_func：%s" % "；".join(evd_msgs))
    elif base_evd:
        bad.append("方案层缺 event/common_func.emevd.dcx")

    # 血条名：按 manifest 记录的目标，重算期望明文并与层里的文件逐字节比对
    bmap = man.get("bar_names") or {}
    if bmap:
        base_mod = (man.get("base") or {}).get("mod")
        n_bar = 0
        bar_src = man.get("bar_sources") or {}
        for mname, tg in bmap.items():
            srcp = os.path.join(base_mod, "event", mname + ".emevd.dcx") if base_mod else ""
            if (not srcp or not os.path.isfile(srcp)) and bar_src.get(mname) == "vanilla":
                srcp = os.path.join(VANILLA_EVENT_DIR, mname + ".emevd.dcx")
            dstp = os.path.join(data_dir, "event", mname + ".emevd.dcx")
            if not srcp or not os.path.isfile(srcp) or not os.path.isfile(dstp):
                bad.append("血条名：缺 %s 的 event 文件" % mname)
                continue
            tgts = {int(k): (v[0] if isinstance(v[0], list) else [int(v[0])], int(v[1]))
                    for k, v in tg.items()}
            okb, msgs = bar_names.verify_file(srcp, dstp, tgts)
            if not okb:
                bad.append("血条名 %s：%s" % (mname, "; ".join(msgs)))
            n_bar += len(tgts)
        n_real = (man.get("counts") or {}).get("bar_name_targets", n_bar)
        log("    复验血条名：%d 张图 / %d 个位置实际改名（manifest 记录）" % (len(bmap), n_real))

    # v1.4.0：双人 Boss 的第二只 —— 必须与主人换出来的不是同一只，且血条名覆盖到它
    # （第二只是 Helper，事件里的名字槽按实体改；漏了会顶着原 helper 的名字）。
    duo_units = [u for u in plan["units"] if u.get("duo")]
    if duo_units:
        by_key = {u["key"]: u for u in plan["units"]}
        bmap2 = man.get("bar_names") or {}
        for u in duo_units:
            du = u.get("duo") or {}
            own = by_key.get(du.get("owner_key"))
            if own and own.get("new_model") == u.get("new_model"):
                bad.append("双人第二只 %s 与主人换成了同一只（%s）"
                           % (u["key"], u.get("new_model")))
            if (man.get("features") or {}).get("bar_names", True):
                for pl in u.get("places") or []:
                    if str(pl["entity_id"]) not in (bmap2.get(pl["map"]) or {}):
                        bad.append("双人第二只 %s（%s/%s）没有血条名目标"
                                   % (u["key"], pl["map"], pl["entity_id"]))
        log("    复验双人第二只：%d 个实体（与主人不同、血条名已覆盖）"
            % len(duo_units))

    # regulation：克隆行的 hp/魂/关键位
    bnd = erio.read_regulation(os.path.join(data_dir, "regulation.bin"))
    npn = find_param_name([n for n, _ in bnd.files], "NpcParam.param")
    pf = param_bin.ParamFile(bnd.get(npn))
    fbn = FieldBook("NpcParam")
    if len(pf.ids) != man["counts"]["npc_rows_after"]:
        bad.append("NpcParam 行数 %d ≠ manifest %d" % (len(pf.ids), man["counts"]["npc_rows_after"]))
    # 多阶段 Boss 血量：按 manifest 的 before/after 复验原始行（参考实现 5 组）
    pfix = man.get("phase_pair_fix") or {}
    if pfix.get("enabled"):
        hp_off = fbn.off("hp")
        for ent in pfix.get("rows") or []:
            rid = ent.get("npc_id")
            if rid is None or rid not in pf.ids:
                bad.append("多阶段血量：找不到 NpcParam 行 %s" % (rid,))
                continue
            want = ent.get("after") if ent.get("applied") else ent.get("before")
            if want is None:
                continue
            got = _u32(pf.payload(rid), hp_off)
            if got != int(want):
                bad.append("多阶段血量：行 %s（%s/%s）的 hp %d ≠ manifest %d"
                           % (rid, ent.get("group"), ent.get("role"), got, int(want)))
        log("    复验多阶段血量：%d 组 / %d 行记录（%d 行已改）"
            % (len({r.get("group") for r in pfix.get("rows") or []}),
               len(pfix.get("rows") or []),
               sum(1 for r in pfix.get("rows") or [] if r.get("applied"))))
    sp_man = man.get("area_scaling") or {}
    sp_pf_c = None
    if sp_man.get("effects"):
        spn = find_param_name([n for n, _ in bnd.files], "SpEffectParam.param")
        sp_pf_c = param_bin.ParamFile(bnd.get(spn))
        want_n = man["counts"].get("sp_effect_rows_after")
        if want_n is not None and len(sp_pf_c.ids) != int(want_n):
            bad.append("SpEffectParam 行数 %d ≠ manifest %d" % (len(sp_pf_c.ids), int(want_n)))
        for ent in sp_man["effects"]:
            rid = ent.get("id")
            if rid not in sp_pf_c.ids:
                bad.append("区域缩放：找不到 SpEffectParam 行 %s" % (rid,))
                continue
            if hashlib.sha1(sp_pf_c.payload(rid)).hexdigest() != ent.get("payload_sha1"):
                bad.append("区域缩放：行 %s 内容不对" % (rid,))
        log("    复验区域缩放：%d 条 SpEffectParam 行" % len(sp_man["effects"]))
    # 克隆行映射：当前 clone_ids 第 8 段是区域 effect；复验按前 7 段找（老层没有第 8 段）
    clone7 = {}
    for _k, _rid in man.get("clone_ids", {}).items():
        _p = _k.split("|")
        clone7.setdefault("|".join(_p[:7]), _rid)
    for key, rid in man.get("clone_ids", {}).items():
        parts_k = key.split("|")
        donor, hp, soul, rel = parts_k[0], parts_k[1], parts_k[2], parts_k[3]
        old_threat = int(parts_k[4]) if len(parts_k) > 4 else 0
        old_npc = int(parts_k[5]) if len(parts_k) > 5 else 0
        if rid not in pf.ids:
            bad.append("克隆行 %s 不在表里" % rid)
            continue
        b = pf.payload(rid)
        if _u32(b, fbn.off("hp")) != int(hp) or _u32(b, fbn.off("getSoul")) != int(soul):
            bad.append("克隆行 %s 的 hp/魂不对" % rid)
        bo, bi = fbn.bit("isSoulGetByBoss")
        if _get_bit(b, bo, bi) != 0:
            bad.append("克隆行 %s 的 isSoulGetByBoss 没清" % rid)
        if old_threat > 0 and _u32(b, fbn.off("threatLv")) != old_threat:
            bad.append("克隆行 %s 的 threatLv %d ≠ 位置原值 %d"
                       % (rid, _u32(b, fbn.off("threatLv")), old_threat))
        # 区域缩放：克隆行挂的 effect 槽必须等于 manifest 记的（没有就不检查）
        ae = (man.get("npc_clone_notes") or {}).get(str(rid), {}).get("area_effect")
        if ae and sp_pf_c is not None:
            slot, eff = ae[0], int(ae[1])
            if _u32(b, fbn.off(slot)) != eff:
                bad.append("克隆行 %s 的 %s=%s ≠ manifest %s"
                           % (rid, slot, _u32(b, fbn.off(slot)), eff))
            if eff not in sp_pf_c.ids:
                bad.append("克隆行 %s 的区域 effect %s 不在表里" % (rid, eff))
        # 来源模型专属加护：克隆行挂的 effect 槽必须等于 manifest 记的
        de = (man.get("npc_clone_notes") or {}).get(str(rid), {}).get("donor_effect")
        if de:
            slot, eff = de[0], int(de[1])
            if sp_pf_c is None:
                spn2 = find_param_name([n for n, _ in bnd.files], "SpEffectParam.param")
                sp_pf_c = param_bin.ParamFile(bnd.get(spn2))
            if _u32(b, fbn.off(slot)) != eff:
                bad.append("克隆行 %s 的 %s=%s ≠ manifest %s"
                           % (rid, slot, _u32(b, fbn.off(slot)), eff))
            if eff not in sp_pf_c.ids:
                bad.append("克隆行 %s 的来源加护 %s 不在表里" % (rid, eff))
        # 掉落必须逐字节等于**位置原行**（F3：掉落绑地点）
        if old_npc and pf_b is not None:
            try:
                src = pf_b.payload(old_npc)
            except Exception:
                src = None
            if src is None:
                bad.append("克隆行 %s 找不到位置原行 %s" % (rid, old_npc))
            else:
                for name in (man.get("stat_copy_fields") or []):
                    if not _same_bytes(b, src, fbn.off(name), fbn.typ(name)):
                        bad.append("克隆行 %s 的 %s 没抄位置原值" % (rid, name))
                        break
                for name in man.get("lot_copy_fields") or LOT_COPY_FIELDS:
                    if not _same_bytes(b, src, fbn.off(name), fbn.typ(name)):
                        bad.append("克隆行 %s 的 %s 没抄位置原值" % (rid, name))
                        break
    rb = man.get("rainbow")
    if rb and rb.get("ids"):
        mn = rb.get("param")
        cm = param_bin.ParamFile(bnd.get(mn))
        mfb = FieldBook("MaterialEx")
        for i, rid in enumerate(rb["ids"]):
            if rid not in cm.ids:
                bad.append("颜色行 %s 不在表里" % rid)
                continue
            p = cm.payload(rid)
            rgb = rb["colors"][i]
            got = [_f32(p, mfb.off("materialParamValue%d" % k)) for k in (0, 1, 2)]
            if any(abs(got[k] - rgb[k] / 255.0) > 1e-4 for k in range(3)):
                bad.append("颜色行 %s 的 RGB 不对" % rid)
            if abs(_f32(p, mfb.off("materialParamValue4")) - 1.0) > 1e-4:
                bad.append("颜色行 %s 的 alpha 不是 1" % rid)
        log("    复验敌人颜色：%d 行 MaterialExParam" % len(rb["ids"]))
    if (man.get("features") or {}).get("nightday"):
        nn = find_param_name([n for n, _ in bnd.files], "ChrActivateConditionParam.param")
        npf = param_bin.ParamFile(bnd.get(nn))
        no = npf.offset_of(101000)
        if no is None or npf.data[no + 2:no + 6] != b"\x00\x00\x00\x00":
            bad.append("夜间BOSS全天：ChrActivateConditionParam 101000 的时间字段没清零")
        else:
            log("    复验夜间BOSS全天：ChrActivateConditionParam 101000 已清零")
    log("    复验 regulation：%d 行、%d 条克隆" % (len(pf.ids), len(man.get("clone_ids", {}))))
    if bad:
        raise WriteError("复验失败（%d 项）：%s" % (len(bad), "; ".join(bad[:8])))
    log("[复验] PASS：%s（%d 张图 / %d 个位置）"
        % (layer_dir, len(maps), man["counts"]["places"]))
    return {"ok": True, "maps": len(maps), "places": man["counts"]["places"]}


def reseal(layer_dir, log=print):
    """把"这层是基于哪份基线"的指纹补齐（M3 闸门用来发现基线漂移）。

    写盘时基线的 map 目录就在 <mod>/map/MapStudio；这里把每张用到的图的
    sha256 与 regulation 的 sha256 记进 manifest，之后基线一变就能立刻看出来。
    """
    man = json.load(open(os.path.join(layer_dir, MANIFEST_NAME), encoding="utf-8"))
    base_reg = man["base"]["regulation"]
    base_maps = man["base"]["maps_dir"]
    if not os.path.isfile(base_reg):
        raise WriteError("基线 regulation 不在了：%s" % base_reg)
    man["base"]["regulation_sha256"] = sha256_file(base_reg)
    miss = []
    for name, info in man["maps"].items():
        p = os.path.join(base_maps, name + ".msb.dcx")
        if os.path.isfile(p):
            info["base_sha256"] = sha256_file(p)
        else:
            miss.append(name)
    man["resealed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = os.path.join(layer_dir, MANIFEST_NAME)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    log("[基线指纹] %d 张图%s" % (len(man["maps"]) - len(miss),
                                "；%d 张基线图不在磁盘上：%s" % (len(miss), ", ".join(miss[:3])) if miss else ""))
    return man


def selftest():
    """M2 的三条验收：owner 冲突零写出、写出的图能独立读回、重跑不留半套。"""
    import tempfile
    out = tempfile.mkdtemp(prefix="gf_enemy_write_self_")
    plan = json.load(open(PLAN_DEFAULT, encoding="utf-8"))
    ok = []
    _de = load_donor_effects()
    if _de.get("c2195") != 18781:
        raise WriteError("来源专属加护表对不上（应为 c2195→18781）：%r" % (_de,))
    ok.append("来源加护表 c2195→18781")

    # ① owner 冲突注入：必须 raise，且目标目录一个字节都不出现
    bad = json.loads(json.dumps(plan))
    u0 = dict(bad["units"][0])
    u0["key"] = u0["key"] + "#dup"
    bad["units"].append(u0)
    pbad = os.path.join(out, "plan_bad.json")
    json.dump(bad, open(pbad, "w", encoding="utf-8"))
    try:
        build(pbad, label="owner_conflict", out_root=out, limit=1, log=lambda *a: None)
    except WriteError as exc:
        if "owner 冲突" not in str(exc):
            raise WriteError("自检①：抛的不是 owner 冲突：%s" % exc)
        ok.append("owner 冲突 raise")
    else:
        raise WriteError("自检①：owner 冲突没有 raise")
    if os.path.isdir(os.path.join(out, "owner_conflict")):
        raise WriteError("自检①：冲突时仍写了目录")
    ok.append("冲突零写出")

    # ② 写两张图 + 独立复验
    _plans = os.path.join(out, "_plans")
    build(PLAN_DEFAULT, label="selftest", out_root=out, limit=2, log=lambda *a: None,
          plans_dir=_plans)
    # v1.3.19：写盘时会补 balance（内存里改过 target_hp），快照是重新序列化的那一份，
    # 所以复验必须用快照而不是原计划文件（否则 sha 必然对不上；2026-10-24 修）。
    verify_layer(os.path.join(out, "selftest"),
                 os.path.join(_plans, "selftest.json"), log=lambda *a: None)
    ok.append("读回 PASS")

    # ③ 同 label 重跑：整体替换、不留 .stage_/.old_
    build(PLAN_DEFAULT, label="selftest", out_root=out, limit=2, log=lambda *a: None,
          plans_dir=_plans)
    leftovers = [n for n in os.listdir(out) if n.startswith((".stage_", "selftest.old_"))]
    if leftovers:
        raise WriteError("自检③：留下临时/旧目录 %s" % leftovers)
    ok.append("重跑无残留")
    shutil.rmtree(out, ignore_errors=True)
    print("[M2 自检] PASS：" + " / ".join(ok))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="M2 写盘层：plan.json → 方案层")
    ap.add_argument("--plan", default=None,
                    help="计划 JSON（默认 investigation/enemy_plan.json；--verify 时默认用该层 manifest 里记的那份）")
    ap.add_argument("--label")
    ap.add_argument("--out-root", help="默认 <法魂包>\\方案")
    ap.add_argument("--base-reg", help="基线 regulation（默认当前 mod 下那份）")
    ap.add_argument("--limit", type=int, help="只写前 N 张图（冒烟用）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", metavar="LABEL", help="复验一个已写好的方案层")
    ap.add_argument("--reseal", metavar="LABEL", help="补记这一层的基线文件指纹")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        selftest()
        return 0
    if args.reseal:
        root = args.out_root or plan_layer.plans_root()
        reseal(os.path.join(root, args.reseal))
        return 0
    if args.verify:
        root = args.out_root or plan_layer.plans_root()
        layer_dir = os.path.join(root, args.verify)
        plan_path = args.plan
        if plan_path is None:
            man = json.load(open(os.path.join(layer_dir, MANIFEST_NAME), encoding="utf-8"))
            plan_path = ((man.get("plan") or {}).get("path") or "")
            if not plan_path or not os.path.isfile(plan_path):
                raise WriteError("这一层的 manifest 没记计划路径或计划已不在：%s" % plan_path)
            print("[复验] 用该层写盘时的计划：%s" % plan_path)
        verify_layer(layer_dir, plan_path)
        return 0
    m = build(args.plan or PLAN_DEFAULT, label=args.label, out_root=args.out_root,
              base_reg=args.base_reg, limit=args.limit, dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        print("[写盘] 完成：%s" % m["label"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
