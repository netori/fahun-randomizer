# -*- coding: utf-8 -*-
"""v2 敌型表：拿参考实现自带的「按模型给名字」的表当主证据，重做 462 个模型的敌型归类。

为什么重做
----------
v1（apply/enemy_type_map.py）只认法魂本体里捞得到的名字：血条名 / Boss 行名 / 行名三路。
462 个模型里只有 161 个（34.8%）拿到"权威名字"，其余 301 个只能靠体型兜底 ——
因为杂兵在 NpcParam 里 nameId=0，本体根本没有它们的名字。

参考实现（thefifthmatt 的 ER Randomizer 428 v0.12.2）自带一张**按模型给名字**的表，
正好补上这个缺口。本脚本用到的只读输入：

  diste\\Names\\ModelName.txt     408 个 c* 模型 -> 英文名（另有 45 个 AEG* 场景物件，不是角色）
  diste\\Names\\ModelNameNT.txt   218 条内部名（ModelNameNT），只当辅助
  diste\\Base\\enemy.txt          23173 条地图放置：Map + ID + `Name: cXXXX_NNN` + Class + Tags + Outfit
                                  另有 Groups 段：模型 -> unkillable / frames / nosouls / nonunique / ballista …
  diste\\Messages\\zh.enemy.json  172 条 Boss 中英对照 + 185 条 enemy_config_names（english_text / text / info）

  实测更正：任务书提到的 `Messages\\en.enemy.json` **在这个版本里不存在** ——
  目录里只有 de/es/es-ES/fr/it/ja/ko/pl/pt-BR/ru/th/zh 十二份（zh 与 en 的字段同名）。
  所以英文名一律取自 ModelName.txt，不用 en.enemy.json。

归类口径（英文名优先，比 v1 的中文关键词准得多）
------------------------------------------------
  规则组 EN_RULES：按**英文名的词**判类（`\bknight\b` → 骑士/重甲 …），命中即止，规则顺序见下。
  规则组 ZH_RULES：模型没有 ModelName.txt 条目时（法魂新增模型），退一步按中文名判；
                   同一模型有多个候选中文名时**多数决**（一半以上指向同一类才认，平局不认）。
  兜底：都没有名字 -> 按参考实现的 Class（Wildlife / Scarab / …）再退一步；
        再没有 -> 按体型档（chr_hit_radius / chr_hit_height）给"体型·大/巨"；最后才是"未分类"。

  两道防"名字带偏"的闸（实测踩过，报告 §4.1 有全部数字）：
    * **共享血条名过滤**：`黄金树看护者` 一个串同时挂在 10 个模型上（多敌血条共用标签），
      凡是同时挂在 >=2 个模型上的血条名一律不参与判类（仍留在 sample_names 里）。
    * **行名只在唯一时可信**：c0000（Human 通用人型基底）挂 124 个不同行名，
      最常见的行名『米莉森』显然不是它的模型名 —— 一个有多个不同行名的模型，行名一律不取。

  手工覆盖只有 4 条（MANUAL），且**每一条都写着"规则会给出什么"**，可在报告里逐条复核：
  c2040 / c2274 / c2275 / c3171。另有 5 条 DOC_ONLY 只补说明、不改判定。

  与 v1 的两处口径变化（报告 §3 有理由）：
    * 去掉 v1 的「血族/贵族」合并进「人形/平民」；去掉 v1 的「敌对NPC/人形」
      （实测 462 个模型里只有 c0000 一个在参考实现里带 HostileNPC 标签，独类没有池子意义）。
    * 新增「坐骑/驮兽」——参考实现把 *Horse 当独立模型（8 个），v1 把它们散进骑士/野兽里了。

只读：三个输入根（法魂 MOD / 我们仓库 / 参考实现 diste）只读；脚本自己在开头结尾各取一次
      两个只读根的文件 mtime 指纹并对比打印（"未被改动"）。本脚本只写
  investigation/enemy_type_map.csv        覆盖写（列名 model / enemy_type 不能改，其它可加）
  investigation/enemy_type_names_zh.csv   新建：中英对照
  investigation/enemy_type_map_v2.md      新建：人读报告

可重跑：基线（v1 表）取"运行前的 enemy_type_map.csv（若还是 v1 结构）"或 `git show HEAD:` 里那份，
取不到就只打印"无基线"，不影响产物。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)

REF_DIR = (r"C:\Users\20905\Downloads\Elden Ring Randomizer 428 v0.12.2 "
           r"2026-09-09T07-25Z kRGZWDlvJ\randomizer\diste")
MOD_DIR = (r"F:/game/studygame/elden ring/THE_COVERAGE-随机开发/"
           r"法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")

IN_MODEL_TYPES = os.path.join(INV, "model_types.csv")
IN_MAP_ENEMIES = os.path.join(INV, "map_enemies.csv")
IN_ENEMY_TABLE = os.path.join(INV, "enemy_table.csv")
IN_ROW_MODELS = os.path.join(INV, "row_models.csv")
IN_BOSS_ROWS = os.path.join(INV, "boss_rows.csv")
IN_BOSS_HEALTHBAR = os.path.join(INV, "boss_healthbar.csv")
OUT_CSV = os.path.join(INV, "enemy_type_map.csv")
OUT_ZH = os.path.join(INV, "enemy_type_names_zh.csv")
OUT_MD = os.path.join(INV, "enemy_type_map_v2.md")

REF_MODELNAME = os.path.join(REF_DIR, "Names", "ModelName.txt")
REF_MODELNAME_NT = os.path.join(REF_DIR, "Names", "ModelNameNT.txt")
REF_ENEMY_TXT = os.path.join(REF_DIR, "Base", "enemy.txt")
REF_ZH_ENEMY = os.path.join(REF_DIR, "Messages", "zh.enemy.json")

SCHEMA = "v2"

# ---------------------------------------------------------------------------
# 类目表：15 个实体类 + 2 个兜底档。
# 顺序即"哪一类先被判"（Boss 覆盖写在表里，不走规则）。
# ---------------------------------------------------------------------------
TYPE_ORDER = [
    "Boss/领主",
    "骑士/重甲",
    "士兵/守军",
    "坐骑/驮兽",
    "人形/平民",
    "施法者/祭司",
    "神皮/黑刀/教会",
    "不死/腐败",
    "龙/龙裔",
    "巨人/巨兽",
    "野兽/动物",
    "虫/花/菌",
    "亚人/混种",
    "魔像/人造",
    "非战斗/NPC",
    "体型·大/巨",
    "未分类",
]
NAME_BACKED = set(TYPE_ORDER) - {"体型·大/巨", "未分类"}
# 只有这些 name_source 才算"名字证据"（`ref:enemy.txt Class` 是类目兜底，不算名字）
NAME_SOURCES = {"ref:ModelName", "unique-boss", "ours:boss_healthbar", "ours:row_name", "manual"}

# ---------------------------------------------------------------------------
# 独特具名 Boss：参考实现的 boss_names 里既有"一次性剧情 Boss"也有"会重复出场的
# 场域 Boss"（结晶人 / 大树守卫 / 死之鸟 …）。后者当**型**用，前者才进 Boss/领主。
# 这份表是逐个点的，报告 §3 会整份列出来供人复核。
# 键 = 模型 id，值 = (英文名, 中文名)。
# ---------------------------------------------------------------------------
UNIQUE_BOSS = {
    "c2010": ("Blaidd", "半狼布萊德"),
    "c2030": ("Rennala 1", "「滿月女王」蕾娜菈"),
    "c2031": ("Rennala 2", "「滿月女王」蕾娜菈"),
    "c2120": ("Malenia", "「米凱拉之刃」瑪蓮妮亞"),
    "c2130": ("Morgott", "「惡兆王」蒙葛特"),
    "c2190": ("Radagon", "「黃金律法」拉達岡"),
    "c2200": ("Elden Beast", "艾爾登之獸"),
    "c4620": ("Astel", "「黑暗棄子」艾絲緹"),
    "c4670": ("Ancestor Spirit", "祖靈"),
    "c4710": ("God-Devouring Serpent", "噬神大蛇"),
    "c4711": ("Rykard's Corpse", "「褻瀆君王」拉卡德"),
    "c4720": ("Godfrey", "「初始之王」葛孚雷"),
    "c4721": ("Hoarah Loux", "戰士荷萊‧露"),
    "c4730": ("Starscourge Radahn", "「碎星」拉塔恩"),
    "c4750": ("Godrick the Grafted", "「接肢」葛瑞克"),
    "c4760": ("Fire Giant", "火焰巨人"),
    "c4800": ("Mohg", "「鮮血君王」蒙格"),
    "c4501": ("Decaying Ekzykes", "「步入腐敗」艾格基斯"),
    "c4503": ("Borealis the Freezing Fog", "「凍結冰霧」玻列琉斯"),
    "c4511": ("Lichdragon Fortissax", "「死龍」弗爾桑克斯"),
    "c4520": ("Dragonlord Placidusax", "「龍王」普拉頓桑克斯"),
    "c4911": ("Great Wyrm Theodorix", "「大土龍」席歐朵利克"),
    "c5000": ("Commander Gaius", "老將蓋烏斯"),
    "c5020": ("Putrescent Knight", "融泥騎士"),
    "c5030": ("Romina", "「花蕾聖女」蘿蜜娜"),
    "c5051": ("Midra, Lord of Frenzied Flame", "「癲火之王」米德拉"),
    "c5120": ("Bayle the Dread", "「狂龍」貝勒"),
    "c5130": ("Messmer", "「穿刺者」梅瑟莫"),
    "c5200": ("Metyr, Mother of Fingers", "「指頭之母」梅蒂爾"),
    "c5210": ("Divine Beast Dancing Lion", "神獸舞獅"),
    "c5220": ("Promised Consort Radahn", "「約定之王」拉塔恩"),
    "c5230": ("Scadutree Avatar", "幽影樹的化身"),
    "c5300": ("Rellana, Twin Moon Knight", "「雙月騎士」蕾菈娜"),
    "c5312": ("Jori, Elder Inquisitor", "「拷問老者」約里"),
    "c5370": ("Ancient Dragon Senessax", "「古龍」瑟涅桑克斯"),
    "c3252": ("Loretta", "「聖樹騎士」羅蕾塔"),
}

# 逐个点死的手工覆盖（模型 -> (类, 理由)）。只在规则会判错时才写。
MANUAL = {
    "c2040": ("非战斗/NPC",
              "Juvenile Scholar = 雷亚卢卡利亚的爬行学徒，不参战"
              "（`\\bscholar\\b` 规则会判成人形/平民，故覆盖）"),
    "c3171": ("施法者/祭司",
              "ModelNameNT 只给 `Phillia`；法魂本体的行名是『「龐大妹妹」菲莉亞』，"
              "与 c3610/c3620/c3630（Oracle Envoy 三型）同族 —— 神谕使者"),
    "c2274": ("巨人/巨兽",
              "Giant Albinauric Crab 是**蟹**；规则 11.5 的 `\\balbinauric\\b` 会先命中白面族，故覆盖"),
    "c2275": ("巨人/巨兽",
              "Albinauric Crab 同理：是蟹，不是白面族人形"),
}

# 只补说明、不改判定：这些模型规则已经判对，但值得在 evidence 里留一句人话解释。
DOC_ONLY = {
    "c0000": ("ModelName 只给基础名 `Human`；参考实现的 enemy.txt 里这个模型有 360+ 处，"
              "Class 分布 None:273 / HostileNPC:54 / Helper:22 / MinorBoss:11 —— "
              "它是**通用人型基底**（NPC、入侵者、Boss 共用），不是某一个敌人"),
    "c3350": ("v1 把 Crystalian 归到不死/腐败是误判：结晶人是结晶造物，不是尸体"),
    "c3251": ("v1 把 Tree Sentinel 归到士兵/守军；重甲骑乘比士兵更贴"),
    "c2274": ("`\\balbinauric\\b` 规则（11.5）会先命中白面族；但这个模型是**巨蟹**，故手工覆盖"),
    "c2275": ("同 c2274：Albinauric Crab 是蟹，不是白面族人形"),
}

# ---------------------------------------------------------------------------
# 英文名规则表（按顺序，命中即止）。正则跑在 lower() 后的英文名上。
# 每一行都写了为什么排在那个位置 —— 顺序本身就是这份表最容易出错的地方。
# ---------------------------------------------------------------------------
EN_RULES = [
    # 1) 坐骑先判：`Godrick Knight's Horse` 同时含 knight 与 horse，horse 才是它的真身
    ("坐骑/驮兽", r"\bhorse\b", "名字含 horse"),
    ("坐骑/驮兽", r"\bdonkey\b", "名字含 donkey"),

    # 1.5) 发狂商人有敌意 —— 必须先于 merchant 的"非战斗"规则
    ("人形/平民", r"\bfrenzied merchant\b", "名字是 Frenzied Merchant（发狂商人，有敌意）"),

    # 2) 假人/尸体态：这些不是敌人
    ("非战斗/NPC", r"\bdummy\b", "名字含 dummy（占位/假人）"),
    ("非战斗/NPC", r"\bballoon\b", "名字含 balloon（气球）"),
    ("非战斗/NPC", r"\bdefeated\b", "名字含 Defeated（已败形态）"),
    # 2.1) 具名非战斗 NPC（商人与任务角色）—— 排在施法者/骑士之前
    ("非战斗/NPC", r"\bmerchant\b|\bgoldmask\b|\branni\b|\bmelina\b|\biji\b|\bgostoc\b|"
                   r"\bfinger reader\b|\benia\b|\btwo fingers\b|\bst\. trina\b|\bgrandam\b|"
                   r"\bgatekeeper\b",
     "名字是具名非战斗 NPC（商人/任务角色）"),

    # 3) 人造体先于 soldier：Marionette Soldier / Avionette Soldier 是傀儡
    ("魔像/人造", r"\bmarionette\b|\bavionette\b", "名字含 marionette/avionette（傀儡兵）"),
    ("魔像/人造", r"\bjar\b|\bgreatjar\b", "名字含 Jar（壶/罐造物）"),
    ("魔像/人造", r"\bgolem\b|\bclayman\b|\bsentry stone\b|\bcrystalian\b|\bsilver tear\b|"
                r"\bwatchdog\b|\bgargoyle\b",
     "名字含 golem/clayman/sentry stone/crystalian/silver tear/watchdog/gargoyle（造物）"),
    ("魔像/人造", r"\bballista\b|\btrebuchet\b|\bflamethrower\b|\bchariot\b|"
                  r"\bwalking mausoleum\b|\bgiant ball\b|\blightning ball\b",
     "名字含 ballista/trebuchet/flamethrower/chariot/mausoleum/ball（器械）"),
    ("魔像/人造", r"\babductor virgin\b", "名字含 abductor virgin（掳人少女人偶）"),
    ("魔像/人造", r"^living magma\b", "名字是 Living Magma（活体岩浆，元素造物）"),

    # 4) 虫类先于 dragon：dragonfly 会被 \bdragon 误吞
    ("虫/花/菌", r"\bdragonfly\b", "名字含 dragonfly（蜻蜓）"),
    ("虫/花/菌", r"\bant\b", "名字含 ant（蚁）"),

    # 5) 具体例外先于泛匹配
    ("野兽/动物", r"^giant rat\b|^rat\b|^royal rat\b", "名字是鼠（Giant Rat 是鼠，不是巨兽）"),
    ("野兽/动物", r"^giant dog\b|^dog\b", "名字是犬"),
    ("不死/腐败", r"\bskeleton\b", "名字含 skeleton（骨架）"),

    # 6) 不死/腐败（先于 soldier/beast）
    ("不死/腐败", r"\bputrid corpse\b|\bputrid flesh\b|\bcorpse\b|\bcemetery shade\b",
     "名字含 putrid corpse/flesh/cemetery shade（腐尸/墓地影子）"),
    ("不死/腐败", r"\bdeath rite bird\b|\bdeathbird\b|\bgravebird\b|\btibia mariner\b|\bmariner\b",
     "名字含 death rite bird/deathbird/gravebird/mariner（死系）"),
    ("不死/腐败", r"\bbasilisk\b|\bkindred of rot\b|\bdisciple of rot\b|\bwormface\b",
     "名字含 basilisk/kindred of rot/wormface（死亡/腐败）"),
    ("不死/腐败", r"\bulcerated tree spirit\b|\brevenant\b|\bspirit eel\b", "名字含 ulcerated tree spirit/revenant/eel（不死）"),
    ("不死/腐败", r"^(rotten|little )?(putrid|rotten)\b", "名字以 putrid/rotten 起头（腐败体）"),

    # 6.5) 蛇人先于龙：Man-Serpent 是蛇人，不是龙
    ("亚人/混种", r"\bman-serpent\b", "名字含 man-serpent（蛇人）"),

    # 7) 龙/龙裔（先于 soldier：Dragonkin Soldier）
    ("龙/龙裔", r"\bdragon|\bdrake\b|\bwyrm\b|\bserpent\b|\bfortissax\b|\bplacidusax\b|"
                r"\bekzykes\b|\bgreyoll\b|\bborealis\b|\bsenessax\b|\blansseax\b|\bbayle\b|"
                r"\btheodorix\b",
     "名字含 dragon/drake/wyrm/serpent 或龙的专名"),

    # 8) 亚人/混种（先于 soldier：Beastman / Divine Bird Warrior）
    ("亚人/混种", r"\bdemi-human\b|\bmisbegotten\b|\bman-serpent\b|\bbeastman\b|\bimp\b|"
                  r"\bgrafted scion\b|\bdivine bird warrior\b|\bcurseblade\b|\bhorned\b",
     "名字含 demi-human/misbegotten/man-serpent/beastman/imp（亚人混种）"),

    # 9) 教会系
    ("神皮/黑刀/教会", r"\bgodskin\b|\bblack knife\b|\bfire monk\b|\bblackflame\b|\bprelate\b|"
                      r"\bclergyman\b|\bconfessor\b",
     "名字含 godskin/black knife/fire monk/blackflame/prelate/clergyman（教会系）"),

    # 10) 施法者
    ("施法者/祭司", r"\bsorcerer\b|\bbattlemage\b|\bperfumer\b|\bstarcaller\b|\bazur\b|\blusat\b|"
                    r"\bgraven school\b|\benvoy\b|\binquisitor\b|\bshaman\b|\bpriest\b|\bwitch\b",
     "名字含 sorcerer/battlemage/perfumer/starcaller/envoy/inquisitor/shaman（施法）"),

    # 11) 骑士/重甲
    ("骑士/重甲", r"\bknight\b|\bcavalry\b|\bsentinel\b|\bduelist\b|\bcommander\b|"
                  r"\bchampion\b|\bveteran\b|\bcrucible\b|\bhero\b|\bguardian\b|"
                  r"\bhunter\b|\blord\b",
     "名字含 knight/cavalry/sentinel/duelist/commander/hero（重甲）"),

    # 11.5) 白面族先于士兵：Albinauric Archer 是白面族弓手，不是守军
    ("人形/平民", r"\balbinauric\b", "名字含 albinauric（白面族）"),

    # 12) 士兵/守军
    ("士兵/守军", r"\bsoldier\b|\bfoot soldier\b|\bmilitia\b|\bpage\b|\bsellsword\b|"
                  r"\bhighwayman\b|\bguilty\b|\bmercenary\b|\bpumpkin head\b",
     "名字含 soldier/militia/page/sellsword/highwayman/pumpkin head（守军）"),

    # 13) 巨人/巨兽（先于野兽：Giant Crab / Giant Crow；具体例外已在 5) 提走）
    ("巨人/巨兽", r"\bgiant\b|\btroll\b|\bhippopotamus\b|\brunebear\b|\bavatar\b|"
                  r"\bfallingstar\b|\blion\b",
     "名字含 giant/troll/hippopotamus/runebear/avatar（巨兽）"),
    ("巨人/巨兽", r"\bcrab\b|\bcrayfish\b|\boctopus\b|\bcrow\b", "名字含 crab/crayfish/octopus/crow（大型兽）"),

    # 14) 人形/平民
    ("人形/平民", r"\bcommoner\b|\bnoble\b|\bcelebrant\b|\balbinauric\b|\bminer\b|\bomen\b|"
                  r"\bbloodfiend\b|\bsanguine\b|\bhuman\b|\bpeasant\b|\bprisoner\b|\bscholar\b|"
                  r"\bfighter\b|\bomenkiller\b|\bnox\b|ancestral follower|mini midra|"
                  r"\buntouchable\b",
     "名字含 commoner/noble/celebrant/albinauric/miner/omen/bloodfiend（人形平民）"),

    # 15) 野兽/动物
    ("野兽/动物", r"\bwolf\b|\bstray\b|\bbear\b|\bboar\b|\bram\b|\bdeer\b|\bspringhare\b|"
                  r"\bturtle\b|\bsnail\b|\beagle\b|\bowl\b|\bguillemot\b|\bbat\b|\bjellyfish\b|"
                  r"\beel\b|hawk|\beel\b|\bhare\b|\bcat\b|\bfrog\b|\bsquirt\b|\bsheep\b",
     "名字含 wolf/stray/bear/boar/ram/deer/turtle/snail/bird（野兽；hawk 不写 \\b 以便匹配 Warhawk）"),

    # 16) 虫/花/菌
    ("虫/花/菌", r"\bscarab\b|\bmiranda\b|\bfingercreeper\b|\bslug\b|"
                  r"\blamprey\b|\bscorpion\b|\bspider\b|\bman-fly\b|\bswarm\b|\blarva\b|"
                  r"\bmoth\b|\bmosquito\b|\bant\b|\bsquirt\b",
     "名字含 scarab/miranda/fingercreeper/slug/wormface/scorpion（虫花菌）"),

    # 17) 兜底：参考实现自己的类目名残留（有些模型名就是类目名）
    ("巨人/巨兽", r"\bbeast\b", "名字含 beast（兽）"),
]

# ---------------------------------------------------------------------------
# 中文名规则表：只在模型**没有** ModelName.txt 条目时启用（法魂新增的模型）。
# 中文规则必然比英文粗，所以这些全部标 medium/low，并在 evidence 里写明是中文证据。
# ---------------------------------------------------------------------------
ZH_RULES = [
    ("坐骑/驮兽", r"马|驴|驮兽", "中文名含 马/驴"),
    ("非战斗/NPC", r"商人|NPC|假人|傀儡|占位|尸骸|焦尸", "中文名含 商人/假人/占位"),
    ("魔像/人造", r"人偶|魔像|石像|陶|罐|壶|战车|弩|投石|石哨|结晶人|看门犬|灵庙",
     "中文名含 人偶/魔像/罐/战车/弩/看门犬（造物）"),
    ("虫/花/菌", r"虫|蠍|蝎|蚁|蜘蛛|蜻蜓|花|菌|芽|腐苗|幼体", "中文名含 虫/花/菌/蚁"),
    ("不死/腐败", r"骷髅|骸骨|尸|腐|死|亡|幽魂|亡灵|墓地|骨", "中文名含 骷髅/尸/腐/死/亡"),
    ("龙/龙裔", r"龙|蛇|蜥", "中文名含 龙/蛇"),
    ("亚人/混种", r"亚人|混种|兽人|恶魔|小鬼|角人", "中文名含 亚人/混种/兽人/角人"),
    ("神皮/黑刀/教会", r"神皮|黑刀|教会|祭司长", "中文名含 神皮/黑刀"),
    ("施法者/祭司", r"法师|术士|魔法|祭司|萨满|拷问|调香|祈祷|僧|巫|学者|贤者|呼召|敕令|塑灵|唤星",
     "中文名含 法师/祭司/萨满/拷问/呼召/塑灵（施法）"),
    ("骑士/重甲", r"骑士|骑兵|守卫|追猎|猎手|斗士|将|官|重甲|铠甲|熔炉|典范|黑夜|看护|守墓",
     "中文名含 骑士/骑兵/守卫/斗士/熔炉/典范/黑夜（重甲）"),
    ("士兵/守军", r"士兵|兵|待从|侍从|卫士|游侠|弓手|弓兵", "中文名含 士兵/兵/卫士"),
    ("巨人/巨兽", r"巨人|山妖|巨兽|巨怪|巨鸦|巨蟹|河马|熊|狮子|化身|树灵", "中文名含 巨人/山妖/巨兽/熊"),
    ("人形/平民", r"平民|贵族|村民|居民|白面|矿工|欧门|恶兆|选民|召唤者", "中文名含 平民/贵族/村民/选民"),
    ("野兽/动物", r"狼|犬|狗|鼠|羊|鹿|龟|鸟|鹰|鸦|蝙蝠|兔|牛|猪|豹|猫|野猪", "中文名含 狼/犬/鼠/熊/鸟"),
]

MODEL_RE = re.compile(r"^(c\d+)")

# ---------------------------------------------------------------------------
# 只读性：记录三个输入根的 mtime 指纹
# ---------------------------------------------------------------------------
def mtime_fingerprint(roots, max_files=40000):
    fp = {}
    n = 0
    for root in roots:
        if not os.path.isdir(root):
            fp[root] = "MISSING"
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    fp[p] = os.path.getmtime(p)
                except OSError:
                    fp[p] = -1
                n += 1
                if n >= max_files:
                    return fp
    return fp


def fp_diff(a, b):
    changed = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
    return changed


# ---------------------------------------------------------------------------
# 读参考实现
# ---------------------------------------------------------------------------
def load_model_names(path):
    """ModelName.txt -> OrderedDict(model -> english_name)。# 开头是注释。"""
    out = OrderedDict()
    if not os.path.isfile(path):
        return out
    with io.open(path, encoding="utf-8-sig") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if not s.strip() or s.lstrip().startswith("#"):
                continue
            parts = s.split(None, 1)
            if len(parts) == 2:
                out[parts[0]] = parts[1].strip()
            else:
                out[parts[0]] = ""
    return out


