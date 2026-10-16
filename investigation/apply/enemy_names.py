# -*- coding: utf-8 -*-
"""FMG 解析（读出**真 id**）+ 敌人名单表（NpcParam × NpcName）导出。

为什么要重写
------------
`_boss_taxonomy.fmg_parse` 只扫了 u64 字符串偏移表，然后**拿数组下标当 id**。
下标当然对不上 `NpcParam.nameId`（真 id 在 1 万~9 亿区间），于是全查不到名字。

实测出来的 FMG v2 结构（本目录 78 个 FMG **全部吻合**，见 main() 自检）
--------------------------------------------------------------------
    0x00  u32   版本（0x00020000）
    0x04  u32   文件大小
    0x08  u32   固定 1
    0x0C  u32   id 表记录数                                   n_rec
    0x10  u32   字符串槽数（= u64 偏移表的项数）               n_str
    0x14  u32   固定 255
    0x18  u32   u64 字符串偏移表在文件内的绝对偏移             tab
    0x1C  12B   0
    0x28  id 表起点：n_rec 条 × **16 字节**
              +0x0  u32  字符串槽下标 —— 指向 tab 那张 u64 表
              +0x4  u32  **id 区间下界**
              +0x8  u32  **id 区间上界**（>= 下界）
              +0xC  u32  0
    tab          u64 × n_str   字符串绝对偏移（0 = 该槽没有文本）
    tab+8*n_str  字符串正文区：UTF-16LE、以 \\0\\0 结尾

**一条记录覆盖的是一段 id 区间 [下界, 上界]，不是单个 id。** 三条证据（main() 每次重算）：
  1. 316 条记录里 0 条出现「上界 < 下界」；跨度中位数 2、p90 10、最大 37 —— 都是小段；
  2. 按区间排序后**两两不重叠**（0 处重叠）—— 只有真区间才会这么干净；
  3. `NpcParam` 引用的 id 落在区间**内部**而不是端点，例如记录 (140900,140906) →「“黑夜剑士”约兰」，
     而 NpcParam 行引用的正是 140903；(141500,141504) →「穆尔」而引用的是 141502。
  覆盖率佐证：只取端点时 750 个非零 nameId 里命中 551；按区间展开后命中 **736（98.1%）**。

两个可验证的结构关系（main() 每次都会重算，不是断言）：
    (0x18 - 0x28) / 16 == 0x0C           即 id 表长度
    0x18 + 8 * 0x10   == 正文区起点       即偏移表尾接正文

注意 id 表**有洞**：字符串槽下标不是连续 1,2,3…（例如 NpcName 是 1..5 之后跳到 16），
所以必须老老实实读「槽下标」那一列，不能拿记录序号当槽号。

导出
----
`main()` 会把 `NpcParam` 全表写成 `investigation/enemy_table.csv`。
"""
import csv
import os
import struct
import sys

WS = os.path.dirname(os.path.abspath(__file__))
if WS not in sys.path:
    sys.path.insert(0, WS)

import erio                      # noqa: E402
import _boss_taxonomy as bt      # noqa: E402

ROOT = os.path.abspath(os.path.join(WS, os.pardir, os.pardir, os.pardir))
DEFAULT_MOD = "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"
CSV_OUT = os.path.normpath(os.path.join(WS, os.pardir, "enemy_table.csv"))

# ── FMG v2 头字段 ─────────────────────────────────────────────────────────
H_REC_COUNT = 0x0C        # id 表记录数
H_STR_COUNT = 0x10        # 字符串槽数
H_OFF_TABLE = 0x18        # u64 偏移表偏移
ID_TABLE = 0x28           # id 表起点
ID_REC_SIZE = 16          # 每条 16 字节
MAX_RANGE = 4096          # 区间展开上限（防脏记录把表撑爆）

NPCNAME_FMGS = ("NpcName", "NpcName_dlc01", "NpcName_dlc02")
DLC_PRIORITY = ("NpcName", "NpcName_dlc01", "NpcName_dlc02")   # 后面的盖前面的

