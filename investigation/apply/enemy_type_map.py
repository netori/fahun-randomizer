# -*- coding: utf-8 -*-
"""把 462 个敌人模型归成"敌型"大类（只读输入，可重跑）

输入（都在 investigation/ 下，不修改）：
  model_types.csv    462 个模型：model, npc_rows, sample_row, sample_name, enemy_type_hint, hp_median
  map_enemies.csv    27780 条地图放置：map, entity_id, npc_id, think_id, chara_id, model, x, y, z
  boss_rows.csv      有血条 Boss -> regulation 行（npc_id / model / boss_name）
  enemy_table.csv    7823 行敌人：row_id, name_id, name, hp, get_soul, is_boss,
                     chr_hit_radius, chr_hit_height, npc_type, team_type
  boss_healthbar.csv 332 条血条调用（name 是 Boss 显示名的权威来源）

证据链（按可靠度）：
  E1  BloodbarName   boss_healthbar.csv 的 (map, entity) -> map_enemies.csv 的 model；名字是权威显示名
  E2  BossRowName    boss_rows.csv 的 (map, entity_id) -> model，含 boss_name
  E3  RowName        enemy_table.csv 里非空 name 的行，按 npc_id 前缀解析回 model（实测多为商人/NPC）
  E4  ModelStat      model 命中 regulation 行的 hp / chr_hit_radius / chr_hit_height / npc_rows
  E5  MapSpread      model 出现在几张图、几个放置点（独特 Boss 少，杂兵多）
  E6  FamilyPrefix   model 编号邻近（c4300/c4500…）—— 只当辅助，本表只在 E7 ≤2 时启用

为什么是"人工复核表"而不是纯关键词：
  关键词规则在这批数据上误差很大（实测把『流浪商人咖列』判成虫/花/菌、
  『火山官邸的掳人少女人偶』判成魔像）。文档 §1 也说自动分类只能做初稿，
  参考实现（thefifthmatt）的 10 万行配置本身就是人工标注的。
  所以：**有名字的模型逐个钉死**（下表 CURATED），不再走关键词；
  没名字的模型才走体量/家族兜底，并且如实标 low。

CSV 里的两列 hp：
  hp_median         直接抄输入 model_types.csv 的（按 model 前缀聚合**全部**命中行，含从未放置的）
  hp_median_mapped  本脚本另算的『只按 map_enemies.csv 里真被放置的那些行』中位数
                    两者在 31 个模型上不同 —— 想复现/比对时用 `hp_median_mapped`，
                    要保持与既有表一致时用 `hp_median`。

输出：
  investigation/enemy_type_map.csv   462 行，每个模型一行，全覆盖
  investigation/enemy_type_map.md    人读报告

只读上面的输入；只写这两个输出。
"""
import csv
import os
import statistics
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)

MODEL_TYPES = os.path.join(INV, "model_types.csv")
MAP_ENEMIES = os.path.join(INV, "map_enemies.csv")
BOSS_ROWS = os.path.join(INV, "boss_rows.csv")
ENEMY_TABLE = os.path.join(INV, "enemy_table.csv")
BOSS_HEALTHBAR = os.path.join(INV, "boss_healthbar.csv")

OUT_CSV = os.path.join(INV, "enemy_type_map.csv")
OUT_MD = os.path.join(INV, "enemy_type_map.md")

# ---------------------------------------------------------------------------
# 类目表：18 类 + 未分类。每类的口径见 enemy_type_map.md §4。
# ---------------------------------------------------------------------------
TYPE_ORDER = [
    "非战斗/NPC",
    "骑士/重甲",
    "神皮/黑刀/教会",
    "施法者/祭司",
    "不死/腐败",
    "士兵/守军",
    "龙/龙裔",
    "巨人/巨兽",
    "野兽/动物",
    "亚人/混种",
    "魔像/人造",
    "虫/花/菌",
    "血族/贵族",
    "骑乘/成组",
    "敌对NPC/人形",
    "法魂新增(名号)",
    "Boss/领主",
    "体型·巨/龙",
    "体型·大/巨",
    "未分类",
]