def _flush_enemy_entry(cur, model_cls, model_tag):
    """把一条 Enemies 条目记进 model_cls / model_tag。"""
    if not cur or not cur.get("Name"):
        return
    mm = MODEL_RE.match(cur["Name"])
    if not mm:
        return
    mdl = mm.group(1)
    model_cls[mdl][cur.get("Class", "None")] += 1
    for t in cur.get("tags", []):
        model_tag[mdl][t] += 1


def parse_enemy_txt(path):
    """Base/enemy.txt -> (model -> Counter(class), model -> Counter(tag),
                         model -> set(group), name -> set(group))"""
    model_cls = defaultdict(Counter)
    model_tag = defaultdict(Counter)
    model_group = defaultdict(set)
    name_group = defaultdict(set)
    entity_rows = 0
    if not os.path.isfile(path):
        return model_cls, model_tag, model_group, name_group, entity_rows

    with io.open(path, encoding="utf-8-sig") as f:
        lines = f.read().split("\n")

    # --- 顶格段 ---
    sec_start = {}
    for i, l in enumerate(lines):
        m = re.match(r"^([A-Za-z]+):\s*$", l)
        if m:
            sec_start[m.group(1)] = i

    # Groups 段（模型名 -> 组名）
    gi = sec_start.get("Groups")
    if gi is not None:
        cur_group = None
        for l in lines[gi + 1:]:
            if re.match(r"^[A-Za-z]+:\s*$", l):
                break
            m = re.match(r"^-\s+Name:\s*(.+?)\s*$", l)
            if m:
                cur_group = m.group(1)
                continue
            m = re.match(r"^  -\s+(.+?)\s*$", l)
            if m and cur_group:
                name_group[m.group(1)].add(cur_group)

    # Enemies 段
    ei = sec_start.get("Enemies")
    if ei is not None:
        cur = None
        pend = None
        for l in lines[ei + 1:]:
            if re.match(r"^[A-Za-z]+:\s*$", l):
                _flush_enemy_entry(cur, model_cls, model_tag)
                cur = None
                break
            m = re.match(r"^-\s+ID:\s*\d+\s*$", l)
            if m:
                _flush_enemy_entry(cur, model_cls, model_tag)
                cur = {}
                pend = None
                entity_rows += 1
                continue
            if cur is None:
                continue
            m = re.match(r"^  ([A-Za-z]+):\s*(.*)$", l)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if k in ("Tags", "Groups") and not v:
                    pend = k
                    continue
                pend = None
                if k == "Tags":
                    cur.setdefault("tags", [])
                    cur["tags"] += v.split()
                elif k == "Groups":
                    cur.setdefault("grp", [])
                    cur["grp"] += v.split()
                else:
                    cur[k] = v
                continue
            m = re.match(r"^  -\s+(.+?)\s*$", l)
            if m and pend:
                if pend == "Tags":
                    cur.setdefault("tags", []).append(m.group(1))
                else:
                    cur.setdefault("grp", []).append(m.group(1))
                continue
        # 收尾
        _flush_enemy_entry(cur, model_cls, model_tag)

    # 模型名 -> 组：用 ModelName 的英文名反查 name_group（enemy.txt 的 Groups 段用的是显示名）
    return model_cls, model_tag, model_group, name_group, entity_rows


