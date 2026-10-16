# -*- coding: utf-8 -*-
"""Boss 血条名单 · 缺口分析（只读，打印 Markdown）

回答三件事：
1. **追忆 ↔ 血条 Boss 对照表**：32 个追忆（本体 22 + DLC 10）逐个对上 `boss_healthbar.csv`
   里的哪一行；对不上的把原因写出来。
   追忆的名字与 Boss 名**经常不是同一个词**（官方如此）：
     影轮草的追忆 → 幽影树的化身（Scadutree Avatar，掉「影轮草大花」）
     假龙之王的追忆 → “伪龙王”达格拉夫
     神嗣的追忆 → 受封印神祇之嗣
   所以匹配不能只靠字面：以 `GoodsCaption` 的正文为准（正文第一句就是「受…雕琢的〈Boss名〉的追忆。」）。

2. **v1（旧名单）到底错/漏在哪**：拿 v1 的 CSV 与 v2 对比，逐类给出证据。

3. **剩下的缺口**：名字表里有、但没有任何血条调用引用的 Boss 名（`--gaps`）。

用法：
    python boss_names_gaps.py            # 追忆对照表 + 汇总
    python boss_names_gaps.py --gaps      # 额外打印"没被任何血条引用"的名字
    python boss_names_gaps.py --diff      # 额外打印 v1/v2 逐行差异
只读：不写任何文件（Markdown 打到 stdout）。
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boss_healthbar as BH          # noqa  复用修正后的 FMG 解析 + 事件扫描
import enemy_names as EN             # noqa

INV = os.path.abspath(os.path.join(HERE, ".."))
CSV_V2 = os.path.join(INV, "boss_healthbar.csv")

# v1 的备份（跑 v2 之前我把它存到了这里；没有就跳过 diff）
CSV_V1_CANDIDATES = [
    os.path.join(os.environ.get("TEMP", ""), "bossgap", "before", "boss_healthbar_v1.csv"),
]

# 官方/法魂的"追忆名 ≠ Boss 名"对照（字面匹配不上的才需要这张表）
ALIAS = {
    "影轮草": "幽影树的化身",          # Scadutree Avatar：追忆/武器按"影轮草"，Boss 名按"化身"
    "假龙之王": "“伪龙王”达格拉夫",
    "神嗣": "受封印神祇之嗣",
    "艾尔登": "艾尔登之兽",
    "女族长": "神皮女族长",
    "死龙": "“死龙”弗尔桑克斯",
    "龙王": "“龙王”普拉顿桑克斯",
    "碎星": "“碎星”拉塔恩",
    "接肢": "“接肢”葛瑞克",
    "恶兆王": "“恶兆王”蒙葛特",
    "腐败女神": "“腐败女神”玛莲妮亚",
    "鲜血君王": "“鲜血君王”蒙格",
    "亵渎君王": "“亵渎君王”拉卡德",
    "满月女王": "“满月女王”蕾娜菈",
    "黑暗弃子": "“黑暗弃子”艾丝缇",
    "火焰巨人": "火焰巨人",
    "祖灵之王": "祖灵之王",
    "荷莱·露": "战士荷莱·露",
    "山猪骑士": "老将盖乌斯",
    "穿刺者": "“穿刺者”梅瑟莫",
    "双月骑士": "“双月骑士”蕾菈娜",
    "花蕾圣女": "“花蕾圣女”萝蜜娜",
    "舞狮": "神兽舞狮",
    "神祇与王": "“米凯拉的王”拉塔恩",
    "癫火之王": "“癫火之王”米德拉",
    "指头之母": "“指头之母”梅蒂尔",
    "融泥": "融泥骑士",
    "背叛熔炉者": "“背叛熔炉者”斯卡德",
    "剥尸王": "“剥尸王”迪鲁",
    "冰之守卫": "“冰之守卫”艾纳尔",
    "塑灵者": "“塑灵者”凯玛",
    "黑剑": "“黑剑”玛利喀斯",
}

REM_NAMES = ("GoodsName", "GoodsName_dlc01")
REM_CAPS = ("GoodsCaption", "GoodsCaption_dlc01")


def norm(s):
    return re.sub(r"[“”\"\s]", "", s or "")


def load_rows(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def boss_from_caption(cap):
    """`GoodsCaption` 正文 → Boss 名。

    格式固定为「受〈黄金树/幽影树〉雕琢的\\n〈Boss名〉的追忆。\\n\\n…」；
    少数条目第一段只有"受…雕琢。"（比如 2967），那就退回用追忆名。
    """
    if not cap:
        return ""
    head = cap.split("的追忆。")[0]
    if len(head) == len(cap):                    # 没有「的追忆。」
        return ""
    lines = [x.strip() for x in head.replace("\r", "").split("\n") if x.strip()]
    if not lines:
        return ""
    name = lines[-1]
    name = re.sub(r"^(受[^，。]*?雕琢的|获[^，。]*?的)", "", name).strip()
    if name.startswith("的追忆"):
        name = lines[-2] if len(lines) > 1 else ""
    return name


def main():
    gaps = "--gaps" in sys.argv
    want_diff = "--diff" in sys.argv

    tables = BH.load_fmg_tables(BH.NAME_STEMS_PRIMARY + BH.NAME_STEMS_FALLBACK
                                + REM_NAMES + REM_CAPS)
    rows = load_rows(CSV_V2)
    byname = collections.defaultdict(list)
    for r in rows:
        byname[norm(r["name"])].append(r)
    allnames = list({norm(r["name"]) for r in rows if r["name"]})

    print("# 追忆 ↔ 血条 Boss 对照表\n")
    print("追忆名取自 `GoodsName*`，Boss 名取自 `GoodsCaption*` 正文（修正解析后每个 id 有自己的正文），")
    print("再回 `boss_healthbar.csv` 找那一行。\n")
    print("| # | 追忆 id | 追忆名 | 正文里的 Boss 名 | 名单里的 Boss 名 | 地图 / 实体 | 匹配方式 |")
    print("|---|---|---|---|---|---|---|")

    stats = collections.Counter()
    rems = []
    for stem, lo, hi in (("GoodsName", 2950, 2971), ("GoodsName_dlc01", 2002900, 2002910)):
        nm = tables.get(stem, {})
        cap = tables.get(stem.replace("GoodsName", "GoodsCaption"), {})
        for i in range(lo, hi + 1):
            if not nm.get(i):
                stats["空槽（无追忆物品）"] += 1
                continue
            rems.append((stem, i, nm[i], boss_from_caption(cap.get(i, ""))))

    def pick(cand):
        """名字候选 → (CSV 行, 匹配方式)。

        **只做同名与别名表两种精确匹配**：早先版本用"包含关系"兜底，
        结果把 `指头之母的追忆` 错配到“指头之母”尤弥尔（真正的梅蒂尔那一行根本不存在）。
        宁可报"未找到"，也不给一个看起来对、其实错的匹配。
        """
        c = norm(cand)
        if not c:
            return None, ""
        if c in byname:
            return byname[c][0], "同名"
        a = norm(ALIAS.get(cand, ""))
        if a and a in byname:
            return byname[a][0], "别名表"
        return None, ""

    for n, (stem, i, rname, boss) in enumerate(rems, 1):
        hit, how = None, ""
        short = rname.replace("的追忆", "")
        for cand in (boss, short):
            hit, how = pick(cand)
            if hit:
                break
        era = "本体" if stem == "GoodsName" else "DLC"
        if hit:
            stats["对上"] += 1
            print("| %d | %s:%d | %s | %s | %s | %s / %s | %s |"
                  % (n, era, i, rname, boss or "—",
                     hit["name"], hit["map"], hit["entity"], how))
        else:
            stats["对不上"] += 1
            print("| %d | %s:%d | %s | %s | **未找到** | — | 未匹配 |"
                  % (n, era, i, rname, boss or "—"))

    print("\n## 汇总\n")
    print("- 追忆物品 **%d** 个（本体 %d + DLC %d）"
          % (len(rems),
             sum(1 for s, _i, _a, _b in rems if s == "GoodsName"),
             sum(1 for s, _i, _a, _b in rems if s != "GoodsName")))
    print("- 能在血条名单里找到对应 Boss 的：**%d**；对不上 **%d**"
          % (stats["对上"], stats["对不上"]))
    if stats["空槽（无追忆物品）"]:
        print("- 号段里还有 %d 个空槽（id 存在、物品名是空串）" % stats["空槽（无追忆物品）"])

    if want_diff:
        v1 = None
        for c in CSV_V1_CANDIDATES:
            if os.path.isfile(c):
                v1 = load_rows(c)
                break
        print("\n## v1 → v2 差异\n")
        if v1 is None:
            print("（找不到 v1 备份，跳过）")
        else:
            k1 = {(r["map"], r["entity"]) for r in v1}
            k2 = {(r["map"], r["entity"]) for r in rows}
            n1 = {int(r["name_id"]): r["name"] for r in v1 if r["name_id"].isdigit() and r["name"]}
            n2 = {int(r["name_id"]): r["name"] for r in rows if r["name_id"].isdigit() and r["name"]}
            print("- v1 %d 行 / %d 个 地图+实体 键 ｜ v2 %d 行 / %d 个键"
                  % (len(v1), len(k1), len(rows), len(k2)))
            print("- 新增（v2 有 v1 没有）**%d** 个 地图+实体" % len(k2 - k1))
            print("- v1 有 v2 没有 **%d** 个（多为被注释的无效调用被合并/改名）" % len(k1 - k2))
            changed = [(i, n1[i], n2[i]) for i in sorted(set(n1) & set(n2)) if n1[i] != n2[i]]
            print("- **同一个名字 id、v1 名字是错的：%d 个**" % len(changed))
            if changed:
                print("\n| name_id | v1 名字（错） | v2 名字（修正后） |")
                print("|---|---|---|")
                for i, a, b in changed:
                    print("| %d | %s | %s |" % (i, a, b))
            only2 = sorted(set(n2) - set(n1))
            print("\n- v2 新覆盖的名字 id：%d 个" % len(only2))
            if only2:
                print("\n| name_id | v2 名字 |")
                print("|---|---|")
                for i in only2[:80]:
                    print("| %d | %s |" % (i, n2[i]))

    if gaps:
        used = {int(r["name_id"]) for r in rows if r["name_id"].isdigit()}
        allids = set()
        for stem in BH.NAME_STEMS_PRIMARY:
            allids |= {i for i in tables.get(stem, {}) if i >= 900000000}
        resolve = BH.make_name_resolver(tables)
        heads = []
        for i in sorted(allids):
            txt = resolve(i)[0]
            if not txt or i in used:
                continue
            if resolve(i - 1)[0] != txt:
                heads.append((i, txt))
        print("\n## 缺口：名字表里有、但 267 个事件脚本里没有任何血条调用引用\n")
        print("（%d 个名字）\n" % len(heads))
        print("| name_id | 名字 |")
        print("|---|---|")
        for i, txt in heads:
            print("| %d | %s |" % (i, txt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