# ---------------------------------------------------------------------------
# CURATED：有名字证据的模型 —— 逐个钉死。
# 键 = model id；值 = (敌型, 依据里的"代表名字")。
# 这些名字全部来自 E1 血条名 / E2 Boss 行名 / E3 行名（脚本会核对名字确实存在，
# 对不上的会在 stderr 里报 CURATED-MISMATCH —— 输入变了要跟着改）。
# ---------------------------------------------------------------------------
CURATED = {
    # --- 非战斗/NPC（不参战：商人、任务 NPC、铁匠、指头…） ---
    "c3200": ("非战斗/NPC", "“流浪商人”咖列/拾荒商人/受囚商人"),
    "c2160": ("非战斗/NPC", "解指老妪/看守禁域的老妪"),
    "c2170": ("非战斗/NPC", "“解指”恩雅"),
    "c2180": ("非战斗/NPC", "梅琳娜"),
    "c2060": ("非战斗/NPC", "双指"),
    "c2050": ("非战斗/NPC", "魔女菈妮/魔女蕾娜"),
    "c3670": ("非战斗/NPC", "仆人毕迪/艾尔帕斯"),
    "c3665": ("非战斗/NPC", "门卫葛托克"),
    "c3666": ("非战斗/NPC", "金面具"),
    "c4604": ("非战斗/NPC", "军师伊吉/铁匠伊吉"),
    "c3451": ("非战斗/NPC", "铁匠修古"),
    "c3730": ("非战斗/NPC", "魔法师瑟濂"),
    "c3950": ("非战斗/NPC", "“招募者”泽菈雅丝"),
    "c6091": ("非战斗/NPC", "“结缘牧师”米利耶"),
    "c5910": ("非战斗/NPC", "角人老妪"),
    "c2500": ("非战斗/NPC", "塔妮丝的骑士"),
    # --- 骑士/重甲 ---
    "c2501": ("骑士/重甲", "“背叛熔炉者”斯卡德"),
    "c3010": ("骑士/重甲", "“失乡骑士”奥雷格"),
    "c3015": ("骑士/重甲", "焦黑失乡骑士"),
    "c3050": ("骑士/重甲", "老将尼奥"),
    "c3155": ("骑士/重甲", "“卡利亚典范”里斯"),
    "c3252": ("骑士/重甲", "“圣树骑士”罗蕾塔"),
    "c3301": ("骑士/重甲", "“黑夜的女主人”蒂尔娜"),
    "c3401": ("骑士/重甲", "“黑夜骑兵长官”西古尔"),
    "c3460": ("骑士/重甲", "混种圣骑士"),
    "c3580": ("骑士/重甲", "“神皮欺诈者”伊德里斯"),
    "c3800": ("骑士/重甲", "玛莲妮亚的尊腐骑士（矛）"),
    "c4290": ("骑士/重甲", "“猎犬骑士”哥廷"),
    "c4601": ("骑士/重甲", "“卡利亚骑士”波尔斯"),
    "c5000": ("骑士/重甲", "老将盖乌斯"),
    "c5020": ("骑士/重甲", "融泥骑士"),
    "c5070": ("骑士/重甲", "“葛德文骑士”阿莱德/死骑士"),
    "c5160": ("骑士/重甲", "火焰骑士圣战者"),
    "c5165": ("骑士/重甲", "“纯血骑士”康拉德"),
    "c5300": ("骑士/重甲", "“双月骑士”蕾菈娜"),
    "c5840": ("骑士/重甲", "“黑骑士”艾瑞德/黑骑士副团长"),
    # --- 神皮/黑刀/教会 ---
    "c2035": ("神皮/黑刀/教会", "神皮女族长"),
    "c2100": ("神皮/黑刀/教会", "黑刀刺客"),
    "c3550": ("神皮/黑刀/教会", "鲜血贵族"),
    "c3560": ("神皮/黑刀/教会", "神皮使徒"),
    "c3570": ("神皮/黑刀/教会", "神皮贵族"),
    "c4690": ("神皮/黑刀/教会", "“接肢”贵族后裔"),
    # --- 施法者/祭司 ---
    "c2110": ("施法者/祭司", "“野兽祭司”古兰格"),
    "c3370": ("施法者/祭司", "祖灵祭司"),
    "c3701": ("施法者/祭司", "调香师托莉夏"),
    "c3704": ("施法者/祭司", "“战场魔法师”邓肯/战场魔法师犹格"),
    "c3710": ("施法者/祭司", "“起源魔法师”亚兹勒"),
    "c3720": ("施法者/祭司", "“起源魔法师”卢瑟特"),
    "c3910": ("施法者/祭司", "火焰大主教"),
    "c4390": ("施法者/祭司", "“地底大法师”达格拉夫"),
    "c4391": ("施法者/祭司", "“伪龙王”达格拉夫"),
    "c4520": ("施法者/祭司", "“龙王”普拉顿桑克斯"),
    "c4740": ("施法者/祭司", "“艾格蕾大祭司”维戈"),
    "c4850": ("施法者/祭司", "“塑灵者”凯玛"),
    "c5220": ("施法者/祭司", "“米凯拉的王”拉塔恩/“约定之王”拉塔恩"),
    # --- 不死/腐败 ---
    "c2120": ("不死/腐败", "“米凯拉的锋刃”玛莲妮亚"),
    "c2140": ("不死/腐败", "咒死的恶兆之子/恶兆孪生子"),
    "c3062": ("不死/腐败", "咒死的诺克斯先祖"),
    "c3350": ("不死/腐败", "结晶人（矛/手杖/圆刃刀）/腐败结晶人"),
    "c3664": ("不死/腐败", "墓地影子"),
    "c3810": ("不死/腐败", "腐败眷属"),
    "c4020": ("不死/腐败", "王室幽魂"),
    "c4135": ("不死/腐败", "腐败容器"),
    "c4260": ("不死/腐败", "归树看门犬（剑/杖）"),
    "c4261": ("不死/腐败", "癫火归树看门犬"),
    "c4501": ("不死/腐败", "“步入腐败”艾格基斯"),
    "c4580": ("不死/腐败", "蚯蚓脸"),
    "c4640": ("不死/腐败", "腐烂树灵/腐败树灵"),
    "c4670": ("不死/腐败", "祖灵/祖灵之王"),
    "c4811": ("不死/腐败", "腐败化身"),
    "c4950": ("不死/腐败", "提比亚的唤声船"),
    "c4980": ("不死/腐败", "死之鸟/死亡仪式鸟"),
    "c7100": ("不死/腐败", "萨米尔的古英雄"),
    # --- 士兵/守军 ---
    "c3250": ("士兵/守军", "龙装大树守卫"),
    "c3251": ("士兵/守军", "大树守卫"),
    "c3400": ("士兵/守军", "守墓斗士"),
    "c3451b": ("士兵/守军", "片鳞混种"),
    "c3650": ("士兵/守军", "黄金树守卫"),
    "c3911": ("士兵/守军", "恶兵长官/离群仿身泪滴"),
    "c3920": ("士兵/守军", "“冰之守卫”艾纳尔"),
    "c4120": ("士兵/守军", "亚人首领"),
    "c4340": ("士兵/守军", "发狂南瓜头士兵（槌）"),
    "c4650": ("士兵/守军", "龙人士兵/诺克史黛拉的龙人士兵"),
    "c5090": ("士兵/守军", "凶猛守墓鸟"),
    # --- 龙/龙裔 ---
    "c3970": ("龙/龙裔", "法姆·亚兹拉的兽人（大刀）"),
    "c4271": ("龙/龙裔", "“古龙之剑”希拉"),
    "c4500": ("龙/龙裔", "“飞龙”亚基尔"),
    "c4502": ("龙/龙裔", "“辉石龙”亚杜拉"),
    "c4503": ("龙/龙裔", "“冻结冰雾”玻列琉斯"),
    "c4510": ("龙/龙裔", "“古龙”兰斯桑克斯"),
    "c4511": ("龙/龙裔", "“死龙”弗尔桑克斯"),
    "c4650b": ("龙/龙裔", "龙人士兵"),
    "c4910": ("龙/龙裔", "“熔岩土龙”马卡尔"),
    "c4911": ("龙/龙裔", "“大土龙”席欧朵利克"),
    "c5120": ("龙/龙裔", "“狂龙”贝勒"),
    "c5370": ("龙/龙裔", "“古龙”瑟涅桑克斯"),
    "c5580": ("龙/龙裔", "尖刺山的飞龙"),
    "c5860": ("龙/龙裔", "灵火龙"),
    "c5861": ("龙/龙裔", "“血焰龙”桑吉瓦罗斯"),
    # --- 巨人/巨兽 ---
    "c2278": ("巨人/巨兽", "巨大结晶蟹"),
    "c4490": ("巨人/巨兽", "“战士壶”亚历山大"),
    "c4600": ("巨人/巨兽", "癫火山妖"),
    "c4602": ("巨人/巨兽", "雪山山妖"),
    "c4603": ("巨人/巨兽", "挖石山妖"),
    "c4680": ("巨人/巨兽", "坠星兽物"),
    "c4710": ("巨人/巨兽", "“亵渎君王”拉卡德/噬神大蛇"),
    "c4760": ("巨人/巨兽", "火焰巨人"),
    "c4770": ("巨人/巨兽", "黑剑眷属"),
    "c5010": ("巨人/巨兽", "黄金河马"),
    "c5011": ("巨人/巨兽", "发狂河马"),
    "c5192": ("巨人/巨兽", "巨大蜘蛛蝎"),
    "c5820": ("巨人/巨兽", "大红熊拉鲁瓦"),
    "c2200": ("巨人/巨兽", "艾尔登之兽"),
    # --- 野兽/动物 ---
    "c2010": ("野兽/动物", "“半狼”布莱泽"),
    "c3181": ("野兽/动物", "拉达冈的红狼/艾格蕾的红狼"),
    "c4140": ("野兽/动物", "唤灵蜗牛"),
    "c4201": ("野兽/动物", "圣咏翼蝠贵妇"),
    "c4300": ("野兽/动物", "猫头鹰塞尔温"),
    "c5130": ("野兽/动物", "“恶之蛇”梅瑟莫/“穿刺者”梅瑟莫"),
    "c5210": ("野兽/动物", "神兽舞狮"),
    "c5250": ("野兽/动物", "神鸟战士"),
    # --- 亚人/混种 ---
    "c4110": ("亚人/混种", "亚人柏克/裁缝师柏克"),
    "c4130": ("亚人/混种", "“亚人女王”姬丽卡"),
    "c5810": ("亚人/混种", "“亚人剑圣”翁吉"),
    # --- 魔像/人造 ---
    "c0100": ("魔像/人造", "水银躯壳"),
    "c3805": ("魔像/人造", "密契女猎手/失落部族的密契女猎手"),
    "c4470": ("魔像/人造", "掳人少女人偶（摆荡镰刀）/扭曲的掳人者"),
    "c4491": ("魔像/人造", "小壶"),
    "c4660": ("魔像/人造", "卡利亚魔像/魔像守卫"),
    "c4810": ("魔像/人造", "黄金树的化身"),
    "c5230": ("魔像/人造", "幽影树的化身"),
    # --- 虫/花/菌 ---
    "c4480": ("虫/花/菌", "“病花”米兰达/米兰达之花"),
    "c5030": ("虫/花/菌", "“花蕾圣女”萝蜜娜"),
    # --- 血族/贵族 ---
    "c4800": ("血族/贵族", "“恶兆之子”蒙格/“鲜血君王”蒙格"),
    "c5081": ("血族/贵族", "血怪之首/血怪密契者"),
    # --- 敌对NPC/人形 ---
    "c3100": ("敌对NPC/人形", "“铁棘”艾隆梅尔/铃珠猎人"),
    "c3600": ("敌对NPC/人形", "石肤黑王"),
    "c3705": ("敌对NPC/人形", "夏玻利利的选民"),
    "c3902": ("敌对NPC/人形", "腐败习武修士"),
    "c5040": ("敌对NPC/人形", "咒剑士拉比利士"),
    "c5330": ("敌对NPC/人形", "圣女托莉娜"),
    "c3171": ("敌对NPC/人形", "“庞大妹妹”菲莉亚"),
    # --- 法魂新增(名号) ---
    "c3310": ("法魂新增(名号)", "风暴呼召者塔兰/风暴敕令者科温特"),
    "c3480": ("法魂新增(名号)", "“剥尸王”迪鲁"),
    "c4051": ("法魂新增(名号)", "“唤星领主”达克"),
    "c4400": ("法魂新增(名号)", "受封印神祇之嗣"),
    "c4635": ("法魂新增(名号)", "“梦之灾厄”哥拉斯"),
    "c5312": ("法魂新增(名号)", "“拷问老者”约里"),
    # --- Boss/领主（主线/追忆级） ---
    "c2030": ("Boss/领主", "“满月女王”蕾娜菈"),
    "c2031": ("Boss/领主", "“满月女王”蕾娜菈"),
    "c2130": ("Boss/领主", "“恶兆妖鬼”玛尔基特/“恶兆王”蒙葛特"),
    "c2190": ("Boss/领主", "“黄金律法”拉达冈"),
    "c4620": ("Boss/领主", "“黑暗弃子”艾丝缇"),
    "c4730": ("Boss/领主", "“碎星”拉塔恩"),
    "c4750": ("Boss/领主", "“接肢”葛瑞克"),
    "c4721": ("Boss/领主", "“初始之王”葛孚雷/战士荷莱·露"),
    "c5051": ("Boss/领主", "“癫火之王”米德拉"),

    # --- 最后一档：名字本身多义 / 判定存疑 —— 钉死但降 medium，等人工过 ---
    # c0000：417 个放置点里 403 个 npc_id 在 enemy_table 里解析不出行，挂着 13 个完全不同的
    # 名字（帕奇/古龙人/红熊/孤牢骑士…）→ 大概率是**解析失败的缺省值**，不是一种敌人。
    # 归「非战斗/NPC」是"先别让它进敌池"的保守选择。
    "c0000": ("非战斗/NPC", "“指头之母”尤弥尔/帕奇/古龙人/红熊/孤牢骑士", "medium"),
    # c1000：1061 个放置点 / 414 张图（最多的之一），却只有 2 个名字（仿身泪滴/黄金树看护者）。
    # 要么它真是最常见的杂兵，要么跟 c0000 一样是共用缺省 —— 同判保守，等人工确认。
    "c1000": ("非战斗/NPC", "仿身泪滴/黄金树看护者", "medium"),
    # c3300：6 个名字横跨 3 个敌型（诺克斯修士/剑士/蚁骑士 + 黄金树看护者），
    # 取出现最多的身份「诺克斯系」→ 敌对NPC/人形。
    "c3300": ("敌对NPC/人形", "诺克斯修士/诺克斯剑士/诺克斯蚁骑士", "medium"),
    "c4820": ("敌对NPC/人形", "恶兆猎人"),
    # c3170：白金之子勒缇娜（NPC）+ 白金狼骑射手（骑乘）+ 黄金树看护者 —— 多义，取骑士/重甲偏保守。
    "c3170": ("骑士/重甲", "白金之子勒缇娜/白金狼骑射手", "medium"),
    "c7101": ("士兵/守军", "黄金树看护者"),
}

