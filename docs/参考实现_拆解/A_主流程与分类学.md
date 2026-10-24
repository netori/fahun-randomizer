# A. 主流程与分类学 —— EnemyRandomizer.cs（9,929 行）拆解

> 范围：RandomizerCommon/Enemy/EnemyRandomizer.cs 为主，配合 EnemyPreset.cs（73KB）、EnemyState.cs、EnemyPermutation.cs、Enemies.cs、EnemyEditor.cs、Elden/EldenEnemyEditor.cs、ScalingEffects.cs、Core/GameData.cs。
> 断言后随 (相对路径:行号)；拿不准的地方写「不确定（缺什么证据）」，不猜。

## 0. 一分钟骨架（先记这四条）

- **只有一个类 + 一个泛型方法**：`class EnemyRandomizer` + `Result RunGame<TMap,TEnemy,TObject,TRegion,TGenerator>(RandomizerOptions opt, EnemyPreset preset, IReadOnlyDictionary<string,TMap> maps, EnemyEditor<TMap,TEnemy,TObject,TRegion,TGenerator> enemyEditor)`（RandomizerCommon/Enemy/EnemyRandomizer.cs:125-127）。其余全是这个方法的**嵌套局部函数**：canPlace、fixupPass、getScalingSections、siloClass、presetOpt、newEntity、enableMultichr、ename、getPlaceTarget、getName、fillEntityIdMapping …… **没有「每个游戏一个随机器子类」**，游戏差异靠 `if (game.EldenRing)` 分支 + `EnemyEditor` 抽象层。
- **入口分派**：`public Result Run(RandomizerOptions opt, EnemyPreset preset)`（:95）按 `game.Type` 走 4 条（:100 Sekiro / :106 EldenRing / :112 DS1 / :118 DS3），都不匹配则 `:121 throw new Exception(Internal error: {game.Type})`。
- **随机流**：`int seed = opt.Seed2 == 0 ? (int)opt.Seed : (int)opt.Seed2;`（:129）。之后每个子系统用**派生种子**：`seed + 40`（:3035，魂量）、`seed + 42`（:1240，Sekiro 老龙）、`seed + (int)silo.Type`（:2057，每 silo 一条独立流）、`(int)seed`（:1430 / :1520-1521）。**唯一故意不喂 seed 的**：`Random arenaRandom = new Random();`（:2474），注释 :2473-2474「Arena points can be independent of seed, keeping things a bit interesting, and also fixes issues on rerandomization」。→ 参考实现里有一处刻意不做确定性。
- **三段式写内存**：① 配置+地图 → 内存模型（:132 ~ :2446）② 只改内存里的 MSB 对象（:3015 ~ :4197）③ 只改内存里的 EMEVD 对象（:4198+）。**落盘不是随机器干的**（见 §8）。

## 1. Run/RunGame 的 25 个阶段

阶段标记原文（`// --- 标题`）→ 行号（grep `^// --- [A-Za-z]` 命中 25 条，全在本文件）：

