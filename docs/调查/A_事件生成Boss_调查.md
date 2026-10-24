# A：事件生成 Boss 能否随机 —— 15 位置调查报告

- 任务：位置表里 15 个 policy=keep、原因「事件生成」的 Boss，能否参与敌人随机；评估改 EMEVD 参数 / 原地改 NpcParam 两条路线。
- 纪律：只读调查（未改仓库任何已有文件、未启动游戏、未改 YAFSML.ini、未动 git）；临时脚本与本文均在 investigation\_probe\ 下，前缀 A_。
- 证据口径：参考实现给 文件:行号；本仓库给 文件:行号；游戏数据给 反编译 js 行 / CSV 行 / param 值。未证实的一律标「未确认」。

## 0. 一句话结论

**15 个位置没有一个是「EMEVD 运行时生成敌人」。** 它们全部是 MSB 里预置的普通 Enemy part，模型名就是 `c0000`（玩家身体模型），外观/装备/加点由 part 的 `E_CHARA`（CharaInitID）指向 CharaInitParam 决定；EMEVD 只做 Disable/EnableCharacter、播入场动画、挂短时 SpEffect、开 BOSS 血条、发奖励。

由此：

| 路线 | 判定 | 依据 |
|---|---|---|
| (a) 改 EMEVD 生成调用参数 | **不可行** | 全 267 个 event js、113,160 个调用点中没有 CreateNPC / SpawnEnemy / CreateCharacter 类指令，没有可改的「生成调用」 |
| (b) 原地改被生成 npc 的 NpcParam 行 | **不可行（换不了模型）** | NpcParam 结构（paramdex NpcParam.xml 2212 行）无模型字段；这 15 行是 hp=1551 的共享玩家模板行；外观在 CharaInitParam |
| (c) MSB 层换 model/npc/think/chara + NpcParam 克隆行 + 血条名改写 | **可行，现有代码已具备** | enemy_write.patch_map / make_npc_clone / collect_clones；enemy_emevd.patch_evd_bytes |

**建议**：放开 8 个（DLC 红熊 2046450800、拉纳舞娘 2046380800、孤牢骑士 2046410800、罗刹 2051440800；本体 死术师哥瑞斯 31190850、喟叹者 41020800、古龙人 43010800、鲜血祭司艾斯加 35000850），保留 7 个（菲雅英雄组 5 实体 + 帕奇 2 实体）。详见 §7。

## 1. 前提更正：c0000 不是「事件生成空壳」

位置表 note 写「占位模型 c0000（真身由事件生成）」，实测不成立，四组证据：

1. **MSB 里 part 已存在且字段完整**（探针 A_probe_msb.py，逐个读法魂包 634 张 MSB 中对应一张）：每个目标实体都是 `type==2` 的 Enemy part，模型名恰为 `c0000`，并带 `npc / think / chara` 三个身份字段（见 §2 表）。运行时没有「创建」动作，只有 Enable/Disable。
2. **参考实现也把 c0000 当普通模型处理**：`RandomizerCommon\Core\GameData.cs:794-796`：`if (modelName == "c0000") modelName = CharacterName(entity.CharaInitID) ?? (EldenRing ? $"Human {entity.CharaInitID}" : "c0000");` —— 它只是拿 CharaInitID 换显示名，说明 c0000 = 玩家模型的人形 NPC，不是占位壳。
3. **全事件目录没有生成指令**（A_probe_events2.py 全量扫描）：267 个 `*.emevd.dcx.js`、113,160 个指令调用点，`CreateNPC` 命中全部是 `CreateNPCPart`（55，怪物部位破坏）；无 `CreateNPC(`、无 `SpawnEnemy`、无 `CreateCharacter`。名字带 spawn 的只有 8 类特效/物件：`SpawnOneshotSFX` 317、`SpawnMapSFX` 348、`CreateAssetfollowingSFX` 384、`CreateNPCPart` 55、`CreateBulletOwner` 60、`CreateDamagingAsset` 70、`CreateBigDamagingAsset` 552、`CreateReferredDamagePair` 22。
4. **事件对该实体的调用全部是「操作已存在的角色」**：`EnableCharacter` / `DisableCharacter` / `DisableCharacterAI` / `EnableCharacterInvincibility` / `ForceAnimationPlayback` / `SetSpEffect` / `SetCharacterTeamType` / `DisplayBossHealthBar` / `AwardItemsIncludingClients`（逐位置行号见 §2）。

> 结论：所谓「真身由事件生成」是把「事件在战斗开始时 EnableCharacter + 播入场动画」误读成了「生成」。位置表 keep 的那条 yaml 规则（`enemy_classes_v3.yaml:86` `when: "model == c0000"`，reason「占位空壳，真身由事件生成（约 390 行）」）注释里的数字也不准：实测 `enemy_places.csv` 中 c0000 共 **417 行**且全部 keep。

