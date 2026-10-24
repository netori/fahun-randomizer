# 参考实现拆解 B：敌人写入与 ER 专属机制

> 对象：thefifthmatt/SoulsRandomizers（只读检出）。**本文所有路径都相对参考仓库根目录**，例如 `RandomizerCommon/Enemy/EnemyRandomizer.cs:3374`。
> 目的：给「敌人随机重制」提供设计依据，尤其是我们连做两轮都失败的那个形态——**写入端全报 ok、玩家看到「一半变了」**。

## 0 读法与证据边界

已读（分段全文/近全文）：

| 文件 | 覆盖 |
|---|---|
| `RandomizerCommon/Elden/EldenEnemyEditor.cs` | 全文（1162 行，分段） |
| `RandomizerCommon/Enemy/NpcEdits.cs` `RandomizerCommon/Enemy/EnemyEditor.cs` `RandomizerCommon/Enemy/EnemyState.cs` `RandomizerCommon/Enemy/EnemyMapping.cs` `RandomizerCommon/Enemy/EnemyPermutation.cs` | 全文 |
| `RandomizerCommon/Enemy/EventConfig.cs` | 全文 |
| `RandomizerCommon/Enemy/ScalingEffects.cs` | 全文（1-780） |
| `RandomizerCommon/Enemy/EnemyRandomizer.cs` | 分段：1620-1745、1955-2045、3020-3320、3326-3914、4813-4888、5486-5546、6600-6790、7430-7520、7860-8130、8430-8490、8830-8930、9740-9780 |
| `RandomizerCommon/Core/GameData.cs` | SaveEldenRing 1134-1360、1518-1596、2090-2160 |
| `RandomizerCommon/Core/RuntimeParamChecker.cs` | 1-200 |

**未读、不作为依据**：`Enemy/Enemies.cs`、`Enemy/EnemyPlacement.cs`、`Enemy/EnemyAnnotations.cs` 的 tag 定义正文（只按使用点引用 tag 名，不解释其含义）、`EnemyRandomizer.cs` 其余约 5500 行。凡本文写「不确定」处即为证据缺口。

---

## 1 「每次随机改动了哪些文件」——输出管线的第一性答案

ER 的一次随机在 `Core/GameData.cs:1134` `SaveEldenRing` 里落盘，顺序固定、集合驱动：

| 顺序 | 写成什么 | 目标路径 | 谁决定写 | 出处 |
|---|---|---|---|---|
| 0 | 运行时自检参数（会**改 NpcParam**） | 见右 | 无条件 | `Core/GameData.cs:1143-1145` → `Core/RuntimeParamChecker.cs:72-161` |
| 1 | `regulation.bin`（全部 PARAM） | `{outPath}\regulation.bin` | 无条件 | `Core/GameData.cs:1152-1185` |
| 2 | EMEVD 事件脚本 | `{outPath}\event\{map}.emevd.dcx` | `WriteEmevds` 含该 map | `Core/GameData.cs:1204-1237` |
| 3 | Hoarah Loux 独立 SFX（纯拷贝） | `{outPath}\sfx\sfxbnd_c4721.ffxbnd.dcx` | 源文件存在 | `Core/GameData.cs:1239-1248` |
| 4 | FMG 文本 | `{outPath}\msg\{lang}\{type}_dlc02.msgbnd.dcx` | `WriteFMGs` | `Core/GameData.cs:1250-1279` |
| 5 | ESD 对话 | `{outPath}\script\talk\{key}.talkesdbnd.dcx` | `WriteESDs` 含该 key | `Core/GameData.cs:1281-1298` |
| 6 | MSB 地图 | `{outPath}\map\mapstudio\{map}.msb.dcx` | `WriteMSBs` 含该 map | `Core/GameData.cs:1301-1327` |

三条铁律（这才是「不会一半变了」的根因）：

1. **输入永远是 Vanilla 基线**：`string basePath = $@"{Dir}\Vanilla\regulation.bin"`（`Core/GameData.cs:1153`、`1304`、`1258`、`1292`），mod 层用 `Mods.Resolve` 顶掉基线（`1155-1158`、`1293-1296`、`1259-1262`）。随机器**不读上一轮输出**。
2. **输出是整包重写，不是增量打补丁**：`Editor.OverrideBndRel(basePath, path, Params.Inner, f => f.Write(), …)`（`Core/GameData.cs:1177`）、`entry.Value.Write(path, overrideDcx)`（`1223`）、`msb.Write(path, overrideDcx)`（`1321`）。参数文件即使在 2.3 MB 上限下也只换压缩（换 Oodle，`1178-1183`），不换「只写差量」的思路。
3. **没写的文件会被删掉或复原**：`AddBackupOrRestoreFile(path, write, uxm)`——`write==true` 记账并备份；否则有 `.randobak` 就 `RestoreBackup`，没有就 `File.Delete(path)`（`Core/GameData.cs:1518-1538`）。遍历范围还刻意包含**未加载的 DLC 地图**：「Include maps which are not loaded, like DLC maps, in case past randomizations had them」（`1332-1337`）——就是为了清掉上一轮的残留。

配套的三个细节：

