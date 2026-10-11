# 法魂 MOD（V3.0.3）新增武器最小范围资产盘点报告

**调查对象**：`女猎手刺剑`、`欺诈者的大戟`
**本报告目录**：`F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\weapon-baseline\`（下称本目录；文中相对路径均相对本目录）
**调查时间（本地）**：2026-10-10 21:18 – 22:0x
**性质**：只读盘点。未实现随机化、未回包、未部署、未启动游戏、未修改原 MOD / 游戏文件 / 存档 / Excel / 工具配置。

---

## 0. 结论速览

| 项目 | 女猎手的刺剑 | 欺诈者的大戟 |
|---|---|---|
| **Item ID** | **5100000** | **18530000** |
| EquipParamWeapon 行 | 5100000 | 18530000 |
| MOD 内行名（英文） | `Huntress's Estoc` | `Halberd of the Deceiver` |
| 武器类别 | `weaponCategory=2`（刺剑）/ `wepType=15` | `weaponCategory=7`（大戟）/ `wepType=29` |
| 战技参数 | `swordArtsParamId=1208` | `swordArtsParamId=5191` |
| 名称 FMG entry | WeaponName.fmg **5100000** | WeaponName_dlc01.fmg **18530000** |
| 描述 FMG entry | WeaponCaption.fmg **5100000** | WeaponCaption_dlc01.fmg **18530000** |
| 奖励入口 | ItemLotParam_map **Lot 30203** slot1（cat=2，数量1，权重1000，flag 530201） | ItemLotParam_map **Lot 20701** slot1（cat=2，数量1，权重1000，flag 520701） |
| 事件发放 | common.emevd 事件 9008010：`AwardItemLot(30203)`，判定 flag 530200 | common.emevd 事件 9008010：`AwardItemLot(20701)`，判定 flag 9270 |
| 商店 | **无**（两处 5100000 命中是防具，见 §8） | **无** |
| 敌人 Lot | 无 | 无 |
| 置信度 | 高（名称/ID/参数行/Lot/事件五重一致） | 高（同上） |

**一句话**：**两把武器的实际 Item ID、奖励 Lot 与 FMG entry 均已读出**（5100000 / Lot 30203 / WeaponName 5100000；18530000 / Lot 20701 / WeaponName_dlc01 18530000）。用户给的名字「女猎手刺剑」在 MOD 文本里逐字**不存在**，MOD 内为「**女猎手的刺剑**」（Huntress's Estoc），属翻译/称呼差异（见 §9）。**没有阻塞到无法读取的程度**（WitchyBND 的 PromptPlus 终端问题已被本次自建的 ConPTY 承载器解决，见 §3）。

---

## 1. 边界与操作审计

- 工作区经 `pwd` 核实为 `F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod`。
- **唯一写入位置**：`investigation/weapon-baseline/`（`inputs/`、`evidence/`、`logs/`、三个交付文件）。未向原 MOD、游戏目录、存档、Excel、工具目录写任何文件；`tools/witchybnd-3.0.1.0/appsettings.json` 未被修改（哈希与上一轮基线一致）。
- **WitchyBND 从未被指向原 MOD 路径**：`logs/*.command.json` 中所有 `WitchyBND.exe` 的入参都是 `investigation/weapon-baseline/` 下的副本。
- 未下载/安装依赖；未注册右键菜单；未改注册表、环境变量或系统设置；未扫描其它游戏目录。
- 只读引用了 MOD 的 `mod/event/*.emevd.dcx.js`（事件脚本，未修改）与工作区 `法魂资料整合表.xlsx`（未修改、未用其行号/地名作 ID 依据）。
- 本次自建的两个**辅助脚本**（不改工具本体，仅用于承载与记录）：
  - `logs/_conpty_run.py`：给需要真实终端的第三方 CLI 分配 ConPTY 并回传输出；
  - `logs/runlog.sh` + `logs/_runlog_write.py`：记录每条命令的 argv / 工作目录 / stdout / stderr / 退出码。

---

## 2. 新版本体定位与选择理由

**候选目录**（含 `version.txt` + `mod/regulation.bin` + `mod/msg` 者，全盘只找到这两个）：

| # | 根目录 | version.txt | mod/regulation.bin | mod/msg | 文件数 | 总字节 |
|---|---|---|---|---|---|---|
| A | `…\elden ring\THE_COVERAGE\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）` | ✅ | ✅ | ✅ | 4110 | 9,050,267,594 |
| B | `…\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）` | ✅ | ✅ | ✅ | 4110 | 9,050,267,594 |

