# -*- coding: utf-8 -*-
"""enemy_data_build —— 敌人位置主表（place table）构建 / 校验。

M0 数据作业产物：把 634 张 MSB 里所有 type==2 的敌人 part 扫成一张表，
并按 (map, part_name) 追加以参考实现（thefifthmatt）的敌人类别。

用法：
    python enemy_data_build.py --build          重建 investigation/enemy_places.csv
    python enemy_data_build.py --check          校验现有表与磁盘上的 MSB 是否一致
    python enemy_data_build.py --stats          只打统计
    python enemy_data_build.py --names          从位置表汇总"模型级"名字表（含无名杂兵的统一名）

口径（见 docs/敌人随机_M0_对齐报告.md）：
  * 主键 = (map, part_name, occurrence)。同一张图里 part 名可能重复 28 组，
    所以按扫描顺序编 occurrence，写作 "c3400_9000#1"。
  * entity_id 允许为 0：ER 里并非每个敌人 part 都有实体 ID（本仓库 27,780 个
    part 里 19,171 个是 0）。没有实体 ID 的 part 不能被 EMEVD 寻址，但仍然可以
    改 MSB 字段（换 npc/think/chara/model）——所以它们**仍然在池里**。
  * 参考实现的 ID 字段不是 MSB EntityID（实测：enemy.txt 说 m12_02 的
    c0100_9030 是 2800323，整个 15.5MB MSB 里搜不到这个 u32；而 c0100_9024 的
    12020304 能在 part+0x260 找到）。所以**类别只能按 part 名 join**，
    不能按 ID join。
  * 参考类别的来源优先级：exact（map + part_name）-> model（同名模型的多数类，
    实测与 exact 一致率 97.0%）-> unknown（法魂新增模型，等人拍板）。
"""
import os
import sys
import csv
import io
import re
import math
import bisect
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
sys.path.insert(0, HERE)

TABLE = os.path.join(INV, "enemy_places.csv")
COLS = ["map", "part_name", "occurrence", "entity_id", "npc_id", "think_id",
        "chara_id", "model", "x", "y", "z", "cls", "cls_src",
        "area", "silo", "tier", "policy", "pools", "note",
        "link",    # 由 MSB 扫描派生（见 assign_links）
        "bar",     # 1 = 这个位置（map+entity）本来就有 Boss 血条事件（见 scan_bars）
        "evt",     # EMEVD 对这个实体的脚本绑定：pair/anim/copy/aiid（见 scan_events）
        "ref_size",   # 参考 enemy.txt 的 size:N（0=未知；越大越占场地）
        "ref_arena"]  # 参考 enemy.txt 的 arena:N（0=未知；这个位置的场地档）

DEFAULT_REF = os.path.join(
    os.path.expanduser("~"), "Downloads",
    "Elden Ring Randomizer 428 v0.12.2 2026-09-09T07-25Z kRGZWDlvJ",
    "randomizer", "diste", "Base", "enemy.txt")
NAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(DEFAULT_REF)), "Names")

MODEL_TABLE = os.path.join(INV, "enemy_model_names.csv")
MODEL_COLS = ["model", "display_name", "name_src", "cls", "cls_src", "placements",
              "npc_rows", "hp_min", "hp_max", "boss_any", "policy", "note"]

# 不参与随机的模型（v1）：圆桌厅堂训练假人 + 弹丸假人 + 闪电球变体（hazard）
KEEP_MODELS = {"c8003", "c8004", "c8005", "c8006", "c8007", "c8008", "c8009",
               "c8099", "c120", "c2105", "c2151"}
# 不参与随机的内部标记类（2026-10-24 起界面也不再显示）：
#   None（占位空壳/剧情对象/拟态复制体）、Helper（跟着主人走）、DupeOnly（只有分身）、
#   Dummy（假人/危害物）、Scarab（粪金龟）、CaravanTroll（商队巨魔）。
# 真正生效的判定在 yaml 的 l1_classes[silo=false]；这个集合只给阅读代码的人对照用。
KEEP_CLASSES = {"None", "Helper", "DupeOnly", "Dummy", "Scarab", "CaravanTroll"}
# 无名模型的统一名（照参考实现 GameData.ModelName 的兜底：表里没有就给模型号）
GENERIC_NAME = "法魂杂兵（%s）"
# 同一个模型在不同图上有多个血条名时，模型级显示名人工指定（血条名多值见 note）
NAME_OVERRIDES = {"c3805": "密契女猎手"}
# 查出来但名字不在任何表里的（凭数值+位置认定），人工给个名字
KEEP_NAMES = {
    "c8003": "圆桌厅堂训练假人", "c8004": "圆桌厅堂训练假人",
    "c8005": "圆桌厅堂训练假人", "c8006": "圆桌厅堂训练假人",
    "c8007": "圆桌厅堂训练假人", "c8008": "圆桌厅堂训练假人",
    "c8009": "圆桌厅堂训练假人", "c8099": "圆桌厅堂训练假人",
    "c120": "弹丸假人",
    "c2105": "闪电球变体", "c2151": "闪电球变体",
}

# 分类与政策配置（v1 的单一权威源）：改它之后必须 --build 重生成位置表
YAML_PATH = os.path.join(HERE, "data", "enemy_classes_v3.yaml")

_ENT_RE = re.compile(r"^\s*-?\s*ID:\s*(\d+)")
_MAP_RE = re.compile(r"^\s*Map:\s*(\S+)")
_NAME_RE = re.compile(r"^\s*Name:\s*(\S+)")
_CLS_RE = re.compile(r"^\s*Class:\s*(\S+)")
_TAGS_RE = re.compile(r"^\s*Tags:\s*(.*)$")
_TAG_NUM_RE = re.compile(r"\b(size|arena):(\d+)")


def map_dir():
    import enemy_randomizer as ER
    mod = ER._mod_reg()
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(mod))),
                        "mod", "map", "MapStudio")


def scan_places():
    """扫全部 MSB，返回 [{map, part_name, occurrence, entity_id, npc_id, ...}]。"""
    import msb_read as M
    d = map_dir()
    out = []
    seen = collections.Counter()
    for f in sorted(x for x in os.listdir(d) if x.endswith(".msb.dcx")):
        m = f[:-len(".msb.dcx")]
        raw, _hdr = M.dcx_payload(open(os.path.join(d, f), "rb").read())
        _v, blocks = M.walk_params(raw)
        par = [b for b in blocks if b["name"] == "PARTS_PARAM_ST"]
        if not par:
            continue
        mdl = [b for b in blocks if b["name"] == "MODEL_PARAM_ST"]
        models = M.read_models(raw, mdl[0]) if mdl else {}
        for off in par[0]["entry_offsets"]:
            e = M.read_enemy(raw, off, models)
            if not e or e.get("type", 2) != 2:
                continue
            seen[(m, e["part_name"])] += 1
            out.append({
                "map": m,
                "part_name": e["part_name"],
                "occurrence": seen[(m, e["part_name"])],
                "entity_id": e["entity_id"] or 0,
                "npc_id": e["npc_id"] or 0,
                "think_id": e.get("think_id") or 0,
                "chara_id": e.get("chara_id") or 0,
                "model": e["model"] or "",
                "x": "%.3f" % (e.get("x") or 0.0),
                "y": "%.3f" % (e.get("y") or 0.0),
                "z": "%.3f" % (e.get("z") or 0.0),
            })
    return out


_BAR_RE = re.compile(r"DisplayBossHealthBars*(([^)]*))")
_INIT_RE = re.compile(r"Initialize(?:Common)?Events*(([^)]*))")
_CONST_RE = re.compile(r"^s*(?:const|let|var)s+([A-Za-z_][A-Za-z0-9_]*)s*=s*(-?d+)s*;", re.M)
# 会显示 Boss 血条的共用事件模板：野外 Boss / 黄金树传送门 / 法魂自定义野外 Boss
_BAR_TEMPLATE_IDS = ("90005870", "90005876", "90005873", "90005863")


def event_dir():
    import enemy_randomizer as ER
    mod = ER._mod_reg()
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(mod))), "mod", "event")