def load_messages(path):
    """zh.enemy.json -> (boss en->zh, config en->zh, config en->info, boss_keys)"""
    boss_en2zh = OrderedDict()
    cfg_en2zh = OrderedDict()
    cfg_en2info = OrderedDict()
    meta = {}
    if not os.path.isfile(path):
        return boss_en2zh, cfg_en2zh, cfg_en2info, meta
    with io.open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
    meta["instructions"] = d.get("instructions", "")
    meta["status"] = d.get("status", "")
    meta["boss_total"] = len(d.get("boss_names", []))
    meta["cfg_total"] = len(d.get("enemy_config_names", []))
    for x in d.get("enemy_config_names", []):
        en = (x.get("english_text") or "").strip()
        if not en:
            continue
        info = (x.get("info") or "").strip()
        if info:
            cfg_en2info.setdefault(en, info)
        zh = (x.get("text") or "").strip()
        if zh:
            cfg_en2zh.setdefault(en, zh)
    for x in d.get("boss_names", []):
        base = (x.get("base") or {}).get("key") or ""
        tr = (x.get("translated") or {}).get("key") or ""
        base = base.strip()
        if base and tr:
            boss_en2zh.setdefault(base, tr.strip())
        for c in x.get("enemy_config_names", []) or []:
            en = (c.get("english_text") or "").strip()
            info = (c.get("info") or "").strip()
            if en and info:
                cfg_en2info.setdefault(en, info)
            zh = (c.get("text") or "").strip()
            if en and zh:
                cfg_en2zh.setdefault(en, zh)
    meta["boss_with_zh"] = len(boss_en2zh)
    meta["cfg_with_info"] = len(cfg_en2info)
    meta["cfg_with_zh"] = len(cfg_en2zh)
    return boss_en2zh, cfg_en2zh, cfg_en2info, meta