**对比结果**（`evidence/candidate_root_comparison.json`）：两树相对路径集合**完全相同**，大小不一致文件数 **0**，且 `version.txt`、`mod/regulation.bin`、`mod/msg/zhocn/item_dlc02.msgbnd.dcx`、`mod/msg/zhocn/menu_dlc02.msgbnd.dcx`、`使用说明.md` 五个关键文件内容哈希**逐一致**（未做 4110 个文件的全量内容哈希）。

**选择：B**（`THE_COVERAGE-随机开发\…V3.0.3…`）。理由：两目录互为副本，数据上等价；B 是上一轮 V3.0.2 调查所在树的直接后继，且与工作区 `随机mod` 同树，便于对照与回溯。

**旧版未混入**：上一轮基线的输入是 V3.0.2 的 `regulation.bin`（2,977,120 B，sha256 `cab62c7f…`），本轮全部输入取自 V3.0.3（`7bcd46b9…`），哈希不同；且 V3.0.2 目录在本轮开始时已不存在（被 V3.0.3 取代）。

**版本证据**：`version.txt` 正文 `3.0.3.0`（7 字节，哈希 `d57819fe…`）。

---

## 3. 工具链：PromptPlus 终端阻塞及其解决（本次的关键突破）

### 3.1 症状（复现）

| 命令 | 退出码 | 输出 |
|---|---|---|
| `WitchyBND.exe --help`（普通重定向） | 1 | `PromptPlus requires a terminal/console without redirection environment!.` |
| `WitchyBND.exe -s --help` / `-s <file>` | 1 | 同上（静默模式**仍先做终端检查**） |
| `winpty … WitchyBND.exe --help` | 3 | `Assertion failed: ASSERT_CONDITION("wp != nullptr && cols > 0 && rows > 0")`（winpty 拿不到终端尺寸） |

日志：`logs/002_witchy_help_winpty_abs.*`、`logs/004_witchy_silent_unpack_msg.*`。

### 3.2 关键排查

单段 ConPTY **仍然失败**：`logs/005_witchy_conpty_default.console.txt` 里工具照旧报 PromptPlus 错。原因经探针证实——**子进程继承的是父进程的管道句柄**，伪控制台并未成为它的标准流。

`logs/000b_conpty_probe.console.txt`（两段式之后）：`PROBE_STDOUT_IS_CONSOLE True filetype 2 conwin 3936310`。

### 3.3 解决：两段式 ConPTY 承载器

`logs/_conpty_run.py`：

1. **stage1**：`CreatePseudoConsole`（200×60）+ `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`，把控制台输出流落盘到 `--raw-out`；
2. **stage2**：在被分到的真实控制台里用 `CONIN$` / `CONOUT$` 句柄，通过 `STARTF_USESTDHANDLES` 显式绑定目标程序的标准流。

之后 WitchyBND 恢复正常：

```
WitchyBND 3.0.1.0
Configuration … Selected mode: Parse … Passive: True … Unpack only: True
```

**并且拿到了工具自身的完整 CLI**（`logs/021_witchy_help.console.txt`）：`-u/--unpack`、`-p/--passive`、`-c/--recursive`、`-s/--silent`、`-d/--dcx`、`-r/--repack` 等。**本轮全部调用使用 `-u -p`（必要时加 `-c`），从不使用会回包写盘的参数。**

### 3.4 关于 oo2core（Oodle）

`regulation.bin` 与两个 `*.msgbnd.dcx` 都是 DCX + **KRAK（Oodle）** 压缩。三者均成功解包 → 这就是 `oo2core_6_win64.dll`（1,085,952 B，sha256 `988e8226…`）**被实际加载并可用**的功能性证明（比"文件存在"强）。

---

## 4. 解包与转换产物（全部在副本上）

