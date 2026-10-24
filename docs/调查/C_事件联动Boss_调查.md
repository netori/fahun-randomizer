# C. 事件联动 Boss 调查：`evt:pair/anim` 的成因、7 个位置逐个判读与救法

- 任务代号：C（probe-event-link）
- 日期：2026-10-24
- 调查范围：`investigation\enemy_places.csv` 中 evt 非空的 7 个 keep 位置；`enemy_data_build.py` 的 evt 推导；法魂 V3.0.3 反编译事件；参考实现 thefifthmatt/SoulsRandomizers
- 纪律：只读调查（未改任何仓库已有文件、未启动游戏、未动 git）；探针产物写在 `investigation\_probe\C_event_scan.json`、`C_fp_analysis.json`
- 证据约定：参考实现给 `file:line`；本仓库给 `file:line`；游戏数据给反编译 js 行号（`mod\event\<map>.emevd.dcx.js` 的行号）。标「未确认」的即为没有直接证据的推断。

---

## 0. 结论摘要（TL;DR）

7 个位置里：**1 个可以直接随（扫描假阳性）**、**1 个可以随但必须整组换（需加 yaml 组）**、**2 个要改事件才有可能救（不建议）**、**3 个是硬风险（保持 keep）**。另有 1 个（水银躯壳）keep 本身正确，但 keep 的「理由」标错了。

| # | 位置 (map/entity) | 敌人 | CSV 行 | evt | 运行时是否真有绑定 | 判定 | 处置 |
|---|---|---|---|---|---|---|---|
| 1 | m60_52_56_00 / 1052560800 | 火焰大主教 c3910 | 19928 | pair | **没有**（pair 只在未初始化事件 1052562820） | **可随** | 修 `scan_events`（去注释 + 有效事件闭包）；无需改事件 |
| 2 | m12_01_00_00 / 12010800 | 诺克史黛拉的龙人士兵 c4650 | 1201 | pair | 有（pair 801/802→800 + 801 的 anim 30002/20002 + 802 是 phase2） | **可随但须整组**（800/801/802 同模型同身份） | yaml 加 multiphase 组；先做实验 |
| 3 | m12_03_00_00 / 12030860 | 腐烂树灵 c4640 | 2233 | anim | 有（$Event 12030866:1466 休眠 30002 / :1473 起身 20002） | **需改事件**（不建议） | 若要救：新增 evd_edit「删/改 ForceAnimationPlayback」；否则 keep |
| 4 | m60_49_52_00 / 1049520850 | 死之鸟 c4980 | 18675 | anim | 有（$Event 1049520855:142 休眠 30000 / :145 起身 20000） | **硬风险 keep** | 已实测换玛尔基特后冻结、没 AI（M2 §7.11） |
| 5 | m60_49_57_00 / 1049570800 | 白金狼骑射手 c3170 | 18882 | pair | 有（pair 801→800 + 骑乘事件 1049572360 + 死亡联动） | **硬风险 keep** | 骑手/狼成对结构，换单边必坏 |
| 6 | m12_01_00_00 / 12010805 | 诺克斯蚁骑士（诺克斯修士 c3300 骑巨蚁 c4280） | 1194 | pair | 有（$Event 12012056:406 pair + 死亡/血条联动） | **硬风险 keep** | 已实测该图读档 0xc0000005（offset 0x3c8e22，两次同偏移） |
| 7 | m17_00_00_00 / 17000852 | 水银躯壳 c0100 | 4012 | pair | 有（pair 850/851→852），但它是 **HP 壳** | **keep 正确**（但理由应是 class None） | 不建议动；可把 keep 理由改准确 |

一句话机制：**我们现在的 evt 列是「对整个 js 文件做纯文本正则」**，不区分注释/死代码/真正被初始化的事件。所以 #1 是被**死代码**误判；#3/#4 是**真的**在事件里被强制播姿态；#2/#5/#6 是**真的** pair 结构。#3/#4/#5/#6 的共同点是「换模型后骨骼/动画槽/骑乘/受击转移对不上」——不是「npc id 变了事件里对不上」，回归测试（M2 §7.11）也证明是模型/动画层面的断裂，而不是 id。

---

## 1. 「evt:pair / evt:anim」这个 keep 原因是怎么来的

### 1.1 数据流（代码路径）

1. `investigation\apply\enemy_data_build.py:218-252` `scan_events()` 扫描 `mod\event\*.emevd.dcx.js`（跳过 `common*`），用 4 条正则全文找实体 id：

   ```python
   # enemy_data_build.py:211-215
   _PAIR_RE = re.compile(r"CreateReferredDamagePair\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
   _ANIM_RE = re.compile(r"ForceAnimationPlayback\s*\(\s*(\d+)\s*,")
   _COPY_RE = re.compile(r"CopyPlayerCharacterData\s*\(\s*10000\s*,\s*(\d+)\s*\)")
   _AIID_RE = re.compile(r"SetCharacterAIId\s*\(\s*(\d+)\s*,")
   _EVT_ORDER = ("pair", "copy", "aiid", "anim")
   ```

   结果 `{(map, entity_id): {flags}}`。**纯文本匹配：不排除 `//` 注释、不判断该 `$Event` 是否被 `InitializeEvent` 调用过、也不判断指令是否在 `if` 的真实分支里。**

2. `enemy_data_build.py:272-282` `attach_events()`：按 `(map, entity_id)` 落列，`entity_id == 0` 留空（事件点不到）；
3. `enemy_data_build.py:255-269` `_evt_blocks(r, pools)` 决定「这个绑定是否真的不允许换模型」：

   ```python
   flags = set((r.get("evt") or "").split(";"))
   if "pair" in flags:
       return True
   # copy / aiid 不一律 keep（用户确认梦之灾厄哥拉斯可随）
   return "anim" in flags and "waygate" in ((r.get("pools") or "") if pools is None else pools)
   ```

4. `enemy_data_build.py:497-506` `apply_layer()` 里正式判 keep，**顺序很重要**：`overrides.places` → `never_touch_npc_ids` → **multiphase 组** → **evt** → c0000 占位 → Sound 占位 → class.silo=false → keep_models/maps/npc_ids/places → 无数值 → randomize。evt 命中即 `policy="keep"`、`reason="evt:%s" % r["evt"]`（:506）。

5. yaml 里**没有** `evt:` 前缀（grep 0 命中）：这个 keep 原因是**运行时从磁盘 EMEVD 现算**的，不是人工 keep_lists。`enemy_data_build.py:893-912` 的 `--check` 会重跑 `scan_events()` 并逐行比对 evt 列，不一致直接 FAIL——所以修 `scan_events` 会同时改变表与 check 结果。

