# -*- coding: utf-8 -*-
"""敌人随机（一期 · regulation 级）

设计口径（作者 2026-10-15 定稿，见 docs/敌人随机_方案.md）：
* 池子模型照抄原版敌人随机：**类别池 + 加权来源池**；池的类型允许自创
* 法魂与原版的敌人**合并进同一个池**；可选「只随机法魂敌人」
* **没有不可动的 Boss**；多阶段 Boss 一期按"同类别"处理（二期接 MSB 时再整组换）
* 兼容性硬指标：与物品随机**共用一个 regulation.bin**，靠"同一次部署里先后写入"实现，
  且**两边的随机数互相独立**（敌人用 `seed|enemy|...`，物品用既有流）

本模块只做**整行置换**：把 A 行（敌人种类）的内容整段换成 B 行的内容。
行大小固定（见 Paramdex），所以是**等长就地改写**，与现有工具同一个哲学。
交换后会把 `teamType` / `npcType` 恢复成原行取值（阵营/生成类型不跟着走）。
"""
import csv
import hashlib
import io
import os
import random
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PARAMDEX = os.path.abspath(os.path.join(HERE, "..", "..", "tools", "witchybnd-3.0.1.0",
                                       "Assets", "Paramdex", "ER", "Defs"))
SIZE = {"u8": 1, "i8": 1, "s8": 1, "dummy8": 1, "u16": 2, "i16": 2, "s16": 2, "dummy16": 2,
        "u32": 4, "i32": 4, "s32": 4, "f32": 4, "angle32": 4,
        "u64": 8, "i64": 8, "s64": 8, "f64": 8}

# 交换整行之后要"恢复成原值"的字段（阵营 / 生成类型 —— 不跟着敌人身份走）
KEEP_FIELDS = ("teamType", "npcType")

# 类别划分的默认口径（纯字段，不依赖名字；名字表可用 CSV 补充）
CLASS_ORDER = ["boss", "elite", "normal"]
CLASS_ZH = {"boss": "Boss", "elite": "精英", "normal": "普通敌人", "skip": "非敌人（排除）"}


# ────────────────────────── Paramdex / 行表 ──────────────────────────

