# item_world_stats.py — 「职业物品以外」物品随机的可行性统计（只读）
#
# 为什么要有这支脚本：
#   现在的物品随机只管 682 件职业说明书物品、835 格；要做「其他物品也随机」，
#   第一步是先把**三张表里到底有多少格、都是什么类别、物品池有多大**数清楚。
#   这个脚本不写任何文件（只打印），数字进 docs/物品随机_范围扩展_讨论稿.md。
#
# 读法：mod/regulation.bin → 明文 → ParamFile（param_bin.py）逐表读行
#       → 用 Paramdex 字段偏移取字段（enemy_randomizer.paramdef_fields）。
import os
import sys
import json
import struct
import collections
import xml.etree.ElementTree as ET

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
sys.path.insert(0, APPLY)

import enemy_randomizer as ER      # noqa: E402
import native_apply as na          # noqa: E402
import param_bin as PB             # noqa: E402
import param_patch as pp           # noqa: E402

CATNAME = {0: "none", 1: "goods", 2: "weapon", 3: "protector", 4: "accessory", 5: "gem", 6: "cat6"}
SHOP_TYPE = {0: "weapon", 1: "protector", 2: "accessory", 3: "goods", 4: "gem", 5: "?5"}
_FMT = {"u8": "<B", "i8": "<b", "s8": "<b", "dummy8": "<B", "u16": "<H", "i16": "<h", "s16": "<h",
        "u32": "<I", "i32": "<i", "s32": "<i", "f32": "<f", "u64": "<Q", "i64": "<q", "s64": "<q", "f64": "<d"}

GOODS_TYPE_ZH = {
    0: "一般/未分类", 1: "关键道具", 2: "素材", 3: "?", 5: "?", 7: "骨灰(灵魂)", 8: "骨灰(傀儡)",
    9: "?", 10: "结晶露滴", 12: "书信", 14: "强化素材(锻造石/种子/露滴)", 15: "大卢恩",
    16: "法术", 17: "祷告", 18: "祷告?", 100: "黄金卢恩", 101: "追忆",
}


def load_param(plain, filename):
    off = size = None
    for name, o, s in na.bnd4_entries(plain):
        if os.path.basename(name.replace("\\", "/")).lower() == filename.lower():
            off, size = o, s
            break
    if off is None:
        raise SystemExit("regulation 里没有 %s" % filename)
    return PB.ParamFile(plain[off:off + size])


def field_map(table):
    fields, row_size = ER.paramdef_fields(table)
    fmap = {}
    for nm, typ, off, sz in fields:
        fmap.setdefault(nm, (off, typ, sz))
    return fmap


def get(pf, payload, fmap, name):
    f = fmap.get(name)
    if not f:
        return None
    off, typ, sz = f
    fmt = _FMT.get(typ)
    if not fmt or sz == 0:
        return None
    return struct.unpack_from(fmt, payload, off)[0]


def table_dict(pf, fmap, names):
    out = {}
    for rid, doff, _nm in pf.entries:
        payload = pf.data[doff:doff + pf.stride]
        out[rid] = {nm: get(pf, payload, fmap, nm) for nm in names}
    return out


def lots(pf, fmap):
    """[(row_id, slot, item_id, category, num, base_point, flag)]"""
    out = []
    for rid, doff, _nm in pf.entries:
        payload = pf.data[doff:doff + pf.stride]
        for s in range(1, 9):
            iid = get(pf, payload, fmap, "lotItemId%02d" % s)
            cat = get(pf, payload, fmap, "lotItemCategory%02d" % s)
            if not iid:
                continue
            out.append((rid, s, iid, cat,
                        get(pf, payload, fmap, "lotItemNum%02d" % s),
                        get(pf, payload, fmap, "lotItemBasePoint%02d" % s),
                        get(pf, payload, fmap, "getItemFlagId%02d" % s)))
    return out


