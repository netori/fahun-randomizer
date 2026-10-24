# 双人/多实体 Boss「单只互换」调查（任务 B）

- 日期：2026-10-24（只读调查；未改任何仓库既有文件）
- 工作目录：F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod
- 参考实现源码：C:\Users\20905\AppData\Local\Temp\dsh_gh\sr（SoulsRandomizers）
- 参考基线数据：C:\Users\20905\Downloads\Elden Ring Randomizer 428 v0.12.2 2026-09-09T07-25Z kRGZWDlvJ\randomizer\diste\Base\enemy.txt
- 法魂包（EMEVD 反编译 js）：F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）\mod\event\<map>.emevd.dcx.js

## 0. 结论速览

1. **参考实现里确实有「互换双人 Boss 里的单个敌人」，但它的真语义不是「保留主 Boss、原地单换第二只」**，而是 opt[swapboss]：
   - 主 Boss 照常独立随机（每个 boss 位置各自从 Boss 池抽）；
   - 每场「多 Boss 战」的第二只（Class=Helper、带 tag swappable、OwnedBy>0）从**全局第二只池**里跨场互换（EnemyRandomizer.cs:1498-1512, 2212-2228）；
   - 写盘时把目标战**原有的 helper 实体删掉**，克隆 donor 战斗的 helper（EnemyRandomizer.cs:3729-3761, 4105-4113）；
   - GUI 文案：Swap bosses between multi-boss fights / For mini-dungeon bosses only（EldenRingRandomizer.Avalonia\Views\MainWindow.axaml:574-576）。
2. **我们 13 个位置全部 keep 的唯一原因是 Class=Helper → class.silo=false**（enemy_classes_v3.yaml:41 的 Helper 定义 + :88 的 policy 规则；enemy_data_build.py:519-520），**不是事件绑定**。3 个 evt=anim 的目标也是被这一条拦住的：_evt_blocks 的 anim 只对 pools 含 waygate 的守门位生效（enemy_data_build.py:255-269）。m12_07 仿身泪滴另有一条 keep_npc_ids（yaml:109-110）。
3. **我们能做，而且比参考更安全**：保留 EntityID、不删实体、事件死亡条件原样；只换 NpcParam/模型/think/chara（enemy_write.py:752-855 已是 unit 驱动）+ 按实体改血条名（enemy_write.py:1299-1351 → bar_names.py:277-324 自动按实体 patch）。这与参考的「删除原 helper + 事件模板改写」是两条路，我们这条路省掉了事件层最大风险。
4. 建议做法：**数据层保持 keep 不动（不重建 CSV/yaml 的 l4 分类）**，在计划层新增「duo 组」：主实体继续走现有随机，第二只独立抽「有血条名的 Boss 档」捐赠者，尺寸/竞技场以**主人**为基准，HP 按原「第二只/主人」比例缩放，魂保持 0。改动集中在 enemy_plan.py（新 duo 分支）+ enemy_write.py 的 _rel_of（一处）+ yaml 新段 duo:；写盘/血条名链路基本不动。
5. 分批：**A 批 6 个低风险**（m30_12、m30_14、m31_15、m31_18、m34_14、m60_49_39）→ **B 批 4 个**（m31_06、m31_11 两只、m32_05：事件里有 ForceAnimationPlayback 姿态命令）→ **C 批 3 个暂缓**（m31_22 神皮两阶段体 = 分阶段召唤战；m12_07 拟态泪 = 单只、真身复制玩家）。
6. 参考**不覆盖**神皮（31220801/31220802 无 swappable tag）与恶兆孪生子（34140851 无 swappable）；我们做这两处属于超出参考范围，机制上可行（无共享 AI，见 §3.4），但风险自负，所以孪生子放 A（机制最简单，用实验 1 验证），神皮放 C。
7. 关键未验证项：ForceAnimationPlayback(30000/20000) 对陌生模型是否只是静默无效/日志报错（B 批 3 图）；m31_22 的阶段生成器 31223307/31223308（EnableGenerator，m31_22:288/:303）与换模型是否互相影响。这两项未确认前不要放开 B/C 批。

## 1. 参考实现机制（file:line 证据）

源码根：C:\Users\20905\AppData\Local\Temp\dsh_gh\sr，下文 ER: 均指 RandomizerCommon\Enemy\EnemyRandomizer.cs。

### 1.1 swapboss：收集与求解

构造第二只池（ER:1498-1512）：

    if (opt["swapboss"])
        foreach (EnemyInfo info in infos.Values)
            if (info.HasTag("swappable") && info.OwnedBy > 0)
            {
                AddMulti(swapHelperMapping, info.OwnedBy, info.ID);
                allSwapHelpers.Add(info.ID);
            }

- 语义：**「第二只」= tag swappable 且自己有一个主人（OwnedBy>0）的 Helper**；按主人分组，同时进全局池 allSwapHelpers。

随机分支（ER:2201-2208）：主实体抽到 source 后，若 source 自己也是某场多 Boss 战的主实体（swapHelperMapping 有它），把 (target, helper) 记进 swapTargets。

求解（ER:2212-2228）：

    List<uint> swapSources = allSwapHelpers.ToList();
    Shuffle(makeRandom(true), swapSources);
    Shuffle(makeRandom(true), swapTargets);
    for (int i = 0; i < swapTargets.Count; i++)
        silo.SwapMapping[swapTargets[i]] = swapSources[(swapSourceIndex++) % swapSources.Count];

- 语义：**每场多 Boss 战的第二只，换成另一场多 Boss 战的第二只**；池是一维全局池（不是同族/同区域），洗牌后轮转分配。
- forceMap 分支同样处理（ER:1539-1552）：if（source 是多 Boss 主实体 && 该 target 不在 preset.DontRandomizeIDs 里）→ 每个 helper 从 allSwapHelpers 里 Choice 一只。
- TempTargets 复制时继承 SwapMapping（ER:2257-2267），保证同一批生成内一致。

### 1.2 写盘：克隆 donor 的 helper、删除目标战原 helper

ER:3729-3761（核心循环，逐行）：

    3729  if (owners.TryGetValue(source, out List<uint> helpers))
    3732      foreach (uint helper in helpers)
    3734          if (!targetMultichr && !infos[helper].HasTag("alwayschr")) continue;   // 闸门一
    3735          if (infos[helper].Class != EnemyClass.Helper) continue;                 // 闸门二
    3736-3742    helperSource = helper;
                 if (silo.SwapMapping.TryGetValue((target, helper), out uint swapHelper)) {
                     helperSource = swapHelper;                // swapboss：换成另一场的第二只
                     mapping.SwapMapping[(target, helper)] = swapHelper;
                 }
    3743-3748    EnemyData data2 = defaultData[helperSource];
                 target2 = newEntity()（HelperMapping 命中则复用站位实体）
    3749         TEnemy e2 = enemyEditor.CloneEnemy(msb, e, data2, target2, helperModelBase++);
    3750         enemyEditor.ClearGroups(e2, preserveGroups);