_INT_TYPES = ("u8", "i8", "s8", "dummy8", "u16", "i16", "s16",
              "u32", "i32", "s32", "u64", "i64", "s64")


# ── 小工具 ───────────────────────────────────────────────────────────────
def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def _read_utf16(buf, off):
    """从绝对偏移读一条 UTF-16LE 字符串（读到 \\0\\0 为止）。0 / 越界 / 空串 → None"""
    end = len(buf)
    if off <= 0 or off + 2 > end:
        return None
    j = off
    while j + 1 < end and buf[j:j + 2] != b"\x00\x00":
        j += 2
    if j == off:
        return None
    try:
        s = buf[off:j].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    return s or None


# ── 核心：FMG → 真 id ────────────────────────────────────────────────────
def fmg_records(data):
    """FMG → [(槽下标, id 下界, id 上界, 文本)]。文本为 None 的条目（空槽 / 偏移为 0）也会给出。"""
    n = len(data)
    if n < ID_TABLE + ID_REC_SIZE:
        return []
    n_rec = _u32(data, H_REC_COUNT)
    n_str = _u32(data, H_STR_COUNT)
    tab = _u32(data, H_OFF_TABLE)
    if not (ID_TABLE <= tab <= n) or n_str > 0x800000:
        return []
    offs = []
    for i in range(n_str):
        p = tab + 8 * i
        offs.append(_u64(data, p) if p + 8 <= n else 0)
    out = []
    for k in range(n_rec):
        p = ID_TABLE + ID_REC_SIZE * k
        if p + ID_REC_SIZE > tab:
            break
        slot, lo, hi, _unk = (_u32(data, p), _u32(data, p + 4),
                              _u32(data, p + 8), _u32(data, p + 12))
        text = _read_utf16(data, offs[slot]) if slot < n_str else None
        out.append((slot, lo, hi, text))
    return out


def fmg_ranges(data):
    """FMG → [(id 下界, id 上界, 文本)]，只留真的有文本的记录。区间合法性在这里就夹好。"""
    out = []
    for _slot, lo, hi, text in fmg_records(data):
        if not text or not lo:
            continue
        if hi < lo or hi - lo > MAX_RANGE:
            hi = lo                      # 上界不合法 → 退化成一个 id
        out.append((lo, hi, text))
    return out


def parse_fmg(data, expand_ranges=True):
    """FMG → {真 id: 文本}。键是真 id（NpcParam.nameId 那一套），不是数组下标。

    `expand_ranges=True`（默认）按实测语义把每条记录的 **[下界, 上界]** 整段铺开 ——
    这是必须的：NpcParam 引用的是区间内部的 id（140903 落在 (140900,140906) 里），
    只取端点会漏掉 750 个非零 nameId 里的 185 个。
    `expand_ranges=False` 只取端点（下界；下界为 0 时取上界），给需要严格单键的场景。
    """
    recs = list(fmg_records(data))
    # ⚠️ 区间语义（2026-10-16 修正）：一条 [lo, hi] 记录里，**每个 id 各占一个字符串槽**，
    #    不是整段共用第一条文本。旧写法 `out[k] = text` 会让整段都显示第一条的名字 ——
    #    实测后果：NpcName 里 42 个 name_id 的名字是错的（902130002 应该是「“恶兆王”蒙葛特」，
    #    旧写法给的是区间的第一条「“恶兆妖鬼”玛尔基特」；902110001 应该是「“黑剑”玛利喀斯」）。
    #    自检：Σ(hi-lo+1) == 字符串槽数（GoodsName_dlc01 1549==1549、NpcName_dlc01 105==105）。
    # ⚠️ 关键：id 记录只有 n_rec 条（NpcName 实测 265），而字符串槽有 n_str 个（626）。
    #    区间记录只给"起始槽"，区间里其余 id 的文本要**按槽号直接读偏移表** ——
    #    不能从记录里找（那些槽根本没有记录）→ 这就是之前整段共用第一条文本的根因。
    n = len(data)
    _tab = _u32(data, H_OFF_TABLE)
    _nstr = _u32(data, H_STR_COUNT)

    def _text_at(slot):
        if slot >= _nstr:
            return None
        q = _tab + 8 * slot
        if q + 8 > n:
            return None
        off = _u64(data, q)
        return _read_utf16(data, off) if off else None

    by_slot = {rec[0]: (rec[3] or _text_at(rec[0])) for rec in recs}
    out = {}
    for slot, lo, hi, text in recs:
        if not text:
            continue
        if not expand_ranges:
            k = lo or hi
            if k:
                out.setdefault(k, text)
            continue
        if not lo:
            continue
        if hi < lo or hi - lo > MAX_RANGE:
            hi = lo                      # 上界不合法 → 不铺开，不猜
        for k in range(lo, hi + 1):
            t = by_slot.get(slot + (k - lo)) or _text_at(slot + (k - lo))
            if t:
                out.setdefault(k, t)
    return out


