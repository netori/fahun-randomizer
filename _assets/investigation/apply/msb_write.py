# -*- coding: utf-8 -*-
"""msb_write.py — 「只改定点字段、不动结构」的 MSB(MSBE) 写入器（二期「真·换敌人」的核心）

设计铁律
--------
1. **不新增 / 不删除 / 不移动任何条目**。只把**已有**的敌人 part 里的几个 int32 就地改写：
   typeData 的 ThinkParamID / NPCParamID / TalkID / CharaInitID，以及 Part 基记录的 ModelIndex。
   因为 MSB 内部所有偏移（param 链、条目偏移数组、nameOffset、entityDataOffset、
   typeDataOffset）都是既有的**相对条目起点**偏移或**文件绝对**偏移，就地等长改写
   天然不产生任何偏移漂移 —— 这是本方案安全性的第一来源。
2. **不重写解析器**：读一律走 `msb_read`（只 import，不改它）。
3. **本模块从不写 mod / 游戏目录**：所有产物只落 `investigation/msb_write_probe/`。

DCX 封装
--------
实测（634 张地图，见 report.md）：
  · 全部 634 张的 DCX 前缀长度都是 **76 (0x4C)**，且同一 kind 内除 DCS 的
    unc/comp 两个大小字段外**逐字节相同**：
        +0x00 "DCX\\0" | +0x04 u32BE(0x100=DFLT / 0x11000=KRAK) | +0x08 dcsOff=24
        +0x0C dcpOff=36 | +0x10 dcaOff=68 | +0x14 dataOff=76
        +0x18 "DCS\\0" | +0x1C u32BE unc | +0x20 u32BE comp
        +0x24 "DCP\\0" | +0x28 kind("DFLT"/"KRAK") | +0x2C u32BE 0x20
        +0x30 u8 level(DFLT=9,KRAK=6) + 15×00 + 00 01 01 00
        +0x44 "DCA\\0" | +0x48 u32BE 8
  · 于是最稳的封装 = **克隆原文件的 76 字节前缀**，只改 kind/level/大小三处。
  · `erio.dcx_compress` 写的是 **ZSTD**（不是 DFLT），且 `erio.dcx_decompress`
    不认 DFLT/KRAK —— 所以本模块自带 DFLT(zlib) 与 KRAK(Oodle) 两条封装路，
    解压走 `msb_read.dcx_payload`（它三条路都认）。
"""
import hashlib
import os
import struct
import sys
import tempfile
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import erio       # noqa: E402
import msb_read   # noqa: E402

# ────────────────────────── 常量 ──────────────────────────

KIND_DFLT = "DFLT"
KIND_KRAK = "KRAK"
KIND_ZSTD = "ZSTD"

DCX_HEAD_LEN = 76            # 实测 634/634 一致
OFF_UNK04 = 0x04
OFF_DCS_UNC = 0x1C
OFF_DCS_COMP = 0x20
OFF_DCP_KIND = 0x28
OFF_DCP_LEVEL = 0x30
DCP_DECLARED_SIZE = 0x20
DCP_TAIL = b"\x00\x01\x01\x00"
LEVEL_DFLT = 9               # payload 头 78 da → zlib level 9 / 32K 窗口
LEVEL_KRAK = 6
UNK04_DFLT = 0x00010000      # 实测 529 张 DFLT 全是它
UNK04_KRAK = 0x00011000      # 实测 105 张 KRAK 全是它

# 可改字段 → (表, 取值类型)。off 相对各自子块起点。
EDITABLE = {
    "think_id": ("typeData", msb_read.E_THINK),     # +0x08 i32 ThinkParamID
    "npc_id":   ("typeData", msb_read.E_NPC),       # +0x0C i32 NPCParamID
    "talk_id":  ("typeData", msb_read.E_TALK),      # +0x10 i32 TalkID
    "chara_id": ("typeData", msb_read.E_CHARA),     # +0x18 i32 CharaInitID
    "model":    ("base", msb_read.P_MODELIDX),      # +0x14 i32 ModelIndex
}
# 别名（容忍常见写法）
ALIASES = {
    "npc": "npc_id", "npcparamid": "npc_id", "npc_param_id": "npc_id",
    "think": "think_id", "thinkparamid": "think_id", "think_param_id": "think_id",
    "talk": "talk_id", "talkid": "talk_id",
    "chara": "chara_id", "charaid": "chara_id", "chara_init": "chara_id",
    "chara_init_id": "chara_id", "charainitid": "chara_id",
    "model_index": "model", "model_index_id": "model", "modelid": "model",
}