- targetMultichr 的来源是 ER:3427：bool targetMultichr = enableMultichr(source, target); 而 enableMultichr 在 ER:3249-3307：
  - ER:3290-3291：target 是 IsImportantTarget → 直接放行；source 带 bossonlymulti → 拒绝；
  - ER:3292-3305：mariner（船）限 20；eldenHelperBosses 白名单（ER:3220-3246：Rennala2/Malenia/Astel/Messmer2/Metyr/Lamenter/龙/Jori/PCR/Radahn）用 eldenMulti 预算（本体 50 / DLC 100，ER:3248）；
  - ER:3317-3319：partsRestricted 阈值 ER=200。
  - 即：**目标战必须「装得下多实体」**（预算/白名单），否则不克隆 helper，双人战会变单人。
- 目标战原有 helper 一律删除（ER:3907-3913 记 usedHelpers；ER:4105-4113）：

    4105  enemyEditor.RemoveEnemies(msb, id => usedHelpers.Contains(id)
    4107      && infos[id].Class == EnemyClass.Helper);
    4113  GarbageCollect(...)

  → 玩家看到的是「donor 战斗的第二只」出现在目标战里；若 donor 本身没有 helper，目标战只剩单人，事件里 CharacterDead(已删实体) 被视为满足（参考实现假设，未在本项目验证；我们不删实体，规避）。

### 1.3 允许 / 不允许「单只互换」的条件（参考版判据）

| 条件 | 允许 | 不允许（绑一起） | 证据 |
|---|---|---|---|
| 全局开关 | opt[swapboss] 开 | 默认 false | ER:1498；ExternalItemPreset.cs:323；MainWindow.axaml:574-576「For mini-dungeon bosses only」 |
| 第二只身份 | tag swappable 且 OwnedBy>0 | 无 swappable（神皮使徒/贵族、恶兆孪生子） | ER:1498-1512；enemy.txt 对应实体 Tags |
| 目标战容量 | enableMultichr(source,target) 过 | 预算不足/白名单外/partsRestricted | ER:3427、3249-3307、3734 |
| helper 类 | Class == Helper | 非 Helper（None/DupeOnly 等） | ER:3735 |
| 是否删除原 helper | 总是删除目标战原 helper | —— | ER:3907-3913、4105-4113 |
| 第一只（主 Boss） | 照常独立随机 | —— | ER:2201-2208 |
| 特殊：神皮蜗牛 | 替换蜗牛时专门移除生成器 31223308 | —— | ER:3418-3421（见 §3.5 m31_22） |

### 1.4 血条 / 事件 / 魂 / 缩放（参考版）

- 血条分组：ER:533-577 totalHealthbars —— info.HealthbarIndex > 0 时 healthKey = OwnedBy>0 ? OwnedBy : ID，取 max(HealthbarIndex+1)（即「一场战斗内第几管血」按主人归并）。ER:5485-5517 getHealthbarIndex；dupe 时累加、超过 maxHealthbars=3 只留主目标返回 -1。
- 事件层血条改写：ER:6702-6780 把事件模板里的 DisplayBossHealthBar 用 nameSource/nameSlot/nameId（cmdArgs[1..3]）重写；ER:8013 int newNameSlot = getHealthbarIndex(nameSource, nameTarget, nameDupeIndex);
- 「两只都死」判定改写（这是参考能安全换 helper 的关键）：ER:6700-6840 的 healthbarcheck / unhealthbarcheck 段，fighters = {data.Target} 并上 owners[data.Source] 中带 mainhelper/combathelper 的 helper 的映射目标（6810-6821），dupe 时再合并（6823-6834）。
- 魂：ER:3067-3089 整体重算 getSoul；3080-3084 若 info.Class == EnemyClass.Helper 且没有 mainhelper tag，则 amt /= 5；nosouls tag 不发 rune（3067）。
- 缩放：ER:8819-8850 —— helper 的缩放基准不是它自己的 hp，而是「主人 target」：若 infos 里没有 target 这条而 source 的 OwnedBy > 0，则用 mapping.HelperMapping 反查 ownerTarget，baseTarget = ownerTarget；若 mapping.SwapMapping 有 (baseTarget, source)，enemySource = swapSource。ER:8811-8813 注释：Currently, it's assumed this won't apply to swappable encounters / All swappable are also expected to be multi and mainhelper。
- SwapMapping 结构注释：EnemyMapping.cs:18-31：To support swapboss mode, mapping from (owner target, source helper) -> other source helper (mainly for scaling)。

### 1.5 纠偏：参考实现的「单只互换」≠「保留主 Boss、原地单换第二只」

- 参考：主 Boss 随机（可能换成任何 Boss）→ 若换入 source 是多 Boss 主实体，克隆它的 helper → swapboss 时再把该 helper 身份换成**另一场的第二只** → 删除目标战原 helper。
- 玩家观感：多 Boss 战的「第二只」在各多 Boss 战之间互换；第一只是独立随机的（可能变成普通杂兵/其它 Boss）。
- 因此参考实现**不需要**「同一场战斗里第二只单独抽本场池」这种功能；它也没有「第一只与第二只成组绑定」的语义。
- 对我们的意义：想要「保留主 Boss、单换第二只」，参考里没有可直接抄的实现；可抄的是它的**第二只全局池 + swappable 白名单 + 尺寸/缩放基准跟主人 + 血条按实体改写**这几条设计原则，而写盘/事件路径要换成我们自己的（保留 EntityID、只改身份 + 改血条名）。

### 1.6 参考不覆盖的位置

- 31220801 神皮使徒 / 31220802 神皮贵族：enemy.txt:25596 / :25611，Tags = multi nomodelname nosouls combathelper partial，**无 swappable** → 不进 allSwapHelpers，参考不会把它们当第二只互换。
- 34140851 恶兆孪生子：enemy.txt:27403，Tags = multi perceptive mainhelper adjective，**无 swappable** → 同上。
- 12070805 仿身泪滴：enemy.txt 里无此实体（grep 无）→ 参考根本没有这个位置。
- 其余 9 个目标都带 swappable（m30_12:22183、m30_14:22518、m31_06:24027、m31_11:24468/24483、m31_15:24831、m31_18:25062、m32_05:26231、m60_49_39:70196），是参考 swapboss 的真实作用域。

## 2. 我们为什么 keep（数据层证据）

### 2.1 判定链

enemy_data_build.py:411-579 apply_layer，按顺序第一条命中生效（与 yaml:78-94 的 l4_policy.rules 同序）：

