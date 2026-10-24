# 参考实现拆解：thefifthmatt ER Randomizer 的敌人随机是怎么设计的

> 对象：thefifthmatt/SoulsRandomizers 的 Elden Ring 分支。用户手里的是 v0.12.2（编译产物），本笔记基于 master 源码（pushed 2026-10-16，源码内自称 EldenVersion v0.13）。
> 本文只回答两件事：**他怎么设计的**、**每次随机改动了哪些文件**；末尾给出对我们自己重做的判词。
> 三份逐行拆解：docs/参考实现_拆解/A_主流程与分类学.md ／ B_敌人写入与ER专属.md ／ C_IO产物与自检.md。

## §0 三句话结论

1. **他不是「改游戏文件」，是「用一个只读基线 + 一套内存决议，重造一整棵覆盖树」**：输入永远是 diste/Vanilla 的原始 regulation.bin，输出写进自己的目录，没写的文件会被删掉或从 .randobak 复原。
2. **敌人随机是一次「先决后写」**：先在内存里把 target→source 的映射（silo.Mapping）全部定死、先出 spoiler log，然后才动 MSB，最后统一由脏集合落盘。**没有任何一步是「读已改过的文件再改」**。
3. **语义全在数据表里**（diste/Base/enemy.txt：23,173 条实体标注），代码只把它翻成布尔。所以他的「Boss 池」「可动/不可动」是可审阅的数据，不是散落的条件判断。

## §1 出处