def fmg_structure_ok(data):
    """自检用：(id 表长度自洽, 偏移表不越界)"""
    n = len(data)
    if n < ID_TABLE + ID_REC_SIZE:
        return False, False
    n_rec = _u32(data, H_REC_COUNT)
    n_str = _u32(data, H_STR_COUNT)
    tab = _u32(data, H_OFF_TABLE)
    return ((tab - ID_TABLE) // ID_REC_SIZE == n_rec,
            bool(tab) and tab + 8 * n_str <= n)


# ── 读 mod 里的 msgbnd ───────────────────────────────────────────────────
def default_mod_dir():
    return os.environ.get("MOD_ROOT") or os.path.join(ROOT, DEFAULT_MOD)


def find_msgbnd(mod_dir=None):
    """挑一个 msgbnd：优先 zhocn，其次文件名带 item 的。"""
    mod_dir = mod_dir or default_mod_dir()
    msg = os.path.join(mod_dir, "mod", "msg")
    cands = []
    if os.path.isdir(msg):
        for lang in sorted(os.listdir(msg)):
            d = os.path.join(msg, lang)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith(".msgbnd.dcx"):
                    pref = (0 if lang.lower() == "zhocn" else 1,
                            0 if "item" in fn.lower() else 1, fn)
                    cands.append((pref, os.path.join(d, fn)))
    cands.sort()
    return cands[0][1] if cands else None


def read_msgbnd_files(path):
    import native_guide as ng
    bnd, _header, _raw = ng.read_msgbnd(path)
    return bnd.files


def _stem(internal):
    b = os.path.basename(internal.replace("\\", "/"))
    return b[:-4] if b.lower().endswith(".fmg") else None


def names_from_files(files, expand_ranges=True):
    """已解开的 msgbnd 文件表 → 嵌套名字表（只取 NpcName 系列）"""
    out = {}
    for internal, blob in files:
        stem = _stem(internal)
        if stem in NPCNAME_FMGS:
            out[stem] = parse_fmg(blob, expand_ranges=expand_ranges)
    return out


def load_names(mod_dir=None, msgbnd_path=None, expand_ranges=True):
    """读 NpcName / NpcName_dlc01 / NpcName_dlc02 三个 FMG。

    **返回嵌套 dict**：``{文件主名: {真 id: 文本}}``，例如
    ``{"NpcName": {110000: "梅琳娜", ...}, "NpcName_dlc01": {...}, ...}``

    为什么不合并成一个平铺的 ``{id: 文本}``：三个文件的 id 空间**会重叠**
    （基础包与 DLC 各编各的），平铺必然互相覆盖，而且覆盖顺序无法自证。
    嵌套返回把每个文件的事实分开保留；要平铺请用 `merge_names()`，它会显式报冲突。
    """
    mod_dir = mod_dir or default_mod_dir()
    path = msgbnd_path or find_msgbnd(mod_dir)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("找不到 msgbnd：%s" % path)
    return names_from_files(read_msgbnd_files(path), expand_ranges)