- **地图孪生（MapDupes）**：同一份地图数据对应两个 map 名时只写一份，另一份靠 `File.Copy` 补（`1189-1202`、`1323-1326`）。
- **选项字符串当版本戳**：EMEVD 末尾追加 `optionsByte`（`Core/GameData.cs:1222`），MSB 里加一条 `Events.Navmeshes` 记 `optionsStr`（`1316-1320`），参数里塞进 `CutSceneTextureLoadParam` 的 777777771..777777774 行（`1162-1175`）。目的是**能判断玩家手上这份产物是哪一轮生成的**。
- 全部地图写盘是 `Parallel.ForEach` 并行（`1338-1347`）。

> 对照我们的故障：在参考实现的架构里，「写入端全 ok 但玩家看到一半变了」这个状态**几乎不可能出现**。要么整包重写完（那么每一张被 `@WriteMSBs` 收进来的 map 都是新的），要么某一步 `throw`。上一轮残留会被删除/复原，而不是静静留着。

---

## 2 §① 换敌人时，MSB `Part.Enemy` 到底改了哪些字段

### 2.1 就地替换（`Elden/EldenEnemyEditor.cs:69-85` `TransplantEnemy`）

| 字段 | 写成 | 出处 | 漏写/写错的玩家可见症状 |
|---|---|---|---|
| `ModelName` | `source.Model` | `Elden/EldenEnemyEditor.cs:72` | 模型不变，只有数值变了（「看着还是原来那只」） |
| `NPCParamID` | `source.NPC` | `:73` | 血量/防御/掉落全是原 boss 的 |
| `ThinkParamID` | `source.Think` | `:74` | AI 行为是原敌人的 |
| `CharaInitID` | `source.Char` | `:75` | 人形敌人的装备/模型部件不对 |
| `BackupEventAnimID` | `-1` | `:79`（注释 `:76-78`） | 事件播放入场动画时按旧 id 走位（注释：**不能**沿用 `source.Anim`，有些敌人在地下，例：Leyndell 小神谕使者 #11000204 住在 `Grave Skeleton` 里） |
| `UnkT15` | `false` | `:81`（注释 `:80`） | Bell Bearing Hunter 一类会「隐身」（注释点名） |

注释同时说明：敌方 part 上的 speffects（`UnkT40` 等）是**故意保留**的——「mostly fun to keep」，例外统一在 `EnemyRandomizer` 里处理（`Elden/EldenEnemyEditor.cs:82-83`）。

### 2.2 新建 part（helper / 分裂 / dupe，`Elden/EldenEnemyEditor.cs:93-126` `CloneEnemy`）额外改

| 字段 | 写成 | 出处 | 备注 |
|---|---|---|---|
| `Name` | `{prefix}{ModelName}_{newPartId:d4}` | `:106`（prefix 拼法 `:101-105`） | `prefix` 取原 part 名里 `m` 开头含 `-` 的前缀（ER 的 `m6*0` 事件图要求 part 名带 map 前缀，见 §4） |
| `EntityID` | `newTarget` | `:100` | |
| `Unk08` | `newPartId` | `:108`（注释 `:107`） | 注释：`Needed to avoid sudden deaths` |
| `TalkID` | `0` | `:110`（注释 `:109`） | 注释：`Transplanting talks seems to break most talk scripts` |
| `PlatoonInfo.GroupPartsNames` | 补空槽 | `:112-124` | 只对 `c4600`/`c4602`/`c3150`（商队巨魔、雪原夜之骑兵） |

### 2.3 不在 `TransplantEnemy` 里、但**必须同批发生**的四类写入

这是最容易做出「半换」的地方——它们的调用点都在主循环里，和 transplant 是分开的两步：

| 步骤 | 做什么 | 出处 | 漏了会怎样 |
|---|---|---|---|
| 模型登记 | 把 `ModelName` 登记进 `msb.Models.Enemies`（`SibPath = N:\GR\data\Model\chr\{name}\sib\{name}.sib`） | `Elden/EldenEnemyEditor.cs:41-67`；调用 `EnemyRandomizer.cs:3727`；`Enemy/EnemyEditor.cs:140-148`（`UseModel` 只在**未声明时**加） | 现代引擎不会自动定义模型；不登记就没有 SIB 可加载 |
| 组 ID | `EntityGroupIDs` 清空 + 按 `groupMapping` 重填；槽满 throw | `Elden/EldenEnemyEditor.cs:178-187`；`Enemy/EnemyEditor.cs:96-129` | 旧团伙残留：老 id 的事件还在驱动新敌人 |
| 碰撞体 | `CollisionPartName` | `Elden/EldenEnemyEditor.cs:173-176`；调用 `EnemyRandomizer.cs:3608-3613` | 卡墙/浮空/穿地 |
| 位置朝向 | `Position`/`Rotation`（arena、places、dupe offset、大量硬编码 id 特例） | `EnemyRandomizer.cs:3479-3605` | 敌人出现在墙里/落进虚空 |

另外两条一次性改写：`ignoresp` 标签或 (`source==19000800` && Evergaol) 时把 `SpEffectSetParamID[0]=0`（`EnemyRandomizer.cs:3629-3638`）；`SetColName` 时同时回写 `defaultData[target].Col`（`:3613`），保证后续步骤看到的是新值——**内存里的「当前状态」也跟着改**，不是只改盘上的。

---

## 3 §② 参数侧：复制新行还是复用？这解决了「同一份 plan 被写两次」吗

### 3.1 一律复制新行，从不原地改别人的行

三种入口，全部是「整行 `CopyRow` + 分配空位 id」（`Enemy/NpcEdits.cs:92-123`）：