- 源码仓库 thefifthmatt/SoulsRandomizers（默认分支 master）。ER 的 EldenRingRandomizer/ 只是外壳（Program.cs、locations.txt、README.md），**逻辑全在 RandomizerCommon/**。
- 取源码：git -c http.sslVerify=false clone --depth 1 --filter=blob:none --sparse https://github.com/thefifthmatt/SoulsRandomizers（sparse 取 RandomizerCommon + EldenRingRandomizer）。本机只读检出在临时目录，不落进本仓库。
- 用户下载包 C:\\Users\\20905\\Downloads\\Elden Ring Randomizer 428 v0.12.2 ...\\randomizer\\ 里 **diste/ 才是全部输入**：Base(14 文件) / Defs(194 个 paramdef xml) / Names(12) / Messages(25) / Vanilla(regulation.bin) / ModEngine(7，含 modengine2)。
- 关系：diste 是「输入」，随机器目录本身是「输出」。源码注释明确 diste 为 distDirs[FromGame.ER]（Randomizer.cs:63-71）。

## §2 每次随机改动了哪些文件

输出根 outPath：默认 = 随机器自身工作目录（Misc/MiscSetup.cs:173-176，originalWorkingDirectory ?? cwd）；只有勾了 uxm/Nuxe 才 = 游戏目录（Randomizer.cs:125-138）。**默认不碰游戏本体。**

| 写什么 | 谁决定它出现 | 落盘位置 |
|---|---|---|
| regulation.bin（全部 PARAM 表） | 无条件写一次 | GameData.cs:1158 / :1177 |
| event/{map}.emevd.dcx | WriteEmevds 集合里有这张图 | GameData.cs:1206-1208 / :1223 |
| map/mapstudio/{map}.msb.dcx | WriteMSBs 集合里有这张图 | GameData.cs:1305-1307 / :1325 |
| msg/{lang}/{menu,item}_dlc02.msgbnd.dcx | WriteFMGs 为真 | GameData.cs:1250-1252 |
| script/talk/{name}.talkesdbnd.dcx | WriteESDs 集合 | GameData.cs:1285 |
| sfx/sfxbnd_c4721.ffxbnd.dcx | 纯拷贝（给 Hoarah Loux 独立 SFX） | GameData.cs:1246 |

**三段式纪律（这条单独就能消灭「一半变了」）**

1. **输入 = 只读基线**：basePath = {Dir}/Vanilla/regulation.bin（有合并 mod 才换成 mod 的那份，GameData.cs:1153-1158）。他从不读上一轮输出。
2. **整文件重写**：一次 Editor.OverrideBndRel(basePath, ...) 把动过的表重新序列化（:1177，DCX_ZSTD；产出 ≥2,300,000 字节改 DCX_KRAK 重压，:1178-1183）。emevd/msb 也是整文件写（:1223/:1325）。
3. **未写文件清理**：AddBackupOrRestoreFile(path, write, uxm)（:1518-1538）三分支 —— 要写就写并留备份；不写且 uxm 就从 .randobak 复原；不写且非 uxm 就 **File.Delete 并打印 Deleting {path}**。清理遍历刻意包含「磁盘上可能存在的全部 map，包括没加载的 DLC 图，以防过去几轮留下了它们」（:1332-1344）。

**脏标记是文件级的，不是行级 diff**：param 侧靠 paramdef 谓词（AppliedParamdef == null 就沿用底本字节），emevd/msb/esd/fmg 靠四个集合/布尔（:1127-1131），而且必须在**确实改了内容之后**才登记（典型 EnemyRandomizer.cs:9349：先 RemoveAll 自己加的旧事件，再 if (evemvd.Events.Count != eventCount) 才打脏）。没打脏的文件连出现都不出现。

**备份与复原是手动动作**：Backup() 写 {file}.randobak，已存在则不覆盖（保留最原始那版，:1508-1516）；复原靠 RestoreBackupsInternal:1599-1609 / GetBackupFiles:1611-1645 / RestoreBackup:1653-1668。

**唯一不要照搬的**：没有原子性。没有临时目录、没有 File.Replace，SaveEldenRing 无 try/catch（唯一 catch 在 :2282 读 FMG）。写一半崩了就是半成品 —— 我们改成「临时目录 + 成功后整体替换」。

## §3 数据资产：真正的护城河

| 文件（diste/Base） | 体量 | 内容 |
|---|---|---|
| enemy.txt | 102,915 行 / 1.98MB | 敌人分类学 + 23,173 条逐实体标注 |
| events.txt | 19,306 行 / 633KB | 1,221 条 EMEVD 声明式补丁 + 6 个事件模板 |
| annotations.txt | 4,412 行 / 137KB | 物品侧 + 放置限制 |
| submaps.txt | 22KB | 坐标 → 子区域 |
| files.txt | 146KB | 游戏文件权威清单（同时是输出清理的枚举源） |
| er-common.emedf.json | 477KB | EMEVD 指令定义，驱动事件解析 |
| Defs/*.xml | 194 个 | paramdef：**没有它就无法把二进制表翻译成字段，也就不知道要不要重写这张表** |

**enemy.txt 的四个块**

- Classes（1-39）：只有 10 个类（Basic / Boss / MinorBoss / Miniboss / NightMiniboss / DragonMiniboss / Evergaol / Wildlife / HostileNPC / Scarab），带 Parent / AltParent / DefaultInherit / DlcSilo / NoMerge / NoSelfRandom。
- Categories（41-2463；CategoryChanges 2464-2710；:40 是 BaseCategories: []）：预设词汇表，每条 Name + **Count（数字写死在文件里，但代码并不校验 —— 唯一比对在 debugNames 分支，而 EnemyPreset.cs:966 把它默认关着，见 :1103-1122）** + Region(base|dlc) + Classes / ParentClasses / Keywords / Contains / Partitions / Instances / Hidden。硬数字：AllEnemies 20,737；**AllBosses 218（= 52+79+41+21+15+10）**；BaseAllEnemies 13,919；BaseAllBosses 174；DLCAllEnemies 6,818；DLCAllBosses 44。
- Groups（2711-2778）：按模型名的组 —— unkillable = Lightning Ball / Eagle / Owl / Guillemot / Aging Untouchable（危害物，不是 Boss 属性）、frames（掉帧名单）、fallout、npcpart、nosouls、nonunique。
- Enemies（2779-102312）：23,173 条逐实体标注，键 = (Map, ID) + Name(part 名) + Class；只有 1,934 条带显式 Tags，其余继承 Defaults/Models 默认。

**覆盖率硬数字**：distinct maps = **483**（m60 271 / m61 115 / m30 21 / m31 19 / m32 8 / m12 8 …）；DefeatFlag 221、NextPhase 8、BuddyGroup 857、RemoveGroup 15、Important 308、Outfit 109。

## §4 一个敌人在这套系统里是什么

EnemyInfo（Enemy/EnemyAnnotations.cs:112-247）。字段不多，但每个都在后面某处被消费：

ID / Map / DLC / Name(part 名) / ModelID+ModelName / Class / **OwnedBy（helper 永远跟着主敌人走，且继承 DefeatFlag/AppearFlag/Arena/ItemName）** / NextPhase / DefeatFlag / AppearFlag / StartFlag / EncounterFlag / MusicFlag / Phases / HealthbarIndex / Important（Key/ProperName/FullTemplate/NpcName）/ StartEvent+EndEvent / DeathLine / Outfit / Tags / Category / Groups / **RemoveGroup（被换掉时从组里移除，主要给多阶段 Boss）** / BuddyGroup / **SplitFrom（派生的随机实体，基实体不动）** / Dupes / EnemyType / Regions / **Arena（Boss 与 miniboss 的区域，一切都要在界内）** / ArenaRegion（通常是 BGM region）。

**三层分类学，语义只在数据里**

1. Class（EnemyClass 枚举，:708-757，22 种）—— 池边界。
2. Category（:45-75）—— 多继承 + 四种下钻（Partition 枚举切 / Partial 子集切 / Instance 点名 / Contains 并集）。
3. Tags（空格分隔串：SetTags :251、HasTag :266、name:val :270、exclude: :286）。

代码里**只有一处**把 Class 翻成布尔（EnemyRandomizer.cs:1004-1018）：IsBossTarget = Class ∈ {Boss, MinorBoss, Evergaol}；IsImportantTarget = 再加 {Miniboss, DragonMiniboss, NightMiniboss}。Boss 认定**不从 EMEVD、不从血条、不从 is_soul_by_boss 推导**。

## §5 流水线：一个 8,000 行的方法，25 个阶段

RunGame 从 :125 一直写到 :9744，没有子类分派，靠阶段横幅切段：
seed(:129) → 常量(:132) → 事件 id 与实体 id 分配器(:50/:74/:171，实体 id 从 4_000_000 起，:205-210 预留 19005800 给 Final boss) → 载入注释表(:249，ReadYamlFile :266) → preset(:297，延后) → 直接改配置(:382) → 配置预扫(:517) → 预处理地图数据(:623) → 配置主扫(:805，**建 EnemyInfo**，:1004-1018) → 处理 preset(:1203) → 提前算 scaling(:1265，为 spoiler 用) → **建 silo(:1391)** → **分配(:1613，只写 silo.Mapping)** → 位置逻辑 fixupPass(:2448) → **spoiler log(:2319，先于任何改动)** → 规范化 NpcParam(:3015) → 预复制 Boss 为普通敌人(:3030) → **主循环改 MSB(:3192)** → Cleanup(:4102) → EMEVD 段(:4198 起) → 落盘（不在这里，见 §2）。

三处「先决后写」的证据链：分配只写内存 Mapping（:2179-2209）→ spoiler 先出（:2319-2443）→ 才动 MSB（:3192），改动进脏集合 game.WriteMSBs（:3416 / GameData.cs:1130）→ 由 GameData.cs:1307 统一写。**这就是我们「方案层从未生效」的反面**：他的方案层就是 Mapping，写盘只看它。

## §6 身份：只有一个写入点

一个敌人 = MSB part 的 5 个外键 + 附属引用。

- **TransplantEnemy（Elden/EldenEnemyEditor.cs:69-85）一次写全 6 行**：ModelName / NPCParamID / ThinkParamID / CharaInitID / BackupEventAnimID = -1 / UnkT15 = false（注释：动画不沿用，有些敌人住在地下）。它**不动** Name / EntityID / Position。
- **NpcParam 行永不就地改**：NpcEdits.cs:111 DuplicateAdjacentNpc / :92 DuplicateAdjacentRow 把源行复制到「原 id 向后第一个空位」再改副本。所以「keep」是默认行为 —— 代码只列必须改的几项（B 报告 §3.2 有完整清单：getSoul、disableInitializeDead、disableRespawn、isSoulGetByBoss、threatLv、nose_dist/eye_dist、hp 几何平均、teamType、dlcGameClearSpEffectID、reduceDamageSps 剔除、hitRadius）。
- **CloneEnemy（:93-126）**用于 helper / 分裂 / dupe：DeepCopy 后重设 EntityID / Name、Unk08 = newPartId（注释 Needed to avoid sudden deaths）、TalkID = 0（Transplanting talks breaks most talk scripts）。
- **ordering 是强制的**：EnemyState.cs:11-52 每个 getter 未初始化就 throw（accessed enemy permutation before initialized），唯一合法构建顺序 Enemies → Preset → Permutation → NpcEdits → Mapping。
- **唯一性靠数据结构，不靠 assert**：一个 target 只属于一个 silo，Mapping 每个 key 只写一次（:2201），主循环每个 target 只 transplant 一次。
- **改写循环从不回读已经改过的 MSB**：读的是 defaultData[source]，写的是 msb（:3373/:3374）。这是「同一份 plan 跑两次结果不同」的承重墙 —— 他的 getBasicAsBoss 注释甚至直说每次调用都新建一行（:3145-3146），不幂等也照样正确，因为输入永远是基线。

**keep 是双层的**：①按行（借源整行：hp/防御/poise/team/spEffect 全来自源行）；②全局后处理 InitialNpcPass（EE:395）/ FinalNpcPass（EE:1057）扫**全部** NpcParam 行，只按 tag 命中处原地改（mortal / immortal / reducepassive / healthbarscale…），未列字段一律不动。

## §7 分配与可放置性

- silo 键 = **(Class, Area)**（Enemy/EnemyPermutation.cs:35）。同一个 silo 内的 source 才可能换到某个 target；桶外永不互通。
- 先无条件预填 Mapping[t] = t（:2044-2047）；抽空就 source = target（:2196-2200，记 poolNorandom）；再用 **canPlace（17 组规则，:1673-1975）** 与 fixupPass 两两交换（:1977-2000）修补；Boss 另有 SourcePhases 预算跑第二遍（:2240-2245）。
- **分配算法是轮转复用，不是置换**：sources[(sourceIndex++) % sources.Count]（:9903）。池比 target 短时同一源会被复用；singleton / forceGlobalUnique 用 taken 位用完即占（:9904-9913），重试上限耗尽直接 throw（:9918）。所以 target→source 单向、RevMapping 只是反查缓存，**无可逆性保证**。
- 随机流不是一个：seed+40 给魂量（:3035）、seed+(int)silo.Type 给每个 silo 独立流（:2057）；**唯一故意不喂 seed 的是竞技场落点（:2474）** —— 也就是说同一 seed 跑两次，竞技场地上的位置会不同，这点要在我们的复现性声明里写明。
- 可复现性来自三件事：seed + 固定遍历顺序 + 排序输出（spoiler 按 -entityId 排，:2406-2411）。

## §8 数值与演出：param 只装数值，演出全在 EMEVD

- **scaling 不碰 NpcParam**：批量生成 SpEffectParam 新行（ScalingBase 7000、新段 7800000、MaxTier 20/34、tier id 规则见 Enemy/ScalingEffects.cs:166-187），再用 EMEVD 公共函数 scale / scale2 在运行时挂到实体上（EnemyRandomizer.cs:8846-8863）。守恒断言：tier 数不符、维度不符、缺段都 throw（:221/:243/:627/:654）。
- **血条名**是 DisplayBossHealthBar 的第 4 个参数（FMG id）+ 槽位重排（:6710-6747、:5486-5517）；GetCleverName 分配**新 FMG id** 而不是原地改（:4813-4887，注释：phase 之间有重复引用）。
- **BGM** 走两条路：param 的 threatLv 置换（Shuffle(new Random(opt.Seed + 400))，EE:722-755，只碰 !HasPerceptiveNose 的 Boss），或 BossBgmArg "<defeat flag> <boss bgm id>" 就地改 init（:7477-7496）。
- **出场动画**改 init 的 anim 参数（:7454-7472；目标不是 arena primary 就不覆盖）。
- **事件补丁是声明式的**：events.txt 里 1,221 条逐实体补丁，每条带 **CondIdentity = IfEventFlag(ON, <StartFlag>) 守卫** —— 只有那个位置**仍是原敌人**时补丁才生效。这是「事件不被套到换过的对象上」的机制，比我们在代码里拼 EMEVD 强一个数量级。

## §9 可观测性与失败处理

- **spoiler log 先于改动生成**（:2319-2443），按 silo 分组打印 Replacing <目标 in 地点>: <源 from 地点>（+可选 scaling a->b），空组打印 (not randomized)。
- **Missing enemy 是一等公民状态**：登记 missingInfos + 打印（:875-880）→ 统一降级 Class = None（:1157-1162）；若仍被当 source/target 使用，直接 throw（:1565/:1597）。非重要自动降级，重要必须人显式移除。
- **文案级改写匹配不到就上报**：把「哪条 init、因为谁被处理、哪些编辑没落地」收集成清单（:8448-8465、:8578-8585）；modifiedEvents 非空即 throw（:8573-8576）。**ok 表示确认落地，不是「API 没抛异常」** —— 这正是我们 native_deploy 无条件写 ok: True 的反面。
- **没有「部分失败」的返回结构**：要么打印后继续，要么 throw 中止。主流程无 try/catch。

## §10 选项面与 seed

- 选项是两个有序字典（SortedDictionary，RandomizerOptions.cs:70-71），解析无白名单（拼错静默生效，:201-205），但因为有序，同一组选项无论输入顺序都产出同一个串；ConfigHash 取 5 位短标识（:511）。
- **两个 seed 必须分开**：opt.Seed 是放置流的唯一来源（Randomizer.cs:172/:493/:499）；trueSeed = JavaStringHash(LogicString + && + preset.ToStableString()) 只喂 CharacterWriter（:436/:519）。所以改 logic 选项不动放置 RNG，却会改角色数据。
- logicless 十二项（:445-450）含 uxm / mergemods / mergegame：不进 seed、不动逻辑，但改输出根与写集。
- ToStableString（EnemyPreset.cs:308-390）：拆 → 小写 → 去重 → InvariantCulture 排序，类内 | 类间 ||，**故意不记 InheritParent** —— 得到的是「语义等价串」。

## §11 六条设计支柱（要抄的是这六条，不是算法）

1. **只读基线 + 另起输出树 + 未写文件清理**（§2）—— 治「一半变了」。
2. **先决后写两段式**（§5）—— 分配只在内存，spoiler 先出，再一次性应用；方案层就是 Mapping。
3. **身份只有一个写入点，param 行只复制不就地改**（§6）—— 治双写错位。
4. **语义全在数据表，代码只派生布尔**（§4）—— 治 Boss 池毒化。
5. **映射桶化 (Class, Area) + 可放置性前置**（§7）—— 治「换了但放不下/放错地方」。
6. **fail loudly：确认落地才算 ok**（§9）—— 治「代码说成功、游戏里没变」。

## §12 对我们六条争议的判词

| 我们的争议（docs/敌人随机_重制交底.md §4） | 参考实现的证据 | 结论 |
|---|---|---|
| ① 最终 Boss（拉达冈 / 艾尔登之兽）动不动 | enemy.txt:16995-17020：Radagon（19000810）与 Elden Beast（19000800）都写 Class: Boss，且**没有 norandom 标签**；代码里没有任何硬编码的「不随机最终 Boss」，只有实体 id 预留（:205-210）。「不动」只可能来自预设层（preset NoRandom / merge.NorandomEntities / tag norandom） | **默认会随机**。我们把它做成**选项**（默认关 = 保留原样），既符合参考实现的机制分层，也照顾我们的口味 |
| ② Boss 池到底多大（170/845/213/218，我们的 boss_rows.csv 实测 337） | AllBosses 218 = 六个类之和（52+79+41+21+15+10）；BaseAllBosses 174；DLC 44；Count 是**写死在表里自校验**的 | 池 = **218 个 Boss 类 place**（本体 174）。我们 337 是「有名字的 Boss 出现位置」超集（去重实体 233），**口径不同不可直接比**；重做时以 218 为基线并给出自己的对照表 |
| ③ 覆盖率分母（实体 vs 行） | 他的分母是 enemy.txt 的**实体标注条数**（23,173 = place 级），Boss 子集 218；NpcParam 行（7,823）根本不是分母 | 分母 = **place 数**。报覆盖率必须写清「place / 去重实体 / NpcParam 行」三者中哪一个 |
| ④ unkillable 是 9 还是 174 | Groups 里 unkillable = **6 个模型名**（Lightning Ball / Eagle / Owl / Guillemot / Aging Untouchable）；它是「危害物」集合，不是 Boss 属性。而 Radagon 这种正经 Boss 身上反而带 exclude:unkillable 标签（= 别被换成一个危害物） | 两种数法都错。unkillable 是**模型组**（危害物），不是 Boss 池过滤器；Boss 池只看 Class |
| ⑤ 地图数口径（845/803/634/484） | enemy.txt 里 distinct map = **483**；输出清理遍历的是「磁盘上可能存在的全部 map」，与有敌人的图不是同一个数 | 报「有敌人标注的图」用 **483**；清理动作另有自己的枚举范围。两者必须分别命名 |
| ⑥ isSoulGetByBoss 算不算 Boss 证据 | 它出现在**必改清单**里，取值改为 0（EnemyRandomizer.cs:3110），理由是「防止小怪掉 Boss 魂」 | **它不是证据，是一个要归零的字段**。Boss 认定只看 Class / preset / norandom |

## §13 映射到我们这边（方案层 + YAFSML）

我们的落点与参考实现一一对应，能对上的都是「可以照抄」，对不上的要自己补：

| 参考实现 | 我们这边 | 备注 |
|---|---|---|
| outPath 独立于游戏目录 + 未写文件删除/复原 | 方案层 方案/<label>/mod/ + YAFSML.ini 的 Plan= | **方案层就是我们的输出树**；但必须显式列出「本次写哪些文件」，并在换方案时清掉旧层 |
| 只读基线 {Dir}/Vanilla/regulation.bin | 游戏本体 regulation.bin（只读）+ 已有 .orig_ 备份 | 我们已有 4 份真原始备份，别动 |
| 脏集合 WriteMSBs / WriteEmevds | Plan 条目 + 我们自己的写集清单 | 每个写批必须回吐 written[] |
| silo.Mapping（内存决议） | plan 文件（target→source 全表 + id 分配表） | 落成文件后可指纹比对，第二次跑应报「已应用过」 |
| TransplantEnemy 单一写入点 | enemy_swapper + msb_write 的外观链 | 现状：外观与数值两条链都能改身份 → 必须收敛成一处 |
| NpcParam 只复制新行 | apply_plan（现在会就地改） | 改成「复制到第一个空位再改」，并维护 id 分配表 |
| enemy.txt 分类学 | 我们的 enemy_type_map.csv / enemy_ref.csv / boss_rows.csv | 语义要挪进数据表并自校验（Count 写死） |
| events.txt 声明式补丁 + CondIdentity 守卫 | enemy_emevd.patch_evd_bytes | 学 CondIdentity：只有「该位置仍是原敌人」才打补丁 |
| RuntimeParamChecker | 我们的五道自检 + 部署后对账 | 退化为离线对账：生成物 ↔ param 行 ↔ Models/parts 集合逐项核 |
| spoiler log | GUI 的「本次替换表」 | **先于写入**生成，可导出 |

**v1 建议范围（只做一件事做到底）**：身份 / 外观（外观链 + 单一写入点 + plan 落文件 + 写集与负向账本 + 对账闸门）。数值、血条名、BGM、scaling、地图覆盖各自独立成版 —— 这正是我们上次「一次铺满八件事」的教训。

## §14 数字口径对齐表（重做时直接用这张表说话）

| 量 | 我们现在的数 | 参考实现 | 说明 |
|---|---|---|---|
| 敌人 place 总数 | map_enemies.csv 27,780 行 | enemy.txt 23,173 条 | 我们的表含无标注实体；需要交集口径 |
| NpcParam 行 | enemy_table.csv 7,823 | 同一份 regulation（paramdef 驱动） | 参考实现不拿它当分母 |
| Boss place | boss_rows.csv 337（去重实体 233，模型 139，图 169） | AllBosses 218 / Base 174 / DLC 44 | 口径差 +119；参考实现全 Boss 都在 regulation 里（我们 337 也全是 in_regulation=True） |
| 地图数 | 845/803/634/484 四种说法 | 有敌人标注 483 | 见 §12⑤ |
| unkillable | 9 或 174 | 6 个模型的组 | 见 §12④ |
| 血条行 | boss_healthbar.csv 332 | 表字段 HealthbarIndex + EMEVD 参数 | 我们 332 与 337 差 5，需要解释 |

## §15 我们不照搬的四件事

1. **轮转复用 + 事后 fixupPass**（§7）：让「同一源被复用到多个目标」变成常态，且「为什么这个位置变成这个敌人」只能靠 spoiler 反推。我们改成 **per-area 真置换（源用一次即消耗）+ 可放置性前移到抽样时**，失败就明确记「该槽保留原样」。
2. **无原子性写入**（§2）：我们改成临时目录 + 成功后整体替换。
3. **C# 独占的强类型写回**（SoulsFormats 的 Write()）：我们只能读→改→整文件写回，所以**写完必须回读校验（能重新解析）**。
4. **34 级手工 scaling 矩阵**：Convergence 数值体系不同，只搬机制与字段名，数值必须由元数据生成。

我们的条件更好的地方：有 GUI（能在执行前列出将写的文件 + 与上一轮 diff + 一键复原）、有 plan 落文件（可指纹、可重放）、有 Python（能做真对账）、只做一部作品（砍掉四分之三的分支）、有 codegraph（字段谁写过可查）。

## §16 证据与缺口

- 三份逐行报告：A（264 行）/ B（378 行）/ C（326 行），在 docs/参考实现_拆解/。
- 已核实到行的事实：§2 全部、§3 全部、§6/§7/§8/§9 关键行号。
- 仍未读透（报告里都标了）：RunGame :5399 之后的事件主循环、WriteEmevds 的填充点、EnemyAnnotations 的 tag 判定正文、Enemies.cs 与 EnemyPlacement.cs、.rpreset 扩展名约定、EldenForm 的 GUI 布局。
- 判定为「不构成依据」的：EMEVD / 血条 / isSoulGetByBoss 用于判断 Boss（§4、§12⑥）。