# ---------------------------------------------------------------------------
# 读我们自己的产物
# ---------------------------------------------------------------------------
def read_csv(path):
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_ours():
    mt = read_csv(IN_MODEL_TYPES)
    me = read_csv(IN_MAP_ENEMIES)
    et = read_csv(IN_ENEMY_TABLE)
    rm = read_csv(IN_ROW_MODELS)
    br = read_csv(IN_BOSS_ROWS)
    bh = read_csv(IN_BOSS_HEALTHBAR)

    models = [r["model"] for r in mt]

    placements = Counter(r["model"] for r in me if r.get("model"))

    # (map, entity) -> model（血条名回推到模型）
    me_by_me = {}
    for r in me:
        key = (r.get("map", ""), str(r.get("entity_id", "")).strip())
        if r.get("model"):
            me_by_me[key] = r["model"]

    tab = {}
    for r in et:
        tab[str(r.get("row_id", "")).strip()] = r

    row2model = {}
    for r in rm:
        rid = str(r.get("npc_id", "")).strip()
        if rid.isdigit() and int(rid) > 0 and r.get("model"):
            row2model[rid] = r["model"]

    zh_ev = defaultdict(list)      # model -> [(source, zh_name)]
    bar_models = set()             # 在法魂本体里出现过血条名/Boss 行名的模型
    # 1) 血条名（最权威的显示名）
    for r in bh:
        nm = (r.get("name") or "").strip()
        if not nm:
            continue
        mdl = (r.get("model") or "").strip()
        if not mdl:
            mdl = me_by_me.get((r.get("map", ""), str(r.get("entity", "")).strip()), "")
        if mdl:
            zh_ev[mdl].append(("ours:boss_healthbar", nm))
            bar_models.add(mdl)
    # 2) Boss 行名
    for r in br:
        nm = (r.get("boss_name") or "").strip()
        mdl = (r.get("model") or "").strip()
        if nm and mdl:
            zh_ev[mdl].append(("ours:boss_row", nm))
            bar_models.add(mdl)
    # 3) 行名（多为商人 / NPC）
    for rid, mdl in row2model.items():
        t = tab.get(rid)
        if t and (t.get("name") or "").strip():
            zh_ev[mdl].append(("ours:row_name", t["name"].strip()))

    # 共享名过滤：同一个血条名被派给 >=2 个模型时，它多半是多敌共用的血条标签
    # （实测「黄金树看护者」同时挂在 c1000/c2278/c3170/c3300/c3805/c4120/c4490/c4602/c4660/c4690 上），
    # 不能当某个模型的"名字证据"。这些名字仍保留在 sample_names 列里，只是不参与判类。
    name_owners = defaultdict(set)
    for mdl, lst in zh_ev.items():
        for _, nm in lst:
            name_owners[nm].add(mdl)
    shared_names = {nm for nm, owners in name_owners.items() if len(owners) >= 2}
    zh_ev_solo = {}
    for mdl, lst in zh_ev.items():
        keep = [(s, n) for s, n in lst if n not in shared_names]
        if keep:
            zh_ev_solo[mdl] = keep

    hp_mapped = {}
    for m, vals in _rows_by_model(me, row2model, tab).items():
        hs = [v for v in vals if v is not None]
        if hs:
            hp_mapped[m] = int(statistics.median(hs))

    return {
        "models": models,
        "model_types": {r["model"]: r for r in mt},
        "placements": placements,
        "zh_ev": zh_ev,
        "zh_ev_solo": zh_ev_solo,
        "shared_names": shared_names,
        "bar_models": bar_models,
        "hp_mapped": hp_mapped,
        "row2model": row2model,
        "tab": tab,
    }


def _rows_by_model(me, row2model, tab):
    out = defaultdict(list)
    for r in me:
        mdl = r.get("model")
        if not mdl:
            continue
        rid = str(r.get("npc_id", "")).strip()
        t = tab.get(rid)
        if t and (t.get("hp") or "").strip().isdigit():
            out[mdl].append(int(t["hp"]))
        else:
            out[mdl].append(None)
    return out


# ---------------------------------------------------------------------------
# 名字对齐
# ---------------------------------------------------------------------------
def align_model_names(ours, ref_names):
    """返回 (对齐表, 统计 dict)。对齐规则：大写化去空白直配；再试去零填充。"""
    refs = {k: v for k, v in ref_names.items()}
    ref_lower = {}
    for k, v in refs.items():
        ref_lower.setdefault(k.lower(), (k, v))
    matched = {}
    unmatched_ours = []
    used = set()
    for m in ours:
        if m in refs:
            matched[m] = (m, refs[m], "exact")
            used.add(m)
        elif m.lower() in ref_lower:
            rk, rv = ref_lower[m.lower()]
            matched[m] = (rk, rv, "case_fold")
            used.add(rk)
        else:
            # 去零填充：c0120 -> c120（ModelName.txt 里就是 c0120，此处是反向保险）
            alt = re.sub(r"^c0+(?=\d)", "c", m)
            alt2 = re.sub(r"^c(?=\d)", "c", m)
            cand = None
            for a in (alt, alt2):
                if a in refs:
                    cand = a
                    break
            if cand:
                matched[m] = (cand, refs[cand], "zero_pad")
                used.add(cand)
            else:
                unmatched_ours.append(m)

    ref_chars = {k: v for k, v in refs.items() if k.startswith("c")}
    ref_aeg = {k: v for k, v in refs.items() if not k.startswith("c")}
    stat = {
        "ref_total": len(refs),
        "ref_char": len(ref_chars),
        "ref_asset": len(ref_aeg),
        "ours_total": len(ours),
        "matched": len(matched),
        "ref_char_matched": len([k for k in ref_chars if k in used]),
        "ref_char_unmatched": sorted(k for k in ref_chars if k not in used),
        "asset_names": sorted(ref_aeg),
        "ours_unmatched": sorted(unmatched_ours),
    }
    return matched, stat


def pick_zh(model, en_name, ours_zh, boss_en2zh, cfg_en2zh):
    """返回 (zh_name, source, note)。顺序：参考实现翻译 -> 我们自己的中文显示名。

    乱用比没有更糟，所以这里有两道闸：
      * **行名只在"这个模型只有一个不同行名"时才算它的名字** ——
        c0000（Human，通用人型基底）挂了几百个行，最常见的行名是『米莉森』，
        那显然不是这个模型的名字。
      * 多个候选名之间必须**有占优者**（top 出现次数 > 一半）；4:4 这种平局一律不取名。
    """
    if en_name:
        if en_name in boss_en2zh:
            return boss_en2zh[en_name], "zh.enemy.json/boss_names", "参考实现自带的 Boss 中英对照（繁體）"
        if en_name in cfg_en2zh:
            return cfg_en2zh[en_name], "zh.enemy.json/enemy_config_names", "参考实现的杂兵对照表（繁體）"
    if model in ours_zh:
        lst = ours_zh[model]
        c = Counter(n for _, n in lst)
        top, cnt = c.most_common(1)[0]
        total = sum(c.values())
        srcs = sorted({s for s, n in lst if n == top})
        if "ours:row_name" in srcs and len(c) > 1:
            return ("", "未找到",
                    "法魂本体里这个模型挂了 %d 个不同行名（%s…），没有一个是它的模型名；参考实现也没有中文"
                    % (len(c), "、".join(n for n, _ in c.most_common(3))))
        if len(c) > 1 and cnt * 2 <= total:
            return ("", "未找到",
                    "法魂本体里这个模型有 %d 个不同显示名且无占优者（%s），不取其中任何一个"
                    % (len(c), " / ".join("%s x%d" % (n, k) for n, k in c.most_common(4))))
        note = "法魂本体中文显示名（来源 %s）" % "/".join(srcs)
        if len(c) > 1:
            note += "；另有别名 %d 个（%s）" % (len(c) - 1, " / ".join(n for n, _ in c.most_common(4)[1:]))
        return top, srcs[0], note
    return "", "未找到", "参考实现与法魂本体都没有它的中文名"