| # | 行 | 阶段（原文标题摘） | 干什么 | 产物写到哪里 | 会不会拒绝/丢弃敌人 |
|---|---|---|---|---|---|
| 1 | 132 | Set up misc constants | entity id 分配器（默认 entityBase=1400000 / entityMax=1500000；ER 4000000 / 5000000，且 :175-178 `if (game.EldenRing && entityBase % 10000 == 4000) entityBase += 6000;`）；分组 id 区间（DS3 5115000、Sekiro 1305000、ER 19005000，:182-203）；跳过清单 entityGroupSkip {5115800, 19005800, 19005801}（:205-210）；DLC 过滤（DS3 按 opt dlc1/dlc2 名单滤 maps+emevds，:223-240；`bool eldenExcludeDlc = game.EldenRing && !opt[opt.dlc]` 按 `game.IsEldenDlcMap` 同时滤 maps 与 emevds，:241-246） | 局部闭包 newEntity / NewEventID 就位 | 越界 :173 `throw new Exception(Internal error: Can't create more entities: out of ids)` |
| 2 | 249 | Load enemy config | `string enemyConfigPath = {game.Dir}/Base/enemy.txt`（:253）→ `EnemyAnnotations ann = ReadYamlFile<EnemyAnnotations>(enemyConfigPath)`（:266）。DEV 构建可切 configs/diste/enemy.txt + enemylist.txt + customnames.txt（:256-294） | ann —— **唯一人工配置源** | 文件缺失即抛错 |
| 3 | 297 | Load preset, but do not fully process | 定 `randomizedTypes` 白名单 :300-323（Boss, Miniboss, MinorBoss, NightMiniboss, DragonMiniboss, Evergaol, FoldingMonkey, TutorialBoss, Basic, HostileNPC, Wildlife, CaravanTroll, DupeOnly；:320 注释 Scarab is not currently included here）；**ER 永远有预设**：:331-350 `if (game.EldenRing && preset == null) { preset = EnemyPreset.MakeClassBasedDefault(ann); … }`，mergeboss 时对 {MinorBoss,Miniboss,DragonMiniboss,NightMiniboss,Evergaol} 置 `assign.MergeParent = true` | parentClass / classDupeCount 两张表 + `EnemyClass siloClass(EnemyClass cl)`（:376-379，子类折叠进父类） | 不在 randomizedTypes 的类永不随机 |
| 4 | 382 | Modify the enemy config directly before any processing | onslaught 复制体（`anyDupeEnabled = preset.EnemyMultiplier > 1 \|\| classDupeCount.Any(...)`，:390-396）与 DS3 箱子→mimic（:487-507） | 往 ann 里**新增 EnemyInfo**（ID 由 newEntity 给，Name = 模型名 + 四位 partId，partId 起点 1000，:439-476） | :410-423 跳过 invader 的 HostileNPC 与 defaultDupeCount>5 时的 20010721/20010723；:425-428 跳过 Helper/None |
| 5 | 517 | Pre-pass on enemy config | 建 infos(:520) / owners(:523) / configEntityIds(:525) / copyTo(:532) / totalHealthbars(:534) / deathLineFlags(:536) / talkLineEdits(:538) / buffGroupEntities(:540)；`isFakeId` 判定 :526-530；`info.SetTags(info.Tags)` :597-600 | Dictionary 索引（纯内存） | :553 duplicate config entity；:566 Internal config error … owns itself |
| 6 | 623 | Preprocess actual map data | 先 `enemyEditor.InitialMapPass(opt)`（:626）→ 逐 map 逐 part：`EnemyData data = enemyEditor.GetEnemyData(e, entry.Key)`（:677）→ `defaultData[data.ID] = data`（:744）+ ownerMap（:745）；copyTo 派生体走 `CloneEnemy + getDupeOffset`（:747-787） | `Dictionary<uint,EnemyData> defaultData`（**后续一切读取的基线**） | :679-691 data.ID 无效且 configEntityIds 补不上 → 打印 Unknown enemy 并 continue（该 part 当没看见） |
| 7 | 805 | Main pass on enemy config | 补算 EnemyInfo 全部派生字段（ModelID/ModelName、ArenaData 系、IsXxx 布尔、owner 继承 flags、翻译名、healthbar、roundBonusSoul） | 就地改 infos | **missingInfos（:875-880）+ :1157-1162 统一降级 `infos[id].Class = EnemyClass.None`**；:1164-1186 merge.NorandomEntities → None |
| 8 | 1203 | Process preset | ann.Groups 按模型名聚组打 tag（:1206-1227）；核心一行 `preset.ProcessEnemyPreset(game, infos, ann, defaultData)`（:1231）；Sekiro old dragons 洗牌特例（:1236-1262） | state.Preset（:1234） | 预设里名字解析不到 → 抛异常（EnemyPreset.cs:1544-1561） |
| 9 | 1265 | Set up scaling | 每游戏一份 ScalingEffects：ER `InitializeEldenScaling`（ScalingEffects.cs:349）、DS1/DS3 `InitializeScaling`（:212）→ `ann.ScalingSections`；再 `EditScalingSpEffects()`（:1272-1287）；可按 seed 重掷 section（:1290-1310） | ann.ScalingSections + scalingSpEffects | 不拒绝敌人 |
| 10 | 1391 | Set up all silos | forceMap + swapboss helper 表 + 按 EnemyClass 分池（§4） | `EnemyPermutation perm`（Silo 集合，结构见 EnemyPermutation.cs:45-63） | :1565 / :1597 两个 throw：Can't randomize #{id} since it was removed from the game |
| 11 | 1613 | Actually assign enemy locations within silos | 每 silo 先预填默认位 → 抽源 → fixup（§4.3） | silo.Mapping（target→source） | 拒绝逻辑全在 canPlace（§3）+ :2196-2200 抽空 → source=target |
| 12 | 2319 | Write to spoiler logs | 打印三组（Boss / Miniboss / Basic）的 Replacing 行（:2322-2443）；`if (opt[opt.silent]) break;`（:2324） | stdout（宿主写成 spoiler_logs 文件，§5.2） | — |
| 13 | 2448 | Enemy position logic | `uint getPlaceTarget(uint target)`（:2451-2472）+ 竞技场取点 + 跨图 region/generator/object 复制工具（供事件阶段用） | 局部函数 + 一个不喂 seed 的 Random | — |
| 14 | 3015 | Fix up and standardize NPC params | `ParamDictionary Params = game.Params;`（:3018）→ `NpcEdits npcs = state.NpcEdits = enemyEditor.InitialNpcPass(state, opt);`（:3027） | NpcEdits —— **所有 param 改写的唯一入口对象** | — |
| 15 | 3030 | Preemptively make copies of all bosses as basic enemies and minibosses | `bossAsBasicNpc` / `bossAsBasicThink`（:3034-3035）+ `Random reward = new Random(seed + 40)`；对 IsFixedSource 实体 `npcs.DuplicateAdjacentNpc(baseNpc)` | 新 PARAM 行（boss 当小怪用时有独立血量/魂量） | — |
| 16 | 3192 | Main enemy randomizer loop | 逐 map 逐 silo 逐 (target,source) 改写 MSB part（§6） | MSB 对象图 + `game.WriteMSBs` + mapping 账本 | :3342 `if (!defaultData[target].Maps.Contains(entry.Key)) continue;`（**只写目标实体真正存在的地图**）；:3343-3366 `source == target` 且无 dupe → 一字不写直接 continue |
| 17 | 4102 | Cleanup | `RemoveEnemies(msb, id => usedHelpers.Contains(id) && infos[id].Class == EnemyClass.Helper)`（:4112）→ `GarbageCollect(msb)`（:4113）→ 非 DS1 按 Name 排序（:4114-4118，注释 :4116 说 DS1 若启用会出现隐形敌人） | MSB 收尾 | **未被引用的 Helper 被物理删除** |
| 18 | 4198 | It's emevd time | `Dictionary<EventKey, EventSpec> templates = eventConfig.EnemyEvents.ToDictionary(...)`（:4201）；`bool argEntityAware = game.EldenRing \|\| game.DS1;`（:4206） | 事件模板表（来自 EventConfig / 外部 JSON，非硬编码） | :4202 非 ER 且 templates 里有 ID 0 → throw |
| 19 | 4209 | Preprocess event config for boss scripts | 摘 endConds / endCond2s / startCmds（:4212 注释 Old boss swap system using StartCmd/EndCond）+ removeImmortality（:4217-4219，IsMortalSekiroBoss 的所有映射目标） | 三张指令表 | — |
| 20 | 4366 | Preprocess emevds for other configs/scripts | 收集 startingAnimations / npcStartingAnimations / defeatFlagBgmIds / DS1 的 specialAnimations、subInitPairs、gravelordFlags；待处理集合 animationEvents、bossBgmEvents（:4369-4383） | 事件改造索引 | — |
| 21 | 4753 | Boss names | `string getName(FMGDictionary fmgs, int nameId)`（:4756-4774）：ER 取 fmgs[NpcName]、DS1 取 fmgs[NPC_name_]、DS3 取 fmgs[NPC名] 空则回落 NPC名_dlc1 / _dlc2 | 血条名混搭（NameTemplates） | — |
| 22 | 4950 | Preprocess dupe events | 注释原文：This modifies the event scripts and the event config in-place. It is confusing.；copyphaseNewMusicFlags、preDupeEvents、idTemplates（:4955-4972） | **就地改**事件脚本与事件配置 | :4963-4965 注释：ER 不支持按 id 索引模板 |
| 23 | 5234 | Main event state | 注释原文：Main event state (avoid editing emevd files directly in main pass)；newInitializations / subInits / subInitEvents / completedTemplates / removedEvents / usedEvents / commonEvents / modifiedEvents（:5237-5250）；唯一落盘口 `void writeModifiedEvents(string map, EMEVD emevd)`（:5252） | 事件缓存（先攒后写） | — |
| 24 | 5274 | Various cached state and output state | `List<RelocMap> dupeRelocs`（按 maxDupeCount 生成，:5278-5290）、progressFlagCopies、music flags | 事件重定位表 | — |
| 25 | 5399 | Event-related entity id and mapping utilities | `void fillEntityIdMapping(RelocMap reloc, uint entity, uint target, bool includeHelpers)`（:5402-5416）：`reloc[EventValue.Enemy(entity)] = EventValue.Enemy(target)` + helper 一并映射（只收 Class == Helper） | reloc 工具 | — |

### 1.1 25 个阶段里真正「拒绝/丢弃敌人」的 8 个位置（汇总，便于做对账）

| 位置 | 条件 | 后果 |
|---|---|---|
| :679-691 | MSB part 的 data.ID 无效且配置补不上 | 打印 Unknown enemy，**跳过该 part** |
| :875-880 | 配置里有、扫完所有地图都没有 | 记入 `missingInfos` 并打印 `Missing enemy {map} {name} #{id}` |
| :1157-1162 | 上一条的集合 | `Class = EnemyClass.None`（**永不参与随机**） |
| :1164-1186 | merge.NorandomEntities | Class = None |
| :1565 / :1597 | 要随机但属 missingInfos | **抛异常中止**（不静默） |
| :4112 | Helper 没被 usedHelpers 引用 | 从 MSB 删除 |
| canPlace + fixupPass | 16 组规则（§3） | 换一个源，或退回原样 |
| :2196-2200 | 源池抽空 | `source = target`（原地不动） |

## 2. EnemyInfo 字段与「谁覆盖谁」