| 输入副本 | 产物 | 证据 |
|---|---|---|
| `evidence/work2/regulation.bin`（= `inputs/regulation.bin`） | `evidence/work2/regulation-bin/`：**195 个 `.param` + 195 个 `.param.xml`**（工具自动解出 Paramdex 并判定 `Determined game for Paramdex: ER`） | `logs/024_regulation_recursive.console.txt` |
| `evidence/work/item_dlc02.msgbnd.dcx` | `evidence/work/item_dlc02-msgbnd-dcx/`：**78 个 FMG** | `logs/007_witchy_msg_unpack.console.txt` |
| `evidence/work/menu_dlc02.msgbnd.dcx` | `evidence/work/menu_dlc02-msgbnd-dcx/`：**53 个 FMG** | `logs/035_menu_unpack.console.txt` |
| 选定的 FMG | `evidence/xml/*.fmg.xml` | `logs/022_023_passive_convert.*`、`logs/02x_xml_*`、`logs/036_eventtalk_evidence.*` |

**注意（工具行为）**：*.param 单文件转 XML 需要交互选择 Paramdex 游戏*（被动模式下报 `Could not determine PARAM type.`，见 `logs/022_023_passive_convert.console.txt` / `logs/011_xml_EquipParamWeapon.console.txt`）。规避办法是**对 `regulation.bin` 用 `-u -c` 递归解包**，游戏判定会下传，一次得到全部 XML——这也是本轮采用的方式。

---

## 5. 已验证：两把武器的实际数据

### 5.1 女猎手的刺剑（Huntress's Estoc）

**物品 ID = 5100000**，`EquipParamWeapon` 行 id = 5100000，行名 `Huntress's Estoc`（证据：`evidence/work2/regulation-bin/EquipParamWeapon.param.xml`；`logs/011_xml_EquipParamWeapon.console.txt`）。

与识别/奖励直接相关的字段（节选，完整值见 XML）：

| 字段 | 值 | 字段 | 值 |
|---|---|---|---|
| `weaponCategory` | 2（刺剑类） | `wepType` | 15 |
| `sortId` | 1408000 | `sortGroupId` | 50 |
| `iconId` | 45944 | `equipModelId` | 256 |
| `behaviorVariationId` | 505 | `swordArtsParamId` | 1208（战技） |
| `attackBaseMagic` | 105 | `spAttribute` | 24 |
| `residentSpEffectId` | 2101 | `spEffectBehaviorId0` | 105563 |
| `reinforceTypeId` / `materialSetId` | 2200 / 2200 | `rarity` | 2 |
| `properStrength/Agility/Faith` | 12 / 8 / 16 | `fixPrice` / `sellValue` | 550 / 200 |
| `correctStrength/Agility/Faith/Luck` | 42 / 18 / 80 / 80 | `weight` | 4 |

**奖励入口（唯一）**：`ItemLotParam_map` **Lot 30203**
- 行名：`[Liurnia - Field - Mystic Huntress] Huntress's Estoc`
- slot1：`lotItemId01=5100000`，`lotItemCategory01=**2**`（武器），`lotItemNum01=1`（默认），`lotItemBasePoint01=1000`（权重/概率；单槽 Lot → 确定性获得），`cumulateLotPoint01=0`
- slot2–8：未写入 → 取 paramdef 默认（id=0/数量0），**即该 Lot 无其它槽物品**
- 领取 flag：`getItemFlagId = 530201`；`GameClearOffset = -1`
- 证据：`logs/030_lot_shop_scan.stdout.txt`

**事件发放点**：`mod/event/common.emevd.dcx.js` 事件 **9008010**（注释 `Save Fixer 3.0.2 -> 3.0.3`）：

```js
$Event(9008010, Default, function() {
    EndIf(EventFlag(1038481700)); //Bellum Highway Flag
    if (EventFlag(530200)) { //Acquisition Flag
        AwardItemLot(30203); //Huntress's Estoc
    }
    …
    SetEventFlagID(1038481700, ON);
    EndEvent();
});
```

**Boss 侧**（`m13_00_00_00.emevd.dcx.js` 事件 13003793「Mystic Huntress Boss Death Handler」）：Boss 死亡 → `SetEventFlagID(13000870, ON)`（Boss 击败 flag）+ `SetEventFlagID(9194, ON)`（注释 `AwardItem Death Flag (In common.emevd)`）。
Boss 名 entry：`EventTextForTalk.fmg` id **910000226** = `失落部族的密契女猎手`；CharacterID `13000870`；所在地图 `m13`（利耶尼亚，与 Lot 行名的 `Liurnia` 一致）。

### 5.2 欺诈者的大戟（Halberd of the Deceiver）

**物品 ID = 18530000**，`EquipParamWeapon` 行 id = 18530000，行名 `Halberd of the Deceiver`。