_ENTITY_DATA_GROUP_OFF = 0x1C       # u32[8] EntityGroupIDs
_ENTITY_DATA_SIZE = 0x3C
_BASE_RECORD_SIZE = 0xC0
_ENEMY_TYPEDATA_SIZE = 0x20

PROBE_DIR = os.path.join(os.path.dirname(_HERE), "msb_write_probe")
TMP_DIR = os.path.join(PROBE_DIR, "_tmp")


class MsbWriteError(Exception):
    """硬错误：调用方给的参数本身不成立。"""


class EditTargetError(MsbWriteError):
    """某个 edits 键定位不到唯一目标（找不到 / 有歧义）。"""


# ────────────────────────── 小工具 ──────────────────────────

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_bytes(path_or_bytes, name_out=None) -> bytes:
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        if name_out is not None:
            name_out.append("<bytes>")
        return bytes(path_or_bytes)
    p = os.fspath(path_or_bytes)
    if name_out is not None:
        name_out.append(p)
    with open(p, "rb") as f:
        return f.read()


# ────────────────────────── DCX：解 / 装 ──────────────────────────

def dcx_unpack(data: bytes):
    """DCX（或裸 MSB）→ (明文 bytes, 头字典或 None)"""
    return msb_read.dcx_payload(data)


def _dflt_compress(raw: bytes, level: int = LEVEL_DFLT) -> bytes:
    """DFLT = 裸 zlib 流（payload 头实测 78 da）。"""
    co = zlib.compressobj(level, zlib.DEFLATED, 15)
    return co.compress(raw) + co.flush()


def _krak_compress(raw: bytes, level: int = LEVEL_KRAK):
    """KRAK = 一段 Oodle Kraken 流。需要游戏自带的 oo2core*.dll。
    返回 (payload, None) 或 (None, 原因字符串)。"""
    try:
        import oodle
    except Exception as e:                                      # noqa: BLE001
        return None, "import oodle 失败: %s" % e
    try:
        dll = oodle.find_dll()
    except Exception as e:                                      # noqa: BLE001
        return None, "oodle.find_dll 失败: %s" % e
    if not dll:
        return None, "找不到 oo2core*.dll（Oodle 压缩不可用）"
    try:
        return oodle.compress(raw, level=level, compressor=8), None
    except Exception as e:                                      # noqa: BLE001
        return None, "Oodle 压缩失败: %s: %s" % (type(e).__name__, e)


def _build_prefix(kind: str, unc: int, comp: int, level: int) -> bytes:
    """从零拼一个 76 字节 DCX 前缀（只在拿不到原文件前缀时用）。"""
    unk04 = UNK04_DFLT if kind.upper() == KIND_DFLT else UNK04_KRAK
    head = b"DCX\0" + struct.pack(">IIIII", unk04, 24, 36, 68, 76)
    dcs = b"DCS\0" + struct.pack(">II", unc, comp)
    dcp = (b"DCP\0" + kind.encode("ascii") + struct.pack(">I", DCP_DECLARED_SIZE)
           + bytes([level]) + b"\0" * 15 + DCP_TAIL)
    dca = b"DCA\0" + struct.pack(">I", 8)
    p = head + dcs + dcp + dca
    if len(p) != DCX_HEAD_LEN:
        raise MsbWriteError("内部错误：拼出的 DCX 前缀 %d 字节 != %d" % (len(p), DCX_HEAD_LEN))
    return p