def _ent_of(tok, consts):
    tok = (tok or "").strip()
    if tok.isdigit():
        return int(tok)
    return consts.get(tok)


def scan_bars():
    """(map, entity_id) 集合：这个位置本来就有 Boss 血条事件。

    血条属于**位置的 EMEVD**，不属于模型/NpcParam（315 个字段里没有任何"显示血条"）。
    所以换人后血条还在原位置；但如果该位置被换成普通杂兵，玩家就看到"原本的 Boss 战变成路人"。
    记进位置表的 bar 列后，规则表可以据此强制换入 boss 级（见 yaml 的 bossbar_position）。

    两种来源（实测 267 个 event js）：
      ① 地图事件直接调用 DisplayBossHealthBar(Enabled, <实体>, 槽, 名字)，实体是数字或同文件 const；
      ② 模板调用 Initialize(Common)Event(0, 9000587x, <实体>, ...)：模板在 common_func 里按参数显示血条。
    common*.js 是共享模板（实体参数是 X0_4 变量），不落到具体地图，跳过。
    """
    d = event_dir()
    bars = set()
    if not os.path.isdir(d):
        print("  ! 找不到 %s：bar 列全部按 0 处理" % d)
        return bars
    for fn in sorted(x for x in os.listdir(d) if x.endswith(".js")):
        stem = fn.split(".emevd")[0]
        if stem.startswith("common"):
            continue
        txt = io.open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
        consts = {k: int(v) for k, v in _CONST_RE.findall(txt)}
        for m in _BAR_RE.finditer(txt):
            parts = [p.strip() for p in m.group(1).split(",")]
            if len(parts) < 2:
                continue
            ent = _ent_of(parts[1], consts)
            if ent:
                bars.add((stem, ent))
        for m in _INIT_RE.finditer(txt):
            parts = [p.strip() for p in m.group(1).split(",")]
            idx = [i for i, p in enumerate(parts) if p in _BAR_TEMPLATE_IDS]
            if not idx:
                continue
            for p in parts[idx[0] + 1:]:
                ent = _ent_of(p, consts)
                if ent:
                    bars.add((stem, ent))
                    break
    return bars


def attach_bars(rows, bars=None):
    """给每行打 bar 标记（entity_id=0 的位置不可能有血条事件，因为 EMEVD 靠实体 ID 点名）。"""
    bars = scan_bars() if bars is None else bars
    n = 0
    for r in rows:
        e = int(r["entity_id"] or 0)
        r["bar"] = "1" if e and (r["map"], e) in bars else "0"
        if r["bar"] == "1":
            n += 1
    return n, len(bars)


