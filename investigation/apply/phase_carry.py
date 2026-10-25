# -*- coding: utf-8 -*-
"""二阶段携带（v1.5）：当来源是多阶段 Boss 的「初始形态」时，把它的「变身成第二形态」
一起搬进目标地图。

为什么需要：多阶段 Boss 在参考实现/本作里是「一个场地两个实体」，原地图 EMEVD 在血量
阈值时关掉初始实体、打开第二形态。把初始形态当来源换到单阶段目标后，目标场地没有这段
事件，于是只有「一阶段名字 + 一阶段招式」，永远看不到二阶段。

本模块做三件事（只对单阶段目标，目标场地自己的多阶段逻辑不碰）：
  1. 在目标地图 MSB 里克隆一个「第二形态」part（同位置，初始隐藏）；
  2. 在目标地图 EMEVD 里追加三个事件：
       init      —— 地图加载时把第二形态藏起来；
       transition—— 初始形态血量到阈值时关它、开第二形态、换血条、按配方挂 SpEffect/动画；
       death     —— 第二形态死亡时补刀初始形态，让目标地图原本的死亡结算照常触发。
  3. 为第二形态克隆一条 NpcParam 行（血量按目标位置的 target_hp，避免二阶段突然变成
     捐赠者原图的满血数值）。

只支持 data/phase_carry.json 里核对过事件的组；没有配方 / 事件没核过的组一律不搬。
"""
import json
import os
import struct

import evd_add
import evd_edit
import msb_edit
import msb_read
import msb_write

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE = os.path.join(HERE, "data", "phase_carry.json")
MAP_REL = os.path.join("map", "MapStudio")

# ── 指令编码（cat, idx）都是从原版事件实测出来的，不要凭记忆改 ──
I_ENDIF_FLAG = (1003, 2)          # EndIf(EventFlag(flag))：8 字节 <u32 0, u32 flag>
I_END_EVENT = (1000, 4)           # End Event：4 字节 0
I_HP_RATIO = (4, 2)               # WaitFor(HPRatio(entity) <= value)：24 字节
I_HP_VALUE = (4, 0)               # WaitFor(CharacterHPValue(entity) <= value)：16 字节
I_CHAR_DEAD = (4, 0)              # WaitFor(CharacterDead(entity))：16 字节，第 2 个 u32=1
I_SET_FLAG = (2003, 66)           # SetEventFlagID(flag, on)：12 字节 <u32 0, u32 flag, u32 on>
I_CHAR_ON = (2004, 5)             # Enable/DisableCharacter(entity, on)：8 字节
I_COLLISION = (2004, 39)          # Enable/DisableCharacterCollision
I_AI = (2004, 1)                  # Enable/DisableCharacterAI
I_GRAVITY = (2004, 10)            # Enable/DisableCharacterGravity
I_NET = (2004, 34)                # SetNetworkUpdateRate(entity, on)
I_BAR = (2003, 11)                # DisplayBossHealthBar(enabled, entity, 0, name)：16 字节
I_SP = (2004, 8)                  # SetSpEffect(entity, effect)：8 字节
I_CLEAR_SP = (2004, 7)            # ClearSpEffect(entity, effect)：8 字节
I_ANIM = (2003, 18)               # ForceAnimationPlayback(entity, anim, 0, 1.0)：16 字节
I_DISPMASK = (2004, 26)           # ChangeCharacterDispmask(entity, mask|on<<8)：8 字节
I_AI_REPLAN = (2004, 20)          # RequestCharacterAIReplan(entity)：4 字节
I_FORCE_DEATH = (2004, 4)         # ForceCharacterDeath(entity, false)：8 字节

MAX_ENTITY = 0xFFFFFF00


def load_recipes(path=RECIPE):
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    fams = {}
    for fam in doc.get("families") or []:
        for key in ("id", "map", "initial", "transformed", "trigger", "actions"):
            if key not in fam:
                raise ValueError("phase_carry 配方缺字段 %s: %s" % (key, fam.get("id")))
        fams[fam["id"]] = fam
    return fams


def _u32(v):
    return struct.pack("<I", int(v) & 0xFFFFFFFF)


def _i32(v):
    return struct.pack("<i", int(v))


def _f32(v):
    return struct.pack("<f", float(v))


def ins(cat, idx, payload):
    """一条待写入的 EMEVD 指令；payload 已经是参数区字节。"""
    return (int(cat), int(idx), bytes(payload))


