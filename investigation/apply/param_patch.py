# param_patch.py — 自研 param 读写（ER format2D/2E，只做"定位 + 就地改 4 字节字段"）
#
# 实测结构（ItemLotParam_map，其他 param 同族）：
#   文件 = [param 主体][名字/枚举表（以 "PARAM_ST" 开头）]
#   param 主体里有一张行表，每条 0x18 字节：{u64 行id, u64 数据偏移, u64 名字偏移}
#   行数据起始处即 lotItemId01；lotItemIdNN = data + 4*(N-1)；lotItemCategoryNN = data + 0x20 + 4*(N-1)
#   （ShopLineupParam 等表字段偏移另算，见 FIELD_MAP）
import struct

MAGIC = b"PARAM"


def name_table_offset(raw: bytes) -> int:
    i = raw.find(b"PARAM_ST")
    return i if i >= 0 else len(raw) // 2


def find_row_table(raw: bytes, probe_id: int) -> dict:
    """定位行表：先按 id 找一条目，再往回走到表头；返回 {row_id: data_offset}"""
    pat = struct.pack("<Q", probe_id) + struct.pack("<Q", 0)      # id 之后是 data（先粗定位 id）
    start = None
    i = 0
    while True:
        i = raw.find(struct.pack("<Q", probe_id), i)
        if i < 0:
            break
        # 该位置若满足 (id, data, name) 三元组，则它是条目起点
        if i + 0x18 <= len(raw):
            rid, data, name = struct.unpack_from("<QQQ", raw, i)
            if rid == probe_id and 0 < data < name < len(raw):
                start = i
                break
        i += 1
    if start is None:
        return {}
    # 往回走
    off = start
    while off - 0x18 >= 0:
        rid, data, name = struct.unpack_from("<QQQ", raw, off - 0x18)
        if not (0 < rid < 0x7FFFFFFF and 0 < data < name < len(raw)):
            break
        nxt = struct.unpack_from("<Q", raw, off)[0]
        if not (rid < nxt):
            break
        off -= 0x18
    rows, o = {}, off
    while o + 0x18 <= len(raw):
        rid, data, name = struct.unpack_from("<QQQ", raw, o)
        if not (0 < rid < 0x7FFFFFFF and 0 < data < name < len(raw)):
            break
        rows[rid] = data
        o += 0x18
    return rows


# 各类 param 的字段布局：{字段名: (行内偏移, 槽步长, 槽数)}
FIELD_MAP = {
    # 字段偏移取自 Paramdex（ER/Defs/ItemLotParam.xml）并经实测验证：
    #   lotItemIdNN       = +0x00 + 4*(NN-1)   (s32)
    #   lotItemCategoryNN = +0x20 + 4*(NN-1)   (s32)
    #   lotItemNumNN      = +0x8A + 1*(NN-1)   (u8)
    "ItemLotParam_map": {
        "lotItemId": (0x00, 4, 8),
        "lotItemCategory": (0x20, 4, 8),
        "lotItemNum": (0x8A, 1, 8),
    },
    "ItemLotParam_enemy": {
        "lotItemId": (0x00, 4, 8),
        "lotItemCategory": (0x20, 4, 8),
        "lotItemNum": (0x8A, 1, 8),
    },
    # 字段偏移取自 WitchyBND 自带 Paramdex（ER/Defs/ShopLineupParam.xml）：
    #   +0x00 equipId(s32) … +0x17 equipType(u8) +0x18 costType(u8) …
    "ShopLineupParam": {
        "equipId": (0x00, 4, 1),
        "equipType": (0x17, 1, 1),
    },
}


def offset_of(table: str, rows: dict, row_id: int, field: str, slot: int = 1):
    if row_id not in rows:
        return None
    base, stride, cnt = FIELD_MAP[table][field]
    if not (1 <= slot <= cnt):
        return None
    return rows[row_id] + base + stride * (slot - 1)


def read_u32(raw, off):
    return struct.unpack_from("<I", raw, off)[0]


def write_u32(raw: bytearray, off, val):
    struct.pack_into("<I", raw, off, val)


def write_u8(raw: bytearray, off, val):
    raw[off] = val & 0xFF


# 类别编码：两张 lot 表用 1=goods 2=weapon 3=protector；ShopLineupParam.equipType 用 0=weapon 1=protector 3=goods
LOT_CAT = {"goods": 1, "weapon": 2, "protector": 3}
SHOP_CAT = {"weapon": 0, "protector": 1, "goods": 3}
