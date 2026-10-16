# -*- coding: utf-8 -*-
"""
msb_read.py — 只读的 Elden Ring MSB(MSBE) 解析器。

只读：本模块从不写任何游戏 / mod 文件；临时产物只写进 investigation/msb_probe/。

结构来源（实证 + 权威参考 SoulsFormatsNEXT）：
  MSB/​MSB.cs            —— 文件头 0x10 字节: "MSB " | i32 1 | i32 0x10 | 00 00 01 FF
  MSB/MSBE/MSBE.cs      —— 6 个 param 块的顺序与链式结构
  MSB/MSBE/PartsParam.cs—— Part 基类 / Enemy 类型数据字段表
  MSB/MSBE/ModelParam.cs—— Model 条目布局

param 块结构（Read 的真实口径，注意是 offsetCount-1 个条目偏移）：
    [i32 version][i32 offsetCount][i64 nameOffset]
    [i64 entryOffsets[offsetCount-1]][i64 nextParamOffset]
  · nameOffset / nextParamOffset 都是**文件绝对**偏移
  · param 名字串是 **UTF-16LE**、以 \0\0 结尾（不是 ASCII！）

条目结构：
    Part 条目 [i64 nameOffset(相对条目起点)] ... 子块偏移也都是**相对条目起点**
"""
import csv
import glob
import os
import struct
import sys
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import erio                                                    # noqa: E402
import oodle                                                   # noqa: E402

# ────────────────────────── 常量 ──────────────────────────

MSBE_MAGIC = b"MSB "
HEADER_SIZE = 0x10
# MSBE.Read 里的固定顺序（见 MSBE.cs Read/Write）
MSBE_PARAM_ORDER = ["MODEL_PARAM_ST", "EVENT_PARAM_ST", "POINT_PARAM_ST",
                    "ROUTE_PARAM_ST", "LAYER_PARAM_ST", "PARTS_PARAM_ST"]

PART_TYPE_MAP_PIECE = 0
PART_TYPE_ENEMY = 2
PART_TYPE_PLAYER = 4
PART_TYPE_COLLISION = 5
PART_TYPE_ASSET = 13

MAPSTUDIO_DIR = None    # 法魂本体不带 MSB（敌人摆放来自游戏本体，打包在 Data*.bhd/.bdt 里）
# 本模块不预设目录：由调用方传路径（例如归档读取器抽出来的地图）
GA_REGULATION = None    # 校验用的 regulation 由调用方传（法魂这边就是它自己的 mod/regulation.bin）
# 产物只落 msb_probe/（apply/ 里除了本文件一个字节都不写）
OUT_DIR = os.path.join(os.path.dirname(_HERE), "msb_probe")
CSV_NAME = "goldenage_enemies.csv"

# Part 基类字段（相对条目起点，实测自 PartsParam.cs Part(BinaryReaderEx)）
P_NAMEOFF, P_INSTANCEID, P_TYPE, P_ID, P_MODELIDX = 0x00, 0x08, 0x0C, 0x10, 0x14
P_SIBOFF, P_POS, P_ROT, P_SCALE = 0x18, 0x20, 0x2C, 0x38
P_ENTITY_DATA_OFF, P_TYPE_DATA_OFF = 0x60, 0x68

# Enemy 类型数据（相对 typeDataOffset，实测自 EnemyBase.ReadTypeData）
E_THINK, E_NPC, E_TALK, E_CHARA = 0x08, 0x0C, 0x10, 0x18


# ────────────────────────── 读取原语 ──────────────────────────

def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i64(b, o):
    return struct.unpack_from("<q", b, o)[0]


def _u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def _f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def _utf16z(b, o, limit=None):
    """UTF-16LE 到 \\0\\0 为止。返回 (字符串, 终止符之后的位置)"""
    if o < 0 or o + 1 >= len(b):
        return "", o
    end = o
    stop = len(b) if limit is None else min(len(b), o + limit)
    while end + 1 < stop and b[end:end + 2] != b"\0\0":
        end += 2
    return b[o:end].decode("utf-16-le", "replace"), end + 2