## 2. 逐位置事实表

MSB 事实（A_probe_msb.py 实读）；事件行号为法魂包 `mod\event\<map>.emevd.dcx.js` 的行号（A_probe_events2.py）。

| # | 地图 / 实体 | 名称 | MSB part：模型 / npc / think / chara | 事件关键指令（行号） | 血条名 id | 建议 |
|---|---|---|---|---|---|---|
| 1 | m61_46_45_00 / 2046450800 | 红熊 Red Bear（DLC） | c0000_9000 / 524210095 / 524210000 / 2024210 | L75 `Unknown200476(2046450800,30900)`；L102 team=Enemy；L106 `ForceAnimationPlayback(2046450800,63100,…)`；L111 `DisplayBossHealthBar(Enabled,2046450800,0,900000560)`；事件 2046452800（L74-87）死亡判定+`AwardItemsIncludingClients(30900)`；2046452810（L89-112）Disable→WaitFor(flag+InArea)→Enable→anim→AI→bar | 900000560 | 可随（同实体另有 m61_46_45_10 一行，需同步） |
| 2 | m61_46_38_00 / 2046380800 | 拉纳舞娘 Dancer of Ranah（DLC） | c0000_9001 / 524220083 / 524220000 / 2024220 | L20 `Unknown200476(2046380800,30810)`；L47 team=Enemy；L51 anim63100；L52 `SetSpEffect(2046380800,20018712)`；L57 bar | 900000561 | 可随 |
| 3 | m61_46_41_00 / 2046410800 | 孤牢骑士 Knight of the Solitary Gaol（DLC） | c0000_9001 / 524240080 / 524240000 / 2024240 | L44 team=Enemy；L48 anim63100；L49 `SetSpEffect(…,20018696)`；L54 bar | 900000563 | 可随 |
| 4 | m61_51_44_00 / 2051440800 | 罗刹 Rakshasa（DLC） | c0000_9002 / 524230091 / 524230000 / 2024230 | L43 `Unknown200476(2051440800,30830)`；L70 team=Enemy；L74 anim63100；L75 `SetSpEffect(…,20018695)`；L80 bar | 900000562 | 可随 |
| 5-9 | m12_03_00_00 / 12030800、12030810、12030811、12030812、12030813 | 菲雅的英雄×3 / 魔法师罗杰尔 / 「无畏」莱恩尼尔 | 5 个 part（c0000_9011..9015）：npc 523610066 / 523250066 / 523290066 / 523610066 / 523610066；think 523610100 / 523250100 / 523290100 / 523610100 / 523610100；chara 23611 / 23252 / 23290 / 23701 / 23711 | L629-650 五实体 HP<=0 全灭→`HandleBossDefeatAndDisplayBanner(12030800,GreatEnemyFelled)`→`EnableAssetTreasure(12031490)`；12032810（L653-730）进区域→`CopyCharacterDataFromOnlinePlayers(0,23611..23618,12030800)`→Enable 12030800→anim63010→bar 136100；12032811（L733-749）死亡→Enable 12030810→bar 132500；12032812（L752-820）死亡→同时 Enable 12030811/12030813/12030812，bar 132900/137000/137100 占 slot 0/1/2 | 136100 / 132500 / 132900 / 137100 / 137000 | **保留** |
| 10 | m31_19_00_00 / 31190850 | 死术师哥瑞斯 Necromancer Garris | c0000_9001 / 523760930 / 523760000 / 23760 | L238 `ForceAnimationPlayback(…,68011)`；L244 anim68012；L248 bar | 137600 | 可随（anim 需实测） |
| 11 | m41_02_00_00 / 41020800 | 喟叹者 Lamenter | c0000_9001 / 524270084 / 524270000 / 2024270 | L379 bar；L446/447、488/489、530/531、572/573、614/615、656/657、698/699、740/741 = 8× `IssueShortWarpRequest(41020800,Area,41022810..817,-1)` + anim61020；L1059 再一次传送；L1070-1100 `SetSpEffect(…,20018630..36)` | 142700 | 可随（传送/阶段特效需实测） |
| 12 | m43_01_00_00 / 43010800 | 古龙人 Ancient Dragon-Man | c0000_9010 / 524070081 / 524070000 / 2024070 | L67 team=Enemy；L73 `SetSpEffect(…,20018660)`；L79 bar | 140700 | 可随 |
| 13 | m35_00_00_00 / 35000850 | 「鲜血祭司」艾斯加 Esgar, Priest of Blood | c0000_9001 / 523860000 / 523860000 / 23860 | L1387 bar；只有 enable/AI/无敌/bar，无 anim、无 SpEffect | 138600 | **首选验证对象** |
| 14-15 | m31_00_00_00 / 31000800、31000850 | 帕奇 Patches（两个 part，同坐标） | c0000_9000 / 523090010 / 523090010 / 23090 + talk 309003100；c0000_9002 / 523090210 / 523090010 / 23090 | L312/L594 `SetSpEffect(…,9643)`；L315/L597 `WarpCharacterAndCopyFloor(…,31002820,…)`；L316/L598 `ChangeCharacterPatrolBehavior`；L325/L607 team=Enemy；L329/L610 bar 130900；L336/L617 team=FriendlyNPC；L347/L627 patrol；L357/L637 team=Enemy；L362/L641 bar | 130900 | **保留** |

