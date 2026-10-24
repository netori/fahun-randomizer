# param_bin.py — ER PARAM 容器读写（format 2E）：解析 / 原位改字段 / 追加行后重排偏移
#
# 为什么要自己写：
#   * M2 要给每个替换位置克隆一条 NpcParam 行（hp/魂 = 位置原值），必须**新增行**；
#   * 现成的 WitchyBND 需要真控制台（PromptPlus 拒绝重定向），不能进无人值守管线。
#
# 实测布局（对 194 张 param 表逐一验证，见 --selftest）：
#   0x00  0x58 字节头：u0/u4 = 行数据区结尾，u2 = (行数+1)<<16 | 小整数，u12 = 行表结尾
#   0x58  行表：每 0x18 字节 {u64 行 id, u64 数据偏移, u64 名字偏移}（按 id 升序）
#   行表后 一段"孤儿行数据"（0x00~8 行不等，没有表项引用它；原样保留）
#   行数据区：每行 stride 字节（stride 由相邻数据偏移的众数得出，行之间可能有共享）
#   数据区结尾 = 头里 u0；其后是尾部区（含 "PARAM_ST" 名字表），原样保留
#
# 追加行的做法：行表 +k*0x18、行数据区 +k*stride，其余整体后移；
#   所有数据偏移 +k*0x18，所有名字偏移 +(k*0x18 + k*stride)；新行名字串追加在文件末尾。
import struct

HEADER_SIZE = 0x58
ENTRY_SIZE = 0x18
MAGIC = b"PARAM"


class ParamError(Exception):
    pass


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def _put32(b, o, v):
    struct.pack_into("<I", b, o, v & 0xFFFFFFFF)


def _put64(b, o, v):
    struct.pack_into("<Q", b, o, v & 0xFFFFFFFFFFFFFFFF)


def _mode(xs):
    c = {}
    for x in xs:
        c[x] = c.get(x, 0) + 1
    return max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] if c else 0