| 字段 | 值 | 字段 | 值 |
|---|---|---|---|
| `weaponCategory` | 7（大戟类） | `wepType` | 29 |
| `sortId` | 2824000 | `sortGroupId` | 190 |
| `iconId` | 45943 | `equipModelId` | 1027 |
| `behaviorVariationId` | 1803 | `swordArtsParamId` | 5191（战技） |
| `attackBaseDark` | 148 | `spAttribute` | 11 |
| `residentSpEffectId` | 5180500（另有 2102） | `spEffectBehaviorId0` | 1620000 |
| `reinforceTypeId` / `materialSetId` | 2200 / 2200 | `rarity` | 3 |
| `properStrength/Agility/Magic/Faith` | 15 / 11 / 30 / 30 | `fixPrice` / `sellValue` | 850 / 1000 |
| `correctStrength/Agility/Magic/Faith` | 60 / 55 / 85 / 85 | `weight` | 12 |

**奖励入口（唯一）**：`ItemLotParam_map` **Lot 20701**
- 行名：`[Idris Godskin Deceiver] Halberd of the Deceiver`
- slot1：`lotItemId01=18530000`，`lotItemCategory01=2`（武器），`lotItemNum01=1`，`lotItemBasePoint01=1000`，`cumulateLotPoint01=0`
- slot2–8：默认空（无其它槽物品）
- 领取 flag：`getItemFlagId = 520701`

**事件发放点**：同一事件 **9008010**：

```js
    if (EventFlag(9270)) { //Idris Death Flag
        AwardItemLot(20701); //Halberd of the Deceiver
    }
```

**Boss 侧**（`m40_00_00_00.emevd.dcx.js` 事件 40002800）：`WaitFor(CharacterHPValue(40000800) <= 0)` → `SetEventFlagID(40000800, ON)` → **`SetEventFlagID(9270, ON)`**。
Boss 名 entry：`EventTextForTalk.fmg` id **910000225** = `“神皮欺诈者”伊德里斯`；CharacterID `40000800`；地图 `m40`。同一脚本里还有 `// Fog Rift Catacombs - Idris, Godskin Deceiver`（`common.emevd` 事件 9006084 的 107 号初始化）——**雾谷地下墓地**。

**第三方印证**：MOD 自带指南文本 `GoodsCaption.fmg` entry **8890** 中有一行 `欺诈者的大戟 - 雾谷地下墓地`（该 entry 是"神皮庆典者"职业/流派指南，列出武器与所在地）。

---

## 6. FMG：名称、描述、指南 entry

| 用途 | 文件（均出自 `mod/msg/zhocn/item_dlc02.msgbnd.dcx`） | entry id | 正文（节选） |
|---|---|---|---|
| 名称 | `WeaponName.fmg` | **5100000** | `女猎手的刺剑` |
| 描述 | `WeaponCaption.fmg` | **5100000** | `希芙拉河森林中的一截扎实树枝，经祖灵之民之手加工成精良的刀刃。…可与梦之矛配合使用。` |
| 名称 | `WeaponName_dlc01.fmg` | **18530000** | `欺诈者的大戟` |
| 描述 | `WeaponCaption_dlc01.fmg` | **18530000** | `“神皮欺诈者”伊德里斯无瑕的长柄武器。那是他觊觎的象征…` |
| 指南/职业说明 | `GoodsCaption.fmg` | **8890** | 含 `欺诈者的大戟 - 雾谷地下墓地` |
| Boss 名 | `EventTextForTalk.fmg`（出自 `menu_dlc02.msgbnd.dcx`） | **910000226** / **910000225** | `失落部族的密契女猎手` / `“神皮欺诈者”伊德里斯` |

证据：`logs/034_fmg_evidence.stdout.txt`、`logs/036_eventtalk_evidence.stdout.txt`。

**内部自洽性**：女猎手的刺剑描述提到"可与**梦之矛**配合使用"，而同一 Boss 线还掉落 `Spear of the Dreaming`（武器 17080000，Lot 13000912，行名 `… Mystic Huntress - Spear of the Dreaming`）——描述与掉落链互相印证。

---

## 7. 奖励入口汇总（本次扫到的全部）