补充事实：

- 每张图的 c0000 part 数：m12_03=12、m31_00=5、m35=5、m41_02=9、m61_46_45=2，其余各 1。这些图**别的敌人模型列表里没有对应 boss 的大模型**（如熊 c5820）→ 进一步说明 c0000 不是 boss 的占位壳，而是「用玩家模型做的 NPC」。
- m41_02 的 9 个 c0000 中 8 个是 Helper（npc 524270001、chara 2024271），即喟叹者的分身/杂兵，与目标同图但不参与本结论。
- 菲雅组另有 12030814（chara 23612）同图 c0000，作为第二阶段参与者被 Enable。
- 位置表里 15 行 = **9 个唯一位置**：红熊在 m61_46_45_00 与 m61_46_45_10 各一行（同一实体 2046450800，封印/未封印两套 MSB，如萝蜜娜）；菲雅组 5 行；帕奇 2 行。

## 3. 事件侧依赖清单（换模型会碰到什么）

| 依赖 | 出现位置（js 行号） | 换模型后是否会断 | 评估 |
|---|---|---|---|
| `DisplayBossHealthBar` 名字 id | 见 §2 血条列；字面指令 | 需要改写名字（enemy_emevd 字面分支可改） | **必须改**，否则血条名子是原 boss |
| `ForceAnimationPlayback` 固定入场动画 | 63100（4 DLC）、63010（菲雅）、68011/68012（哥瑞斯）、61020（喟叹者） | 新模型可能没有该动画/绑定不同 → 入场动作怪异或 T-pose | 视觉风险，非崩溃；实测确认 |
| 短时 `SetSpEffect` | 20018712（舞娘）、20018696（孤牢）、20018695（罗刹）、20018660（古龙人）、20018630..36（喟叹者阶段） | behaviorId/animIdOffset 全 -1、condHp 只做 HP 阶段判定（实测 SpEffectParam） | 低：不改行为/模型，只是数值/阶段指示 |
| 死亡旗标 = 实体 id | 红熊 `SetEventFlagID(2046450800,ON)` + `EndIf(EventFlag(2046450800))`；各图同类 | 与 npc/模型无关 | 不受影响 |
| 奖励 `itemLot` | `AwardItemsIncludingClients(30900)`（红熊）、`Unknown200476(flag,itemLot)`（DLC 4 处）、帕奇 itemLotId_map=111800 | 事件按实体+itemLot 发，与 npc 无关 | 不受影响（奖励照发） |
| 阶段血条 slot | 菲雅组 12032811/12032812：bar slot 0/1/2 | 事件按实体 Enable + slot 显示 | 换模型不会崩，但 5 连战+复制玩家外观是结构性的 |
| `CopyCharacterDataFromOnlinePlayers` | 全事件仅 m12_03 ×24、m60_47_41_00 ×24 | 复制玩家外观/装备到 c0000；换非 c0000 模型行为未知 | **未确认**，菲雅组保留的主因之一 |
| 帕奇：Warp/Patrol/TeamType 切换/对话 | m31_00 行号见 §2 | 换模型会破坏商人/剧情状态机 | **保留** |

`Unknown200476` 语义：全事件 7 处（common×2、common_func×3、m60_41_51_00×1、m61_46_38_00/2046380800,30810、m61_46_45_00(及 _10)/2046450800,30900、m61_51_44_00/2051440800,30830）。common_func 90005860/61/63 的写法是 `if (Signed(X16_4) != 0) Unknown200476(X0_4, X16_4);`，其中 X0_4 后文用作 `EventFlag(X0_4)` / `SetEventFlagID(X0_4, ON)`，X16_4 后文用作 `AwardItemsIncludingClients(X16_4)` → 参数=(实体/事件 flag, itemLotId)，只与奖励/防重复有关，**不碰角色模型**；指令名未在 ER emedf 里（js 里就叫 Unknown200476），语义**未确认**但不影响本结论。

## 4. 路线 (a)：改 EMEVD 生成调用参数 —— 不可行

结论：**没有可改的对象**。证据链：

