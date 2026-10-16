# 敌型表 v2 —— 用参考实现自带的模型名表重建

> 由 `investigation/apply/enemy_type_map_v2.py` 生成，可重跑。
> 只读输入：法魂 MOD（只读）/ 本仓库 investigation 产物 / 参考实现 `Elden Ring Randomizer 428 v0.12.2 .../randomizer/diste`（只读）。

## 0. 一句话结论

- v1 只有 **161/462 (34.8%)** 的模型有权威名字，其余 301 个靠体型兜底、全标 low。
- v2 用参考实现的 `Names/ModelName.txt`（**按模型给名字**的那张表）之后：**398/462 (86.1%)** 拿到英文名，**423/462 (91.6%)** 的类别是**由名字判出**的。
- 未拿到具体类的模型从 v1 的 277 个降到 **33 个**。

## 1. 参考实现给了什么

| 文件 | 规模 | 本脚本怎么用 |
|---|---|---|
| `Names/ModelName.txt` | 453 条 = c* 角色 **408** + AEG* 场景物件 45 | **主证据**：模型 -> 英文名 |
| `Names/ModelNameNT.txt` | 218 条 | 辅助（内部名，本版未参与判类） |
| `Base/enemy.txt` | 23173 条地图放置，覆盖 394 个模型 | 参考实现自己的 **Class**（Basic / Wildlife / Scarab / Boss / MinorBoss / Miniboss / NightMiniboss / DragonMiniboss / Evergaol / HostileNPC / CaravanTroll / Helper / DupeOnly / None）+ Tags + Groups |
| `Messages/zh.enemy.json` | boss_names 172 条（带中文 172）；enemy_config_names 185 条（带 info 484 / 带中文 139） | 中英对照 + 行为类目（info 里的 `Nx in …`） |

**与任务书不一致的两处，如实记在这里：**

1. `Messages/en.enemy.json` **在这个版本里不存在**（目录里只有 de / es / es-ES / fr / it / ja / ko / pl / pt-BR / ru / th / zh 十二份）。所以英文名一律取 `ModelName.txt`。
2. `ModelName.txt` 不是 454 条 `cXXXX 英文名`：文件共 455 行，其中 **2 行是 `#` 注释**（`# Shiny Item = Invisible`、`# DLC`），剩 453 条里 **408 条是 c* 角色模型**、**45 条是 AEG* 场景物件**（`AEG464_071 Painting` 之类，不是敌人）。把 AEG 也算进来的话对齐率必然掉到 90% 以下 —— 那 45 条本来就不该跟我们 462 个角色模型对齐。

## 2. 模型名对齐

| 口径 | 数字 |
|---|---|
| ModelName.txt 全部条目 | 453 |
| 其中 c* 角色模型 | 408 |
| 其中非角色 AEG* 场景物件 | 45 |
| **对齐上（以 c* 为分母）** | **398 / 408 = 97.5%** |
| 对齐上（以全部条目为分母，含 AEG*） | 398 / 453 = 87.9% |
| 我们这边命中 | 398 / 462 = 86.1% |

对齐方式：先原样匹配，再大小写折叠，再试去零填充（`c0120` / `c120`）。**实测三种规则都没有额外收益 —— 我们的模型 id 与 ModelName.txt 的键完全同构**，差异只来自「表里没有这个模型」。

### 2.1 参考实现有、我们没有的 c* 模型（10 个）

| 模型 | 参考实现里的名字 |
|---|---|
| `c2070` | The Three Fingers |
| `c4310` | Lordsworn Soldier |
| `c4341` | Thin Mad Pumpkin Head |
| `c4350` | Lordsworn Knight |
| `c4360` | Lordsworn Knight's Horse |
| `c4366` | Haligtree Knight's Horse |
| `c4370` | Foot Soldier |
| `c5710` | Demi-Human Shaman |
| `c5730` | Demi-Human Queen |
| `c8000` | Torrent |

这些是**本仓库的模型集合（来自法魂本体地图放置）里不存在**的模型 —— 参考实现按原版 + DLC 的 MSB 列，法魂本体改过放置，所以有出入；反过来我们多出来的模型见下一节。这是**数据源口径差**，不是对齐失败。

### 2.2 我们有、参考实现 ModelName.txt 里没有的模型（64 个）

```
  c120  c2035  c2105  c2151  c2195  c2278  c2300  c2501  c3015  c3062  c3071  c3155
  c3301  c3302  c3310  c3361  c3371  c3401  c3480  c3580  c3655  c3705  c3755  c3805
  c3902  c3903  c3911  c3920  c3971  c4051  c4072  c4135  c4151  c4242  c4251  c4261
  c4271  c4342  c4357  c4390  c4391  c4400  c4484  c4493  c4635  c4740  c4850  c5165
  c5652  c5662  c5841  c5861  c5885  c7005  c7101  c7102  c8003  c8004  c8005  c8006
  c8007  c8008  c8009  c8099
```

这 64 个模型在参考实现的 `Base/enemy.txt` 里**也一条都没有**（实测交集为 0），说明它们是**法魂 MOD 自己新增/改过的模型**，或参考实现主动排除的对象。v2 对它们的处理见 §6。

## 3. 类别清单（17 类，含 2 个兜底档）

| 类 | 模型数 | 占比 | 覆盖行数 | 放置数 |
|---|---|---|---|---|
| Boss/领主 | 36 | 7.8% | 82 | 109 |
| 骑士/重甲 | 35 | 7.6% | 250 | 601 |
| 士兵/守军 | 25 | 5.4% | 375 | 2023 |
| 坐骑/驮兽 | 9 | 1.9% | 34 | 66 |
| 人形/平民 | 27 | 5.8% | 791 | 3203 |
| 施法者/祭司 | 24 | 5.2% | 126 | 482 |
| 神皮/黑刀/教会 | 9 | 1.9% | 51 | 92 |
| 不死/腐败 | 45 | 9.7% | 356 | 2677 |
| 龙/龙裔 | 15 | 3.2% | 36 | 64 |
| 巨人/巨兽 | 32 | 6.9% | 139 | 958 |
| 野兽/动物 | 54 | 11.7% | 536 | 10720 |
| 虫/花/菌 | 30 | 6.5% | 269 | 2111 |
| 亚人/混种 | 24 | 5.2% | 216 | 1015 |
| 魔像/人造 | 36 | 7.8% | 317 | 1516 |
| 非战斗/NPC | 22 | 4.8% | 141 | 1672 |
| 体型·大/巨 | 6 | 1.3% | 10 | 27 |
| 未分类 | 33 | 7.1% | 121 | 444 |

与 v1 的 16 类相比：**去掉「血族/贵族」「敌对NPC/人形」，新增「坐骑/驮兽」**，理由：