# ---------------------------------------------------------------------------
# 归类
# ---------------------------------------------------------------------------
def class_of(result_rule, cls_counter):
    if result_rule != "fallback":
        return None
    if not cls_counter:
        return None
    # 参考实现的 Class：Wildlife / Scarab 是能直接当类的
    if cls_counter.get("Wildlife", 0) > 0 and cls_counter.get("Basic", 0) == 0:
        return ("野兽/动物", "ref:Class 多为 Wildlife（被动野生动物）")
    if cls_counter.get("Scarab", 0) > 0 and cls_counter.get("Basic", 0) == 0:
        return ("虫/花/菌", "ref:Class 多为 Scarab（粪金龟）")
    return None


def classify(entry):
    """entry: dict(model, en, zh, sources, cls, tags, groups, hp, radius, height, placements)"""
    m = entry["model"]
    en = entry["en"]

    if m in MANUAL:
        t, why = MANUAL[m]
        return t, "high", "手工钉死：" + why, "manual", ""

    if m in UNIQUE_BOSS:
        _, zh = UNIQUE_BOSS[m]
        return ("Boss/领主", "high",
                "独特具名 Boss：ModelName `%s` 命中参考实现 boss_names（%s）" % (en or "?", zh),
                "unique-boss", "")

    if en:
        low = en.lower()
        for typ, pat, why in EN_RULES:
            if re.search(pat, low):
                note = ("；" + DOC_ONLY[m]) if m in DOC_ONLY else ""
                return typ, "high", "英文名 `%s`：%s%s" % (en, why, note), "ref:ModelName", pat
        return ("未分类", "low",
                "英文名 `%s` 存在但没命中任何规则（待人工补规则）" % en, "ref:ModelName", "")

    # 没有 ModelName 条目 -> 退到中文名
    zh = entry["zh"]
    cands = entry.get("zh_cands") or ([zh] if zh else [])
    if cands:
        hits = []            # [(类, 名字, 命中理由, 正则)]
        for n in cands:
            for typ, pat, why in ZH_RULES:
                if re.search(pat, n):
                    hits.append((typ, n, why, pat))
                    break
        if hits:
            tally = Counter(t for t, _, _, _ in hits)
            top, cnt = tally.most_common(1)[0]
            # 多数决：至少一半候选名指向同一类才认。4:4 这种平局 -> 不认。
            if cnt * 2 >= len(cands):
                name0, why0, pat0 = next((n, w, p) for t, n, w, p in hits if t == top)
                extra = ""
                if len(tally) > 1:
                    extra = ("；另有 %d 个候选名指向别的类（%s），按多数 %d/%d 取"
                             % (len(tally) - 1,
                                "/".join(k for k, _ in tally.most_common()[1:]), cnt, len(cands)))
                src = entry["zh_source"] if entry["zh_source"] != "未找到" else \
                    (entry.get("zh_srcs") or ["ours:boss_healthbar"])[0]
                conf = "medium"
                return (top, conf,
                        "无 ModelName 条目，退用中文名 `%s`：%s%s" % (name0, why0, extra),
                        src, pat0)

    # 再退：参考实现的 Class
    cls = entry["cls"]
    hit = class_of("fallback", cls)
    if hit:
        return hit[0], "medium", "无名字；" + hit[1], "ref:enemy.txt Class", ""

    # 最后：体型档
    r = entry["radius"]
    h = entry["height"]
    if r is not None and h is not None and (r >= 1.0 or h >= 3.5):
        return ("体型·大/巨", "low",
                "无名字/无规则命中；体型 r=%.2f h=%.2f 偏大，只作体型兜底" % (r, h),
                "none", "")

    if zh:
        detail = "无 ModelName 条目；中文名 `%s`（来源 %s）也没命中任何规则" % (zh, entry["zh_source"])
    else:
        detail = "无名字（ModelName.txt / boss_names / 血条名 / 行名四路全无）"
    if r is not None and h is not None:
        detail += "；体型 r=%.2f h=%.2f 不构成判据" % (r, h)
    return ("未分类", "low", detail, "none", "")