def _end_if(flag):
    return ins(*I_ENDIF_FLAG, _u32(0) + _u32(flag))


def _set_flag(flag, on=1):
    return ins(*I_SET_FLAG, _u32(0) + _u32(flag) + _u32(on))


def _char(cat, entity, on):
    return ins(*cat, _u32(entity) + _u32(on))


def _bar(enabled, entity, name):
    return ins(*I_BAR, _u32(enabled) + _u32(entity) + _u32(0) + _u32(name))


def _sp(cat, entity, effect):
    return ins(*cat, _u32(entity) + _u32(effect))


def _anim(entity, anim):
    return ins(*I_ANIM, _u32(entity) + _u32(anim) + _u32(0) + _f32(1.0))


def _dispmask(entity, mask, on):
    return ins(*I_DISPMASK, _u32(entity) + _u32(int(mask) | (1 << 8) if on else int(mask)))


def _hp_ratio(entity, value):
    # 与 DarkScript3 编译 WaitFor(HPRatio(...) <= x) 的字节一致：group=5
    return ins(*I_HP_RATIO, _u32(0) + _u32(entity) + _u32(5) + _f32(value)
               + _u32(0) + _f32(1.0))


def _hp_value(entity, value=1):
    return ins(*I_HP_VALUE, _u32(0) + _u32(entity) + _u32(int(value)) + _f32(1.0))


def _char_dead(entity):
    return ins(*I_CHAR_DEAD, _u32(0) + _u32(entity) + _u32(1) + _f32(1.0))


def _force_death(entity):
    return ins(*I_FORCE_DEATH, _u32(entity) + _u32(0))


def _trigger(trigger, entity):
    if trigger.get("kind") == "hp1":
        return [_hp_value(entity, 1)]
    return [_hp_ratio(entity, float(trigger.get("value") or 0.01))]


def build_events(fam, phase1, phase2, flag_tr, flag_death, bar2):
    """返回 {kind: [ins...]}，phase1/phase2 是目标地图里的实体 ID。"""
    act = fam.get("actions") or {}
    init = [
        _char(I_CHAR_ON, phase2, 0),
        _char(I_COLLISION, phase2, 0),
        _char(I_AI, phase2, 0),
        _char(I_GRAVITY, phase2, 0),
        _char(I_NET, phase2, 0),
        ins(*I_END_EVENT, _u32(0)),
    ]
    trans = [_end_if(flag_tr)]
    trans += _trigger(fam.get("trigger") or {}, phase1)
    trans += [
        _char(I_NET, phase1, 0),
        _char(I_AI, phase1, 0),
        _char(I_COLLISION, phase1, 0),
        _char(I_CHAR_ON, phase1, 0),
        _char(I_CHAR_ON, phase2, 1),
        _char(I_AI, phase2, 1),
        _char(I_COLLISION, phase2, 1),
        _char(I_GRAVITY, phase2, 1),
        _char(I_NET, phase2, 1),
    ]
    if bar2:
        trans.append(_bar(1, phase2, bar2))
    for effect in act.get("sp1") or []:
        trans.append(_sp(I_SP, phase1, effect))
    for effect in act.get("clear1") or []:
        trans.append(_sp(I_CLEAR_SP, phase1, effect))
    for effect in act.get("sp2") or []:
        trans.append(_sp(I_SP, phase2, effect))
    for effect in act.get("clear2") or []:
        trans.append(_sp(I_CLEAR_SP, phase2, effect))
    for mask, on in act.get("dispmask") or []:
        trans.append(_dispmask(phase2, mask, bool(on)))
    if act.get("anim2"):
        trans.append(_anim(phase2, act["anim2"]))
    trans.append(ins(*I_AI_REPLAN, _u32(phase2)))
    trans.append(_set_flag(flag_tr, 1))

    death = [
        _end_if(flag_death),
        _char_dead(phase2),
        _char(I_CHAR_ON, phase1, 1),   # 已隐藏的实体也唤醒一下，ForceDeath 才能结算
        _force_death(phase1),
        _set_flag(flag_death, 1),
    ]
    return {"init": init, "transition": trans, "death": death}