1. 若「真身由 EMEVD 生成」，事件里应出现生成指令（CreateNPC / SpawnEnemy / CreateCharacter / spawn 之类的 c0000 创建调用）。全量普查（A_probe_events2.py，遍历 267 个 js、113,160 个调用点）：无任何此类指令；`CreateNPC` 全部命中 `CreateNPCPart`（部位破坏，55 次）。
2. 15 个实体在事件里第一次出现之前，MSB 里就已经有同名 part（§2 表，A_probe_msb.py 同一批 MSB 实读）。
3. 事件对它们的调用是 Enable/Disable + 动画 + SpEffect + 血条 + 奖励（§2、§3）。
4. 因此 enemy_emevd.py / evd_edit.py 面对的不是「生成参数」，而是「血条名字 id / BGM / 模板调用」——这两个模块已经覆盖血条字面改写的需求（`patch_evd_bytes` 的 `<4I>` 分支：`enemy_emevd.py:??` 见代码内 `pos+12` 名字改写；`evd_edit.py` 的 neutralize 与 BGM 条件组）。**无需也没有「生成参数」可改。**

> 附带确认：即使把 EMEVD 的 EnableCharacter 换成别的实体，也只能「启用 MSB 里另一个已存在的 part」，不能凭空生成新 npc/模型——没有生成指令就没有这条路。

## 5. 路线 (b)：原地改被生成 npc 的 NpcParam —— 不可行（换不了模型）

结论：**换不了外观**，且这些行是共享玩家模板行，改它还会波及同行位置。

### 5.1 NpcParam 没有模型字段

`tools\witchybnd-3.0.1.0\Assets\Paramdex\ER\Defs\NpcParam.xml`（2212 行）字段含 behaviorVariationId / nameId / hp / getSoul / teamType / spEffectID3 / itemLotId_* / chrHitRadius / chrHitHeight / animIdOffset / moveType / npcType / threatLv …，**没有模型字段**。模型由 MSB part 的模型名决定（enemy_places 的 model 列来自 msb_read 的 MODEL_PARAM_ST 名）；c0000 的外观由 CharaInitID→CharaInitParam 决定。

### 5.2 这 15 行是「玩家模板行」（A_probe_params.py 实读法魂 regulation.bin）

- 全部 hp=1551、getSoul=0、behaviorVariationId=10000、chrHitRadius=0.5、chrHitHeight=2.2、animIdOffset=0、moveType=3、npcType=0、threatLv=1、itemLotId_enemy=-1、itemLotId_map=-1；帕奇例外：getSoul=800、itemLotId_map=111800、nameId=130900。
- nameId：524210095→142100、524220083→142200、524240080→142400、524230091→142300、523610066→0、523250066→132500、523290066→0、523760930→137600、524270084→142700、524070081→0、523860000→0、523090010/210→130900。
- spEffectID3（等级档）：524210095→20007340、524220083→20007230、524240080→20007300、524230091→20007350、523610066→19390、523250066→19361、523290066→19361、523760930→19360、524270084→20007270、524070081→20007310、523860000→19363、523090010→19353、523090210→19361。
- teamType：多数 6；524070081=27、523860000=33、523090210=26。

即：等级/HP 来自「NpcParam hp（1551 基数）× spEffectID3 档」，外观/装备/加点/玩家 think 来自 CharaInitParam（见 5.3）。改 NpcParam 行只能改数值/名字/掉落，**改不了模型**——这与任务描述里「只换模型/数值」中的「模型」直接矛盾。

### 5.3 外观在 CharaInitParam

paramdex 定义文件 `CharaInitParam.xml`；15 个 chara 行全部存在。字段含 npcPlayerThinkId、npcPlayerType/DrawType/Sex、vowType、equip_Wep_Right/Left、equip_Subwep_*、equip_Helm/Armer/Gaunt/Leg、equip_Spell_02..、baseEnd/baseDex/baseMag/baseFai/baseLuc/baseHeroPoint、item_*、gestureId*、isSyncTarget。

实读样例：2024210（红熊）think=2024210、武器 68690000、装 5020000 系；2024220 武器 7680000；2024240 武器 3690000+弩；2024230 武器 66680000；23611 武器 3610/3611 装 201000/180100；23252 法杖 3250/3251 法术 53160/53525/53252；23290 武器 3290/3291 法术 53290/53291；23760 武器 13020002；2024270 武器 24590000；2024070 武器 66690000 法术 2050020/21；23860 武器 13050010；23090（帕奇）think=23090、Subwep 3090/3091。

→ 这些行是「PvP 人形 NPC 的 build」。若走 MSB 换模型路线，把 E_CHARA 置 -1（enemy_write 已用捐赠者 chara 覆盖）即可，不需要保留这些 chara 行。

### 5.4 npc_id 复用（原地改行的爆炸半径）

A_probe_c0000_stats.py / A_probe_cross.py 交叉位置表：目标 npc 在**位置表内**不跨地图复用——524210095 出现 2 行（同一实体在 m61_46_45_00 与 _10）、523610066 出现 4 行（都在 m12_03：12030800/12030812/12030813/12030814）、其余各 1 行（524220083 / 524240080 / 524230091 / 523760930 / 524270084 / 524070081 / 523860000 / 523250066 / 523290066 / 523090010 / 523090210）。