| 步 | 规则 | 行号 | 13 个目标是否命中 |
|---|---|---|---|
| 1 | overrides.places | 491-493 | 否 |
| 2 | never_touch_npc_ids | 494 | 否 |
| 3 | multiphase.groups | 497 | 否（14 组见 yaml:144-159，全是本体主线大 Boss，不含这些） |
| 4 | EMEVD 绑定（evt 非空） | 500 → 255-269 | **否**：anim 只在 pools 含 waygate 时算绑定；3 个 evt=anim 的目标 pools 为空 |
| 5 | model == c0000 | 507 | 否 |
| 6 | part 名含 Sound | 512 | 否 |
| 7 | class 不在 l1_classes | 517 | 否 |
| 8 | **class.silo == false** | 519-520 | **是 —— 13 个全部命中，唯一原因** |
| 9 | keep_models | 521 | 否 |
| 10 | keep_maps | 523 | 否 |
| 11 | keep_npc_ids | 525 | 仅 m12_07 命中（npc 526100965，yaml:109-110） |
| 12 | keep_places | 527/529 | 否（m12_07 的壳 12070810 是另一行，见 yaml:121-123） |
| 13 | hp 无数值 | 531 | 否 |

结论：**12 个 Helper 位置 keep = class.silo=false（yaml:41 Helper 注释「跟随主人的 helper（召唤物/炮台/剧情随从）：单独换 = 与主人断链」）；m12_07 是 cls=None（cls_src=model，c1000 不在参考表里）+ keep_npc_ids 双保险**。yaml:19-20 已把 Helper/None/DupeOnly 列为「内部标记类：不进界面、不参与随机、不当来源」。

### 2.2 13 个目标实测行（investigation\enemy_places.csv）

| map | entity | CSV 行 | npc | model | cls | bar | evt | policy | note |
|---|---|---|---|---|---|---|---|---|---|
| m12_07_00_00 | 12070805 | 2590 | 526100965 | c1000 | None | 1 | （空） | keep | class.silo=false |
| m30_12_00_00 | 30120801 | 5378 | 37011930 | c3701 | Helper | 1 | （空） | keep | class.silo=false |
| m30_14_00_00 | 30140801 | 5440 | 42601940 | c4260 | Helper | 1 | （空） | keep | class.silo=false |
| m31_06_00_00 | 31060801 | 5865 | 33501920 | c3350 | Helper | 1 | anim | keep | class.silo=false |
| m31_11_00_00 | 31110801 | 5958 | 33500940 | c3350 | Helper | 1 | anim | keep | class.silo=false |
| m31_11_00_00 | 31110802 | 5959 | 33502940 | c3350 | Helper | 1 | anim | keep | class.silo=false |
| m31_15_00_00 | 31150801 | 6040 | 41200910 | c4120 | Helper | 1 | （空） | keep | class.silo=false |
| m31_18_00_00 | 31180801 | 6094 | 48200930 | c4820 | Helper | 1 | （空） | keep | class.silo=false |
| m31_22_00_00 | 31220801 | 6206 | 35600950 | c3560 | Helper | 1 | （空） | keep | class.silo=false |
| m31_22_00_00 | 31220802 | 6207 | 35700950 | c3570 | Helper | 1 | （空） | keep | class.silo=false |
| m32_05_00_00 | 32050801 | 6378 | 33501930 | c3350 | Helper | 1 | anim | keep | class.silo=false |
| m34_14_00_00 | 34140851 | 6721 | 21403150 | c2140 | Helper | 1 | （空） | keep | class.silo=false |
| m60_49_39_00 | 1049390801 | 18582 | 33001940 | c3300 | Helper | 1 | （空） | keep | class.silo=false |

主实体（owner，policy=randomize，现有随机照常作用）：

| map | owner entity | npc | hp | cls | helper hp / owner hp |
|---|---|---|---|---|---|
| m30_12 | 30120800 | 34600930 | 664 | MinorBoss | 184/664 = 0.277 |
| m30_14 | 30140800 | 42600940 | 1052 | MinorBoss | 1.0 |
| m31_06 | 31060800 | 33502920 | 352 | MinorBoss | 1.0 |
| m31_11 | 31110800 | 33501940 | 698 | MinorBoss | 1.0（两只） |
| m31_15 | 31150800 | 41200910 | 534 | MinorBoss | 1.0（**与 helper 同一 npc**） |
| m31_18 | 31180800 | 44800930 | 1939 | MinorBoss | 429/1939 = 0.221 |
| m31_22 | 31220800 | 41402950 | 190 | MinorBoss | 使徒 2033 / 贵族 2439（约 10.7 倍 / 12.8 倍主人） |
| m32_05 | 32050800 | 33500930 | 352 | MinorBoss | 1.0 |
| m34_14 | 34140850 | 21403050 | 1625 | MinorBoss | 1350/1625 = 0.831 |
| m60_49_39 | 1049390800 | 33000940 | 339 | MinorBoss | 1.0 |

### 2.3 如果放开：三种改法对比

| 改法 | 具体 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|---|
| A. 直接改 CSV policy | 手改 enemy_places.csv 12 行 keep→randomize | 最快 | 违反「yaml 单一权威源」；下次 --build 被覆盖；且会带来 B 的全部副作用 | 不可用 |
| B. 改 yaml overrides.places | 在 yaml:412 overrides 段给 12 个 (map,entity) 加 policy: randomize（apply_layer:491-493 最高优先） | 单一源、重建后持久 | ①这 12 行进入 **donor 来源池**（donor_units 只排除 keep，enemy_plan.py:1356-1388），低 hp 的 Helper 会被当低档捐赠者，破坏平衡；②silo 变成 Helper 加 base，tier 只在这 13 行内分位（data_build:536,565-579）；③helper 的 ref_size/ref_arena 全 0 → arena_safety 失效；④enemy_write._rel_of 会把「Helper→Boss 捐赠者」误判成 m2b（enemy_write.py:416-422），写 disableInitializeDead=1；⑤helper 有可能被别的位置抽为捐赠者。 | 不推荐 |
| C. 计划层 duo 组（推荐） | 数据层不动；yaml 新增 duo: 段；enemy_plan 为每组第二只构造 duo 单元、专用 donor 池/尺寸基准/HP 比例；enemy_write 只改 _rel_of | 数据统计不变；不会污染 donor 池；可开关、可分批复；血条名/写盘全复用 | 需要在 plan 层加一条旁路分支（约百行）；yaml 改动会改 seed（见下） | **推荐** |

### 2.4 数据重建 / 统计影响（若走 B）