### 1.2 这 7 个位置在 `investigation\enemy_places.csv` 的整行

表头：`map,part_name,occurrence,entity_id,npc_id,think_id,chara_id,model,x,y,z,cls,cls_src,area,silo,tier,policy,pools,note,link,bar,evt,ref_size,ref_arena`

```
:1194  m12_01_00_00,c3300_9130,1,12010805,33001050,33100050,-1,c3300,366.552,-80.377,80.777,Basic,model,base,,,keep,waygate,evt:pair,,1,pair,0,0
:1201  m12_01_00_00,c4650_9000,1,12010800,46500960,1,-1,c4650,-49.640,-224.290,84.330,Boss,exact,base,,,keep,,evt:pair,,1,pair,2,0
:2233  m12_03_00_00,c4640_9000,1,12030860,46400050,46400010,-1,c4640,-216.210,92.234,-669.126,Basic,model,base,,,keep,waygate,evt:anim,,1,anim,0,0
:4012  m17_00_00_00,HP_Dummuy,1,17000852,21050000,-1,-1,c0100,-292.882,66.386,-294.302,None,model,base,,,keep,,evt:pair,,1,pair,0,0
:18675 m60_49_52_00,c4980_9000,1,1049520850,49801010,49800100,-1,c4980,-75.574,1051.078,94.029,NightMiniboss,model,base,,,keep,waygate,evt:anim,,1,anim,0,0
:18882 m60_49_57_00,c3170_9000,1,1049570800,31700100,31700050,-1,c3170,160.746,1391.714,-54.633,Basic,model,base,,,keep,waygate,evt:pair,,1,pair,0,0
:19928 m60_52_56_00,c3910_9000,1,1052560800,39101200,39101150,-1,c3910,-38.408,1674.697,63.654,Basic,model,base,,,keep,waygate,evt:pair,,1,pair,0,0
```

同 CSV 里的「伙伴」行（同一事件链，但**不在这 7 行里**，因为不在 waygate 池或 cls 不同）：

```
:1193  m12_01_00_00,c4280_9130,1,12010806,42801150,42800050,-1,c4280,366.284,-80.377,81.093,Basic,model,base,,,keep,,evt:pair,,0,pair,0,0
:1202  m12_01_00_00,c4650_9001,1,12010801,46500060,46500100,-1,c4650,-143.673,-224.499,110.362,Helper,exact,base,,,keep,,evt:pair;anim,,0,pair;anim,0,0
:1203  m12_01_00_00,c4650_9002,1,12010802,46500160,46500100,-1,c4650,-147.221,-224.499,114.050,Helper,exact,base,,,keep,,evt:pair,,0,pair,0,0
:4011  m17_00_00_00,c2105_9000,1,17000850,21050000,21050000,-1,c2105,-271.009,66.386,-300.250,Dummy,auto:dummy,base,,,keep,,evt:pair;anim,,0,pair;anim,0,0
:4013  m17_00_00_00,c2151_9000,1,17000851,21050001,21050000,-1,c2151,-293.153,66.715,-295.597,Dummy,auto:dummy,base,,,keep,,evt:pair;anim,,0,pair;anim,0,0
:18878 m60_49_57_00,c3180_9000,1,1049570801,31800100,31800050,-1,c3180,160.236,1390.249,-53.731,Basic,model,base,,,keep,,evt:pair,,0,pair,0,0
```

`1052560801/802/803`、`1049570802`、`1049520851`、`12030861/862` 在 `enemy_places.csv` 里 0 行（不是 `type==2` 敌人 part 或不存在），所以「整组换」的可行范围要按 CSV 里有的实体来定。

---

## 2. 逐位置：事件读到了什么、换模型断在哪一步

> 行号 = `F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）\mod\event\<map>.emevd.dcx.js` 的行号。
> 事件结构：`$Event(id, Restart|Default, function(X0_4,...))`，由 event 0 里的 `InitializeEvent(slot, id, args...)` / `InitializeCommonEvent(slot, template, args...)` 激活。**没被初始化的 `$Event` 是死代码。**

### 2.1 m12_01_00_00 / 12010805 诺克斯蚁骑士（+ 12010806 巨蚁）— 硬风险

- 实体关系（MSB/CSV）：12010805 = 骑手（c3300 诺克斯修士），12010806 = 坐骑（c4280 Giant Ant），二者在 waygate 池里只有骑手 12010805（坐骑不是独立行）。
- 事件链：
  - event 0：`:21 InitializeCommonEvent(0, 9005810, 12010805, 12010000, 12010960, 12011960, 1084227584)`（守卫赐福）；`:147 InitializeCommonEvent(0, 9005995, 12010750, 12010725, 12010805)`（传送门）；`:149 InitializeCommonEvent(0, 90005875, 12010805, 30610, 921000)`（死亡奖励 + 旗标）；`:150 //InitializeEvent(0, 12012055, 0)` **被注释**；`:151 InitializeEvent(0, 12012056, 0)` 生效；`:152/153 InitializeCommonEvent(0, 90005890/90005891, 12010805, 12010807, ...)`（区域/墙）。
  - 生效的 `$Event(12012056)`（`:393-423`）：
    - `:395-398` 若 `EventFlag(12010805)` 已死：禁用 12010806/12010805 并按 Flag 处理；
    - `:402-407` `DisableCharacterAI(12010805)` → `EnableCharacterInvincibility(12010805)` → `DisableCharacterAI(12010806)` → `EnableCharacterInvincibility(12010806)` → **`:406 CreateReferredDamagePair(12010806, 12010805)`** → `DisableCharacterHPBarDisplay(12010806)`（坐骑不显示血条）；
    - `:414-415` 等 6 秒/受伤/玩家接近，`:416-417` 才 `EnableCharacterAI` 两只，`:418 SetBossBGM(921400)`，`:419 DisplayBossHealthBar(Enabled, 12010805, 0, 904810663)`；
    - `:420 WaitFor(CompareCharacterHPValue(12010805, Equal, 0))` → `:422 ForceCharacterDeath(12010806)`（骑手死坐骑必死）。
  - 死代码 `$Event(12012055)`（`:387-391`，未初始化）。
