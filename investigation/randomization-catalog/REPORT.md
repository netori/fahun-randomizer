# 法魂随机化前期调查 · 职业专属装备与职业法术卢恩候选清单

**范围**：只建立候选清单，不实现随机算法、不修改/回包 MOD、不启动游戏。
**本目录**：`F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\randomization-catalog\`（新增产物只写这里；原 MOD / 游戏 / 存档 / 法魂资料整合表.xlsx 全程只读）
**基线**：沿用上一轮确认的 `法魂mod V3.0.3 汉化本体（…新YAFSML引擎V0.10.4）`

---

## 0. 上一轮验收（先说结论：**确实解析成功了**）

我重新读取了上一轮的 [REPORT.md](../weapon-baseline/REPORT.md)、[manifest.json](../weapon-baseline/manifest.json)、[weapon_mapping.csv](../weapon-baseline/weapon_mapping.csv) 与 `logs/`，并且**不看结论、直接回到上一轮解包出来的 XML/日志本身复核**。判定依据只用实际解析数据：

| 验收项 | 实际解析证据（可点开） | 结论 |
|---|---|---|
| 女猎手的刺剑参数行 | `EquipParamWeapon.param.xml` 存在 `row id=5100000`，行名 `Huntress's Estoc`（`weaponCategory=2`/`wepType=15`/`swordArtsParamId=1208`） | ✅ 已解析 |
| 欺诈者的大戟参数行 | 同文件 `row id=18530000`，行名 `Halberd of the Deceiver`（`weaponCategory=7`/`wepType=29`） | ✅ 已解析 |
| 名称 FMG 条目 | `WeaponName.fmg.xml` → `id=5100000: 女猎手的刺剑`；`WeaponName_dlc01.fmg.xml` → `id=18530000: 欺诈者的大戟` | ✅ 已解析 |
| 描述 FMG 条目 | `WeaponCaption.fmg.xml` id=5100000；`WeaponCaption_dlc01.fmg.xml` id=18530000 | ✅ 已解析 |
| 奖励 Lot | `ItemLotParam_map` 30203 / 20701 的 slot1（cat=2 武器） | ✅ 已解析 |
| 执行日志 | `logs/024_regulation_recursive.*`（195 param+195 xml）、`logs/011_xml_EquipParamWeapon.console.txt`、`logs/034_fmg_evidence.stdout.txt` | ✅ 命令与退出码齐全 |

**不是**用目录盘点、DLL 加载成功、Excel 名称线索或人工猜测充当成功。因此本轮**复用上一轮已解包数据**：`weapon-baseline/evidence/work2/regulation-bin/`（194 张 param 的 XML）与 `work/item_dlc02-msgbnd-dcx/`（78 个已解出的 FMG）。本轮**没有重新全量解包**，只新增了 14 个 FMG 的 XML 转换（`logs/001..014_xml_*`）与一次 `menu_dlc02` 容器解包（上一轮遗留项，`logs/035_*`）。

---

## 1. 基线核对（开工前 + 收尾各一次，全部 MATCH）

| 文件 | 大小 | SHA256（前 16） | 结论 |
|---|---|---|---|
| `version.txt` | 7 | `d57819fefc715b1f` | 未变（= V3.0.3，正文 `3.0.3.0`） |
| `mod/regulation.bin` | 2,984,544 | `7bcd46b957ac49cf` | 未变 |
| `mod/msg/zhocn/item_dlc02.msgbnd.dcx` | 366,164 | `ee10d0771774d68b` | 未变 |
| `mod/msg/zhocn/menu_dlc02.msgbnd.dcx` | 505,503 | `8feea2ac9bfc7289` | 未变 |
| `法魂资料整合表.xlsx` | 282,013 | `59f2d0a64981286d` | 未变 |
| `tools/witchybnd-3.0.1.0/WitchyBND.exe` | 82,128,653 | `00aa5b321d5af017` | 未变 |
| `tools/witchybnd-3.0.1.0/appsettings.json` | 493 | `a918ab24344e27be` | 未变 |

无版本漂移，**无需重建隔离副本**；上一轮 `inputs/` 副本继续有效。收尾复核记录：`logs/029_integrity_final.*` 与 `evidence/source_integrity_final.json`（`BASELINE_ALL_MATCH: true`）。

---

## 2. 覆盖范围与方法（每条结论都标了可复核的出处）