- keep 原因 class.silo=false 当前 2,711 行；放 12 行 → 2,699（-12）。
- Helper 类当前 440 行（bar=1 的 20 行、带 link 的 66 行）；若 12 行变 randomize，会出现 Helper 加 base 的 silo（仅这些行），tier 在极小样本内分位 → tier 值可参考性差。
- assertions 段（yaml:422 起）只校验 total_places 27780、linked_pairs 2124、linked_rows 4248、physical_positions 25656、distinct_maps 519、no_unknown_class、allowed_policy_values，**没有 policy 计数断言** → 改 12 行不会让 --check 红（enemy_data_build.py apply_layer 411-579 与 assertions 实测）。
- **seed 影响（重要）**：enemy_plan.py:2223-2243 把 yaml 文件 sha256 记进 data.hashes；1220-1234 seed_material = {plan_version, seed, data_hashes}。**任何 yaml 改动（包括新增 duo: 段）都会改变 yaml_sha256 → 所有单元的 RNG 全量重排**（代码注释 1226 明确说这是有意行为）。发布 duo 功能时应视为一次「全量换种子」的版本；若不想重排旧种子，可把 duo 配置放在单独文件（例如 data\duo_v3.yaml）并只让 enemy_plan 读取、不纳入 data_hashes——但代价是权威源分裂，不推荐。
- get_soul：13 行全部 0（enemy_table.csv）→ 克隆行 getSoul=0，第二只不掉卢恩（与召唤体一致）；主 Boss 的追忆/掉落不受影响（掉落抄位置原行，见 §3.3）。

## 3. 风险清单（按 13 个位置实测）

### 3.1 血条：是「位置 + 事件」属性，每个实体各有独立血条调用

DisplayBossHealthBar 参数 = (Enabled, Entity, Slot, NameId)，逐图实测（法魂包 mod\event\<map>.emevd.dcx.js）：

| map | 主实体血条 | helper 血条 | 备注 |
|---|---|---|---|
| m30_12 | :149 (30120800, slot0, 903460300) | :152 (30120801, slot1, 903700300) | 槽位常规 |
| m30_14 | :123 (30140800, slot0, 904260304) | :127 (30140801, slot1, 904260305) | 常规 |
| m31_06 | :111 (31060800, slot0, 903350310) | :112 (31060801, slot1, 903350311) | 常规 |
| m31_11 | :368/:369/:370 三条：31110800 slot0 903350313、31110801 slot1 903350312、31110802 slot2 903350314 | 同左（slot1/slot2） | 三管血 |
| m31_15 | :123/:125 与 :138/:140 两处开（进战斗 + AIState Combat） | helper slot1 904120311 | 两处都引 helper |
| m31_18 | :221 (31180800, slot0, 904480310) | :222 (31180801, slot1, 904820310) | 常规 |
| m31_22 | :273 使徒 slot0 903560310 / :295 贵族 slot0 903570310 / :306+:312 蜗牛 slot0 904140310 | 阶段体 slot 都是 0 | **分阶段顺序开三条，不是同屏三条** |
| m32_05 | :396 (32050800, slot0, 903350321) | :397 (32050801, slot1, 903350322) | 常规 |
| m34_14 | :208 (34140850, **slot1**, 902140000) | :209 (34140851, **slot0**, 902140001) | **槽位顺序与其它图相反** |
| m60_49_39 | :345 (1049390800, slot0, 903300560) | :346 (1049390801, slot1, 903300561) | 常规 |
| m12_07 | :173 DisplayBossHealthBar(Enabled, X0_4, 0, X8_4)；:177 Disabled | 无（单只） | 用事件寄存器取真身 |

结论：**血条数量/槽位是事件写死的（按实体 id），跟模型无关**。我们保留 EntityID → 槽位不变；只需把 NameId 改成新身份的血条名——bar_names.targets_for_map（bar_names.py:277-324）就是按「每个 unit 的每个 place」生成 {entity: ([old...], new)}，因此 helper 作为独立 unit 时会**自动按它自己的实体 id patch 名字**，m34_14 槽位顺序相反也不影响。m31_22 三阶段共用 slot0 但每段是不同实体，也各自 patch。

### 3.2 胜利 / 死亡条件（逐图实测）

| map | 胜利条件 | helper 死亡如何被引用 | 换 helper 后是否会卡 |
|---|---|---|---|
| m30_12 | :114 WaitFor(HP(30120800)<=0 且 HP(30120801)<=0) → :117 WaitFor(Dead 双) → 结算 | :157 阶段 flag 30122802 也由 CharacterDead(30120801) 触发（二阶段演出） | 不会（entity 不变，新模型可死即可） |
| m30_14 | :91 双 HP0 → :94 双 Dead → 结算 | 仅死亡条件 | 不会 |
| m31_06 | :55 WaitFor(Dead(31060800) 且 Dead(31060801)) | :67/:74 各自 HP<=0→PlaySE；:119 任一 Dead→flag 31062842 | 不会；注意 :82-95/:106-114 有 ForceAnimationPlayback(31060801, 30000/20000) |
| m31_11 | :303 WaitFor(三只全 Dead) | :315/:322/:329 各自 HP<=0→PlaySE；:378 任一 Dead→31112842 | 不会；:337-356 各自 ForceAnimationPlayback(30000/30001/20001/20000) |
| m31_15 | :66 双 Dead → 结算 | :148 任一 Dead→31152842 | 不会；31152820 事件体 :152-156 按实体挂 SpEffect(4305)，与新模型无关但会照样执行 |
| m31_18 | :180 双 Dead → 结算 | :191/:198 各自 HP<=0→PlaySE；:237 任一 Dead→31182842 | 不会 |
| m31_22 | 分阶段：:284 WaitFor(Dead(31220801)) → 关血条 → 5s → :288 EnableGenerator(31223307) → 开贵族；:300 WaitFor(Dead(31220802)) → :303 EnableGenerator(31223308) → 5s → 开蜗牛；蜗牛最后 | 各阶段各自 Dead | **风险最高**：阶段推进 + 生成器 + 蜗牛本体 hp 只有 190；换阶段体可能改变演出/生成器效果（未验证） |
| m32_05 | :342 双 HP0 / :345 WaitFor(HP(32050800)==0 且 HP(32050801)==0) → 结算 | :405 条件含 CharacterDead(32050801)；:371/380/384/387 ForceAnimationPlayback(30000/20000) | 不会（另注意 :400-407 里两条 HPRatio 判断疑似原版笔误都写 32050800，与本次改动无关） |
| m34_14 | :161 双 HP0 → :164 双 Dead → :166 结算/flag/9174/10740 | 34140860 :175-211 战斗启动：:190-194 若 !EventFlag(34140851) 进区域/受击 → SetNetworkconnectedEventFlagID(34140851,ON)；:202-209 启用两只+两条血条 | 不会；同时在场、各自 AI |
| m60_49_39 | :311 双 HP0 → :314 WaitFor(CharacterDead(1049390800))（只等主）→ 结算 | helper 只参与 HP 检查 | 不会；注意「主死但第二只没死」的极端情况下也会结算（原版如此） |
| m12_07 | 单只；:173/:177 血条用寄存器 | 无 helper | 不适用 |

通用结论：**没有任何一张图要求「只剩一只」；全部是「两只 HP=0 + 两只 Dead」或分阶段各自 Dead**。我们保留实体 → 死亡条件无需改；只要新身份是正常可击杀敌人（候选池满足）就不会卡胜利。

### 3.3 共死 flag / 掉落 / 魂