- 断点：pair 本身只做「伤害/HP 转移到骑手」+「死亡联动」；真正致命的是**骑乘（rider/mount）结构**。把骑手模型换成非坐骑模型（或把巨蚁换成别的模型）后，pair 还在（id 没变），但 MSB 的 rider 关系、坐骑生成、动画都不匹配 → 加载/生成期崩。**M2 §7.11 实测已证实**：12010805+12010806 被换成塔兰+Commoner 后读档 `0xc0000005`（offset `0x3c8e22`，两次同偏移），存档停在在该图（`docs\敌人随机_M2_写盘层报告.md:296`）。
- 判定：**保持 keep**。而且 12010806 不在 waygate 池/CSV 的 7 行里，整组换也无法用现有 pool 表达。

### 2.2 m12_01_00_00 / 12010800 龙人士兵 — 可随但必须整组（实验候选）

- 实体关系：12010800 = Boss 血条/HP 受体；12010801 = **可见的休眠体/前身**（同模型 c4650，Helper）；12010802 = **phase2 替换体**（同模型 c4650，Helper）。三者是「一个 Boss 的三副身体」，不是普通杂兵。
- 事件链：
  - `:20 InitializeCommonEvent(0, 9005810, 12010800, 71210, ...)` 赐福；死亡走手写的 `$Event(12012800)`（`:967-981`）：`WaitFor(CharacterHPValue(12010800) <= 0)` → `ForceCharacterDeath(12010801)`/`(12010802)` → 4 秒 → `HandleBossDefeatAndDisplayBanner(12010800, GreatEnemyFelled)` → `:980 SetEventFlagID(12010800, ON)` + 9109 + 61109（自己世界）。
  - 战斗初始化 `$Event(12012810)`（`:983-1045`，活）：
    - `:997-1000` 关 801/802 的 AI 与血条；`:1001 CreateReferredDamagePair(12010801, 12010800)`；`:1002 CreateReferredDamagePair(12010802, 12010800)`；`:1003-1004` 801/802 无敌；
    - `:1005-1007` 关 800 的重力/碰撞、禁用 802；
    - `:1008 ForceAnimationPlayback(12010801, 30002, true, false, false)`（**休眠姿态**）；
    - `:1009-1034` 等玩家进入区域（`InArea(10000, 12012801)`）/801 受伤/状态 436/2/5/6/260 → `:1027-1029` 启用 800+801 并 `ForceAnimationPlayback(12010801, 20002)`（**起身**）；
    - `:1035-1044` 3 秒后置旗标（12010840/12012803/12010801）、`:1042 EnableCharacterAI(12010801)`、`:1044 DisplayBossHealthBar(Enabled, 12010800, 0, 904650000)`。
  - **phase2**：`$Event(12012811)`（`:1077-1090`，活）`WaitFor(CharacterHasSpEffect(12010801, 13209))` → 置 12012811/12012802 → `:1082 EnableCharacter(12010802)` + `EnableCharacterAI(12010802)` → `IssueShortWarpRequest(12010802 → 12010801, 100)` → 90 帧后禁用 801。**13209 这个 SpEffect 在 m12_01 里只有 `:1079` 的 WaitFor，没有施加点**（未确认来源，见 §7）。
  - 相机：`$Event(12012835)`（`:1047-1054`）按 802 的 SpEffect 13208 切；`$Event(12012830)`（`:1056-1064`）反向切。
  - 初始化 `$Event(12012849)`（`:1099-1106`）把 800/801 交给通用模板 9005811/9005822/9005800/9005801。
- 断点：
  1. **只换 800（现在 evt 只 keep 800，801/802 因 Helper 且不在 waygate 池另有 keep 路径）**：身体可见的是 801（模型不变），名字/血条是 800（名字会变）→「身子还是原来的、名字换了」的假随机；且 801 的 anim 30002/20002 仍在。
  2. **整组换成同一新身份（800/801/802 同模型）**：pair 关系不变、死亡/banner 不变；但 `ForceAnimationPlayback(12010801, 30002/20002)` 要求新模型有这两段动画（30002=休眠、20002=起身，见常见 Boss 模板），若没有 → 与死之鸟同样的冻结风险。
  3. 13209 若由模型/AI 侧施加，新模型 phase2 可能**永不触发**（只有单阶段也能打死，但等于丢阶段）。
- 判定：**可以做，但要做成 yaml 的 multiphase 组**（整组同身份），并且必须先验证 13209 与 anim 30002/20002。给用户的建议是「实验 B」，不作为默认放开。

### 2.3 m12_03_00_00 / 12030860 腐烂树灵 — 需改事件（不建议）

- 先说清一个误传：任务书写「与菲雅英雄战同图」。**同图成立，共用事件/实体不成立**。菲雅战是 `:22-24`（`SetEventFlagID(12030800, ON)`、`$InitializeEvent(0, 12032810)`、`:29 12032849` 雾墙），腐烂树灵是 Event 12030866；12030860 在全文的引用只有 `:192-197`（初始化）与 `:1456-1482`（自己的事件）。
- 事件链：
  - event 0：`:192 InitializeCommonEvent(0, 9005810, 12030860, 12030000, ...)`（赐福）；`:193 InitializeCommonEvent(0, 9005995, 12030750, 12030725, 12030860)`（传送门）；`:194 InitializeCommonEvent(0, 90005876, 12030860, 12030861, 904640000, 920600)`（Boss 开始：AI/血条/BGM）；`:195 InitializeCommonEvent(0, 90005875, 12030860, 30640, 920600)`（死亡奖励）；`:196/197 90005890/90005891`（区域/墙）；`:198 InitializeEvent(0, 12030866)`。
  - `$Event(12030866)`（`:1452-1487`，活）：
    - `:1453-1455` 关墙资产；`:1456` 若已死则禁用+death；
    - `:1463 DisableCharacterAI(12030860)`；`:1464` 无敌；`:1465` 关血条；
    - **`:1466 ForceAnimationPlayback(12030860, 30002, true, false, false)`（休眠）**；
    - `:1472 WaitFor(InArea(10000, 12030861))` → **`:1473 ForceAnimationPlayback(12030860, 20002, false, false, false)`（起身）**；
    - `:1475 EnableCharacterAI`、`:1476` 关无敌、`:1478` 等 4.3 秒、`:1479 DisplayBossHealthBar(Enabled, 12030860, 0, 904640000)`；
    - `:1482 WaitFor(EventFlag(12030860))` 后关墙。
  - Boss 开始/AI 是 `90005876` 模板（common_func `:7843-7869`）：进区 → 4 秒/受伤/近 4 米 → 才 `EnableCharacterAI`。
