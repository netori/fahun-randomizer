# -*- coding: utf-8 -*-
"""敌型初稿表（给人工复核用）：名字关键词 + 数值画像

说明（口径见 docs/敌人随机_敌人分类.md）：
* **敌型不当作池的轴** —— 池子照抄原版敌随（类别池 + 加权来源池）。
  这张表是给**人工复核**与以后"只换同类外观"这类高级选项用的画像。
* 名字只覆盖 736 行（Boss 行的 nameId 基本是 0），其余靠数值画像（hp/体型）。
* 输出：investigation/enemy_classes_auto.csv
    row_id, name, cls, enemy_type, hp, get_soul, radius, height, npc_type, team_type
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = os.path.join(HERE, "..", "enemy_classes_auto.csv")

# 顺序敏感：先匹配到的算（与文档里的 12 类一致）
RULES = [
    ("龙系", ["龙"]),
    ("骑士·重甲精英", ["骑士", "熔炉", "流放", "圣职", "十字军", "黑铁", "守卫"]),
    ("士兵·正规军人形", ["士兵", "兵", "哨兵", "仪卫", "仪仗", "弓手", "弩手", "长官", "队长",
                    "指挥官", "战士", "剑士", "斗士", "刺客", "猎人", "盗贼", "警卫"]),
    ("施法者", ["法师", "魔女", "术师", "萨满", "祭司", "女巫", "魔法", "僧", "信徒", "神官",
              "奥秘", "占星", "巫师", "大祭司"]),
    ("不死与腐败", ["骷髅", "骨", "亡灵", "幽灵", "幽魂", "尸", "丧", "腐", "死", "枯", "凋", "脓"]),
    ("大型兽·巨兽", ["巨人", "巨兽", "河马", "大象", "山猪", "巨", "战车", "弩车"]),
    ("野兽", ["狼", "犬", "鼠", "鸟", "鹰", "猫", "羊", "牛", "马", "鹿", "猪", "猴", "蛙",
            "蛇", "蜥", "蝠", "鳐", "狮", "虎", "象", "熊"]),
    ("虫与异形", ["虫", "蝎", "蛛", "蛆", "蛾", "蚁", "蜂", "蛞", "软体", "史莱姆", "泥",
               "花", "草", "菌", "树"]),
    ("亚人与蛮族", ["亚人", "蛮", "食人", "哥布林", "狼人", "土人"]),
    ("人造与魔像", ["魔像", "雕像", "傀儡", "结晶", "石像", "机关", "罐", "壶", "人偶"]),
    ("神皮与教会", ["神皮", "黑刀", "暗杀", "异端", "神使"]),
    ("血族与贵族", ["血族", "吸血", "贵族", "皇家", "王朝", "密契", "血怪"]),
]


def enemy_type_of(name):
    if not name:
        return ""
    for cls, kws in RULES:
        if any(k in name for k in kws):
            return cls
    return "其它/未分类"


def main():
    import enemy_randomizer as er
    plain = er.load_plain()
    units = er.load_units(plain)
    er.classify(units, names=er.load_name_table(), healthbar_ids=er.load_healthbar_nameids())

    rows, by_type = [], {}
    for rid in sorted(units):
        u = units[rid]
        t = enemy_type_of(u.name)
        if u.name and "其它" not in t:
            by_type.setdefault(t, []).append(u.name)
        rows.append({"row_id": rid, "name": u.name, "cls": u.cls, "enemy_type": t,
                     "hp": u.hp, "get_soul": u.soul,
                     "radius": f"{u.radius:.2f}" if u.radius else "",
                     "height": f"{u.height:.2f}" if u.height else "",
                     "npc_type": u.npc_type, "team_type": u.team_type})
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"→ {os.path.abspath(OUT)}（{len(rows)} 行）")

    print("\n=== 敌型分布（只统计有名字的行）===")
    for t, names in sorted(by_type.items(), key=lambda x: -len(x[1])):
        uq = sorted(set(names))
        print(f"  【{t}】行 {len(names)}｜唯一名 {len(uq)}｜例：{uq[:5]}")
    unk = sorted({r["name"] for r in rows if r["name"] and "其它" in r["enemy_type"]})
    print(f"\n=== 未分类（{len(unk)}）===")
    print("  " + "、".join(unk[:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