def names_from_xml(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return {}
    root = ET.parse(p).getroot()
    out = {}
    for t in root.iter("text"):
        tid = t.get("id")
        if tid is None:
            continue
        txt = (t.text or "").strip()
        if txt and txt not in ("[ERROR]", "%null%"):
            out.setdefault(int(tid), txt)
    return out


def main():
    plain = ER.load_plain()
    print("regulation 明文 %d 字节" % len(plain))

    # ---- 三张物品表 ----
    lf = field_map("ItemLotParam")
    map_pf = load_param(plain, "ItemLotParam_map.param")
    enemy_pf = load_param(plain, "ItemLotParam_enemy.param")
    shop_pf = load_param(plain, "ShopLineupParam.param")
    map_lots = lots(map_pf, lf)
    enemy_lots = lots(enemy_pf, lf)
    sf = field_map("ShopLineupParam")
    shops = table_dict(shop_pf, sf, ("equipId", "equipType", "value", "sellQuantity", "costType"))

    # ---- 四张物品定义表 ----
    gf = field_map("EquipParamGoods")
    goods_pf = load_param(plain, "EquipParamGoods.param")
    goods = table_dict(goods_pf, gf, ("goodsType", "isOnlyOne", "basicPrice", "sellValue", "maxNum", "sortGroupId", "refCategory"))
    wf = field_map("EquipParamWeapon")
    weapon_pf = load_param(plain, "EquipParamWeapon.param")
    weapons = table_dict(weapon_pf, wf, ("weaponCategory", "fixPrice", "sellValue", "weight", "sortGroupId", "reinforceTypeId"))
    pf_ = field_map("EquipParamProtector")
    prot_pf = load_param(plain, "EquipParamProtector.param")
    prots = table_dict(prot_pf, pf_, ("protectorCategory", "basicPrice", "sellValue", "sortGroupId"))
    af = field_map("EquipParamAccessory")
    acc_pf = load_param(plain, "EquipParamAccessory.param")
    accs = table_dict(acc_pf, af, ("accessoryCategory", "basicPrice", "sellValue", "sortGroupId"))
    gemf = field_map("EquipParamGem")
    gem_pf = load_param(plain, "EquipParamGem.param")
    gems = table_dict(gem_pf, gemf, ("sortGroupId", "sellValue"))

    print("行数：map %d / enemy %d / shop %d ｜ goods %d / weapon %d / protector %d / accessory %d / gem %d"
          % (len(map_pf.entries), len(enemy_pf.entries), len(shop_pf.entries),
             len(goods_pf.entries), len(weapon_pf.entries), len(prot_pf.entries), len(acc_pf.entries), len(gem_pf.entries)))

    def slot_stats(tag, L):
        n = len(L)
        bycat = collections.Counter(x[3] for x in L)
        unknown = collections.Counter()
        for x in L:
            tbl = {1: goods, 2: weapons, 3: prots, 4: accs, 5: gems}.get(x[3])
            if tbl is None or x[2] not in tbl:
                unknown[CATNAME.get(x[3], x[3])] += 1
        print("  [%s] 格 %d ｜ 类别 %s ｜ 表里查不到 id 的格 %s"
              % (tag, n, {CATNAME.get(k, k): v for k, v in bycat.most_common()}, dict(unknown)))
        return bycat

    print("== 世界拾取(ItemLotParam_map)")
    slot_stats("map", map_lots)
    print("== 敌人掉落(ItemLotParam_enemy)")
    slot_stats("enemy", enemy_lots)
    print("== 商店(ShopLineupParam) 行 %d" % len(shops))
    st = collections.Counter(SHOP_TYPE.get(v["equipType"], v["equipType"]) for v in shops.values())
    priced = [v for v in shops.values() if (v["value"] or 0) > 0]
    print("  equipType %s ｜ price>0 %d ｜ price 分布 %s"
          % (dict(st), len(priced), collections.Counter(v["value"] for v in priced).most_common(8)))

    # ---- 物品池：真正出现在格子里的物品 ----
    universe = collections.defaultdict(set)
    for x in map_lots + enemy_lots:
        universe[x[3]].add(x[2])
    for v in shops.values():
        cat = {"weapon": 2, "protector": 3, "accessory": 4, "goods": 1, "gem": 5}.get(SHOP_TYPE.get(v["equipType"]))
        if cat and (v["value"] or 0) > 0:
            universe[cat].add(v["equipId"])
    for cat, ids in sorted(universe.items()):
        print("  可获得的 %-10s %d 个 id" % (CATNAME.get(cat, cat), len(ids)))

    # ---- goods 细分（决定池子怎么切） ----
    gslots = [x for x in map_lots + enemy_lots if x[3] == 1 and x[2] in goods]
    bytype = collections.Counter(goods[x[2]]["goodsType"] for x in gslots)
    print("== goods 格按 goodsType（%d 格 / %d 个 id）" % (len(gslots), len({x[2] for x in gslots})))
    for t, c in bytype.most_common():
        ids = len({x[2] for x in gslots if goods[x[2]]["goodsType"] == t})
        print("   type %-3s %-22s 格 %5d ｜ id %4d" % (t, GOODS_TYPE_ZH.get(t, "?"), c, ids))
    only = [x for x in gslots if goods[x[2]]["isOnlyOne"]]
    print("   isOnlyOne=1 的格 %d（%d 个 id）" % (len(only), len({x[2] for x in only})))

    # ---- 武器细类 ----
    wslots = [x for x in map_lots + enemy_lots if x[3] == 2 and x[2] in weapons]
    wc = collections.Counter(weapons[x[2]]["weaponCategory"] for x in wslots)
    base_ids = {x[2] - (x[2] % 100) for x in wslots}
    print("== 武器格 %d（%d 个 id）｜ id%%100==0 的格 %d ｜ 疑似基础武器 %d 把 ｜ weaponCategory %s"
          % (len(wslots), len({x[2] for x in wslots}),
             sum(1 for x in wslots if x[2] % 100 == 0), len(base_ids), dict(wc.most_common(12))))

    pslots = [x for x in map_lots + enemy_lots if x[3] == 3 and x[2] in prots]
    pc = collections.Counter(prots[x[2]]["protectorCategory"] for x in pslots)
    print("== 护甲格 %d（%d 个 id）｜ protectorCategory %s" % (len(pslots), len({x[2] for x in pslots}), dict(pc)))

    # ---- 名字覆盖 ----
    gnames = names_from_xml("investigation/randomization-catalog/evidence/xml/GoodsName.fmg.xml")
    gnames.update(names_from_xml("investigation/randomization-catalog/evidence/xml/GoodsName_dlc01.fmg.xml"))
    pnames = names_from_xml("investigation/randomization-catalog/evidence/xml/ProtectorName.fmg.xml")
    pnames.update(names_from_xml("investigation/randomization-catalog/evidence/xml/ProtectorName_dlc01.fmg.xml"))
    def cover(ids, nm):
        return sum(1 for i in ids if i in nm)
    print("== 名字覆盖：goods %d/%d ｜ protector %d/%d ｜ weapon 0/%d ｜ accessory 0/%d ｜ gem 0/%d"
          % (cover(universe.get(1, set()), gnames), len(universe.get(1, set())),
             cover(universe.get(3, set()), pnames), len(universe.get(3, set())),
             len(universe.get(2, set())), len(universe.get(4, set())), len(universe.get(5, set()))))

    # ---- 现有地图分档信息能覆盖多少格 ----
    # lot id 前 3 位 = 地图号（104 → m10_04）
    pre = collections.Counter(str(x[2])[:3] for x in map_lots)
    print("== 世界格按 lot 前缀(map) 分布 top10 %s（不同前缀 %d）" % (pre.most_common(10), len(pre)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