- 断点：**与死之鸟一模一样的机制**——先强制 30002（休眠），玩家进区强制 20002（起身），之后才交还 AI。换模型后新模型的动画槽里没有 30002/20002（或姿态差异大）→ 模型卡在奇怪姿势，`90005876` 的 EnableAI 条件也可能因为「受伤/接近」判定在姿态卡住时不成立 → 实测症状就是「站着不动、没 AI」（M2 §7.11 对死之鸟的实测：`docs\敌人随机_M2_写盘层报告.md:297`）。
- 救法：只能改事件。最小改动是**删掉或按模型改掉 `:1466` 和 `:1473` 两条 ForceAnimationPlayback**（或整体改成 90005200/90005211 通用待机模板）。这需要 `evd_edit.py` 增加一个「改/删指令」函数（现只在 `:170-221` 有 neutralize：改参数区首 u32 + 追加 arg blob，不改指令个数）。风险：改事件是本项目最危险的操作；且删掉休眠动画后，Boss 会一开始就站着，但 `90005876` 的「进区→开 AI」逻辑不受影响，可能反而更简单——不过没有实测前不能保证。
- 判定：**默认 keep**；如果将来要做「改事件版」，它和死之鸟可以共用同一个函数，先拿死之鸟（单文件 148 行）做实验。

### 2.4 m17_00_00_00 / 17000852 水银躯壳 — keep 正确（但不是因为 pair）

- 这张图（m17）是法魂新增的「伪龙王达格拉夫」两阶段场（17000800 c4390 / 17000810 c4391），另有 Silver Tear Boss：17000850/17000851 是可见体（c2105/c2151，CSV 里 cls=Dummy），**17000852（c0100 水银躯壳）是它的 HP 壳**。
- 事件链：event 0 `:127-132` 初始化 17000853（Init）/17000854（Death）/17000855-857（Stance）/17000858（Crawl）。
  - `$Event(17000853)`（`:442-493`，活）：`:444 DisableCharacterAI(17000852)`；`:460 DisableCharacterCollision(17000852)`；`:461 DisableCharacterGravity(17000852)`；`:467 ForceAnimationPlayback(17000850, 30001, ...)`（本体休眠）；**`:468 pair(17000850 → 17000852)`；`:469 pair(17000851 → 17000852)`**；`:471 DisableLockOnPoint(17000850, 220)`；`:472-477` 关 850/851 的 AI/血条/无敌；`:492 DisplayBossHealthBar(Enabled, 17000852, 1, 902036020)`。
  - `$Event(17000854)`（`:496-519`，活）：`WaitFor(HPRatio(17000852) <= 0)` → 关 850/851 无敌 → `ForceCharacterDeath(850, true)/851/852` → banner on 17000850 → `:518 SetEventFlagID(17000850, ON)`。
  - `$Event(17000858)`（`:574-610`，Retreat/Heal）：`:587 SetSpEffect(17000852, 10469)`，`:592-600` 等 5 轮，`:601 ClearSpEffect`。
- 断点：17000852 是**血条+受伤转移的受体**，本体是 850/851。换 17000852 的模型/身份 = 换掉「血量壳」，pair 仍把伤害转给它，但它的 AI/碰撞/重力本来就是关的、class=None；换它只会在死亡判定/血条上制造不一致。
- 判定：**keep 正确**。但 keep 的**理由**标成 `evt:pair` 会误导（真正的理由是 class None + HP 壳）。建议未来把 keep 理由改成「class None / HP 壳」，不是改行为。

### 2.5 m60_49_52_00 / 1049520850 死之鸟 — 硬风险（已实测）

- 文件仅 148 行。event 0：`:22 InitializeCommonEvent(0, 90005876, 1049520850, 1049520851, 904980600, 920900)`（Boss 开始/AI/血条）；`:23 90005875(1049520850, 30535, 920900)`（死亡奖励）；`:30 9005995(1049520750, 1049520725, 1049520850)`（传送门）；`:31 9005810(...)`（赐福）；`:28 90005892(...)`（墙）；`:21 InitializeEvent(0, 1049520855)`。
- `$Event(1049520855)`（`:139-148`，活）：`:141 EndIf(EventFlag(1049520850))`；**`:142 ForceAnimationPlayback(1049520850, 30000, true, false, false)`（休眠）**；`WaitFor(InArea(10000, 1049520851))`；**`:145 ForceAnimationPlayback(1049520850, 20000, true, false, false)`（起身）**；`:146 WaitFor(CharacterDead)`。
- 断点：换模型后 30000/20000 找不到/姿态不匹配 → 模型冻结；M2 §7.11 记录实测：1049520850 换成玛尔基特后「脚本强制播 30000（休眠）/20000（起身）→ 站着不动、没 AI」。
- 参考实现也承认这类难改：`EnemyRandomizer.cs:7448-7452` 对 `changed && locEntity == 2047390800`（死仪鸟家系）直接 `forceRemove`（把事件删掉），说明连上游项目都不打算兼容。
- 判定：**硬风险 keep**。要救必须改事件（删/改 `:142`/`:145`），与 §2.3 同一个函数，不建议。

### 2.6 m60_49_57_00 / 1049570800 白金狼骑射手 — 硬风险

- 实体关系：1049570800 = 骑手（c3170，血条/死亡判定实体）；1049570801 = 狼（c3180，坐骑）。**这是法魂的「骑乘对」结构**，与 §2.1 同类但事件更复杂。
- 事件链：
  - event 0：`:11 9005810(1049570800, 1049570000, ...)`（赐福）；`:20 InitializeEvent(0, 1049572360, 1049570800, 1049570801)`（骑乘逻辑）；`:25 9005995(1049570750, 1049570725, 1049570800)`（传送门）；`:30 InitializeEvent(0, 1049572355, 0)`；`:33 90005875(1049570800, 30570, 921400)`（奖励）；`:34 90005890(1049570800, 1049570810, 1049570805)`；`:35 InitializeEvent(0, 1049572361, 1049570800, 1049570810, 1049570802)`（墙）。
  - `$Event(1049572355)`（`:76-104`，活）：`:85-90` 关 800/801 AI、给 800/801 无敌、**`:89 CreateReferredDamagePair(1049570801, 1049570800)`**、关 801 血条；`:91` 等玩家进区；`:96` 等 6 秒/受伤/近 4 米；`:97-98` 才 `EnableCharacterAI(801/800)`；`:99 SetBossBGM(921400)`；`:100 DisplayBossHealthBar(Enabled, 1049570800, 0, 904810661)`；`:101 WaitFor(HP(800) == 0)`；`:103 ForceCharacterDeath(1049570801)`（骑手死→狼死）。
  - `$Event(1049572356)`（`:106-111`，活）：`WaitFor(CompareHPRatio(1049570800, LessOrEqual, 0.6))` → `ForceAnimationPlayback(1049570802, 3009)`（802 是墙/场景资产，不在 CSV）。
  - `$Event(1049572360)`（`:113-130`，活，骑乘）：`WaitFor(CharacterHasSpEffect(801, 11893) && 两者未死)` → **`:120 WarpCharacterAndSetFloor(801 → 800, 283, 0)`**（把狼定到骑手位置）→ `:122 ForceAnimationPlayback(801, 20003)` → `:123-124 SetSpEffect(800/801, 11880)` → `:125 RequestCharacterAIReplan(800)` → 5 秒后 `SetNetworkUpdateRate(false)` + RestartEvent。