### 2.1 字段清单（RandomizerCommon/Enemy/EnemyAnnotations.cs:112-322，字段名:行号）
ID:117、Map:119、DLC:121、Name:123、DupeMap:126、DupePartName:127、NeighborMap:129、ModelID:132、ModelName:134、DebugText:136、ESDs:138、Events:140、Comment:142、Class:144、OwnedBy:146、NextPhase:148、Add:151、DefeatEntity:153、DefeatFlag:154、AppearFlag:155、StartFlag:156、EncounterFlag:157、MusicFlag:158、Phases:159、HealthbarIndex:160、Important:163、StartEvent:165、EndEvent:166、DeathLine:168、TalkLine:170、Outfit:172、Tags:174、Category:176、ItemName:178、Groups:180、RemoveGroup:183、BuddyGroup:185、SplitFrom:188、DupeFrom:190、DupeIndex:191、DupeEvents:194、SetColName:196、ExtraName:198、FullName:200、PartName:202、DupeName:206、NpcName:208、EnemyType:210、Regions:212、Arena:214、ArenaExclude:216、ExtraArenas:221、DragonArena:223、DragonTrees:225、ArenaRegion:227、ArenaData:229、ArenaExcludeData:231、ExtraArenaData:233、DragonArenaData:245、DragonTreeList:247。

派生属性（同文件 :250-322）：TagSet / SetTags / AddTag / HasTag / GetNamedTag / ExcludeTags(:286，只取以 `exclude:` 开头的 tag)、IsBossTarget(:291)、IsBuffSource(:294)、IsFixedSource(:298)、IsImportantTarget(:301)、HasPerceptiveNose(:304)、IsArenaTarget(:307)、IsImmortal(:310)、IsMortalSekiroBoss(:314)、`SourcePhases(:317) = (Phases < 1 ? 1 : Phases) + (HasTag(buffphase) ? 1 : 0)`、`TargetPhases(:319) = 与之同 + (HasTag(nerfloc) ? -1 : 0)`、`ShallowClone(:321) = (EnemyInfo)MemberwiseClone()`。

关键注释原文：:110 Entire config takes around 15MB；:116 Unique entity id；:122 Part name, unique within map；:145 OwnedBy = For helpers, always travel with the main enemy；:147 NextPhase = For ER first-phase bosses, the second phase；:186-188 SplitFrom = If this is a derived randomized entity, the base non-randomized entity to copy it from. The derived entity is never created if it's *not* randomized.；:299-301 IsImportantTarget = Is a proper encounter with an healthbar, defeat flag, and non-respawning enemy；:209-210 EnemyType = Category for minibosses, to avoid them replacing each other (Arena is also used for this, for bosses)。

### 2.2 来源优先级（实际生效顺序，从底到顶）

| 层 | 来源 | 提供什么 | 覆盖关系 |
|---|---|---|---|
| L0 | **地图 MSB**（阶段 6 的 `defaultData`，EnemyEditor.cs:21 GetEnemyData） | 存在性、Pos、原始 Model/NPC/Think/Char/Col/Anim、EntityGroupIDs、Part 名 | 只被读、**永不写回**（后续一切读 defaultData，§6）；缺了就把 config 层拉黑（missingInfos） |
| L1 | **Base/enemy.txt**（YAML → EnemyAnnotations，阶段 2/5） | Class、OwnedBy/NextPhase、事件与 flags、Arena、名字、Tags、Groups、Category、ItemName、DupeEvents | 覆盖 MSB 的**语义归属**；不改模型本体 |
| L2 | **程序补算**（阶段 7） | ModelID/ModelName（:882-889）、ArenaData 系（:951-967）、IsXxx 布尔（:968+）、owner 继承（:926-941，注释 Bosses inherit most attributes）、NextPhase 只补 BuddyGroup（:942-950）、Important→ExtraName/NpcName/Translated（:911-925） | 一般只填空（写法多为 `??=`） |
| L3 | **预设 EnemyPreset**（阶段 8） | 池组成、NoRandom/MergeParent/InheritParent/ManualParent、EnemyMultiplier、ClassSilo、EnemyIDs（定点替换）、DontRandomize/RemoveSource/AdjustSource | 只改**分类与池**，不碰 model |
| L4 | **强制映射 forceMap**（阶段 10） | target→source 硬绑定 | canPlace 里**无条件放行**（:1676 `if (forceMap.ContainsKey(target)) return true;`） |
| L5 | **运行时改写**（阶段 16） | MSB part 的四个身份字段 + 组 + 位置 | §6 |

### 2.3 「Missing enemy」分支（:875-880）什么条件下触发

```csharp
if (!defaultData.TryGetValue(info.ID, out EnemyData data)) {
    missingInfos.Add(info.ID);
    Console.WriteLine(Missing enemy {info.Map} {info.Name} #{info.ID});
}
```

- 触发条件（三条同时成立）：① enemy.txt 里有这个 ID；② 阶段 6 扫完 `game.Locations` 里全部 map，没有任何 part 的 EntityID 等于它；③ 配置也没法用 fake id 映射补上（:555-563、:692-709）。
- **它不 return**：注释原文 :877 These can potentially be fine. Handle them later. —— 后面元数据照样填，只是到阶段 10 会被降级 `Class = None`（:1157-1162），或被要求随机时抛异常（:1565/:1597）。
- 对我们的意义：参考实现把「配置与本体不一致」当**一等公民状态**处理（一个集合 + 一条日志 + 一个统一降级点），而不是在循环里零散 try/catch。
## 3. canPlace 的全部拒绝规则

签名：`bool canPlace(uint source, uint target, EnemySilo silo, BossPhaseLimit prevLimits, bool explain)`（RandomizerCommon/Enemy/EnemyRandomizer.cs:1673，结束于 :1976）。唯一提前放行：`:1676 if (forceMap.ContainsKey(target)) return true;`。每条拒绝在 explain=true 时打印 `Not adding {ename(source)} to {ename(target)} because …` 再 `return false`。

