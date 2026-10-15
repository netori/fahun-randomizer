# -*- coding: utf-8 -*-
"""敌人分类挖掘（只读）

思路：
* Boss 行的 nameId 查不到名字（上一轮实测）→ 所以"有名字"的行 ≈ 普通敌人
* 用关键词把中文名归类，输出每类的数量与样例
* 同时用 hp / getSoul / teamType 分布做交叉验证
"""
import os
import re
import struct
import sys
import importlib.util
from collections import Counter, defaultdict

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
import erio  # noqa
import native_apply as na
import native_guide as ng

spec = importlib.util.spec_from_file_location("bt", os.path.join(WS, "_boss_taxonomy.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)
MOD = bt.MOD

# 关键词 → 类别（顺序敏感：先匹配到的算）
RULES = [
    ("Boss·最终/主线", ["拉达冈", "艾尔登之兽", "葛瑞克", "蕾娜菈", "蒙格特", "玛利喀斯", "玛莲妮亚", "蒙格",
                    "拉塔恩", "拉卡德", "阿斯特尔", "佛尔桑克斯", "普拉顿桑克斯", "荷莱·露", "米德拉",
                    "梅瑟莫", "蕾菈娜", "梅蒂尔", "萝蜜娜"]),
    ("Boss·法魂新增", ["Skarde", "西格德", "Caimar", "Einar", "Dyru", "Daergraf", "Sigur", "Seera", "Oleg",
                   "Dakk", "Gethin", "Duncan", "Konrad", "Sanguivaros", "Shabriri"]),
    ("龙类", ["龙"]),
    ("骑士/重甲人形", ["骑士", "骑士长", "流放", "熔炉", "黑骑士", "圣职", "十字军"]),
    ("士兵/杂兵人形", ["士兵", "兵", "守卫", "看护者", "哨兵", "仪卫", "仪仗", "军队", "长官", "队长", "指挥官", "弓手", "弩手"]),
    ("法师/施法者", ["法师", "魔女", "术师", "萨满", "祭祀", "女巫", "魔法师", "僧", "信徒", "传道", "奥秘"]),
    ("不死/亡灵", ["骷髅", "骨", "亡灵", "幽灵", "死", "尸", "幽魂", "亡灵", "丧", "腐"]),
    ("巨兽/大型", ["巨人", "巨兽", "巨蛛", "巨蛙", "巨鸟", "河马", "大象", "猛禽", "巨魔", "山猪", "熊", "蟹"]),
    ("野兽/动物", ["狼", "犬", "鼠", "鸟", "鹰", "猫", "羊", "牛", "马", "鹿", "野猪", "猴", "蛙", "蛇", "蜥", "蝠", "鳐"]),
    ("虫/异形", ["虫", "蝎", "蛛", "蛆", "蛾", "蚁", "蜂", "蚁", "软体", "史莱姆", "泥", "树灵", "花", "草"]),
    ("亚人/蛮族", ["亚人", "蛮", "食人", "哥布林", "狼人"]),
    ("人造/魔像", ["魔像", "雕像", "傀儡", "结晶", "石像", "机关", "战车", "弩车"]),
    ("神皮/教会", ["神皮", "黑刀", "暗杀"]),
    ("血族/贵族", ["血族", "吸血", "贵族", "皇家"]),
    ("元素/精灵", ["精灵", "元素", "火焰", "冰", "雷", "腐败", "猩红"]),
]


def classify(name):
    for cls, kws in RULES:
        if any(k in name for k in kws):
            return cls
    return "其它/未分类"


def main():
    reg = os.path.join(MOD, "mod", "regulation.bin")
    plain = bytes(erio.dcx_decompress(erio.regulation_decrypt(reg)))
    sizes = {}
    for name, off, size in na.bnd4_entries(plain):
        b = os.path.basename(name.replace("\\", "/"))
        if b.endswith(".param"):
            sizes[b[:-6]] = (off, size)

    fields, _rs = bt.paramdef_fields("NpcParam")
    off0, size0 = sizes["NpcParam"]
    rows = bt.scan_rows(plain, off0, size0)
    off = {f[0]: (f[2], f[1]) for f in fields}

    def rd(base, k):
        if k not in off:
            return None
        o, t = off[k]
        p = off0 + base + o
        if t in ("u8", "i8", "s8"):
            return plain[p]
        if t in ("u16", "i16", "s16"):
            return struct.unpack_from("<H", plain, p)[0]
        if t in ("u32", "i32", "s32"):
            return struct.unpack_from("<I", plain, p)[0]
        return None

    bnd, _h, _r = ng.read_msgbnd(os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx"))
    fm = {n.split("\\")[-1].replace(".fmg", ""): bt.fmg_parse(d) for n, d in bnd.files}
    npc = {}
    for k in ("NpcName", "NpcName_dlc01", "NpcName_dlc02"):
        npc.update(fm.get(k, {}))

    named, bosses = [], []
    for rid, base in rows.items():
        nm = npc.get(rd(base, "nameId") or -1, "")
        isboss = rd(base, "isSoulGetByBoss") == 1
        rec = (rid, nm, rd(base, "hp") or 0, rd(base, "getSoul") or 0,
               rd(base, "npcType"), rd(base, "teamType"))
        if isboss:
            bosses.append(rec)
        elif nm:
            named.append(rec)

    print(f"=== 总数 ===")
    print(f"  NpcParam 行 {len(rows)}｜Boss 行(isSoulGetByBoss) {len(bosses)}｜有名字的普通敌人行 {len(named)}")
    uniq = sorted({r[1] for r in named if r[1]})
    print(f"  唯一名字 {len(uniq)}")

    cls_map = defaultdict(list)
    for r in named:
        if r[1]:
            cls_map[classify(r[1])].append(r)
    print("\n=== 普通敌人按关键词分类（行数 / 唯一名字数）===")
    for cls, recs in sorted(cls_map.items(), key=lambda x: -len(x[1])):
        uq = sorted({x[1] for x in recs})
        hp = sorted(x[2] for x in recs if x[2])
        med = hp[len(hp) // 2] if hp else 0
        print(f"\n  【{cls}】行 {len(recs)}｜名字 {len(uq)}｜血量中位 {med}")
        print(f"    {uq[:10]}")

    print("\n=== 未分类的名字（看看还缺什么类别）===")
    rest = sorted({x[1] for x in cls_map.get("其它/未分类", [])})
    print(f"  {len(rest)} 个: {rest[:40]}")


if __name__ == "__main__":
    main()