- 断点：换骑手成非骑乘模型 → 狼还在但骑手姿势/位置不匹配；换狼 → 骑乘 warp/动画 20003 失败；整对换需要找到「骑手+同骨架坐骑」的组合（现池里没有这种 pair 表达）。即使 pair 保持（id 不变），骑乘的那 3 条指令也会把新模型摆成错误姿态。
- 判定：**硬风险 keep**。

### 2.7 m60_52_56_00 / 1052560800 火焰大主教 — 可随（扫描假阳性）

- 文件 160 行。**运行时真正生效的只有 6 条通用模板**：
  - `:11 RegisterBonfire`；`:12 InitializeCommonEvent(0, 9005810, 1052560800, 1052560001, 1052560951, 1052561951, 0)`（赐福）；`:23 InitializeCommonEvent(0, 9005995, 1052560750, 1052560725, 1052560800)`（传送门）；`:24 InitializeCommonEvent(0, 90005876, 1052560800, 1052560801, 904810659, 920900)`（Boss 开始/AI/血条）；`:25 InitializeCommonEvent(0, 90005875, 1052560800, 30525, 920900)`（死亡奖励）；`:26 90005890(1052560800, 1052560801, 1052560801)`（区域）；`:27 90005891(1052560800, 1052560801, 1052560802)`（墙）。
  - `:30 InitializeEvent(0, 1052562810, 1052565550, 1052562900)` 只对场景资产 1052565550 做 SpEffect 开关（`:33-56`），与敌人无关。
- **被注释/未初始化的死代码**：`:14 //90005860`、`:15 //InitializeEvent(0, 1052562815, ...)`、`:16 //InitializeCommonEvent(0, 90005211, 1052560800, 30000, 20000, ...)`、`:18 //InitializeEvent(0, 1052562820, 0)`、`:19 //1052562821`、`:20 //1052562830`、`:22 //Erdtree Warps`。
  - `$Event(1052562815)`（`:58-108`）双血条管理（1052560803）；
  - **`$Event(1052562820)`（`:110-123`）才是 pair 的来源**：`:120-122 CreateReferredDamagePair(1052560800 → 1052560803)/(1052560801 → 1052560803)/(1052560802 → 1052560803)`；
  - `$Event(1052562821)`（`:125-147`）死亡同步；`$Event(1052562830)`（`:149-165`）换体/动画（ForceAnimationPlayback(1052560801, 20020)）。
  - 全部**未初始化** = 运行时不存在。
- 断点：**没有**。运行时没有活 pair、没有活 anim；只剩 90005876 的 AI/血条和 90005875 的奖励。换模型后需要处理的只是血条名（`bar_names.py` 可自动改名；若换入模型没名字则写占位 999999999）。
- 判定：**可随**。这就是那 1 行假阳性：`C_event_scan.json` 里 pair 共 21 条，其中 3 条属于未初始化事件、2 条属于注释；全表 232 行 evt 非空中，「evt 要求 keep 但磁盘上没有活绑定」的**只有这一行**。

---

## 3. 参考实现（thefifthmatt/SoulsRandomizers）怎么处理

仓库：`C:\Users\20905\AppData\Local\Temp\dsh_gh\sr`（C# 源码）。结论：**它根本不按 EMEVD 绑定排除 Boss，而是反过来——换人之后重写事件。** 这是和我们最本质的差别。

### 3.1 它不把「事件联动」当排除条件

- `RandomizerCommon\Enemy\EnemyRandomizer.cs`（ER 路径）里没有「CreateReferredDamagePair / ForceAnimationPlayback → skip 该实体」的规则；全仓库 `CreateReferredDamagePair` 的**代码命中为 0**（我 grep 过）。
- 分类表 `EldenRingRandomizer\locations.txt`：`:141` 有 `Major boss in Ainsel River: Dropped by Dragonkin Soldier of Nokstella`；死之鸟/死仪鸟按 `Minor night boss`/`Minor boss` 列出（`:41,105,106,170,222` 等）。也就是说 §2.2 的龙人士兵、§2.5 的死之鸟在参考实现里都是**普通 Boss**，照随机不误。
- 它给每个位置/实体提供**事件模板**（events.txt，不在检出里），换人时按模板**重写事件**，把旧动画 id 换成新模型的动画 id，或置 -1 删掉。

### 3.2 动画事件重写（可直接抄的做法）

`EnemyRandomizer.cs:7396-7474`（事件改造主循环）：

```csharp
// 7396-7413 取来源实体
var changed = mapping.GetRandomizedSource(locEntity, ...);
// 7414-7421 来源带 hidden 标记 → 事件整个删掉
if (hidden) { ... forceRemove ... }
// 7422-7428 取来源实体在它的模板里的动画对
anims = startingAnimations[source];
// 7429-7440 type==gravity 且目标没有 primary arena → anims = null（清空）
// 7442-7452 type==gravityarg：按 drop tag 改 arg
// 7448-7452 死仪鸟特例：changed && locEntity == 2047390800 → forceRemove
// 7454-7456 eventIndices = type == wakeup ? [-1, 2] : [2, 3]
// 7457-7470 把事件里的旧动画 id 替换成 anims[a]（>0 时），否则 -1
events.ReplaceMacro(..., type: EventValueType.Animation)
```

构造 `startingAnimations`：`EnemyRandomizer.cs:4369-4370` 定义 `Dictionary<uint,(int,int)>`；`:4509-4625` 从模板调用点解析出 type 与两个动画 id：`:4603-4611` `wakeup` 时 `anims=(0, parsePart2)`，否则 `(parsePart2, parsePart3)`；`:4620-4624` 只记非 gravity 的。