def dcx_repack(raw: bytes, in_kind=None, out_kind="dflt", orig_prefix=None, level=None):
    """明文 → 新 DCX 字节。

    out_kind: "dflt"（默认）/ "krak" / "same"（尽量保持原 kind）
    orig_prefix: 原文件的 76 字节前缀；给了就克隆它（最稳），只改 kind/level/大小。
    返回 (dcx_bytes, report)；report 里 degraded 记录降级原因。
    """
    w = {"in_kind": (in_kind or "").upper() or None, "out_kind": None,
         "degraded": [], "prefix_source": None, "level": None}
    want = (out_kind or "dflt").lower()
    ik = (in_kind or "").upper()

    if want in ("same", "keep", "orig"):
        want = {KIND_DFLT: "dflt", KIND_KRAK: "krak", KIND_ZSTD: "zstd"}.get(ik, "dflt")
        if want == "zstd":
            w["degraded"].append(
                "原 kind=ZSTD，本模块没有 ZSTD 封装路（erio 那条是给 regulation 用的口径），"
                "已降级为 DFLT")
            want = "dflt"
        elif want == "dflt" and ik not in (KIND_DFLT, ""):
            w["degraded"].append("原 kind=%s 认不出，已降级为 DFLT" % (ik or "?"))
        w["requested_out_kind"] = "same"

    if want == "krak":
        comp, why = _krak_compress(raw, level or LEVEL_KRAK)
        if comp is None:
            w["degraded"].append("out_kind=same 但保持 KRAK 做不到（%s）→ 已降级为 DFLT" % why)
            want = "dflt"
        else:
            kind, lv = KIND_KRAK, (level or LEVEL_KRAK)
    if want == "dflt":
        kind, lv = KIND_DFLT, (level or LEVEL_DFLT)
        comp = _dflt_compress(raw, lv)

    w["out_kind"], w["level"] = kind, lv

    if orig_prefix is not None and len(orig_prefix) >= DCX_HEAD_LEN:
        pre = bytearray(orig_prefix[:DCX_HEAD_LEN])
        pre[OFF_DCP_KIND:OFF_DCP_KIND + 4] = kind.encode("ascii")
        pre[OFF_DCP_LEVEL] = lv
        w["prefix_source"] = "clone-original"
    else:
        pre = bytearray(_build_prefix(kind, 0, 0, lv))
        w["prefix_source"] = "built"
    # unk04 与 kind 严格配套（实测：DFLT 恒 0x10000 / KRAK 恒 0x11000）
    struct.pack_into(">I", pre, OFF_UNK04,
                     UNK04_DFLT if kind == KIND_DFLT else UNK04_KRAK)
    struct.pack_into(">I", pre, OFF_DCS_UNC, len(raw))
    struct.pack_into(">I", pre, OFF_DCS_COMP, len(comp))
    return bytes(pre) + comp, w


# ────────────────────────── MSB：遍历 part ──────────────────────────

def _param_blocks(raw):
    return msb_read.walk_params(raw)[1]


def _find_block(raw, name):
    for b in _param_blocks(raw):
        if b["name"] == name:
            return b
    return None


def iter_parts(raw):
    """PARTS_PARAM_ST 的每个条目 → dict（不筛类型）。"""
    pb = _find_block(raw, "PARTS_PARAM_ST")
    if pb is None:
        return
    n = len(raw)
    for i, o in enumerate(pb["entry_offsets"]):
        if o <= 0 or o + _BASE_RECORD_SIZE > n:
            continue
        name_off = msb_read._i64(raw, o + msb_read.P_NAMEOFF)
        name, _ = msb_read._utf16z(raw, o + name_off) if 0 <= o + name_off < n else ("", 0)
        ent = o + msb_read._i64(raw, o + msb_read.P_ENTITY_DATA_OFF)
        typ = o + msb_read._i64(raw, o + msb_read.P_TYPE_DATA_OFF)
        yield {
            "index": i,
            "off": o,
            "name": name,
            "instance_id": msb_read._i32(raw, o + msb_read.P_INSTANCEID),
            "type": msb_read._u32(raw, o + msb_read.P_TYPE),
            "id": msb_read._i32(raw, o + msb_read.P_ID),
            "model_index": msb_read._i32(raw, o + msb_read.P_MODELIDX),
            "ent_off": ent,
            "type_off": typ,
            "entity_id": msb_read._u32(raw, ent) if 0 <= ent < n - 4 else -1,
        }


def enemy_parts(raw):
    """只留 PartType==2（Enemy）。"""
    return [p for p in iter_parts(raw) if p["type"] == msb_read.PART_TYPE_ENEMY]


