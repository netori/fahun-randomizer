# msb_edit.py — MSB 结构编辑（重建布局 + 追加模型 + 改 part 字段）
#
# 为什么要有它：msb_write.patch 只能改**已有**字段。换敌人时新敌人可能不在本图的
# 模型表里（Boss 图通常只有 Boss 一个 chr 模型），必须往 MSB 的 MODEL_PARAM_ST 里
# 追加一条模型（参考实现 EldenEnemyEditor.RegisterModel 做的同一件事）。
#
# 实测布局（m10_00_00_00 逐块核对）：
#   file = fileHeader(0x10) + 逐块 [ blockHeader, blockName(utf16), entries ]
#   blockHeader = {i32 version, i32 count(=条目数+1), i64 nameOffset,
#                  u64 entryOffset[count-1], i64 nextParamOffset}
#   entryOffset 是**绝对**偏移；nextParamOffset = 下一块 blockHeader 的绝对偏移（最后一块为 0）
#   条目内部的名字/路径偏移都是**相对条目**的 i64，所以整体搬动不影响它们
#   条目长度由相邻偏移差得出（最后一条 = 下一块起点/文件尾 - 起点），实测与文件完全吻合
import struct

import msb_read

HEADER_SIZE = 0x10
MODEL_ENTRY_NAME_REL = 0x00
MODEL_ENTRY_SIB_REL = 0x10
MODEL_ENTRY_FLAG = 0x18


class MsbEditError(Exception):
    pass


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _i64(b, o):
    return struct.unpack_from("<q", b, o)[0]


def _put32(b, o, v):
    struct.pack_into("<i", b, o, int(v))


def _put64(b, o, v):
    struct.pack_into("<q", b, o, int(v))


def _name_bytes(raw, off):
    """从绝对偏移读一条 utf16 名字，返回 (字符串, 含终止符的字节)"""
    end = off
    while end + 1 < len(raw) and raw[end:end + 2] != b"\0\0":
        end += 2
    s = raw[off:end].decode("utf-16-le", "replace")
    return s, raw[off:end + 2]