| 方法 | 对象 | 新 id 怎么来 |
|---|---|---|
| `DuplicateAdjacentRow(paramName, baseId)` | 任意 PARAM | `copyId = baseId; while (existingIds.Contains(copyId)) copyId++;` → `game.AddRow` + `GameEditor.CopyRow`（`:92-106`） |
| `DuplicateAdjacentThink(baseId)` | `NpcThinkParam` | 同上（`:108`） |
| `DuplicateAdjacentNpc(baseId)` | `NpcParam` | 同上，并写进 `Npcs` 缓存（`:111-123`） |

基线行不存在直接抛：`{paramName} {baseId} is referenced but does not exist`（`:99`、`:115`）。

**关键设计后果**：复制 = 整行照抄，所以「keep 哪些字段」是**默认行为**，代码里只需要列「必须改哪些」。这正是我们最容易反过来的地方（我们习惯列白名单，一升级就漏字段）。

### 3.2 「必须改」的清单（ER）

| 字段 | 改成 | 为什么 | 出处 |
|---|---|---|---|
| `getSoul` | 重算（1200-1600 基础，Boss ×2，按 tier 乘 `EldenSoulScaling`，helper /5） | boss 变杂兵/杂兵变 boss 的魂量 | `EnemyRandomizer.cs:3067-3089` |
| `disableInitializeDead` | `0`（boss→杂兵）/ `1`（杂兵→boss） | 决定是否需要事件唤醒 | `:3095`、`:3185` |
| `disableRespawn` | `0` | | `:3096` |
| `isSoulGetByBoss` | `0` | 防止小怪掉「boss 魂」 | `:3110` |
| `threatLv` | 为 0 时置 1 | ER 用它决定 boss 音乐/血条行为 | `:3106-3109` |
| `nose_dist`/`eye_dist` | 夹到 `min(…,5)`/`min(…,30)` | 野外的 boss 会满地图追人 | `:3120-3126`（复制出来的 `NpcThinkParam`） |
| `basicBuffFields` = `getSoul`/`hp` | 取 `sqrt(source*target)` 的几何平均（只在目标更大时） | boss 变杂兵别太软 | `:3132-3174`；类型不认识就 throw `Unknown NpcParam field type`（`:3173`） |
| `hp` / 二阶段血量 | 手工按对重分配，夹在 `(500,5000)` | 一/二阶段血量失衡 | `Elden/EldenEnemyEditor.cs:961-1018` |
| `teamType` | `6`（先记 `NpcOriginalTeam`） | transferTeams | `Elden/EldenEnemyEditor.cs:641-645` |
| `dlcGameClearSpEffectID` | `-1` | DLC 通关后才生效的 speffect 会误触发 | `:701` |
| `spEffectID0..31` 里的 `reduceDamageSps` | 剔除 `{20011664,20011665,20011666,20012710,20012711}` | 抗性/减伤 speffect 跨地域错配 | `:573-595` |
| `hitRadius`/`hitHeight` | `ShrinkNpc(row, 2.5f, 5.1f)`（跳过 52300596/52300496/52300196） | 大体积敌人塞进小空间 | `:687`；`Enemy/NpcEdits.cs:52-64` |

### 3.3 缓存，而不是「每次用到就再造一份」

- `bossAsBasicNpc`/`bossAsBasicThink`：**每个 source 只造一次**，字典记住 id（`EnemyRandomizer.cs:3034-3035`、写回 `:3112`/`:3125`）。
- 明确的反例（作者自己承认）：`getBasicAsBoss` 是「每次调用都新建一行」——`// Just make a new row every time`（`:3145-3146`）。也就是说**他并没有做幂等**，只是让重复调用产出「没人引用的垃圾行」而不是错误。

### 3.4 所以：这解决「同一份 plan 写两次」了吗

**没有正面解决，是绕开了。** 他的幂等性有三层外援，都不在参数层：

1. **置换只算一次**：`EnemyPermutation` 是一份内存结构，`EnemySilo.Mapping` 注释写死方向「Mapping from target to source」（`Enemy/EnemyPermutation.cs:59-60`），主循环按 map 遍历、每个 part 只命中一次（`EnemyRandomizer.cs:3326-3342`）。
2. **每次运行都从 Vanilla 重算、整包重写**（§1 铁律 1、2）。
3. **没写的文件被删/复原**（§1 铁律 3）。

推论（对我们直接有用）：参考实现的产物是「这一轮从头生成的完整包」，不存在「在上一轮结果上再改一次」的路径。我们如果是在已改过的文件上跑第二轮，**必然**会得到「一半变了」——因为第二轮看到的不是 Vanilla。这不是随机算法的问题，是输入基线的问题。

---

## 4 §③ 多阶段 Boss：顺序与一致性怎么保