# ────────────────────────── DCX ──────────────────────────

def dcx_payload(data):
    """DCX → 明文。ZSTD / DFLT(zlib) / KRAK(Oodle) 三条路。"""
    if data[:4] == b"DCX\0":
        h = erio.dcx_parts(data)
        kind = (h["kind"] or "").upper()
        payload = data[h["payload_off"]:h["payload_off"] + h["comp"]]
        unc = h["unc"]
        if kind.startswith("ZSTD"):
            import zstandard as zstd
            out = zstd.ZstdDecompressor().decompress(payload, max_output_size=unc + 4096)
        elif kind.startswith(("ZLIB", "DEFLATE", "DFLT", "FLATE")):
            # DFLT 就是裸 zlib 流（实测）
            out = zlib.decompress(payload)
        elif kind.startswith("KRAK") or kind.startswith("OODL"):
            out = oodle.decompress(payload, unc)
        else:
            raise ValueError("未知 DCX 压缩类型 %r" % h["kind"])
        if len(out) != unc:
            raise ValueError("解压后大小不符 %d != %d" % (len(out), unc))
        return out, h
    return data, None


# ────────────────────────── param 链 ──────────────────────────

def walk_params(raw, trace=None):
    """走完所有 param 块。返回 [ {version,count,name,entry_offsets,next,head} ]"""
    if raw[:4] != MSBE_MAGIC:
        raise ValueError("不是 MSB（magic=%r）" % raw[:4])
    fver = _i32(raw, 4)
    hdrsize = _i32(raw, 8)
    if raw[0x0E] != 1 or raw[0x0F] != 0xFF:
        raise ValueError("头标志不符 enc=%d off64=%#x" % (raw[0x0E], raw[0x0F]))
    pos = HEADER_SIZE
    blocks = []
    guard = 0
    while True:
        guard += 1
        if guard > 64:
            raise ValueError("param 链过长，疑似环")
        if pos <= 0 or pos + 16 > len(raw):
            raise ValueError("nextParamOffset 越界 %#x" % pos)
        bver = _i32(raw, pos)
        cnt = _i32(raw, pos + 4)
        name_off = _i64(raw, pos + 8)
        if cnt < 1 or cnt > 10 ** 7:
            raise ValueError("offsetCount 异常 %d @%#x" % (cnt, pos))
        arr = pos + 16
        nxt_pos = arr + (cnt - 1) * 8
        if nxt_pos + 8 > len(raw):
            raise ValueError("条目偏移数组越界 @%#x" % pos)
        nxt = _i64(raw, nxt_pos)
        name, _ = _utf16z(raw, name_off)
        entry_offsets = struct.unpack_from("<%dq" % (cnt - 1), raw, arr) if cnt > 1 else ()
        blocks.append({"version": bver, "count": cnt, "name": name, "head": pos,
                       "name_offset": name_off, "entry_offsets": entry_offsets,
                       "next": nxt, "arr_pos": arr, "next_pos": nxt_pos})
        if trace is not None:
            trace.append("  block@%#08x ver=%#x offsetCount=%d nameOffset=%#010x "
                         "nextParamOffset@%#x=%#x name=%r"
                         % (pos, bver, cnt, name_off, nxt_pos, nxt, name))
        if nxt == 0:
            break
        pos = nxt
    return fver, blocks


# ────────────────────────── 条目 ──────────────────────────

def read_models(raw, block):
    """MODEL_PARAM_ST → [名字]，顺序即 ModelIndex 的顺序"""
    out = []
    for o in block["entry_offsets"]:
        if o <= 0 or o + 0x18 > len(raw):
            out.append("")
            continue
        name_off = _i64(raw, o)
        nm, _ = _utf16z(raw, o + name_off)
        out.append(nm)
    return out