- 参考实现把 `*Horse` 当**独立模型**（`Night's Cavalry Horse` / `Godrick Knight's Horse` / `Leyndell Knight's Horse` / `Troll Knight's Horse` …，本仓库实测 8 个）。v1 没这一类，它们被拆到骑士/野兽两个池子里 —— 单独立类后，换敌时「马换马」才成立。
- 462 个模型里**只有 c0000 一个**在参考实现里带 `HostileNPC` 标签（`enemy.txt` 实测），单独留一类没有池子意义；v1 的「敌对NPC/人形」在 v1 表里也只有 9 个模型，全部已按名字归到骑士/士兵/施法者等更贴的类。
- v1 的「血族/贵族」只有 2 个模型（鲜血贵族、血怪之首），与「平民/贵族」（漫游贵族、暗影平民）在换敌池里没有区分度，v2 合并进「人形/平民」。

## 4. 判类规则

顺序即优先级，命中即止。**英文名优先**是本版相对 v1 的核心差别 —— v1 的表里 301/462 个模型（65%）根本没有名字，只能标 low；实测的重判实例见 §5.2。

```
坐骑/驮兽          \bhorse\b
坐骑/驮兽          \bdonkey\b
人形/平民          \bfrenzied merchant\b
非战斗/NPC        \bdummy\b
非战斗/NPC        \bballoon\b
非战斗/NPC        \bdefeated\b
非战斗/NPC        \bmerchant\b|\bgoldmask\b|\branni\b|\bmelina\b|\biji\b|\bgostoc\b|\bfinger reader\b|\benia\b|\btwo fingers\b|\bst\. trina\b|\bgrandam\b|\bgatekeeper\b
魔像/人造          \bmarionette\b|\bavionette\b
魔像/人造          \bjar\b|\bgreatjar\b
魔像/人造          \bgolem\b|\bclayman\b|\bsentry stone\b|\bcrystalian\b|\bsilver tear\b|\bwatchdog\b|\bgargoyle\b
魔像/人造          \bballista\b|\btrebuchet\b|\bflamethrower\b|\bchariot\b|\bwalking mausoleum\b|\bgiant ball\b|\blightning ball\b
魔像/人造          \babductor virgin\b
魔像/人造          ^living magma\b
虫/花/菌          \bdragonfly\b
虫/花/菌          \bant\b
野兽/动物          ^giant rat\b|^rat\b|^royal rat\b
野兽/动物          ^giant dog\b|^dog\b
不死/腐败          \bskeleton\b
不死/腐败          \bputrid corpse\b|\bputrid flesh\b|\bcorpse\b|\bcemetery shade\b
不死/腐败          \bdeath rite bird\b|\bdeathbird\b|\bgravebird\b|\btibia mariner\b|\bmariner\b
不死/腐败          \bbasilisk\b|\bkindred of rot\b|\bdisciple of rot\b|\bwormface\b
不死/腐败          \bulcerated tree spirit\b|\brevenant\b|\bspirit eel\b
不死/腐败          ^(rotten|little )?(putrid|rotten)\b
亚人/混种          \bman-serpent\b
龙/龙裔           \bdragon|\bdrake\b|\bwyrm\b|\bserpent\b|\bfortissax\b|\bplacidusax\b|\bekzykes\b|\bgreyoll\b|\bborealis\b|\bsenessax\b|\blansseax\b|\bbayle\b|\btheodorix\b
亚人/混种          \bdemi-human\b|\bmisbegotten\b|\bman-serpent\b|\bbeastman\b|\bimp\b|\bgrafted scion\b|\bdivine bird warrior\b|\bcurseblade\b|\bhorned\b
神皮/黑刀/教会       \bgodskin\b|\bblack knife\b|\bfire monk\b|\bblackflame\b|\bprelate\b|\bclergyman\b|\bconfessor\b
施法者/祭司         \bsorcerer\b|\bbattlemage\b|\bperfumer\b|\bstarcaller\b|\bazur\b|\blusat\b|\bgraven school\b|\benvoy\b|\binquisitor\b|\bshaman\b|\bpriest\b|\bwitch\b
骑士/重甲          \bknight\b|\bcavalry\b|\bsentinel\b|\bduelist\b|\bcommander\b|\bchampion\b|\bveteran\b|\bcrucible\b|\bhero\b|\bguardian\b|\bhunter\b|\blord\b
人形/平民          \balbinauric\b
士兵/守军          \bsoldier\b|\bfoot soldier\b|\bmilitia\b|\bpage\b|\bsellsword\b|\bhighwayman\b|\bguilty\b|\bmercenary\b|\bpumpkin head\b
巨人/巨兽          \bgiant\b|\btroll\b|\bhippopotamus\b|\brunebear\b|\bavatar\b|\bfallingstar\b|\blion\b
巨人/巨兽          \bcrab\b|\bcrayfish\b|\boctopus\b|\bcrow\b
人形/平民          \bcommoner\b|\bnoble\b|\bcelebrant\b|\balbinauric\b|\bminer\b|\bomen\b|\bbloodfiend\b|\bsanguine\b|\bhuman\b|\bpeasant\b|\bprisoner\b|\bscholar\b|\bfighter\b|\bomenkiller\b|\bnox\b|ancestral follower|mini midra|\buntouchable\b
野兽/动物          \bwolf\b|\bstray\b|\bbear\b|\bboar\b|\bram\b|\bdeer\b|\bspringhare\b|\bturtle\b|\bsnail\b|\beagle\b|\bowl\b|\bguillemot\b|\bbat\b|\bjellyfish\b|\beel\b|hawk|\beel\b|\bhare\b|\bcat\b|\bfrog\b|\bsquirt\b|\bsheep\b
虫/花/菌          \bscarab\b|\bmiranda\b|\bfingercreeper\b|\bslug\b|\blamprey\b|\bscorpion\b|\bspider\b|\bman-fly\b|\bswarm\b|\blarva\b|\bmoth\b|\bmosquito\b|\bant\b|\bsquirt\b
巨人/巨兽          \bbeast\b
```

几条顺序是有意为之的（写错就会判错）：

- `horse` 排在 `knight` 之前：`Godrick Knight's Horse` 同时含 knight 与 horse，而它是个**坐骑模型**。
- `marionette / avionette` 排在 `soldier` 之前：`Marionette Soldier` 是**傀儡**不是士兵。
- `dragonfly` 排在 `dragon` 之前：否则蜻蜓会被龙规则吞掉。
- `skeleton` / `putrid` 排在 `giant` 之前：`Giant Skeleton Torso` 是骨架不是巨人。
- `dragon` 排在 `soldier` 之前：`Dragonkin Soldier` 是龙人。
- `demi-human / beastman` 排在 `soldier / warrior` 之前：`Beastman of Farum Azula`、`Divine Bird Warrior` 是亚人不是士兵。

中文规则（仅在模型**没有** ModelName.txt 条目时启用）：