def part_fingerprint(raw) -> list:
    """**全类型** part 的逐字段指纹（验收 A 用）。

    每个 part 一条 tuple：位置 + 基记录全字段 + 基记录原始字节哈希 +
    entityData 哈希 + （敌人）typeData 哈希。这是"字段级没变"的可读证据；
    更强的证据是整段明文逐字节相同（见 verify_roundtrip 的 plain_same）。
    """
    models = []
    mb = _find_block(raw, "MODEL_PARAM_ST")
    if mb is not None:
        models = msb_read.read_models(raw, mb)
    n = len(raw)
    out = []
    for p in iter_parts(raw):
        o, ent, typ = p["off"], p["ent_off"], p["type_off"]
        mi = p["model_index"]
        rec = {
            "idx": p["index"], "off": o, "name": p["name"],
            "instance_id": p["instance_id"], "type": p["type"], "id": p["id"],
            "model_index": mi,
            "model": models[mi] if 0 <= mi < len(models) else "",
            "sib": msb_read._i64(raw, o + msb_read.P_SIBOFF),
            "pos": tuple(round(msb_read._f32(raw, o + msb_read.P_POS + 4 * k), 6) for k in range(3)),
            "rot": tuple(round(msb_read._f32(raw, o + msb_read.P_ROT + 4 * k), 6) for k in range(3)),
            "scl": tuple(round(msb_read._f32(raw, o + msb_read.P_SCALE + 4 * k), 6) for k in range(3)),
            "ent_rel": msb_read._i64(raw, o + msb_read.P_ENTITY_DATA_OFF),
            "typ_rel": msb_read._i64(raw, o + msb_read.P_TYPE_DATA_OFF),
            "entity_id": p["entity_id"],
            "groups": struct.unpack_from("<8I", raw, ent + _ENTITY_DATA_GROUP_OFF)
            if 0 <= ent and ent + _ENTITY_DATA_SIZE <= n else None,
            "base_sha": sha256(raw[o:o + _BASE_RECORD_SIZE]),
            "ent_sha": sha256(raw[ent:ent + _ENTITY_DATA_SIZE])
            if 0 <= ent and ent + _ENTITY_DATA_SIZE <= n else None,
            "typ_sha": sha256(raw[typ:typ + _ENEMY_TYPEDATA_SIZE])
            if p["type"] == msb_read.PART_TYPE_ENEMY and 0 <= typ and typ + _ENEMY_TYPEDATA_SIZE <= n else None,
        }
        if p["type"] == msb_read.PART_TYPE_ENEMY and 0 <= typ < n - 0x20:
            rec["think_id"] = msb_read._i32(raw, typ + msb_read.E_THINK)
            rec["npc_id"] = msb_read._i32(raw, typ + msb_read.E_NPC)
            rec["talk_id"] = msb_read._i32(raw, typ + msb_read.E_TALK)
            rec["chara_id"] = msb_read._i32(raw, typ + msb_read.E_CHARA)
        out.append(rec)
    return out


# ────────────────────────── edits 归一 ──────────────────────────

def _norm_field(k):
    kk = str(k).strip().lower()
    kk = ALIASES.get(kk, kk)
    return kk


def _norm_edits(edits):
    """{key: {字段: 值}} → [(key, {规范字段: 值})]，顺带收集未知字段。"""
    if not edits:
        return [], []
    if isinstance(edits, (list, tuple)):
        edits = dict(edits)
    if not isinstance(edits, dict):
        raise MsbWriteError("edits 必须是 dict 或 (key, value) 序列，收到 %r" % type(edits))
    norm, bad = [], []
    for key, spec in edits.items():
        if not isinstance(spec, dict):
            raise MsbWriteError("edits[%r] 必须是 dict，收到 %r" % (key, type(spec)))
        fs = {}
        for k, v in spec.items():
            nk = _norm_field(k)
            if nk not in EDITABLE:
                bad.append((key, k))
                continue
            if not isinstance(v, int) or isinstance(v, bool):
                raise MsbWriteError("edits[%r][%r] 必须是 int，收到 %r" % (key, k, v))
            if not (-2 ** 31 <= v < 2 ** 31):
                raise MsbWriteError("edits[%r][%r]=%d 超出 i32 范围" % (key, k, v))
            fs[nk] = v
        norm.append((key, fs))
    return norm, bad


# ────────────────────────── 核心：patch ──────────────────────────