def detect(plan, recipes=None):
    """从计划里找出「目标单阶段 + 来源是多阶段初始形态」的单元。

    返回 [{unit_key, family, places, target_hp, initial, transformed}]。
    判定用来源单元自己的 places.entity_id == 配方 initial.entity；不能只看 npc，
    因为玛莲妮亚两阶段同 npc/model。
    """
    recipes = recipes or load_recipes()
    units = plan.get("units") or []
    by_key = {u.get("key"): u for u in units}
    mp_maps = set()
    for u in units:
        if u.get("multiphase"):
            for pl in u.get("places") or []:
                mp_maps.add(pl.get("map"))
    out = []
    for u in units:
        dk = u.get("donor_key")
        don = by_key.get(dk) if dk else None
        if not don or not don.get("multiphase"):
            continue
        maps = {p.get("map") for p in u.get("places") or []}
        if maps & mp_maps:
            continue                     # 目标自己就是多阶段场地：保留原场地事件，不搬
        for fam in recipes.values():
            ini = fam["initial"]
            if not any(int(p.get("entity_id") or 0) == int(ini["entity"])
                       for p in don.get("places") or []):
                continue
            if int(u.get("new_npc_id") or 0) != int(ini["npc"]):
                continue
            out.append({"unit_key": u.get("key"), "family": fam["id"],
                        "places": [dict(p) for p in u.get("places") or []],
                        "target_hp": int(u.get("target_hp") or 0),
                        "initial": ini, "transformed": fam["transformed"]})
            break
    return out


def _read_field(payload, fbn, field):
    typ = fbn.typ(field)
    fmt = {"u8": "<B", "s8": "<b", "u16": "<H", "s16": "<h",
           "u32": "<I", "s32": "<i", "f32": "<f"}[typ]
    return struct.unpack_from(fmt, payload, fbn.off(field))[0]


def alloc_npc_rows(carries, npc_pf, fbn, used=None, log=None):
    """给每个 carry 的第二形态克隆一条 NpcParam 行；返回 [(id, payload, name)]。

    不直接用捐赠者的第二形态原行：那样二阶段血量会是捐赠者原图数值（例如 889 血的目标
    突然变成几万血）。这里沿用原行所有战斗参数，把 hp 改成「目标位置的血量 × 捐赠者
    二阶段/一阶段基础血量比」、魂置 0 —— 目标位置要打多少血，二阶段就按原作的相对量给。
    """
    used = set(npc_pf.ids) | set(used or ())
    rows = []
    for c in carries:
        t = c["transformed"]
        src = npc_pf.payload(int(t["npc"]))
        b = bytearray(src)
        hp = int(c.get("target_hp") or 0)
        if hp <= 0:
            hp = 1
        try:
            hp1 = float(_read_field(npc_pf.payload(int(c["initial"]["npc"])), fbn, "hp"))
            hp2 = float(_read_field(src, fbn, "hp"))
            ratio = (hp2 / hp1) if hp1 > 0 else 1.0
        except Exception:
            ratio = 1.0
        ratio = max(0.2, min(3.0, ratio))
        hp = max(1, int(round(hp * ratio)))
        for field, val in (("hp", hp), ("getSoul", 0)):
            typ = fbn.typ(field)
            fmt = {"u8": "<B", "s8": "<b", "u16": "<H", "s16": "<h",
                   "u32": "<I", "s32": "<i", "f32": "<f"}[typ]
            struct.pack_into(fmt, b, fbn.off(field),
                             float(val) if typ == "f32" else int(val))
        nid = int(t["npc"])
        while nid in used:
            nid += 1
        if nid >= 0x7FFFFFFF:
            raise ValueError("phase_carry: NpcParam 行 id 用尽")
        used.add(nid)
        c["hp_ratio"] = round(ratio, 3)
        if log:
            log("    %s：二阶段 NpcParam %d（原行 %d；目标 hp %d × %.3f = %d）"
                % (c["family"], nid, int(t["npc"]), int(c["target_hp"] or 0), ratio, hp))
        name = "gfPhase2:%d:%s:%d" % (int(t["npc"]), c["family"], hp)
        rows.append((nid, bytes(b), name))
        c["npc2"] = nid
    if log:
        log("[写盘] 二阶段携带：%d 个目标，克隆 %d 条第二形态 NpcParam"
            % (len(carries), len(rows)))
    return rows


def _part_index(m, part_name, occurrence):
    seen = 0
    for i, p in m.parts():
        if p.get("type") != msb_read.PART_TYPE_ENEMY:
            continue
        if p.get("part_name") != part_name:
            continue
        seen += 1
        if seen == int(occurrence):
            return i
    raise ValueError("phase_carry: 找不到 part %s#%s" % (part_name, occurrence))