```
坐骑/驮兽          马|驴|驮兽
非战斗/NPC        商人|NPC|假人|傀儡|占位|尸骸|焦尸
魔像/人造          人偶|魔像|石像|陶|罐|壶|战车|弩|投石|石哨|结晶人|看门犬|灵庙
虫/花/菌          虫|蠍|蝎|蚁|蜘蛛|蜻蜓|花|菌|芽|腐苗|幼体
不死/腐败          骷髅|骸骨|尸|腐|死|亡|幽魂|亡灵|墓地|骨
龙/龙裔           龙|蛇|蜥
亚人/混种          亚人|混种|兽人|恶魔|小鬼|角人
神皮/黑刀/教会       神皮|黑刀|教会|祭司长
施法者/祭司         法师|术士|魔法|祭司|萨满|拷问|调香|祈祷|僧|巫|学者|贤者|呼召|敕令|塑灵|唤星
骑士/重甲          骑士|骑兵|守卫|追猎|猎手|斗士|将|官|重甲|铠甲|熔炉|典范|黑夜|看护|守墓
士兵/守军          士兵|兵|待从|侍从|卫士|游侠|弓手|弓兵
巨人/巨兽          巨人|山妖|巨兽|巨怪|巨鸦|巨蟹|河马|熊|狮子|化身|树灵
人形/平民          平民|贵族|村民|居民|白面|矿工|欧门|恶兆|选民|召唤者
野兽/动物          狼|犬|狗|鼠|羊|鹿|龟|鸟|鹰|鸦|蝙蝠|兔|牛|猪|豹|猫|野猪
```

## 4.1 两个必须先说清的数据陷阱

### (a) 共享血条名 —— `boss_healthbar.csv` 里的名字不能无条件当模型名

**实测**：`黄金树看护者`（Erdtree Warden）这一个字符串同时被派给了 c1000 / c2278 / c3170 / c3300 / c3805 / c4120 / c4490 / c4602 / c4660 / c4690 十个模型。原因是同一个 (map, entity) 上的血条调用会被回推到该实体上的**多个**模型，而这些多敌血条用的是**同一个标签**。不处理的话，`c2278`（真身是 c2270~c2277 一串蟹里的一个）会被判成「骑士/重甲」—— 纯属被标签带偏。

本脚本的处理：**凡是同时挂在 ≥2 个模型上的血条名，一律不参与判类**（仍然保留在 `sample_names` 列里供人看）。实测被剔掉的这类名字共 **9** 个：

```
  “招募者”泽菈雅丝
  “满月女王”蕾娜菈
  猫头鹰塞尔温
  腐烂树灵
  裁缝师柏克
  魔法师瑟濂
  鲜血贵族
  黄金树的化身
  黄金树看护者
```

### (b) 手工覆盖只剩 4 条

v1 的 `CURATED` 表有 150+ 条逐个点死。v2 先把规则表写足，然后**只保留规则确实判错的** 4 条硬覆盖 —— 其余一律交给规则，可复核、可复跑：

| 模型 | 手工类 | 规则会给出 | 理由 |
|---|---|---|---|
| `c2040` | 非战斗/NPC | 人形/平民 | Juvenile Scholar = 雷亚卢卡利亚的爬行学徒，不参战（`\bscholar\b` 规则会判成人形/平民，故覆盖） |
| `c2274` | 巨人/巨兽 | 人形/平民 | Giant Albinauric Crab 是**蟹**；规则 11.5 的 `\balbinauric\b` 会先命中白面族，故覆盖 |
| `c2275` | 巨人/巨兽 | 人形/平民 | Albinauric Crab 同理：是蟹，不是白面族人形 |
| `c3171` | 施法者/祭司 | 未分类 | ModelNameNT 只给 `Phillia`；法魂本体的行名是『「龐大妹妹」菲莉亞』，与 c3610/c3620/c3630（Oracle Envoy 三型）同族 —— 神谕使者 |

另有 5 条 `DOC_ONLY`（`c0000`、`c2274`、`c2275`、`c3251`、`c3350`）**不改判定**，只是把「为什么」写进 evidence。

## 5. 新旧对比

基线：git HEAD:investigation/enemy_type_map.csv（v1）（462 行）。

| 指标 | 数字 |
|---|---|
| 可比模型 | 462 |
| enemy_type **一致** | 113 |
| enemy_type **不一致** | **349** |
| ├─ 旧=兜底（未分类/体型档）→ 新=具体类 | 269（覆盖率提升） |
| └─ 旧=具体类 → 新=具体类（真·重判） | 80 |

### 5.1 旧=兜底 → 新=具体类（269 个）