- **无共死 flag**：逐图扫描未发现「helper 与主实体共用同一死亡 flag」。主实体死亡 flag 是 (map 前缀 + 00/50)，helper 不设置同一 flag（m34_14 的 34140851 是「进区域/受击」网络 flag，不是死亡 flag：m34_14:190-194）。m31_22 是分阶段 flag，与 helper 死亡绑定但不共享。
- **掉落**：enemy_write.make_npc_clone（enemy_write.py:653-667）从「位置原本那只」的 NpcParam 抄 LOT_COPY_FIELDS（F3 掉落绑地点），**不抄捐赠者的掉落**。helper 位置原行没有 boss 掉落 → 克隆行不带捐赠者掉落；主 Boss 掉落（AwardItemsIncludingClients(主id) 等）不受影响。
- **魂**：13 个 helper 的 get_soul 全为 0；make_npc_clone:621-622 写 getSoul=target_soul（None→0），:624-627 强制 isSoulGetByBoss=0、disableRespawn=0；enemy_write.py:1750-1752 还有 verify 断言「克隆行 isSoulGetByBoss 没清」会报错。参考实现是给 helper 魂量 /5（ER:3080-3084）并整体重算，我们的做法「第二只 0 魂」更保守，符合召唤体/助战一致。
- **卢恩归属**：写盘层不复制 donor 的 getSoul，因此不会出现「杀第二只掉大额卢恩」；如果用户希望第二只掉魂，需要额外改计划层 soul 策略（不建议 v1）。

### 3.4 AI / 脚本绑定 / 召唤体

- **EMEVD 扫描结论**：13 个 helper 在事件里只被这些命令引用：DisplayBossHealthBar、CharacterDead/CharacterHPValue、Disable/EnableCharacter(+AI/Collision/Invincibility)、ForceCharacterDeath、ForceAnimationPlayback、SetNetworkUpdateRate、SetNetworkconnectedEventFlagID。**没有**针对 helper 的 SetSpEffect、共享 AI id、CreateReferredDamagePair（全 mod 只有 11 张图有 pair，均不含本任务 10 张图）。
- **AI 配合**：神皮使徒/贵族是蜗牛的两个阶段召唤体，但各自 EnableCharacterAI，没有共享 think id；恶兆孪生子各自 Disable/EnableCharacterAI（m34_14:186-187/204-205），无共享 AI。三结晶人也是各自 AI。→ 替换成任意 Boss 身份不会「断 AI 链」，只会让演出气质变化。
- **召唤体与主人绑定**：真正绑定的是 **m31_22**（唤灵蜗牛本体 hp 190，先使徒、再贵族、最后本体；阶段推进靠 CharacterDead + 生成器）与 **m12_07**（仿身泪滴真身 CopyPlayerCharacterData 复制玩家、可见壳 12070810 另 keep）。其余 10 个是「同场并存的第二只 Boss」，不是召唤体。→ m31_22 与 m12_07 放 C 批/不做；其余 11 个可做。
- **姿态动画风险**：m31_06、m31_11（两只）、m32_05 的事件里对新实体有 ForceAnimationPlayback(30000/20000/20001/30001)（休眠/起身姿态）。换新模型后这些 animation id 可能不存在 → 预期「静默无效或日志报错」而非崩溃（**未实机验证，B 批要专门看**）。A 批 6 个均无此类命令。

### 3.5 逐位置风险表与分批建议

| 批次 | 位置 | 风险点 | 说明 |
|---|---|---|---|
| A（先做，6 个） | m30_12/30120801 托莉夏 | 低 | 无 anim；双死条件；HP 比例 0.277 |
| A | m30_14/30140801 看门犬杖 | 低 | 无 anim；两只同 hp；体型 1.2/2.4（大，需尺寸上限） |
| A | m31_15/31150801 亚人首领 | 低 | 无 anim；与主人同 npc；AIState Combat 重开血条不依赖模型 |
| A | m31_18/31180801 恶兆猎人 | 低 | 无 anim；HP 比例 0.221（第二只弱） |
| A | m34_14/34140851 恶兆孪生子 | 低-中 | 无 anim；**同时在场**、slot 顺序相反；参考无 swappable（超出参考范围） |
| A | m60_49_39/1049390801 诺克斯剑士 | 低 | 无 anim；胜利只等主死（原版如此） |
| B（第二批，4 个） | m31_06/31060801 结晶人矛 | 中 | ForceAnimationPlayback 30000/20000；双死 |
| B | m31_11/31110801+31110802 腐败结晶人 | 中 | 三只全死；anim 30000/30001/20001/20000；两条同时换（难度/演出） |
| B | m32_05/32050801 结晶人矛 | 中 | anim 30000/20000；阶段判断有原版笔误（无影响） |
| C（暂缓，3 个） | m31_22/31220801+31220802 神皮 | **高** | 分阶段召唤战 + 生成器 31223307/31223308 + 蜗牛本体 hp190；参考专门移除生成器 31223308（ER:3418-3421）；无 swappable |
| C | m12_07/12070805 仿身泪滴 | 高/不做 | 单只、真身 CopyPlayerCharacterData + 可见壳 keep（yaml:109-110/121-123）；不是双人战 |

## 4. 落地方案（推荐：计划层 duo 组）

### 4.1 语义定义（三档，v1 只做档 1）

- **档 1 second_only（推荐 v1）**：主实体继续走现有随机（policy=randomize 已做）；第二只独立抽「有血条名的 Boss 档」捐赠者；尺寸/竞技场基准用主人；HP 按原比例缩放；魂 0；写盘只改身份 + 血条名。**保留 EntityID、不删实体、不改事件死亡条件。**
- **档 2 pair_follow（v2 可选）**：第二只跟随主人新身份的「同族/同地图第二只」（例如主人换成某场双人 Boss 的主实体，就把它的搭档抽来）；找不到则 fallback 档 1。实现依赖 donor 的 OwnedBy 关系（enemy.txt 有、我们 places 表没有）→ 需要另建映射，v1 不做。
- **不做**：主实体与第二只互换（swap owner 与 helper）——需要重写事件里的血条 slot、死亡条件、flag、生成器引用，超出写盘层能力；参考实现也不做（它走删 helper 重建路线）。
- **不做**：整场替换/删除原 helper（参考路线）——我们不删实体，避免 CharacterDead(已删实体) 的未验证假设。