| 步骤 | 数据源 | 关键约束 |
|---|---|---|
| 防具候选线索 | xlsx **第一个工作表** `Sheet3 (2)`（列 `Name/Text/Location`，611 条数据行、142 个不同 Location） | 表里**没有数字 ID**；不整表判为职业专属；不凭英文名猜中文 ID |
| 防具身份确认 | `EquipParamProtector.param.xml`（978 行，942 行带内嵌行名）+ zhocn `ProtectorName.fmg`/`ProtectorName_dlc01.fmg` | 匹配用**规范化精确同名**：xlsx 英文名 ↔ regulation 内嵌行名 → ID → 中文名（496/611 命中） |
| 部位确认 | `EquipParamProtector` 真实部位标志 `headEquip/bodyEquip/armEquip/legEquip` | 部位不靠名字猜，用参数行标志 |
| 职业归属 | xlsx `职业初始套装位置表`（职业/初始套装/效果/获取位置，26 组 104 件）+ MOD 内 `GoodsCaption` 职业说明条目 | 两条独立来源；名称不一致时用「职业前缀+部位后缀 ∧ 真实部位标志」双信号 |
| 卢恩 | `EquipParamGoods.param.xml`（3793 行）+ `GoodsName/GoodsCaption/GoodsInfo`（zhocn） | 等级名按新版实际数据（见 §3.3），不预设只有五档 |
| 奖励入口 | 全量扫描 `ItemLotParam_map`(7473 行)/`ItemLotParam_enemy`(4631 行)/`ShopLineupParam`(1554 行)，索引 11,311 个 lot 行 | 每个入口单独一行；不合并来源 |
| 类别语义 | 用真表反推：`lotItemCategory` 1=道具(7392 例)、2=武器(879)、3=防具(631)、4=护符、5=战灰、0=杂；`equipType` 0=武器/1=防具/2=护符/3=道具/4=战灰 | ID 会在不同类别重号（例：5100000 既是武器也是防具 Igon's Helm），**必须带类别定位** |

---

## 3. 已验证（含验收样例）

### 3.1 池A：完整四件施法套装（结构上可批准：2 套）

判定 = 四部位齐全 ∧ 四个奖励槽都找到 ∧ 无「同槽被两个 Bundle 占用」。

**① 火山术士（Volcanist，智力+信仰）** — 职业说明 entry **8880**，xlsx `'职业初始套装位置表'!A42`

| 部位 | 物品（zhocn） | ID | 匹配依据 | 奖励槽 | 行名（MOD 自带） |
|---|---|---|---|---|---|
| head | 火山术士帽子 | 1210000 | 职业前缀+部位后缀 ∧ `headEquip=1` | `ItemLotParam_map:16000090:slot1` (cat3, num1, bp1000) | `[LD - Volcano Manor] Volcanist Set …` |
| body | 火山术士长袍 | 1210100 | 精确同名 | `16000091:slot1` | 同上 |
| arm | 火山术士手套 | 1210200 | 精确同名 | `16000092:slot1` | 同上 |
| leg | 火山术士靴子 | 1210300 | 精确同名 | `16000093:slot1` | 同上 |

四槽共同领取 flag `16007090`；效果行（xlsx）：智力/信仰 +1~2、魔法专注消耗 −1~2%；获取位置（xlsx）：火山官邸内锁着的房间、蜗牛后面的秘密通道尽头。

**② 基本主义者（Fundamentalist，信仰）** — 职业说明 entry **8887**，xlsx `'职业初始套装位置表'!A70`
head 基本主义者头冠 **1310000** → `1045370050:slot1`；body 1310100 → `…051`；arm 1310200 → `…052`；leg 1310300 → `…053`；行名 `[Limgrave - Mistwood] Fundamentalist Set`，四槽共同 flag `1045377050`。

其余 9 个施法职业 Bundle **未批准**（缺件或缺槽），列表见 `bundles.json`：辉石魔法师/地底魔法师/诺克斯神谕官/死灵术士/火焰预言家/癫火狂徒（四件不齐）、唤星者(3/4 槽)、腐败侍仆(2/4)、密契者(1/4)。

### 3.2 池B：近战专属**散件**样例

按「效果为 STR/DEX/END 类 ∧ 同名词干不足四部位（确为散件）∧ 有 cat=3 的防具奖励槽」筛选（共 129 条线索，`evidence/set_candidates.json`）：

- **皮革长裤（Leather Trousers）ID 40300**（leg，head/body 同组为不同名散件）— 效果 `Increases STR and VIG by 1 and reduces weapon stamina cost by 1%`，奖励槽 `ItemLotParam_map:1043310343:slot1`（cat3、num1、bp1000），行名 `[Weeping Peninsula - Castle Morne] Leather Trousers`。
- 同组另有 铁头盔 40000 / 鳞甲 40100 / 铁臂甲 40200（各自有 cat=3 槽，例如 40100 的 `1043310341:slot1`）。注意：这三件同时出现在 **cat=5（战灰）** 的槽里（如 `40334:slot1`）——那是 ID 与战灰重号，**不是防具入口**，已按类别剔除。