def patch_ex(path_or_bytes, edits=None, out_kind="dflt", template=None,
             allow_multi=False, strict=False, level=None):
    """只改定点字段、不动结构。返回 (新 DCX bytes, 报告 dict)。

    参数
    ----
    path_or_bytes : 文件路径 或 原始 DCX/裸 MSB 字节
    edits         : {key: {"npc_id":…, "think_id":…, "talk_id":…, "chara_id":…, "model":…}}
                    key = int      → 按 **EntityID**（0 也算一个合法 id）定位
                          str      → 按 **part 名字**（如 "c0000_9026"）
                          ("idx",N) → 按 PARTS_PARAM_ST 的**条目序号**（最兜底、永远唯一）
                    ⚠ 实测：634 张图里 **447 张**存在"多个敌人 part 共用同一 EntityID"，
                      所以 EntityID 只在部分图上唯一；真·换敌人时应先用 `enemy_parts()`
                      枚举，再按 part 名或条目序号寻址。
                    只改**给了**的字段；没给的字段一个字节都不动。
    out_kind      : "dflt"（默认）/"krak"/"same"
    template      : 可选的"原 DCX"，用它克隆 76 字节前缀（不给就用被 patch 的那份的）
    allow_multi   : EntityID 命中多个 part 时，False=报 issue 且**不改**；True=全部改
    strict        : True 时任何 issue 直接抛 EditTargetError
    """
    src_name = []
    data = _as_bytes(path_or_bytes, src_name)
    raw, hdr = dcx_unpack(data)
    if hdr is None and raw[:4] != msb_read.MSBE_MAGIC:
        raise MsbWriteError("既不是 DCX 也不是 MSB：%r" % (src_name[0] if src_name else "?"))
    in_kind = (hdr or {}).get("kind")

    buf = bytearray(raw)
    n = len(buf)
    parts = enemy_parts(raw)
    by_eid, by_name = {}, {}
    for p in parts:
        by_eid.setdefault(p["entity_id"], []).append(p)
        by_name.setdefault(p["name"], []).append(p)

    norm, bad = _norm_edits(edits)
    rep = {
        "src": src_name[0] if src_name else "<bytes>",
        "in_kind": in_kind, "enemy_parts": len(parts),
        "plain_size": len(raw), "plain_sha256_before": sha256(raw),
        "requested": len(norm), "applied": [], "issues": [], "degraded": [],
        "unknown_fields": [{"key": k, "field": f} for k, f in bad],
    }
    for k, f in bad:
        rep["issues"].append({"code": "unknown-field", "key": k,
                              "detail": "字段 %r 不可改；可改的是 %s" % (f, sorted(EDITABLE))})

    for key, fs in norm:
        if isinstance(key, str):
            hits = by_name.get(key, [])
            how = "part-name"
        elif isinstance(key, tuple) and len(key) == 2 and str(key[0]).lower() in ("idx", "index"):
            # ("idx", N) —— 按 PARTS_PARAM_ST 条目序号寻址（EntityID / part 名都可能重复时的兜底）
            try:
                want_idx = int(key[1])
            except (TypeError, ValueError):
                want_idx = -1
            hits = [p for p in parts if p["index"] == want_idx]
            how = "entry-index"
        elif isinstance(key, int) and not isinstance(key, bool):
            hits = by_eid.get(key & 0xFFFFFFFF, []) if key >= 0 else []
            how = "entity-id"
        else:
            rep["issues"].append({"code": "bad-key", "key": repr(key),
                                  "detail": "键必须是 int(EntityID) / str(part 名) / "
                                            "('idx', 条目序号)"})
            continue
        if not hits:
            rep["issues"].append({"code": "enemy-part-not-found", "key": key,
                                  "detail": "本图没有 Enemy part 命中这个 key"})
            continue
        if len(hits) > 1 and not allow_multi:
            rep["issues"].append({
                "code": "ambiguous-key", "key": key,
                "detail": "命中 %d 个 Enemy part（%s），本轮**没有改**；"
                          "用 part 名作 key 或 allow_multi=True 才能定下来"
                          % (len(hits), ", ".join(h["name"] for h in hits[:6]))})
            continue
        for p in hits:
            ch = {}
            for f, v in fs.items():
                tbl, off = EDITABLE[f]
                base = p["type_off"] if tbl == "typeData" else p["off"]
                a = base + off
                if a < 0 or a + 4 > n:
                    rep["issues"].append({"code": "field-out-of-range", "key": key,
                                          "detail": "%s @%#x 越界" % (f, a)})
                    continue
                old = msb_read._i32(buf, a)
                if old != v:
                    struct.pack_into("<i", buf, a, v)
                ch[f] = [old, v]
            rep["applied"].append({"key": key, "via": how, "entity_id": p["entity_id"],
                                   "part_name": p["name"], "entry_off": p["off"],
                                   "type_off": p["type_off"], "changes": ch})

    rep["plain_sha256_after"] = sha256(bytes(buf))
    rep["plain_changed"] = rep["plain_sha256_after"] != rep["plain_sha256_before"]

    if strict and rep["issues"]:
        raise EditTargetError("; ".join("%s(%s)" % (i["code"], i.get("key")) for i in rep["issues"]))

    pre = None
    if template is not None:
        tdata = _as_bytes(template)
        _traw, th = dcx_unpack(tdata)
        pre = tdata[:DCX_HEAD_LEN] if th else None
    elif hdr is not None:
        pre = data[:DCX_HEAD_LEN]

    out, w = dcx_repack(bytes(buf), in_kind=in_kind, out_kind=out_kind,
                        orig_prefix=pre, level=level)
    rep.update(w)
    rep["dcx_size"] = len(out)
    rep["comp"] = len(out) - DCX_HEAD_LEN
    rep["dcx_sha256"] = sha256(out)
    return out, rep