| 模型 | 旧 | 新 | 参考实现英文名 |
|---|---|---|---|
| `c4191` | 未分类 | 虫/花/菌 | Small Scarab |
| `c5240` | 未分类 | 人形/平民 | Shadow Commoner |
| `c3500` | 未分类 | 不死/腐败 | Skeleton |
| `c3660` | 未分类 | 人形/平民 | Commoner |
| `c4313` | 未分类 | 士兵/守军 | Leyndell Soldier |
| `c3661` | 未分类 | 不死/腐败 | Putrid Corpse |
| `c5830` | 未分类 | 士兵/守军 | Messmer Soldier |
| `c4200` | 未分类 | 野兽/动物 | Man-Bat |
| `c3000` | 未分类 | 士兵/守军 | Exile Soldier |
| `c3470` | 未分类 | 人形/平民 | Albinauric |
| `c3080` | 未分类 | 亚人/混种 | Imp |
| `c5450` | 未分类 | 野兽/动物 | Ram |
| `c6060` | 未分类 | 野兽/动物 | Ram |
| `c3360` | 未分类 | 人形/平民 | Ancestral Follower |
| `c4373` | 未分类 | 士兵/守军 | Leyndell Foot Soldier |
| `c5080` | 未分类 | 人形/平民 | Bloodfiend |
| `c5401` | 未分类 | 野兽/动物 | Eagle |
| `c3510` | 未分类 | 不死/腐败 | Catacombs Skeleton |
| `c4100` | 未分类 | 亚人/混种 | Demi-Human |
| `c4080` | 未分类 | 野兽/动物 | Rat |
| `c3850` | 未分类 | 魔像/人造 | Marionette Soldier |
| `c4321` | 未分类 | 士兵/守军 | Vulgar Militia |
| `c4374` | 未分类 | 士兵/守军 | Radahn Foot Soldier |
| `c5440` | 未分类 | 野兽/动物 | Boar |
| `c4312` | 未分类 | 士兵/守军 | Raya Lucaria Soldier |
| `c5410` | 未分类 | 野兽/动物 | Deer |
| `c5360` | 未分类 | 不死/腐败 | Skeleton |
| `c4161` | 未分类 | 野兽/动物 | Stray |
| `c4371` | 未分类 | 士兵/守军 | Godrick Foot Soldier |
| `c3702` | 未分类 | 施法者/祭司 | Glintstone Sorcerer |
| `c4315` | 未分类 | 士兵/守军 | Mausoleum Soldier |
| `c4311` | 未分类 | 士兵/守军 | Godrick Soldier |
| `c4382` | 未分类 | 人形/平民 | Miner |
| `c5651` | 未分类 | 士兵/守军 | Messmer Foot Soldier |
| `c4353` | 未分类 | 骑士/重甲 | Leyndell Knight |
| `c5311` | 未分类 | 施法者/祭司 | Hornsent Inquisitor |
| `c4240` | 未分类 | 虫/花/菌 | Fingercreeper |
| `c3320` | 未分类 | 魔像/人造 | Silver Tear |
| `c5490` | 未分类 | 野兽/动物 | Springhare |
| `c4481` | 未分类 | 虫/花/菌 | Miranda Sprout |
| `c4280` | 未分类 | 虫/花/菌 | Giant Ant |
| `c4316` | 未分类 | 士兵/守军 | Haligtree Soldier |
| `c4314` | 未分类 | 士兵/守军 | Radahn Soldier |
| `c6001` | 未分类 | 野兽/动物 | Eagle |
| `c4070` | 未分类 | 野兽/动物 | Wolf |
| `c6100` | 未分类 | 野兽/动物 | Springhare |
| `c3450` | 未分类 | 亚人/混种 | Misbegotten |
| `c3750` | 未分类 | 魔像/人造 | Clayman |
| `c4385` | 未分类 | 不死/腐败 | Disciple of Rot |
| `c6010` | 未分类 | 野兽/动物 | Deer |
| `c5661` | 未分类 | 士兵/守军 | Shadow Militia |
| `c5480` | 未分类 | 野兽/动物 | Turtle |
| `c4210` | 未分类 | 野兽/动物 | Warhawk |
| `c3070` | 未分类 | 人形/平民 | Dominula Celebrant |
| `c3210` | 未分类 | 坐骑/驮兽 | Merchant's Donkey |
| `c4630` | 未分类 | 巨人/巨兽 | Runebear |
| `c4550` | 未分类 | 野兽/动物 | Giant Dog |
| `c4071` | 未分类 | 野兽/动物 | White Wolf |
| `c4180` | 未分类 | 野兽/动物 | Spirit Jellyfish |
| `c4040` | 未分类 | 虫/花/菌 | Slug |
| `c4170` | 未分类 | 不死/腐败 | Putrid Flesh |
| `c5870` | 未分类 | 亚人/混种 | Imp |
| `c5110` | 未分类 | 不死/腐败 | Spirit Eel |
| `c3703` | 未分类 | 士兵/守军 | Page |
| `c4090` | 未分类 | 野兽/动物 | Giant Rat |
| `c5430` | 未分类 | 野兽/动物 | Owl |
| `c3860` | 未分类 | 魔像/人造 | Avionette Soldier |
| `c6031` | 未分类 | 野兽/动物 | Bear |
| `c5900` | 未分类 | 虫/花/菌 | Man-Fly |
| `c6090` | 未分类 | 野兽/动物 | Turtle |
| `c4430` | 未分类 | 魔像/人造 | Sentry Stone |
| `c3060` | 未分类 | 不死/腐败 | Giant Skeleton |
| `c3150` | 未分类 | 骑士/重甲 | Night's Cavalry |
| `c4460` | 体型·大/巨 | 魔像/人造 | Flame Chariot |
| `c4000` | 未分类 | 不死/腐败 | Revenant Follower |
| `c5190` | 未分类 | 虫/花/菌 | Spider Scorpion |
| `c4230` | 未分类 | 巨人/巨兽 | Larval Land Octopus |
| `c4355` | 未分类 | 骑士/重甲 | Mausoleum Knight |
| `c4352` | 未分类 | 骑士/重甲 | Cuckoo Knight |
| `c5740` | 未分类 | 不死/腐败 | Kindred of Rot |
| `c5530` | 未分类 | 野兽/动物 | Man-Bat |
| `c5750` | 未分类 | 魔像/人造 | Living Jar Warrior |
| `c4354` | 未分类 | 骑士/重甲 | Redmane Knight |
| `c3160` | 未分类 | 坐骑/驮兽 | Night's Cavalry Horse |
| `c5260` | 未分类 | 魔像/人造 | Smith Golem |
| `c4220` | 未分类 | 巨人/巨兽 | Land Octopus |
| `c4150` | 未分类 | 不死/腐败 | Basilisk |
| `c3330` | 未分类 | 魔像/人造 | Giant Ball |
| `c6050` | 未分类 | 野兽/动物 | Boar |
| `c6080` | 未分类 | 虫/花/菌 | Dragonfly |
| `c4356` | 未分类 | 骑士/重甲 | Haligtree Knight |
| `c4351` | 未分类 | 骑士/重甲 | Godrick Knight |
| `c4160` | 未分类 | 野兽/动物 | Large Stray |
| `c8100` | 未分类 | 魔像/人造 | Ballista |
| `c3900` | 未分类 | 神皮/黑刀/教会 | Fire Monk |
| `c5270` | 未分类 | 魔像/人造 | Jar Innards |
| `c4420` | 未分类 | 巨人/巨兽 | Giant Crayfish |
| `c4483` | 未分类 | 不死/腐败 | Rotten Miranda Sprout |
| `c4380` | 未分类 | 施法者/祭司 | Starcaller |
| `c5500` | 未分类 | 魔像/人造 | Living Magma |
| `c6081` | 未分类 | 虫/花/菌 | Yellow Dragonfly |
| `c3700` | 未分类 | 施法者/祭司 | Depraved Perfumer |
| `c4101` | 未分类 | 亚人/混种 | Large Demi-Human |
| `c5060` | 未分类 | 虫/花/菌 | Lamprey |
| `c4165` | 未分类 | 野兽/动物 | Bloodbane Stray |
| `c0120` | 未分类 | 非战斗/NPC | Bullet Dummy |
| `c2040` | 未分类 | 非战斗/NPC | Juvenile Scholar |
| `c4383` | 未分类 | 人形/平民 | Glintstone Miner |
| `c4376` | 未分类 | 士兵/守军 | Haligtree Foot Soldier |
| `c4192` | 未分类 | 虫/花/菌 | Extra Large Scarab |
| `c4372` | 未分类 | 士兵/守军 | Raya Lucaria Foot Soldier |
| `c6040` | 未分类 | 野兽/动物 | Owl |
| `c5170` | 体型·巨/龙 | 魔像/人造 | Furnace Golem |
| `c6201` | 未分类 | 虫/花/菌 | Scarab |
| `c5421` | 未分类 | 野兽/动物 | Bear |
| `c3020` | 未分类 | 士兵/守军 | Large Exile Soldier |
| `c4050` | 未分类 | 士兵/守军 | Kaiden Sellsword |
| `c3901` | 未分类 | 神皮/黑刀/教会 | Blackflame Monk |
| `c2270` | 未分类 | 巨人/巨兽 | Giant Crab |
| `c2150` | 未分类 | 魔像/人造 | Lightning Ball |
| `c2271` | 未分类 | 巨人/巨兽 | Crab |
| `c4450` | 体型·巨/龙 | 魔像/人造 | Walking Mausoleum |
| `c2275` | 未分类 | 巨人/巨兽 | Albinauric Crab |
| `c3662` | 未分类 | 不死/腐败 | Large Putrid Corpse |
| `c5590` | 未分类 | 不死/腐败 | Putrid Flesh |
| `c5600` | 未分类 | 不死/腐败 | Catacombs Skeleton |
| `c5760` | 未分类 | 野兽/动物 | Rat |
| `c6290` | 未分类 | 亚人/混种 | Misbegotten |
| `c6070` | 未分类 | 野兽/动物 | Guillemot |
| `c5523` | 未分类 | 野兽/动物 | Shadow Stray |
| `c4270` | 未分类 | 巨人/巨兽 | Elder Lion |
| `c5320` | 未分类 | 施法者/祭司 | Fat Hornsent Inquisitor |
| `c5880` | 未分类 | 施法者/祭司 | Catacombs Sorcerer |
| `c3180` | 未分类 | 野兽/动物 | Archer's Wolf |
| `c5560` | 未分类 | 虫/花/菌 | Small Fingercreeper |
| `c5761` | 未分类 | 野兽/动物 | Giant Rat |
| `c4250` | 未分类 | 虫/花/菌 | Small Fingercreeper |
| `c5470` | 未分类 | 虫/花/菌 | Dragonfly |
| `c6320` | 未分类 | 人形/平民 | Wandering Noble |
| `c5380` | 未分类 | 虫/花/菌 | Miranda Blossom |
| `c5381` | 未分类 | 虫/花/菌 | Miranda Sprout |
| `c6231` | 未分类 | 施法者/祭司 | Perfumer |
| `c5570` | 未分类 | 魔像/人造 | Marionette Soldier |
| `c8101` | 未分类 | 魔像/人造 | Trebuchet |
| `c3201` | 未分类 | 人形/平民 | Frenzied Merchant |
| `c4560` | 体型·大/巨 | 巨人/巨兽 | Giant Crow |
| `c4482` | 未分类 | 不死/腐败 | Rotten Miranda Blossom |
| `c2041` | 未分类 | 虫/花/菌 | Larva of Rot |
| `c7000` | 未分类 | 士兵/守军 | Fallen Hawks Soldier |
| `c5241` | 未分类 | 人形/平民 | Large Shadow Commoner |
| `c5960` | 体型·大/巨 | 不死/腐败 | Ulcerated Tree Spirit |
| `c5640` | 未分类 | 巨人/巨兽 | Giant Crab |
| `c5751` | 未分类 | 魔像/人造 | Living Jar |
| `c4440` | 未分类 | 野兽/动物 | Land Squirt |
| `c4190` | 未分类 | 虫/花/菌 | Large Scarab |
| `c5522` | 未分类 | 野兽/动物 | Large Shadow Stray |
| `c5850` | 未分类 | 巨人/巨兽 | Giant Ram |
| `c8110` | 未分类 | 魔像/人造 | Dragon-Faced Flamethrower |
| `c3610` | 未分类 | 施法者/祭司 | Small Oracle Envoy |
| `c3630` | 未分类 | 施法者/祭司 | Fat Oracle Envoy |
| `c3471` | 未分类 | 人形/平民 | Large Albinauric |
| `c4381` | 未分类 | 士兵/守军 | Guilty |
| `c3061` | 未分类 | 不死/腐败 | Giant Beast Skeleton |
| `c4171` | 体型·大/巨 | 不死/腐败 | Large Putrid Flesh |
| `c4570` | 未分类 | 不死/腐败 | Wormface |
| `c4164` | 未分类 | 野兽/动物 | Large Bloodbane Stray |
| `c5180` | 未分类 | 非战斗/NPC | DLC Dummy |
| `c5181` | 未分类 | 非战斗/NPC | DLC Dummy 2 |
| `c5511` | 未分类 | 不死/腐败 | Putrid Corpse |
| `c5641` | 未分类 | 巨人/巨兽 | Crab |
| `c5271` | 未分类 | 魔像/人造 | Large Jar Innards |
| `c5940` | 未分类 | 魔像/人造 | Sentry Stone |
| `c4377` | 未分类 | 士兵/守军 | Highwayman |
| `c5931` | 未分类 | 不死/腐败 | Giant Beast Skeleton |
| `c2274` | 未分类 | 巨人/巨兽 | Giant Albinauric Crab |
| `c5550` | 未分类 | 虫/花/菌 | Fingercreeper |
| `c5790` | 体型·巨/龙 | 魔像/人造 | Guardian Golem |
| `c5460` | 未分类 | 野兽/动物 | Guillemot |
| `c5630` | 未分类 | 巨人/巨兽 | Giant Crayfish |
| `c5700` | 未分类 | 亚人/混种 | Demi-Human |
| `c5471` | 未分类 | 虫/花/菌 | Yellow Dragonfly |
| `c5521` | 未分类 | 野兽/动物 | Messmerfire Stray |
| `c3620` | 未分类 | 施法者/祭司 | Tall Oracle Envoy |
| `c4720` | 未分类 | Boss/领主 | Godfrey |
| `c4505` | 体型·巨/龙 | 龙/龙裔 | Small Flying Dragon |
| `c4162` | 未分类 | 野兽/动物 | Large Farum Azula Stray |
| `c4281` | 体型·大/巨 | 虫/花/菌 | Skull Plate Giant Ant |
| `c6082` | 未分类 | 虫/花/菌 | Great Dragonfly |
| `c4166` | 未分类 | 野兽/动物 | Large Rotten Stray |
| `c5800` | 未分类 | 骑士/重甲 | Crucible Knight Devonia |
| `c6240` | 未分类 | 魔像/人造 | Lightning Ball |
| `c5193` | 未分类 | 虫/花/菌 | Small Spider Scorpion |
| `c2272` | 未分类 | 巨人/巨兽 | Giant Black Crab |
| `c4441` | 体型·大/巨 | 巨人/巨兽 | Giant Land Squirt |
| `c4363` | 未分类 | 坐骑/驮兽 | Leyndell Knight's Horse |
| `c5513` | 未分类 | 不死/腐败 | Cemetery Shade |
| `c5350` | 未分类 | 不死/腐败 | Basilisk Eyes |
| `c5990` | 未分类 | 不死/腐败 | Basilisk |
| `c4362` | 未分类 | 坐骑/驮兽 | Cuckoo Knight's Horse |
| `c4960` | 未分类 | 不死/腐败 | Giant Skeleton Torso |
| `c2276` | 未分类 | 巨人/巨兽 | Giant Death Crab |
| `c2277` | 未分类 | 巨人/巨兽 | Death Crab |
| `c4361` | 未分类 | 坐骑/驮兽 | Godrick Knight's Horse |
| `c5527` | 未分类 | 野兽/动物 | Bloodbane Stray |
| `c5930` | 未分类 | 不死/腐败 | Giant Skeleton |
| `c5391` | 体型·大/巨 | 骑士/重甲 | Troll Knight |
| `c5525` | 未分类 | 野兽/动物 | Stray |
| `c5890` | 未分类 | 坐骑/驮兽 | Black Knight Horse |
| `c6291` | 未分类 | 亚人/混种 | Scaly Misbegotten |
| `c5970` | 未分类 | 魔像/人造 | Abductor Virgin |
| `c5980` | 未分类 | 人形/平民 | Omenkiller |
| `c5472` | 未分类 | 虫/花/菌 | Great Dragonfly |
| `c6251` | 未分类 | 骑士/重甲 | Tree Sentinel |
| `c4751` | 未分类 | 非战斗/NPC | Defeated Godrick |
| `c2131` | 未分类 | 非战斗/NPC | Defeated Morgott |
| `c4365` | 未分类 | 坐骑/驮兽 | Mausoleum Knight's Horse |
| `c4493` | 未分类 | 体型·大/巨 |  |
| `c4163` | 未分类 | 野兽/动物 | Farum Azula Stray |
| `c4242` | 未分类 | 体型·大/巨 |  |
| `c4711` | 未分类 | Boss/领主 | Rykard's Corpse |
| `c4342` | 未分类 | 体型·大/巨 |  |
| `c5251` | 未分类 | 施法者/祭司 | Hornsent Shaman |
| `c5140` | 未分类 | 龙/龙裔 | Large Messmer Serpent |
| `c5141` | 未分类 | 龙/龙裔 | Messmer Serpent |
| `c5591` | 体型·大/巨 | 不死/腐败 | Large Putrid Flesh |
| `c5950` | 未分类 | 亚人/混种 | Leonine Misbegotten |
| `c5200` | 体型·巨/龙 | Boss/领主 | Metyr, Mother of Fingers |
| `c5050` | 未分类 | 人形/平民 | Mini Midra |
| `c5280` | 未分类 | 人形/平民 | Aging Untouchable |
| `c4561` | 未分类 | 巨人/巨兽 | Bloodbane Giant Crow |
| `c2273` | 未分类 | 巨人/巨兽 | Black Crab |
| `c8120` | 未分类 | 魔像/人造 | Merciless Chariot |
| `c4384` | 未分类 | 人形/平民 | Large Glintstone Miner |
| `c5871` | 未分类 | 亚人/混种 | Large Bigmouth Imp |
| `c5872` | 体型·大/巨 | 亚人/混种 | Massive Bigmouth Imp |
| `c5540` | 未分类 | 野兽/动物 | Wolf |
| `c5541` | 未分类 | 野兽/动物 | White Wolf |
| `c5920` | 体型·大/巨 | 龙/龙裔 | Magma Wyrm |
| `c0110` | 未分类 | 非战斗/NPC | Caravan Dummy |
| `c4060` | 未分类 | 坐骑/驮兽 | Kaiden Sellsword's Horse |
| `c4492` | 体型·巨/龙 | 魔像/人造 | Greatjar |
| `c0130` | 体型·大/巨 | 非战斗/NPC | Balloon |
| `c4167` | 未分类 | 不死/腐败 | Rotten Stray |
| `c4375` | 未分类 | 士兵/守军 | Mausoleum Foot Soldier |
| `c4442` | 体型·大/巨 | 巨人/巨兽 | Giant Rotten Land Squirt |
| `c4364` | 未分类 | 坐骑/驮兽 | Redmane Knight's Horse |
| `c4504` | 体型·巨/龙 | 龙/龙裔 | Greyoll |
| `c4241` | 体型·巨/龙 | 虫/花/菌 | Colossal Fingercreeper |
| `c5526` | 未分类 | 野兽/动物 | Large Bloodbane Stray |
| `c5780` | 未分类 | 巨人/巨兽 | Runebear |
| `c6300` | 未分类 | 野兽/动物 | Snail |
| `c5701` | 未分类 | 亚人/混种 | Large Demi-Human |
| `c5680` | 未分类 | 魔像/人造 | Ballista |
| `c5390` | 体型·大/巨 | 巨人/巨兽 | Troll |
| `c6260` | 体型·大/巨 | 不死/腐败 | Death Rite Bird |
| `c5720` | 未分类 | 亚人/混种 | Demi-Human Chief |
| `c5524` | 未分类 | 野兽/动物 | Large Stray |
| `c6232` | 未分类 | 施法者/祭司 | Glintstone Sorcerer |
| `c6233` | 未分类 | 士兵/守军 | Page |
| `c5690` | 未分类 | 魔像/人造 | Dragon-Faced Flamethrower |
| `c5520` | 未分类 | 野兽/动物 | Large Messmerfire Stray |
| `c5620` | 未分类 | 不死/腐败 | Tibia Mariner |
| `c6270` | 未分类 | 不死/腐败 | Royal Revenant |
| `c5340` | 未分类 | 非战斗/NPC | DLC Dummy 3 |
| `c6210` | 未分类 | 人形/平民 | Albinauric Archer |
| `c6220` | 未分类 | 野兽/动物 | Archer's Wolf |
| `c6310` | 体型·大/巨 | 巨人/巨兽 | Fallingstar Beast |
| `c5061` | 未分类 | 虫/花/菌 | Large Lamprey |
| `c5551` | 体型·巨/龙 | 虫/花/菌 | Colossal Fingercreeper |