| 环节 | 机制 | 出处 |
|---|---|---|
| 阶段登记 | `info.NextPhase>0` → `multiPhase[ID]=NextPhase` 且 `multiPhase[NextPhase]=NextPhase`；`DupeFrom` 继承原 next | `EnemyRandomizer.cs:1620-1650` |
| 放置约束 | 阶段的「总血量/阶段数」不许凭空膨胀：`sourcePhases > targetPhases+1` 直接拒绝；只有「省下的阶段足够多」时才放行（`prevLimits.Amount > targetPhases+2.1f && … -1.6f` 这类手调阈值） | `:1957-1973`；`fixupPass` 用两两交换修（`:1977-2000`）；`BossPhaseLimit{Entity,Amount}`（`:9757-9761`） |
| 事件契约 | 每种 Boss 必须提供指定段：`All bosses must provide: 1. dead or disable 2. setup/altsetup/secondsetup 4. start or quickstart 5. end or endphase`；`All bosses providing presetup must provide first/second setup/start` | `Enemy/EventConfig.cs:225-239` |
| 血条槽位 | `getHealthbarIndex(source,target,dupeIndex)`：把每个 source 的 `HealthbarIndex` 按 dupe 顺序累加；总数超 `maxHealthbars` 时只留主目标（返回 -1 = 这条指令不写） | `EnemyRandomizer.cs:5486-5517`；重写点在 `6742-6747`、`8013-8030` |
| 死亡 flag | `DefeatFlag`/`EndCond`/`EndCond2` 走段替换（`replaceCond`）；同一 defeat flag 决定 BGM 覆盖 | `EnemyRandomizer.cs:7477-7496`、`8415-8445` |
| 阶段血量 | 一/二阶段按对重分配（Hoarah Loux / Maliketh / Fire Giant / Messmer / PCR），并夹 `(500,5000)` | `Elden/EldenEnemyEditor.cs:961-1018` |
| 阶段缩放 | 阶段敌人大/小明暗处理成两个 speffect：`PhaseUpScaling=1.4f`、`PhaseDownScaling=0.7f` | `Enemy/ScalingEffects.cs:731-751`、挂载点 `EnemyRandomizer.cs:8903-8921` |
| 复制品的阶段 speffect | `getDupeSpEffect = 6095000 + dupeIndex*2 + (start?0:1)`；dupeIndex==-1 直接 throw | `EnemyRandomizer.cs:5518-5523` |

一句话：**阶段一致性不是靠参数对齐，是靠 EMEVD 段契约 + 放置期阶段预算**。参数侧只负责「血够不够」。

---

## 5 §④ helper / multichar / BuddyGroup / perceptor

### 5.1 helper 什么时候会被加出来

主替换循环 `EnemyRandomizer.cs:3729-3855`：

`owners.TryGetValue(source)` 取出 source 的 helpers，然后两道闸：

1. `if (!targetMultichr && !infos[helper].HasTag("alwayschr")) continue;`（`:3734`）
2. `if (infos[helper].Class != EnemyClass.Helper) continue;`（`:3735`）

过关后：换源（`silo.SwapMapping`，`:3738-3742`）→ 取稳定目标 id（`mapping.HelperMapping`，没有就 `newEntity()`，注释强调 dupe 时映射**必须稳定**，`:3744-3748`）→ `CloneEnemy(…, helperModelBase++)`（`:3749`，`helperModelBase=100` 见 `:3196`）→ `ClearGroups`（`:3750`）→ 位置 → 模型登记 → 记账 → `CopyGroups` → 跨图搬事件 `CopyAssociations`（`:3827-3840`）。

位置策略（这是「helper 加出来会不会打架」的核心）：

| 标签/条件 | 位置 | 出处 |
|---|---|---|
| `primary` | 贴着主敌 `e2.Position = e.Position` | `:3762-3768` |
| 有 arena | `randomSafePoint(arena, ArenaExcludeData, e.Position)`（Sekiro 额外 `extraHeight 0.5f`） | `:3769-3778` |
| 有预计算落点 | `places.GetEntry(placeTarget, helper)` | `:3779-3787` |
| dupe | 源 helper 位置 + `getDupeOffset` | `:3794-3805` |
| `angel` | `extraHeight = angelHeight` | `:3806-3809` |
| `ballista` | `moveInDirection(e2.Position, e2.Rotation, -1.5f)` | `:3814-3818` |

### 5.2 multichar 开关与那张硬编码表

`enableMultichr(source,target)`（`EnemyRandomizer.cs:3249-3307`）——ER 分支：

- 重要目标（有名有姓的 Boss 位）→ 允许（`:3292`）
- `bossonlymulti` → 拒绝（`:3293`）
- `mariner` → 每个 source 最多 20（`:3295`）
- **`eldenHelperBosses` 表 → 上限 `eldenMulti = opt["dlc"] ? 100 : 50`**（`:3248`、`:3297`）
- Groups 非空且全局 `requiredGroups>500` → 按 `target.GetHashCode() % requiredGroups < 500` 抽签（`:3301-3304`）

表本身（`:3219-3246`，11 个 + 1 个被注释掉的）：

`1400080` Rennala 2、`15000800` Malenia、`32110800` Yelough Astel、`21010800` Messmer 2（TODO 应部分启用）、`25000800` Metyr、`41020800` Lamenter、`2048380850` Cerulean Ghostflame Dragon、`2051450720` Count Ymir、`2052430800` Jori、`20010800` PCR、`1052385800` 基础游戏 Radahn（NPC 不需要）；注释里 `Scadutree Avatar 2050480800, currently difficult to make partial`。

**为什么会有这张表（作者自述 + 物理约束）**：

- 表头注释直说 `TODO: Any way to automate these? Helper count? Amounts are made up. Also based on map density, maybe`（`:3221-3222`）——**数字是拍的，不是推出来的**。这是「没有理论，只有实测上限」的诚实写法。
- 真正的物理原因在 `:3308-3320`：`partsNeeded` 统计所有 `npcpart` 标签的目标总数，超过阈值（ER **200**、DS3 96、其它 48）就 `partsRestricted = true`；注释原话「There can be no more than a handful of npc parts loaded at once locally」（`:3309-3311`）。
- 人形 Boss 的组合会爆模型槽：「Human bosses are an issue. Oops All Mimic Tear, Stray wouldn't work」（`:3299-3300`）。