def patch(path_or_bytes, edits=None, out_kind="dflt", template=None,
          allow_multi=False, strict=False, level=None) -> bytes:
    """同 patch_ex，但只返回新的 DCX 字节（二期主入口）。"""
    return patch_ex(path_or_bytes, edits, out_kind=out_kind, template=template,
                    allow_multi=allow_multi, strict=strict, level=level)[0]


# ────────────────────────── 自校验：写出来再读一遍 ──────────────────────────

def read_back(data: bytes, tmp_dir=None):
    """把写出来的字节落临时文件 -> 调 msb_read.read_msb 再解析一遍。
    临时文件只在 investigation/msb_write_probe/_tmp/ 下建，用完即删。"""
    d = tmp_dir or TMP_DIR
    os.makedirs(d, exist_ok=True)
    fd, p = tempfile.mkstemp(suffix=".msb.dcx", dir=d)
    os.close(fd)
    try:
        with open(p, "wb") as f:
            f.write(data)
        return msb_read.read_msb(p)
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def verify_roundtrip(path, out_kind="dflt", template=None, level=None):
    """一张图的完整往返验收：读 → patch(空 edits) → 重封装 → 再读。
    返回报告 dict；`ok` 表示**所有**判据都过。"""
    with open(path, "rb") as f:
        data = f.read()
    raw0, hdr0 = dcx_unpack(data)
    fp0 = part_fingerprint(raw0)
    out, rep = patch_ex(data, {}, out_kind=out_kind, template=template, level=level)
    raw1, hdr1 = dcx_unpack(out)
    fp1 = part_fingerprint(raw1)
    rep.update({
        "file": os.path.basename(path),
        "plain_same": raw0 == raw1,
        "plain_len_same": len(raw0) == len(raw1),
        "parts_before": len(fp0), "parts_after": len(fp1),
        "fields_same": fp0 == fp1,
        "read_back_kind": (hdr1 or {}).get("kind"),
        "read_back_ok": hdr1 is not None,
    })
    if not rep["fields_same"]:
        diff = [i for i, (a, b) in enumerate(zip(fp0, fp1)) if a != b][:3]
        rep["first_diff_indexes"] = diff
        rep["first_diff"] = [(fp0[i], fp1[i]) for i in diff]
    rb = read_back(out)                                        # 真正走 msb_read.read_msb
    en0 = msb_read.read_msb(path)["enemies"]
    rep["read_msb_enemies_same"] = en0 == rb["enemies"]
    rep["read_msb_enemies"] = len(en0)
    rep["read_back_dcx_kind"] = rb["dcx_kind"]
    rep["ok"] = bool(rep["plain_same"] and rep["fields_same"]
                     and rep["parts_before"] == rep["parts_after"]
                     and rep["read_msb_enemies_same"] and rep["read_back_ok"])
    return rep


# ────────────────────────── CLI ──────────────────────────

def _maps():
    import modpaths
    try:
        mod = (os.environ.get("CONVERGENCE_MOD_ROOT")
               or modpaths.require_mod_root(os.path.dirname(os.path.abspath(__file__))))
    except RuntimeError as e:
        raise MsbWriteError(str(e))
    d = os.path.join(mod, "mod", "map", "MapStudio")
    if not os.path.isdir(d):
        raise MsbWriteError("找不到地图目录: %s" % d)
    import glob
    return sorted(glob.glob(os.path.join(d, "*.msb.dcx")))