| # | 行 | 触发条件 | 理由串（照抄原文） |
|---|---|---|---|
| 1 | :1680-1691 | target 的 `exclude:xxx` tag 命中 source（`string excludeStr = exclude.Substring(8);` :1684） | because it is excluded from {excludeStr} |
| 2 | :1693-1701 | ER 且 target 有 `sensitive`、source 有 `perceptive`（除非 `!sourceInfo.IsFixedSource \|\| targetInfo.HasPerceptiveNose`） | because it's too perceptive |
| 3 | :1703-1709 | ER 且 source 有 `frames`、target 地图在 eldenFrameMaps、target 无 `allowframes`、非 IsImportantTarget | because frames in {targetInfo.Map} |
| 4 | :1711-1715 | source == 31220800（Godskin Snail）且 target 是重要目标、DupeIndex == -1、dupeCount>0 | because a bug prevents it from working as the main enemy in an onslaught boss |
| 5 | :1718-1722 | sourceInfo.ItemName == divinedragon 且 targetInfo.DragonArenaData == null | because no Divine Dragon arena support |
| 6 | :1724-1728 | source 有 `unique` 且 target 的 Group 命中 sekiroPhantomGroups（:1658-1668 硬编码 11 个 id） | because it is a unique enemy into a transient target |
| 7a | :1730-1735 | 两者 IsImportantTarget 且 `sourceInfo.Arena == targetInfo.Arena` | because they have the same arena |
| 7b | :1736-1742 | 同上且 arenaEnemyTypes[target.Arena] 已含 source.EnemyType | because they have the same enemy type |
| 7c | :1744-1764 | DS3/ER 且 target 是 NightMiniboss/DragonMiniboss：source==target → 同一条理由；否则 EnemyType 相同或 Model 相同 | because they're identical / because they have the same model |
| 7d | :1766-1773 | DS1 且 source == target | because they're identical |
| 8 | :1775-1782 | DS1 且 target 是 Miniboss 且同 Model | because they have the same model |
| 9a | :1783-1804 | 体积安全模式：两者都是重要目标且 `(source == 2054390800 \|\| !opt[ignoresize])`；`int arena = tag arena ?: (IsBossTarget ? 2 : 3)`、`int size = tag size ?: 0`，size > arena | in safe mode because size {size} > arena {arena} |
| 9b | 同段 | `Randomizer.Omit && (source == 16000800 \|\| source == 16000801) && (arena < 3 \|\| !targetInfo.IsBossTarget)` | in safe mode because arena size {arena} or boss status … |
| 9c | 同段 | source == 2054390800 且 arena < (Boss/Evergaol ? 2 : 3) | in safe mode because arena {arena} will cause frame issues |
| 10a | :1806-1829 | HostileNPC 且 Char>0 且两者 Char 相同 | because they have the same character type |
| 10b | 同段 | ER 且 silo.Sources.Count>1 且同一遭遇组（`info.ID / 10 * 10`，encounterNpcs）里已有同 `Char/10` | because character already exists in the same encounter, {ename(encounterSource)} to {ename(encounterTarget)} |
| 11 | :1831-1841 | (Miniboss 且 opt[earlyreq]) 或 (Boss 且 opt[phasebuff])，target 有 earlyreq 而 source 有 mid/late | because it's not an early enemy |
| 12 | :1843-1847 | opt[phases]+opt[phasebuff]、source.ItemName ∈ {headlessape, demonofhatred}、target.ItemName ∈ {owl, isshin, genichiro} | because of arena restriction due to late-game enemy phases |
| 13 | :1849-1860 | Boss 且 opt[earlyreq] 且 target 有 earlyreq 而 source 有 excludeearly | because it's not an early boss |
| 14 | :1861-1874 | DS1 Boss：(opt[simpleasylum] 且 target 有 simpleasylum) 或 (opt[simpletaurus] 且 target 有 simpletaurus)，而 source 有 excludeearly（两条独立 if，理由串相同） | because it's not a simple boss |
| 15 | :1877-1893 | DS3 Boss 且 silo.Sources.Count>1：source == 该 target 的另一个相位源 | because already present in other phase {ename(otherPhaseTarget)} |
| 16 | :1895-1909 | (ER/DS1) Boss 且 silo.Sources.Count>1：multiPhase 里 sourcePhase == targetPhase > 0，或 targetPhase>0 且 source 有 excludemultiphase | because they have the same final phase / because source has excludemultiphase |
| 17 | :1913-1974 | Sekiro Boss 且 prevLimits != null：`sourcePhases > targetPhases + 1 && Math.Abs(sourcePhases - targetPhases) > 0.001f`；仅当 `prevLimits.Entity == target` 时可用逃生口 `Amount > targetPhases + 2.1f && Amount - sourcePhases > 1.6f` | （Boss fit，§4.4） |
| — | :1975 | 全通过 | return true |

**事后修补 `fixupPass(EnemySilo silo, List<uint> targets, bool useLimits)`（:1977-2000）**：逐 target，若 `!canPlace(cur, targets[i], silo, limits, false)`，就在**全部 target 里线性扫描**找 j 使 `canPlace(cur, targets[j], …) && canPlace(cand, targets[i], …)`，然后**直接改 silo.Mapping 做两两交换**。它**不是重排、不是回溯搜索**，是「违规就地换位」的贪心修补。配套 `printPermutation`（:2001-2007）仅调试用。

相邻闭包：`sekiroRandomizeOpts { Boss: bosses, Miniboss: minibosses, Basic: enemies }`（:2008-2013）；`isRandomized(EnemyClass type)`（:2014-2028，ER 还看 `preset.Classes[type].NoRandom`）；`singletons`（:2030-2032）= 有 tag `singleton` 或属 forceGlobalUnique 的实体（抽源时不许重复抽）。

## 4. silo 的构造（阶段 10，:1391-1610）与放置（阶段 11，:1613-2316）

### 4.1 数据结构（RandomizerCommon/Enemy/EnemyPermutation.cs，65 行）
- `class EnemyPermutation { bool AnyRandomized; SortedDictionary<EnemySiloType, EnemySilo> Silos; GetSilos(EnemyClass); GetSiloMappings(EnemyClass); GetOrCreateSilo(siloType) }`
- `class EnemySiloType { EnemyClass Type; AreaSilo Area = AreaSilo.Default; static Of(type)(:40); WithArea(area)(:41) }`，比较键 = (Type, Area.Type, Area.Index) 三元组。
- `class EnemySilo { EnemySiloType SiloType; List<uint> Sources; List<uint> Targets; List<uint> TempTargets; Dictionary<uint,uint> Mapping; Dictionary<(uint,uint),uint> SwapMapping; }`（:45-63）。注释原文：:54 For now, entity IDs are unique and not collapsed；:57 TempTargets = Targets which are copied from other ones. Must exist in tempBosses and target must exist in Targets.；:59-60 Mapping = Mapping from target to source；:61-62 SwapMapping = (target owner, source helper) to other source helper。
- `record AreaSilo(AreaSiloType Type, int Index, string Name)`（RandomizerCommon/Item/LocationData.cs:172）；`enum AreaSiloType { None, DLC, Region }`（:150-156）；`static AreaSilo ForDlc(bool dlc) => new AreaSilo(AreaSiloType.DLC, dlc ? 1 : 0, dlc ? dlc : base)`（:175）。**「DLC silo」本质是给 siloType 加一个 Area 维度，base 与 dlc 互不流通**。

### 4.2 构造流程（:1394-1600）
1. `EnemyPermutation perm = new();`（:1394）。
2. **forceMap（target→source）六路来源**：
   - ER 且 (preset==null 或 ignoreTarnished)：`preset == null && info.HasTag(norandom)` → 映射自己；`ignoreTarnished && info.HasTag(tarnished)` → 映射自己（:1400-1415；`bool ignoreTarnished = !opt[tarnished];`）。
   - `externalPreset.ForceBossTargets` → 同时 `forceGlobalUnique.Add(source)` 与 `preset.RemoveSourceIDs.Add(source)`（:1420-1428）。
   - `preset.EnemyIDs`（Dictionary<uint,List<uint>> 目标→候选源）：单候选直取，多候选 `Choice(forcemapRandom, sources)`（:1430-1443）；与 forceGlobalUnique 冲突则 :1439 throw（Cannot manually place … because it is forced by item placement）。
   - dupeEnabled 时把 DupeOnly / CaravanTroll 加进 DontRandomizeIDs（:1444-1451，注释 TODO: Fix double invasions）。
   - `preset.DontRandomizeIDs` → 映射自己（:1453-1458，注释 Previously, norandom overwrite Enemies, but this makes phobia presets etc hard）。
   - dupe 跟随原体：`info.DupeFrom > 0 && DontRandomizeIDs.Contains(info.DupeFrom)` → `forceMap[dupe] = DupeFrom`（:1459-1472）；mimic 同理（:1474-1480）。