事件模板的元语：`RandomizerCommon\Enemy\EnemyAnnotations.cs:856-886` `SpecialAnim`（字段 `InitType`/`InitAnim`/`InitStr`/`CancelType`/`CancelAnim`/`CancelStr`/`Type`）；注释 `:867-883` 明确列出 type 语义（wakeup/root/climb/invincible/lunge/dropdown/float/passive）以及每类需要额外加的编辑（**加 AI enable/disable、加受伤条件**）。`:779-826` 是 `EnemyClass` 枚举（`Boss=3, Miniboss=2, NightMiniboss=18, Helper=4, None=100`）。

条件组：`EnemyRandomizer.cs:7831-7850` —— 只有 `t.Animation == null && game.EldenRing` 才 `AdjustConditionGroups`，即有动画事件的实体**不调条件组**（避免二次破坏）。

### 3.3 它对 pair 的处理

全仓库唯一相关代码：`EldenEnemyEditor.cs:961-970`「Undo CreatedReferredDamagePair」——只处理 Hoarah Loux p2（`47210070`）从 p1（`47200070`）继承血量：

```csharp
// EldenEnemyEditor.cs:961-970（大意）
if (hoarah1dead) {
    var hp = hoarah2.hp - hoarah1.hp;     // 去掉 p1 那份血
    if (hp > 500 && hp < 5000) hoarah2.hp = hp;
}
```

也就是说：**参考实现把 pair 当「血量数值关系」处理，而不是当「不能换」的结构约束**；它敢换是因为它会重写事件（pair 本身在事件里，它按模板重建）。具体每只 Boss 的 pair 重写条目在 events.txt（不在检出内）→ **未确认**。

### 3.4 我们能抄什么（按性价比排序）

1. **对动画事件：换模型后改写/删掉 ForceAnimationPlayback**（`:7454-7470`）。这正好是 §2.3/§2.5 的救法，但我们需要先有「改/删指令」的 evd_edit 函数。
2. **hidden 来源直接删事件**（`:7414-7421`）：如果换入的模型明显不适合该事件，干脆把事件删了（Boss 变普通敌人）。
3. **事件模板里加 AI enable/disable + 受伤条件**（`EnemyAnnotations.cs:867-883`）：这正是 90005200/90005211 那套「休眠→起身」模板在做的事；参考实现通过模板参数化，我们也可以把「30002/20002 硬编码」换成「按新模型取 anim id 或跳过」。
4. 不建议抄它的 pair HP 补正（针对 Hoarah Loux 的专用补丁，与我们的 7 个位置不对应）。

---

## 4. 假阳性量化 + `scan_events` 的修复方案

### 4.1 量化（探针结果）

探针：扫描 `mod\event\*.emevd.dcx.js`（跳过 `common*`），去 `//` 注释，按 `$Event(id, ...)` 块归属，从 event 0 起沿 `InitializeEvent`/`InitializeCommonEvent` 的**字面量目标**做 active 闭包，分类 pair/anim，再与 `enemy_places.csv` 的 evt 列 join。结果写入：

- `investigation\_probe\C_event_scan.json`：逐 (map, entity) 的 pair/anim 归属与「活/死事件/注释」标记；
- `investigation\_probe\C_fp_analysis.json`：与 CSV join 后的假阳性清单。

统计：

| 分类 | 总匹配 | 活 | 死事件内 | 注释内 |
|---|---|---|---|---|
| pair | 21 | 16 | 3 | 2 |
| anim | 737 | 691 | 31 | 15 |

- CSV 里 evt 非空共 **232 行**。
- 「evt 要求 keep、但磁盘上没有任何**活**绑定」= **1 行**：`m60_52_56_00/1052560800 evt=pair`（唯一死 pair 在未初始化事件 1052562820；其余两条死 pair 的伙伴 1052560801/802 不在 CSV；注释 pair 在 `m12_01:2092-2093` 神皮组，但那里被 multiphase keep 覆盖且另有活 anim）。
- waygate 池 27 行状态：22 行已 `randomize`；`keep` 4 行 = 12010805(pair 活)/12030860(anim 活)/1049520850(anim 活)/1049570800(pair 活)；另有 `12070805`（拟态泪 c1000，class None）keep；假阳性 1 行（1052560800）。
- 其他：`1049570802` 有活 `ForceAnimationPlayback(1049572356:109)`，但它不在 CSV；`12010805` 的坐骑 12010806 的 evt=pair 行也 keep。

### 4.2 修复方案（在 `enemy_data_build.py` 内，最小改动）

目标：把「文本里有」变成「运行时真的会被执行」。三步，全部在 `scan_events()`（`:218-252`）内完成，`_evt_blocks` 不用改：

1. **去注释**：逐行处理，跳过 `^s*//`；块注释（`/* ... */`）如存在也去掉（先 grep 确认量）。注释行直接剔除，再对剩余文本跑正则。
2. **active 事件闭包**：先解析所有 `$Event(d+,s*(Restart|Default)s*,s*function` 块边界；从 event 0 的 `InitializeEvent(slot, id, args...)` / `InitializeCommonEvent(slot, template, args...)` 开始收集「被初始化的事件 id」，反复迭代直到不动点（事件里还会再 InitializeEvent）。**只有落在 active 集合里的 `$Event` 块内的指令才算绑定。** 模板 `90005200/90005211` 在 `common_func` 里，但它们的动画 id 是**调用点实参**传入的（如 `m60_49_57:12-14 90005211(1049570251, 30003, 20003, ...)`），所以若要覆盖这类绑定，还需要：遇到 `InitializeCommonEvent(0, 90005200|90005211, X0, X4, X8, ...)` 时把 `(X0, X4)` 记为 anim（X4=休眠动画）——这是当前 scan 的**盲区**，本次 7 行不受影响，但修的时候可以顺手补上（否则 m60_49_57 的 1049570251/252/259 这类普通杂兵会被漏标；它们现在也被 90005211 强制姿态，理论上换模型同样有冻结风险）。
3. **保留 unresolved**：对无法静态判定的调用（模板、变量实参）保守 **不标**，但不要因此 keep——现状是靠人工回归测试兜底。

影响面：232 行里只有 1 行会从 keep 变成 randomize（1052560800）；其余 231 行不变。风险低、收益明确，所以值得修。

改完后 `enemy_data_build.py:893-912` 的 `--check` 会自动重新验证（它会重算 evt 列并与 CSV 比对）。

> 注意：这修的是「假阳性」。真正的 anim/pair 绑定（§2.2/§2.3/§2.5/§2.6）仍然会 keep，不会因为修 scan 就放开——这是对的。

---

## 5. 方案与要改的文件