| 表 | 行 | 内容 | 是否本武器 |
|---|---|---|---|
| ItemLotParam_map | **30203** | cat2 → 5100000（女猎手的刺剑） | ✅ |
| ItemLotParam_map | **20701** | cat2 → 18530000（欺诈者的大戟） | ✅ |
| ItemLotParam_map | 107111 / 107121 / 117102 | cat**3** → 5100000（**防具**） | ❌ 见 §8 |
| ShopLineupParam | 110276 / 111276 | `equipId=5100000`，`equipType=**1**`（防具） | ❌ 见 §8 |
| ItemLotParam_enemy | — | 两把武器 **0 命中** | — |
| 全 195 张表的全字段扫描 | — | 命中仅：上表 + `CharaInitParam`(头盔) + `EquipMtrlSetParam 900176`(materialCate01=1 防具) + `DecalParam 611701`(贴图 id 同名巧合) | ❌ |

---

## 8. 否定结论与 ID 冲突分析（重要）

**5100000 这个 id 同时存在于武器表与防具表**，同名不同物：

- `ItemLotParam_map` 107111 / 107121 / 117102：`lotItemId01=5100000` 但 `lotItemCategory01=3` → **防具**；行名 `Igon's Helm`（Igon 的头盔）。
- `ShopLineupParam` 110276 / 111276：`equipId=5100000`，`equipType=1` → **防具**；行名 `[Reversion] Igon's Helm`；`value` 0 / 500，`mtrlId=900376`，`sellQuantity=-1`，`eventFlag_forStock/Release=0`。
- `CharaInitParam`（`equip_Helm=5100000`，行名 `Igon (NPC)` 等）、`EquipMtrlSetParam 900176`（`materialId01=5100000` 且 `materialCate01=1`）指向的都是该**防具**。

`equipType` 语义不是猜的，是用**交叉表推导**得到的（把 `equipId` 与 `EquipParamWeapon / Protector / Accessory / Goods / Gem` 的 id 集合求交）：

| equipType | 命中表（多数情形） | 例 |
|---|---|---|
| 0 | weapon | `[Merchant] Caestus`、`Great Arrow` |
| 1 | protector | `[Merchant Kale] Chain Coif` |
| 2 | accessory | `[Twin Maiden Husks] Host's Trick-Mirror` |
| 3 | goods | `Ruin Fragment`、`Furlcalling Finger Remedy` |
| 4 | gem（战灰） | `[Bernahl] Ash of War: Square Up` |

**因此：这两把武器没有任何商店售卖入口**；把 `110276/111276` 当成"武器出售"会指到一个头盔上。

`lotItemCategory` 语义同样由行名反推（`logs/030_lot_shop_scan.stdout.txt` 与 `ItemLotParam_map` 全表分布）：**2=武器、3=防具、1=道具、5=战灰、4=护符**。

---

## 9. 未确认（明确列出）

1. **用户所给名字的逐字差异**：`女猎手刺剑` 在 MOD 全部相关 FMG 中**逐字不存在**；MOD 内为 `女猎手的刺剑`（行名 `Huntress's Estoc`）。二者指向同一把武器的证据是：名称 entry id(5100000) = 参数行 id = 行名 `Huntress's Estoc` = 奖励 Lot 30203 的 slot1 物品 id。**"同一把"是推断**（多源一致），不是逐字同名。
2. **`女猎手刺剑` 这个说法的出处未定位**：工作区 `法魂资料整合表.xlsx` 全表检索**没有**"女猎手/欺诈者"条目（只有本体武器的"刺剑/罗杰尔刺剑"等）；MOD 文本里也没有。可能来自 MOD 攻略/社区wiki/口述。
3. **原生掉落链与"存档修复"的关系未完全追踪**：两把武器的 `AwardItemLot` 只出现在 `common.emevd` 事件 9008010（注释标明是 3.0.2→3.0.3 的 **Save Fixer**，并有一次性守卫 flag 1038481700）。而 `common.emevd` 里登记给这两个死亡 flag 的常见发放事件指向的是**别的 Lot**（9194→13000910 铃珠、9270→20700 暗影卢恩）。`common_func.emevd.dcx.js` 中 1100/1200 号通用事件体未展开核对 → **"3.0.3 新玩家实际从何处获得这两件"未确认**。
4. **Lot 与地图实体/宝箱/敌人掉落表的绑定未追**（哪些实体的 `ItemLotId` 指向 30203/20701；`ItemLotParam_map` 属"地图放置"表，通常由地图实体引用）。需要地图实体/EMEVD 的进一步追踪。
5. **"是否属于 MOD 新增"未验证**：本轮未与官方原版 `regulation.bin` 对比（本轮输入范围不含游戏本体目录）。可确认的是：这两行**存在于本案 MOD 的 `regulation.bin`**，且行名/文本是本案 MOD 语境（`[Idris Godskin Deceiver]`、`失落部族的密契女猎手`）。
6. **女猎手的刺剑描述文本**（枝条刃 / 祖灵之民 / 可与梦之矛配合）与"刺剑"字面不完全贴合，但与同一 Boss 线的 `Spear of the Dreaming` 呼应；是否有更合适的解释**未确认**。
7. **`WeaponName_dlc02.fmg` 为空**（1 个 entry）；`GoodsCaption.fmg` 中除指南 entry 外未见其它提及。
8. **`sellQuantity=-1` / `eventFlag_forStock=0` 的确切语义**未从本文档独立验证（且这两行最终被判定为防具，不影响结论）。
9. **地图放置位置**（女猎手/伊德里斯的实际获取地点）本轮只有**行名 + 事件脚本 + 指南文本**三类旁证，**未做地图级核实**。