def read_enemy(raw, off, models):
    """一个 Part 条目 → dict（仅当 type==Enemy 时有意义）"""
    p_type = _u32(raw, off + P_TYPE)
    midx = _i32(raw, off + P_MODELIDX)
    name_off = _i64(raw, off + P_NAMEOFF)
    ent_off = off + _i64(raw, off + P_ENTITY_DATA_OFF)
    typ_off = off + _i64(raw, off + P_TYPE_DATA_OFF)
    part_name, _ = _utf16z(raw, off + name_off)

    entity_id = _u32(raw, ent_off) if 0 <= ent_off < len(raw) - 4 else -1
    think_id = _i32(raw, typ_off + E_THINK) if 0 <= typ_off < len(raw) - 0x20 else -1
    npc_id = _i32(raw, typ_off + E_NPC) if 0 <= typ_off < len(raw) - 0x20 else -1
    talk_id = _i32(raw, typ_off + E_TALK) if 0 <= typ_off < len(raw) - 0x20 else -1
    chara_id = _i32(raw, typ_off + E_CHARA) if 0 <= typ_off < len(raw) - 0x20 else -1

    model = ""
    if 0 <= midx < len(models):
        model = models[midx] or part_name

    return {"type": p_type, "part_name": part_name, "model": model,
            "model_index": midx, "entity_id": entity_id,
            "npc_id": npc_id, "think_id": think_id, "chara_id": chara_id,
            "talk_id": talk_id,
            "x": _f32(raw, off + P_POS), "y": _f32(raw, off + P_POS + 4),
            "z": _f32(raw, off + P_POS + 8)}


# ────────────────────────── 主入口 ──────────────────────────

def read_msb(path, trace=None):
    """只读解析一个 MSB / MSB.dcx。返回 dict。"""
    data = open(path, "rb").read()
    raw, hdr = dcx_payload(data)
    fver, blocks = walk_params(raw, trace=trace)
    by_name = {}
    for b in blocks:
        by_name.setdefault(b["name"], b)

    models = read_models(raw, by_name["MODEL_PARAM_ST"]) if "MODEL_PARAM_ST" in by_name else []

    enemies = []
    pb = by_name.get("PARTS_PARAM_ST")
    if pb:
        for o in pb["entry_offsets"]:
            if o <= 0 or o + 0xC8 > len(raw):
                continue
            if _u32(raw, o + P_TYPE) != PART_TYPE_ENEMY:
                continue
            enemies.append(read_enemy(raw, o, models))

    return {"path": path, "version": fver, "dcx": hdr is not None,
            "dcx_kind": (hdr or {}).get("kind"), "raw_size": len(raw),
            "params": [(b["name"], b["count"]) for b in blocks],
            "models": models, "enemies": enemies}