### 3.3 池B：职业法术解锁卢恩（完整 108 条）

- 命名结构：`等级前缀 + 法术流派 + 卢恩`。**实际等级名称**（MOD 描述原文）：`微光`=新手级、`闪光`=学徒级、`明亮`=熟练级、`闪耀`=精通级、`辉光`=大师级，另有 **`幽影` 系列**（描述同为"大师级"，但为独立物品，共 18 条）——即**每流派 6 档**，不是五档。
- 流派（18）：野兽/律法/恶焰/雷电/黑焰/癫火/血焰/腐败/祖灵/辉石/重力/龙人/岩浆/黑夜/死灵/风暴/冰霜/荆棘。完整清单 `items.csv`（`role=完整职业法术卢恩`，`rune_school`/`rune_tier` 已填）。
- **样例**：`8349 辉光辉石卢恩` → `ItemLotParam_map:10190:slot1`（cat1，行名 `[Haligtree - Loretta] Glint Tome #5`，flag 510190）；`8345 微光辉石卢恩` → `1037440022:slot1`（`[Liurnia of the Lakes - Gate Town Southeast] Glint Tome #1`，flag 1037447020）；`8445 幽影辉石卢恩` → `2050400000:slot1`（行名 `Shadow Rune of Glintstone (used to be Crimson Seed Talisman +1)`）。
- 职业归属证据：职业说明条目点名，例如 entry **8807（辉石魔法师）** 正文列出 `明亮辉石卢恩(8347)`、`辉光辉石卢恩(8349)`、`幽影辉石卢恩(8445)`；共 90 条卢恩拿到此类证据。
- **中间物已排除**：`8550 岩浆卢恩碎片`（描述"…幽影岩浆卢恩的两块碎片之一"，`role=卢恩碎片(中间物)`，`suggested_pool=excluded`）。

### 3.4 商店样例（找到了）

`reward_slots.csv` 中 **286 条** `ShopLineupParam` 入口。样例（原始字段）：

| 物品 | 商店行 | equipType | 价格 | 库存 | 库存 flag | 释放 flag |
|---|---|---|---|---|---|---|
| 凯丹长裤 50300 | 100079 | 1（防具） | 800 | 1 | 100790 | 0 |
| 龙骑士头盔 60000 | 100090 | 1（防具） | 1000 | 1 | 100900 | 0 |
| 铁头盔 40000 | 112089 | 1（防具） | 1 | −1 | 0 | 65899 |

⚠️ 后一类（价格 1 / 库存 −1 / 释放 flag 非 0）的行**没有内嵌行名**，`row_name` 是 Paramdex 回退名（如 `Ash of War: Through and Through`），与 mod 实际售卖内容不符——数值可信、**行语义需人工复核**，已在 CSV 的 `world_position_confidence=shop_row_only` 中标注。

### 3.5 职业说明/路线 FMG 条目（52 条）

- 文件：`GoodsCaption.fmg`（45 条）+ `GoodsInfo.fmg`（7 条），全文见 `guide_entries.csv`（含 `text_raw` 原文，未做任何改写）。
- **caster 职业** entry **8807–8825**：句式 `XX主要使用<属性>，造成<属性>伤害。`，解析出 **18 个职业**（如 8807 辉石魔法师/智力、8816 火焰预言家/信仰、8820 神皮庆典者/信仰与智力）。
- 其余 entry **8870–8895**：武器推荐式说明（每条点名 2 件武器，如 8877 提到 `亚兹勒的辉石杖(33230000)`、`卡利亚骑士剑(2180000)`）。
- 这些条目就是后续「位置→新物品 / 物品→新位置」双向映射的锚：条目里同时有**职业名**、**物品名**、以及（部分）**地点**。

---

## 4. 待确认（明确不进入批准清单）

| 项 | 数量/范围 | 说明 |
|---|---|---|
| 世界位置 | 全部 | 只有 lot 行名提示（如 `[Limestone - Mistwood] Fundamentalist Set`）与 xlsx Location 文本；**未做地图/事件核实**，`world_position_confidence=lot_row_name_hint_only` |
| 单次获取 | 全部 | 库存/flag 都**不能**证明只能领一次；`single_acquisition_confidence=unverified` |
| 职业归属缺证据的防具 | 601 条 | 只有 xlsx 名称/效果线索，未被任何职业说明点名，也未组成可批准 Bundle → 仅作 `poolB_candidate` 线索 |
| Bundle 缺件/缺槽 | 9 个施法职业 | 见 §3.1，`bundles.json` 中 `four_parts_present=false` 或 `n_members_with_entrance<4` |
| 商店行语义 | 286 条中的回退命名行 | 见 §3.4 警告 |
| 装备强度 | — | 按要求**留空**，不凭部位/名称编造 |
| 两把新武器 | 2 条 | `suggested_pool=pending_approval`，**不自动入池B** |