_PAIR_RE = re.compile(r"CreateReferredDamagePair\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_ANIM_RE = re.compile(r"ForceAnimationPlayback\s*\(\s*(\d+)\s*,")
_COPY_RE = re.compile(r"CopyPlayerCharacterData\s*\(\s*10000\s*,\s*(\d+)\s*\)")
_AIID_RE = re.compile(r"SetCharacterAIId\s*\(\s*(\d+)\s*,")
_EVT_ORDER = ("pair", "copy", "aiid", "anim")


def scan_events():
    """{(map, entity_id): "pair;anim;..."} —— 被 EMEVD 脚本绑死的实体。

    这些实体不能按普通敌人换模型（实测踩坑）：
      pair  CreateReferredDamagePair(a,b)：坐骑/受击绑定对（如安塞尔河传送门的诺克斯虫骑）。
            只换其中一只、或换成非坐骑模型 → 加载/生成时崩游戏（2026-10-21 坏档的根因）。
      anim  ForceAnimationPlayback(实体, 动画)：脚本给这个实体强制播待机/起身/阶段动画。
            换模型后动画槽对不上 → 站着不动（禁域传送门的玛尔基特就是这样）。
      copy  CopyPlayerCharacterData(10000, 实体)：外观被事件覆盖成玩家，换模型看不到。
      aiid  SetCharacterAIId(实体, AI)：AI 被脚本换成特定行为树，换模型后可能原地发呆。
    """
    d = event_dir()
    out = collections.defaultdict(set)
    if not os.path.isdir(d):
        print("  ! 找不到 %s：evt 列全部留空" % d)
        return out
    for fn in sorted(x for x in os.listdir(d) if x.endswith(".js")):
        stem = fn.split(".emevd")[0]
        if stem.startswith("common"):
            continue
        txt = io.open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
        for m in _PAIR_RE.finditer(txt):
            for x in m.groups():
                if int(x):
                    out[(stem, int(x))].add("pair")
        for m in _ANIM_RE.finditer(txt):
            if int(m.group(1)):
                out[(stem, int(m.group(1)))].add("anim")
        for m in _COPY_RE.finditer(txt):
            if int(m.group(1)):
                out[(stem, int(m.group(1)))].add("copy")
        for m in _AIID_RE.finditer(txt):
            if int(m.group(1)):
                out[(stem, int(m.group(1)))].add("aiid")
    return out


def _evt_blocks(r, pools=None):
    """这个位置的脚本绑定是否真的不允许换模型。

    pair/copy/aiid：结构性绑定（坐骑对、外观复制、脚本 AI）——换就崩或失效，必须 keep。
    anim：只是脚本会点名播某段动画。绝大多数具名 Boss 的入场/死亡动画都是这样，
          一律 keep 会把大半个 Boss 池排除掉；只有**传送门守门位**的强制姿态
          （休眠 30000 / 起身 20000）换模型后 AI 不起，才 keep。
    """
    flags = set((r.get("evt") or "").split(";"))
    if "pair" in flags:
        return True
    # copy（CopyPlayerCharacterData）与 aiid（SetCharacterAIId）不一律 keep：
    # 用户已确认「梦之灾厄」哥拉斯可以随掉；实测换模型后仍能战斗。
    # 真正会崩的是坐骑/受击对（pair）与「传送门守门位的强制姿态」（anim + waygate）。
    return "anim" in flags and "waygate" in ((r.get("pools") or "") if pools is None else pools)


def attach_events(rows, evts=None):
    """给每行打脚本绑定标记（entity_id=0 的位置 EMEVD 点不到，留空）。"""
    evts = scan_events() if evts is None else evts
    n = 0
    for r in rows:
        e = int(r["entity_id"] or 0)
        flags = evts.get((r["map"], e)) if e else None
        r["evt"] = ";".join(x for x in _EVT_ORDER if x in flags) if flags else ""
        if r["evt"]:
            n += 1
    return n, len(evts)


def parse_ref(path):
    """解析参考实现 enemy.txt 的 Enemies 块 -> ({(map,name): cls}, {model: Counter})。"""
    if not os.path.exists(path):
        raise SystemExit("找不到参考基线：%s\n可以用 --ref 指定，或先不建表。" % path)
    lines = io.open(path, encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "Enemies:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^[A-Za-z]", lines[i]) and not lines[i].startswith(" "):
            end = i
            break
    by_name = {}
    model_cls = collections.defaultdict(collections.Counter)
    cur = {}
    def flush():
        if cur.get("map") and cur.get("name"):
            if cur.get("cls"):
                model_cls[cur["name"].rsplit("_", 1)[0]][cur["cls"]] += 1
                by_name.setdefault((cur["map"], cur["name"]), {
                    "cls": cur["cls"],
                    "size": int(cur.get("size") or 0),
                    "arena": int(cur.get("arena") or 0),
                })
    for l in lines[start:end]:
        m = _ENT_RE.match(l)
        if m:
            flush(); cur = {}; continue
        m = _MAP_RE.match(l)
        if m and "map" not in cur: cur["map"] = m.group(1); continue
        m = _NAME_RE.match(l)
        if m and "name" not in cur: cur["name"] = m.group(1); continue
        m = _CLS_RE.match(l)
        if m and "cls" not in cur: cur["cls"] = m.group(1); continue
        m = _TAGS_RE.match(l)
        if m:
            for k, v in _TAG_NUM_RE.findall(m.group(1)):
                cur[k] = int(v)
    flush()
    return by_name, model_cls


def attach_classes(rows, ref_path):
    by_name, model_cls = parse_ref(ref_path)
    ctr = collections.Counter()
    for r in rows:
        key = (r["map"], r["part_name"])
        ref = by_name.get(key)
        if ref:
            r["cls"] = ref["cls"]; r["cls_src"] = "exact"
            r["ref_size"] = ref.get("size") or 0
            r["ref_arena"] = ref.get("arena") or 0
        else:
            mc = model_cls.get(r["model"])
            if mc:
                r["cls"] = mc.most_common(1)[0][0]; r["cls_src"] = "model"
            else:
                r["cls"] = ""; r["cls_src"] = "unknown"
            r["ref_size"] = 0
            r["ref_arena"] = 0
        ctr[r["cls_src"]] += 1
    return ctr


# ── 分类/政策层（enemy_classes_v3.yaml）─────────────────────────────────────

def load_cfg(path=None):
    """读分类配置。缺文件就报清楚（它的产物是位置表的后 6 列，缺了不该静默继续）。"""
    import yaml
    p = path or YAML_PATH
    if not os.path.exists(p):
        raise SystemExit("找不到分类配置：%s" % p)
    with io.open(p, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for k in ("l1_classes", "l2_silo", "l3_tier", "l4_policy"):
        if k not in cfg:
            raise SystemExit("分类配置缺 %s：%s" % (k, p))
    # 类合并表（class_aliases）：目标是合并后的现行类，必须已定义；源是旧类名，允许已删除。
    for src, dst in (cfg.get("class_aliases") or {}).items():
        if dst not in cfg["l1_classes"]:
            raise SystemExit("class_aliases 的目标类未定义：%s → %s" % (src, dst))
        if src in (cfg.get("class_aliases") or {}).values():
            raise SystemExit("class_aliases 不允许链式合并：%s → %s" % (src, dst))
    return cfg


def load_npc_stats():
    """npc_id(NpcParam row_id) -> (hp, get_soul)。缺表就返回空（那样所有位置都会被 keep）。"""
    p = os.path.join(INV, "enemy_table.csv")
    d = {}
    if not os.path.exists(p):
        return d
    for r in csv.DictReader(io.open(p, encoding="utf-8-sig", newline="")):
        try:
            rid = int(r["row_id"])
        except (ValueError, KeyError):
            continue
        def _i(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0
        d[rid] = (_i(r.get("hp")), _i(r.get("get_soul")))
    return d


def load_healthbar_names():
    """(map, entity_id) -> set(血条名)。这是"这模型是不是 Boss"的证据（血条名只有 Boss 有）。"""
    p = os.path.join(INV, "boss_healthbar.csv")
    d = collections.defaultdict(set)
    if not os.path.exists(p):
        return d
    for r in csv.DictReader(io.open(p, encoding="utf-8-sig", newline="")):
        try:
            k = (r["map"].strip(), int(r["entity"]))
        except (ValueError, KeyError):
            continue
        n = (r.get("name") or "").strip()
        if n:
            d[k].add(n)
    return d


def _area_of(map_id, prefixes):
    return "dlc" if map_id.split("_")[0] in prefixes else "base"


def apply_layer(rows, cfg, npc=None):
    """把 yaml 的分类/政策/池/强度档落到每个位置上（写 cls/area/silo/tier/policy/pools/note）。"""
    npc = npc if npc is not None else load_npc_stats()
    prefixes = set(cfg["l2_silo"].get("dlc_map_prefixes") or [])
    classes = cfg["l1_classes"] or {}
    pol = cfg["l4_policy"] or {}
    keep_models = set(pol.get("keep_models") or [])
    keep_maps = set(pol.get("keep_maps") or [])
    keep_npcs = set(int(k) for k in (pol.get("keep_npc_ids") or {}))
    never_npcs = set(int(k) for k in (pol.get("never_touch_npc_ids") or {}))
    # keep_places 支持两种写法：按主键 (map, part_name, occurrence) 或按实体 (map, entity)
    keep_places = set()
    keep_entities = {}
    for x in (pol.get("keep_places") or []):
        if "entity" in x:
            keep_entities[(x["map"], int(x["entity"]))] = x.get("reason", "keep_places")
        else:
            keep_places.add((x["map"], x["part_name"], int(x.get("occurrence", 1))))
    ov = cfg.get("overrides") or {}
    ov_models = ov.get("models") or {}
    ov_places = {(x["map"], x["part_name"], int(x.get("occurrence", 1))): x
                 for x in (ov.get("places") or [])}
    # 多阶段 Boss：一场战斗的两阶段，v1 一律 keep（证据见 M0 报告 §5.2）
    mp_of = {}
    for grp in ((cfg.get("multiphase") or {}).get("groups") or []):
        for ent in (grp.get("phases") or []):
            mp_of[(grp["map"], int(ent))] = grp.get("id", "multiphase")

    # 模型级兜底类：位置表里 cls 为空的模型（参考基线没有它们）
    hb = load_healthbar_names()
    model_rows = collections.defaultdict(list)
    for r in rows:
        model_rows[r["model"]].append(r)
    defaults = {}
    for model, rs in model_rows.items():
        cl = collections.Counter(r["cls"] for r in rs if r["cls"])
        if model in ov_models and ov_models[model].get("class"):
            defaults[model] = (ov_models[model]["class"], "yaml")
        elif cl:
            defaults[model] = (cl.most_common(1)[0][0], "ref")
        elif model in keep_models:
            defaults[model] = ("Dummy", "auto:dummy")
        elif any(hb.get((r["map"], int(r["entity_id"] or 0))) for r in rs):
            defaults[model] = ("Boss", "auto:bossbar")   # 有血条名 = Boss 级
        else:
            # 法魂新增的无名杂兵：统一名「法魂杂兵（cXXXX）」，2026-10-24 起并入 Basic
            defaults[model] = ("Basic", "auto:noname")

    # 池成员：(map, entity_id) -> [pool id]
    pool_of = collections.defaultdict(list)
    for p in cfg.get("pools") or []:
        if p.get("status") != "ready":
            continue
        for m in p.get("members") or []:
            pool_of[(m["map"], int(m["entity"]))].append(p["id"])

    ctr = collections.Counter()
    by_silo = collections.defaultdict(list)      # silo -> [(row 下标, hp, soul)]
    for i, r in enumerate(rows):
        m, model = r["map"], r["model"]
        r["area"] = _area_of(m, prefixes)
        ovc = (ov_models.get(model) or {}).get("class")
        if ovc:
            r["cls"], r["cls_src"] = ovc, "yaml"
        elif not r["cls"]:
            r["cls"], r["cls_src"] = defaults[model]
        # 类合并（yaml.class_aliases）：旧类名 → 现行类名。法魂无名杂兵 Mob 并入 Basic。
        _alias = (cfg.get("class_aliases") or {}).get(r["cls"])
        if _alias:
            r["cls"], r["cls_src"] = _alias, "alias:%s" % r["cls_src"]
        cls = r["cls"]
        try:
            npc_id = int(r["npc_id"])
        except (TypeError, ValueError):
            npc_id = 0
        hp, soul = npc.get(npc_id, (0, 0))
        key = (m, r["part_name"], int(r["occurrence"]))
        c = classes.get(cls)
        reason = ""
        if key in ov_places and (ov_places[key].get("policy") or ov_places[key].get("reason")):
            policy = ov_places[key].get("policy", "keep")
            reason = ov_places[key].get("reason", "overrides.places")
        elif npc_id in never_npcs:
            # 传送门本体物件：换掉它那扇门就永久失效，这一条优先于类别判定
            policy, reason = "keep", "never_touch_npc_ids"
        elif (m, int(r["entity_id"] or 0)) in mp_of:
            # 多阶段 Boss：只换一阶段会留下"半只 Boss"，v1 整组不动
            policy, reason = "keep", "multiphase:%s" % mp_of[(m, int(r["entity_id"] or 0))]
        elif _evt_blocks(r, pool_of[(m, int(r["entity_id"] or 0))]):
            # 被 EMEVD 脚本绑死的实体：坐骑/受击对、强制动画、外观复制、脚本 AI。
            # 换模型会崩游戏或让 AI 失效（2026-10-21 安塞尔河坏档 / 禁域玛尔基特没 AI 的根因）。
            # anim 不一律 keep：绝大多数具名 Boss 的入场/死亡动画也会被脚本点名，
            # 一律 keep 会把 55 个 Boss 排除出随机；只有「传送门守门位 + 强制姿态」
            # （休眠/起身那套）才必须保持原模型。
            policy, reason = "keep", "evt:%s" % r["evt"]
        elif model == "c0000":
            # MSB 里的 c0000 part 是"空壳"：真正的身体由事件/生成器按 npc_id 另配（永恒监牢、
            # 部分 DLC Boss、入侵者等）。换它的 npc 要么无效、要么换掉一个玩家根本看不见的对象，
            # 反过来（把它当捐赠者）也会换进一只空壳 —— 两边都不碰。
            policy, reason = "keep", "占位模型 c0000（真身由事件生成）"
        elif _SOUND_RE.search(r["part_name"]):
            # MSB 里有专门的声音/演出占位 part（如 "c5300 Rellana Twin Moon Knight Sound"）：
            # 它带 Boss 的 npc/think，但舞台上并不战斗。当成敌人换掉/拿来当捐赠者，
            # 换来的可能是个不出手、甚至不落地的空壳 —— 直接 keep。
            policy, reason = "keep", "声音/演出占位（非战斗实体）"
        elif c is None:
            policy, reason = "keep", "类别不在 l1_classes 里：%s" % (cls or "(空)")
        elif not c.get("silo"):
            policy, reason = "keep", "class.silo=false"
        elif model in keep_models:
            policy, reason = "keep", "keep_models"
        elif m in keep_maps:
            policy, reason = "keep", "keep_maps"
        elif npc_id in keep_npcs:
            policy, reason = "keep", "keep_npc_ids"
        elif key in keep_places:
            policy, reason = "keep", "keep_places"
        elif (m, int(r["entity_id"] or 0)) in keep_entities:
            policy, reason = "keep", "keep_places:%s" % keep_entities[(m, int(r["entity_id"] or 0))]
        elif not hp:
            policy, reason = "keep", "取不到数值：不碰"
        else:
            policy = "randomize"
        r["policy"] = policy
        r["silo"] = ("%s|%s" % (cls, r["area"])) if policy == "randomize" else ""
        r["tier"] = ""
        pp = pool_of.get((m, int(r["entity_id"] or 0)))
        r["pools"] = "|".join(sorted(set(pp))) if pp else ""
        r["note"] = reason

    # 重复 MSB（已封印/未封印两份）：同一物理位置必须同政策，否则同一地点两种状态看到不同的敌人。
    # 保守取 keep —— 参考基线常把副本那一份标成 None/Helper（它只认其中一张图），不能据此去换另一半。
    n_unified = 0
    by_link = collections.defaultdict(list)
    for r in rows:
        if r.get("link"):
            by_link[r["link"]].append(r)
    for lid, g in by_link.items():
        if len(set(x["policy"] for x in g)) > 1:
            n_unified += 1
            for x in g:
                x["policy"] = "keep"
                x["silo"] = ""
                x["note"] = "link:副本政策不一致，保守 keep（%s）" % lid

    ctr = collections.Counter()
    by_silo = collections.defaultdict(list)
    for i, r in enumerate(rows):
        ctr[r["policy"]] += 1
        if r["policy"] == "randomize":
            hp, soul = npc.get(int(r["npc_id"] or 0), (0, 0))
            by_silo[r["silo"]].append((i, hp, soul))

    # 强度档：silo 内复合分位（hp 0.75 / get_soul 0.25）→ tier 1..4
    for _silo, items in by_silo.items():
        n = float(len(items))
        hps = sorted(math.log10(max(h, 1)) for _i, h, _s in items)
        souls = sorted(math.log10(max(s, 1)) for _i, _h, s in items)
        for i, h, s in items:
            rh = bisect.bisect_right(hps, math.log10(max(h, 1))) / n
            rs = bisect.bisect_right(souls, math.log10(max(s, 1))) / n
            sc = 0.75 * rh + 0.25 * rs
            rows[i]["tier"] = str(min(4, 1 + int(max(0.0, sc - 1e-9) * 4)))

    return {"policy": ctr, "link_unified": n_unified,
            "silo": collections.Counter(r["silo"] for r in rows if r["silo"]),
            "tier": collections.Counter(r["tier"] for r in rows if r["tier"]),
            "pools": collections.Counter(r["pools"] for r in rows if r["pools"])}


_LINK_PREFIX_RE = re.compile(r"^m\d\d_\d\d_\d\d_\d\d-")
_SOUND_RE = re.compile(r"\bSound\b", re.I)


def link_key(r):
    """"同一物理位置的两份 MSB"的判据：part 名去掉图名前缀 + 坐标(0.1) + entity_id。

    实测 2,124 组 / 4,248 行，每组恰好 2 行、跨 2 张图（…_00 / …_10，"已封印/未封印"），
    没有同图重复、没有跨 3 张图的组。→ 27,780 行 = 25,656 个物理位置。
    """
    return (_LINK_PREFIX_RE.sub("", r["part_name"]),
            round(float(r["x"]), 1), round(float(r["y"]), 1), round(float(r["z"]), 1),
            str(r["entity_id"]))


def assign_links(rows):
    """给同一物理位置的两行打同一个 link 号（L0001…）。M1 必须把它们当一个目标：**同步替换**。"""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[link_key(r)].append(r)
    n = 0
    for k in sorted(groups):
        g = groups[k]
        if len(g) < 2:
            for r in g:
                r["link"] = ""
            continue
        n += 1
        for r in g:
            r["link"] = "L%04d" % n
    return n, sum(len(g) for g in groups.values() if len(g) > 1)


_CLS_SRC_RANK = {"exact": 0, "model": 1}


def unify_link_classes(rows):
    """同一物理位置的两份 MSB 必须是同一个类。

    实测有 6 组冲突：一份 part 名在参考表里命中（exact，如 Miniboss），另一份因为 part 名
    带图名前缀没命中、回退到模型多数类（Basic）。同一实体不可能既是 Boss 又是杂兵 ——
    exact 胜出，整组统一。否则 M1 会把一个物理位置拆成两个 silo 的候选，写出来必然一半新一半旧。
    """
    groups = collections.defaultdict(list)
    for r in rows:
        if r.get("link"):
            groups[r["link"]].append(r)
    n_fixed = 0
    for link, g in groups.items():
        if len({r["cls"] for r in g}) <= 1:
            continue
        best = sorted(g, key=lambda r: (_CLS_SRC_RANK.get(r["cls_src"], 9), r["cls"]))[0]
        for r in g:
            if r["cls"] != best["cls"]:
                r["cls"] = best["cls"]
                r["cls_src"] = best["cls_src"]
                n_fixed += 1
    return n_fixed


def write_table(rows):
    with io.open(TABLE, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_table():
    with io.open(TABLE, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _padded(model):
    d = model[1:]
    return "c" + d.zfill(4) if d.isdigit() else model


def load_name_tables(names_dir=None):
    """读参考实现的 diste/Names（ModelName.txt / ModelNameNT.txt）。"""
    names_dir = names_dir or NAMES_DIR
    def load(fn):
        d = {}
        p = os.path.join(names_dir, fn)
        if not os.path.exists(p):
            return d
        for ln in io.open(p, encoding="utf-8", errors="replace"):
            k, _, v = ln.rstrip("\n").partition(" ")
            if k.strip():
                d[k.strip()] = v.strip()
        return d
    return load("ModelName.txt"), load("ModelNameNT.txt")


def build_model_names(rows=None):
    """把位置表汇总成"模型级"表：名字 + 类 + 是否参与随机。

    名字优先级：血条名（中文，Boss 才有）-> 参考实现 ModelName -> ModelNameNT
    -> 统一名 GENERIC_NAME（照参考实现 GameData.ModelName 的兜底）。
    无名杂兵不卡住：给统一名、归到 L1 类 Mob（只在彼此之间互换）。
    """
    if rows is None:
        rows = read_table()
    mn, mnt = load_name_tables()
    npc = {}
    p = os.path.join(INV, "enemy_table.csv")
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig", newline="")):
            try:
                npc[int(r["row_id"])] = r
            except (ValueError, KeyError):
                pass
    hb = collections.defaultdict(set)
    p = os.path.join(INV, "boss_healthbar.csv")
    if os.path.exists(p):
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig", newline="")):
            try:
                hb[(r["map"].strip(), int(r["entity"]))].add(r.get("name", "").strip())
            except (ValueError, KeyError):
                pass
    agg = collections.OrderedDict()
    for r in rows:
        a = agg.setdefault(r["model"], {"n": 0, "cls": collections.Counter(),
                                        "src": collections.Counter(),
                                        "pol": collections.Counter(), "note": [],
                                        "hp": [], "boss": set(), "hb": set(),
                                        "rows": set()})
        a["n"] += 1
        a["cls"][r["cls"] or ""] += 1
        a["src"][r["cls_src"] or ""] += 1
        a["pol"][r["policy"] or ""] += 1
        if r.get("note"):
            a["note"].append(r["note"])
        a["hb"] |= {x for x in hb.get((r["map"], int(r["entity_id"])), set()) if x}
        try:
            t = npc.get(int(r["npc_id"]))
        except ValueError:
            t = None
        if t:
            a["rows"].add(r["npc_id"])
            if t.get("hp"):
                a["hp"].append(t["hp"])
            if t.get("is_boss"):
                a["boss"].add(t["is_boss"])
    out = []
    for model, a in agg.items():
        hbn = sorted(a["hb"])
        mname = mn.get(model) or mn.get(_padded(model)) or ""
        if not mname:
            ntn = mnt.get(model) or mnt.get(_padded(model)) or ""
            name, src = (ntn, "ModelNameNT") if ntn else ("", "")
        else:
            name, src = mname, "ModelName"
        if hbn:
            name, src = hbn[0], "血条名"
            if len(hbn) > 1:
                src = "血条名(多: %d)" % len(hbn)
        if model in NAME_OVERRIDES:
            name, src = NAME_OVERRIDES[model], "人工指定"
        elif model in KEEP_NAMES:
            name, src = "%s（%s）" % (KEEP_NAMES[model], model), "人工指定"
        elif not name:
            name, src = GENERIC_NAME % model, "generic"
        hps = sorted(int(h) for h in a["hp"] if str(h).isdigit()) or [0]
        # 类 / 政策 / 备注一律以位置表的最终判定为准（yaml 覆盖已经落到位置上）
        cls = a["cls"].most_common(1)[0][0] if a["cls"] else ""
        srcs = [s for s in a["src"] if s]
        cls_src = srcs[0] if srcs else "unknown"
        policy = a["pol"].most_common(1)[0][0] if a["pol"] else ""
        note = a["note"][0] if a["note"] else ""
        out.append({"model": model, "display_name": name, "name_src": src,
                    "cls": cls, "cls_src": cls_src, "placements": a["n"],
                    "npc_rows": len(a["rows"]), "hp_min": hps[0], "hp_max": hps[-1],
                    "boss_any": "1" if a["boss"] else "0", "policy": policy,
                    "note": note})
    out.sort(key=lambda x: (-x["placements"], x["model"]))
    with io.open(MODEL_TABLE, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MODEL_COLS)
        w.writeheader()
        for r in out:
            w.writerow(r)
    srcs = collections.Counter(r["name_src"] for r in out)
    pols = collections.Counter(r["policy"] for r in out)
    print("wrote %s (%d models)" % (MODEL_TABLE, len(out)))
    print("name_src:", dict(srcs))
    print("policy:", dict(pols))
    print("generic(%s): %s" % (GENERIC_NAME % "cXXXX",
          [r["model"] for r in out if r["name_src"] == "generic"]))
    return out


def stats(rows):
    print("places: %d  maps: %d" % (len(rows), len(set(r["map"] for r in rows))))
    n_ent = sum(1 for r in rows if int(r["entity_id"]))
    print("entity_id>0: %d  (%.1f%%)" % (n_ent, 100.0 * n_ent / max(1, len(rows))))
    print("cls_src:", dict(collections.Counter(r["cls_src"] for r in rows)))
    print("cls:", collections.Counter(r["cls"] or "(空)" for r in rows).most_common())
    if rows and "policy" in rows[0]:
        print("policy:", dict(collections.Counter(r["policy"] for r in rows)))
        print("area:", dict(collections.Counter(r["area"] for r in rows)))
        print("silo:", collections.Counter(r["silo"] for r in rows if r["silo"]).most_common())
        print("tier:", dict(sorted(collections.Counter(r["tier"] for r in rows if r["tier"]).items())))
        pl = collections.Counter()
        for r in rows:
            for p in (r["pools"] or "").split("|"):
                if p:
                    pl[p] += 1
        print("pools:", dict(pl))
        print("link: %d 行有 link（= 2 × %d 组重复 MSB）" % (
            sum(1 for r in rows if r.get("link")), sum(1 for r in rows if r.get("link")) // 2))
        print("evt:", dict(collections.Counter(r.get("evt") or "(无)" for r in rows)))
        print("randomize 覆盖: %d 个位置 / %d 个 silo" % (
            sum(1 for r in rows if r["policy"] == "randomize"),
            len(set(r["silo"] for r in rows if r["silo"]))))
    unk = collections.Counter(r["model"] for r in rows if r["cls_src"] == "unknown")
    if unk:
        print("异常：还有 %d 个模型没定类: %s" % (len(unk), unk.most_common()))



def build(ref_path, yaml_path=None):
    cfg = load_cfg(yaml_path)
    rows = scan_places()
    nbar, nbar_pos = attach_bars(rows)              # Boss 血条位置（规则表按它强制 boss 级候选）
    nevt, nevt_pos = attach_events(rows)            # 脚本绑死的实体（成对/强制动画/复制外观/脚本 AI）
    ctr = attach_classes(rows, ref_path)
    nlink, nlink_rows = assign_links(rows)          # 先算 link：政策要按"同一物理位置"统一
    n_cls = unify_link_classes(rows)                # 再统一类：exact 优先，同一实体不能两个类
    lay = apply_layer(rows, cfg)
    print("linked MSB: %d 组 / %d 行 → 物理位置 %d（政策统一改判 %d 组，类统一改判 %d 行）" % (
        nlink, nlink_rows, len(rows) - nlink, lay["link_unified"], n_cls))
    print("Boss 血条: %d 个 (map,entity) 有血条事件 → 命中 %d 个位置行（bar=1）" % (nbar_pos, nbar))
    print("脚本绑定: %d 个 (map,entity) 被 EMEVD 绑定（pair/anim/copy/aiid）→ 命中 %d 个位置行（evt 非空）" % (nevt_pos, nevt))
    write_table(rows)
    print("wrote %s (%d rows)" % (TABLE, len(rows)))
    print("cls_src:", dict(ctr))
    print("policy:", dict(lay["policy"]))
    stats(rows)
    build_model_names(rows)
    return 0


def _read_model_table():
    if not os.path.exists(MODEL_TABLE):
        return {}
    return {r["model"]: r for r in csv.DictReader(
        io.open(MODEL_TABLE, encoding="utf-8-sig", newline=""))}


def check(yaml_path=None):
    """严格校验：磁盘 ↔ 位置表 ↔ 分类配置 ↔ 模型名字表 四处必须自洽。

    任何一条对不上都是 FAIL —— M1 的运行期只信这张表，它错了后面全错。
    """
    cfg = load_cfg(yaml_path)
    fails = []
    warns = lambda m: print("  ! " + m)

    if not os.path.exists(TABLE):
        print("缺少 %s，先跑 --build" % TABLE)
        return 2

    # ① 磁盘 ↔ 位置表
    disk = {(r["map"], r["part_name"], int(r["occurrence"])): r for r in scan_places()}
    tab = {(r["map"], r["part_name"], int(r["occurrence"])): r for r in read_table()}
    missing = sorted(set(disk) - set(tab))
    extra = sorted(set(tab) - set(disk))
    drift = []
    for k in sorted(set(disk) & set(tab)):
        for col in ("entity_id", "npc_id", "model"):
            if str(disk[k][col]) != str(tab[k][col]):
                drift.append((k, col, tab[k][col], disk[k][col]))
                break
    print("disk parts=%d  table rows=%d  maps=%d" % (
        len(disk), len(tab), len(set(r["map"] for r in tab.values()))))
    if missing:
        fails.append("磁盘上有 %d 个 part 表里没有，例：%s" % (len(missing), missing[:5]))
    if extra:
        fails.append("表里有 %d 个 part 磁盘上没有（陈旧行），例：%s" % (len(extra), extra[:5]))
    if drift:
        fails.append("字段漂移 %d 处（表值≠磁盘值），例：%s" % (len(drift), drift[:3]))

    # ①b Boss 血条列（bar）：必须与磁盘上的 EMEVD 现算结果一致
    bars = scan_bars()
    bar_mismatch = []
    for r in tab.values():
        e = int(r["entity_id"] or 0)
        want = "1" if e and (r["map"], e) in bars else "0"
        if (r.get("bar") or "0") != want:
            bar_mismatch.append((r["map"], r["part_name"], r.get("bar"), want))
    n_bar = sum(1 for r in tab.values() if (r.get("bar") or "0") == "1")
    bar_cls = collections.Counter(r["cls"] for r in tab.values() if (r.get("bar") or "0") == "1")
    bar_pol = collections.Counter(r["policy"] for r in tab.values() if (r.get("bar") or "0") == "1")
    print("bar: %d 行有 Boss 血条（cls=%s / policy=%s）" % (n_bar, dict(bar_cls), dict(bar_pol)))
    if bar_mismatch:
        fails.append("bar 列与磁盘 EMEVD 不一致 %d 行，例：%s" % (
            len(bar_mismatch), bar_mismatch[:3]))

    # ①c 脚本绑定列（evt）：必须与磁盘 EMEVD 现算结果一致
    evts = scan_events()
    evt_mismatch = []
    for r in tab.values():
        e = int(r["entity_id"] or 0)
        flags = evts.get((r["map"], e)) if e else None
        want = ";".join(x for x in _EVT_ORDER if x in flags) if flags else ""
        if (r.get("evt") or "") != want:
            evt_mismatch.append((r["map"], r["part_name"], r.get("evt"), want))
    n_evt = sum(1 for r in tab.values() if (r.get("evt") or ""))
    evt_kind = collections.Counter()
    for r in tab.values():
        for x in (r.get("evt") or "").split(";"):
            if x:
                evt_kind[x] += 1
    evt_pol = collections.Counter(r["policy"] for r in tab.values() if (r.get("evt") or ""))
    print("evt: %d 行被脚本绑定（%s / policy=%s）" % (n_evt, dict(evt_kind), dict(evt_pol)))
    if evt_mismatch:
        fails.append("evt 列与磁盘 EMEVD 不一致 %d 行，例：%s" % (
            len(evt_mismatch), evt_mismatch[:3]))

    # ② 构建期断言（yaml.assertions）
    asrt = cfg.get("assertions") or {}
    if asrt.get("total_places") and len(tab) != asrt["total_places"]:
        fails.append("assertions.total_places=%s，实际 %d" % (asrt["total_places"], len(tab)))
    if asrt.get("distinct_maps") and len(set(r["map"] for r in tab.values())) != asrt["distinct_maps"]:
        fails.append("assertions.distinct_maps=%s，实际 %d" % (
            asrt["distinct_maps"], len(set(r["map"] for r in tab.values()))))

    # ③ 每行字段合法性
    allowed = set((cfg["l4_policy"] or {}).get("values") or [])
    allowed |= set(asrt.get("allowed_policy_values") or [])
    bad_cls = [r for r in tab.values() if not r.get("cls") or not r.get("cls_src")]
    if bad_cls:
        fails.append("有 %d 行没有类别（cls/cls_src 为空），例：%s" % (
            len(bad_cls), [(r["map"], r["part_name"]) for r in bad_cls[:3]]))
    unk = [r for r in tab.values() if r.get("cls_src") == "unknown"]
    if unk and asrt.get("no_unknown_class", True):
        fails.append("cls_src 仍是 unknown 的有 %d 行（模型级兜底没生效？）" % len(unk))
    bad_pol = [r for r in tab.values() if r["policy"] not in allowed]
    if bad_pol:
        fails.append("非法 policy %d 行，例：%s" % (
            len(bad_pol), [(r["map"], r["part_name"], r["policy"]) for r in bad_pol[:3]]))
    bad_silo = [r for r in tab.values() if (r["policy"] == "randomize") != bool(r["silo"])]
    if bad_silo:
        fails.append("silo 与 policy 不一致 %d 行（randomize ⇔ silo 非空）" % len(bad_silo))
    bad_tier = [r for r in tab.values()
                if r["policy"] == "randomize" and r["tier"] not in ("1", "2", "3", "4")]
    if bad_tier:
        fails.append("randomize 但有 %d 行没有 tier，例：%s" % (
            len(bad_tier), [(r["map"], r["part_name"]) for r in bad_tier[:3]]))
    bad_area = [r for r in tab.values()
                if r["policy"] == "randomize" and r["silo"].split("|")[-1] not in ("base", "dlc")]
    if bad_area:
        fails.append("silo 的区域段不是 base/dlc：%d 行" % len(bad_area))
    # ③a 类合并 / 内部类：别名源类不应再出现在表里；ui=false 的类必须全是 keep
    aliases = cfg.get("class_aliases") or {}
    stale_alias = sorted(set(r["cls"] for r in tab.values() if r["cls"] in aliases))
    if stale_alias:
        fails.append("位置表里还有旧类名（应为 %s）：%s" % (
            {k: aliases[k] for k in stale_alias}, stale_alias))
    hidden = {c for c, v in (cfg["l1_classes"] or {}).items() if v and v.get("ui") is False}
    bad_hidden = [r for r in tab.values()
                  if r["cls"] in hidden and r["policy"] != "keep"]
    if bad_hidden:
        fails.append("内部标记类（ui=false）有 %d 行不是 keep，例：%s" % (
            len(bad_hidden), [(r["map"], r["part_name"], r["cls"], r["policy"])
                              for r in bad_hidden[:3]]))

    # ③b 随机化规则表（randomization.rules）：任意类 → 任意类的唯一开关
    classes = set((cfg.get("l1_classes") or {}).keys())
    pool_ids = set(p["id"] for p in (cfg.get("pools") or []))
    rules = (cfg.get("randomization") or {}).get("rules") or []
    if not rules:
        fails.append("randomization.rules 是空的：没有任何位置会被随机")
    seen_ids = set()
    for r in rules:
        rid = r.get("id")
        if not rid:
            fails.append("随机化规则缺少 id")
            continue
        if rid in seen_ids:
            fails.append("随机化规则 id 重复：%s" % rid)
        seen_ids.add(rid)
        t = r.get("targets") or {}
        tcls = t.get("cls")
        tcls = sorted(classes) if tcls == "all" else (tcls or [])
        if not tcls:
            fails.append("规则 %s 没有 targets.cls（写 \"all\" 表示全部类）" % rid)
        bad = [c for c in tcls if c not in classes]
        if bad:
            fails.append("规则 %s 的 targets.cls 有未定义的类：%s" % (rid, bad))
        bad = [c for c in ((r.get("match") or {}).get("cls") or []) if c not in classes]
        if bad:
            fails.append("规则 %s 的 match.cls 有未定义的类：%s" % (rid, bad))
        bad_keys = [k for k in (r.get("match") or {})
                    if k not in ("cls", "pools", "area", "tier", "bar", "multiphase")]
        if bad_keys:
            fails.append("规则 %s 的 match 有未知键（拼错了会静默不生效）：%s" % (rid, bad_keys))
        for key in ("bar", "multiphase"):
            if (r.get("match") or {}).get(key) not in (None, True, False):
                fails.append("规则 %s 的 match.%s 只能是 true/false：%s" % (
                    rid, key, (r.get("match") or {}).get(key)))
        rate = r.get("rate")
        if rate is not None and not (0.0 <= float(rate) <= 1.0):
            fails.append("规则 %s 的 rate 不在 0..1：%s" % (rid, rate))
        for key in ("match", "targets"):
            bad = [x for x in ((r.get(key) or {}).get("pools") or []) if x not in pool_ids]
            if bad:
                fails.append("规则 %s 的 %s.pools 有未定义的池：%s" % (rid, key, bad))
        areas = t.get("areas", "same")
        if isinstance(areas, str):
            if areas not in ("same", "any", "base", "dlc"):
                fails.append("规则 %s 的 targets.areas 非法：%s" % (rid, areas))
        else:
            bad = [a for a in areas if a not in ("base", "dlc")]
            if bad:
                fails.append("规则 %s 的 targets.areas 非法：%s" % (rid, bad))
        for key in ("hp_band", "clamp_hp", "clamp_soul"):
            v = r.get(key)
            if v is None:
                continue
            if not (isinstance(v, (list, tuple)) and len(v) == 2):
                fails.append("规则 %s 的 %s 必须写成 [lo, hi]：%s" % (rid, key, v))
                continue
            try:
                lo, hi = float(v[0]), float(v[1])
            except (TypeError, ValueError):
                fails.append("规则 %s 的 %s 不是数字：%s" % (rid, key, v))
                continue
            if not (0 < lo <= hi):
                fails.append("规则 %s 的 %s 非法（要 0 < lo <= hi）：%s" % (rid, key, v))

    # ③c 捐赠者黑名单（randomization.donor_deny）：模型必须真实存在，拼错就会静默失效
    deny = (cfg.get("randomization") or {}).get("donor_deny") or []
    known_models = set(r["model"] for r in tab.values())
    try:
        known_models |= set(_read_model_table().keys())
    except SystemExit:
        pass
    seen_deny = set()
    for item in deny:
        model = str(item.get("model") or "").strip()
        if not model:
            fails.append("donor_deny 里有一条没有 model")
            continue
        if model in seen_deny:
            fails.append("donor_deny 里模型重复：%s" % model)
        seen_deny.add(model)
        if model not in known_models:
            fails.append("donor_deny 的模型在位置表/模型表里找不到：%s" % model)
        if not str(item.get("reason") or "").strip():
            fails.append("donor_deny 的 %s 没有 reason（以后没人知道为什么禁）" % model)
    if deny:
        print("捐赠者黑名单: %d 个模型（%s）" % (len(deny), ", ".join(sorted(seen_deny))))

    # ③d 战斗 AI 兜底（randomization.ai_fallback）：模型必须存在、goal 必须正整数
    fallback = (cfg.get("randomization") or {}).get("ai_fallback") or []
    seen_fb = set()
    for item in fallback:
        model = str(item.get("model") or "").strip()
        if not model:
            fails.append("ai_fallback 里有一条没有 model")
            continue
        if model in seen_fb:
            fails.append("ai_fallback 里模型重复：%s" % model)
        seen_fb.add(model)
        if model not in known_models:
            fails.append("ai_fallback 的模型在位置表/模型表里找不到：%s" % model)
        try:
            goal = int(item.get("goal"))
        except (TypeError, ValueError):
            fails.append("ai_fallback 的 %s 没有合法的 goal：%r" % (model, item.get("goal")))
            continue
        if goal <= 0:
            fails.append("ai_fallback 的 %s goal 必须 > 0：%s" % (model, goal))
    if fallback:
        print("战斗 AI 兜底: %d 个模型（%s）" % (len(fallback), ", ".join(sorted(seen_fb))))

    # 每条 randomize 行都必须被至少一条规则接管（否则计划层会静默 no_rule 跳过）
    def _hit_pools(r):
        return set(x for x in r.get("pools", "").replace(";", "|").replace(",", "|").split("|") if x)

    uncovered = collections.Counter()
    for r in tab.values():
        if r["policy"] != "randomize":
            continue
        hit = None
        for rule in rules:
            m = rule.get("match") or {}
            if m.get("multiphase"):
                continue          # 只匹配多阶段组（keep 行），不参与 randomize 行覆盖
            mc = m.get("cls") or []
            if mc and r["cls"] not in mc:
                continue
            mp = m.get("pools") or []
            if mp and not (set(mp) & _hit_pools(r)):
                continue
            ma = m.get("area") or "any"
            if ma != "any" and r.get("area") != ma:
                continue
            if m.get("bar") and (r.get("bar") or "0") != "1":
                continue
            hit = rule
            break
        if hit is None:
            uncovered[r["cls"]] += 1
    if uncovered:
        fails.append("有 %d 行 randomize 没有任何规则接管（会被静默跳过）：%s" % (
            sum(uncovered.values()), dict(uncovered)))
    print("随机化规则: %d 条，覆盖 %d 行 randomize" % (
        len(rules), sum(1 for r in tab.values() if r["policy"] == "randomize")))

    # ④ 池：每个成员必须**恰好**对上一个位置，且 npc/model 与 yaml 一致
    for p in cfg.get("pools") or []:
        pid = p.get("id")
        if p.get("status") != "ready":
            warns("池 %s 未就绪（status=%s）：%s" % (pid, p.get("status"), p.get("name")))
            continue
        for m in p.get("members") or []:
            hit = [r for r in tab.values()
                   if r["map"] == m["map"] and int(r["entity_id"] or 0) == int(m["entity"])]
            if len(hit) != 1:
                fails.append("池 %s：%s/%s 在位置表里命中 %d 行（应为 1）" % (
                    pid, m["map"], m["entity"], len(hit)))
                continue
            r = hit[0]
            if "npc_id" in m and str(r["npc_id"]) != str(m["npc_id"]):
                fails.append("池 %s：%s/%s npc_id 表值 %s ≠ yaml %s" % (
                    pid, m["map"], m["entity"], r["npc_id"], m["npc_id"]))
            if "model" in m and r["model"] != m["model"]:
                fails.append("池 %s：%s/%s model 表值 %s ≠ yaml %s" % (
                    pid, m["map"], m["entity"], r["model"], m["model"]))
        for u in p.get("unresolved") or []:
            hit = [r for r in tab.values()
                   if r["map"] == u["map"] and int(r["entity_id"] or 0) == int(u["entity"])]
            if hit:
                fails.append("池 %s：unresolved 的 %s/%s 现在能在 MSB 找到（口径变了，改 yaml）" % (
                    pid, u["map"], u["entity"]))

    # ⑤ 政策互斥（keep 名单里的东西绝不能是 randomize）
    polcfg = cfg["l4_policy"] or {}
    keep_maps = set(polcfg.get("keep_maps") or [])
    keep_npcs = set(str(k) for k in (polcfg.get("keep_npc_ids") or {}))
    never_npcs = set(str(k) for k in (polcfg.get("never_touch_npc_ids") or {}))
    for r in tab.values():
        if r["map"] in keep_maps and r["policy"] != "keep":
            fails.append("keep_maps 里的 %s 有 randomize 行：%s" % (r["map"], r["part_name"]))
            break
    for r in tab.values():
        if r["npc_id"] in keep_npcs and r["policy"] == "randomize":
            fails.append("keep_npc_ids 的 %s 被标成 randomize：%s/%s" % (
                r["npc_id"], r["map"], r["part_name"]))
            break
    nt_rows = [r for r in tab.values() if r["npc_id"] in never_npcs]
    if not nt_rows:
        warns("never_touch_npc_ids 的 %s 在位置表里一个都没找到（口径变了？）"
              % sorted(never_npcs))
    for r in nt_rows:
        if r["policy"] != "keep":
            fails.append("never_touch_npc_ids 的 %s 被标成 %s（换它=传送门失效）：%s/%s" % (
                r["npc_id"], r["policy"], r["map"], r["part_name"]))
            break
    print("never_touch 命中: %d 行（必须全部 keep）" % len(nt_rows))

    # ⑤b 多阶段 Boss：一组两阶段都必须存在、且全部 keep（只换一阶段 = 半只 Boss）
    mp_groups = (cfg.get("multiphase") or {}).get("groups") or []
    seen_mp = {}
    for grp in mp_groups:
        gid, gmap = grp.get("id", "?"), grp.get("map")
        for ent in grp.get("phases") or []:
            k = (gmap, int(ent))
            if k in seen_mp:
                fails.append("多阶段组 %s 的 %s/%s 与 %s 重复" % (gid, gmap, ent, seen_mp[k]))
            seen_mp[k] = gid
            hit = [r for r in tab.values()
                   if r["map"] == gmap and int(r["entity_id"] or 0) == int(ent)]
            if not hit:
                fails.append("多阶段组 %s：%s/%s 在位置表里找不到（编号错了？）" % (gid, gmap, ent))
            for r in hit:
                if r["policy"] != "keep":
                    fails.append("多阶段组 %s：%s/%s 被标成 %s（只换一阶段=半只 Boss）" % (
                        gid, gmap, r["part_name"], r["policy"]))
                if grp.get("swap") and "pair" in (r.get("evt") or ""):
                    fails.append("多阶段组 %s 开了 swap，但 %s 有 CreateReferredDamagePair 绑定"
                                 "（整组换会重演安塞尔河坏档）：%s" % (
                                     gid, r["part_name"], r.get("evt")))
        if grp.get("swap") and str(grp.get("kind") or "phase") != "phase":
            fails.append("多阶段组 %s 开了 swap，但 kind=%s（只有 phase 组能整组换）" % (
                gid, grp.get("kind")))
    swap_n = sum(1 for g in mp_groups if g.get("swap"))
    print("multiphase: %d 组 / %d 个位置（必须全部 keep；其中 %d 组开了整组替换）"
          % (len(mp_groups), len(seen_mp), swap_n))

    # ⑤c 重复 MSB（已封印/未封印两份）：同一物理位置必须成组，且 link 列自洽
    kg = collections.defaultdict(list)
    for r in tab.values():
        kg[link_key(r)].append(r)
    embedded = {k: g for k, g in kg.items() if len(g) > 1}
    if asrt.get("linked_pairs") is not None and len(embedded) != asrt["linked_pairs"]:
        fails.append("assertions.linked_pairs=%s，实际 %d" % (asrt["linked_pairs"], len(embedded)))
    linked_rows = sum(len(g) for g in embedded.values())
    if asrt.get("linked_rows") is not None and linked_rows != asrt["linked_rows"]:
        fails.append("assertions.linked_rows=%s，实际 %d" % (asrt["linked_rows"], linked_rows))
    phys = len(tab) - linked_rows // 2
    if asrt.get("physical_positions") is not None and phys != asrt["physical_positions"]:
        fails.append("assertions.physical_positions=%s，实际 %d" % (
            asrt["physical_positions"], phys))
    bad_link = []
    for k, g in embedded.items():
        maps = set(r["map"] for r in g)
        if len(g) != 2 or len(maps) != 2:
            bad_link.append((g[0]["map"], g[0]["part_name"], len(g), len(maps)))
        elif len(set(r.get("link") for r in g)) != 1 or not g[0].get("link"):
            bad_link.append((g[0]["map"], g[0]["part_name"], "link 不一致或为空"))
    if bad_link:
        fails.append("重复 MSB 分组异常 %d 例，例：%s" % (len(bad_link), bad_link[:3]))
    stray = [r for r in tab.values() if r.get("link") and len(kg[link_key(r)]) == 1]
    if stray:
        fails.append("有 %d 行带 link 但找不到同伴（陈旧 link），例：%s" % (
            len(stray), [(r["map"], r["part_name"]) for r in stray[:3]]))
    # 成对的两行必须同类同 policy（否则玩家从封印/未封印进去会看到不同的东西）
    for k, g in embedded.items():
        if len(set(r["cls"] for r in g)) != 1:
            fails.append("重复 MSB 两行 cls 不同：%s/%s %s vs %s" % (
                g[0]["map"], g[0]["part_name"], g[0]["cls"], g[1]["cls"]))
            break
    for k, g in embedded.items():
        if len(set(r["silo"] for r in g)) != 1:
            fails.append("重复 MSB 两行 silo 不同：%s/%s %s vs %s" % (
                g[0]["map"], g[0]["part_name"], g[0]["silo"], g[1]["silo"]))
            break
    for k, g in embedded.items():
        if len(set(r["policy"] for r in g)) != 1:
            fails.append("重复 MSB 两行 policy 不同：%s/%s %s vs %s" % (
                g[0]["map"], g[0]["part_name"], g[0]["policy"], g[1]["policy"]))
            break
    print("重复 MSB: %d 组 / %d 行 → 物理位置 %d" % (len(embedded), linked_rows, phys))

    # ⑥ 模型名字表：模型集合、类、政策、位置数都要与位置表一致
    mtab = _read_model_table()
    if not mtab:
        warns("没有 %s（跑 --names 生成）" % MODEL_TABLE)
    else:
        agg = collections.defaultdict(lambda: {"n": 0, "cls": collections.Counter(),
                                               "pol": collections.Counter()})
        for r in tab.values():
            a = agg[r["model"]]
            a["n"] += 1
            a["cls"][r["cls"]] += 1
            a["pol"][r["policy"]] += 1
        if set(mtab) != set(agg):
            fails.append("模型名字表与位置表的模型集合不一致（表 %d / 位置表 %d）" % (
                len(mtab), len(agg)))
        for model, a in agg.items():
            m = mtab.get(model)
            if not m:
                continue
            if m["cls"] != a["cls"].most_common(1)[0][0]:
                fails.append("模型 %s 类不一致：名字表 %s / 位置表 %s" % (
                    model, m["cls"], a["cls"].most_common(1)[0][0]))
            elif m["policy"] != a["pol"].most_common(1)[0][0]:
                fails.append("模型 %s 政策不一致：名字表 %s / 位置表 %s" % (
                    model, m["policy"], a["pol"].most_common(1)[0][0]))
            elif str(m["placements"]) != str(a["n"]):
                fails.append("模型 %s 位置数不一致：名字表 %s / 位置表 %d" % (
                    model, m["placements"], a["n"]))

    # ⑦ 分布报告
    pol = collections.Counter(r["policy"] for r in tab.values())
    print("policy:", dict(pol))
    print("silo（randomize）:", collections.Counter(
        r["silo"] for r in tab.values() if r["silo"]).most_common())
    print("tier:", dict(sorted(collections.Counter(
        r["tier"] for r in tab.values() if r["tier"]).items())))
    pl = collections.Counter()
    for r in tab.values():
        for x in (r["pools"] or "").split("|"):
            if x:
                pl[x] += 1
    print("pools:", dict(pl))
    print("keep 原因:", dict(collections.Counter(
        r["note"] for r in tab.values() if r["policy"] != "randomize")))

    for f in fails:
        print("  ✗ " + f)
    ok = not fails
    print("RESULT:", "PASS" if ok else "FAIL", "(%d 项不通过)" % len(fails))
    return 0 if ok else 1


def main(argv):
    ref = DEFAULT_REF
    if "--ref" in argv:
        ref = argv[argv.index("--ref") + 1]
    yaml_path = None
    if "--yaml" in argv:
        yaml_path = argv[argv.index("--yaml") + 1]
    if "--build" in argv:
        return build(ref, yaml_path)
    if "--check" in argv:
        return check(yaml_path)
    if "--names" in argv:
        build_model_names()
        return 0
    if "--stats" in argv:
        rows = read_table() if os.path.exists(TABLE) else scan_places()
        stats(rows)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