def evidence_dump(path):
    """把一个 Enemy part 的字节级证据摊开：基记录 + 两个子块 + 落位字段。
    这是"字段偏移猜对了"的实证，也是报告里最该留的一段。"""
    L = []
    raw, _h = dcx_payload(open(path, "rb").read())
    _v, blocks = walk_params(raw)
    pb = next(b for b in blocks if b["name"] == "PARTS_PARAM_ST")
    models = read_models(raw, next(b for b in blocks if b["name"] == "MODEL_PARAM_ST"))

    # 找第一个 type==2 的条目
    off = None
    types = {}
    for o in pb["entry_offsets"]:
        if o <= 0 or o + 0xC8 > len(raw):
            continue
        t = _u32(raw, o + P_TYPE)
        types[t] = types.get(t, 0) + 1
        if t == PART_TYPE_ENEMY and off is None:
            off = o
    L.append("  条目类型分布（PARTS_PARAM_ST, 本图）: %s"
             % sorted(types.items(), key=lambda x: -x[1]))
    if off is None:
        L.append("  本图没有 Enemy part")
        return L

    ent = off + _i64(raw, off + P_ENTITY_DATA_OFF)
    typ = off + _i64(raw, off + P_TYPE_DATA_OFF)
    L.append("  第一个 Enemy 条目 @%#x" % off)
    L.append("    基记录 %#x..%#x:" % (off, off + 0xC0))
    for i in range(0, 0xC0, 16):
        L.append("      %#08x  %s" % (off + i, raw[off + i:off + i + 16].hex(" ")))
    L.append("    实测字段:")
    L.append("      +0x00 i64 nameOffset      = %#x  (相对条目起点) -> name=%r"
             % (_i64(raw, off + P_NAMEOFF), _utf16z(raw, off + _i64(raw, off + P_NAMEOFF))[0]))
    L.append("      +0x08 i32 InstanceID      = %d" % _i32(raw, off + P_INSTANCEID))
    L.append("      +0x0C u32 PartType        = %d   (2 = Enemy)"
             % _u32(raw, off + P_TYPE))
    L.append("      +0x10 i32 ID              = %d" % _i32(raw, off + P_ID))
    L.append("      +0x14 i32 ModelIndex      = %d -> model=%r"
             % (_i32(raw, off + P_MODELIDX),
                models[_i32(raw, off + P_MODELIDX)] if 0 <= _i32(raw, off + P_MODELIDX) < len(models) else "?"))
    L.append("      +0x18 i64 sibOffset       = %#x" % _i64(raw, off + P_SIBOFF))
    L.append("      +0x20 V3  Position        = (%.3f, %.3f, %.3f)"
             % (_f32(raw, off + P_POS), _f32(raw, off + P_POS + 4), _f32(raw, off + P_POS + 8)))
    L.append("      +0x2C V3  Rotation        = (%.3f, %.3f, %.3f)"
             % (_f32(raw, off + P_ROT), _f32(raw, off + P_ROT + 4), _f32(raw, off + P_ROT + 8)))
    L.append("      +0x38 V3  Scale           = (%.3f, %.3f, %.3f)"
             % (_f32(raw, off + P_SCALE), _f32(raw, off + P_SCALE + 4), _f32(raw, off + P_SCALE + 8)))
    L.append("      +0x60 i64 entityDataOffset= %#x -> 绝对 %#x"
             % (_i64(raw, off + P_ENTITY_DATA_OFF), ent))
    L.append("      +0x68 i64 typeDataOffset  = %#x -> 绝对 %#x"
             % (_i64(raw, off + P_TYPE_DATA_OFF), typ))
    L.append("    entityData @%#x:" % ent)
    L.append("      +0x00 u32 EntityID        = %d" % _u32(raw, ent))
    L.append("      +0x1C u32[8] EntityGroupIDs= %s"
             % (struct.unpack_from("<8I", raw, ent + 0x1C),))
    L.append("    typeData @%#x (EnemyBase.ReadTypeData):" % typ)
    L.append("      +0x08 i32 ThinkParamID    = %d" % _i32(raw, typ + E_THINK))
    L.append("      +0x0C i32 NPCParamID      = %d   <== 拿去 NpcParam 对账的就是它"
             % _i32(raw, typ + E_NPC))
    L.append("      +0x10 i32 TalkID          = %d" % _i32(raw, typ + E_TALK))
    L.append("      +0x18 i32 CharaInitID     = %d" % _i32(raw, typ + E_CHARA))
    return L


# ────────────────────────── 自校验 / CLI ──────────────────────────

def _quiet(fn, p):
    try:
        return fn(p), None
    except Exception as e:                                      # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def _param_body(plain, table):
    import native_apply as na
    off, size = 0, 0
    for name, o, s in na.bnd4_entries(plain):
        if os.path.basename(name.replace("\\", "/")) == table + ".param":
            off, size = o, s
    return off, size