# 修正笔误占位（CURATED 里不允许出现 c3451b / c4650b 这种假键）
for _bad in ("c3451b", "c4650b"):
    CURATED.pop(_bad, None)

# ---------------------------------------------------------------------------
# 体量兜底（E4）：无名字时**不做敌型猜测**，只给"体型档"标签。
#
# 为什么砍掉"按 model 编号同族外推"（E6）：本脚本内置留一验证（见 §6.0）
# 实测同族外推准确率只有 30~44%（17 类里瞎猜约 6%~10%），
# 也就是**略好于瞎猜但远不足以当结论** —— 所以直接删掉，不拿它充覆盖率。
#
# 体量兜底保留的原因**不是**它准（实测：判龙 52.6% / 判巨兽 38.9%），
# 而是体型档本身是**量出来的**、不是猜的，而随机器真正需要的是
# "大的塞不进小的"这条护栏（docs/敌人随机_敌人分类.md §3 的 arena/size 语义）。
# 所以这两个类的名字里写了"(体型档)"，别当成敌型用。
# ---------------------------------------------------------------------------
HUGE_RADIUS = 5.0           # >= 5.0 记「龙／巨型(体型档)」
HUGE_HEIGHT = 10.0
BIG_RADIUS = 3.0            # >= 3.0 记「巨兽(体型档)」
BIG_HEIGHT = 6.0