def merge_names(nested):
    """嵌套名字表 → (平铺 ``{id: 文本}``, 冲突清单)。

    覆盖顺序 = DLC_PRIORITY 的先后（后面的盖前面的）；冲突**逐条返回**而不是默默吞掉。
    冲突项 = (id, 旧文本, 来源文件, 新文本)。
    """
    flat, conflicts = {}, []
    for stem in DLC_PRIORITY:
        for rid, text in nested.get(stem, {}).items():
            if rid in flat and flat[rid] != text:
                conflicts.append((rid, flat[rid], stem, text))
            flat[rid] = text
    return flat, conflicts


# ── Paramdex：位域与字段读取 ─────────────────────────────────────────────
def bit_field_index(fields, name):
    """位域的 (字节偏移, 位序号)。

    `paramdef_fields` 只给 ``bit_off // 8``（同字节的位域共享同一个偏移且 size=0），
    所以位序号要自己数：同字节组内第 0 个 = bit0。
    实测 0x15d 那一组是 isSoulGetByBoss(b0), isBulletOwner_byObject(b1),
    isUseLowHitFootIk(b2), isCalculatePvPDamage(b3), isHostSyncChr(b4),
    isSkipWeakDamageAnim(b5), isKeepHitOnRide(b6), isSpCollide(b7)。
    """
    cur_off, bit = None, 0
    for nm, typ, off, size in fields:
        if size == 0 and typ in _INT_TYPES:
            if off != cur_off:
                cur_off, bit = off, 0
            if nm == name:
                return off, bit
            bit += 1
        else:
            cur_off, bit = None, 0
    return None


_FMT = {"u8": "<B", "i8": "<b", "s8": "<b", "dummy8": "<B",
        "u16": "<H", "i16": "<h", "s16": "<h",
        "u32": "<I", "i32": "<i", "s32": "<i",
        "f32": "<f", "u64": "<Q", "i64": "<q", "s64": "<q", "f64": "<d"}


def npcparam_layout():
    """NpcParam 的 (字段表, 行字节数, 字段名→(偏移, 类型, 大小))"""
    fields, row_size = bt.paramdef_fields("NpcParam")
    fmap = {}
    for nm, typ, off, size in fields:
        fmap.setdefault(nm, (off, typ, size))
    return fields, row_size, fmap


def _open_npcparam(mod_dir):
    """→ (regulation 明文, NpcParam 在明文里的起点, 长度)"""
    import native_apply as na
    reg = os.path.join(mod_dir, "mod", "regulation.bin")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(reg)))
    for name, off, size in na.bnd4_entries(plain):
        if os.path.basename(name.replace("\\", "/")).lower() == "npcparam.param":
            return plain, off, size
    raise RuntimeError("regulation.bin 里没找到 NpcParam.param")