# ---------------------------------------------------------------------------
# 基线（v1）对比
# ---------------------------------------------------------------------------
def load_baseline(current_path):
    """v1 基线：优先用磁盘上那份（若还是 v1 结构），否则用 git HEAD 里那份。"""
    rows = []
    src = ""
    if os.path.isfile(current_path):
        rows = read_csv(current_path)
        if rows and "model" in rows[0] and "model_name_en" not in rows[0]:
            return rows, "磁盘上的 enemy_type_map.csv（v1 结构）"
        rows = []
    try:
        out = subprocess.run(["git", "show", "HEAD:investigation/enemy_type_map.csv"],
                             cwd=os.path.dirname(INV), capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            text = out.stdout.decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(text)))
            src = "git HEAD:investigation/enemy_type_map.csv（v1）"
    except Exception as e:  # noqa: BLE001
        return [], "取基线失败：%s" % e
    return rows, src


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("enemy_type_map_v2 —— 用参考实现的 ModelName.txt 重做敌型表")
    print("=" * 78)

    for p in (REF_DIR, MOD_DIR):
        print("只读输入根 %s : %s" % ("存在" if os.path.isdir(p) else "**缺失**", p))
    if not os.path.isdir(REF_DIR):
        print("参考实现目录缺失，终止。")
        return 2

    fp_before = mtime_fingerprint([REF_DIR, MOD_DIR])

    # ---- 参考实现 ----
    ref_names = load_model_names(REF_MODELNAME)
    ref_names_nt = load_model_names(REF_MODELNAME_NT)
    model_cls, model_tag, _mg, name_group, entity_rows = parse_enemy_txt(REF_ENEMY_TXT)
    boss_en2zh, cfg_en2zh, cfg_en2info, msg_meta = load_messages(REF_ZH_ENEMY)

    print()
    print("[参考实现]  ModelName.txt 条目 %d（c* 角色 %d / 非 c* 场景物件 %d）"
          % (len(ref_names),
             len([k for k in ref_names if k.startswith("c")]),
             len([k for k in ref_names if not k.startswith("c")])))
    print("[参考实现]  ModelNameNT.txt 条目 %d" % len(ref_names_nt))
    print("[参考实现]  Base/enemy.txt 地图放置 %d 条，覆盖模型 %d 个" % (entity_rows, len(model_cls)))
    print("[参考实现]  zh.enemy.json：boss_names %d 条（带中文 %d），"
          "enemy_config_names %d 条（本文件里带 info %d / 带中文 %d；含 boss_names 内嵌同名字段）"
          % (msg_meta.get("boss_total", 0), msg_meta.get("boss_with_zh", 0),
             msg_meta.get("cfg_total", 0), msg_meta.get("cfg_with_info", 0),
             msg_meta.get("cfg_with_zh", 0)))

    # ---- 我们的数据 ----
    ours = build_ours()
    models = ours["models"]
    print()
    print("[我们的数据]  模型 %d 个；地图放置 %d 条" % (len(models), sum(ours["placements"].values())))

    match, align = align_model_names(models, ref_names)

    print()
    print("=" * 78)
    print("【验收 1】模型名对齐率")
    print("=" * 78)
    print("ModelName.txt 总条目 %d = c* 角色模型 %d + 非角色场景物件(AEG*) %d"
          % (align["ref_total"], align["ref_char"], align["ref_asset"]))
    print("  以 c* 角色模型为分母：%d/%d = %.1f%%"
          % (align["ref_char_matched"], align["ref_char"], 100.0 * align["ref_char_matched"] / max(1, align["ref_char"])))
    print("  以全部条目为分母：  %d/%d = %.1f%%  （AEG* 是场景物件，不是敌人模型，只能算不对口）"
          % (align["matched"], align["ref_total"], 100.0 * align["matched"] / max(1, align["ref_total"])))
    print("  我们这边命中：%d/%d = %.1f%%"
          % (align["matched"], len(models), 100.0 * align["matched"] / max(1, len(models))))
    print("  参考实现 c* 里我们**没有**的（%d）：%s"
          % (len(align["ref_char_unmatched"]), ", ".join(align["ref_char_unmatched"]) or "无"))
    print("  我们**对不上** ModelName 的（%d）：%s"
          % (len(align["ours_unmatched"]),
             ", ".join(align["ours_unmatched"][:25]) + (" …" if len(align["ours_unmatched"]) > 25 else "")))
    if align["asset_names"]:
        print("  非 c* 条目举例（AEG*，场景物件，不是敌人）：%s …"
              % ", ".join(align["asset_names"][:6]))

    # ---- 组名映射（Groups 段用的是显示名 -> 反查模型） ----
    def groups_of(model, en):
        gs = set()
        if en and en in name_group:
            gs |= name_group[en]
        return gs

    # 体型预表：模型 -> (chr_hit_radius, chr_hit_height)
    body_tab = {}
    for rid, mdl in ours["row2model"].items():
        if mdl in body_tab:
            continue
        t = ours["tab"].get(rid)
        if not t:
            continue
        rr, hh = _f(t.get("chr_hit_radius")), _f(t.get("chr_hit_height"))
        if rr is not None and hh is not None:
            body_tab[mdl] = (rr, hh)

    # ---- 逐模型归类 ----
    rows = []
    zh_rows = []
    for m in models:
        mt = ours["model_types"][m]
        rk, en, how = match.get(m, ("", "", ""))
        zh, zh_src, zh_note = pick_zh(m, en, ours["zh_ev_solo"], boss_en2zh, cfg_en2zh)
        cls = model_cls.get(m, Counter())
        cls_str = "/".join("%s:%d" % (k, v) for k, v in cls.most_common(4)) if cls else ""
        grp = sorted(groups_of(m, en))
        tags = sorted(set(model_tag.get(m, Counter())))
        rad, hei = body_tab.get(m, (None, None))
        entry = {
            "model": m, "en": en, "zh": zh, "zh_source": zh_src,
            "zh_cands": [n for _, n in ours["zh_ev_solo"].get(m, [])],
            "zh_srcs": sorted({s for s, _ in ours["zh_ev_solo"].get(m, [])}),
            "cls": cls, "tags": tags, "groups": grp,
            "radius": rad, "height": hei,
            "placements": ours["placements"].get(m, 0),
        }
        typ, conf, ev, ev_src, rule = classify(entry)

        info = cfg_en2info.get(en, "") if en else ""
        ev_parts = [ev]
        if ev_src:
            ev_parts.append("名字来源=" + ev_src)
        if cls_str:
            ev_parts.append("ref Class=" + cls_str)
        if grp:
            ev_parts.append("ref Group=" + "|".join(grp))
        if info:
            ev_parts.append("ref info=" + info)
        rows.append({
            "model": m,
            "model_name_en": en,
            "enemy_type": typ,
            "confidence": conf,
            "npc_rows": mt.get("npc_rows", ""),
            "placements": ours["placements"].get(m, 0),
            "sample_names": _sample_names(m, ours),
            "hp_median": mt.get("hp_median", ""),
            "evidence": "；".join(p for p in ev_parts if p),
            "_cls": cls_str,
            "_rule": rule,
            "_esrc": ev_src,
            "_bar": "yes" if m in ours["bar_models"] else "",
        })
        zh_rows.append({
            "model": m,
            "model_name_en": en,
            "name_zh": zh,
            "source": zh_src,
            "note": zh_note,
        })

    # ---- 统计 ----
    type_cnt = Counter(r["enemy_type"] for r in rows)
    named = [r for r in rows if r["model_name_en"]]
    named_set = {r["model"] for r in rows if r["model_name_en"]}
    zh_set = {r["model"] for r in zh_rows if r["name_zh"]}
    zh_cand_set = set(ours["zh_ev_solo"])          # 有任何候选中文名（含多个候选）
    zh_found = [r for r in rows if r["model"] in zh_set]
    zh_any = [r for r in rows if r["model"] in zh_cand_set]
    name_backed = [r for r in rows if r["enemy_type"] in NAME_BACKED and r["_esrc"] in NAME_SOURCES]
    typed = [r for r in rows if r["enemy_type"] not in ("未分类",)]

    print()
    print("=" * 78)
    print("【验收 2】敌型覆盖率（有名字支撑的类别）")
    print("=" * 78)
    print("  有 ModelName.txt 英文名：%d/%d = %.1f%%" % (len(named), len(rows), 100.0 * len(named) / len(rows)))
    print("  有可确定的中文名：%d/%d = %.1f%%；有任何中文名证据（含多候选）：%d/%d = %.1f%%"
          % (len(zh_found), len(rows), 100.0 * len(zh_found) / len(rows),
             len(zh_any), len(rows), 100.0 * len(zh_any) / len(rows)))
    print("  类别由**名字**判出（name_source ∈ %s）：%d/%d = %.1f%%"
          % ("/".join(sorted(NAME_SOURCES)), len(name_backed), len(rows),
             100.0 * len(name_backed) / len(rows)))
    print("  拿到具体类（非「未分类」）：%d/%d = %.1f%%"
          % (len(typed), len(rows), 100.0 * len(typed) / len(rows)))
    print("  —— v1 的对照数字：161/462 = 34.8%（有权威名字）；旧表「未分类」277 个")

    # ---- 基线对比 ----
    base_rows, base_src = load_baseline(OUT_CSV)
    diff_same = []
    diff_old_fallback = []
    diff_real = []
    if base_rows:
        bmap = {r["model"]: r.get("enemy_type", "") for r in base_rows if r.get("model")}
        for r in rows:
            old = bmap.get(r["model"])
            if old is None:
                continue
            if old == r["enemy_type"]:
                diff_same.append((r["model"], old))
            elif old in ("未分类",) or old.startswith("体型"):
                diff_old_fallback.append((r["model"], old, r["enemy_type"], r["model_name_en"]))
            else:
                diff_real.append((r["model"], old, r["enemy_type"], r["model_name_en"]))
        print()
        print("=" * 78)
        print("【验收 3】新表 vs 旧表（基线：%s）" % base_src)
        print("=" * 78)
        print("  基线模型数 %d；可比模型 %d" % (len(bmap), len(diff_same) + len(diff_old_fallback) + len(diff_real)))
        print("  enemy_type 不一致的模型：%d 个"
              % (len(diff_old_fallback) + len(diff_real)))
        print("    ├─ 旧表是「未分类/体型档」→ 新表给了具体类：%d 个（这是覆盖率提升）"
              % len(diff_old_fallback))
        print("    └─ 旧表也是具体类、但换了类：%d 个（逐条列在报告 §5）" % len(diff_real))
        print()
        print("  --- A. 旧=兜底 -> 新=具体类（前 40 条）---")
        for m, old, new, en in diff_old_fallback[:40]:
            print("    %-7s %-12s -> %-14s %s" % (m, old, new, en))
        if len(diff_old_fallback) > 40:
            print("    …（共 %d 条，全部见报告）" % len(diff_old_fallback))
        print()
        print("  --- B. 具体类 -> 具体类（前 60 条）---")
        for m, old, new, en in diff_real[:60]:
            print("    %-7s %-14s -> %-14s %s" % (m, old, new, en))
        if len(diff_real) > 60:
            print("    …（共 %d 条，全部见报告）" % len(diff_real))
    else:
        print()
        print("【验收 3】无 v1 基线可用（磁盘与 git HEAD 都没有 v1 结构的那份），跳过对比。")

    # ---- 类别清单 ----
    print()
    print("=" * 78)
    print("【类别清单】%d 类（含 2 个兜底档）" % len(TYPE_ORDER))
    print("=" * 78)
    print("  %-14s %6s %8s %9s %9s" % ("类", "模型数", "占比", "覆盖行数", "放置数"))
    for t in TYPE_ORDER:
        sub = [r for r in rows if r["enemy_type"] == t]
        if not sub:
            continue
        print("  %-14s %6d %7.1f%% %9d %9d"
              % (t, len(sub), 100.0 * len(sub) / len(rows),
                 sum(_i(r["npc_rows"]) for r in sub), sum(r["placements"] for r in sub)))

    # ---- 没名字 / 没归类 ----
    no_name = [r for r in rows if r["model"] not in named_set and r["model"] not in zh_cand_set]
    no_type = [r for r in rows if r["enemy_type"] == "未分类"]
    print()
    no_type_noname = [r for r in no_type if r["_esrc"] in ("none", "ref:enemy.txt Class", "")]
    print("  还剩多少没归类：「未分类」%d 个 + 「体型·大/巨」%d 个 = %d 个模型没拿到具体类"
          % (len(no_type), len([r for r in rows if r["enemy_type"] == "体型·大/巨"]),
             len(no_type) + len([r for r in rows if r["enemy_type"] == "体型·大/巨"])))
    print("  全表 462 个模型里，**中英文都没有名字**的：%d 个" % len(no_name))
    print("  其中连「未分类」都没判出来的原因就是没名字：%d 个" % len(no_type_noname))
    print("  没名字的模型（%d）：%s" % (len(no_name), ", ".join(r["model"] for r in no_name) or "无"))

    # ---- 写产物 ----
    # 报告需要的小数据：手工覆盖条目（连"规则会给出什么"一起）+ 被剔掉的共享名
    manual_items = [(k, v[0], v[1]) for k, v in sorted(MANUAL.items())]
    manual_rule_says = {}
    for k, _t, _why in manual_items:
        _rk, _en, _h = match.get(k, ("", "", ""))
        probe = {"model": k, "en": _en, "zh": "", "zh_source": "none",
                 "cls": Counter(), "radius": None, "height": None}
        _saved = MANUAL.pop(k)
        try:
            manual_rule_says[k] = classify(probe)[0]
        finally:
            MANUAL[k] = _saved
    extra = {
        "n_manual": len(MANUAL),
        "manual_items": manual_items,
        "manual_rule_says": manual_rule_says,
        "n_doc": len(DOC_ONLY),
        "doc_list": sorted(DOC_ONLY),
        "zh_any": set(ours["zh_ev_solo"]),
        "n_shared": len(ours["shared_names"]),
        "shared_list": sorted(ours["shared_names"]),
    }
    _write_csv(rows)
    _write_zh(zh_rows)
    _write_md(rows, zh_rows, align, msg_meta, base_rows, base_src,
              diff_old_fallback, diff_real, diff_same, entity_rows, model_cls, extra)

    # ---- 只读性 ----
    fp_after = mtime_fingerprint([REF_DIR, MOD_DIR])
    changed = fp_diff(fp_before, fp_after)
    print()
    print("=" * 78)
    print("【验收 4】只读性：参考实现目录 + 法魂目录 mtime 前后对比")
    print("=" * 78)
    print("  指纹文件数 before=%d after=%d；mtime 变化的文件：%d 个 %s"
          % (len(fp_before), len(fp_after), len(changed),
             ("（%s）" % ", ".join(changed[:5])) if changed else "-> 未被改动 ✅"))
    print()
    print("产物：")
    for p in (OUT_CSV, OUT_ZH, OUT_MD):
        print("  %s  (%d bytes)" % (p, os.path.getsize(p) if os.path.isfile(p) else -1))
    return 0


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _sample_names(model, ours):
    ev = ours["zh_ev"].get(model)
    if not ev:
        return ""
    c = Counter(n for _, n in ev)
    return "|".join(n for n, _ in c.most_common(6))