### 4.2 yaml 新段 duo:（草稿，建议加在 multiphase 段之后）

    duo:
      version: 1
      enabled: false            # 默认关；GUI features.duo_second 打开才生效
      mode: second_only         # second_only（v1）| pair_follow（v2）
      size_base: owner          # 尺寸/竞技场基准用主人（helper 的 ref_size/ref_arena 全 0）
      hp_mode: keep_ratio       # keep_ratio（默认）| donor_hp
      soul_mode: zero           # 第二只 0 魂（所有 13 个原值都是 0）
      donor:
        require_bar_name: true  # 必须有血条名（_named_ok 也会再强制一次）
        classes: [Boss, MinorBoss, Miniboss]
        exclude_models: []      # 可放进「脚本无敌/不可杀」名单（当前未确认，见 §6）
        size_mult: {radius: 1.5, height: 1.2}   # 相对主人
        hp_ratio: {min: 0.2, max: 1.0}          # 目标 hp / 主人 hp 的允许区间
        require_model_change_vs_owner: true     # 防止主/第二只同为一只 Boss
      groups:
        # batch 只是注释方便分批；A=低风险 B=anim C=暂缓
        - {id: misbegotten_perfumer, map: m30_12_00_00, owner: 30120800, second: [30120801], batch: A}
        - {id: watchdog_duo,         map: m30_14_00_00, owner: 30140800, second: [30140801], batch: A}
        - {id: demi_human_duo,       map: m31_15_00_00, owner: 31150800, second: [31150801], batch: A}
        - {id: miranda_omenkiller,   map: m31_18_00_00, owner: 31180800, second: [31180801], batch: A}
        - {id: fell_twins,           map: m34_14_00_00, owner: 34140850, second: [34140851], batch: A}
        - {id: nox_duo,              map: m60_49_39_00, owner: 1049390800, second: [1049390801], batch: A}
        - {id: cryst_spear_duo,      map: m31_06_00_00, owner: 31060800, second: [31060801], batch: B, anim: true}
        - {id: putrid_trio,          map: m31_11_00_00, owner: 31110800, second: [31110801, 31110802], batch: B, anim: true}
        - {id: cryst_ringblade_duo,  map: m32_05_00_00, owner: 32050800, second: [32050801], batch: B, anim: true}
        - {id: godskin_stages,       map: m31_22_00_00, owner: 31220800, second: [31220801, 31220802], batch: C, stage: true}
        # m12_07 拟态泪不进：无主人、真身复制玩家（keep_npc_ids 双保险）

### 4.3 enemy_plan.py 改动（最小侵入，约 120 行）

1. **加载 duo 配置**：enemy_plan.py:239 load_yaml 已返回整份 cfg（data["cfg"] 含顶层键），新增 load_duo(cfg) 读取 cfg["duo"]（缺省空）。配置校验：owner/second 必须在该图 places 里存在、second 的 policy 必须是 keep（否则跳过并记 skip）。
2. **在 build_plan（1850-2176）打标记**：unitize（1157-1188）之后、policy 分流（1987 处 skips.append(_skip(u, "policy:...", ...))）之前，给 second 对应的 unit 打 u["duo"] = {group_id, owner_unit_key, batch, ...}；**不要改 u["policy"]**。
3. **policy 跳过加旁路**：1987 改成「若 policy 不是 randomize 且 unit 没有 duo 标记，才 skip」。
4. **专用 donor 池**：在 1938 donors = donor_units(...) 之后构造 duo_donors = [d for d in donors if d.get("bar") and d.get("cls") in BOSSISH and d["key"] != owner_key]（donors 已排除 keep/Sound/c0000/hp<=0，且未被 include_keep_as_source 污染）。duo 单元**不得**以自己身份进入 donors（因为 CSV 仍是 keep，天然满足）。
5. **构造 duo 单元字段**：复制 places 行后覆盖 radius/height/ref_size/ref_arena = owner_unit 的对应值（这是让现有 _size_ok:1281-1306 的 arena_safety 与 size_max 以主人为基准的最小改动）；把 owner 的 hp 存进 duo.owner_hp、原 helper hp 存 duo.second_hp。
6. **生成 entry**：复用 _entry_for（1574-1647），再覆盖两处：
   - HP：ratio = second_hp / owner_hp（m30_12=0.277、m31_18=0.221、m34_14=0.831、其余=1.0；m31_22 比例大于 1，若开启则 clamp 到 1.0），target_hp = clamp(round(donor_hp * ratio), donor_hp*hp_ratio.min, donor_hp)；写进 entry 的 hp 字段（_entry_for 的 reasons 里加 duo 说明）。
   - soul：保持 0（target_soul=None）。
   其余字段（new_npc/new_model/new_think/new_chara/donor_map/donor_entity）照现有逻辑；entry 加 duo: {group, owner_entity} 供写盘/verify 使用。
7. **manual 支持**：load_manual（1128-1146）现在「只对 policy=randomize 位置生效」；改为「policy=randomize 或 unit 带 duo 标记」。manual_pool（1943）已包含 keep 单元，够用；manual 分支（1995-2020 区间，manual:no_donor 在 2008、manual:same_model 在 2017）无需改。
8. **manifest/plan 记录**：plan 里增加 duo_groups 与每个 duo entry 的 owner/donor/ratio/hp，便于 verify 与人工复核（plan dict 现有 meta/hashes 结构见 2119-2160）。
9. **跳过原因**：新增 duo:no_donor / duo:size / duo:same_model_as_owner 写进 skips（_skip 在 2178），便于统计。

### 4.4 enemy_write.py 改动（一处必须 + 一处可选校验）

1. **必须**：_rel_of（416-422）把「带血条的 Helper」视作 boss 侧：
   p = unit.get("cls") in BOSSISH or unit.get("bar") == 1
   否则 duo 单元 cls=Helper、捐赠者 cls=Boss → 判 m2b → make_npc_clone:629-633 写 disableInitializeDead=1（语义是「不按事件 flag 初始化死亡」，对 boss 侧位置是错的），可能让第二只出场即死/不生成。改成 same 后不写这一位。
2. **可选校验**（enemy_write 的 verify 段已有 isSoulGetByBoss 检查，1750-1752）：增加
   - duo entry 的 new_model != owner entry 的 new_model；
   - duo entry 的 new_npc_id != 位置原 npc；
   - bar_names 的 manifest/bar_sources 里必须出现 duo 实体（否则说明名字没换）。
3. 其余无需改：patch_map（752-855）是 unit 驱动；make_npc_clone（610-701）是位置驱动（掉落抄位置原行、getSoul 走计划值、isSoulGetByBoss 清 0）；血条名接线（1299-1351）按 unit 的 places 逐个实体 patch，duo 单元天然被覆盖。

### 4.5 bar_names.py / GUI / 文档

- **bar_names.py 不用改**：targets_for_map（277-324）按 unit 的 place 生成 {entity: ([old...], new)}，duo 单元的 place 就是 helper 自己那行；新名优先级「捐赠位置自己的血条名 > model_name > overrides > 占位名」。注意新名会显示「捐赠者 Boss 的名字」（例如把第二只换成恶兆猎人 → 血条显示恶兆猎人），这正是想要的；同名捐赠者被多处使用会重名，可接受（与 boss_any 已有行为一致）。
- **randgui.py**：_ev1_options（1695-1728）增加 features.duo_second（默认 false）；界面 1438-1450 区间加勾选/说明（「双人 Boss 的第二只也参与随机（实验）」）；自检 5411/5420-5423/5557/5595-5610 是既有断言，新增字段不会破坏，但要补一条默认值断言。
- **docs\敌人随机_参考功能对照.md:27** 需要订正：现在写「Swap bosses between multi-boss fights 已接（同场每个 BOSS 位置独立抽任意 BOSS；boss_any 允许两个位置得到不同种类）」——这与事实不符（第二只是 Helper、全部 keep；参考语义也不同）。建议改为「未接：第二只（Helper）仍 keep；参考的 swapboss 是跨场互换第二只，语义见 docs\参考实现_拆解\A…:142-160」。