### 5.3 Groups 不是 helper

`sourceInfo.Groups` 走的是另一条路（`:3429-3447`）：每个 group 分配一个 `newGroupEntity()`，写 `mapping.HelperMapping[(target,group)]`，并把 `ownerMap[group2]` 指到该 map 的 eventMap；不开 multichr 时直接映射到 target 自己。槽位不够就 throw（见 §7）。

### 5.4 BuddyGroup

- source 与 target 都有 `BuddyGroup` → 直接对齐：`groupMapping[srcBG] = tgtBG`（`:3448-3453`）。
- target 有 `BuddyGroup` 且 `NextPhase>0` → 复制一份 `groupMapping` 作为 `mainGroupMapping`，并把 `[0]` 换成 `targetInfo.BuddyGroup`（`:3454-3462`）。注释：`We really do need to make sure this happens`。

### 5.5 perceptor：证据不足

只能给三个使用点，**tag 的语义与阈值（`HasPerceptiveNose`/`HasTag("perceptive")`/`HasTag("sensitive")`）我没有读到定义**，因此不下结论：

- 放置期：`targetInfo.HasTag("sensitive") && sourceInfo.HasTag("perceptive")` → 拒绝放置（除非 source 是 fixed 且 target 自己鼻子的够灵）（`:1693-1701`）。
- 参数期：只有 `!targetInfo.HasPerceptiveNose` 时才用 `bossAsBasicThink` 替换 think（`:3394-3397`）。
- 威胁等级：`IsImportantTarget && sourceInfo.HasPerceptiveNose` 且源 `threatLv<=1` 时才记 `npcThreatTargets`（`:3406-3413`）。
- 另有一处**被停用**的收缩分支：`if (false && …) exclude:perceptive …`（`:3686-3689`）——看起来是曾经想「对敏感敌人不缩放」，后来关掉了。**不确定**关掉的原因。
- 一个反直觉的用法（可迁移）：BGM 随机只碰 `!HasPerceptiveNose` 的 Boss，理由是「鼻子范围无限等价于手动指定 BGM」——`perceptive` 实际上被当成「这只敌人的战斗音乐由事件决定、不是由 param 决定」的代理判据（`Elden/EldenEnemyEditor.cs:722-726`）。

不确定（缺什么证据）：`Enemy/EnemyAnnotations.cs` 里 `HasPerceptiveNose` 的定义、以及 perceptor 相关 part 在 MSB 里怎么被改。

---

## 6 §⑤ scaling 落到哪些 param 字段

**结论：不改 NpcParam 的数值，而是批量造 `SpEffectParam` 新行，再用 EMEVD 在运行时挂上去。** NpcParam 里唯一被读的字段是 `spEffectID3`（用来**推断**原 tier，不是用来写缩放）。

### 6.1 缩放矩阵的维度 → 落到哪些字段（ER，`Enemy/ScalingEffects.cs:176-186`）

| 维度键 | 写入的 SpEffectParam 字段 |
|---|---|
| `health` | `maxHpRate` |
| `stamina` | `maxStaminaRate` |
| `staminadamage` | `staminaAttackRate` |
| `damage` | `physicsAttackPowerRate`, `magicAttackPowerRate`, `fireAttackPowerRate`, `thunderAttackPowerRate`, `darkAttackPowerRate` |
| `damagerate` | `physicsAttackRate`, `magicAttackRate`, `fireAttackRate`, `thunderAttackRate`, `darkAttackRate` |
| `defense` | `physicsDiffenceRate`, `magicDiffenceRate`, `fireDiffenceRate`, `thunderDiffenceRate`, `darkDiffenceRate`（字段名拼写就是 `Diffence`，照抄） |
| `buildup` | `registPoizonChangeRate`, `registDiseaseChangeRate`, `registBloodChangeRate`, `registFreezeChangeRate`, `registSleepChangeRate`, `registMadnessChangeRate` |
| `xp` | `haveSoulRate`（ER 实际用 `EldenSoulScaling` 手写曲线替换，`:457-458`、`:578-586`） |

### 6.2 常量与 tier 定义（全是硬事实）

| 项 | 值 | 出处 |
|---|---|---|
| `ScalingBase` | `7000` | `Enemy/ScalingEffects.cs:168` |
| `NewScalingBase` | `7800000`（注释：`7910 only allows for 90, we need ~150`；以前是 77700） | `:169-171` |
| `MaxTier` | `34` | `:172` |
| 本体 tier 的 speffect id | `7000 + 10*i`（i=1..20），人形对应 `19350 + i` | `:355-364` |
| DLC tier | `20007000 + 10*(i-21)`（i=21..34）；人形 `+200` 但「完全不一致」故忽略 | `:365-372` |
| 无缩放并入 tier 1 | `speffectTiers[7000] = 1` | `:381` |
| 生成的段对 | 所有 `(j,i)` 且 `j<i`，共 34*33/2 = 561 段 | `:383-390` |
| 每段生成几行 | 2 行（Fixed/Regular）+ 2 行（Unique）——`UniqueScalingMatrix` 最终被指回 `ScalingMatrix`（`:481-482`），实际等价 | `:676-689` |
| 复制品缩放 | `bossDupeScaling = Enumerable.Range(2,4).Select(c => Math.Sqrt(1.0/c))`（2x/3x/4x/5x → 0.7071/0.5774/0.5/0.4472） | `:759` |
| 阶段 | `phaseDown = 0.7f`、`phaseUp = 1.4f` | `:745-746` |
| Boss→杂兵 | `0.25f`（health 与 xp） | `:705-715` |
| Rykard 野外版 | `0.2f` | `:747` |
| 教程 Boss | `0.75f` / down `1/2f` / up `2f` | `:695-703`、`:748-749` |
| DLC 段的伤害阻尼 | `dampen = 1.0/Math.Pow(1.5, 1.0/15)`、`factor /= 1.5`（i==21 处硬切，注释给了一串实测比值） | `:428-440` |