3. **swapboss**：`opt[swapboss]` 时收集 `HasTag(swappable) && OwnedBy > 0` 的 helper（:1498-1512）→ `swapHelperMapping`（owner→helpers）与 `allSwapHelpers`；`reverseForceMap`（:1514-1518）用于「某源已被强制映射进同一 silo 就不再当源」。
4. **sub-silo 开关**：`bool allowSubsilo = overallSilo == AreaSiloType.None && opt[dlc] && preset != null;`（:1522）。`overallSilo` 在阶段 4 定：:510 `AreaSiloType overallSilo = opt[dlc] && (opt[dlcsilo] || (!dlcDupe && anyDupeEnabled)) ? AreaSiloType.DLC : AreaSiloType.None;`，None 且有 preset 时回落 `preset.OverallSilo`（:511-514）。
5. **主循环（:1523-1600）**逐 `ann.Enemies`（配置顺序）：
   - `EnemyClass infoSilo = siloClass(info.Class)`（父类折叠，:1526）；不在 randomizedTypes → 完全跳过（:1527）。
   - `EnemySiloType siloType = EnemySiloType.Of(infoSilo)`；allowSubsilo 时改用 `assign.ClassSilo`（:1530-1533）；DLC 时 `siloType = siloType.WithArea(AreaSilo.ForDlc(info.DLC))`（:1534-1537）。
   - `EnemySilo silo = perm.GetOrCreateSilo(siloType);`（:1538）。**silo 是「类 × 区域」的桶，第一次遇到就建，没有预声明**。
   - **目标侧四分支**：forceMap 命中 → `silo.Mapping[target] = source`，并给 swappable helper 写 `silo.SwapMapping[(target, helper)] = Choice(forceSwapRandom, allSwapHelpers.ToList())`（:1539-1553）；`Class == DupeOnly` → **只能靠 forceMap，否则彻底不参与**（:1554-1557 注释 Dupe-only enemies should only be forceMap'd）；`tempBosses.ContainsKey` → `silo.TempTargets.Add`（:1558-1562）；否则（missingInfos → throw）`silo.Targets.Add`（:1563-1567）。
   - **源侧排除链（顺序即优先级，:1569-1599）**：① reverseForceMap 命中且同 silo 类 → 不当源；② `preset.RemoveSourceIDs` → 不当源（注释：per-class RemoveSource 留到每类随机时处理）；③ `opt[reducepassive] && HasTag(passive) && reducePassiveRandom.NextDouble() <= 0.9f` → 砍 90%（注释 Cut 90% of instances of a passive enemy）；④ `preset.AdjustSourceIDs[id] = remain` 且 `NextDouble() > remain` → 砍；⑤ `DupeFrom > 0` 或 tempBosses → 不当源（:1592-1593 注释 Dupes cannot be sources - this will generally involve duplicating other eligible sources）；⑥ 否则（missingInfos → throw）`silo.Sources.Add`。
6. **配置为空时怎么办**（阶段 11 内，:2076-2082）：`silo.Sources` 为空则回落 `infos.Values.Where(i => siloClass(i.Class) == siloType).Select(i => i.ID).ToList()`；**仍为空** → throw（Can't find any enemies to use for default pool for {siloType}）。即**没有「静默空池」**。

### 4.3 放置算法（阶段 11，:2035-2269）
1. `if (silo.Targets.Count == 0) continue;`（:2042）。
2. **先无条件预填默认位**：`for (…) silo.Mapping[silo.Targets[i]] = silo.Targets[i];`（:2044-2047），注释 Assign all enemies which are still eligible targets to their default locations, before overwriting it later, just in case. → 任何后续失败都退化为「原样」。
3. `if (!isRandomized(siloType)) continue;`（:2049-2051），之后才 `perm.AnyRandomized = true;`（:2052）。
4. **每个 silo 一条独立随机流**：`Random makeRandom(bool secondary = false)`，`int rseed = seed + (int)silo.Type;`，secondary 再 `rseed += (secondaryCount++) * 100 + 50;`，主序列 `rseed += (randomCount++) * 100;`（:2056-2070）。→ 加一个池不会平移别处的随机结果。
5. **源池组装**（:2071-2171）：`classAssign = preset.Classes[siloType]` → sources（含 RemoveSourceIDs 过滤，**全删光则回退原池**，:2095 `if (removedSources.Count > 0) sources = removedSources;`）→ customPools（preset.Basic / Miniboss / (Boss|TutorialBoss) / FoldingMonkey，否则 classAssign.Pools）→ DLC silo 时把每个 PoolGroup 过滤成只留 `infos[id].DLC == dlcSilo`，**全空则打印 Ignoring configuration … because it's empty after filtering enemies based on DLC silo 并把 customPools 置 null**（:2109-2126）→ `custom = RandomSources.Create(makeRandom(true), customPools, sources, silo.Targets.Count)`。
   - 特例：FoldingMonkey 用带 `early` 的 Miniboss 按 EnemyType 去重（:2147-2158）；TutorialBoss 用全部 Boss 并 `sources.Remove(1110800);`（注释 Castle Genichiro too boring here，:2159-2167）；其余 `Shuffle(makeRandom(), sources)`。
6. **抽源循环**（:2179-2209）：`source = custom.Next(singletons, target)` 或 `RandomSources.Next(singletons, sources, ref sourceIndex)`；:2196-2200 `if (source <= 0) { source = target; poolNorandom.Add(source); }`（**池抽空 = 不随机**，并记入 poolNorandom 以免被 fixup 动）；`silo.Mapping[target] = source;`。
7. **swapboss 求解**（:2212-2228）：swapSources = allSwapHelpers 洗牌、swapTargets 洗牌，`silo.SwapMapping[swapTargets[i]] = swapSources[(swapSourceIndex++) % swapSources.Count]`。
8. **fixup 两轮**（:2230-2245）：`targetsToFix = poolNorandom.Count == 0 ? silo.Targets : silo.Targets.Except(poolNorandom)`，洗牌后 `fixupPass(silo, targetsToFix, false)`；**Boss 且 opt[phases] 再按 `infos[silo.Mapping[t]].SourcePhases` 降序跑一遍 `fixupPass(silo, targetsBySize, true)`** —— 带 limits 的第二轮才是相位均衡真正生效处。
9. **TempTargets**（:2247-2268）：从 tempBosses 映射到的 target 复制源，并把 SwapMapping 一起搬过去。

### 4.4 Boss fit（相位预算）细节（:1913-1974）
- `targetPhases` = Σ TargetPhases；`sourcePhases` = Σ SourcePhases **乘权重**：target 有 early → source 有 mid 乘 1.1f、有 late 乘 1.6f；target 有 mid → source ItemName == demonofhatred 乘 1.1f；target 有 late → source 有 early 乘 0.5f。
- 打印格式：Boss fit … (sourcePhases) into … (targetPhases). Lim {prevLimits.Amount}. Conds …（含 `Amount > targetPhases + 2.1f` 与 `Amount - sourcePhases > 1.6f` 两个判断原样输出）。
- `BossPhaseLimit limits = useLimits ? new BossPhaseLimit { Entity = targets[i] } : null;`（:1983）—— 语义是「该 target 已妥协到的相位预算」，Amount==0 表示还没记过；记过之后同轮用它判断「省下的相位够不够换」。