def export_enemy_table(mod_dir=None, out_csv=None, quiet=False):
    """把 NpcParam 全表写成 CSV（列固定），并返回统计 dict。"""
    mod_dir = mod_dir or default_mod_dir()
    out_csv = out_csv or CSV_OUT

    files = read_msgbnd_files(find_msgbnd(mod_dir))
    nested = names_from_files(files, expand_ranges=True)
    names, conflicts = merge_names(nested)
    # 只取端点的版本：用来量化「区间展开」到底多救回多少行（诚实报告用）
    flat_ep, _ = merge_names(names_from_files(files, expand_ranges=False))

    plain, p_off, p_size = _open_npcparam(mod_dir)
    fields, row_size, fmap = npcparam_layout()
    rows = bt.scan_rows(plain, p_off, p_size)
    boss_bf = bit_field_index(fields, "isSoulGetByBoss")

    def rd(base, nm):
        f = fmap.get(nm)
        if not f:
            return None
        off, typ, size = f
        if size == 0:                       # 位域：用 bit()
            return None
        fmt = _FMT.get(typ)
        if fmt is None:
            return None
        p = p_off + base + off
        if p + struct.calcsize(fmt) > len(plain):
            return None
        return struct.unpack_from(fmt, plain, p)[0]

    def bit(base):
        if not boss_bf:
            return None
        off, b = boss_bf
        p = p_off + base + off
        return ((plain[p] >> b) & 1) if p < len(plain) else None

    def rdf(base, nm):
        """f32 字段：收到 6 位小数。param 里存的是 f32，直接 str() 会写出
        0.6000000238418579 这种浮点噪声；这俩字段是「米」，6 位足够且可读。"""
        v = rd(base, nm)
        return round(v, 6) if isinstance(v, float) else v

    header = ["row_id", "name_id", "name", "hp", "get_soul", "is_boss",
              "chr_hit_radius", "chr_hit_height", "npc_type", "team_type"]
    st = {"rows": 0, "named": 0, "nameid_pos": 0, "boss": 0, "boss_named": 0,
          "boss_nid0": 0, "boss_unnamed_nameid": [],
          "named_endpoint_only": 0, "boss_named_endpoint_only": 0,
          "out": out_csv, "fields": len(fields), "row_size": row_size,
          "conflicts": conflicts, "nested": nested, "names": len(names),
          "names_endpoint_only": len(flat_ep), "boss_bit": boss_bf}

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for rid in sorted(rows):
            base = rows[rid]
            nid = rd(base, "nameId")
            nm = names.get(nid) if nid else None
            b = bit(base)
            w.writerow([
                rid, nid if nid is not None else "", nm or "",
                rd(base, "hp"), rd(base, "getSoul"), b,
                rdf(base, "chrHitRadius"), rdf(base, "chrHitHeight"),
                rd(base, "npcType"), rd(base, "teamType"),
            ])
            st["rows"] += 1
            if nid and nid > 0:
                st["nameid_pos"] += 1
            if nm:
                st["named"] += 1
            if nid and flat_ep.get(nid):
                st["named_endpoint_only"] += 1
            if b == 1:
                st["boss"] += 1
                if not nid:
                    st["boss_nid0"] += 1
                if nm:
                    st["boss_named"] += 1
                else:
                    st["boss_unnamed_nameid"].append(nid)
                if nid and flat_ep.get(nid):
                    st["boss_named_endpoint_only"] += 1
    return st