### 5.1 立即可做：放开 1052560800（火焰大主教）

| 项目 | 内容 |
|---|---|
| 要改的文件 | `investigation\apply\enemy_data_build.py`（`scan_events()`，:218-252）；然后重新生成 `investigation\enemy_places.csv`（:19928 行 policy→randomize、evt 清空、reason 走 waygate_guardian 规则） |
| 不需要改 | yaml 不用加任何东西（waygate_guardian 规则已覆盖）；`evd_edit.py` 不用改；`bar_names.py` 自动改名（904810659 火焰大主教 → 新模型对应名字；若 enemy_bar_names.csv 没有新名字则写 PLACEHOLDER 999999999） |
| 风险 | 低。只剩：新模型 AI 是否兼容（一般可以）、血条名显示、奖励 lot 30525、传送门解锁（依赖 EventFlag(1052560800)，与模型无关） |
| 验证 | 见 §6 实验 A |

### 5.2 可选：12010800 龙人士兵整组（实验 B）

在 `enemy_classes_v3.yaml` 的 `multiphase.groups`（`:144-159`）加一组（写法参照 `godskin_scion`）：

```yaml
- id: nokstella_dragonkin
  phases: [12010800, 12010801, 12010802]   # 全部同模型，数据层全 keep
  bosses: [[12010800, 12010801, 12010802]] # 一个 Boss，三实体同身份
  pair: true
  swap: true
  sources: [12010800]
  note: "诺克史黛拉的龙人士兵：800=血条受体/801=休眠可见体/802=phase2；13209 来源未确认"
```

前置条件（不满足就别做默认放开）：① 确认 13209 施加点（否则 phase2 不触发，等于单阶段）；② 验证新模型的 30002/20002 动画；③ 参考 `multiphase_boss` 规则 note 的警告——「有 pair 绑定的组不开（安塞尔河坏档的根因）」，虽然那是 rider+mount，不完全是同一 boss 的多阶段，但风险同类，必须先单图验证。

### 5.3 需改事件才可能救：12030860、1049520850（不建议）

- 现状 `evd_edit.py:170-221` 的 `neutralize` 只能改参数区首 u32 + 追加 arg blob，**不能删指令**（docstring 警告删指令会让 arg 替换表按指令下标错位）。要「删/改 ForceAnimationPlayback」需要新增一个小函数，比如 `retarget_anim(eid, inst_index, new_id_or_del, ...)`：把指令的实体/动画参数 u32 改掉，或把该指令替换成等长的 no-op（如果存在），或按 append-arg 机制重写参数块。
- 改哪条：12030860 改 `m12_03:1466/1473`；1049520850 改 `m60_49_52:142/145`。可以先把动画 id 改成「新模型自己的」而不是删——但那需要知道新模型的动画表，工作量更大。
- 风险：事件改写不可回滚（除快照）、可能连带 `90005876` 的 WaitFor 条件失效、影响全图；建议放到最后一个里程碑，且先用 1049520850（单文件）做实验。

### 5.4 硬风险，建议不做：12010805、1049570800、17000852

- **12010805（诺克斯修士+巨蚁）**：已实测坏档（`0xc0000005`，offset `0x3c8e22`，两次同偏移）；这是骑乘对，安全换法必须整对换（骑手+坐骑同骨架），而 12010806 不在 waygate 池、CSV 里也只有 1 行，无法表达整对；收益低（一个守门位），风险最高。**不做。**
- **1049570800（白金狼骑射手）**：骑乘对 + 4 条骑乘/死亡联动指令（pair、WarpCharacterAndSetFloor、动画 20003、ForceDeath 狼）。**不做。**
- **17000852（水银躯壳）**：不是 Boss，是 Silver Tear Boss 的 HP 壳（class None 本就不该随机）。**不做**；建议只是把 keep 理由写准确。

---

## 6. 最小可验证实验（按优先级）

### 实验 A（最高性价比）：1052560800 火焰大主教

1. 前置：`scan_events` 修复（或临时在 yaml `overrides.places` 给它 `policy: randomize, reason: probe`，不改 scan；但正式版应修根因）。
2. 重建表 → `enemy_plan.py` 生成计划（只该图该位，其余不动）→ `enemy_write.py` 写盘（`NpcParam` 克隆 + MSB 改写 + 血条名）。
3. 进游戏（m60_52_56 火焰大主教场）：观察
   - 进场后 AI 是否正常（应该不用「休眠/起身」这套）；
   - 血条名显示是否为新怪名（或 `?NpcName?`）；
   - 击杀后：奖励 lot 30525 是否到手、传送门 9005995 是否因 EventFlag(1052560800) 解锁；
   - 存档/读档/再次传送不崩。
4. 成功判据：无 crash、AI 正常、血条名正确或占位、奖励与门锁正常。失败则回滚（manifest 的 revert 路径）。

### 实验 B（次优）：12010800 龙人士兵整组（单图、只改该 Boss）

1. 前置：yaml 加 §5.2 的 multiphase 组；先只在该图做，不参与全图随机。
2. 进游戏：观察进场（休眠体 801 是否用新模型、姿态是否正常）→ 进区起身（20002）→ 受伤/打死 801 → 是否触发 802（看 13209）→ 血条 904650000、banner、死亡奖励。
3. 成功判据：三段都正常、新模型动画不冻结、死亡后旗标/奖励正常、读档不崩。
4. 若失败但单阶段能打（802 不触发）：可降级为「只当单阶段 Boss 随机」，仍然比 keep 好，但要接受丢阶段。

---

## 7. 未确认事项（写报告时明确标注，不编）

1. **13209 的施加点**：m12_01 里只有 `$Event(12012811):1079` 的 WaitFor，没有事件内施加；很可能是 NpcParam/AI/Silver Tear 类似逻辑（SpEffect 由 AI 或别的系统上），**未确认**；phase2 是否触发取决于它。
2. **12010800 的奖励来源**：其死亡事件 12012800 没有 90005875（手写 banner+SetFlag），奖励可能走 MSB lot 或别的事件，**未确认**。验证实验时要看实际掉落。
3. **死之鸟「没 AI」的精确机制**：M2 §7.11 是实测症状（换玛尔基特后冻结、没 AI），但「是动画状态机卡住，还是 90005876 的 WaitFor 条件不满足」没有逐帧验证 → **未确认**。
4. **12010805 崩溃的精确原因**：只有 `0xc0000005` + offset `0x3c8e22`（两次同偏移）和「pair/骑乘」的机制推断，没有 crash dump 符号 → **未确认**。
5. **参考实现 events.txt 的 pair 重写条目**：检出里没有数据目录（glob 空），只能确认它「重建事件、用模板」；具体每只 Boss 的 pair 条目 → **未确认**。
6. **scan 的 anim 盲区**：90005200/90005211 这类「模板执行、动画 id 从调用点实参传入」的绑定，当前 scan 识别不到（本次 7 行不受影响，但 §4.2 建议顺手补）。