## 5. 预设 EnemyPreset 与 spoiler log

### 5.1 预设是什么（RandomizerCommon/Enemy/EnemyPreset.cs，约 1,563 行）
- 它是 **YAML 文件**：`public string FileName => presets\\{Name}.txt;`（:28）；`GetPresetNames()` 扫 `presets` 目录的 `*.txt`、剔掉 README/Template（:173-184）。**不是代码、不是硬编码表**。
- 字段（:17-111）：Name、Builtin、Description、RecommendFullRandomization / RecommendNoEnemyProgression、`Options`（空格分隔的选项集合，SortedSet，`private static readonly int optVersion = 4` 版本化，:36-52）、OverallSilo、OopsAll / OopsAllIDs、EnemyMultiplier（:75-76 注释 For enemy onslaught runs (>2 may cause crashes)）、Boss / Miniboss / Basic / Add / FoldingMonkey 五组 `List<PoolAssignment>`、`Dictionary<EnemyClass, ClassAssignment> Classes`、AdjustSource、BuffBasicEnemiesAsBosses、DontRandomize、RemoveSource、`Dictionary<string,string> Enemies`（:102 注释 Specific enemies in specific spots）、`Dictionary<uint,List<uint>> EnemyIDs`、Items、RandomScaling。
- `class ClassAssignment { NoRandom; MergeParent; InheritParent; ManualParent; EnemyMultiplier; ClassSilo; List<PoolAssignment> Pools; RemoveSource; RootParent }`（:113-135）；`class PoolAssignment { int Weight; string Pool; bool RandomByType; bool Norandom; List<List<uint>> PoolGroups; int DefaultCount }`（:148-171）；`class SourceAdjustment { string Source; int Keep; int Total; HashSet<uint> SourceIDs; float Multiplier }`（:137-146）。
- **ER 永远有预设**：`preset == null` 时 `EnemyPreset.MakeClassBasedDefault(ann)`（EnemyPreset.cs:191-215）现场合成 CustomEnemy 默认预设（每组一个 `Pool = default, Weight = 1000, RandomByType = false`）。→ **「没有预设」这个状态被消掉了**。
- 两个入口：`ProcessParents(EnemyAnnotations ann)`（:834，阶段 3 展开 parent）；`ProcessEnemyPreset(GameData game, Dictionary<uint,EnemyInfo> infos, EnemyAnnotations ann, Dictionary<uint,EnemyData> defaultData)`（:878，阶段 8 把**名字**解析成 id）。名字解析先收集 `ann.AllCategories` 的 Name / Instance / Partition / Partial 形成 `eligibleNames` 与 `impliedNames` / `impliedClasses`（:884-915），再落到 EnemyIDs / DontRandomizeIDs / RemoveSourceIDs / AdjustSourceIDs。
- 错误处理很硬：`HandleErrors(List<string> errors)` 逐条打印，非空即 throw —— 单条时是 Error processing preset 后接原文，多条时是 `{n} error(s) processing preset …, listed in spoiler logs`（:1544-1561）。**预设写错 = 整轮不跑**，不做尽力而为。

### 5.2 spoiler log 写了什么、为什么
- 阶段 12（:2319-2443）只做一件事：把 **perm 的最终映射**打印成人话。三组：Boss（并入 TutorialBoss + FoldingMonkey，:2341-2346）、Miniboss（ER 并入 MinorBoss / NightMiniboss / DragonMiniboss / Evergaol，:2359-2371）、Basic（并入 HostileNPC / Wildlife，:2347-2358）。
- 单行格式：`Replacing {fullName(target, true)}: {fullName(source, false)}{scale}`（:2433）。`fullName` = `{Category} {ExtraName ?? game.ModelCharacterName(data.Model, data.Char)} (#{ent}) in|from {LocationName(mapId, pos: data.Pos)}`（:2327-2340）；`scale` 段是 ` (scaling {sourceSection}->{targetSection})`（:2420-2432）；`if (missingInfos.Contains(ent)) return missing #{ent};`（:2329）。
- 排序键：`SortedDictionary<(int grouping, long keyId, uint dupeId), uint>`（:2376）。Basic 按**地图序**分组（:2402-2405）；Boss 按 `ann.ScalingSections` 分组（:2406-2411），ER 用 `keyId = -targetId` 反序（注释 Boss ids usually decrease from side to major bosses, although e.g. Fortissax is an exception）；dupe 先把 targetId 还原成 DupeFrom 再排序（:2392-2399）。
- 两个细节：`:2390 if (autoForce.Contains(targetId)) continue;` 不打印自动映射；`#if !DEBUG` 时每组后补 50 个空行（:2440-2442）给翻页用。
- **落盘不在随机器里**：全部 `Console.WriteLine`。宿主把控制台输出写成文件 —— `EldenRingRandomizer/README.md:92` 原文 The randomizer creates a file in the spoiler_logs directory which contains hints and spoilers for the run you just generated.（具体文件名规则在 app 侧，**不确定**）。
- **为什么这么做**：① 它是唯一「人能读懂」的产物（一局几百行 Replacing，玩的时候当攻略）；② 预设错误信息直接引用它（EnemyPreset.cs:1558），即**日志是错误报告的一部分**；③ 阶段 9 特意提前算 scaling 就为让它能打印（:1265 注释 This is done early mainly to print it out in spoiler logs.）—— **为了日志可读性，允许重排计算顺序**。

## 6. 身份所有权：谁决定 model / npc / think / char

**结论：一次替换的身份是一个不可分割的四元组，来源只有一个 —— `defaultData[source]`。**

| 字段 | 谁写（ER 实现） | 写一次还是可能两次 |
|---|---|---|
| ModelName | 只有 `TransplantEnemy`（Elden/EldenEnemyEditor.cs:72）与复制体 `CloneEnemy`（:96） | 一次 |
| NPCParamID | `TransplantEnemy`（:73）→ 可能被 `SetNpcParam`（:89）覆盖 | **可能两次**（后写生效） |
| ThinkParamID | `TransplantEnemy`（:74）→ `SetNpcParam(npcThinkParam:)`（:90）；另 ER 的 `InitialMapPass` 也会改 | **可能两次到三次** |
| CharaInitID | 只有 `TransplantEnemy`（:75）与 `CloneEnemy`（:99） | 一次，**没有去重/唯一化逻辑** |