def patch_map(raw, carries, log=None):
    """给一张地图克隆第二形态 part；返回 (新明文, 新增的 part 信息列表)。"""
    m = msb_edit.Msb(raw)
    parts = dict(m.parts())
    pb = m.block("PARTS_PARAM_ST")
    if pb is None:
        raise ValueError("phase_carry: 地图没有 PARTS_PARAM_ST")
    entities = [int(p.get("entity_id") or 0) for p in parts.values()]
    ids = [struct.unpack_from("<i", e, msb_read.P_ID)[0] for e in pb["entries"]
           if len(e) > msb_read.P_ID + 4]
    insts = [struct.unpack_from("<i", e, msb_read.P_INSTANCEID)[0] for e in pb["entries"]
             if len(e) > msb_read.P_INSTANCEID + 4]
    next_ent = max([x for x in entities if 0 < x < MAX_ENTITY] or [1000000]) + 1
    next_pid = max(ids or [0]) + 1
    next_inst = max(insts or [0]) + 1
    added = []
    for c in carries:
        t = c["transformed"]
        for pl in c["places"]:
            i = _part_index(m, pl["part_name"], pl.get("occurrence") or 1)
            src = bytes(pb["entries"][i])
            mi = m.model_entry(t["model"])
            if mi < 0:
                mi = m.add_model(t["model"], msb_edit.chr_sib_path(t["model"]))
            e = bytearray(src)
            ent_rel = struct.unpack_from("<q", e, msb_read.P_ENTITY_DATA_OFF)[0]
            ent = next_ent
            next_ent += 1
            if ent >= MAX_ENTITY:
                raise ValueError("phase_carry: EntityID 用尽")
            struct.pack_into("<I", e, ent_rel, ent)
            struct.pack_into("<i", e, msb_read.P_ID, next_pid)
            next_pid += 1
            struct.pack_into("<i", e, msb_read.P_INSTANCEID, next_inst)
            next_inst += 1
            struct.pack_into("<i", e, msb_read.P_MODELIDX, mi)
            typ = struct.unpack_from("<q", e, msb_read.P_TYPE_DATA_OFF)[0]
            struct.pack_into("<i", e, typ + msb_read.E_THINK, int(t["think"]))
            struct.pack_into("<i", e, typ + msb_read.E_NPC, int(c["npc2"]))
            struct.pack_into("<i", e, typ + msb_read.E_CHARA, int(t.get("chara") or -1))
            e[typ + 0x15] = 0                  # UnkT15 = false
            struct.pack_into("<i", e, typ + 0x38, -1)  # BackupEventAnimID = -1
            pb["entries"].append(bytes(e))
            added.append({"entity": ent, "part_id": next_pid - 1,
                          "instance_id": next_inst - 1, "source_index": i,
                          "npc": int(c["npc2"]), "think": int(t["think"]),
                          "model": t["model"], "family": c["family"],
                          "unit_key": c.get("unit_key")})
            if log:
                log("    %s：克隆第二形态 part entity=%d（%s %s）"
                    % (c["family"], ent, t["model"], t["npc"]))
    return m.assemble(), added


def _event_family(path):
    if not os.path.isfile(path):
        return None
    data = open(path, "rb").read()
    raw, hdr = msb_read.dcx_payload(data)
    return data, raw, hdr