---

## 8. 证据索引

### 8.1 反编译事件（行号为 mod\event\*.js）

| 文件 | 关键行 |
|---|---|
| `m12_01_00_00.emevd.dcx.js` | :20-21（赐福）、:147-157（传送门/奖励/12012055 注释/12012056）、:387-391（12012055 死代码）、:393-423（12012056：pair :406、血条 :419、死亡联动 :420-422）、:967-981（12012800 死亡）、:983-1045（12012810 trio 初始化/anim :1008/:1029/血条 :1044）、:1047-1064（相机 13208）、:1077-1090（13209 phase2） |
| `m12_03_00_00.emevd.dcx.js` | :22-24（菲雅战 flag，与树灵无关）、:191-198（Erdtree Waygate 6 条模板）、:1452-1487（12030866：休眠 :1466 / 起身 :1473 / 血条 :1479） |
| `m17_00_00_00.emevd.dcx.js` | :127-132（Init/Death/Stance/Crawl）、:442-493（17000853：pair :468-469、anim 30001 :467、血条 :492）、:496-519（17000854 死亡）、:574-610（17000858 Heal） |
| `m60_49_52_00.emevd.dcx.js` | :11-33（event 0 全部初始化）、:139-148（1049520855：休眠 :142 / 起身 :145） |
| `m60_49_57_00.emevd.dcx.js` | :11-35（event 0）、:76-104（1049572355：pair :89、血条 :100）、:106-111（1049572356）、:113-130（1049572360 骑乘）、:133-145/148-152（墙/碰撞） |
| `m60_52_56_00.emevd.dcx.js` | :11-30（event 0，含 :14-20/:22 注释行）、:33-56（只动资产）、:58-108（1052562815 死代码）、:110-123（1052562820：pair :120-122 死代码）、:125-147（1052562821 死）、:149-165（1052562830 死） |
| `common_func.emevd.dcx.js` | :7827-7840（90005875）、:7843-7869（90005876）、:9048+（9005995 传送门）、:10/:262（90005200/90005211）、:8161-8187（90005890/91）、:8190+（90005892） |

### 8.2 本仓库

| 位置 | 内容 |
|---|---|
| `investigation\apply\enemy_data_build.py:45` | COLS 含 evt |
| `:211-215` | 4 条正则 + 顺序 |
| `:218-252` | scan_events（纯文本、不排注释/死代码） |
| `:255-269` | _evt_blocks（pair 全 keep；anim 仅 waygate） |
| `:272-282` | attach_events |
| `:497-506` | apply_layer 的 keep 顺序与 evt 分支 |
| `:893-912` | --check 重算 evt |
| `investigation\apply\evd_edit.py:170-221` | neutralize（只改参数区首 u32 + append arg，不能删指令） |
| `investigation\apply\enemy_emevd.py`（576 行） | 血条名/BGM 参数槽改写 |
| `investigation\apply\bar_names.py`（362 行） | 血条名替换、支持 90005876/InitializeEvent 转交、占位 999999999 |
| `investigation\apply\data\enemy_classes_v3.yaml:82-94` | l4_policy 顺序 |
| `:132-143/:144-159` | multiphase 组语义与 14 组（12010800/801/802 不在其中） |
| `:161-203` | pools.waygate 27 成员（12010805/12030860/1049520850/1049570800/1052560800 在内；12010800/17000852 不在） |
| `:360-373` | multiphase_boss 警告 + waygate_guardian 规则 |
| `investigation\enemy_places.csv` | :1194/:1201/:2233/:4012/:18675/:18882/:19928 + 伙伴行 :1193/:1202/:1203/:4011/:4013/:18878 |
| `investigation\_probe\C_event_scan.json` / `C_fp_analysis.json` | 探针结果（本任务产物） |

### 8.3 文档

- `docs\敌人随机_M2_写盘层报告.md:288-318`（§7.11，用户实测与 pair/anim 事故记录；:296 坏档偏移、:297 玛尔基特冻结；:307-314 最终粒度）
- `docs\敌人随机_假设台账.md:43/45/48`（H-034 pair 不能换、H-035 anim 仅守门位必须保持、H-039 多阶段组不能整组替换）
- `docs\敌人随机_传送门_可换性验证.md`（奖励=90005875 按 entity id、开锁=EventFlag(守门实体)，换 npc 本身不破坏奖励/开锁）
- `docs\敌人随机_传送门_资料考证.md:42-77`（30 个守门实体表）、`:144-148`（参考实现无 waygate 规则）
- `docs\发布\更新日志_v1.3.15.md:18-35,55,71-97`（pair 组首次默认整组换；「理论上实体 id 不变 pair 就还在」）

### 8.4 参考实现

- `RandomizerCommon\Enemy\EnemyRandomizer.cs:7396-7474`（动画事件重写：hidden 删事件 :7414-7421、动画替换/置 -1 :7454-7470、死仪鸟特例 :7448-7452、gravity :7429-7452）
- `EnemyRandomizer.cs:4369-4370,4509-4625`（startingAnimations 构建，wakeup :4603-4611）
- `EnemyRandomizer.cs:7831-7850`（只有 t.Animation==null && EldenRing 才 AdjustConditionGroups）
- `EnemyAnnotations.cs:856-886`（SpecialAnim 模板）、`:779-826`（EnemyClass 枚举）
- `EldenEnemyEditor.cs:961-970`（Hoarah Loux pair 的 HP 补正）
- `EldenRingRandomizer\locations.txt:141` 等（龙人士兵/死鸟按普通 Boss 列）

---

## 9. 给 lead 的一句话建议

- **默认放开 1052560800**（修 scan_events 的 1 行假阳性），这是 7 个里唯一低风险、无需改事件、有明确验证路径的。
- **12010800 做成 multiphase 实验组**（整组换），先确认 13209 与动画 30002/20002，成功再默认开。
- **12030860 / 1049520850 保持 keep**；要救必须先有 evd_edit 的「改/删 ForceAnimationPlayback」能力，且建议先拿 1049520850 单文件做。
- **12010805 / 1049570800 / 17000852 保持 keep**（前者有坏档实证，后两者是骑乘对/HP 壳）。