def accept_a(out_kind="dflt", limit=0, verbose=False):
    files = _maps()
    if limit:
        files = files[:limit]
    ok = bad = 0
    tpl = {}
    rows = []
    for i, p in enumerate(files, 1):
        try:
            r = verify_roundtrip(p, out_kind=out_kind)
        except Exception as e:                                  # noqa: BLE001
            bad += 1
            rows.append((i, os.path.basename(p), "EXC", "0", "0", True, "%s: %s" % (type(e).__name__, e)))
            print("  [%3d/%d] %-26s **异常** %s: %s" % (i, len(files), os.path.basename(p), type(e).__name__, e))
            continue
        if r["ok"]:
            ok += 1
        else:
            bad += 1
        rows.append((i, r["file"], r["in_kind"], r["parts_before"], r["parts_after"],
                     r["plain_same"], "fields_same=%s read_msb=%s out=%s%s" % (
                         r["fields_same"], r["read_msb_enemies_same"], r["out_kind"],
                         " 降级:%s" % ";".join(r["degraded"]) if r["degraded"] else "")))
        if verbose or not r["ok"] or i % 50 == 0 or i == len(files):
            print("  [%3d/%d] %-26s %s parts=%d/%d plain_same=%s fields_same=%s rmsb=%s -> %s %d B"
                  % (i, len(files), r["file"], r["in_kind"], r["parts_before"], r["parts_after"],
                     r["plain_same"], r["fields_same"], r["read_msb_enemies_same"],
                     r["out_kind"], r["dcx_size"]))
        tpl[r["in_kind"]] = tpl.get(r["in_kind"], 0) + 1
    print("\n[验收 A / out_kind=%s] 通过 %d / %d   （失败 %d）" % (out_kind, ok, len(files), bad))
    print("    输入 kind 分布: %s" % tpl)
    return {"files": len(files), "ok": ok, "bad": bad, "kinds": tpl, "rows": rows}