def _alloc_ids(ev, map_raw, count, other_blobs=None, base_hint=None, taken=None):
    """给一张图分配 count 组 (event_id 三元组, flag 对)；用地图事件号段里的空号。

    other_blobs 是其它地图/公共事件文件的明文，用来额外避开「这个 flag 号在别处已经在用」
    的情况（事件 flag 是全局的，只扫本图会漏）。base_hint 用目标 part 的实体号推地图号段
    （实体号前缀 = 地图事件号段）；taken 是本次写层已经用掉的号，跨地图唯一。
    """
    taken = taken if taken is not None else set()
    eids = {int(e.get("eid") or 0) for e in ev.events}
    # 地图号段优先用「目标 part 的实体号前缀」——实体号和事件 id 同属这张地图的号段
    # （m12_05 → 12050000、m61_47_45 → 2047450000），比扫事件 id 猜更稳。
    # 兜底才用「最常见的万位桶」：地图事件里常夹着 10 亿级世界 flag 或 100 万级公共号。
    from collections import Counter
    base = 0
    if base_hint and 1000000 <= int(base_hint) < 2100000000:
        base = (int(base_hint) // 10000) * 10000
    if not base:
        buckets = Counter((x // 10000) * 10000 for x in eids if 10000 < x < 2000000000)
        base = buckets.most_common(1)[0][0] if buckets else 1000000
    # 已被事件文件里任何 4 字节数字占用的值（粗筛，避免撞 flag）
    used_bytes = set()
    for i in range(0, len(map_raw) - 3):
        used_bytes.add(map_raw[i:i + 4])
    other_blobs = other_blobs or []
    def pick(start):
        n = start
        while True:
            if n not in eids and n not in taken:
                b = _u32(n)
                if b not in used_bytes and not any(b in blob for blob in other_blobs):
                    return n
            n += 1
    blocks = []
    for k in range(count):
        blocks.append({
            "init": pick(base + 9000 + k * 8),
            "transition": pick(base + 9001 + k * 8),
            "death": pick(base + 9002 + k * 8),
            "flag_transition": pick(base + 9100 + k * 8),
            "flag_death": pick(base + 9101 + k * 8),
        })
    for blk in blocks:
        taken.update(blk.values())
    return blocks


def patch_events(event_data, raw, carries, recipes, log=None, other_blobs=None,
                 base_hint=None, taken=None):
    """给事件明文加 init/transition/death 三个事件；返回 (新明文, 分配信息, 新事件列表)。"""
    ev = evd_edit.Evd(raw)
    blocks = _alloc_ids(ev, raw, len(carries), other_blobs, base_hint, taken)
    specs = []
    info = []
    for c, ids in zip(carries, blocks):
        # phase1 实体：目标 part 原本的 entity（places 里每个图各一个，但调用方按图过滤）
        phase1 = int(c["places"][0]["entity_id"])
        phase2 = int(c["phase2_entity"])
        evs = build_events(recipes[c["family"]], phase1, phase2,
                           ids["flag_transition"], ids["flag_death"],
                           c["transformed"].get("bar"))
        for kind in ("init", "transition", "death"):
            specs.append({"event_id": ids[kind], "rest": 1,
                          "instructions": evs[kind]})
        info.append({"family": c["family"], "phase1": phase1, "phase2": phase2,
                     "events": [ids["init"], ids["transition"], ids["death"]],
                     "flags": [ids["flag_transition"], ids["flag_death"]]})
        if log:
            log("    %s：事件 %d/%d/%d，flag %d/%d（实体 %d→%d）"
                % (c["family"], ids["init"], ids["transition"], ids["death"],
                   ids["flag_transition"], ids["flag_death"], phase1, phase2))
    out, meta = evd_add.add_events(raw, specs, register=True)
    return out, meta, info


def _load_event_blobs(dirs):
    """读一批目录下所有 .emevd.dcx 的明文（失败的文件跳过）。"""
    out = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".emevd.dcx"):
                continue
            try:
                data = open(os.path.join(d, fn), "rb").read()
                out.append(msb_read.dcx_payload(data)[0])
            except Exception:
                continue
    return out


def apply(stage_data, carries, mod_dir, vanilla_event_dir, log=None):
    """在已写好的层上做二阶段携带（地图 part + 事件）。返回统计。"""
    if not carries:
        return {"targets": 0, "maps": 0, "parts": 0, "events": 0, "details": []}
    # 按图分组；同一单元跨两张图时两张都做（链接组）
    by_map = {}
    for c in carries:
        for pl in c["places"]:
            cc = dict(c)
            cc["places"] = [pl]
            cc["_key"] = (c["unit_key"], pl["map"])
            by_map.setdefault(pl["map"], []).append(cc)
    recipes = load_recipes()
    # 事件 flag 是全局的：把 mod / 本体的事件明文都读进来，分配时避开别处用过的号
    other_blobs = _load_event_blobs([os.path.join(mod_dir, "event"), vanilla_event_dir])
    taken = set()
    stats = {"targets": len(carries), "maps": 0, "parts": 0, "events": 0,
             "details": [], "skipped": []}
    for mname in sorted(by_map):
        # 2) 事件：已有分层事件文件优先（血条名已改过），否则用 mod / 本体事件
        epath = os.path.join(stage_data, "event", mname + ".emevd.dcx")
        src = None
        if os.path.isfile(epath):
            src = epath
        else:
            mod_ev = os.path.join(mod_dir, "event", mname + ".emevd.dcx")
            van_ev = os.path.join(vanilla_event_dir, mname + ".emevd.dcx")
            src = mod_ev if os.path.isfile(mod_ev) else (van_ev if os.path.isfile(van_ev) else None)
        if src is None:
            # 少数地图变体（如 m61_47_45_10）本体和 mod 都没有独立事件文件；
            # 这种图整张跳过（part 也不克隆），不要凭空造一份事件。
            stats["skipped"].append({"map": mname, "reason": "no-event-file"})
            if log:
                log("[写盘] 二阶段携带：%s 没有事件文件，跳过这张图" % mname)
            continue
        # 1) part
        mpath = os.path.join(stage_data, MAP_REL, mname + ".msb.dcx")
        if not os.path.isfile(mpath):
            raise ValueError("phase_carry: 层里没有地图 %s" % mpath)
        mdata = open(mpath, "rb").read()
        mraw, mhdr = msb_read.dcx_payload(mdata)
        mout, added = patch_map(mraw, by_map[mname], log=log)
        mdcx, mrep = msb_write.dcx_repack(mout, in_kind=(mhdr or {}).get("kind"),
                                          out_kind="same",
                                          orig_prefix=mdata[:76] if mhdr else None)
        with open(mpath, "wb") as f:
            f.write(mdcx)
        # 回读验证 part 数 + 新 part 身份
        chk = msb_edit.Msb(msb_read.dcx_payload(mdcx)[0])
        cparts = dict(chk.parts())
        base_n = len(dict(msb_edit.Msb(mraw).parts()))
        if len(cparts) != base_n + len(added):
            raise ValueError("phase_carry: %s part 数不对 %d+%d != %d"
                             % (mname, base_n, len(added), len(cparts)))
        ents = {int(p.get("entity_id") or 0): p for p in cparts.values()}
        for a in added:
            p = ents.get(a["entity"])
            if not p:
                raise ValueError("phase_carry: %s 复制 part entity=%d 没写进去"
                                 % (mname, a["entity"]))
            if int(p.get("npc_id") or 0) != a["npc"] or int(p.get("think_id") or 0) != a["think"]:
                raise ValueError("phase_carry: %s 复制 part %d 身份不对" % (mname, a["entity"]))
        edata = open(src, "rb").read()
        eraw, ehdr = msb_read.dcx_payload(edata)
        # 每张图可能同时有多个目标；按 unit_key 对上自己那份新 part
        for c in by_map[mname]:
            mine = [a for a in added if a.get("unit_key") == c["unit_key"]]
            if not mine:
                raise ValueError("phase_carry: %s 找不到 %s 的新 part"
                                 % (mname, c["unit_key"]))
            c["phase2_entity"] = mine[0]["entity"]
        _ents = [int(pl.get("entity_id") or 0) for c in by_map[mname] for pl in c["places"]]
        _ents = [x for x in _ents if x > 0]
        _base = min(_ents) if _ents else None
        eout, emeta, einfo = patch_events(edata, eraw, by_map[mname], recipes, log=log,
                                          other_blobs=other_blobs, base_hint=_base,
                                          taken=taken)
        edcx, erep = msb_write.dcx_repack(eout, in_kind=(ehdr or {}).get("kind"),
                                          out_kind="same",
                                          orig_prefix=edata[:76] if ehdr else None)
        os.makedirs(os.path.dirname(epath), exist_ok=True)
        with open(epath, "wb") as f:
            f.write(edcx)
        # 结构复验
        nev = evd_edit.Evd(msb_read.dcx_payload(edcx)[0])
        bad = [n for n, ok in nev.check_chain() if not ok]
        if bad:
            raise ValueError("phase_carry: %s 事件结构复验失败：%s" % (mname, bad))
        stats["maps"] += 1
        stats["parts"] += len(added)
        stats["events"] += len(einfo) * 3
        stats["details"].append({"map": mname, "parts": added, "events": einfo})
        if log:
            log("[写盘] 二阶段携带：%s +%d part / +%d 事件（%s）"
                % (mname, len(added), len(einfo) * 3,
                   "、".join(x["family"] for x in by_map[mname])))
    return stats