即便如此，「原地改行」的收益是零（不能换模型）、风险却要担：改 hp/teamType/itemLot/nameId 会同时改到共享该行的其他位置（菲雅组 3 处共用 523610066），且事件按实体查 HP/血条/阶段时用的是 NpcParam 数值语义，一处手滑就会让「阶段血条」或「死亡判定」错位。**不值得走。**

### 5.5 「事件按 npc_id 查东西」的风险，逐条对账

- 血条：`DisplayBossHealthBar` 参数是**实体 id**（§2），不是 npc_id → 换模型不影响。
- 死亡/奖励：事件 flag = 实体 id、奖励 itemLot 独立（§3）→ 不影响。
- HPRatio 阶段：喟叹者用 SpEffect condHp（75/65/55…）挂在身体上，按 HP 比例触发，与 npc 无关 → 换模型后机制仍在，只是新敌人 HP 不同，阶段节奏可能变。
- 动画/掉落：动画看模型/ThinkParam；掉落看 itemLotId_enemy（克隆时从位置原行抄，见 enemy_write.py:655-667）→ 换模型不影响掉落。

## 6. 参考实现怎么做

### 6.1 这 15 个位置在参考实现里都是正常目标

`C:\Users\20905\Downloads\Elden Ring Randomizer 428 v0.12.2 …\randomizer\diste\Base\enemy.txt`（23,173 条，格式 `- ID / Map / Name / Class / Tags`）里 15 个位置全部在表内（A_probe_refenemy.py 逐条匹配）：DLC 4 个 = Class=MinorBoss；菲雅 12030800 = Boss（Helpers 4 个 OwnedBy=12030800）、哥瑞斯/喟叹者/古龙人/艾斯加 = MinorBoss；帕奇 = Class=None。tag 里常见 `exclude:unkillable perceptive arena:1 size:1/2`、菲雅多 `multi/manualname/partial`。

`exclude:unkillable` 不是「目标禁用」：`RandomizerCommon\Enemy\EnemyRandomizer.cs:1673-1690` 的 `canPlace()` 里 `exclude:X` 表示「别把带 X tag 的 source 放进这个 target」（限制来源），目标是可随的。

### 6.2 参考实现也是「改 MSB part 字段」，不是改事件生成

- `RandomizerCommon\Elden\EldenEnemyEditor.cs:23-39` `GetEnemyData`：记 Model / NPC / Think / Char / Col / Anim / Pos；
- `:69-85` `TransplantEnemy(msb, source, target)`：找到 target part 后 `e.ModelName = source.Model; e.NPCParamID = source.NPC; e.ThinkParamID = source.Think; e.CharaInitID = source.Char; e.BackupEventAnimID = -1; e.UnkT15 = false;`；
- `:93-126` `CloneEnemy`：同样四个字段 + EntityID/名字 + TalkID=0；
- `:41-67` `GetModelEditor` 的 `RegisterEnemy` 把 donor 模型名加进 `msb.Models.Enemies`（SibPath `N:\GR\data\Model\chr\<name>\sib\<name>.sib`）。

这几行与我们 `enemy_write.patch_map` 的做法**逐字段一致**（model 登记 + P_MODELIDX + E_NPC/E_THINK/E_CHARA + BackupEventAnimID=-1 + UnkT15=0）。

### 6.3 参考实现的事件层只做两件事

- 血条名改写：`RandomizerCommon\Enemy\EnemyRandomizer.cs:6710-6761` `Reloc[NpcName(nameId)] = NpcName(GetCleverName(...))`；`:7989-8033` EldenRing 分支重写 `DisplayBossHealthBar` 的 instr[2]/instr[3]，或把指令换成 (1014,69)。即「换完模型重指血条名」，不是「改生成参数」。
- 给 ER 注入通用事件模板：`diste\Base\events.txt`（NewEvents，19,306 行）里 9005890 scale / 9005891 scale2 / 9005892 teamtype / 9005893 musicflag / 9005894 enemydrop 等 → 缩放、阵营、音乐、掉落统一由这些模板管。

### 6.4 c0000 相关的三处特判（可借鉴）

- `GameData.cs:794-796`：c0000 的显示名用 CharacterName(CharaInitID)（我们换模型后不再需要）。
- `RandomizerCommon\Enemy\ScalingEffects.cs:290-299`、`:495-502`：`Model == "c0000"` 的敌人单独跳过 spEffect 档（说明参考实现把 c0000 视为「不适用普通数值档」的特例）。
- `EldenEnemyEditor.cs:1114-1115`：c0000 名字开头的目标，换入无 speak 的 source 时要裁 TalkParam lipSync（帕奇这类有对话的要注意）。
- `EnemyRandomizer.cs:3255-3256` 注释 `too much for Gideon, who comes with many c0000s` —— 多角色拆分（Gideon 一套很多 c0000）有性能/复杂度上限。