---

## 10. 阻塞

**结论：无导致任务无法完成的阻塞。** 曾经的两道坎及处置：

| 坎 | 现象 | 处置 | 状态 |
|---|---|---|---|
| 工具完全无法启动（终端检查） | `PromptPlus requires a terminal/console without redirection environment!.` 退出码 1；winpty 断言失败 | 自建两段式 ConPTY 承载器 `logs/_conpty_run.py` | **已解决**（§3） |
| 单文件 `.param` 需交互选 Paramdex | 被动模式下 `Could not determine PARAM type.`；交互模式挂起至 400 s 超时（`logs/011_…`） | 改为对 `regulation.bin` 用 `-u -c` 递归解包（游戏判定下传） | **已绕过** |

`XAML/RecipeParam`：本 MOD 的 regulation 中**没有** `RecipeParam`；同名概念的表是 `ShopLineupParam_Recipe`（204 行，两把武器 **0 命中**）。`TalkParam` 存在（已扫，0 命中）。事件脚本引用**已记录**（§5），**未修改任何事件**。

---

## 11. 偏差与副作用披露（诚实清单）

1. **工具对"目录"的行为**：`logs/009_witchy_fmg_to_xml` 中我把**解包目录**当输入传给 WitchyBND，工具把它当成"**重打包**"处理，于是 `evidence/work/item_dlc02.msgbnd.dcx`（工作副本）被重写为 366,000 B，原副本被工具改名为 `.bak`（366,164 B）。
   - 影响范围：**仅本目录下的工作副本**；`inputs/` 里的原始副本与 MOD 原件、哈希均已复核未变。
   - 教训已记录：**不要给 WitchyBND 传目录**；后续全部改为逐文件 + `-u`。
2. 早期两次尝试（`000_conpty_sanity` 退出码 1、`001_witchy_help_winpty` 退出码 127、`002_…` 退出码 3）为**失败的试验**，日志原样保留，未据此宣称成功。
3. 一次大脚本（生成 CSV/manifest 的初版）在 300 s 内**无输出被转后台并取消**（`bash-139`），未产生任何文件；三个交付文件改为直接写入。该次失败不计入"已完成命令"。
4. 工具自身的临时/缓存落点（Paramdex 解出目录等）未逐项审计；本轮只保证**已登记源文件**的哈希前后一致，不扩张为"全机器零写入"。

---

## 12. 完整性核验（收尾重算）

`logs/033_integrity_final.stdout.txt` + `evidence/source_integrity_final.json`，**ALL_MATCH: true**：

| 文件 | 大小 | SHA256（前 16） | 结论 |
|---|---|---|---|
| `version.txt` | 7 | `d57819fefc715b1f` | 与复制前一致 ⇒ 未改动 |
| `mod/regulation.bin` | 2,984,544 | `7bcd46b957ac49cf` | 与复制前一致 ⇒ 未改动 |
| `mod/msg/zhocn/item_dlc02.msgbnd.dcx` | 366,164 | `ee10d0771774d68b` | 与复制前一致 ⇒ 未改动 |
| `mod/msg/zhocn/menu_dlc02.msgbnd.dcx` | 505,503 | `8feea2ac9bfc7289` | 与复制前一致 ⇒ 未改动 |
| `法魂资料整合表.xlsx` | 282,013 | `59f2d0a64981286d` | 与上一轮基线一致 ⇒ 未改动 |
| `tools/…/WitchyBND.exe` | 82,128,653 | `00aa5b321d5af017` | 与上一轮基线一致 ⇒ 未改动 |
| `tools/…/appsettings.json` | 493 | `a918ab24344e27be` | 与上一轮基线一致 ⇒ 未改动 |
| `mod/event/common.emevd.dcx.js` | 690,670 | `88f42cb85866c546` | 读取后重算一致 |
| `mod/event/m13_00_00_00…js` / `m40_00_00_00…js` / `m11_10_00_00…js` | 77,791 / 80,547 / 107,818 | `a4045114…` / `e2741f55…` / `2942faf7…` | 读取后重算一致 |
| `mod/event/*.js`（267 个，5,283,362 B） | — | 清单哈希 `aebf36918d6fbd4f` | 未逐文件内容哈希（如实标注） |