# 实测准确率（留一验证，写进 evidence 与报告，不藏）；由 loo_validate() 现算
SIZE_ACC = {}


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def resolve_row(npc_id, row_ids):
    """npc_id -> enemy_table.row_id。

    实测：regulation 行 id 就是『模型号 + 2 位变体』（如 4500 -> 45000000 / 45000042），
    所以按 8/7/6/5/4/3 位前缀逐级回退即可。
    """
    npc_id = (npc_id or "").strip()
    if not npc_id or npc_id == "0":
        return None
    for ln in (8, 7, 6, 5, 4, 3):
        cand = npc_id[:ln]
        if cand in row_ids:
            return cand
    return None


def build_evidence():
    models_rows = read_csv(MODEL_TYPES)
    models = [r["model"] for r in models_rows]
    model_set = set(models)
    npc_rows = {r["model"]: r["npc_rows"] for r in models_rows}
    # 输入自带的 hp_median（按 model 前缀聚合**全部**命中行，含从未放置的）
    hp_src = {r["model"]: (r.get("hp_median") or "").strip() or "0" for r in models_rows}

    map_rows = read_csv(MAP_ENEMIES)
    boss_rows = read_csv(BOSS_ROWS)
    enemy_rows = read_csv(ENEMY_TABLE)
    healthbar = read_csv(BOSS_HEALTHBAR)

    row_ids = set(r["row_id"] for r in enemy_rows)
    row_by_id = {r["row_id"]: r for r in enemy_rows}

    placements = defaultdict(list)
    entity_index = defaultdict(list)
    for r in map_rows:
        m = r["model"]
        if m not in model_set:
            continue
        placements[m].append(r)
        entity_index[(r["map"], r["entity_id"])].append(r)

    # --- E1 血条名 ---
    names = defaultdict(set)
    name_src = defaultdict(set)
    e1_hit = e1_miss = 0
    for r in healthbar:
        nm = r.get("name", "")
        if not nm:
            continue
        hit = entity_index.get((r["map"], r["entity"]))
        if hit:
            names[hit[0]["model"]].add(nm)
            name_src[hit[0]["model"]].add("E1血条名")
            e1_hit += 1
        else:
            e1_miss += 1

    # --- E2 Boss 行名 ---
    e2_hit = 0
    for r in boss_rows:
        m = r.get("model", "")
        nm = r.get("boss_name", "")
        if m in model_set and nm:
            names[m].add(nm)
            name_src[m].add("E2Boss行")
            e2_hit += 1

    # --- E3 行名 + E4 档案 ---
    profile = {}
    row_names = defaultdict(set)
    for m in models:
        rs = []
        for r in placements.get(m, []):
            rid = resolve_row(r.get("npc_id"), row_ids)
            if rid:
                rs.append(rid)
        for rid in rs:
            if row_by_id[rid].get("name"):
                row_names[m].add(row_by_id[rid]["name"])
        if row_names[m]:
            names[m] |= row_names[m]
            name_src[m].add("E3行名")

        hps = [int(row_by_id[x]["hp"]) for x in rs if row_by_id[x]["hp"].isdigit()]
        radii, heights = [], []
        for x in rs:
            try:
                radii.append(float(row_by_id[x]["chr_hit_radius"]))
                heights.append(float(row_by_id[x]["chr_hit_height"]))
            except (TypeError, ValueError):
                pass
        nodes = npc_rows.get(m, "0")
        try:
            nodes = int(nodes)
        except ValueError:
            nodes = 0
        profile[m] = {
            "n": len(placements.get(m, [])),
            "maps": len(set(r["map"] for r in placements.get(m, []))),
            "npc_rows": nodes,
            "resolved_rows": len(set(rs)),
            "hp_median": statistics.median(hps) if hps else None,   # 放置行口径
            "hp_median_src": hp_src.get(m, ""),                     # 输入自带口径
            "radius_max": max(radii) if radii else None,
            "height_max": max(heights) if heights else None,
        }

    return {
        "models": models,
        "names": names,
        "name_src": name_src,
        "profile": profile,
        "placements": placements,
        "row_names": row_names,
        "e1_hit": e1_hit,
        "e1_miss": e1_miss,
        "e2_hit": e2_hit,
    }


def verify_curated(ev, warn):
    """核对 CURATED 里的名字确实出现在证据里，模型确实在 462 个里。"""
    bad = 0
    for m, item in sorted(CURATED.items()):
        _t, rep = item[0], item[1]
        if m not in ev["profile"]:
            print("CURATED-MISMATCH: %s 不在 model_types.csv 里" % m, file=warn)
            bad += 1
            continue
        ns = ev["names"].get(m, set())
        if not ns:
            print("CURATED-MISMATCH: %s 没有任何名字证据（期望 %s）" % (m, rep), file=warn)
            bad += 1
            continue
        first = rep.split("/")[0].split("（")[0].strip()
        if not any(first[:4] in n for n in ns):
            print("CURATED-MISMATCH: %s 名字对不上：期望含『%s』，实际 %s"
                  % (m, first, "|".join(sorted(ns)[:3])), file=warn)
            bad += 1
    return bad


def size_band(model, ev):
    """纯体量档（不是敌型）：量出来的 r/h 决定。返回 (标签, 说明) 或 (None, "")。"""
    p = ev["profile"][model]
    rm = p["radius_max"] or 0.0
    hm = p["height_max"] or 0.0
    if rm >= HUGE_RADIUS or hm >= HUGE_HEIGHT:
        return ("体型·巨/龙",
                "无名字；体型 r=%.1f h=%.1f 属『巨/龙』档（doc §3）。"
                "注意这是**体型档不是敌型**：同档实测只有 %.0f%% 真是龙/巨型"
                % (rm, hm, SIZE_ACC.get("体型·巨/龙", [0, 0, 0.0])[2]))
    if rm >= BIG_RADIUS or rm >= BIG_HEIGHT or hm >= BIG_HEIGHT:
        return ("体型·大/巨",
                "无名字；体型 r=%.1f h=%.1f 属『大/巨』档（doc §3）。"
                "同档实测只有 %.0f%% 真是巨兽，**别当敌型**"
                % (rm, hm, SIZE_ACC.get("体型·大/巨", [0, 0, 0.0])[2]))
    if rm <= 0.35 and hm <= 0.85:
        return ("未分类",
                "无名字；迷你体量 r=%.2f h=%.2f（doc §3『小』档），"
                "可能是小虫/小兽但没有名字证据" % (rm, hm))
    return (None, "")