### 6.3 tier 从哪来、怎么挂

1. **推断**：`NpcParam.spEffectID3` → tier（`:487-517`）；没有就按「同 map 最常见 speffect」补（`:518-540`）；再被 `manualEntityTiers` 覆盖（`:541-571`，ER 现在整张表都注释空了）。
2. **挂载**：`addCommonFuncInit(scaleEvent, target, new List<object> { target, scaleSp })`，`scaleEvent` 是 EMEVD 里的公共函数名 `scale`/`scale2`（ER：helper、重要目标、或生成物用 `scale2`）（`EnemyRandomizer.cs:8845-8863`）。同一 target 可叠加多条：`TutorialScaling`、`TutorialUp/DownScaling`、`BossAsBasicScaling`、`RykardScaling`、`PhaseUp/DownScaling`（`8864-8921`）。
3. **守恒断言**：找到的 tier 数必须等于 `MaxTier`，否则 `Error: expected to find {MaxTier} scaling tiers between {AutoScaleStart} and {AutoScaleEnd}, found {baseTier}`（`Enemy/ScalingEffects.cs:241-244`）；矩阵维度/段对不齐 → `Internal error: bad scaling values`（`:625-628`）；缺某一段 → `Internal error: no scaling values defined for section transfer {i}->{j}`（`:654`）。
4. 生成完 `game.Params["SpEffectParam"].Rows.Sort`（`:753`）——新 id 段（7.8M）落在文件尾部，排序是为了让 diff 可读。

> 对我们：**scaling 是一张「预生成的参数矩阵 + 运行时挂载」**，不是「逐行改敌人」。这一条直接决定数据量级：改 NpcParam 是 O(敌人数)，造矩阵是 O(34^2)。

---

## 7 §⑥ 血条名（FMG）/ BGM / 出场动画：为什么必须动 EMEVD

### 7.1 血条名：名字是 EMEVD 指令参数 + FMG 行，不是 param 字段

`DisplayBossHealthBar(Enabled, entity, slot, nameId)` 的第 4 个参数是条目 id（`EnemyRandomizer.cs:6710-6712` 解析 `cmdArgs[1..3]`）。所以改名 = 三件事同时做：

1. **分配新 FMG 行**（而不是原地改）：`GetCleverName`（`:4813-4887`）先按「同 FullName 就保留」短路（`:4822-4824`），否则按 `MainTemplate` 计算（`:4843-4846`），再过 `ann.CustomNames` 覆盖（`:4875-4879`）；最后**新 id**——注释直说 `// In-place replacement would be nice, but there are duplicate usages across phases / So select a new id`（`:4880-4882`）。
2. **改指令参数**：`data.Reloc[EventValue.NpcName(nameId)] = EventValue.NpcName(GetCleverName(targetNameId, nameSource, segTarget, true))`（`:6759-6760`），另在 `7989-8030` 走「就地读-改-写」路径。
3. **重排血条槽位**：`cmdArgs[2] = newNameSlot.ToString()`（`:6745`），槽位计算见 §4 的 `getHealthbarIndex`。

`t.Name` 的语法定义写死在配置结构里：`Replacing boss/miniboss health bar names. Either "entity" to refer to Entity, or "<entity> <name>" containing ints or arg refs`（`Enemy/EventConfig.cs:148-149`）；带 `X` 前缀表示不处理（`:7989` `!t.Name.StartsWith("X")`）。换源（swapboss）时还要重算名字 id（`:6748-6758`）。

**为什么不在 param 侧**：血条名不是 param 字段；param 里跟「boss 感」有关的只有 `threatLv`（决定音乐/血条行为，见 §3.2）和 `isSoulGetByBoss`。

### 7.2 BGM：两条路，都不是改 NpcParam 的显式字段

| 路 | 机制 | 出处 |
|---|---|---|
| param-based（`bossbgm` 选项） | 先圈出 `worldBossNpcs = IsImportantTarget && !HasPerceptiveNose` 的 NpcParam（注释：`having infinite nose range is equivalent to having manual BGM`，`Elden/EldenEnemyEditor.cs:722-726`）→ 收集 `threatLv>1` 到 `ThreatLvs`（`:732-736`）→ `Shuffle(new Random((int)opt.Seed + 400), npcs.ThreatLvs)` → 同一筛选条件下 `row["threatLv"].Value = newThreatLv`（`:738-755`，注释称这是 full permutation）—— **威胁等级互换，音乐随之互换** |
| event-based（`BossBgmArg`） | 配置语法 `<defeat flag> <boss bgm id>`（`Enemy/EventConfig.cs:117-118`），实现是就地改 init 参数：`init[init.Offset + bgmIdPos] = newBgmId`（`EnemyRandomizer.cs:7484-7495`），按 defeat flag 查 `assignedDefeatFlagBgmIds` | 同上 |
| 格式错 | `throw new Exception($"Internal error: badly formatted BossBgmArg {t.BossBgmArg} for {init}")`（要求两段都是 arg spec `c\d_`） | `:7479-7483` |