### 4.6 自检 / 验证清单（不改游戏也能跑）

- plan 层：每组恰好 1 个 second entry（m31_11 是 2 个）；second entry 的 positions 含 helper 行且 entity 与 CSV 一致；new_model != owner_new_model；尺寸/HP 比例在约束内；非 duo 组 entry 数量与旧计划一致（回归）。
- data 层：enemy_places.csv 逐字节不变；--build --check 仍过 27780/2124/4248/25656/519。
- write 层（dry-run/manifest）：MSB patch 命中 helper 的 part（MODELIDX/NPC/THINK/CHARA 改变）；EMEVD 血条名替换后 bar_names.verify_file 通过（bar_names.py:245-263）；克隆行 getSoul=0、isSoulGetByBoss=0（verify 1750-1752 已有）；新增断言见 §4.4-2。
- 实机：见 §5 三个实验。

## 5. 最小可验证实验（前置：先实现 §4.3/4.4 最小版本）

说明：现在 load_manual 只对 policy=randomize 生效（enemy_plan.py:1128-1146），helper 是 keep → **不改代码无法手动指定**。下面按「duo 功能已实现」给配置；若只想先验证写盘链路，可把实验 1 当作 A 批第一个落地包。

### 5.1 实验 1（最简单机制）：m34_14 恶兆孪生子 → 第二只换成恶兆猎人

- 理由：同时在场、无 anim、无阶段、事件最简单（:159-173 双死结算 + :175-211 启动）；参考无 swappable，但机制上只考验「身份替换 + 血条名 + 双死条件」。
- 手动指定（enemy_manual.csv 追加一行，列为 map,entity_id,npc_id,model,note）：
    m34_14_00_00,34140851,48200930,c4820,实验1：恶兆孪生子的第二只换成恶兆猎人
  （48200930/c4820 = m31_18 的恶兆猎人，enemy_places.csv:6094，血条名 904820310 存在于 enemy_bar_names.csv）
- 实机重点看：
  1) 进雾门（区域 34142855）后两只都出现，第二只是恶兆猎人模型、不是隐身/灰模；
  2) 血条两条：主（slot1）名字仍是原主 Boss 名，第二（slot0）显示「恶兆猎人」；
  3) 只杀第二只 → 不结算；只杀主 → 不结算；两只都死 → Enemy Felled（:161/:164 条件保持）；
  4) 第二只不掉卢恩/追忆（getSoul=0），主 Boss 掉落正常；
  5) 二阶段无特殊演出（本图没有），不会卡旗；退出试玩看日志无 traceback。
- 判定：以上 5 条全过 = A 批方案成立，可推到其余 A 批。

### 5.2 实验 2（anim 风险）：m31_06 结晶人（矛）→ 换成神皮使徒

- 理由：事件在新实体上有 ForceAnimationPlayback(31060801, 30000/20000)（m31_06:82-95、:106-114），是最小代价验证「陌生模型 + 姿态动画 id」是否只是静默无效。
- 手动指定：
    m31_06_00_00,31060801,35600950,c3560,实验2：结晶人（矛）换成神皮使徒（含姿态动画）
  （35600950/c3560 = m31_22 的神皮使徒，enemy_places.csv:6206，血条名 903560310）
- 实机重点看：
  1) 0000/战斗开始时的「休眠摆放」是否正常（新模型没被摆成奇怪姿势/T-pose 是否明显）；
  2) 进战后起身姿态（20000）是否正常；是否出现控制台/日志 animation 报错（不要求通过，只记录）；
  3) 双死胜利（:55）是否仍成立；血条 slot1 显示「神皮使徒」；
  4) 若日志出现大量 animation 错误但不崩 → 结论：B 批可做但需接受姿态演出缺失；若崩/卡死 → B 批暂缓。
- 判定：不崩 + 双死可结算为「技术通过」；姿态表现记录在案。

### 5.3 实验 3（阶段战，只摸机制）：m31_22 神皮使徒阶段 → 换成恶兆猎人

- 理由：验证分阶段召唤战（:284/:300 WaitFor(CharacterDead) + :288/:303 EnableGenerator 31223307/31223308 + 蜗牛 hp190）能否承受单换阶段体；参考实现甚至专门移除生成器 31223308（ER:3418-3421），说明这张图需要特殊处理。
- 手动指定：
    m31_22_00_00,31220801,48200930,c4820,实验3：神皮使徒阶段换成恶兆猎人
- 实机重点看：
  1) 开场是否只有「使徒位」出现（其余阶段不出现）；
  2) 杀死使徒后，5 秒后贵族是否照常登场（:288 EnableGenerator 31223307 → :295 血条开）；血条 slot0 名字是否按阶段切换正确；
  3) 杀死贵族后，蜗牛本体是否登场（:303 生成器 31223308 → :306/:312 血条）；蜗牛是否可被击杀（hp190）；
  4) 若任一阶段卡住/不登场/血条名错位 → 结论：m31_22 不做（C 批放弃），并在报告里记录生成器行为。
- 判定：不是「必须通过」，而是「取证」；失败即放弃该位置，符合「先不做风险高」的策略。

## 6. 未确认事项（不要当结论用）

1. **姿态动画**：ForceAnimationPlayback(30000/20000/20001/30001) 对陌生模型是「静默无效」「日志报错」还是崩溃 —— 未实机验证，B 批实验 2 取证。
2. **m31_22 生成器**：31223307/31223308 不在 enemy_places.csv（不是敌人 part），只在 EMEVD :288/:303 EnableGenerator；具体生成物与换模型的相互影响未确认 → C 批不做。
3. **亲测「角色被事件禁用/启用」对新模型是否 100% 生效**：DisableCharacter/EnableCharacter 是按实体 id 的，理论上与模型无关；未实机验证（A 批实验 1 覆盖基本路径）。
4. **脚本无敌/不可杀捐赠者**：参考用 Group unkillable + exclude:unkillable 放置限制（本仓库 docs\敌人分类_参考词汇表.md:233 记录 ER:1680-1691）；我们没有等价名单，duo_donor 若抽到「脚本无敌」身份可能导致第二只打不死 → 卡「双死」胜利。v1 先靠试玩排查；确认后把名单写进 duo.donor.exclude_models。
5. **体型/卡墙**：helper 的 ref_size/ref_arena 全 0，现行 arena_safety 不生效；duo 方案改用主人基准后只保证「相对主人不过分大」，不保证 helper 出生点空间够（如 m30_14 arena:1）→ 需实机看卡墙。
6. **重名血条**：两个位置抽到同一捐赠者时血条名会重复；与现有 boss_any 行为一致，是否需要去重（池内不重复使用捐赠者）未定。
7. **「CharacterDead(已删实体) 视为满足」**：参考实现依赖的假设，我们不删实体，未验证也不需要验证。
8. **m30_14/m31_06 等 helper 与 owner 同 hp 的情况**：第二只换入后 HP 比例=1.0，可能让「第二只和主人一样强」，是否要压低需平衡拍板（hp_ratio.max 可调）。