### 5.2 旧=具体类 → 新=具体类（80 个，逐个看是不是新表更对）

| 模型 | 旧 | 新 | 参考实现英文名 | 判断 |
|---|---|---|---|---|
| `c0000` | 非战斗/NPC | 人形/平民 | Human | 按英文名 `Human` 重判 |
| `c4300` | 野兽/动物 | 人形/平民 | Wandering Noble | 按英文名 `Wandering Noble` 重判 |
| `c4490` | 巨人/巨兽 | 魔像/人造 | Living Jar Warrior | 按英文名 `Living Jar Warrior` 重判 |
| `c3300` | 敌对NPC/人形 | 人形/平民 | Nox Fighter | 按英文名 `Nox Fighter` 重判 |
| `c2140` | 不死/腐败 | 人形/平民 | Omen | 按英文名 `Omen` 重判 |
| `c5250` | 野兽/动物 | 亚人/混种 | Divine Bird Warrior | 按英文名 `Divine Bird Warrior` 重判 |
| `c3350` | 不死/腐败 | 魔像/人造 | Crystalian | 按英文名 `Crystalian` 重判 |
| `c3970` | 龙/龙裔 | 亚人/混种 | Beastman of Farum Azula | 按英文名 `Beastman of Farum Azula` 重判 |
| `c5090` | 士兵/守军 | 不死/腐败 | Gravebird | 按英文名 `Gravebird` 重判 |
| `c2500` | 非战斗/NPC | 骑士/重甲 | Crucible Knight | 按英文名 `Crucible Knight` 重判 |
| `c0100` | 魔像/人造 | 非战斗/NPC | Dummy | 按英文名 `Dummy` 重判 |
| `c3400` | 士兵/守军 | 骑士/重甲 | Grave Warden Duelist | 按英文名 `Grave Warden Duelist` 重判 |
| `c3670` | 非战斗/NPC | 人形/平民 | Elder Albinauric | 按英文名 `Elder Albinauric` 重判 |
| `c2010` | 野兽/动物 | Boss/领主 | Blaidd | 按英文名 `Blaidd` 重判 |
| `c3950` | 非战斗/NPC | 亚人/混种 | Man-Serpent | 按英文名 `Man-Serpent` 重判 |
| `c3451` | 非战斗/NPC | 亚人/混种 | Scaly Misbegotten | 按英文名 `Scaly Misbegotten` 重判 |
| `c3650` | 士兵/守军 | 骑士/重甲 | Guardian | 按英文名 `Guardian` 重判 |
| `c4820` | 敌对NPC/人形 | 人形/平民 | Omenkiller | 按英文名 `Omenkiller` 重判 |
| `c3910` | 施法者/祭司 | 神皮/黑刀/教会 | Fire Prelate | 按英文名 `Fire Prelate` 重判 |
| `c5040` | 敌对NPC/人形 | 亚人/混种 | Curseblade | 按英文名 `Curseblade` 重判 |
| `c3600` | 敌对NPC/人形 | 骑士/重甲 | Onyx Lord | 按英文名 `Onyx Lord` 重判 |
| `c4260` | 不死/腐败 | 魔像/人造 | Erdtree Burial Watchdog | 按英文名 `Erdtree Burial Watchdog` 重判 |
| `c3730` | 非战斗/NPC | 施法者/祭司 | Graven School | 按英文名 `Graven School` 重判 |
| `c4770` | 巨人/巨兽 | 魔像/人造 | Gargoyle | 按英文名 `Gargoyle` 重判 |
| `c4120` | 士兵/守军 | 亚人/混种 | Demi-Human Chief | 按英文名 `Demi-Human Chief` 重判 |
| `c3310` | 法魂新增(名号) | 施法者/祭司 |  | 按英文名 `—` 重判 |
| `c3170` | 骑士/重甲 | 人形/平民 | Albinauric Archer | 按英文名 `Albinauric Archer` 重判 |
| `c4690` | 神皮/黑刀/教会 | 亚人/混种 | Grafted Scion | 按英文名 `Grafted Scion` 重判 |
| `c3460` | 骑士/重甲 | 亚人/混种 | Leonine Misbegotten | 按英文名 `Leonine Misbegotten` 重判 |
| `c3550` | 神皮/黑刀/教会 | 人形/平民 | Sanguine Noble | 按英文名 `Sanguine Noble` 重判 |
| `c4650` | 士兵/守军 | 龙/龙裔 | Dragonkin Soldier | 按英文名 `Dragonkin Soldier` 重判 |
| `c5230` | 魔像/人造 | Boss/领主 | Scadutree Avatar | 按英文名 `Scadutree Avatar` 重判 |
| `c7100` | 不死/腐败 | 骑士/重甲 | Ancient Hero of Zamor | 按英文名 `Ancient Hero of Zamor` 重判 |
| `c5081` | 血族/贵族 | 人形/平民 | Chief Bloodfiend | 按英文名 `Chief Bloodfiend` 重判 |
| `c4670` | 不死/腐败 | Boss/领主 | Ancestor Spirit | 按英文名 `Ancestor Spirit` 重判 |
| `c3100` | 敌对NPC/人形 | 骑士/重甲 | Bell Bearing Hunter | 按英文名 `Bell Bearing Hunter` 重判 |
| `c2110` | 施法者/祭司 | 神皮/黑刀/教会 | Beast Clergyman | 按英文名 `Beast Clergyman` 重判 |
| `c5192` | 巨人/巨兽 | 虫/花/菌 | Large Spider Scorpion | 按英文名 `Large Spider Scorpion` 重判 |
| `c7101` | 士兵/守军 | 未分类 |  | 按英文名 `—` 重判 |
| `c3705` | 敌对NPC/人形 | 人形/平民 |  | 按英文名 `—` 重判 |
| `c4800` | 血族/贵族 | Boss/领主 | Mohg | 按英文名 `Mohg` 重判 |
| `c3805` | 魔像/人造 | 骑士/重甲 |  | 按英文名 `—` 重判 |
| `c5220` | 施法者/祭司 | Boss/领主 | Promised Consort Radahn | 按英文名 `Promised Consort Radahn` 重判 |
| `c2278` | 巨人/巨兽 | 体型·大/巨 |  | 按英文名 `—` 重判 |
| `c6091` | 非战斗/NPC | 巨人/巨兽 | Giant Turtle | 按英文名 `Giant Turtle` 重判 |
| `c3251` | 士兵/守军 | 骑士/重甲 | Tree Sentinel | 按英文名 `Tree Sentinel` 重判 |
| `c4400` | 法魂新增(名号) | 体型·大/巨 |  | 按英文名 `—` 重判 |
| `c4635` | 法魂新增(名号) | 体型·大/巨 |  | 按英文名 `—` 重判 |
| `c3250` | 士兵/守军 | 骑士/重甲 | Draconic Tree Sentinel | 按英文名 `Draconic Tree Sentinel` 重判 |
| `c5300` | 骑士/重甲 | Boss/领主 | Rellana, Twin Moon Knight | 按英文名 `Rellana, Twin Moon Knight` 重判 |
| `c2120` | 不死/腐败 | Boss/领主 | Malenia | 按英文名 `Malenia` 重判 |
| `c4710` | 巨人/巨兽 | Boss/领主 | God-Devouring Serpent | 按英文名 `God-Devouring Serpent` 重判 |
| `c5210` | 野兽/动物 | Boss/领主 | Divine Beast Dancing Lion | 按英文名 `Divine Beast Dancing Lion` 重判 |
| `c5130` | 野兽/动物 | Boss/领主 | Messmer | 按英文名 `Messmer` 重判 |
| `c5020` | 骑士/重甲 | Boss/领主 | Putrescent Knight | 按英文名 `Putrescent Knight` 重判 |
| `c4760` | 巨人/巨兽 | Boss/领主 | Fire Giant | 按英文名 `Fire Giant` 重判 |
| `c5820` | 巨人/巨兽 | 野兽/动物 | Great Red Bear | 按英文名 `Great Red Bear` 重判 |
| `c4511` | 龙/龙裔 | Boss/领主 | Lichdragon Fortissax | 按英文名 `Lichdragon Fortissax` 重判 |
| `c4520` | 施法者/祭司 | Boss/领主 | Dragonlord Placidusax | 按英文名 `Dragonlord Placidusax` 重判 |
| `c3252` | 骑士/重甲 | Boss/领主 | Loretta | 按英文名 `Loretta` 重判 |
| `c4391` | 施法者/祭司 | 龙/龙裔 |  | 按英文名 `—` 重判 |
| `c2200` | 巨人/巨兽 | Boss/领主 | Elden Beast | 按英文名 `Elden Beast` 重判 |
| `c5330` | 敌对NPC/人形 | 非战斗/NPC | St. Trina | 按英文名 `St. Trina` 重判 |
| `c4261` | 不死/腐败 | 魔像/人造 |  | 按英文名 `—` 重判 |
| `c3911` | 士兵/守军 | 骑士/重甲 |  | 按英文名 `—` 重判 |
| `c3580` | 骑士/重甲 | 神皮/黑刀/教会 |  | 按英文名 `—` 重判 |
| `c4503` | 龙/龙裔 | Boss/领主 | Borealis the Freezing Fog | 按英文名 `Borealis the Freezing Fog` 重判 |
| `c3920` | 士兵/守军 | 骑士/重甲 |  | 按英文名 `—` 重判 |
| `c3480` | 法魂新增(名号) | 不死/腐败 |  | 按英文名 `—` 重判 |
| `c4810` | 魔像/人造 | 巨人/巨兽 | Erdtree Avatar | 按英文名 `Erdtree Avatar` 重判 |
| `c3171` | 敌对NPC/人形 | 施法者/祭司 | Phillia | 按英文名 `Phillia` 重判 |
| `c3902` | 敌对NPC/人形 | 不死/腐败 |  | 按英文名 `—` 重判 |
| `c4501` | 不死/腐败 | Boss/领主 | Decaying Ekzykes | 按英文名 `Decaying Ekzykes` 重判 |
| `c4911` | 龙/龙裔 | Boss/领主 | Great Wyrm Theodorix | 按英文名 `Great Wyrm Theodorix` 重判 |
| `c4051` | 法魂新增(名号) | 施法者/祭司 |  | 按英文名 `—` 重判 |
| `c5030` | 虫/花/菌 | Boss/领主 | Romina | 按英文名 `Romina` 重判 |
| `c5000` | 骑士/重甲 | Boss/领主 | Commander Gaius | 按英文名 `Commander Gaius` 重判 |
| `c5312` | 法魂新增(名号) | Boss/领主 | Jori, Elder Inquisitor | 按英文名 `Jori, Elder Inquisitor` 重判 |
| `c5120` | 龙/龙裔 | Boss/领主 | Bayle the Dread | 按英文名 `Bayle the Dread` 重判 |
| `c5370` | 龙/龙裔 | Boss/领主 | Ancient Dragon Senessax | 按英文名 `Ancient Dragon Senessax` 重判 |