### 7.3 出场动画：也是 EMEVD init 参数

配置侧的语法树（`Enemy/EventConfig.cs:132-147`）：`Animation` 支持 `pose / wakeup / gravity / active / passive / suspend / suspendgravity` 等子键。实现（`EnemyRandomizer.cs:7454-7472`）：

- 取两个下标（`wakeup` 用 `{-1,2}`，其余 `{2,3}`），逐一把「原动画」换成 `anims != null && anims[a] > 0 ? anims[a] : -1`；
- 参数是 arg spec 就走 `init[init.Offset + animPos]`，是字面整数就走 `events.ReplaceMacro(edits, prevAnim, newAnim.ToString(), type: EventValueType.Animation)`；
- **目标必须支持这个动画**：如果目标不是 arena 的 `primary` 副本，就 `anims = null`（即不覆盖）（`:7433-7440`）；`gravityarg` 标签还带一个特例（`:7442-7452`）。

> 一句话：**ER 里「演出」全在 EMEVD，param 只装数值。** 我们若在 param 侧找血条名/音乐/动画，永远找不到。

---

## 8 §⑦ fail loudly：自检 / 断言 / 异常清单

| 层 | 断言 | 出处 |
|---|---|---|
| 参数复制 | 基线行不存在 → throw `{paramName} {baseId} is referenced but does not exist` | `Enemy/NpcEdits.cs:99`、`:115` |
| 组槽位 | 槽满 → throw `Ran out of group slots for {source.ID}. Want to add {addGroups} but stuck at {targetGroups}` | `Enemy/EnemyEditor.cs:125` |
| 事件图 | 缺 map → throw `Internal error: no event map for {target}` | `EnemyRandomizer.cs:3426` |
| 跨图移植 | 无碰撞 → throw `No collision defined for cross-map transplant …` | `:773` |
| 阶段配置 | 引用了不存在的 NextPhase → throw `Entity {info.ID} referencing {info.NextPhase} which does not exist in config` | `:945` |
| 字段类型 | 类型不在 `int/uint/short/ushort` → throw `Unknown NpcParam field type {field} {type}` | `:3173` |
| 配置格式 | `BossBgmArg` 格式错 → throw | `:7482` |
| 事件 id | 超限 → throw `Event {newId} hit event limit.` | `:91` |
| **未应用的编辑** | `edits.PendingEdits.Count != 0` 就逐条记录「哪条 init、因为谁被处理、哪些编辑没落地」，最后统一输出 | `:8448-8465`、`:8578-8580` |
| 缩放守恒 | tier 数/矩阵/段对不齐 → throw（§6.3） | `Enemy/ScalingEffects.cs:221/234/243/627/654` |
| Vanilla 基线 | 文件长度或 SHA1 不符 → throw `is not compatible with this version of randomizer` | `Core/GameData.cs:2111-2133` |
| 开发期防护 | DEBUG 下禁止覆盖 Vanilla：`Won't overwrite them in development build - delete the Vanilla directory` | `Core/GameData.cs:2090-2103` |
| 元数据顺序 | `EnemyState` 的 getter 未初始化就 throw（把「构建顺序」变成运行时约束） | `Enemy/EnemyState.cs:17/33/41/49` |
| **运行时自检（最狠的一条）** | 把两个随机选的 `SpEffectParam` id 塞进 `NpcParam.spEffectID4/5`，并在 `common.emevd` 注入事件：角色加载且带这两个 speffect 时弹框 `RestartMessageId=666400` | `Core/RuntimeParamChecker.cs:131-161`、`:163-200`（`AlertFlag = EldenRingBase + 2001`，`GameData.cs:1143`） |
| map 解析器 | `Entity {eventMap} {eventPart} missing map-specific name`（ER `m6*0` 的 part 名必须带 `-` 前缀） | `EnemyRandomizer.cs:712-720` |
| object 依赖 | `Required object {objId} not found by {ename(source)}` | `:3864` |

结构上的两个要点：

1. **失败不是「回滚」，是不产出**：任何断言命中都会让这次运行在写盘之前（或写盘过程中）中断，玩家拿不到半成品。
2. **「未应用的编辑」是一等公民**：EMEVD 的文本级改写（Reloc/Macro）可能匹配不到，他把「匹配不到」收集成清单打印（`:8448-8465`），而不是静默放过——这正好对应我们「写入端全报 ok」的病根：**ok 应该表示「我确认这条编辑落地了」，而不是「我调用完 API 没抛异常」**。

---

## 9 §可迁移性

### ① 可直接照抄的机制（我们照做就能对症）