## 7. 结论与建议（分组）

### 7.1 可随（8 个唯一位置）

| 组 | 位置 | 为什么可以 | 附加动作 |
|---|---|---|---|
| A 低风险（首选验证） | m35_00_00_00/35000850 艾斯加；m43_01_00_00/43010800 古龙人 | 事件只有 enable/AI/无敌/bar（艾斯加连 anim 和 SpEffect 都没有）；古龙人只有一次 SpEffect+anim | MSB 换四字段 + 克隆行 + 血条名改写 |
| B 中风险 | m31_19_00_00/31190850 哥瑞斯；m41_02_00_00/41020800 喟叹者；DLC 4 个（2046450800/2046380800/2046410800/2051440800） | 事件有固定入场动画（68011/68012、61020、63100）或短时 SpEffect；DLC 奖励走 Unknown200476(flag,itemLot) 但奖励与实体绑定 | 同上；实测入场动画与阶段特效是否正常（视觉风险） |

DLC 4 个另外注意：红熊在 m61_46_45_00 与 m61_46_45_10 **两套 MSB 各一行**，如果要求「同一个 boss 同一身份」需两行同 donor（否则两处会随成不同敌人）；位置上它们是两张图，互不影响。

### 7.2 保留（7 个实体 / 7 行）

| 位置 | 保留理由 |
|---|---|
| m12_03_00_00 菲雅组 5 实体（12030800/810/811/812/813） | ① 12032810 用 `CopyCharacterDataFromOnlinePlayers` **把玩家外观/装备复制到这些 c0000 上**，换成非 c0000 模型的行为未确认；② 是 5 连战 + 阶段血条（12032811/12032812 逐步 Enable，bar slot 0/1/2），换模型虽不崩但战斗结构全变；③ 5 行里 3 行共用 npc 523610066 + chara 各不相同，参考实现标 `multi/manualname/partial` |
| m31_00_00_00 帕奇 2 实体（31000800/31000850） | Class=None（商人/剧情 NPC 而非 Boss）；事件含 `SetSpEffect(9643)`（不在 SpEffectParam）/ `WarpCharacterAndCopyFloor` / `ChangeCharacterPatrolBehavior` / 阵营在 FriendlyNPC↔Enemy 间切换 / 对话；换模型会破坏剧情状态机 |

### 7.3 一句话给决策者

「事件生成」这个 keep 理由是误判；15 个位置里 8 个可以按现有 MSB 路线直接放开（零新代码），7 个（菲雅组+帕奇）建议保留，理由是战斗/剧情结构而非模型无法替换。

## 8. 实现清单（要改哪个文件）

### 8.1 放开 8 个位置：改 `investigation/apply/data/enemy_classes_v3.yaml`

规则链（yaml 第 81-94 行；`enemy_data_build.py:490-511` 同一顺序）：`overrides.places` → never_touch_npc_ids → multiphase.groups → evt 非空 → **model==c0000（第 86 行）** → Sound → class.silo=false → keep_models → keep_maps → keep_npc_ids → keep_places（113-125）→ hp 无数值 → else randomize。

实现已经读到，**推荐用 `overrides.places`**（它排第一条，优先于所有自动规则）：

- `enemy_data_build.py:429-432` 把 overrides.places 解析成 `{(map, part_name, occurrence): entry}` —— 键是 **(map, part_name, occurrence)**，不是 entity_id（yaml:419 的示例键也是 `{map, part_name, occurrence, policy, reason}`）。
- `enemy_data_build.py:490-493` 在 never_touch / multiphase / evt / model==c0000 **之前**就套用 override 的 policy → 能压过 c0000 keep。
- 因此把 yaml:419 的 `places: []` 换成 9 条（8 个唯一位置，红熊两图两行），每条 `{map, part_name, occurrence, policy: randomize, reason: ...}`；**part_name/occurrence 从 `investigation/enemy_places.csv` 对应行原样抄**（CSV 列就是 map,part_name,occurrence,…；如红熊 `m61_46_45_00,c0000_9000,1,2046450800,…` 行 22132、`m61_46_45_10,c0000_9000,1,…` 行 22220），别按实体 id 猜。
- 红熊两行 `link` 列都是 `L0014`（CSV 行 22132/22220）→ 计划层 `enemy_plan.py:1146-1175` 把 link 组并成一个替换单元，并校验组内政策一致（`:1169` 政策不一致直接 SystemExit）；写盘层 `enemy_write.py:771` 只改属于本图的那份 → **两行必须都加 override**。
- （备选）在 `model == c0000` 规则（第 86 行）之前插精确 `when` 规则也能生效；但 overrides 是既有机制，优先用它。