- **整包搬运**：`EnemyData data = defaultData[source];`（RandomizerCommon/Enemy/EnemyRandomizer.cs:3373）→ `TEnemy e = enemyEditor.TransplantEnemy(msb, data, target);`（:3374）。ER 的 TransplantEnemy 只写 6 行（Model / NPC / Think / Char + `BackupEventAnimID = -1` + `UnkT15 = false`），**不动 Name、不动 EntityID、不动 EntityGroupIDs、不动 Position**（EldenEnemyEditor.cs:69-85）。→ 「目标 part 的名字与坐标留在原地、皮换掉」= 玩家看到「位置没变、怪变了」。
- **为什么不可能「一半变了」**：没有「模型来自 A、npc 来自 B」的代码路径。四元组同源 → 不存在 model 与 npc 错配的中间态。**错配只可能来自「该写的 part 没写到」**，而由 §8 的写盘模型兜底。
- **可能写两次的地方（如实列出）**：
  1. `SetNpcParam(e, npcParam: …)` 在 Transplant 之后定点覆盖 NPC —— gravelord 分支（:3384）、`bossAsBasicNpc.TryGetValue(source, out int sourceNpc)`（:3386-3389）、`getBasicAsBoss(source, target)`（:3390-3393）。三个值**都派生自同一个 source**（data.NPC / bossAsBasicNpc[source] / getBasicAsBoss(source,target)），故不破坏同源不变量；但**这是唯一能破坏它的入口**。Think 同理（:3394-3403：bossAsBasicThink / npcs.NpcAsInvaderThink / npcs.NpcAsWorldThink）。
  2. `bossAsBasicNpc`（:3034-3035）是阶段 15 预先 Duplicate 出来的 param 行；而 `getBasicAsBoss`（:3136-3187）**每次调用都新 Duplicate 一行**（注释 :3131 These are not cached currently, but there are a finite number of bosses in the game.）→ 同一 (source,target) 若被调两次会得到内容相同、id 不同的两行（当前路径只调一次）。
  3. ER `InitialMapPass`（EldenEnemyEditor.cs:396-440+）为 Night's Cavalry 改写 Think：`e.ThinkParamID = altThink;`（:424）或就地改 NpcThinkParam 行的 logicId（:430-434）。它在阶段 6（:626）跑，**早于**阶段 16 的 TransplantEnemy；是否真会被后续 transplant 覆盖、或另有再应用，**不确定（缺 InitialMapPass 全貌）**。
  4. Helper 复制走 `CloneEnemy`（:96-99）：四元组 + 新 EntityID + 新 Name 一起给，自洽。
- **唯一性由谁保证**：**没有任何字段需要唯一**。唯一性只在两层：EntityID（阶段 1 的分配器）与 part Name（`CloneEnemy` 生成 prefix + ModelName + _ + 四位 partId，EldenEnemyEditor.cs:100-106）。CharaInitID 允许重复（多个 part 共用一份 chr init）。→ 「同一张脸最多出现 N 次」在参考实现里是 canPlace 规则（:1806-1829），不是 id 层约束。
- **防污染不变量**：改写循环边读 `defaultData` 边写 `msb`（:3373 读、:3374 写；:3342 用 `defaultData[target].Maps`），从不从已改过的 MSB 回读身份字段。**这条是整个设计的承重墙**。

## 7. 缩放 scaling 怎么算

- **section 是算出来的，不是配的**：ER 走 `InitializeEldenScaling(defaultData, dupeEnemyMap)`、DS1/DS3 走 `InitializeScaling(...)`（EnemyRandomizer.cs:1272-1287；实现 ScalingEffects.cs:349 / :212）。产出 `ann.ScalingSections` = Dictionary<uint,int>（entity → 档次）。MaxTier 按游戏不同：DS3 5（ScalingEffects.cs:40）、ER 20（:98）、Sekiro 34（:172）、DS1 15（:196）。
- **可选随机重掷**（:1290-1310）：条件 `ann.ScalingSections != null && opt[scale] && (presetOpt(scalerandom) || (preset != null && preset.RandomScaling))`；`Random scalingRandom = new Random(seed);`；对每个 `targetSection > 0` 的实体 `int newScale = scalingRandom.Next(scalingSpEffects.MaxTier) + 1;`（注释 MaxTier is something like 20 (tier 0 ignored in Elden Ring), so normally this goes from 0 to 19 -> 1 to 20.）；`onlyScaleUp`（presetOpt(scaleup)）时取 `Math.Max(newScale, targetSection)`，注释说明这比在 [targetSection, MaxTier] 均匀取数更好平衡。
- **查询函数** `bool getScalingSections(uint source, uint target, out int sourceSection, out int targetSection, bool ignoreCustom = false)`（:1311-…）：任一侧查不到（-1）→ false；ignoreCustom 直接 true；DS1 + opt[earlyscale] + targetSection == 1 → 恒 true；随后按 `noscale` / `noscaleup` tag 做例外（:1328-1334）。
- **真正生效在事件层，不在参数层**（:8840-8922）：`opt[scale]` 时先选 common func 名 —— DS1 用 `speffect`；ER 且（source 是 Helper 或重要目标或 target 有 `generated`）用 `scale2`；DS1 的 generated 用 `speffect2`（:8845-8855）。然后查 `scalingSpEffects.Areas[(sourceSection, targetSection)]` 得 spEffect id，按 `fixedXp` 选 RegularScaling / UniqueFixedScaling / FixedScaling（:8861）→ `addCommonFuncInit(scaleEvent, target, new List<object> { target, scaleSp })`（:8863）。
- 额外叠加档（同函数名、另一个 spEffect）：earlyscale 补 `TutorialScaling`（:8865-8868）；tutscale 方向不一致补 TutorialUp/DownScaling（:8869-8874）；`presetOpt(regularhp)` 时 boss-as-basic 补 `BossAsBasicScaling`（:8889-8893）；Rykard 特例（:8895-8899）；`opt[phasehp]` 时按 `scalephase` tag 补 PhaseUpScaling / PhaseDownScaling（:8903-8921）；dupe 用 `GetDupeScaling(baseCount)`（:9040）。
- 找不到映射**不报错**：`sourceSection > 0 && sourceSection == targetSection` 明确视为正常（注释 we don't expect to find the speffect when the sections are the same, or if the source explicitly has section 99 (do not scale)），其余只在 #if DEBUG 构建下打印 warning（:8876-8886）。

## 8. 写盘模型：「每次随机改了哪些文件」的真正答案

**随机器不写文件**，只往集合里登记，最后由 RandomizerCommon/Core/GameData.cs 统一写：
- `public HashSet<string> WriteMSBs = new();`（:1130）、`WriteESDs`（:1128），另有 WriteEmevds / WriteFMGs。
- 登记点：`:3416 game.WriteMSBs.Add(entry.Key);`（ER 每真正改一个 part 就登记这张图）+ 两个硬编码跨图落点（EldenEnemyEditor.cs:482 / :555）。
- 落盘遍历的是「**磁盘上可能存在的全部 map**」，不是本版改过的 map：`knownMaps = unpackPaths.Where(p => p.EndsWith(.msb.dcx)).Select(BaseName).Union(EldenMaps.Keys)`（:1332-1344，注释 Include maps which are not loaded, like DLC maps, in case past randomizations had them），`Parallel.ForEach` 逐张 `writeMap`。
- 单张图的决策：`bool write = WriteMSBs.Contains(map) && EldenMaps.ContainsKey(map); AddBackupOrRestoreFile(path, write, uxm);`；写时还塞一个 Navmesh 水印（:1316-1320）。
- **决定性的一行** `AddBackupOrRestoreFile`（:1518-1538）：write 时备份并登记；**不 write 且存在 .randobak 时还原；不 write 且没有备份时直接删掉**（`Console.WriteLine(Deleting + path); File.Delete(path);`）。→ **上一版改过、这一版没改的文件不会留在原地**。这是「一半变了」的结构性解药。
- 双胞胎图单列 `getDupePath`（:1189-1202），四条规则注释写得很清楚（tl;dr if dupe is written, do nothing）；EMEVD（:1206-1216）、ESD（:1286-1298）走同一套。