1. **三段式输出纪律**：Vanilla 基线 → 整包重写 → 未写文件删除/复原（`Core/GameData.cs:1153`、`1213`、`1518-1538`）。这一条单独就能消灭「一半变了」。
2. **「写了哪些文件」是显式集合**（`WriteMSBs`/`WriteEmevds`/`WriteFMGs`/`WriteESDs`），遍历范围含未加载的 DLC 地图（`:1332-1337`）。
3. **所有 param 改动都是新行复制**，id 取「已有 id 的第一个空位」（`Enemy/NpcEdits.cs:92-106`）；keep 是默认行为，只列必改项。
4. **换敌人的字段清单**（§2.1 + §2.3）逐项落成代码，漏一项对应一种玩家可见症状——这张表可以直接当我们的验收清单。
5. **模型登记与 `ModelName` 同批**（`Enemy/EnemyEditor.cs:140-148`）。
6. **组 ID 用「清空 + 空槽重填」，槽满就抛**，不要贪心追加（`Enemy/EnemyEditor.cs:96-129`）。
7. **不删事件、只置空**：`Don't do removal of events, as this probably breaks some things. Instead, dummy things out`（`Elden/EldenEnemyEditor.cs:205-258`）。
8. **血条名 = FMG 新 id + EMEVD 参数改写 + 槽位重排**三件套（§7.1）。
9. **scaling = 预生成 speffect 矩阵 + 运行时挂载**（§6）。
10. **「未应用的编辑」当错误上报**（§8）。

### ② 依赖 C# / SoulsFormats / ModEngine，Python 侧照搬不了的部分

| 依赖 | 参考实现怎么用 | 我们的替代做法 |
|---|---|---|
| `SoulsFormats` 的 `MSBE/EMEVD/PARAM` 强类型 + `Write()` | 整包重写在类型层面是「一次 `Write`」（`Core/GameData.cs:1177/1223/1321`） | 走 YAFSML/WitchyBND 的读写；我们得自己做「读→改→整文件写回」而不是直接改字节区间；写完必须回读校验（parse 一遍） |
| `Mods.Resolve` / ModEngine 的目录叠加 | 基线在 Vanilla，mod 层顶掉（`1155-1158`） | 我们没有 mod 叠加层；需要自建「vanilla 快照目录 + 一份产物目录」，规则写死：只读快照、只写产物、跑前清产物 |
| `RuntimeParamChecker` 的运行时自检（EMEVD 注入弹框） | 需要能跑游戏内事件 | 退化为**离线对账**：把本次生成的 speffect id 集合 / 模型名集合 / part id 集合与 param 行集合、`Models.Enemies`、`Parts.Enemies` 逐项对账，缺一个就 fail |
| `Editor.OverrideBndRel` + `DCX` 压缩类型切换（`DCX_DFLT_11000_44_9` → 超 2.3 MB 换 `DCX_KRAK`，`1148`、`1178-1183`） | Oodle 压缩是闭源 DLL | 我们只能选 KRAK/ZSTD 之一并把大小上限当硬约束；超限要**减少新增行**（例如 scaling 段对只生成被用到的） |
| 34 级手工矩阵（`Enemy/ScalingEffects.cs:107-152`、`176-186` 那堆常量） | 是针对 DS3/ER 原版数值调的 | **数字不能照搬**（Convergence 数值体系不同），只搬「机制 + id 段 + 字段名」；矩阵要我们用数据驱动生成 |
| `Parallel.ForEach` 并行写盘（`1338-1347`） | C# 线程安全靠不可变输入 | Python 侧别并发做「写/删/复原」，串行 + 逐文件校验更稳 |

### ③ 我们的条件更好的地方

1. **有 GUI**：参考实现「本次会写哪些文件」只有 `Console.WriteLine("Writing {path}")`（`Core/GameData.cs:1546-1554`）。我们能在 GUI 里**执行前列出将写的文件清单 + 与上一轮产物的 diff 预览 + 一键复原**，把「一半变了」变成用户可见、可回滚的状态。
2. **有 ini `Plan=` 与方案层**：参考实现的置换只是内存里的 `EnemyPermutation`（`Enemy/EnemyPermutation.cs:50-63`），跑完就没了。我们可以把 plan **落成文件**（target→source 全表 + 参数行 id 分配表），于是「同一份 plan 被写两次」这种问题能被直接观测：比对 plan 指纹 / 已分配 id 表，第二次就应该报「已应用过」而不是再写一遍。
3. **有 Python**：能做参考实现做不到的对账（§9② 那条离线校验），也能把「字段清单」写成 schema 断言，而不是靠人记。
4. **只做一部作品**：参考实现 `EnemyRandomizer.cs` 里满屏 `if (game.Sekiro)/else if (game.DS3)/else if (game.DS1)/else if (game.EldenRing)`（如 `:3261-3306`、`7864-8032`）。我们只保留 ER 分支，代码量与出错面直接砍掉一个数量级。
5. **有 codegraph**：这套「字段 → 症状」的映射可以做成可查询的知识条目，后续改动前先查「这个字段谁写过」。

---

## 附：待补的缺口（后续若需要更硬的结论）

- `Enemy/EnemyAnnotations.cs` 的 tag 定义正文（`perceptive`/`sensitive`/`scalephase`/`cmdhelper`/`alwayschr`/`npcpart` 的判定条件与适用对象）。
- `Enemy/Enemies.cs` 与 `Enemy/EnemyPlacement.cs`：`EnemyData` 的完整字段集、以及 `places.GetEntry` 的落点预计算是怎么来的。
- `Core/RuntimeParamChecker.cs` 161 行之后（`EditEvents` 已读，`CheckEntries` 之后是否还有别的检查未读）。
- `EnemyRandomizer.cs` 中 `WriteEmevds` 的填充逻辑（我只确认了它在写盘侧被消费，`Core/GameData.cs:1211-1212`，没读填充点）。