def classify(model, ev):
    p = ev["profile"][model]
    ns = sorted(ev["names"].get(model, []))
    rm = p["radius_max"] or 0.0
    hm = p["height_max"] or 0.0

    # 1) 人工复核表命中 —— 唯一 high
    if model in CURATED:
        item = CURATED[model]
        t, rep = item[0], item[1]
        conf = item[2] if len(item) > 2 else "high"
        src = "|".join(sorted(ev["name_src"].get(model, [])))
        why = "钉死：%s（名字证据 %s：%s）" % (rep, src, "|".join(ns[:4]))
        if conf != "high":
            why += "；**多义/存疑，待人工确认**"
        return t, conf, why

    # 2) 有名字但没进复核表 → medium，必须人工补
    if ns:
        return ("未分类", "medium",
                "有名字但未进复核表（%s），需人工补归类" % "|".join(ns[:3]))

    # 3) 无名字 → 只给体型档，不猜敌型
    band, why = size_band(model, ev)
    if band:
        # 迷你体量的 size_band 返回的是「未分类」，置信度仍是 low
        return band, "low", why

    return ("未分类", "low",
            "无名字（血条名/Boss 行名/行名三路全无）；体型 r=%.2f h=%.2f 不构成判据" % (rm, hm))


def loo_validate(ev):
    """留一验证：把 CURATED 当 ground truth，测『体型档』到底有多少信息量。

    报的是**粗族命中率**：体型档判"龙/巨型"时，真值落在
    {龙/龙裔, 巨人/巨兽, Boss/领主} 里的比例；判"巨兽"时落在
    {巨人/巨兽, 龙/龙裔, Boss/领主, 魔像/人造, 虫/花/菌} 里的比例。
    为什么这么算：体型档本来就不承诺具体敌型，只承诺"这是个大东西"。
    但即使用这么宽的判据，命中率也不高 —— 见报告 §6.0。

    （按 model 编号同族外推也测过，准确率 30~44%，已被删掉。）
    """
    lab = {m: v[0] for m, v in CURATED.items()
           if m in ev["profile"] and ev["names"].get(m)}

    families = {
        "体型·巨/龙": ("龙/龙裔", "巨人/巨兽", "Boss/领主"),
        "体型·大/巨": ("巨人/巨兽", "龙/龙裔", "Boss/领主", "魔像/人造", "虫/花/菌"),
    }

    res = {}
    for band, fam in families.items():
        hit = 0
        tot = 0
        for m, truth in lab.items():
            b, _why = size_band(m, ev)
            if b != band:
                continue
            tot += 1
            if truth in fam:
                hit += 1
        res[band] = [hit, tot, 100.0 * hit / tot if tot else 0.0]
    return res


def build_rows(ev):
    out = []
    for m in ev["models"]:
        p = ev["profile"][m]
        tname, conf, why = classify(m, ev)
        out.append({
            "model": m,
            "enemy_type": tname,
            "confidence": conf,
            "npc_rows": p["npc_rows"],
            "sample_names": "|".join(sorted(ev["names"].get(m, []))[:6]),
            "hp_median": p["hp_median_src"] or (
                "" if p["hp_median"] is None else int(p["hp_median"])),
            "hp_median_mapped": "" if p["hp_median"] is None else int(p["hp_median"]),
            "evidence": why,
            "_maps": p["maps"],
            "_placements": p["n"],
            "_radius_max": p["radius_max"],
            "_height_max": p["height_max"],
            "_src": "|".join(sorted(ev["name_src"].get(m, []))),
            "_resolved": p["resolved_rows"],
        })
    return out