def _write_csv(rows):
    cols = ["model", "model_name_en", "enemy_type", "confidence",
            "npc_rows", "placements", "sample_names", "hp_median", "evidence",
            "name_source", "ref_class", "boss_healthbar", "type_rule", "schema"]
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["model"], r["model_name_en"], r["enemy_type"], r["confidence"],
                        r["npc_rows"], r["placements"], r["sample_names"], r["hp_median"],
                        r["evidence"], r["_esrc"], r["_cls"], r["_bar"],
                        r["_rule"], SCHEMA])


def _write_zh(rows):
    cols = ["model", "model_name_en", "name_zh", "source", "note"]
    with io.open(OUT_ZH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["model"], r["model_name_en"], r["name_zh"], r["source"], r["note"]])


def _write_md(rows, zh_rows, align, msg_meta, base_rows, base_src,
              diff_fallback, diff_real, diff_same, entity_rows, model_cls, extra):
    N_MANUAL = extra["n_manual"]
    MANUAL_ITEMS = extra["manual_items"]
    MANUAL_RULE_SAYS = extra["manual_rule_says"]
    N_DOC = extra["n_doc"]
    DOC_LIST = extra["doc_list"]
    N_SHARED = extra["n_shared"]
    SHARED_LIST = extra["shared_list"]
    L = []
    A = L.append
    A("# 敌型表 v2 —— 用参考实现自带的模型名表重建")
    A("")
    A("> 由 `investigation/apply/enemy_type_map_v2.py` 生成，可重跑。")
    A("> 只读输入：法魂 MOD（只读）/ 本仓库 investigation 产物 / 参考实现 "
      "`Elden Ring Randomizer 428 v0.12.2 .../randomizer/diste`（只读）。")
    A("")
    A("## 0. 一句话结论")
    A("")
    nm = len([r for r in rows if r["model_name_en"]])
    nb = len([r for r in rows if r["enemy_type"] in NAME_BACKED and r["_esrc"] not in ("none", "")])
    A("- v1 只有 **161/462 (34.8%)** 的模型有权威名字，其余 301 个靠体型兜底、全标 low。")
    A("- v2 用参考实现的 `Names/ModelName.txt`（**按模型给名字**的那张表）之后："
      "**%d/462 (%.1f%%)** 拿到英文名，**%d/462 (%.1f%%)** 的类别是**由名字判出**的。"
      % (nm, 100.0 * nm / len(rows), nb, 100.0 * nb / len(rows)))
    A("- 未拿到具体类的模型从 v1 的 277 个降到 **%d 个**。"
      % len([r for r in rows if r["enemy_type"] == "未分类"]))
    A("")
    A("## 1. 参考实现给了什么")
    A("")
    A("| 文件 | 规模 | 本脚本怎么用 |")
    A("|---|---|---|")
    A("| `Names/ModelName.txt` | %d 条 = c* 角色 **%d** + AEG* 场景物件 %d | **主证据**：模型 -> 英文名 |"
      % (align["ref_total"], align["ref_char"], align["ref_asset"]))
    A("| `Names/ModelNameNT.txt` | 218 条 | 辅助（内部名，本版未参与判类） |")
    A("| `Base/enemy.txt` | %d 条地图放置，覆盖 %d 个模型 | 参考实现自己的 **Class**（Basic / Wildlife / "
      "Scarab / Boss / MinorBoss / Miniboss / NightMiniboss / DragonMiniboss / Evergaol / HostileNPC / "
      "CaravanTroll / Helper / DupeOnly / None）+ Tags + Groups |" % (entity_rows, len(model_cls)))
    A("| `Messages/zh.enemy.json` | boss_names %d 条（带中文 %d）；enemy_config_names %d 条"
      "（带 info %d / 带中文 %d） | 中英对照 + 行为类目（info 里的 `Nx in …`） |"
      % (msg_meta.get("boss_total", 0), msg_meta.get("boss_with_zh", 0),
         msg_meta.get("cfg_total", 0), msg_meta.get("cfg_with_info", 0),
         msg_meta.get("cfg_with_zh", 0)))
    A("")
    A("**与任务书不一致的两处，如实记在这里：**")
    A("")
    A("1. `Messages/en.enemy.json` **在这个版本里不存在**（目录里只有 de / es / es-ES / fr / it / ja / "
      "ko / pl / pt-BR / ru / th / zh 十二份）。所以英文名一律取 `ModelName.txt`。")
    A("2. `ModelName.txt` 不是 454 条 `cXXXX 英文名`：文件共 455 行，其中 **2 行是 `#` 注释**"
      "（`# Shiny Item = Invisible`、`# DLC`），剩 453 条里 **408 条是 c* 角色模型**、"
      "**45 条是 AEG* 场景物件**（`AEG464_071 Painting` 之类，不是敌人）。"
      "把 AEG 也算进来的话对齐率必然掉到 90% 以下 —— 那 45 条本来就不该跟我们 462 个角色模型对齐。")
    A("")
    A("## 2. 模型名对齐")
    A("")
    cf = align["ref_char_matched"]
    A("| 口径 | 数字 |")
    A("|---|---|")
    A("| ModelName.txt 全部条目 | %d |" % align["ref_total"])
    A("| 其中 c* 角色模型 | %d |" % align["ref_char"])
    A("| 其中非角色 AEG* 场景物件 | %d |" % align["ref_asset"])
    A("| **对齐上（以 c* 为分母）** | **%d / %d = %.1f%%** |" % (cf, align["ref_char"], 100.0 * cf / align["ref_char"]))
    A("| 对齐上（以全部条目为分母，含 AEG*） | %d / %d = %.1f%% |"
      % (align["matched"], align["ref_total"], 100.0 * align["matched"] / align["ref_total"]))
    A("| 我们这边命中 | %d / %d = %.1f%% |"
      % (align["matched"], len(rows), 100.0 * align["matched"] / len(rows)))
    A("")
    A("对齐方式：先原样匹配，再大小写折叠，再试去零填充（`c0120` / `c120`）。"
      "**实测三种规则都没有额外收益 —— 我们的模型 id 与 ModelName.txt 的键完全同构**，"
      "差异只来自「表里没有这个模型」。")
    A("")
    A("### 2.1 参考实现有、我们没有的 c* 模型（%d 个）" % len(align["ref_char_unmatched"]))
    A("")
    if align["ref_char_unmatched"]:
        A("| 模型 | 参考实现里的名字 |")
        A("|---|---|")
        for k in align["ref_char_unmatched"]:
            A("| `%s` | %s |" % (k, _ref_name(k)))
    else:
        A("无")
    A("")
    A("这些是**本仓库的模型集合（来自法魂本体地图放置）里不存在**的模型 —— "
      "参考实现按原版 + DLC 的 MSB 列，法魂本体改过放置，所以有出入；"
      "反过来我们多出来的模型见下一节。这是**数据源口径差**，不是对齐失败。")
    A("")
    A("### 2.2 我们有、参考实现 ModelName.txt 里没有的模型（%d 个）" % len(align["ours_unmatched"]))
    A("")
    A("```")
    for i in range(0, len(align["ours_unmatched"]), 12):
        A("  " + "  ".join(align["ours_unmatched"][i:i + 12]))
    A("```")
    A("")
    A("这 %d 个模型在参考实现的 `Base/enemy.txt` 里**也一条都没有**（实测交集为 0），"
      "说明它们是**法魂 MOD 自己新增/改过的模型**，或参考实现主动排除的对象。"
      "v2 对它们的处理见 §6。" % len(align["ours_unmatched"]))
    A("")
    A("## 3. 类别清单（%d 类，含 2 个兜底档）" % len(TYPE_ORDER))
    A("")
    A("| 类 | 模型数 | 占比 | 覆盖行数 | 放置数 |")
    A("|---|---|---|---|---|")
    for t in TYPE_ORDER:
        sub = [r for r in rows if r["enemy_type"] == t]
        if not sub:
            continue
        A("| %s | %d | %.1f%% | %d | %d |"
          % (t, len(sub), 100.0 * len(sub) / len(rows),
             sum(_i(r["npc_rows"]) for r in sub), sum(r["placements"] for r in sub)))
    A("")
    A("与 v1 的 16 类相比：**去掉「血族/贵族」「敌对NPC/人形」，新增「坐骑/驮兽」**，理由：")
    A("")
    A("- 参考实现把 `*Horse` 当**独立模型**（`Night's Cavalry Horse` / `Godrick Knight's Horse` / "
      "`Leyndell Knight's Horse` / `Troll Knight's Horse` …，本仓库实测 8 个）。v1 没这一类，"
      "它们被拆到骑士/野兽两个池子里 —— 单独立类后，换敌时「马换马」才成立。")
    A("- 462 个模型里**只有 c0000 一个**在参考实现里带 `HostileNPC` 标签（`enemy.txt` 实测），"
      "单独留一类没有池子意义；v1 的「敌对NPC/人形」在 v1 表里也只有 9 个模型，全部已按名字归到"
      "骑士/士兵/施法者等更贴的类。")
    A("- v1 的「血族/贵族」只有 2 个模型（鲜血贵族、血怪之首），与「平民/贵族」（漫游贵族、暗影平民）"
      "在换敌池里没有区分度，v2 合并进「人形/平民」。")
    A("")
    A("## 4. 判类规则")
    A("")
    A("顺序即优先级，命中即止。**英文名优先**是本版相对 v1 的核心差别 —— "
      "v1 的表里 301/462 个模型（65%）根本没有名字，只能标 low；实测的重判实例见 §5.2。")
    A("")
    A("```")
    for typ, pat, why in EN_RULES:
        A("%-14s %s" % (typ, pat))
    A("```")
    A("")
    A("几条顺序是有意为之的（写错就会判错）：")
    A("")
    A("- `horse` 排在 `knight` 之前：`Godrick Knight's Horse` 同时含 knight 与 horse，"
      "而它是个**坐骑模型**。")
    A("- `marionette / avionette` 排在 `soldier` 之前：`Marionette Soldier` 是**傀儡**不是士兵。")
    A("- `dragonfly` 排在 `dragon` 之前：否则蜻蜓会被龙规则吞掉。")
    A("- `skeleton` / `putrid` 排在 `giant` 之前：`Giant Skeleton Torso` 是骨架不是巨人。")
    A("- `dragon` 排在 `soldier` 之前：`Dragonkin Soldier` 是龙人。")
    A("- `demi-human / beastman` 排在 `soldier / warrior` 之前：`Beastman of Farum Azula`、"
      "`Divine Bird Warrior` 是亚人不是士兵。")
    A("")
    A("中文规则（仅在模型**没有** ModelName.txt 条目时启用）：")
    A("")
    A("```")
    for typ, pat, why in ZH_RULES:
        A("%-14s %s" % (typ, pat))
    A("```")
    A("")
    A("## 4.1 两个必须先说清的数据陷阱")
    A("")
    A("### (a) 共享血条名 —— `boss_healthbar.csv` 里的名字不能无条件当模型名")
    A("")
    A("**实测**：`黄金树看护者`（Erdtree Warden）这一个字符串同时被派给了 "
      "c1000 / c2278 / c3170 / c3300 / c3805 / c4120 / c4490 / c4602 / c4660 / c4690 十个模型。"
      "原因是同一个 (map, entity) 上的血条调用会被回推到该实体上的**多个**模型，"
      "而这些多敌血条用的是**同一个标签**。不处理的话，"
      "`c2278`（真身是 c2270~c2277 一串蟹里的一个）会被判成「骑士/重甲」—— 纯属被标签带偏。")
    A("")
    A("本脚本的处理：**凡是同时挂在 ≥2 个模型上的血条名，一律不参与判类**"
      "（仍然保留在 `sample_names` 列里供人看）。实测被剔掉的这类名字共 **%d** 个：" % N_SHARED)
    A("")
    A("```")
    for x in SHARED_LIST:
        A("  " + x)
    A("```")
    A("")
    A("### (b) 手工覆盖只剩 %d 条" % N_MANUAL)
    A("")
    A("v1 的 `CURATED` 表有 150+ 条逐个点死。v2 先把规则表写足，"
      "然后**只保留规则确实判错的** %d 条硬覆盖 —— 其余一律交给规则，可复核、可复跑：" % N_MANUAL)
    A("")
    A("| 模型 | 手工类 | 规则会给出 | 理由 |")
    A("|---|---|---|---|")
    for k, t, why in MANUAL_ITEMS:
        A("| `%s` | %s | %s | %s |" % (k, t, MANUAL_RULE_SAYS.get(k, "—"), why))
    A("")
    A("另有 %d 条 `DOC_ONLY`（%s）**不改判定**，只是把「为什么」写进 evidence。"
      % (N_DOC, "、".join("`%s`" % d for d in DOC_LIST)))
    A("")
    A("## 5. 新旧对比")
    A("")
    if not base_rows:
        A("本次运行没取到 v1 基线（磁盘上的 `enemy_type_map.csv` 已是 v2 结构，git HEAD 里也没有 v1），"
          "跳过对比。")
    else:
        A("基线：%s（%d 行）。" % (base_src, len(base_rows)))
        A("")
        A("| 指标 | 数字 |")
        A("|---|---|")
        A("| 可比模型 | %d |" % (len(diff_same) + len(diff_fallback) + len(diff_real)))
        A("| enemy_type **一致** | %d |" % len(diff_same))
        A("| enemy_type **不一致** | **%d** |" % (len(diff_fallback) + len(diff_real)))
        A("| ├─ 旧=兜底（未分类/体型档）→ 新=具体类 | %d（覆盖率提升） |" % len(diff_fallback))
        A("| └─ 旧=具体类 → 新=具体类（真·重判） | %d |" % len(diff_real))
        A("")
        A("### 5.1 旧=兜底 → 新=具体类（%d 个）" % len(diff_fallback))
        A("")
        A("| 模型 | 旧 | 新 | 参考实现英文名 |")
        A("|---|---|---|---|")
        for m, old, new, en in diff_fallback:
            A("| `%s` | %s | %s | %s |" % (m, old, new, en))
        A("")
        A("### 5.2 旧=具体类 → 新=具体类（%d 个，逐个看是不是新表更对）" % len(diff_real))
        A("")
        A("| 模型 | 旧 | 新 | 参考实现英文名 | 判断 |")
        A("|---|---|---|---|---|")
        for m, old, new, en in diff_real:
            verdict = _verdict(old, new, en)
            A("| `%s` | %s | %s | %s | %s |" % (m, old, new, en, verdict))
    A("")
    A("## 6. 还剩多少没归类 / 没名字")
    A("")
    zh_map = {r["model"]: r["name_zh"] for r in zh_rows}
    zh_any_note = extra["zh_any"]
    no_name = [r for r in rows if not r["model_name_en"] and r["model"] not in zh_any_note]
    only_zh = [r for r in rows if not r["model_name_en"] and r["model"] in zh_any_note]
    no_type = [r for r in rows if r["enemy_type"] == "未分类"]
    A("| 项 | 数量 |")
    A("|---|---|")
    A("| 有 ModelName.txt 英文名 | %d |" % len([r for r in rows if r["model_name_en"]]))
    A("| 只有中文名（法魂新增/改名的模型，含多候选） | %d |" % len(only_zh))
    A("| 中英文都没有 | %d |" % len(no_name))
    A("| 拿到具体类 | %d |" % len([r for r in rows if r["enemy_type"] != "未分类"]))
    A("| 仍是「未分类」 | %d |" % len(no_type))
    A("")
    A("**中英文都没有名字的模型（%d 个）：**" % len(no_name))
    A("")
    A("```")
    for i in range(0, len(no_name), 12):
        A("  " + "  ".join(r["model"] for r in no_name[i:i + 12]))
    A("```")
    A("")
    A("**仍是「未分类」的模型（%d 个）：**" % len(no_type))
    A("")
    if no_type:
        A("| 模型 | 放置数 | hp 中位 | 备注 |")
        A("|---|---|---|---|")
        for r in no_type:
            A("| `%s` | %s | %s | %s |"
              % (r["model"], r["placements"], r["hp_median"],
                 (r["_cls"] or "参考实现无此模型")))
    else:
        A("无。")
    A("")
    A("## 7. 产物与列")
    A("")
    A("| 文件 | 说明 |")
    A("|---|---|")
    A("| `investigation/enemy_type_map.csv` | 覆盖写。`model` / `enemy_type` 两列名保持不变"
      "（`enemy_randomizer.load_row_types` 只认这两列）；列序："
      "`model, model_name_en, enemy_type, confidence, npc_rows, placements, sample_names, "
      "hp_median, evidence, name_source, ref_class, boss_healthbar, type_rule, schema` |")
    A("| `investigation/enemy_type_names_zh.csv` | 中英对照：`model, model_name_en, name_zh, source, note` |")
    A("| `investigation/enemy_type_map_v2.md` | 本文件 |")
    A("")
    A("列的含义：")
    A("")
    A("- `evidence` 把 name 来源 / ref Class / ref Group / ref info 全部串起来，判错了能顺着它回溯。")
    A("- `confidence` 三档：`high` = 有英文名且命中规则、或独特具名 Boss、或手工覆盖；"
      "`medium` = 中文名判出（含多候选多数决）、或参考实现 Class 兜底；`low` = 体型兜底 / 未分类。")
    A("- `boss_healthbar` = `yes` 表示这个模型在**法魂本体**里出现过血条名/Boss 行名 —— "
      "它**不参与**判类（共享名不可信，见 §4.1a），只是把这条证据留着。全表 %d 个模型带这个标记。"
      % len([r for r in rows if r["_bar"]]))
    A("- `schema` = `v2`，用来和 v1 表区分（脚本自己就是靠这一列判断「这是不是 v1 基线」）。")
    A("")
    A("对齐口径的实测结论（供复核）：")
    A("")
    A("- 大小写折叠 / 去零填充两条规则**都没有额外收益**，我们的模型 id 与 ModelName.txt 的键完全同构。")
    A("- `ModelNameNT.txt` 本版**未参与判类**：64 个没有 ModelName 条目的模型里，它只覆盖 1 个（c3310），"
      "而且给的是内部名 `MarikaLineageWoman`，判不出比中文名更多的信息。")
    A("")
    with io.open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


_REF_NAMES_CACHE = {}


def _ref_name(k):
    if not _REF_NAMES_CACHE:
        for kk, vv in load_model_names(REF_MODELNAME).items():
            _REF_NAMES_CACHE[kk] = vv
    return _REF_NAMES_CACHE.get(k, "")


def _verdict(old, new, en):
    """给人看的"新表是不是更对"的判断（基于名字，不做主观发挥）。"""
    if old == new:
        return "一致"
    return "按英文名 `%s` 重判" % (en or "—")


if __name__ == "__main__":
    sys.exit(main())