def load_row_ids(reg_path, table):
    """该 regulation 里某张 param 表的全部行 id"""
    import enemy_randomizer as er
    plain = er.load_plain(reg_path)
    off, size = _param_body(plain, table)
    if not size:
        raise RuntimeError("regulation 里找不到 %s" % table)
    return set(er.scan_rows(plain, off, size).keys())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    bed, reg = MAPSTUDIO_DIR, GA_REGULATION
    out_csv = os.path.join(OUT_DIR, CSV_NAME)
    for i, a in enumerate(argv):
        if a == "--bed":
            bed = argv[i + 1]
        elif a == "--reg":
            reg = argv[i + 1]
        elif a == "--csv":
            out_csv = argv[i + 1]

    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(bed, "*.msb.dcx"))) or \
        sorted(glob.glob(os.path.join(bed, "*.msb")))
    L = []

    def say(s=""):
        print(s)
        L.append(s)

    say("=" * 78)
    say("MSB 测试床: %s" % bed)
    say("文件数: %d" % len(files))
    say("=" * 78)

    # ---- 结构定位的实测数值（对第一个文件打印全链）----
    trace = []
    first = None
    for p in files:
        r, err = _quiet(lambda q: read_msb(q, trace=trace), p)
        if r:
            first = r
            break
    if first is None:
        say("!! 全都没解出来")
        return 2
    say("[结构链实测] %s" % os.path.basename(first["path"]))
    raw_first, hh = dcx_payload(open(first["path"], "rb").read())
    say("  DCX: kind=%s unc=%d ; 明文头 16B = %s"
        % (hh["kind"], len(raw_first), raw_first[:16].hex(" ")))
    say("  头字段: magic=%r ver=%d hdrSize=%#x enc=%d off64=%#x"
        % (raw_first[:4], _i32(raw_first, 4), _i32(raw_first, 8),
           raw_first[0x0E], raw_first[0x0F]))
    for line in trace:
        say(line)
    a = raw_first.find(b"PARTS_PARAM_ST")
    u = raw_first.find("PARTS_PARAM_ST".encode("utf-16-le"))
    say("  名字串编码实证: ASCII find b'PARTS_PARAM_ST' -> %s ; UTF-16LE find -> %#x"
        % (a, u))
    say("  —— 字节级字段证据 ——")
    for line in evidence_dump(first["path"]):
        say(line)
    say("-" * 78)

    # ---- 全量扫描 ----
    rows, ok, errs = [], 0, []
    parts_total = 0
    param_shapes = {}
    dcx_kinds = {}
    for p in files:
        r, err = _quiet(read_msb, p)
        if r is None:
            errs.append((os.path.basename(p), err))
            continue
        ok += 1
        dcx_kinds[r["dcx_kind"]] = dcx_kinds.get(r["dcx_kind"], 0) + 1
        mp = os.path.basename(p).replace(".msb.dcx", "").replace(".msb", "")
        shape = tuple(n for n, _ in r["params"])
        param_shapes[shape] = param_shapes.get(shape, 0) + 1
        parts_total += len(r["enemies"])
        for e in r["enemies"]:
            rows.append([mp, e["entity_id"], e["npc_id"], e["think_id"], e["chara_id"],
                         e["model"], "%.3f" % e["x"], "%.3f" % e["y"], "%.3f" % e["z"]])

    say("[1] 解析成功: %d / %d  张   (目标 >= 200)" % (ok, len(files)))
    if errs:
        say("    失败 %d 张，样例:" % len(errs))
        for n, e in errs[:5]:
            say("      %s -> %s" % (n, e))
    say("[2] 敌人 part 总数: %d   （均值 %.1f / 张，量级 几十~几百）"
        % (parts_total, parts_total / max(ok, 1)))
    say("    DCX 压缩类型分布: %s" % dcx_kinds)
    say("    param 链形状（出现次数）:")
    for k, v in sorted(param_shapes.items(), key=lambda x: -x[1])[:4]:
        say("      %s  ×%d" % (" → ".join(k), v))

    # ---- 与 regulation 对账 ----
    say("-" * 78)
    say("regulation: %s" % reg)
    npc_ids = load_row_ids(reg, "NpcParam")
    say("    NpcParam 行 id 数: %d" % len(npc_ids))
    hit = miss = 0
    zero = pos_miss = 0
    missing_samples = []
    for r in rows:
        nid = r[2]
        if nid in npc_ids:
            hit += 1
        else:
            miss += 1
            if nid <= 0:
                zero += 1
            else:
                pos_miss += 1
                if len(missing_samples) < 10:
                    missing_samples.append((nid, r[1], r[0]))
    tot = hit + miss
    say("[3] npc_id 命中 NpcParam 的比例: %d / %d = %.2f%%   (目标 >= 90%%)"
        % (hit, tot, 100.0 * hit / max(tot, 1)))
    say("    未命中拆解: npc_id<=0（本来就是\"未指定\"）= %d ；正数但表里没有 = %d"
        % (zero, pos_miss))
    if pos_miss:
        denom = hit + pos_miss
        say("    只算正数 id 的命中率: %d / %d = %.2f%%"
            % (hit, denom, 100.0 * hit / max(denom, 1)))
        say("    未命中样例（npc_id, entity_id, map）:")
        for nid, eid, mp in missing_samples:
            say("      npc_id=%-12d entity_id=%-12d %s" % (nid, eid, mp))

        # 决定性判据：这些 id 到底"表里没有"还是"我的扫描器漏了"？
        # 直接在 NpcParam 原文里数该 id 的 u64 字节出现次数。对照组是几个已知的真实行 id。
        try:
            import enemy_randomizer as _er
            plain = _er.load_plain(reg)
            boff, bsize = _param_body(plain, "NpcParam")
            body = plain[boff:boff + bsize]
            ctrl = [1000000, 20100000, 523090000]
            say("    决定性判据（在 NpcParam 原文里数 u64 字节出现次数）:")
            say("      对照组（已知真实行 id）: %s"
                % ", ".join("%d→%d次" % (c, body.count(struct.pack("<Q", c))) for c in ctrl))
            uniq_miss = sorted({r[2] for r in rows if r[2] not in npc_ids and r[2] > 0})
            cnt = {m: body.count(struct.pack("<Q", m)) for m in uniq_miss}
            absent = [m for m in uniq_miss if cnt[m] == 0]
            present = [m for m in uniq_miss if cnt[m] != 0]
            say("      未命中的 %d 个**唯一**正数 id:" % len(uniq_miss))
            for m in uniq_miss:
                say("        npc_id=%-12d 引用 %-4d 次, 在 NpcParam 原文里出现 %d 次"
                    % (m, sum(1 for r in rows if r[2] == m), cnt[m]))
            if not present:
                say("      => 全部 %d 个在原文里 0 次出现：数据本身就没有这一行，"
                    "既不是字段偏移错、也不是行表扫描器漏" % len(absent))
            else:
                say("      => %d 个确认原文里没有（数据侧缺失）；%d 个在原文里有字节命中 %s，"
                    "后者多为小数值 id 的偶然字节匹配，需单独核" % (len(absent), len(present), present))
        except Exception as e:                                   # noqa: BLE001
            say("      决定性判据跳过（%s）" % e)

    # ---- think_id 独立复核（第二次对账，换一张表）----
    try:
        think_ids = load_row_ids(reg, "NpcThinkParam")
        th_hit = sum(1 for r in rows if r[3] in think_ids)
        th_pos = sum(1 for r in rows if r[3] > 0)
        say("    旁证 think_id: 命中 NpcThinkParam %d/%d = %.2f%%（%d 张表行）"
            % (th_hit, len(rows), 100.0 * th_hit / max(len(rows), 1), len(think_ids)))
    except Exception as e:                                       # noqa: BLE001
        say("    旁证 think_id: 跳过（%s）" % e)

    # ---- model 样例 ----
    mset = sorted({r[5] for r in rows if r[5]})
    say("[4] model 字段: 唯一值 %d 个，样例 %s" % (len(mset), mset[:12]))
    bad_model = [m for m in mset if not (m[:1] == "c" and m[1:5].isdigit())]
    say("    形态不符 cXXXX 的: %d 个 %s" % (len(bad_model), bad_model[:8]))

    # ---- 导出 CSV ----
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["map", "entity_id", "npc_id", "think_id", "chara_id",
                    "model", "x", "y", "z"])
        w.writerows(rows)
    say("-" * 78)
    say("CSV -> %s  (%d 行)" % (out_csv, len(rows)))

    with open(os.path.join(OUT_DIR, os.path.splitext(os.path.basename(out_csv))[0]
                           + ".report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("报告 -> %s" % os.path.join(
        OUT_DIR, os.path.splitext(os.path.basename(out_csv))[0] + ".report.txt"))
    return 0 if ok >= 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