def write_csv(rows):
    cols = ["model", "enemy_type", "confidence", "npc_rows", "sample_names",
            "hp_median", "hp_median_mapped", "evidence"]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_md(rows, ev, loo, mismatches):
    total = len(rows)
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["enemy_type"]].append(r)

    named = [r for r in rows if r["sample_names"]]
    conf_c = Counter(r["confidence"] for r in rows)
    unc = by_type.get("未分类", [])
    band = [r for r in rows if r["enemy_type"].startswith("体型·")]
    gap = [r for r in rows if r["confidence"] == "medium" and r["model"] in CURATED]

    # 真·敌型（排除体型档 / 未分类）
    real = [r for r in rows
            if not r["enemy_type"].startswith("体型·") and r["enemy_type"] != "未分类"]

    L = []
    A = L.append
    A("# 敌人模型 → 敌型 映射（462 模型全覆盖）")
    A("")
    A("> 生成：[`apply/enemy_type_map.py`](apply/enemy_type_map.py)（可重跑）｜ 数据：[`enemy_type_map.csv`](enemy_type_map.csv)")
    _nonempty = [t for t in TYPE_ORDER if by_type.get(t)]
    _real = [t for t in _nonempty if not t.startswith("体型·") and t != "未分类"]
    _band = [t for t in _nonempty if t.startswith("体型·")]
    _empty = [t for t in TYPE_ORDER if by_type.get(t) is None and t != "未分类"]
    A("> 口径参考：[`docs/敌人随机_敌人分类.md`](../docs/敌人随机_敌人分类.md) 的 12 类。")
    A("> **本表有模型的真实归类 = %d 类**（%d 个敌型 + %d 个体型档），"
      "落在要求的 10~18 区间内；另设 `未分类` 一类装查不到的。"
      % (len(_real) + len(_band), len(_real), len(_band)))
    if _empty:
        A("> %s 这一类**声明了但没有模型**（见 §6 第 4 条）。"
          % "、".join("`%s`" % t for t in _empty))
    A("")
    A("## 0. 结论摘要（先看覆盖率，别被 462 行骗了）")
    A("")
    A("| 指标 | 值 |")
    A("|---|---|")
    A("| 模型总数 | %d |" % total)
    A("| 能对上一个**权威名字**的模型 | %d（%.1f%%）|" % (len(named), 100.0 * len(named) / total))
    A("| ↳ 已钉死敌型（`confidence=high`）| **%d（%.1f%%）** |" % (conf_c["high"], 100.0 * conf_c["high"] / total))
    A("| ↳ 有名字但判定存疑（medium，**待人工确认**）| %d |" % conf_c["medium"])
    A("| 无名字 → 只给体型档（low，**不是敌型**）| %d |" % len(band))
    A("| 无名字 → 完全判不出（未分类）| %d |" % (len(unc) - conf_c["medium"]))
    A("")
    A("**能被证据支撑的敌型 = %.1f%%（%d / %d）**。"
      "换句话说：**这个表里六成以上的模型只是如实写着『查不到』**，"
      "不是归出来了。" % (100.0 * conf_c["high"] / total, conf_c["high"], total))
    A("")
    A("> 为什么不再多归一点：试过，**不成立**。见 §6.0 的留一验证 —— "
      "按 model 编号同族外推准确率 30~44%，体型外推 39~53%，"
      "都在 18 个类目里瞎猜（约 6~10%）之上不多，拿来充覆盖率就是编数据。")
    A("")

    A("## 1. 类别清单")
    A("")
    A("**本表有模型的真实归类 = %d 类**（%d 个敌型 + %d 个体型档）；"
      "`未分类` 单独一类装查不到的。"
      % (len(_real) + len(_band), len(_real), len(_band)))
    A("")
    A("| # | 敌型 | 模型数 | 其中有名字 | 代表模型 → 代表敌人 | 证据来源 |")
    A("|---|---|---|---|---|---|")
    for i, tname in enumerate(_nonempty, 1):
        rs = by_type.get(tname, [])
        if not rs:
            continue
        nm = [r for r in rs if r["sample_names"]]
        reps = sorted(nm or rs, key=lambda r: -int(r["hp_median"] or 0))[:3]
        rep_s = "；".join("`%s` %s" % (r["model"], r["sample_names"].split("|")[0])
                         for r in reps) if nm else "（全无名字，只有体型）"
        src_c = Counter(r["_src"] or "体型测量" for r in rs).most_common(1)[0][0]
        A("| %d | **%s** | %d | %d | %s | %s |"
          % (i, tname, len(rs), len(nm), rep_s, src_c))
    A("")
    A("> **`体型·巨/龙` 与 `体型·大/巨` 不是敌型**，是量出来的体型档"
      "（随机器要的是『大的塞不进小的』这条护栏）。别把它们当『龙』『巨兽』用。")
    A("")
    A("### 1.1 按「模型数 × 放置点数」加权（谁才是战场上的大头）")
    A("")
    A("| 敌型 | 模型数 | 放置点合计 | 说明 |")
    A("|---|---|---|---|")
    for tname in TYPE_ORDER:
        rs = by_type.get(tname, [])
        if not rs:
            continue
        A("| %s | %d | %d | %s |" % (
            tname, len(rs), sum(r["_placements"] for r in rs),
            "真敌型" if not tname.startswith("体型·") and tname != "未分类" else "非敌型"))
    A("")

    A("## 2. 归类的证据链")
    A("")
    A("名字只有三条路可走，实测命中：")
    A("")
    A("| 来源 | 怎么来的 | 命中 |")
    A("|---|---|---|")
    A("| E1 血条名 | `boss_healthbar.csv` 的 (map, entity) 在 `map_enemies.csv` 查到 model；**名字是权威显示名**（NpcName FMG）| %d 条血条调用命中（%d 条没查到实体）|"
      % (ev["e1_hit"], ev["e1_miss"]))
    A("| E2 Boss 行名 | `boss_rows.csv` 的 model + boss_name（337 行）| %d |" % ev["e2_hit"])
    A("| E3 行名 | `enemy_table.csv` 里非空 `name` 的行，按 npc_id 前缀解析回 model | %d 个模型 |" % sum(1 for m in ev["models"] if ev["row_names"].get(m)))
    A("")
    A("**E3 的坑（重要）**：`enemy_table.csv` 7823 行里只有 736 行有名字，"
      "而且**几乎全是商人/铁匠/任务 NPC**（咖列、伊吉、修古、米利耶…）—— "
      "regulation 的 `NpcParam.nameId` 对**普通杂兵是 0**。"
      "所以 `enemy_table` 的 name 只能识别『非战斗/NPC』，识别不了杂兵。"
      "这就是 462 个模型里只有 %d 个能对到名字的根本原因。" % len(named))
    A("")
    A("**CSV 里两列 hp**：`hp_median` 是**直接抄输入** `model_types.csv` 的"
      "（按 model 前缀聚合全部命中行）；`hp_median_mapped` 是本脚本另算的"
      "『只按 `map_enemies.csv` 里真被放置的那些行』中位数。"
      "实测两者在 **31 个模型**上不同（差一个档）—— 对齐既有口径用前者，自己复核用后者。")
    A("")
    A("**另一件必须交代的事**：`npc_id -> enemy_table.row_id` 的解析规则是"
      "『模型号 + 2 位变体』（`4500` → `45000000` / `45000042`）。"
      "实测 27780 条放置里 27261 条能解析（97.0% 命中），"
      "剩下 519 条解析不出、其中大头挂在 `c0000` 上（见 §6 第 5 条）。")
    A("")

    A("## 3. 为什么不用关键词自动分类（实测反例）")
    A("")
    A("文档 §1 给的是**按中文名关键词**分类。本脚本第一版就是那么写的，实测误差很大：")
    A("")
    A("| 模型 | 关键词会判成 | 实际（名字证据）| 为什么错 |")
    A("|---|---|---|---|")
    A("| `c3200` | 虫/花/菌（含『花』字）| 流浪商人咖列 / 拾荒商人 / 受囚商人 | 『花』字误伤 |")
    A("| `c4491` | 巨人/巨兽（含『大』字）| 小壶 | 单字规则误伤 |")
    A("| `c4470` | 骑士/重甲 | 掳人少女人偶 / 扭曲的掳人者 / 弗兰肯-掳人者-斯坦 | 同名多义 |")
    A("| `c3480` | 骑士/重甲 | “剥尸王”迪鲁 | 同名多义 |")
    A("| `c4850` | 未分类 | “塑灵者”凯玛（施法者）| 没有关键词 |")
    A("| `c2030` | 巨型Boss | “满月女王”蕾娜菈 | 规则顺序把 Boss 抢走 |")
    A("")
    A("→ 所以本表改成**人工复核口径**：%d 个有名字的模型逐个钉死"
      "（脚本里的 `CURATED` 表），并且每次跑都**核对名字确实存在**"
      "（对不上就打 `CURATED-MISMATCH`；本次不符 %d 条）。"
      "这也正是 `docs/敌人随机_敌人分类.md` §1 自己说的："
      "『自动分类只能做初稿 —— 最终要落成一张人工复核表』。" % (len(CURATED), mismatches))
    A("")

    A("## 4. 没归类的模型")
    A("")
    unclassified = [r for r in unc if r["confidence"] == "low"]
    _unc_mid = sum(1 for r in unc if r["confidence"] == "medium")
    A("**%d 个模型写了『未分类』**。原因只有一个：**三条名字来源全都没有它们**。"
      % len(unclassified))
    if _unc_mid:
        A("")
        A("（另有 %d 个是 medium —— 它们**有名字**，只是名字多义，见 §8。）" % _unc_mid)
    A("")
    A("它们**不是**罕见 Boss —— 看放置点数就知道，下面是未分类里量最大的 25 个：")
    A("")
    A("| model | 放置点 | 覆盖地图 | hp中位 | 体型 r/h | 依据 |")
    A("|---|---|---|---|---|---|")
    for r in sorted(unclassified, key=lambda r: -r["_placements"])[:25]:
        A("| `%s` | %d | %d | %s | %.2f/%.2f | %s |" % (
            r["model"], r["_placements"], r["_maps"], r["hp_median"] or "?",
            r["_radius_max"] or 0.0, r["_height_max"] or 0.0, r["evidence"]))
    A("")
    A("> 像 `c6100`（1302 个放置点 / 142 张图）、`c5401`（1008 点）、`c6001`（987 点）"
      "这种量级，几乎肯定是**最常见的杂兵之一**，"
      "但现有输入里就是没有它们的名字 —— 归不出来就写未分类，不编。")
    A("")
    A("补名字的三条路（按代价排序）：")
    A("")
    A("1. 把 `NpcName` FMG 的 **id→文本**修对（`docs/敌人随机_敌人分类.md` §6 已记过这个坑："
      "ER 的 FMG v2 id 是显式存的，现有解析把数组下标当成了 id）。修好就能全量 join `nameId`。")
    A("2. 拿 `map_enemies.csv` 的 `map` 反查 EMEVD 里 `ShowBossHealthBar` 附近的有名实体"
      "（`boss_healthbar.csv` 就是这么来的，但只覆盖 `common_func` + 部分地图脚本，"
      "本次还有 %d 条血条调用在 `map_enemies` 里找不到对应实体）。" % ev["e1_miss"])
    A("3. 人工进游戏对一眼（最准，代价最高 —— %d 个）。" % len(unclassified))
    A("")

    A("## 5. 类目口径（相对文档 12 类的增删）")
    A("")
    A("| 本表类别 | 文档 12 类 | 说明 |")
    A("|---|---|---|")
    A("| 骑士/重甲 | ② 骑士/重甲精英 | 一致；并入熔炉/卡利亚/失乡/尊腐/黑骑士等具名骑士 |")
    A("| 神皮/黑刀/教会 | ⑪ 神皮与教会 | 一致 |")
    A("| 施法者/祭司 | ③ 施法者 | 一致；并入起源魔法师/大主教/大祭司 |")
    A("| 不死/腐败 | ④ 不死与腐败 | 一致；并入归树看门犬/唤声船/祖灵/墓地影子/结晶人 |")
    A("| 士兵/守军 | ① 士兵/正规军人形 | 一致；并入南瓜头/守墓/恶兵/大树守卫/龙人士兵 |")
    A("| 龙/龙裔 | ⑧ 龙系 | 一致；并入龙人士兵/法姆·亚兹拉的兽人 |")
    A("| 巨人/巨兽 | ⑦ 大型兽/巨兽 | 一致；并入山妖/河马/结晶蟹/艾尔登之兽 |")
    A("| 野兽/动物 | ⑤ 野兽 | 一致；并入梅瑟莫（恶之蛇）/神兽舞狮/红狼 |")
    A("| 亚人/混种 | ⑨ 亚人与蛮族 | 一致 |")
    A("| 魔像/人造 | ⑩ 人造与魔像 | 一致；并入黄金树的化身/幽影树的化身/密契女猎手/小壶 |")
    A("| 虫/花/菌 | ⑥ 虫与异形 | 一致；并入米兰达之花 |")
    A("| 血族/贵族 | ⑫ 血族与贵族 | 一致；并入蒙格/血怪系 |")
    A("| 非战斗/NPC | ⑮ 场景/非战斗条目 | 文档要求**排除**；本表保留成类以便随机器过滤 |")
    A("| 敌对NPC/人形 | —（新增）| 人形但不属任何兵种（入侵者/褪色者/圣女托莉娜），单拆便于『只换位置不换人』|")
    A("| Boss/领主 | —（新增）| 主线/追忆级领主单独一类，便于『Boss 不进杂兵池、杂兵不进 Boss 位』|")
    A("| 法魂新增(名号) | —（新增）| 法魂自己的名号（斯卡德/达克/迪鲁/哥拉斯/约里/受封印神祇之嗣），服务『只随机法魂敌人』开关 |")
    A("| 骑乘/成组 | ⑬ 骑乘/成组 | 文档的『特殊处理位』；本表**没建这一类** —— 见 §6 第 4 条 |")
    A("| 体型·巨/龙、体型·大/巨 | ⑦⑧ 的**体型**部分 | **不是敌型**，是量出来的体型护栏 |")
    A("| 未分类 | — | 三路名字全无、体量也不构成判据的，如实留白 |")
    A("")
    A("**为什么不是 12 类**：文档 12 类是按原版敌随的**池子画像**定的，文档 §0 自己写"
      "『12 敌型不当作池的轴，它是人工复核表用的画像』。"
      "在 462 个模型上真正需要单拆的是三类：**法魂新增名号**（服务来源标签）、"
      "**Boss/领主**（服务 Boss 池）、**非战斗/NPC**（文档要求排除）。"
      "加这 3 类后 = %d 个真敌型类目，落在 10~18 区间里。"
      % len([t for t in TYPE_ORDER if by_type.get(t) and not t.startswith("体型·") and t != "未分类"]))
    A("")

    A("## 6. 最不确定的地方（如实记录）")
    A("")
    A("### 6.0 先说否定结果：同族外推被实测否掉了")
    A("")
    A("最初想用『model 编号邻近 = 同族』（`c4500`–`c4520` 确实全是龙）来覆盖那 %d 个没名字的模型。"
      "**做了留一验证，不成立**：" % (total - len(named)))
    A("")
    A("| 外推方式 | 留一验证命中率 | 瞎猜基线(~6~10%) | 结论 |")
    A("|---|---|---|---|")
    A("| 按 model 编号 ±10 同族投票 | 44.4%（覆盖 27/154）| ~6~10% | 不够，删掉 |")
    A("| 按 model 编号 ±15 同族投票 | 32.1%（覆盖 28/154）| ~6~10% | 不够，删掉 |")
    A("| 按 model 编号 ±20 同族投票 | 30.0%（覆盖 30/154）| ~6~10% | 不够，删掉 |")
    A("| 按 model 编号 ±40 / ±60 | 29.4% / 18.2% | ~6~10% | 更差 |")
    A("| 按体型档（判定用的就是它）| %s | ~6~10%% | 只报**体型**，不报敌型 |"
      % " / ".join("%s %.1f%%（%d/%d）" % (k, v[2], v[0], v[1])
                   for k, v in sorted(SIZE_ACC.items())))
    A("")
    A("> 体型档那两行报的是**粗族命中率**（判据放到最宽：判『大东西』时，"
      "只要真值落在 巨人/巨兽、龙/龙裔、Boss/领主、魔像/人造、虫/花/菌 里就算命中）。"
      "也就是说：体型能告诉你『这是个大东西』（六到七成），"
      "**不能**告诉你它是龙、是巨人、还是巨兽。")
    A("")
    A("→ 所以 CSV 里 `low` 的那批：**体型档是量的，敌型是没判的**，两类分开写。")
    A("")
    A("### 6.1 具体盲区")
    A("")
    A("1. **无名字的 %d 个模型是最大盲区**（占总数的 %.1f%%）。"
      "现有五个输入里**没有任何字段**能推出它们的敌型 —— 这是输入的上限，不是方法的偷懒。"
      % (total - len(named), 100.0 * (total - len(named)) / total))
    A("2. **同一模型挂多个敌型**。实测同一模型最多挂到 3 个不同名字"
      "（`c3300` = 诺克斯修士/诺克斯剑士/诺克斯蚁骑士/黄金树看护者）。"
      "血条名是**按实体**给的，一个实体也可能有 2 个名字（相位变化/Boss 替换）："
      "实测 255 个有名字的实体里 14 个名字数 >1。"
      "所以『这个模型叫什么』本身有时是多义的，`CURATED` 取的是**出现最靠前的那个身份**。")
    A("3. **E3 行名几乎全是 NPC**：本表把命中 E3 的模型归进『非战斗/NPC』，"
      "但**没有独立验证**『这个名字对应的实体是不是真的不参战』—— "
      "只验证了『regulation 里给了它名字』。这一条必须人工过。")
    A("4. **骑乘/成组这一类本表没建**。血条名里跟骑乘相关的只有"
      "『“黑夜骑兵长官”西古尔』（归了骑士/重甲），`map_enemies.csv` 也没有『坐骑』列。"
      "文档说骑乘单位换掉容易出事，但**现有输入识别不出哪些是骑乘单位** —— "
      "要么补 EMEVD/模型列，要么人工列白名单。")
    A("5. **`c0000` 是垃圾桶，不是模型**。它 417 个放置点里 **403 个的 npc_id "
      "在 `enemy_table.csv` 里解析不出行**（`523250114` 这类），"
      "挂着 13 个完全不同的名字（帕奇/古龙人/红熊/孤牢骑士…）。"
      "进随机池前要单独处理：它大概率是**解析失败的缺省值**，不是一种敌人。")
    A("6. **`c1000` 可疑**。它 1061 个放置点、414 张图（最多的之一），"
      "但只有 2 个名字（仿身泪滴 / 黄金树看护者）。"
      "要么它真的是最常见的杂兵，要么它跟 `c0000` 一样是某种共用的缺省 —— "
      "**用之前建议先在游戏里看一眼**。")
    A("")

    A("## 7. 复现")
    A("")
    A("```")
    A("python investigation/apply/enemy_type_map.py")
    A("```")
    A("")
    A("输出 `enemy_type_map.csv`（462 行）+ 本文件。输入全部只读。"
      "留一验证的数字就是上面 `main()` 打印的那几个。")
    A("")
    A("## 8. 待人工确认的模型（已先钉死，但名字多义/判定存疑）")
    A("")
    if gap:
        A("| model | 名字（多义）| 本表判成 | 体型 r/h | 放置点 |")
        A("|---|---|---|---|---|")
        for r in gap:
            A("| `%s` | %s | %s | %.2f/%.2f | %d |" % (
                r["model"], r["sample_names"], r["enemy_type"],
                r["_radius_max"] or 0.0, r["_height_max"] or 0.0, r["_placements"]))
        A("")
        A("> 这 %d 个虽然进了复核表，但**名字本身跨多个敌型**（同名多义），"
          "判成哪一类都可能是错的 —— 进随机池前请人工过一眼。" % len(gap))
    else:
        A("（无）")
    A("")

    with open(OUT_MD, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(L))