class Msb(object):
    """一个 MSB：file header + 块（每块含条目原始字节）。"""

    def __init__(self, raw):
        self.raw = bytes(raw)
        if self.raw[:4] != msb_read.MSBE_MAGIC:
            raise MsbEditError("不是 MSB（magic=%r）" % self.raw[:4])
        self.file_header = self.raw[:HEADER_SIZE]
        _fver, blocks = msb_read.walk_params(self.raw)
        self.blocks = []
        for b in blocks:
            offs = list(b["entry_offsets"])
            nxt = b["next"] or len(self.raw)
            if not offs:
                entries = []
            else:
                sizes = [offs[i + 1] - offs[i] for i in range(len(offs) - 1)]
                sizes.append(nxt - offs[-1])
                entries = [self.raw[o:o + s] for o, s in zip(offs, sizes)]
            name, _nb = _name_bytes(self.raw, b["name_offset"])
            # 块名字后面有对齐填充（实测 6 个块的 "…_PARAM_ST" 都是 30 字节 + 2 填充 = 32）。
            # 名字区 = [nameOffset, 第一条目偏移)；没有条目时到下一块头/文件尾。
            nxt_head = b["next"] or len(self.raw)
            region_end = offs[0] if offs else nxt_head
            name_b = self.raw[b["name_offset"]:region_end]
            self.blocks.append({"version": b["version"], "name": name,
                                "name_bytes": name_b, "entries": entries})

    # ---------------------------------------------------------------- 查
    def block(self, name):
        for b in self.blocks:
            if b["name"] == name:
                return b
        return None

    def models(self):
        out = []
        b = self.block("MODEL_PARAM_ST")
        for e in b["entries"]:
            nm, _ = _name_bytes(e, _i64(e, MODEL_ENTRY_NAME_REL))
            out.append(nm)
        return out

    def model_entry(self, name):
        b = self.block("MODEL_PARAM_ST")
        for i, e in enumerate(b["entries"]):
            nm, _ = _name_bytes(e, _i64(e, MODEL_ENTRY_NAME_REL))
            if nm == name:
                return i
        return -1

    def parts(self):
        """[(条目序号, part 对象)]（复用 msb_read.read_enemy 的字段解析）"""
        b = self.block("PARTS_PARAM_ST")
        # msb_read 的解析基于绝对偏移，这里为了复用先拼一张"只有 PARTS 块"的临时文件
        tmp = self.assemble()
        _fver, blocks = msb_read.walk_params(tmp)
        models = self.models()
        out = []
        for blk in blocks:
            if blk["name"] != "PARTS_PARAM_ST":
                continue
            for i, off in enumerate(blk["entry_offsets"]):
                out.append((i, msb_read.read_enemy(tmp, off, models)))
        return out

    # ---------------------------------------------------------------- 改
    def add_model(self, name, sib_path):
        """追加一条模型，返回新的 ModelIndex（已存在则直接返回旧下标）。"""
        idx = self.model_entry(name)
        if idx >= 0:
            return idx
        b = self.block("MODEL_PARAM_ST")
        tmpl = b["entries"][0] if b["entries"] else b""
        b["entries"].append(make_model_entry(tmpl, name, sib_path))
        return len(b["entries"]) - 1

    def set_part_int(self, part_index, field_off, value):
        b = self.block("PARTS_PARAM_ST")
        e = bytearray(b["entries"][part_index])
        _put32(e, field_off, value)
        b["entries"][part_index] = bytes(e)

    def set_part_typedata(self, part_index, field_off, value, typ="i32"):
        """写 part 的 typeData 区（typ 偏移在条目 +0x68，相对条目）。

        EnemyBase 实测布局（DSMapStudio 的 MSBE PartsParam.cs:1738-1771 对得上）：
          +0x08 ThinkParamID / +0x0C NPCParamID / +0x10 TalkID
          +0x15 UnkT15(bool) / +0x18 CharaInitID / +0x38 BackupEventAnimID
        """
        b = self.block("PARTS_PARAM_ST")
        e = bytearray(b["entries"][part_index])
        typ_off = _i64(e, 0x68)
        o = typ_off + field_off
        if typ == "u8":
            e[o] = int(value) & 0xFF
        elif typ == "i16":
            struct.pack_into("<h", e, o, int(value))
        else:
            _put32(e, o, value)
        b["entries"][part_index] = bytes(e)

    # ---------------------------------------------------------------- 写
    def assemble(self):
        out = bytearray(self.file_header)
        pos = HEADER_SIZE
        nblocks = len(self.blocks)
        for bi, b in enumerate(self.blocks):
            entries = b["entries"]
            n = len(entries)
            arr_len = (n + 1) * 8
            name_off = pos + 16 + arr_len
            entries_start = name_off + len(b["name_bytes"])
            offs, cur = [], entries_start
            for e in entries:
                offs.append(cur)
                cur += len(e)
            next_head = cur if bi + 1 < nblocks else 0
            out += struct.pack("<iiq", b["version"], n + 1, name_off)
            for o in offs:
                out += struct.pack("<q", o)
            out += struct.pack("<q", next_head)
            out += b["name_bytes"]
            for e in entries:
                out += e
            pos = cur
        return bytes(out)


def make_model_entry(template, name, sib_path):
    """按参考实现的做法造一条 model 条目：名字 + sib 路径，长度按内容算（8 字节对齐）。"""
    nb = name.encode("utf-16-le") + b"\0\0"
    sb = sib_path.encode("utf-16-le") + b"\0\0"
    name_rel = 0x28
    sib_rel = name_rel + len(nb)
    size = sib_rel + len(sb)
    size += (-size) % 8
    e = bytearray(size)
    _put64(e, MODEL_ENTRY_NAME_REL, name_rel)
    _put64(e, MODEL_ENTRY_SIB_REL, sib_rel)
    _put64(e, MODEL_ENTRY_FLAG, 1)
    # 模板里 0x08 / 0x20 之后的非字符串字段照抄（名字/路径区域不动）
    if template:
        _put64(e, 0x08, _i64(template, 0x08))
        for off in range(0x20, min(len(template), 0x28)):
            if off < len(e):
                e[off] = template[off]
    e[name_rel:name_rel + len(nb)] = nb
    e[sib_rel:sib_rel + len(sb)] = sb
    return bytes(e)


def chr_sib_path(model):
    return "N:\\GR\\data\\Model\\chr\\%s\\sib\\%s.sib" % (model, model)


def selftest_roundtrip(paths):
    """解析→原样重建，必须逐字节一致（证明对布局的理解没漏东西）"""
    bad = []
    for p in paths:
        raw, _hdr = msb_read.dcx_payload(open(p, "rb").read())
        try:
            m = Msb(raw)
            out = m.assemble()
        except Exception as exc:                        # noqa: BLE001
            bad.append((p, "EXC %s" % exc))
            continue
        if out != raw:
            n = min(len(out), len(raw))
            diff = [i for i in range(n) if out[i] != raw[i]]
            bad.append((p, "len %d/%d diff %d first %s" % (
                len(out), len(raw), len(diff), [hex(x) for x in diff[:3]])))
    return bad