## 9. 对照本项目失败症状的三个结构性差异（只陈述机制）
1. **基线不可变**：参考实现的 `defaultData` 是阶段 6 的一次性快照，阶段 16 所有读都从它来（:3373 / :3342 / :3138 / :3407）。若写入端读的是「已被自己改过的 MSB」，第二轮就会读到自己上一轮写的值 —— 这类「跑两次结果不同」的症状与本项目一致（对照性观察，**不确定**是本项目具体成因）。
2. **写与不写都要落地**：见 §8 —— 「这一版没改这张图」必须**主动清掉上一版留下的文件**。
3. **默认位预填**：silo 内所有 target 先 `Mapping[t] = t`（:2044-2047），失败即原样 —— 不会出现「这个 target 没有任何来源」。

## §可迁移性

### ① 可以直接照抄的机制（与语言无关）
1. **三阶段切分**：配置+地图 → 内存模型（defaultData / infos）；placement 只算 target→source 映射；rewrite 只按映射改 part。**先算完所有映射，再统一改写**，不要边抽边写。
2. **不可变基线 + 派生账本**：defaultData（原始）、infos（语义）、mapping.Mapping / RevMapping / HelperMapping / SwapMapping（这次做了哪些替换）。任何一步只读前两者。
3. **每 silo 独立随机流**（:2056-2070 的 rseed 偏移方案）：增删一个池不影响别处的随机结果，可复现。
4. **先预填默认位再覆盖**（:2044-2047）+ **抽空就不随机**（:2196-2200）：失败最小退化为「原样」，永不出现空洞。
5. **约束检查 + 事后两两交换**（canPlace + fixupPass）：比回溯搜索简单一个数量级，可解释（explain 参数就是为日志准备的）。
6. **写与不写都要落到一致状态**（WriteXxx 集合 + restore-or-delete）：这是「一半变了」的唯一结构性解法。
7. **preset 是数据不是代码**（YAML + 名字解析 + 硬错误）：我们 ini 的 `Plan=` / YAFSML 方案层天然同类，可直接把 presets/*.txt 的字段表照搬成一节 ini。
8. **spoiler log 是产物不是调试输出**：Replacing 表 + scaling 段 + 预设错误引用它。我们 GUI 可直接渲染成「这一局换了什么」。

### ② 依赖 C#/SoulsFormats/ModEngine 我们 Python 侧照搬不了的部分
| 依赖 | 它换来什么 | 我们的替代做法 |
|---|---|---|
| SoulsFormats 的 MSBE / EMEVD / PARAM 强类型对象树（`msb.Parts.Enemies`、`e.CharaInitID = …`） | 内存里随便改，最后 `msb.Write(path)` 一次落盘；改错字段不会破坏文件结构 | 只能对 **YAFSML 提供的方案层 / ini 参数**动手，或走「生成 patch + ModEngine 加载」。**不要在 Python 里手写 MSB 二进制** —— 参考实现能用对象树是因为它自带全套序列化。替代：① 用 YAFSML API 列出该地图的 enemy part 并改字段；② 只在其支持范围定义我们的身份四元组改动；③ YAFSML 不覆盖的字段列成不支持，**在 planner 层明确拒绝**而不是猜着写 |
| `GameData.Params`（PARAM 行读写、`DuplicateAdjacentNpc`） | 给 boss-as-basic 造独立血量/魂量行 | 若 YAFSML/param 侧无此能力，就把「boss 当小怪」记为 unsupported，或只换 model 不换 hp 并在 GUI 如实标注 |
| EventConfig + EMEVD 指令级改写（:4201 之后约 5,000 行） | 换 boss 时把死亡/无敌/BGM/掉落脚本一起搬走 | **最大的一块不可迁移**。降级做法：只支持已接线好的事件集合 —— 换怪**不换事件**，并在 GUI 明说「血条/胜利条件可能不跟着换」。要补齐得接 YAFSML 事件能力或另做 emevd 工具 |
| ModEngine 的 mod 目录覆盖 + `.randobak` 还原/删除 | 不写就一致 | 我们有更好的位置：ini 的 `Plan=` 决定加载哪套方案，天然声明式、可整体撤销。替代：把「这一版要写的文件清单」变成**方案目录的清单**，生成时**整目录替换**（旧文件随旧目录一起消失），效果等价于 AddBackupOrRestoreFile 且不需要备份 |
| 多游戏泛型参数化（TMap / TEnemy / …） | 一份代码管 4 个游戏 | 我们只做 ER/法魂一个上下文，**不要抄这套泛型**，直接写具体的 ErEnemyPart 一类结构 |

### ③ 我们条件更好的地方
1. **有 Python + 现有 investigation/apply 层**：placement 算法（silo / 权重 / 约束）可纯 Python 实现并**离线单测**；参考实现想测只能 dotnet 跑全流程。我们的 canPlace 规则表应直接写成 `@pytest.mark.parametrize` 用例表。
2. **有 YAFSML 方案层 + ini `Plan=`**：参考实现的「WriteMSBs 集合 + 不写就还原」是**补丁式**写盘（结果依赖上一版留下了什么）；我们的 `Plan=` 是**选择式**加载（结果只依赖本版清单）。**这从根上消掉了「一半变了」这个类别** —— 只要坚持「一次随机 = 一个完整方案目录」，不做逐文件增量。
3. **有 GUI**：spoiler log / Replacing 表 / 无法满足的约束（canPlace 的 explain 输出）/「哪些槽位没有可用来源」都能当场展示；参考实现只能靠控制台加 50 行空行翻页（:2440-2442）。而且**校验可以在 GUI 里前置**，不用等一轮跑完。
4. **没有 4 个游戏的兼容包袱**：所有 `if (game.DS3)` / `if (game.Sekiro)` 分支（本文件里占相当篇幅）我们一行都不用写。
5. **可以保留确定性**：参考实现故意让竞技场落点不确定（:2474）；我们若要求「同种子可复现」，把这个例外去掉或做成显式开关即可。

## 附录：本报告未覆盖 / 需二次确认
- `RunGame` 在 :5399 之后的行数（事件主循环如何消费 templates → modifiedEvents → writeModifiedEvents）**未通读**；阶段 18-25 只到「输入输出与用途」级别。
- `RandomizerOptions` 的默认值（opt[dlc]、opt[scale]、opt[phases]、opt[earlyreq] 等）**未读**，文中只记「代码按它分支」，不写默认值。
- `EnemyPreset.ProcessEnemyPreset` 主体（EnemyPreset.cs:878-1502 约 620 行）只读到名字解析与错误处理部分；**名字→id 的完整规则未逐条读**。
- `ScalingEffects.InitializeEldenScaling`（ScalingEffects.cs:349-…）如何从地图/实体推出 section 的算法**未读**，只记它产出 Dictionary<uint,int> 与 MaxTier=20。