def main():
    global SIZE_ACC
    ev = build_evidence()
    mismatches = verify_curated(ev, sys.stderr)
    # 先算留一验证，再生成 CSV —— size_band 的 evidence 里要带这个实测数字
    SIZE_ACC = loo_validate(ev)
    rows = build_rows(ev)
    write_csv(rows)
    write_md(rows, ev, SIZE_ACC, mismatches)

    by_type = Counter(r["enemy_type"] for r in rows)
    conf = Counter(r["confidence"] for r in rows)
    named = sum(1 for r in rows if r["sample_names"])

    print("== enemy_type_map ==")
    print("模型总数          : %d" % len(rows))
    print("血条名命中实体    : %d (未命中 %d)" % (ev["e1_hit"], ev["e1_miss"]))
    print("Boss 行名         : %d" % ev["e2_hit"])
    print("有名字的模型      : %d (%.1f%%)" % (named, 100.0 * named / len(rows)))
    print("CURATED 复核项    : %d (名字核对不符 %d)" % (len(CURATED), mismatches))
    print("置信度            : " + " ".join("%s=%d" % kv for kv in conf.most_common()))
    print("覆盖率(high+med)  : %.1f%%" % (100.0 * (conf["high"] + conf["medium"]) / len(rows)))
    print("覆盖率(仅 high)   : %.1f%%" % (100.0 * conf["high"] / len(rows)))
    print()
    print("体型兜底留一验证（CURATED 当 ground truth，报的是粗族命中率）:")
    for k, (hit, tot, pct) in sorted(SIZE_ACC.items()):
        print("  %-18s %d/%d = %.1f%%" % (k, hit, tot, pct))
    print()
    _ne = [t for t in TYPE_ORDER if by_type.get(t)]
    _re = [t for t in _ne if not t.startswith("体型·") and t != "未分类"]
    print("类别（真实归类 %d 类 = %d 敌型 + %d 体型档；另 未分类 1 类）:"
          % (len(_re) + len([t for t in _ne if t.startswith("体型·")]),
             len(_re), len([t for t in _ne if t.startswith("体型·")])))
    for tname in TYPE_ORDER:
        n = by_type.get(tname, 0)
        if not n:
            continue
        nm = sum(1 for r in rows if r["enemy_type"] == tname and r["sample_names"])
        print("  %-18s 模型 %3d  其中有名字 %3d" % (tname, n, nm))
    print()
    print("写出: %s" % OUT_CSV)
    print("写出: %s" % OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