class ParamFile(object):
    """一张 param 表。只做三件事：读行、改行内字节、追加行后重排。"""

    def __init__(self, data):
        data = bytes(data)
        # 注意：ER 1.17 的 param 没有 "PARAM" 魔数（文件从"数据区结尾"u32 直接开始），
        # 不要按魔数判断 —— 只能按结构校验（行表三元组 + 头部偏移自洽）。
        if len(data) < HEADER_SIZE:
            raise ParamError("文件太短（%d B）" % len(data))
        self.data = data
        self.header = data[:HEADER_SIZE]
        self.count_field = (u32(data, 8) >> 16) - 1
        # 行表
        ents, o = [], HEADER_SIZE
        while o + ENTRY_SIZE <= len(data):
            rid, dd, nm = struct.unpack_from("<QQQ", data, o)
            if not (0 < rid < 0x7FFFFFFF and 0 < dd < nm <= len(data)):
                break
            ents.append((rid, dd, nm))
            o += ENTRY_SIZE
        self.table_start = HEADER_SIZE
        self.table_end = o
        self.entries = ents                      # [(id, data_off, name_off)] 升序
        self.ids = [e[0] for e in ents]
        if self.count_field not in (len(ents), -1):
            # 允许两者一致；不一致说明头字段含义不是"行数"，交给上层决定
            self.count_mismatch = True
        else:
            self.count_mismatch = False
        offs = sorted(set(e[1] for e in ents))
        diffs = [b - a for a, b in zip(offs, offs[1:]) if b > a]
        self.stride = _mode(diffs) or 0
        # 行数据区：从最小偏移到头部 u0；行表与数据区之间是"孤儿行数据"
        self.data_end = u32(data, 0)
        if not ents:
            # 0 行的表（GameSystemCommonParam 等）：没有行数据区
            self.data_start = self.data_end if self.data_end >= self.table_end else self.table_end
            self.stride = 0
        else:
            self.data_start = offs[0]
        if self.stride <= 0 and self.data_end - self.data_start > 0:
            self.stride = self.data_end - self.data_start   # 只有 1 行时用整段长度
        self.gap = data[self.table_end:self.data_start]
        if self.data_end < self.data_start or self.data_end > len(data):
            raise ParamError("头部数据区结尾 0x%x 不合理（起点 0x%x，文件 %d）" % (
                self.data_end, self.data_start, len(data)))
        self.data_region = data[self.data_start:self.data_end]
        self.tail = data[self.data_end:]
        self.row_count_in_data = (len(self.data_region) // self.stride) if self.stride else 0
        if self.stride and (self.data_end - self.data_start) % self.stride:
            raise ParamError("行数据区长度 %d 不是行大小的整数倍 %d" % (
                self.data_end - self.data_start, self.stride))

    # ---------------------------------------------------------------- 读
    def offset_of(self, rid):
        for e in self.entries:
            if e[0] == rid:
                return e[1]
        return None

    def payload(self, rid):
        o = self.offset_of(rid)
        if o is None:
            raise ParamError("没有行 %s" % rid)
        return self.data[o:o + self.stride]

    def next_free_id(self, after):
        """after 之后第一个空位（参考实现 NpcEdits.cs:92-106 的做法）"""
        used = set(self.ids)
        nid = int(after) + 1
        while nid in used and nid < 0x7FFFFFFF:
            nid += 1
        if nid >= 0x7FFFFFFF:
            raise ParamError("行 id 用尽")
        return nid

    # ---------------------------------------------------------------- 写
    @staticmethod
    def patch(payload, offset, value, typ):
        """在一行字节里写一个字段（按 paramdef 的类型）"""
        b = bytearray(payload)
        if typ in ("u8", "i8", "s8"):
            struct.pack_into("<B", b, offset, int(value) & 0xFF)
        elif typ in ("u16", "i16", "s16"):
            struct.pack_into("<H", b, offset, int(value) & 0xFFFF)
        elif typ in ("u32", "i32", "s32"):
            struct.pack_into("<I", b, offset, int(value) & 0xFFFFFFFF)
        elif typ in ("u64", "i64", "s64"):
            struct.pack_into("<Q", b, offset, int(value) & 0xFFFFFFFFFFFFFFFF)
        elif typ == "f32":
            struct.pack_into("<f", b, offset, float(value))
        elif typ == "f64":
            struct.pack_into("<d", b, offset, float(value))
        else:
            raise ParamError("不认识的字段类型 %r" % (typ,))
        return bytes(b)

    def rebuild(self, extra=None, force=False, drop=()):
        """重排整张表并返回新字节。

        extra: [(row_id, payload_bytes, name_str)]，行 id 必须不存在；
               payload 长度必须 == stride；name_str 会追加到名字区末尾。
        drop:  要删掉的行 id（本轮之前的产物；重跑时靠它保持幂等）。
        """
        extra = list(extra or [])
        drop = set(int(x) for x in (drop or ()))
        if not extra and not force and not drop:
            # 无改动：原样返回。
            # force=True 时仍走一遍重排，用来验证"我们对布局的理解能逐字节重建"（--selftest）。
            return self.data
        used = set(self.ids)
        for rid, payload, _nm in extra:
            if rid in used:
                raise ParamError("行 id %s 已存在" % rid)
            used.add(rid)
            if len(payload) != self.stride:
                raise ParamError("行 %s 的字节数 %d ≠ 行大小 %d" % (rid, len(payload), self.stride))
        for rid in drop:
            if rid not in used:
                raise ParamError("要删的行 %s 不存在" % rid)
        if drop and self.row_count_in_data != len(self.entries):
            # 删行要求数据区就是"每条一行"的紧凑布局（NpcParam / NpcThinkParam 实测都是）
            raise ParamError("表里有 %d 个数据槽但只有 %d 条行表记录，不敢删行"
                             % (self.row_count_in_data, len(self.entries)))
        keep = [(i, e) for i, e in enumerate(self.entries) if e[0] not in drop]
        kd, ka = len(self.entries) - len(keep), len(extra)
        table_delta = ENTRY_SIZE * (ka - kd)
        table_end_new = self.table_end + table_delta
        data_start_new = table_end_new + len(self.gap)

        # 数据区按**旧偏移升序**排（NpcParam 的行表与数据区顺序一致；PhantomParam 等乱序表
        # 也不动相对顺序）。注意：行表里**可能有重复 id**（ItemLotParam_enemy 实测有），
        # 所以索引一律按"行表下标"算，不能按 id 建字典，否则重复 id 会串行。
        order = sorted(keep, key=lambda t: t[1][1])
        if kd:
            region_bytes = b"".join(self.data[e[1]:e[1] + self.stride] for _i, e in order)
            new_off = {i: data_start_new + k * self.stride for k, (i, _e) in enumerate(order)}
        else:
            # 不删行时数据区原样保留（有的表数据区里除了行还有别的字节：ItemLotParam_enemy 实测有）
            region_bytes = self.data_region
            new_off = {i: e[1] + table_delta for i, e in keep}
        for k, (rid, _p, _n) in enumerate(extra):
            new_off[("new", rid)] = data_start_new + len(region_bytes) + k * self.stride
        data_end_new = data_start_new + len(region_bytes) + self.stride * ka
        shift_tail = data_end_new - self.data_end

        # 行表顺序**原样保留**（乱序表不能重排）；新行插到"第一个 id 更大的行"前面。
        rows = [(e[0], i) for i, e in keep]
        for rid, _p, _n in sorted(extra, key=lambda x: x[0]):
            pos = len(rows)
            for k, (r, _i) in enumerate(rows):
                if r > rid:
                    pos = k
                    break
            rows.insert(pos, (rid, ("new", rid)))
        extra_map = {rid: (p, n) for rid, p, n in extra}

        out = bytearray()
        header = bytearray(self.header)
        _put32(header, 0x00, data_end_new)       # 数据区结尾（u0）
        _put32(header, 0x10, data_end_new)       # 同一个值的副本（u4）
        _put32(header, 0x30, table_end_new)      # 行表结尾（u12）
        # 0x48 是行表结尾的**副本**（vanilla / 法魂都等于 0x30）；SpEffectParam 的加载器读它，
        # 只更新 0x30 会让它在增行后读到旧偏移 —— 实测 = 启动 crt abort（0xc0000409）。
        if u32(self.header, 0x48) == self.table_end:
            _put32(header, 0x48, table_end_new)
        # 0x50 = 名字区起点 = 数据区结尾 + (paramdef 名字 + NUL) 的长度；尾部整体平移时要跟着平移。
        base_name_off = u32(self.header, 0x50)
        if base_name_off >= self.data_end:
            _put32(header, 0x50, base_name_off + shift_tail)
        u2 = u32(self.header, 8)
        # 实测：头部 (u2>>16) 恒等于 行数+1（ActionButton 475→476、AiSound 216→217、NpcParam 7830→7831）
        _put32(header, 0x08, (((len(rows) + 1) << 16) | (u2 & 0xFFFF)) & 0xFFFFFFFF)
        out += header
        # 行表（新行先占位，名字偏移等尾部拼好再回填）
        for rid, key in rows:
            if rid in extra_map and isinstance(key, tuple):
                out += struct.pack("<QQQ", rid, new_off[key], 0)
            else:
                out += struct.pack("<QQQ", rid, new_off[key], self.entries[key][2] + shift_tail)
        # 孤儿行数据 + 行数据区（删行时按旧偏移顺序重拼）+ 新行数据
        out += self.gap
        out += region_bytes
        for rid, payload, _nm in extra:
            out += payload
        # 尾部（名字表）
        tail_start = len(out)
        out += self.tail
        appended = b""
        name_off = {}
        base = tail_start + len(self.tail)
        for rid, _p, nm_str in extra:
            name_off[rid] = base + len(appended)
            appended += nm_str.encode("utf-16-le") + b"\0\0"
        out += appended
        # 回填新行的名字偏移
        pos = HEADER_SIZE
        for rid, key in rows:
            if rid in extra_map and isinstance(key, tuple):
                _put64(out, pos + 16, name_off[rid])
            pos += ENTRY_SIZE
        return bytes(out)

    @staticmethod
    def _extra_data_index(extra, rid):
        for i, (r, _p, _n) in enumerate(extra):
            if r == rid:
                return i
        raise ParamError("内部错误：找不到新行 %s" % rid)


def selfcheck_one(data):
    """无改动往返：必须逐字节一致"""
    pf = ParamFile(data)
    return pf.rebuild([]) == data


def field_offsets(fields):
    """paramdef_fields() 的结果 → {字段名: (行内偏移, 类型, 大小)}（位域另算）"""
    return {nm: (off, typ, size) for nm, typ, off, size in fields}