## 6. 还剩多少没归类 / 没名字

| 项 | 数量 |
|---|---|
| 有 ModelName.txt 英文名 | 398 |
| 只有中文名（法魂新增/改名的模型，含多候选） | 28 |
| 中英文都没有 | 36 |
| 拿到具体类 | 429 |
| 仍是「未分类」 | 33 |

**中英文都没有名字的模型（36 个）：**

```
  c5652  c3071  c2300  c7005  c3971  c4357  c3361  c7101  c3302  c5841  c3755  c3903
  c5662  c8099  c8006  c8005  c8007  c8003  c8008  c8009  c8004  c3371  c4072  c4493
  c3655  c4484  c4151  c7102  c4251  c4242  c2105  c2151  c4342  c2195  c5885  c120
```

**仍是「未分类」的模型（33 个）：**

| 模型 | 放置数 | hp 中位 | 备注 |
|---|---|---|---|
| `c5652` | 106 | 147 | 参考实现无此模型 |
| `c3071` | 41 | 233 | 参考实现无此模型 |
| `c2300` | 11 | 800 | 参考实现无此模型 |
| `c7005` | 79 | 115 | 参考实现无此模型 |
| `c3971` | 13 | 250 | 参考实现无此模型 |
| `c4357` | 17 | 576 | 参考实现无此模型 |
| `c3361` | 37 | 316 | 参考实现无此模型 |
| `c7101` | 4 | 1418 | 参考实现无此模型 |
| `c3302` | 11 | 339 | 参考实现无此模型 |
| `c5841` | 4 | 512 | 参考实现无此模型 |
| `c3755` | 35 | 262 | 参考实现无此模型 |
| `c3903` | 6 | 594 | 参考实现无此模型 |
| `c5662` | 6 | 153 | 参考实现无此模型 |
| `c8099` | 1 | 1939 | 参考实现无此模型 |
| `c8006` | 1 | 1939 | 参考实现无此模型 |
| `c8005` | 1 | 1939 | 参考实现无此模型 |
| `c8007` | 2 | 1939 | 参考实现无此模型 |
| `c8003` | 1 | 1939 | 参考实现无此模型 |
| `c8008` | 2 | 1939 | 参考实现无此模型 |
| `c8009` | 2 | 1939 | 参考实现无此模型 |
| `c8004` | 1 | 1939 | 参考实现无此模型 |
| `c3371` | 4 | 450 | 参考实现无此模型 |
| `c4072` | 6 | 409 | 参考实现无此模型 |
| `c3655` | 17 | 167 | 参考实现无此模型 |
| `c4484` | 3 | 1939 | 参考实现无此模型 |
| `c4151` | 10 | 338 | 参考实现无此模型 |
| `c7102` | 1 | 1418 | 参考实现无此模型 |
| `c4251` | 13 | 105 | 参考实现无此模型 |
| `c2105` | 1 | 2765 | 参考实现无此模型 |
| `c2151` | 1 | 2765 | 参考实现无此模型 |
| `c2195` | 1 | 3130 | 参考实现无此模型 |
| `c5885` | 5 | 210 | 参考实现无此模型 |
| `c120` | 1 |  | 参考实现无此模型 |