**原 MOD / 游戏 / 存档 / Excel / 工具配置均未改变。**

---

## 13. 下一步（建议，未执行）

1. **随机化可用锚点**（若要做武器随机化，证据已足够）：
   - `ItemLotParam_map` **30203 / 20701** 的 slot1（`lotItemId01` / `lotItemCategory01=2` / `lotItemNum01`）；
   - 若要"给其它敌人挂上这两把武器"，注意 `lotItemCategory` 必须随物品类别改（武器=2），否则指到同名 id 的防具；
   - 事件侧的 `AwardItemLot(30203/20701)` 是**二次发放**，改动奖励时应一并考虑去重（一次性守卫 flag 1038481700）。
2. **需要人拍板/补充的问题**：
   - `女猎手刺剑` 这个称呼的出处（攻略？群文件？）——若要按该名建白名单，需确认就是 5100000；
   - 是否允许我用**官方原版 `regulation.bin`** 做一次对比，以确认这两件是否属于 MOD 新增（当前输入范围不含游戏本体）。
3. **可选深挖**：`common_func.emevd.dcx.js` 的 1100/1200 通用事件体；地图实体 → `ItemLotId` 的绑定（宝箱/NPC）；`Lot 30203` 是否另有"地图拾取"实体。
4. 若之后要动随机化：**先复制再改**，并把 `evidence/` 下 XML 当基线，用同一套命令重跑校验。

---

## 附录 A：交付物与证据清单

| 文件 | 说明 |
|---|---|
| `REPORT.md` | 本报告 |
| `weapon_mapping.csv` | UTF-8 **BOM**；4 行（两把武器 × 2 类来源：Lot / 事件）；17 列，仅填有证据字段 |
| `manifest.json` | 输入源 / 副本 / 工具 / 命令 / 哈希 / 发现摘要 |
| `logs/` | 每条命令的 `.command.json`（argv、工作目录、退出码）+ `.stdout.txt` + `.stderr.txt`；含 `_conpty_run.py`（承载器）与 `runlog.sh`（记录器） |
| `evidence/source_integrity_final.json` | 收尾哈希核验（ALL_MATCH true） |
| `evidence/candidate_root_comparison.json` | 两个候选本体目录的对比 |
| `evidence/artifact_hashes.json` | 本次产物/交付物哈希 |
| `evidence/xml/`、`evidence/work*/` | FMG→XML 与 regulation 解包副本（可再生成） |
| `inputs/` | 4 个必要输入的原始副本（哈希与源一致） |

## 附录 B：命令日志索引（关键）

| 日志 | 作用 |
|---|---|
| `000b_conpty_probe` | 证明子进程拿到真实控制台 |
| `003_copy_inputs` | 复制输入并双向核对哈希 |
| `007_witchy_msg_unpack` / `008_witchy_regulation_unpack` / `035_menu_container` | 三个容器的解包 |
| `021_witchy_help` | 工具 CLI 全参数（`-u/-p/-c/-s/-r/…`） |
| `024_regulation_recursive` | 195 个 `.param` + 195 个 `.param.xml` |
| `030_lot_shop_scan` | Lot / 商店命中扫描与 Lot 语义 |
| `031_event_context` | `AwardItemLot(30203/20701)` 与死亡 flag |
| `034_fmg_evidence` / `036_eventtalk_evidence` | 名称/描述/指南/Boss 名 entry |
| `033_integrity_final` | 收尾完整性核验 |

> 说明：本报告只陈述本次实际执行到的事；未执行的事在 §9/§10/§11 中逐条标注为"未确认/未做"。