8 个唯一位置共 9 行（红熊两图各一行）：m61_46_45_00/2046450800、m61_46_45_10/2046450800、m61_46_38_00/2046380800、m61_46_41_00/2046410800、m61_51_44_00/2051440800、m31_19_00_00/31190850、m41_02_00_00/41020800、m43_01_00_00/43010800、m35_00_00_00/35000850。

不建议改第 86 行本身：c0000 共 417 行，其中 320 行是 cls=None 的 NPC / 场景人物，仍必须 keep。

### 8.2 复核计划层（`investigation/apply/enemy_plan.py`）

- `:1378` / `:1665`：c0000 当**来源**时排除（donor 过滤）——保留，正确。
- `:1616`/`:1635` 新身份的 new_model/new_chara_id/new_think_id 取自捐赠者（正确，不用改）。
- `:1944`：手动指定的候选池也排除 c0000 —— 与本任务无关。
- `:2190-2191`：`_no_candidate_reason` 在「无候选」时给 c0000 一个 `placeholder_model` 文案——只是失败原因说明，**不是目标过滤**。
- `:2860-2862`：属于 selftest ⑮ 挑样本（`_tgt/_don` 取非 c0000 的随机位），**不是生产逻辑**——之前怀疑的「计划层排除 c0000 目标」经复核**不存在**。
→ 结论：计划层**不需要改代码**；`_no_candidate_reason` 的文案（可选）可改掉「真身由事件生成」的说法。

### 8.3 写盘层（不用改）

- `enemy_write.py:610-667` `make_npc_clone`：克隆行以 donor 为底、hp/getSoul 写**位置原值**(621-622)、isSoulGetByBoss=0(624)、disableRespawn=0(626)、threatLv 用位置原值 old_threat(637-641)、itemLot 从位置原行抄(655-667)、spEffectID3 保留 donor 的(647-651) → 位置奖励/位置数值语义自动继承。
- `enemy_write.py:584-602` `collect_clones` 分配新 NpcParam 行 id；`:752-855` `patch_map` 做 model 登记、P_MODELIDX、E_NPC/E_THINK/E_CHARA、0x15=0、0x38=-1；`:860-880`/`:1633-1637` `verify_map` 读回校验。**分析：不需要加新逻辑**。

### 8.4 事件层（不用改）

血条是字面 `DisplayBossHealthBar`，名字 id 在 §2 的行号（红熊 L111、舞娘 L57、孤牢 L54、罗刹 L80、菲雅 L727/L737、哥瑞斯 L248、喟叹者 L379、古龙人 L79、艾斯加 L1387、帕奇 L329/L610）。`enemy_emevd.patch_evd_bytes` 的「字面」分支（`<4I>(en,ent,slot,old_name)` 改 pos+12 名字）已经能做；`evd_edit.py` 管 BGM/neutralize，与本任务无关。

## 9. 风险表

| # | 风险 | 影响 | 严重度 | 缓解/验证 |
|---|---|---|---|---|
| R1 | 固定入场动画对新模型无效（63100/63010/68011/68012/61020） | 入场/传送瞬间姿势怪异或脚本报错 | 中（视觉，理论上不崩） | 实机看 8 个位置的入场；若难受可把该 anim 调用换成 donor 的进场动作或删掉（事件改动，需评估） |
| R2 | 血条名 id 跨区/跨命名空间 | 血条显示 donor 的中文名或空白 | 中 | enemy_emevd 改写后实机看血条文字；DLC 9000005xx ↔ 本体 13xxxx 名字表兼容性**未确认** |
| R3 | 喟叹者 8 次 IssueShortWarpRequest + anim61020 | 新模型在 8 个分身位置反复传送，可能动作/位置错乱 | 中 | 实机跑喟叹者整场；必要时先只放 B 组以外的低风险 4 个 |
| R4 | 哥瑞斯 anim68011/68012（疑似召唤/阶段动画） | 阶段切换可能异常 | 中低 | 实机看二阶段 |
| R5 | DLC `Unknown200476(flag,itemLot)` 语义未确认 | 若它按实体/npc 校验，可能影响奖励 | 低（参数第二位是 itemLot，语义指向奖励） | 实机击杀 4 个 DLC boss 看是否掉原奖励 |
| R6 | 菲雅组 CopyCharacterData 到非 c0000 | 未确认 | —（不放开，无风险） | — |
| R7 | 帕奇剧情状态机 | 商人/对话断 | —（不放开） | — |
| R8 | 位置表放开后 c0000 目标被当成身份/来源 | 随机计划把玩家模板行当 donor | 低（enemy_plan.py:1378 已排除来源） | 跑一次 plan 检查没有 c0000 出现在 donor 列表 |
| R9 | 红熊 link 组（L0014）只 override 一行 | `enemy_plan.py:1169` 构建期直接 SystemExit（link 组内政策不一致） | 中（构建即失败，好发现） | 两行都写；构建后 grep CSV 两行 policy 都是 randomize |
| R10 | overrides.places 的键写错（写成 entity_id / part 名猜错） | 静默不匹配，policy 仍是 keep，看起来「改了却没生效」 | 中 | 构建后 `grep 2046450800 investigation/enemy_places.csv` 看 policy 列必须是 randomize；构建无报错 ≠ 生效 |