## 7. 产物与列

| 文件 | 说明 |
|---|---|
| `investigation/enemy_type_map.csv` | 覆盖写。`model` / `enemy_type` 两列名保持不变（`enemy_randomizer.load_row_types` 只认这两列）；列序：`model, model_name_en, enemy_type, confidence, npc_rows, placements, sample_names, hp_median, evidence, name_source, ref_class, boss_healthbar, type_rule, schema` |
| `investigation/enemy_type_names_zh.csv` | 中英对照：`model, model_name_en, name_zh, source, note` |
| `investigation/enemy_type_map_v2.md` | 本文件 |

列的含义：

- `evidence` 把 name 来源 / ref Class / ref Group / ref info 全部串起来，判错了能顺着它回溯。
- `confidence` 三档：`high` = 有英文名且命中规则、或独特具名 Boss、或手工覆盖；`medium` = 中文名判出（含多候选多数决）、或参考实现 Class 兜底；`low` = 体型兜底 / 未分类。
- `boss_healthbar` = `yes` 表示这个模型在**法魂本体**里出现过血条名/Boss 行名 —— 它**不参与**判类（共享名不可信，见 §4.1a），只是把这条证据留着。全表 139 个模型带这个标记。
- `schema` = `v2`，用来和 v1 表区分（脚本自己就是靠这一列判断「这是不是 v1 基线」）。

对齐口径的实测结论（供复核）：

- 大小写折叠 / 去零填充两条规则**都没有额外收益**，我们的模型 id 与 ModelName.txt 的键完全同构。
- `ModelNameNT.txt` 本版**未参与判类**：64 个没有 ModelName 条目的模型里，它只覆盖 1 个（c3310），而且给的是内部名 `MarikaLineageWoman`，判不出比中文名更多的信息。