---

## 5. 排除（按本次约束）

- 普通经验卢恩 24 条（黄金卢恩/稀人卢恩/英雄卢恩/王之卢恩/毁坏卢恩/幽影之地卢恩…）→ `out_of_scope`。
- 卢恩碎片（`8550 岩浆卢恩碎片`）→ `excluded`（幽影卢恩两半属于中间物）。
- 大卢恩/卢恩弯弧/修复卢恩（剧情类）、材料、地图、关键道具：未纳入候选（`role` 留空或标 out_of_scope）。
- 合成/制造逻辑：只记录候选与奖励入口，**未修改**。

---

## 6. 评级分离（四个维度各自打分）

| 维度 | 取值 | 依据 |
|---|---|---|
| 物品身份 | `high` | 名称（zhocn FMG）+ 参数行 + 部位标志 三者一致 |
| 奖励槽定位 | `high` | 该 id 在目标表中**以正确类别**出现在具体 (表,行,slot) |
| 世界位置 | `lot_row_name_hint_only` / `shop_row_only` / 空 | 只有行名或商店行，没有地图/实体核实 |
| 单次获取 | `unverified` | 无证据可证一次性 |

---

## 7. 工具与命令

- 复用上一轮的 ConPTY 承载器 `../weapon-baseline/logs/_conpty_run.py`（WitchyBND 的 PromptPlus 终端问题上一轮已解决），本轮只用它做 14 次 `-u -p` 的 FMG→XML 转换（`logs/001_xml_*` … `logs/014_xml_*`）。
- 本轮新增脚本（只读解析，位于本目录 `scripts/`）：
  `scan_rewards.py`（奖励槽索引与类别反推）、`analyze_sets.py`（套装候选）、`analyze_runes.py`（卢恩）、`analyze_guides.py`（职业说明）、`build_catalog.py`/`build_catalog2.py`（清单生成）、`patch_items.py`（职业归属补齐）。
- 命令日志：`logs/*.command.json` + `.stdout.txt` + `.stderr.txt`（argv、工作目录、退出码齐全）。

## 8. 阻塞

**无致命阻塞。** 过程中的两个小坑已修正并留痕：① 一次超大内联脚本被 shell 静默丢弃（无文件产生），改为**脚本文件方式**执行（`logs/022_*` 首次无输出 → 改脚本后成功）；② 初版脚本的 xlsx 路径层级与职业说明过滤条件写错（`logs/026_*` 报 `FileNotFoundError`/解析 0 个职业），修正后 `logs/027_*` 成功。

## 9. 原件完整性（收尾复核）

`logs/029_integrity_final.stdout.txt`：7 个关键源文件**全部 MATCH**（含 xlsx 与工具 exe/appsettings），`BASELINE_ALL_MATCH: true`。本目录 10 个产物哈希记入 `evidence/source_integrity_final.json`。**原 MOD / 游戏 / 存档 / xlsx / 工具配置均未改动。**

---

## 10. 建议首批测试对象（结构上最完整、证据最足）

| 优先级 | 对象 | 目标槽 | 理由 |
|---|---|---|---|
| 1 | **火山术士四件套**（1210000–1210300） | `16000090`–`16000093` 各 slot1 | 四部位齐、四槽齐、无槽冲突、行名自带 `Volcanist Set`、职业说明 8880 可回溯 |
| 2 | **基本主义者四件套**（1310000–1310300） | `1045370050`–`1045370053` 各 slot1 | 同上（`Fundamentalist Set`，说明 8887） |
| 3 | 卢恩 `8349 辉光辉石卢恩` / `8345 微光辉石卢恩` | `10190:slot1` / `1037440022:slot1` | cat1 单槽，flag 明确，职业说明 8807 点名 |
| 4 | 近战散件 `40300 皮革长裤` | `1043310343:slot1` | 散件、cat3、效果偏 STR/VIG |
| 5 | 商店样例 `50300 凯丹长裤` | 商店行 `100079`（价 800/库存 1/flag 100790） | 验证商店路径；注意价格 1 类行的语义未确认 |

> 说明：以上均为**结构上可用**的候选，`bundles.json` 的 `approvable=true` 只代表四部位+四槽+无冲突；**世界位置与单次获取仍需人工确认**，本清单**不可直接注入**。