def _print_stats(st):
    print("\n=== 敌人名单表统计 ===")
    print("  NpcParam 行数（scan_rows）        : %d" % st["rows"])
    print("  nameId > 0 的行                   : %d" % st["nameid_pos"])
    print("  查到名字的行                      : %d" % st["named"])
    print("  is_boss == 1 的行                 : %d" % st["boss"])
    print("  有名字的 is_boss 行               : %d" % st["boss_named"])
    print("  [对照] 只取 id 区间端点：有名字 %d 行 / Boss 有名字 %d 行"
          % (st["named_endpoint_only"], st["boss_named_endpoint_only"]))
    print("  is_boss 行里 nameId == 0 的       : %d 行" % st["boss_nid0"])
    uniq = sorted({x for x in st["boss_unnamed_nameid"] if x})
    print("  is_boss 但没名字、且 nameId != 0  : %d 行，nameId 去重 %d 个 %s"
          % (len([x for x in st["boss_unnamed_nameid"] if x]), len(uniq), uniq[:12]))
    print("  写出                              : %s" % st["out"])


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    mod_dir = default_mod_dir()
    msgbnd = find_msgbnd(mod_dir)
    print("=" * 72)
    print("FMG 解析自检 + 敌人名单表导出")
    print("  mod : %s" % mod_dir)
    print("  msg : %s" % msgbnd)
    print("=" * 72)
    if not msgbnd:
        print("[X] 找不到 msgbnd")
        return 1
    files = read_msgbnd_files(msgbnd)

    # ── 1) 结构自检（全部 FMG）────────────────────────────────────────
    print("\n[1] FMG 结构关系自检（全部 FMG）")
    tot = ok_rec = ok_tab = 0
    for internal, blob in files:
        if _stem(internal) is None or len(blob) < ID_TABLE + ID_REC_SIZE:
            continue
        tot += 1
        a, b = fmg_structure_ok(blob)
        ok_rec += a
        ok_tab += b
    print("  (0x18-0x28)/16 == 0x0C : %d/%d" % (ok_rec, tot))
    print("  0x18 + 8*0x10 <= size  : %d/%d" % (ok_tab, tot))

    # ── 2) NpcName 系列 ──────────────────────────────────────────────
    print("\n[2] NpcName 系列解析结果")
    nested = names_from_files(files, expand_ranges=True)
    ep = names_from_files(files, expand_ranges=False)
    for stem in NPCNAME_FMGS:
        if stem in nested:
            print("  %-18s %6d 条（区间展开） / %5d 条（只取端点）"
                  % (stem, len(nested[stem]), len(ep.get(stem, {}))))

    npc = nested.get("NpcName") or {}
    n = len(npc)
    print("  → NpcName 条目数 %d  (%s)"
          % (n, "OK：数百条" if 300 <= n <= 100000 else "异常，id 表多半没读对"))

    # ── 3) 区间语义自检 ──────────────────────────────────────────────
    print("\n[3] id 区间语义自检（三条证据）")
    ranges = []
    desc = inv = spread = 0
    for internal, blob in files:
        if _stem(internal) not in NPCNAME_FMGS:
            continue
        for lo, hi, _t in fmg_ranges(blob):
            ranges.append((lo, hi))
            spread += 1
            if hi < lo:
                inv += 1
            if hi == lo:
                desc += 1
    sr = sorted(ranges)
    ov = sum(1 for i in range(1, len(sr)) if sr[i][0] <= sr[i - 1][1])
    ds = sorted(h - l for l, h in ranges if h > l)
    print("  区间总数 %d：单点 %d、跨多 id %d、上界<下界 %d"
          % (spread, desc, len(ds), inv))
    if ds:
        print("  跨度的中位/最大：%d / %d" % (ds[len(ds) // 2], ds[-1]))
    print("  区间两两重叠处数：%d  （0 = 真区间；若当成「两个独立 id」则无法解释）" % ov)

    # ── 4) 硬指标 ────────────────────────────────────────────────────
    print("\n[4] 硬指标：必须能找到这些真 id")
    miss = []
    for k in (110000, 110200, 131800, 134800, 180000):
        v = npc.get(k)
        if v is None:
            miss.append(k)
        print("  id %-8d → %s" % (k, ("%r" % v) if v else "<<缺失>>"))
    print("  → %s" % ("全部命中 ✓" if not miss else "缺 %s ✗" % miss))

    print("\n[5] 抽样 10 条")
    for i, k in enumerate(sorted(npc)):
        if i >= 10:
            break
        print("  %-8d %s" % (k, npc[k]))

    flat, conflicts = merge_names(nested)
    print("\n[6] 三文件合并（DLC 覆盖基础包）")
    print("  合并后 %d 条，id 冲突 %d 条" % (len(flat), len(conflicts)))
    for rid, a, stem, b in conflicts[:8]:
        print("    id %-8d NpcName=%r  vs  %s=%r" % (rid, a, stem, b))

    # ── 5) 导出 ──────────────────────────────────────────────────────
    print("\n[7] 导出 enemy_table.csv")
    st = export_enemy_table(mod_dir, CSV_OUT, quiet=True)
    _print_stats(st)

    # ── 6) 结论 ──────────────────────────────────────────────────────
    nz = st["boss"] - st["boss_nid0"]
    print("\n[8] 结论：Boss 行有没有名字")
    print("  is_boss=1 共 %d 行 → 查到名字 %d 行（%.1f%%）"
          % (st["boss"], st["boss_named"],
             100.0 * st["boss_named"] / st["boss"] if st["boss"] else 0.0))
    print("  其中 nameId == 0 的 %d 行 —— 这些行**本来就没名字**，不是解析失败"
          % st["boss_nid0"])
    print("  nameId != 0 的 Boss 行 %d 行 → 查到名字 %d 行（%.1f%%）"
          % (nz, st["boss_named"],
             100.0 * st["boss_named"] / nz if nz else 0.0))
    print("  只取区间端点时 Boss 只查到 %d 行 —— 区间展开多救回 %d 行"
          % (st["boss_named_endpoint_only"],
             st["boss_named"] - st["boss_named_endpoint_only"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