## 7. 证据索引

参考实现（C:\Users\20905\AppData\Local\Temp\dsh_gh\sr）：
- RandomizerCommon\Enemy\EnemyRandomizer.cs:1498-1512（swappable 池构造）、1539-1552（forceMap）、2201-2208（随机分支）、2212-2228（求解）、2257-2267（TempTargets）、3249-3307（enableMultichr 及其白名单/阈值）、3418-3421（神皮生成器 31223308 特判）、3427（targetMultichr）、3729-3761（helper 克隆/交换/闸门）、3779-3787（helper 落点）、3907-3913、4105-4113（删除原 helper）、533-577（totalHealthbars）、5485-5517（getHealthbarIndex）、6700-6840（healthbarcheck 事件改写）、6702-6780（DisplayBossHealthBar 重写）、8013（newNameSlot）、3067-3089（魂/helper 除 5/nosouls）、8811-8813（swappable 假设注释）、8819-8850（helper 缩放基准/SwapMapping 反查）。
- RandomizerCommon\Enemy\EnemyMapping.cs:18-31（SwapMapping 注释）。
- EldenRingRandomizer.Avalonia\Views\MainWindow.axaml:574-576（swapboss 文案）。
- ExternalItemPreset.cs:323（swapboss 默认 false）。
- 参考基线 diste\Base\enemy.txt：30120801=22183、30140801=22518、31060801=24027、31110801=24468、31110802=24483、31150801=24831、31180801=25062、31220801=25596、31220802=25611、32050801=26231、34140851=27403、1049390801=70196（12070805 无）。

本仓库：
- investigation\apply\data\enemy_classes_v3.yaml:19-20（内部标记类）、28-45（l1_classes；Helper 在 :41）、78-94（l4_policy.rules；class.silo=false 在 :88）、109-110（keep_npc_ids 拟态泪）、113-123（keep_places 拟态泪壳）、127-159（multiphase 14 组，不含本任务图）、161（pools）、334（randomization）、412（overrides）、422（assertions）。
- investigation\apply\enemy_data_build.py:40-47（COLS）、49-52（DEFAULT_REF）、82-83（YAML_PATH）、200-208（bar）、211-252（scan_events）、255-269（_evt_blocks）、411-579（apply_layer；:491-493 overrides.places、:494 never_touch、:497 multiphase、:500 evt、:507 c0000、:512 Sound、:517 unknown cls、:519-520 class.silo=false、:521 keep_models、:523 keep_maps、:525 keep_npc_ids、:527/:529 keep_places、:531 hp、:534 randomize、:536 silo、:542-555 link 一致性、:565-579 tier）。
- investigation\apply\enemy_plan.py:47/48/50/54/55/57（路径常量）、61-109（DEFAULT_OPTIONS）、119-133（_target_hp_for）、239（load_yaml）、279（multiphase_source_units）、300（load_rules）、1128-1146（load_manual）、1157-1188（unitize）、1255/1273（_match/rule_for）、1281-1306（_size_ok）、1356-1388（donor_units）、1391（build_rule_donors）、1447-1458（_named_ok）、1574-1647（_entry_for）、1850（build_plan）、1932-1943（mp_src_map/donors/manual_pool）、1987（policy skip）、1995-2020（manual 分支）、2008（manual:no_donor）、2017（manual:same_model）、2178（_skip）、2190-2211（无候选诊断）、2223-2243（hashes 装配）、1220-1234（seed_material）。
- investigation\apply\enemy_write.py:61（BOSSISH 集合）、416-422（_rel_of）、610-701（make_npc_clone；:621-622 hp/soul、:624-627 isSoulGetByBoss=0/disableRespawn=0、:628-633 disableInitializeDead、:637-641 threatLv、:649-651 donor spEffect、:653-667 掉落抄位置行、:669-681 area effect、:693-700 压 hitRadius/Height）、752-855（patch_map）、899-909（check_owners）、912+（build）、1299-1351（bar_names 接线）、1750-1752（verify isSoulGetByBoss）。
- investigation\apply\bar_names.py:135-216（patch_evd）、219-242（patch_file）、245-263（verify_file）、277-324（targets_for_map）。
- investigation\enemy_places.csv：13 个目标行 2590/5378/5440/5865/5958/5959/6040/6094/6206/6207/6378/6721/18582；m31_22 蜗牛主实体 6230；m31_22 c4140 幻影 6225-6229。
- investigation\enemy_bar_names.csv：13 个 helper 行（如 m30_12/30120801=903700300、m34_14/34140851=902140001）。
- investigation\enemy_table.csv：13 个 npc 行（hp/get_soul 全 0）。
- randgui.py:1396/1438-1450（敌人摆放控件）、1695-1728（_ev1_options）、5411/5420-5423/5557/5595-5610（自检）。
- docs\参考实现_拆解\A_主流程与分类学.md:142-160（swapboss）、B_敌人写入与ER专属.md:161-183（helper 克隆/删除）、敌人分类_参考词汇表.md:251/256/265（mainhelper/swappable/combathelper）、:233（exclude:unkillable）、敌人随机_分类与平衡_设计v0.md:155（helper 永不独立随机）。
- docs\敌人随机_参考功能对照.md:27（**需订正**：swapboss 现状描述与事实不符）。
- 法魂包 EMEVD（mod\event\）：m30_12:114/117/149/152/157；m30_14:91/94/123/127；m31_06:55/67/74/82-95/106-114/111/112/119/124-128；m31_11:303/315/322/329/337-356/368-370/378；m31_15:16/34/66/123/125/135/138/140/148/152-156；m31_18:180/191/198/221/222/237；m31_22:246-280/273/282-296/285/288/290/291-295/295/298-316/300/301/303/306/310/312/314/315/318-330/332-337；m32_05:342/345/357-361/366-371/375-377/380/384/387/391-395/396/397/400-407/411/418/420；m34_14:159-173/161/164/166-170/175-211/186-209/190-194/208/209/210；m60_49_39:309-321/311/314/345/346；m12_07:173/177。
- common_func.emevd.dcx.js:7038（9005800 雾门/开战处理器）、:7098（9005801）、:7131（9005811）。
- 探针脚本（只读，investigation\_probe\）：B_duo_evt_scan.py、B_duo_facts.py、B_duo_hp.py、B_check_named.py、B_size_check.py。