## 10. 最小可验证实验

### 10.1 离线（不启动游戏）

对象：**m35_00_00_00/35000850（艾斯加）** 与 **m43_01_00_00/43010800（古龙人）**（事件依赖最少，一个无 anim/SpEffect，一个有 1 次 SetSpEffect+anim）。

1. yaml 按 §8.1 在 `overrides.places` 加两条（part_name/occurrence 从 CSV 抄）→ 跑 `enemy_data_build.py` 重建 `investigation/enemy_places.csv`，确认两行 policy 从 keep 变 randomize、reason 变了。
2. 跑现有 plan（固定种子、只开这两个位置），确认它们出现在「待换目标」里、且 donor 不是 c0000、new_model/new_npc/new_think/new_chara 都有值。
3. 跑写盘（enemy_write）：写出方案层 MSB + NpcParam 克隆行 + EMEVD；用 `msb_read.read_msb` 读回：原 part 的 model 名变了、E_NPC/E_THINK/E_CHARA 变了、模型已登记进 Models.Enemies；`verify_map` 通过（part 数不变、身份字段一致）。
4. 用 `enemy_emevd` 读回事件：`DisplayBossHealthBar` 名字 id 从 138600/140700 变成 donor 的 nameId；`enemy_emevd` 自检（现有 selftest 三例）仍通过。
5. 归档产物 diff：只应出现该 2 个 MSB + event + 新增 NpcParam 行，其他 MSB/事件零改动。

### 10.2 实机（给人执行）

- 进 m35_00_00_00 的 Boss 房：确认出现的是换入的敌人（不是原艾斯加）、能打死、血条显示新名字、击杀后原奖励（itemLot/事件旗标）照发；退出重进确认 `disableRespawn=0` 下重生行为符合预期。
- 进 m43_01_00_00 古龙人房：额外确认 `SetSpEffect(20018660)`（endurance）挂在换入敌人身上没有异常、入场动画 anim 正常播放。
- 两者都过 → 再放 DLC 4 个，逐个看入场动画/血条/奖励。

## 11. 未确认项（明确标注）

1. `Unknown200476` 的准确语义（只从参数用法推断为 (flag,itemLot)，未在 ER emedf 找到定义）。
2. 血条名 id 跨命名空间可用性（DLC 9000005xx 与本体 13xxxx 名字表是否同一 UI 表）。
3. `CopyCharacterDataFromOnlinePlayers` 对非 c0000 模型的行为。
4. m12_03 的 5 个 part（c0000_9011..9015）与 5 个实体 id 的精确配对（事件按实体 Enable，不影响 keep 结论）。
5. 红熊 link 组写盘：`enemy_write.py:771` 只改本图那份，另一份由 link 组另一行负责（代码如此，未实跑验证两份产物都写）。
6. `enemy_bar_name_overrides.csv` 是否已覆盖这 8 个位置的「donor→名字 id」映射（enemy_emevd 字面改写的数据源）；本次未逐行核对，若缺则血条名仍是旧 boss——需在写盘产物里确认。
7. SpEffect 9643 不在 SpEffectParam（帕奇事件用），所在表未确认（不影响本结论，帕奇保留）。

## 12. 附录：本次探针脚本（均在 investigation\_probe\，前缀 A_）

| 脚本 | 用途 |
|---|---|
| A_probe_msb.py | 逐图读 MSB，打印目标实体的 part 身份字段（model/npc/think/chara/pos） |
| A_probe_events2.py | 逐位置扫描 event js：引用点、指令归类、行号；并做全量指令普查（267 js / 113,160 调用点） |
| A_probe_cross.py | 位置表 ↔ 事件 ↔ 血条名交叉 |
| A_probe_c0000_stats.py | enemy_places.csv 里 c0000 全量统计（417 行，cls/bar 分布） |
| A_probe_params.py | 实读法魂 regulation.bin 的 NpcParam 15 行 + CharaInitParam 行 + 事件 SpEffectParam 行 |
| A_probe_refenemy.py | 在参考实现 enemy.txt 里匹配 15 个位置，打印 Class/Tags/NpcName |

复现命令（示例）：`& "C:\Program Files\Python312\python.exe" "investigation\_probe\A_probe_params.py"`。

---

结论汇总：**15 个位置没有一个是事件生成的；8 个可随（现有 MSB 路线零新代码），7 个建议保留（菲雅组 5 + 帕奇 2，原因是战斗/剧情结构）。路线 (a)(b) 均不可行。**