def paramdef_fields(name):
    """Paramdex 的 ER 定义 → ([(字段名, 类型, 行内偏移, 字节大小)], 行大小)"""
    p = os.path.join(PARAMDEX, name + ".xml")
    if not os.path.isfile(p):
        return None, 0
    x = open(p, encoding="utf-8-sig").read()
    out, bit_off = [], 0
    for m in re.finditer(r'<Field Def="([^"]+)">', x):
        d = m.group(1)
        typ, _, rest = d.partition(" ")
        bits = 0
        if ":" in rest:
            rest, _, b = rest.partition(":")
            b = b.split("=")[0].strip()
            bits = int(b) if b.isdigit() else 0
        nm = rest.split("=")[0].strip()
        cnt = 1
        mm = re.search(r"\[(\d+)\]", nm)
        if mm:
            cnt = int(mm.group(1))
            nm = nm[:mm.start()].strip()
        if bits:
            out.append((nm, typ, bit_off // 8, 0))
            bit_off += bits
        else:
            sz = SIZE.get(typ, 0) * cnt
            if bit_off % 8:
                bit_off += 8 - (bit_off % 8)
            out.append((nm, typ, bit_off // 8, sz))
            bit_off += sz * 8
    return out, (bit_off + 7) // 8


MIN_RUN = 100        # 一个"段"至少多大才算真 param 表（见 scan_rows 注释）


def scan_rows(raw, base, size):
    """扫 param 行表（{id, data, name} 三元组，0x18 字节一条）→ {row_id: 相对本 param 的偏移}

    ⚠️ 2026-10-16 修正：以前只保留**最长的一段连续行**，会漏掉后面那些同样合法的段
    （实测：GA 那边漏 12 行、法魂这边漏 ~24 行）。现在取**所有段的并集** —— 子 agent 在 MSB 对账时发现的。
    """
    region = raw[base:base + size]
    runs, o = [], 0
    while o + 0x18 <= len(region):
        rid, data, nm = struct.unpack_from("<QQQ", region, o)
        if 0 < rid < 0x7FFFFFFF and 0 < data < nm < len(region):
            run, r = {}, o
            while r + 0x18 <= len(region):
                _id, _d, _n = struct.unpack_from("<QQQ", region, r)
                if not (0 < _id < 0x7FFFFFFF and 0 < _d < _n < len(region)):
                    break
                run[_id] = _d
                r += 0x18
            runs.append(run)
            o = r
        else:
            o += 1
    # 只认**够大的段**（真 param 表是几千行；那堆 1~7 行的"段"是扫出来的垃圾：
    # 实测法魂 NpcParam 有 55 段，最长那段 7823 行 = 真表，其余 54 段全是重复 id 的假行，
    # 把它们当行用会直接把置换搞成非双射 —— 2026-10-16 回归当场抓到过）。
    return {k: v for run in runs if len(run) >= MIN_RUN for k, v in run.items()}


def read_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def size_bucket(radius, height):
    """体型档（参考实现用 arena/size 标签，我们用游戏里现成的两个字段自动分）"""
    if radius is None or height is None:
        return 2
    if radius > 1.5 or height > 3.5:
        return 3          # 巨
    if radius > 0.7 or height > 2.4:
        return 2          # 大
    if radius > 0.5 or height > 2.0:
        return 1          # 中
    return 0              # 小


class Unit(object):
    """一种敌人 = NpcParam 的一行"""

    __slots__ = ("rid", "off", "row_size", "hp", "soul", "is_boss", "radius", "height",
                 "npc_type", "team_type", "cls", "source", "sha", "name", "name_id",
                 "boss_like_name", "model", "enemy_type",
                 # 参考实现（thefifthmatt）的模型级人工标注
                 "ref_class", "multi", "unkillable", "ref_names", "ref_size")

    def __init__(self, rid, off, row_size, fields, plain):
        self.rid, self.off, self.row_size = rid, off, row_size
        # 参考实现的模型级标注（后面 classify 时填）
        self.ref_class, self.multi, self.unkillable = "", False, False
        self.ref_names, self.ref_size = "", ""
        p = off

        def g(k):
            f = fields.get(k)
            if not f:
                return None
            o, t, sz = f
            q = p + o
            if t in ("u8", "i8", "s8"):
                return plain[q]
            if t in ("u16", "i16", "s16"):
                return struct.unpack_from("<H", plain, q)[0]
            if t in ("u32", "i32", "s32"):
                return struct.unpack_from("<I", plain, q)[0]
            if t == "f32":
                return struct.unpack_from("<f", plain, q)[0]
            return None

        self.hp = g("hp") or 0
        self.soul = g("getSoul") or 0
        self.is_boss = (g("isSoulGetByBoss") == 1)
        self.radius = g("chrHitRadius")
        self.height = g("chrHitHeight")
        self.npc_type = g("npcType")
        self.team_type = g("teamType")
        self.name_id = g("nameId") or 0
        self.boss_like_name = False
        self.model = ""
        self.enemy_type = ""
        self.cls = "normal"
        self.source = "old"            # old = 原版 / new = 法魂新增（默认 unknown → old）
        self.name = ""
        self.sha = hashlib.sha256(bytes(plain[off:off + row_size])).hexdigest()[:16]


def load_units(plain, table="NpcParam"):
    """读全部敌人行 → {row_id: Unit}"""
    import native_apply as na
    fields, row_size = paramdef_fields(table)
    if not fields:
        raise RuntimeError(f"读不到 Paramdex 定义：{table}")
    base = na.file_start(plain, table)
    if not base:
        raise RuntimeError(f"regulation 里找不到 {table}")
    # 行表在 param 文件体里，偏移相对该 param 起始
    _off, _size = 0, 0
    for name, off, size in na.bnd4_entries(plain):
        if os.path.basename(name.replace("\\", "/")) == table + ".param":
            _off, _size = off, size
    rows = scan_rows(plain, _off, _size)
    fmap = {f[0]: (f[2], f[1], f[3]) for f in fields}
    units = {}
    for rid, rel in rows.items():
        u = Unit(rid, _off + rel, row_size, fmap, plain)
        if u.hp > 0 and u.hp < 10 ** 8:
            units[rid] = u
    return units


# ────────────────────────── 分类与池 ──────────────────────────

def load_row_types(row_models=None, type_map=None):
    """{row_id: 敌型} —— 走两层：行 →（实际被放置的）模型 → 敌型。

    `row_models.csv` 来自地图实测（3807 个行在地图上被用到，其中 3788 个只对应 1 个模型）；
    `enemy_type_map.csv` 来自子 agent 的归类（462 个模型 → 16 类 + 体型档 + 未分类）。
    注意：只有 34.8% 的模型有权威名字（杂兵在 NpcParam 里 nameId=0），所以大部分行拿不到敌型 ——
    这不是 bug，是数据上限；拿到的那部分当**画像标签**用，不要当池子的轴。
    """
    rm = row_models if row_models is not None else os.path.join(HERE, "..", "row_models.csv")
    tm = type_map if type_map is not None else os.path.join(HERE, "..", "enemy_type_map.csv")
    mod2type, row2model = {}, {}
    try:
        with open(tm, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("model"):
                    mod2type[r["model"]] = r.get("enemy_type") or ""
        with open(rm, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = str(r.get("npc_id") or "").strip()
                if rid.isdigit() and int(rid) > 0 and r.get("model"):
                    row2model[int(rid)] = r["model"]
    except Exception:
        return {}
    return {rid: mod2type.get(m, "") for rid, m in row2model.items()}


def load_row_models(path=None):
    """{row_id: 主模型}（地图实测：某个行被放置时最常用的那个模型）"""
    p = path or os.path.join(HERE, "..", "row_models.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = str(r.get("npc_id") or "").strip()
                if rid.isdigit() and int(rid) > 0 and r.get("model"):   # 0 是占位，不是行
                    out[int(rid)] = r["model"]
    except Exception:
        return {}
    return out


def load_new_rows(path=None):
    """**法魂新增**的 NpcParam 行集合（{row_id}）。

    来源：拿**游戏本体的原版 regulation.bin** 与法魂那份做行级 diff —— 只在法魂里出现的行就是新增的。
    实测：原版 7037 行 vs 法魂 7823 行 → 只在法魂 **786** 行（其中 727 行连名字都没有）。
    这就是界面上「只随机法魂敌人」的依据 —— 以前只能靠名字猜，现在有据可依。
    数据表随包一起发（investigation/convergence_new_rows.csv），所以玩家机器上不需要有原版 regulation。
    """
    p = path or os.path.join(HERE, "..", "convergence_new_rows.csv")
    out = set()
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid = str(r.get("row_id") or "").strip()
                if rid.isdigit():
                    out.add(int(rid))
    except Exception:
        return set()
    return out


def load_ref(path=None):
    """参考实现（thefifthmatt ER Randomizer）的**模型级**人工标注 → {模型: dict}。

    来源：它自带 Base/enemy.txt（23173 条），我们只把它转成自己的表（enemy_ref.csv，随包发）。
    比我们自研分类强的地方：
      * ref_class：人工档位（Basic / Miniboss / Boss / Miniboss / Wildlife / Scarab / Helper / None…）
      * multi：**多阶段 Boss**（98 个模型）—— "整组换"要用的名单
      * unkillable：打不死的（174 个模型）—— 换掉它们可能卡剧情，默认跳过
      * size / arena / perceptive / names（101 个模型带真名，如 c2030=Rennala 1、c2110=Beast Clergyman/Maliketh）
    """
    p = path or os.path.join(HERE, "..", "enemy_ref.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = (r.get("model") or "").strip()
                if not m:
                    continue
                out[m] = {
                    "class": (r.get("ref_class_top") or "").strip(),
                    "classes": (r.get("ref_class") or "").strip(),
                    "multi": r.get("multi") == "1",
                    "unkillable": r.get("unkillable") == "1",
                    "size": (r.get("size") or "").strip(),
                    "arena": (r.get("arena") or "").strip(),
                    "perceptive": r.get("perceptive") == "1",
                    "names": (r.get("extra_names") or "").strip(),
                    "n": int(r.get("n_entries") or 0),
                }
    except Exception:
        return {}
    return out


def load_boss_names(path=None):
    """Boss 行的显示名：{npc_id: 血条上的名字}（来自 boss_rows.csv）

    为什么需要它：Boss 行在 NpcParam 里 nameId 基本是 0（实测 296 个 Boss 行里只有 29 个有名字），
    真正的显示名在 EMEVD 的血条指令里 —— 所以名字要从那张表贴过来。
    """
    p = path or os.path.join(HERE, "..", "boss_rows.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                nid = str(r.get("npc_id") or "").strip()
                nm = (r.get("boss_name") or "").strip()
                if nid.isdigit() and nm:
                    out.setdefault(int(nid), nm)
    except Exception:
        return {}
    return out


def load_boss_rows(path=None):
    """**有血条 Boss** 对应的 NpcParam 行集合（来自 enemy_map_atlas 的 boss_rows.csv）。

    这是目前最强的 Boss 判据：地图实体（MSB）→ NPCParamID（行），
    而实体是不是"有血条 Boss"由 EMEVD 的 DisplayBossHealthBar 决定 —— 两端都是解包实测。
    本机实测：332 条血条调用 → 313 条能在地图里找到实体 → 228 个唯一 Boss 行。
    """
    p = path or os.path.join(HERE, "..", "boss_rows.csv")
    out = set()
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if str(r.get("in_regulation", "")).lower() not in ("true", "1"):
                    continue
                # 子 agent 给的四条用法（照做）：
                #   ① 剔掉 .js 里被 // 注释掉的调用（血条根本不会开）
                #   ② 剔掉没解析出名字的（name_id=0）
                if "commented" in (r.get("note") or "").lower():
                    continue
                if not str(r.get("name_id") or "").strip().strip("0"):
                    continue
                nid = str(r.get("npc_id") or "").strip()
                if nid.isdigit():
                    out.add(int(nid))
    except Exception:
        return set()
    return out


def load_healthbar_nameids(path=None):
    """血条名单里的名字 id 集合（来自 EMEVD 的 DisplayBossHealthBar）。

    用途：如果某行的 `nameId` 正好等于某个"有血条 Boss 的名字 id"，
    那它就是**有确凿证据的 Boss**（不是靠 hp/名字猜的）→ 强制归入 Boss 池。
    本机实测：血条名单 165 个唯一名字 id，其中 12 个能对上 53 行 NpcParam。
    """
    p = path or os.path.join(HERE, "..", "boss_healthbar.csv")
    out = set()
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                nid = (r.get("name_id") or "").strip()
                if nid.isdigit() and int(nid) > 0:
                    out.add(int(nid))
    except Exception:
        return set()
    return out


def load_name_table(path=None):
    """敌人中文名表 {row_id: 文本}。

    数据源是 `investigation/enemy_table.csv`（由 enemy_names.py 的 FMG 解析导出：
    修好了 ER 的"区间条目"之后，7823 行里有 736 行能对上中文名）。
    直接按 **row_id** 贴，不再走 nameId —— 三个 FMG 的 id 空间会重叠，row_id 没有这个问题。
    注意：Boss 行的 nameId 基本是 0（实测 750 个有 nameId 的行里绝大多数是普通敌人），
    所以 Boss 的名字要去事件/追忆物品那边找（二期）。
    """
    p = path or os.path.join(HERE, "..", "enemy_table.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rid, nm = (r.get("row_id") or "").strip(), (r.get("name") or "").strip()
                if rid.isdigit() and nm:
                    out[int(rid)] = nm
    except Exception:
        return {}
    return out


def infer_hostile_teams(units, cover=0.95):
    """从数据推断"敌对阵营"的 teamType 集合。

    做法（本机实测得出的口径）：**无名行**的 teamType 分布在 6/7/48/51/47/9 这类值上占了绝大多数，
    而"有名字的行"（NPC / 有名角色）集中在 26/27/2 —— 也就是友好 NPC 用的队伍号。
    所以取"无名行里累计覆盖到 cover 的那几个 teamType"当敌对集合，比硬编码一个白名单更耐版本变化。
    （参考实现是拿 10 万行人工标注解决这件事的；我们先用数据推断，再留人工覆盖口子。）
    """
    import collections
    cnt = collections.Counter(u.team_type for u in units.values() if not u.name and u.team_type is not None)
    total = sum(cnt.values()) or 1
    out, acc = set(), 0
    for t, c in cnt.most_common():
        out.add(t)
        acc += c
        if acc / total >= cover:
            break
    return out


def classify(units, table=None, names=None, healthbar_ids=None, boss_rows=None,
             boss_names=None, row_types=None, new_rows=None, ref=None):
    """给每个 unit 定 cls（boss / elite / normal）与 source（old / new）。
    可选 table：{row_id: {"cls":…, "source":…, "name":…}}（由名字表导出，人工可改）"""
    if names:
        for rid, nm in names.items():
            u = units.get(int(rid))
            if u and nm:
                u.name = nm
    hps = sorted(u.hp for u in units.values())
    hi = hps[int(len(hps) * 0.75)] if hps else 0
    hostile = infer_hostile_teams(units, cover=0.80)
    _hb_ids = healthbar_ids if healthbar_ids is not None else load_healthbar_nameids()
    _boss_rows = boss_rows if boss_rows is not None else load_boss_rows()
    boss_names = boss_names if boss_names is not None else load_boss_names()
    for rid, u in units.items():
        if rid in _boss_rows:
            # **解包实测**的 Boss：地图实体 → 行，且该实体有 Boss 血条（EMEVD）
            # —— 这条比 isSoulGetByBoss 更准（那条只表示"击杀给 Boss 魂"），也比名字靠谱
            u.cls = "boss"
        elif u.is_boss:
            u.cls = "boss"                      # Boss 按游戏自己的标记（友好 NPC 不会有）
        elif u.name_id and u.name_id in _hb_ids:
            # 名字 id 命中血条名单 —— 只能当**标签**，不能当证据！
            # 实测反例：帕奇（130900）是友好 NPC，他的名字 id 也出现在血条名单里
            #（名字 id 在多行之间共享）→ 强行升成 boss 会把 NPC 拉进 Boss 池。
            # 真正"这一行是不是有血条 Boss"要等 MSB 映射（实体 → NPCParamID）才能确定。
            u.boss_like_name = True
        elif u.name:
            # 有中文名的行 ≈ 有名有姓的 NPC / 独特角色（实测 736 个有名字的行里只有 26 个是 Boss）
            # → 保守起见先不参与杂兵/精英池；想放开就用人工复核表逐行指定 cls
            u.cls = "skip"
        elif u.team_type in hostile and u.hp > 0:
            u.cls = "elite" if u.hp >= max(hi, 800) else "normal"
        else:
            u.cls = "skip"
    if boss_names:
        for rid, u in units.items():
            if u.cls == "boss" and not u.name and rid in boss_names:
                u.name = boss_names[rid]        # Boss 的名字来自血条名单
    _ref = ref if ref is not None else load_ref()
    _r2m = {}                                  # 行 → 模型（用于接上模型级标注）
    try:
        with open(os.path.join(HERE, "..", "row_models.csv"), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("model") and str(r.get("npc_id", "")).isdigit():
                    _r2m[int(r["npc_id"])] = r["model"]
    except Exception:
        pass
    _new = new_rows if new_rows is not None else load_new_rows()
    if _new:
        # 法魂新增 / 原版就有 —— 这是「只随机法魂敌人」的依据
        for rid, u in units.items():
            u.source = "new" if rid in _new else "old"
    if row_types is None:
        row_types = load_row_types()
    if row_types:
        for rid, u in units.items():
            t = row_types.get(rid)
            if t:
                u.enemy_type = t
    # ── 接上参考实现的**模型级人工标注**（比我们自己靠血量/名字关键词推的准）──
    if _ref and _r2m:
        for rid, u in units.items():
            r = _ref.get(_r2m.get(rid, ""))
            if not r:
                continue
            u.ref_class = r["class"]
            u.multi = bool(r["multi"])
            u.unkillable = bool(r["unkillable"])
            u.ref_names = r["names"]
            u.ref_size = r["size"]
            _c = r["class"]
            # 只有它明确标了档位才覆盖；"None/Helper" 这类我们不动（保留自己的判断）
            if _c in ("Basic", "Wildlife", "Scarab"):
                u.cls = "normal" if u.cls != "boss" else u.cls
            elif _c in ("Miniboss", "MinorBoss", "NightMiniboss", "DragonMiniboss"):
                u.cls = "elite" if u.cls != "boss" else u.cls
            elif _c == "Boss":
                u.cls = "boss"
        # ── 多阶段 Boss：档位由**整组**决定 ──
        # 为什么必须这样：一阶段通常有血条（判成 boss），二阶段没有（会被判成 elite/normal）——
        # 分开判的结果就是"组里两行进了不同的池"，整组换立刻跨池（自检一次报了 2277 条，就是这么来的）。
        # 阶段 2 本来也是 Boss，所以取组内最高档。
        _rank = {"skip": 0, "normal": 1, "elite": 2, "boss": 3}
        for _key, members in multi_units(units, sorted(units)):
            if len(members) < 2:
                continue
            top = max(members, key=lambda r: _rank.get(units[r].cls, 0))
            best = units[top].cls
            if best in ("elite", "boss"):
                for r in members:
                    if _rank.get(units[r].cls, 0) < _rank[best]:
                        units[r].cls = best

    if table:
        for rid, meta in table.items():
            u = units.get(int(rid))
            if not u:
                continue
            if meta.get("cls") in CLASS_ORDER:
                u.cls = meta["cls"]
            if meta.get("source"):
                u.source = meta["source"]
            if meta.get("name"):
                u.name = meta["name"]
    return units


def load_class_table(path):
    """外部分类表（CSV：row_id,cls,source,name）—— 名字表/人工复核表都走这里"""
    if not path or not os.path.isfile(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rid = (r.get("row_id") or "").strip()
            if not rid.isdigit():
                continue
            out[int(rid)] = {"cls": (r.get("cls") or "").strip() or None,
                             "source": (r.get("source") or "").strip() or None,
                             "name": (r.get("name") or "").strip() or None}
    return out


def build_pools(units, cfg):
    """按类别分池；再按"来源标签"过滤候选（只随机法魂敌人 / 全随机）"""
    pools = {c: [] for c in CLASS_ORDER}
    keep_unk = bool(cfg.get("allow_unkillable"))     # 默认 False：打不死的先别动
    n_unk = 0
    for u in units.values():
        if u.unkillable and not keep_unk:
            n_unk += 1
            continue                        # 打不死的（174 个模型的 1910 行）：换掉可能卡剧情
        if u.cls in pools:                      # skip（友好 NPC/场景物）直接不进任何池
            pools[u.cls].append(u.rid)
    wanted = cfg.get("enemy_pools") or CLASS_ORDER
    src = cfg.get("enemy_source") or "all"
    types = cfg.get("types")            # 空 = 不限；否则只出现在这些敌型里
    if types:
        types = set(types)
        pools = {c: [r for r in v if units[r].enemy_type in types] for c, v in pools.items()}
    out = {}
    for c in CLASS_ORDER:
        if c not in wanted:
            continue
        rids = sorted(pools[c])
        if src == "new":
            keep = [r for r in rids if units[r].source == "new"]
            if len(keep) < 2:
                # 名单还没接进来时不要静默变成"什么都不换"
                keep = rids
                out.setdefault("_warn", []).append(
                    f"{CLASS_ZH[c]}：'只随机法魂敌人' 的名单为空（名字表未接入）→ 该池按全随机处理")
        else:
            keep = rids
        if len(keep) >= 2:
            out[c] = keep
    if n_unk:
        out.setdefault("_warn", []).append(
            "有 %d 行是参考实现标注的「打不死」，默认没动它们（想一起换就开 allow_unkillable）" % n_unk)
    return out


# ────────────────────────── 方案（置换） ──────────────────────────

def _derangement(items, rng):
    """错排：没有任何一项留给自己（与物品随机器同一种做法）"""
    n = len(items)
    if n < 2:
        return list(items)
    for _ in range(60):
        cand = items[:]
        rng.shuffle(cand)
        if all(cand[i] != items[i] for i in range(n)):
            return cand
    return items[1:] + items[:1]        # 兜底：整体轮换一位


def multi_units(units, rids):
    """把"同一个 Boss 的多个阶段"捆成一个**单元**：[(组名, [各阶段行…]), …]

    为什么必须整组换：多阶段 Boss 是**好几行 NpcParam**（一阶段一行）。
    只换其中一行的结果是"打到半血变身，又变回原样 / 变成别的 Boss 的第一形态" —— 坏体验。
    分组依据（来自参考实现的人工标注，见 enemy_ref.csv）：
      * multi 标记：这个模型是多阶段的
      * ExtraName 里的基础名：`Rennala 1` / `Rennala 2` → 基础名都叫 Rennala ⇒ 同一组
        没有名字时退回"同模型"（同模型的多阶段行必然同组）
    阶段数会写进桶键（见 make_plan）⇒ 2 阶段的只会和 2 阶段的换，1 对 1 的不会被拆散。
    """
    groups = {}
    for rid in rids:
        u = units[rid]
        if not getattr(u, "multi", False):
            groups.setdefault(("single", rid), []).append(rid)
            continue
        names = [x.strip() for x in (u.ref_names or "").replace("、", ",").split(",") if x.strip()]
        base = ""
        for nm in names:
            b = re.sub(r"\s*\d+$", "", nm).strip()      # "Rennala 1" → "Rennala"
            if b:
                base = b
                break
        key = ("multi", base or ("model:" + str(getattr(u, "model", "") or u.rid)))
        groups.setdefault(key, []).append(rid)
    return [(k, sorted(v)) for k, v in groups.items()]


def make_plan(units, cfg):
    """生成置换计划：{row_id: new_row_id}

    关键：**先按体型分桶、再在桶内置换** —— 这样"大的不许塞进小的"这条护栏
    是**由构造保证**的，而且每个子集都是**闭合置换**（种类守恒不会被破坏）。
    （一开始我写成"逐对判断、不合格就跳过"，那会破坏双射 —— 自检里当场抓到了。）
    """
    seed = cfg.get("seed", 0)
    rate_all = float(cfg.get("enemy_rate", 1.0))
    rates = cfg.get("enemy_rates") or {}          # 每类各自的比例（参考实现的 per-category）
    ignore_size = bool(cfg.get("ignore_size"))    # 忽略体型限制
    pools = build_pools(units, cfg)
    warn = pools.pop("_warn", [])
    plan = {}
    for cls in CLASS_ORDER:
        rids = pools.get(cls)
        if not rids:
            continue
        rate = float(rates.get(cls, rate_all))
        # ① 先捆单元：多阶段 Boss 的几个阶段是一整个单元（整组换）
        unit_list = multi_units(units, rids)
        # ② 体型分桶（桶键里带"阶段数" ⇒ 2 阶段的只和 2 阶段的换）
        buckets = {}
        for key, members in unit_list:
            reps = [units[r] for r in members]
            if ignore_size:
                b = 0
                prof = ()
            else:
                prof = tuple(sorted(size_bucket(x.radius, x.height) for x in reps))
                b = max(prof)                      # 取最大，保守
            if cfg.get("same_type"):
                b = (reps[0].enemy_type or "?", b)
            # 阶段数 + "各阶段的体型档案"都进桶键：档案一样才会配对，
            # 于是"阶段 k 换阶段 k"必然同档（此前只取最大档，自检抓到过一条体型越界）
            b = (b, len(members), prof)
            buckets.setdefault(b, []).append((key, members))
        for bucket, units_in_bucket in sorted(buckets.items(), key=lambda kv: str(kv[0])):
            if len(units_in_bucket) < 2:
                continue
            rng = random.Random(f"{seed}|enemy|{cls}|{bucket}|{ignore_size}|{bool(cfg.get('same_type'))}")
            k = len(units_in_bucket) if rate >= 1 else max(2, int(round(len(units_in_bucket) * rate)))
            pool = units_in_bucket[:]
            rng.shuffle(pool)
            chosen = sorted(pool[:k], key=lambda x: str(x[0]))
            if len(chosen) < 2:
                continue
            order = _derangement(chosen, rng)
            for (tk, tm), (sk, sm) in zip(chosen, order):
                if tm == sm or tk == sk:
                    continue
                # 阶段对阶段：第 k 阶段换第 k 阶段（组内按行号排序即阶段序）
                for i, t in enumerate(tm):
                    if i < len(sm):
                        plan[t] = sm[i]    # 桶内置换 ⇒ 双射成立
    return plan, warn


def plan_fingerprint(plan):
    h = hashlib.sha256()
    for k in sorted(plan):
        h.update(f"{k}>{plan[k]};".encode())
    return h.hexdigest()


# ────────────────────────── 写出 / 应用 ──────────────────────────

PLAN_COLS = ["row_id", "cls", "new_row_id", "old_sha", "new_sha", "name_old", "name_new"]


def write_plan(plan, units, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f)
        w.writerow(PLAN_COLS)
        for rid in sorted(plan):
            nid = plan[rid]
            w.writerow([rid, units[rid].cls, nid, units[rid].sha, units[nid].sha,
                        units[rid].name, units[nid].name])
    return path


def read_plan(path):
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out.append(r)
    return out


class EnemyPlanError(RuntimeError):
    """写前复核失败：现状与计划不符 → 立即中止（与物品侧的 H12 同一种纪律）"""


def apply_plan(plan_rows, source, out_path=None, verify=True, quiet=False, table="NpcParam"):
    """把计划应用到 regulation：整行内容按计划置换（等长就地改写）"""
    import erio
    import native_apply as na
    out_path = out_path or source
    plain = bytearray(erio.dcx_decompress(erio.regulation_decrypt(source)))
    fields, row_size = paramdef_fields(table)
    fmap = {f[0]: (f[2], f[1], f[3]) for f in fields}
    _off, _size = 0, 0
    for name, off, size in na.bnd4_entries(bytes(plain)):
        if os.path.basename(name.replace("\\", "/")) == table + ".param":
            _off, _size = off, size
    rows = scan_rows(bytes(plain), _off, _size)

    # ① 复核：每一行的当前内容必须与计划里的 old_sha 一致
    for r in plan_rows:
        rid = int(r["row_id"])
        rel = rows.get(rid)
        if rel is None:
            raise EnemyPlanError(f"复核失败：找不到行 {rid}")
        cur = hashlib.sha256(bytes(plain[_off + rel:_off + rel + row_size])).hexdigest()[:16]
        if cur != r["old_sha"]:
            raise EnemyPlanError(f"复核失败：行 {rid} 的现状与计划不符（{cur} ≠ {r['old_sha']}）→ 已中止")

    # ② 先把所有涉及行的**原始内容**快照下来（置换会让每行既是目标又是源，边写边读必错）
    need = set()
    for r in plan_rows:
        need.add(int(r["row_id"]))
        need.add(int(r["new_row_id"]))
    before_rows = {rid: bytes(plain[_off + rows[rid]:_off + rows[rid] + row_size]) for rid in need}

    # ③ 逐行覆盖 + 恢复 KEEP_FIELDS
    changed = 0
    for r in plan_rows:
        rid, nid = int(r["row_id"]), int(r["new_row_id"])
        base = _off + rows[rid]
        newb = bytearray(before_rows[nid])          # 源行的原始内容
        for k in KEEP_FIELDS:
            if k in fmap:
                o, t, sz = fmap[k]
                newb[o:o + sz] = before_rows[rid][o:o + sz]   # 保留字段取**原行**的值
        if len(newb) != row_size:
            raise EnemyPlanError("行大小不一致，拒绝写入")
        plain[base:base + row_size] = newb
        changed += 1

    if verify:
        _verify_plan_applied(bytes(plain), plan_rows, rows, _off, row_size, fmap, before_rows)
    # 回压：与现有工具完全相同的封装顺序（沿用原文件的 DCX 模板，保证帧参数不变）
    dcx = erio.dcx_compress(bytes(plain), getattr(na.erio_bnd_template(source), "dcx_template", None), 12)
    erio.regulation_encrypt(dcx, out_path)
    if not quiet:
        print(f"  敌人随机：应用 {changed} 行（整行置换，等长改写）→ {os.path.basename(out_path)}")
    return {"rows": changed, "fingerprint": plan_fingerprint(
        {int(r["row_id"]): int(r["new_row_id"]) for r in plan_rows})}


def _verify_plan_applied(plain, plan_rows, rows, off0, row_size, fmap, before_rows):
    """应用后自检：每行现在的内容 == **源行的原始内容**（保留字段除外），且长度不变"""
    for r in plan_rows:
        rid, nid = int(r["row_id"]), int(r["new_row_id"])
        a = bytes(plain[off0 + rows[rid]:off0 + rows[rid] + row_size])
        want = bytearray(before_rows[nid])
        for k in KEEP_FIELDS:
            if k in fmap:
                o, _t, sz = fmap[k]
                want[o:o + sz] = before_rows[rid][o:o + sz]
        want = bytes(want)
        if a != want:
            bad = [i for i in range(row_size) if a[i] != want[i]]
            raise EnemyPlanError(f"应用后自检失败：行 {rid} 与源行 {nid} 在 {len(bad)} 字节处不一致")


def verify_plan(units, plan, cfg):
    """生成侧自检：池内、体型护栏、双射（种类守恒）"""
    issues = []
    pools = build_pools(units, cfg)
    pools.pop("_warn", None)
    inverse = {}
    for tgt, src in plan.items():
        if src in inverse:
            issues.append(f"行 {src} 被用了两次（{inverse[src]} 与 {tgt}）→ 不是置换")
        inverse[src] = tgt
        if tgt == src:
            issues.append(f"行 {tgt} 换成了自己")
        ct, cs = units[tgt].cls, units[src].cls
        if ct != cs:
            issues.append(f"跨池：{tgt}({ct}) ← {src}({cs})")
        elif cls_members := pools.get(ct):
            if tgt not in cls_members or src not in cls_members:
                issues.append(f"池外成员：{tgt} 或 {src} 不在 {ct} 池里")
        if cfg.get("same_type") and (units[tgt].enemy_type or "?") != (units[src].enemy_type or "?"):
            issues.append(f"\u8de8\u654c\u578b\uff1a{tgt}({units[tgt].enemy_type or '?'}) \u2190 ({units[src].enemy_type or '?'})")
        if not cfg.get("ignore_size"):
            # 人为放开体型时不检这条（对应参考实现的 Ignore arena size）
            b_t = size_bucket(units[tgt].radius, units[tgt].height)
            b_s = size_bucket(units[src].radius, units[src].height)
            if b_s > b_t:
                issues.append(f"体型越界：{tgt}({b_t}) ← ({b_s})")
    return issues


def summarize(units, plan):
    import collections
    c = collections.Counter(units[r].cls for r in plan)
    return {CLASS_ZH.get(k, k): v for k, v in c.items()}


def examples(units, plan, n=3):
    """给几条"谁换成了谁"的例子：**优先挑有中文名的**（预览里给人看的）"""
    named = [r for r in sorted(plan) if units[r].name and units[plan[r]].name]
    pick = named[:n] if named else sorted(plan)[:n]
    return [f"{units[r].name or units[r].rid} → {units[plan[r]].name or units[plan[r]].rid}"
            for r in pick]


# ────────────────────────── 自检 / 命令行 ──────────────────────────

def _mod_reg():
    root = os.environ.get("CONVERGENCE_MOD_ROOT") or r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"
    return os.path.join(root, "mod", "regulation.bin")


def load_plain(reg_path=None):
    """读出 regulation 明文（供调用方复用，避免重复解密解包）"""
    import erio
    return bytes(erio.dcx_decompress(erio.regulation_decrypt(reg_path or _mod_reg())))


def plan_for_cfg(enemy_cfg, reg_path=None, plain=None, class_table=None, names=None):
    """按 cfg 生成完整计划：读 → 分类 → 置换 → 自检。

    enemy_cfg 形如：{"on": True, "pools": ["boss","elite","normal"], "rate": 0.5, "source": "all"}
    返回 (units, plan, warn, issues)；调用方负责决定要不要落盘。
    """
    plain = plain if plain is not None else load_plain(reg_path)
    units = load_units(plain)
    if names is None:
        names = load_name_table()
    classify(units, class_table if class_table is not None
             else load_class_table(os.environ.get("ENEMY_CLASS_TABLE")),
             names=names)
    cfg = {"seed": enemy_cfg.get("seed", 20261015),
           "enemy_rate": float(enemy_cfg.get("rate", 1.0)),
           "enemy_pools": enemy_cfg.get("pools") or CLASS_ORDER,
           "enemy_source": enemy_cfg.get("source") or "all"}
    # 2026-10-17：界面新增的两项要透传过去，否则设置会被静默忽略
    if enemy_cfg.get("rates"):
        cfg["enemy_rates"] = enemy_cfg["rates"]
    if enemy_cfg.get("ignore_size"):
        cfg["ignore_size"] = True
    if enemy_cfg.get("same_type"):
        cfg["same_type"] = True
    if enemy_cfg.get("allow_unkillable"):
        cfg["allow_unkillable"] = True
    if enemy_cfg.get("types"):
        cfg["types"] = list(enemy_cfg["types"])
    plan, warn = make_plan(units, cfg)
    if not names and not class_table:
        # 少了名字表就分不出"友好 NPC"，可能把它们也换掉 —— 必须说出来，不静默
        warn.append("名字表缺失（investigation/enemy_table.csv 不在）—— 无法识别友好 NPC，"
                    "本次可能把 NPC 也换掉；请确认这个文件在")
    issues = verify_plan(units, plan, cfg)
    return units, plan, warn, issues


def selftest():
    """读真实 regulation → 分类 → 生成 → 自检 → 应用到临时副本 → 回读核对"""
    import erio
    import tempfile
    src = _mod_reg()
    print(f"[1/6] 读 regulation：{src}")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(src)))
    units = load_units(plain)
    print(f"[2/6] 敌人行 {len(units)}")
    classify(units)
    import collections
    cnt = collections.Counter(u.cls for u in units.values())
    print(f"      分类后：{ {CLASS_ZH[k]: v for k, v in cnt.items()} }")

    cfg = {"seed": 20261015, "enemy_rate": 1.0, "enemy_pools": CLASS_ORDER, "enemy_source": "all"}
    plan, warn = make_plan(units, cfg)
    for w in warn:
        print("      [警告]", w)
    issues = verify_plan(units, plan, cfg)
    print(f"[3/6] 计划 {len(plan)} 行置换｜自检问题 {len(issues)}")
    for i in issues[:5]:
        print("      [X]", i)
    assert not issues, "计划自检没过"

    # 确定性：同种子两次必须一样
    plan2, _ = make_plan(units, cfg)
    assert plan == plan2, "同种子结果不一致"
    print("[4/6] 同种子可复现 ✓")

    # 比例
    cfg2 = dict(cfg, enemy_rate=0.3)
    plan3, _ = make_plan(units, cfg2)
    print(f"[5/6] rate=0.3 → {len(plan3)} 行（满额 {len(plan)}）")

    # 应用到一个临时副本
    tmpdir = tempfile.mkdtemp(prefix="enemy_selftest_")
    out = os.path.join(tmpdir, "regulation.bin")
    import shutil
    shutil.copy2(src, out)
    pp = os.path.join(tmpdir, "plan.csv")
    write_plan(plan, units, pp)
    res = apply_plan(read_plan(pp), out, quiet=False)
    # 回读：确认换了、且**种类守恒**（置换必须是双射）
    plain2 = bytes(erio.dcx_decompress(erio.regulation_decrypt(out)))
    units2 = load_units(plain2)
    ok = 0
    for tgt, srcid in plan.items():
        if units2[tgt].hp == units[srcid].hp:       # 与**应用前**的源行比（不是应用后的源行！）
            ok += 1
    print(f"[6/6] 写后回读：{ok}/{len(plan)} 行的血量与源行（应用前）一致")
    multiset_before = sorted(u.hp for u in units.values())
    multiset_after = sorted(u.hp for u in units2.values())
    same = multiset_before == multiset_after
    print(f"      种类守恒（全部行 hp 多重集一致）：{same}")
    print(f"      临时产物：{tmpdir}")
    assert ok == len(plan), "整行置换没有完全生效"
    assert same, "种类守恒被破坏（置换不是双射）"
    return len(plan)


def main(argv):
    if "--selftest" in argv or not argv:
        n = selftest()
        print(f"\nSELFTEST {'PASS' if n else 'FAIL'}")
        return 0 if n else 1
    if "--plan" in argv:
        import erio
        out = argv[argv.index("--plan") + 1]
        rate = float(argv[argv.index("--rate") + 1]) if "--rate" in argv else 1.0
        seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20261015
        pools = argv[argv.index("--pools") + 1].split(",") if "--pools" in argv else CLASS_ORDER
        plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(_mod_reg())))
        units = load_units(plain)
        classify(units, load_class_table(os.environ.get("ENEMY_CLASS_TABLE")))
        cfg = {"seed": seed, "enemy_rate": rate, "enemy_pools": pools,
               "enemy_source": os.environ.get("ENEMY_SOURCE", "all")}
        plan, warn = make_plan(units, cfg)
        issues = verify_plan(units, plan, cfg)
        write_plan(plan, units, out)
        print(f"计划 {len(plan)} 行 → {out}｜自检问题 {len(issues)}｜{summarize(units, plan)}")
        for w in warn:
            print("  [警告]", w)
        return 0 if not issues else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