def accept_b(map_name="m10_00_00_00", out_dir=None, out_kind="dflt"):
    """真换一个敌人：m10_00_00_00 里两个实体的 npc_id 互换。"""
    import glob
    out_dir = out_dir or PROBE_DIR
    os.makedirs(out_dir, exist_ok=True)
    src = next((p for p in glob.glob(os.path.join(os.path.dirname(_maps()[0]), "*.msb.dcx"))
                if os.path.basename(p).startswith(map_name)), None)
    if src is None:
        raise MsbWriteError("找不到 %s*.msb.dcx" % map_name)

    # 1) NpcParam 行表（必须是真行）
    import enemy_randomizer as er
    units = er.load_units(er.load_plain())
    with open(src, "rb") as f:
        data = f.read()
    raw, _h = dcx_unpack(data)
    parts = enemy_parts(raw)

    # 2) 挑两个 EntityID 在本图**唯一**、且 npc_id 都在 NpcParam 里的敌人
    seen = {}
    for p in parts:
        seen.setdefault(p["entity_id"], []).append(p)
    cands = []
    for p in parts:
        if len(seen[p["entity_id"]]) != 1 or p["entity_id"] <= 0:
            continue
        nid = msb_read._i32(raw, p["type_off"] + msb_read.E_NPC)
        if nid in units:
            cands.append((p, nid))
    print("[验收 B] 候选（EntityID 唯一 + npc_id 是 NpcParam 真行）: %d 个" % len(cands))
    if len(cands) < 2:
        raise MsbWriteError("候选不足 2 个，换一张图")
    # 取前两个 npc_id 不同、part 名也不同的
    a = cands[0]
    b = next(c for c in cands[1:] if c[1] != a[1] and c[0]["name"] != a[0]["name"])
    ka, kb = a[0]["entity_id"], b[0]["entity_id"]
    na, nb = a[1], b[1]
    print("  A: entity_id=%-12d part=%-14s npc_id=%d  -> %d" % (ka, a[0]["name"], na, nb))
    print("  B: entity_id=%-12d part=%-14s npc_id=%d  -> %d" % (kb, b[0]["name"], nb, na))

    # 3) 互换
    out, rep = patch_ex(data, {ka: {"npc_id": nb}, kb: {"npc_id": na}}, out_kind=out_kind)
    dst = os.path.join(out_dir, os.path.basename(src).replace(".msb.dcx", "_patched.msb.dcx"))
    with open(dst, "wb") as f:
        f.write(out)

    # 4) 读回来逐字段比对
    raw1, _h1 = dcx_unpack(out)
    f0, f1 = part_fingerprint(raw), part_fingerprint(raw1)
    diffs = [(i, x, y) for i, (x, y) in enumerate(zip(f0, f1)) if x != y]
    # 用条目偏移做键（patch 不动任何偏移，所以两次的 off 一一对应）
    by_off1 = {x["off"]: x for x in f1}
    npc_changed = []
    for x, y in zip(f0, f1):
        if x.get("npc_id") != y.get("npc_id"):
            npc_changed.append((y["idx"], y["name"], x.get("npc_id"), y.get("npc_id")))
    other_changed = [d for d in diffs if (d[1].get("npc_id") == d[2].get("npc_id"))]
    got_a = (by_off1.get(a[0]["off"]) or {}).get("npc_id")
    got_b = (by_off1.get(b[0]["off"]) or {}).get("npc_id")
    # 逐字节差异：应当**恰好**只有那 8 个字节（每个实体 typeData 的 4 字节 npc_id）
    bd = [i for i in range(min(len(raw), len(raw1))) if raw[i] != raw1[i]]
    expect = sorted([a[0]["type_off"] + msb_read.E_NPC, a[0]["type_off"] + msb_read.E_NPC + 3,
                     b[0]["type_off"] + msb_read.E_NPC, b[0]["type_off"] + msb_read.E_NPC + 3])
    rb = read_back(out)
    res = {
        "src": src, "dst": dst, "A": {"entity_id": ka, "part": a[0]["name"], "from": na, "to": nb, "got": got_a},
        "B": {"entity_id": kb, "part": b[0]["name"], "from": nb, "to": na, "got": got_b},
        "swapped": got_a == nb and got_b == na,
        "npc_changed": npc_changed, "other_fields_changed": len(other_changed),
        "parts_before": len(f0), "parts_after": len(f1),
        "plain_changed": raw != raw1, "dcx_size": len(out), "in_kind": rep["in_kind"],
        "out_kind": rep["out_kind"], "degraded": rep["degraded"],
        "read_back_enemies": len(rb["enemies"]),
        "read_back_npc_a": next((e["npc_id"] for e in rb["enemies"]
                                 if e["entity_id"] == ka), None),
        "read_back_npc_b": next((e["npc_id"] for e in rb["enemies"]
                                 if e["entity_id"] == kb), None),
        "units_total": len(units), "npc_id_in_units": [na in units, nb in units],
        "byte_diff_count": len(bd),
        "byte_diff_span": [min(bd), max(bd)] if bd else None,
        "byte_diff_expect": [min(expect), max(expect)],
        "byte_diff_is_exact": bool(bd) and min(bd) >= min(expect) and max(bd) <= max(expect)
                              and len(bd) <= 8,
        "diff_entry_offset_a": a[0]["type_off"], "diff_entry_offset_b": b[0]["type_off"],
    }
    res["ok"] = bool(res["swapped"] and res["other_fields_changed"] == 0
                     and len(npc_changed) == 2 and res["parts_before"] == res["parts_after"]
                     and res["read_back_npc_a"] == nb and res["read_back_npc_b"] == na
                     and res["byte_diff_is_exact"])
    print("  互换生效: %s   逐字段只变了 npc_id 的 part: %d   其它字段变动: %d"
          % (res["swapped"], len(npc_changed), res["other_fields_changed"]))
    print("  逐字节差异: %d 个字节，范围 [%d, %d]（期望落在 [%d, %d] 内 = 两个 npc_id 字段）"
          % (len(bd), res["byte_diff_span"][0] if bd else -1,
             res["byte_diff_span"][1] if bd else -1, min(expect), max(expect)))
    print("  part 数 %d -> %d   产物: %s (%d B, %s)"
          % (res["parts_before"], res["parts_after"], dst, len(out), res["out_kind"]))
    if res["degraded"]:
        print("  降级: %s" % res["degraded"])
    print("  验收 B: %s" % ("通过" if res["ok"] else "**未通过**"))
    return res


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    limit = 0
    kink = "dflt"
    same_too = True
    for i, a in enumerate(argv):
        if a == "--limit":
            limit = int(argv[i + 1])
        elif a == "--kind":
            kink = argv[i + 1]
        elif a == "--no-same":
            same_too = False
    print("=" * 78)
    print("msb_write 验收   地图目录: %s" % os.path.dirname(_maps()[0]))
    print("=" * 78)
    print("\n【验收 A】全量往返：读 -> patch(空 edits) -> 重封装(%s) -> 再读" % kink)
    ra = accept_a(out_kind=kink, limit=limit)
    if same_too and not limit:
        print("\n【验收 A2】同上，但 out_kind=\"same\"（DFLT 保持 DFLT / KRAK 用 Oodle 保持 KRAK）")
        ra2 = accept_a(out_kind="same")
    else:
        ra2 = None
    print("\n【验收 B】真换一个敌人（m10_00_00_00：两个实体 npc_id 互换）")
    rb = accept_b(out_kind=kink)
    print("\n" + "=" * 78)
    print("汇总: A %d/%d 通过%s ; B %s"
          % (ra["ok"], ra["files"],
             ("  A2(same) %d/%d" % (ra2["ok"], ra2["files"])) if ra2 else "",
             "通过" if rb["ok"] else "未通过"))
    return 0 if ra["bad"] == 0 and rb["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
