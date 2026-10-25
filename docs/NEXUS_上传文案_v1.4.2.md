# N 网上传文案 · v1.4.2（以此为准）

> 生成日期：2026-10-25。适用发行包：..\发布包\ConvergenceClassItemRandomizer_v1.4.2.zip（20,560,835 B / SHA16 C4DD7B1251A1FD5A）。
> **旧的 docs/NEXUS_发布文案.md、NEXUS_建页清单.md、NEXUS_英文简介.md、NEXUS_页面字段.md、NEXUS_整段版.md 全部是 v1.1.0 时代（只有物品、直写本体流程）的稿子，已过时，不要直接贴。** 本文件是按 v1.4.2 现功能重写的完整上传包，英文为主 + 中文补充段。

## 0. 名字

**推荐（Mod 页 Name）**
Convergence Item & Enemy Randomizer (法魂 物品与敌人随机器)

备选：
- Convergence Randomizer — Items & Enemies (法魂随机器)
- Convergence Randomizer (法魂 物品与敌人随机器)

说明：exe 文件名保持 **ConvergenceClassItemRandomizer.exe** 不变（方案层路径、自检与文档都按它写）；N 网上传时只改「显示名 / 文件展示名」，不用改 exe 与 zip 内部结构。文件展示名建议：**Convergence Item & Enemy Randomizer v1.4.2**。

## 1. 简介（Summary，N 网限 350 字符）

**英文（319 字符 / 325 字节）**
~~~text
Two randomizers in one for The Convergence (法魂): reshuffle class-guide item locations and swap enemies and bosses across the whole map — 7 presets, multi-phase and duo bosses, regional scaling, plan layers, per-plan saves. The base mod is never modified; one click back. Chinese-localized build only; no English UI yet.
~~~

**中文摘要（117 字，可放描述开头或中文补充段）**
~~~text
法魂专用「物品 + 敌人」双随机器：物品只换说明书地点；敌人按 9 类 + 4 个特殊池互抽，含多阶段 / 双人 BOSS、区域缩放、7 份预设。随机只生成方案，开玩才挂覆盖层，法魂本体一个字节不改，一键切回。仅支持中文法魂汉化本体。
~~~

## 2. Description（英文 BBCode，整段复制）

~~~bbcode
[center][size=6][b]Convergence Item & Enemy Randomizer[/b][/size]
[size=4]法魂 物品与敌人随机器[/size]
[i]Two randomizers for The Convergence — reshuffle where class items are, and who stands where.[/i][/center]

[line]
[size=5][b][color=orange]Language notice: Chinese localization only (for now).[/color][/b][/size]
This tool is built for the [b]Chinese localized build[/b] of The Convergence (法魂 · 汉化本体 V3.0.3, YAFSML build, ELDEN RING 1.17.1). The UI is entirely Chinese, the guide-text rewriting only works with the Chinese guide file, and the path checks expect that layout. There is no English build yet — it is not a matter of translating a few strings. It will not work correctly on other language versions.

[line]
[size=5][b]What this is[/b][/size]
Two independent randomizers that share one plan system:
[list]
[*][b]Item randomizer[/b] — swaps the items listed in the in-game class guides (职业说明书). Item identities only: quantities, drop rates, prices, stock and unlock flags are never touched. The guides are rewritten to show the real new locations.
[*][b]Enemy randomizer[/b] — swaps enemies and bosses across the whole map by class, with regional scaling, boss HP balance, boss health-bar names, multi-phase bosses, duo bosses and four special pools.
[/list]
You can randomize items, enemies, or both into a single plan.

[line]
[size=5][b]Nothing is written into the base mod[/b][/size]
Randomizing creates a [b]plan[/b], not a modified mod. When you press Play, the tool builds an [b]overlay layer[/b] (regulation, guides, maps, events) and mounts it through YAFSML's Plan= line. The Convergence's own mod folder is never modified — byte for byte. Switching back is one click: remove the mount and the base mod is exactly as it was. Plans are kept in a plan library and can be renamed, tagged, copied, exported/imported. Each plan gets its own save slot, stored inside the Convergence folder; progress is saved back to that slot when you exit the game.

[line]
[size=5][b]Item randomization[/b][/size]
[list]
[*]Pick runes / armor / weapons; mix all categories, pair two categories, or keep each category separate. Caster (mage/incantation) armor always stays in its own pool.
[*]One [b]Coherence[/b] slider (0–100%, default 80%) controls tier span, cross-tier rate, and how many weapons can join a mixed pool (hard cap 66%). At 80% a pool can only widen two tiers, with at most 20% of rolls crossing tiers.
[*]Optional: include class gear sold by merchants. Only the 69 class-gear rows (50 caster armor, 16 melee, 2 weapons) are touched; prices, stock limits and unlock conditions never change. The other 1,485 merchant rows stay untouched.
[*]Item names, quantities, probabilities, prices and unlock conditions never change — only where each guide entry points.
[*]Every write is audited; a plan is fully reproducible from its seed.
[/list]

[line]
[size=5][b]Enemy randomization[/b][/size]
[list]
[*][b]9 visible classes[/b] — regular enemies (including The Convergence's unnamed mobs), passive wildlife, hostile NPCs, major bosses, minor bosses, field bosses, night bosses, dragon bosses, evergaol bosses. Six internal marker classes (uncategorized, helpers/summons, duplicates, dummies, scarabs, caravan trolls) are never randomized and never used as sources.
[*][b]Four special pools[/b] — Erdtree waygates, Great Pot keystones, Remembrances, Rauh reliquary. Each can be toggled on/off; pool placements can keep their original occupant or draw replacements of their own, and pools can also be used as sources elsewhere.
[*][b]7 built-in presets[/b] — from a conservative same-family default to full chaos, with difficulty tiering: important boss slots draw more Remembrance/Keystone bosses, field/night/dragon slots draw more field bosses. Presets can be edited per class and saved as your own.
[*][b]Multi-phase bosses[/b] — 14 groups / 20 bosses / 33 placements. Same model = one boss (one identity, one HP); different forms = separate bosses. Phases are event-driven, so only the boss identity is swapped; transformation sequences stay with their original arena.
[*][b]Duo bosses[/b] — the second unit of 6 duo fights can be swapped independently, keeping the same entity and only changing identity + health-bar name. HP follows its original ratio, runes are set to 0. Three crystalian groups and one godskin group are off by default; the mimic-tear pair is not touched.
[*][b]Event-placed bosses[/b] — 9 bosses / 10 placements that older tools had to skip are now replaceable through the same model/npc/AI/appearance four-field swap.
[*][b]Regional scaling[/b] — every incoming enemy gets its own SpEffect matching the area's strength (HP, attack, defense, resistances, runes). A boss placed into a regular-enemy slot is scaled down (HP ×0.25, runes ×0.25, damage ×0.5) and the balance pass brings its effective HP back to that placement's intended strength.
[*][b]Boss HP balance[/b] — boss-to-boss swaps are anchored between 0.85× and 1.25× of the original boss at that spot, with k=10 stratified sampling. Regular enemies are not touched by this pass.
[*][b]Switches[/b] — boss health-bar names, night bosses anytime, ignore size/arena limits, BGM follows the new boss, runes follow the new boss, random enemy colors (experimental), HP multiplier 0.5–2.0×, "replace all" class override, enemy onslaught 1.0–2.0× (regular enemies only), 5–100% replace rate, seed.
[*][b]Fine control[/b] — per-class preset editor (14 source rows: 9 classes + 4 pools + same-type bosses), per-class rate/targets/size caps, a boss usage cap (default 5 per boss, 0 = unlimited), and a manual CSV to pin individual placements by map/entity/npc/model.
[/list]

[line]
[size=5][b]Built-in presets[/b][/size]
[list]
[*][b]01 Reference default · same-family[/b] — closest to a classic randomizer; difficulty-tiered.
[*][b]02 Boss brawl[/b] — all boss classes draw from each other; hard tiering toward Remembrance/Keystone.
[*][b]03 Mob brawl[/b] — regular ↔ wildlife mix; boss slots stay in-family but lean toward harder pools.
[*][b]04 Everything brawl[/b] — all 9 classes + 4 pools share one weighted pool.
[*][b]05 Conservative half[/b] — same as 01, but only 50% of placements change.
[*][b]06 All-boss pool · same-family mobs[/b] — bosses share one pool, mobs stay in-family.
[*][b]07 Same-type bosses · same-family mobs[/b] — each boss class only draws from its own type.
[/list]

[line]
[size=5][b]Requirements[/b][/size]
[list]
[*]ELDEN RING — the version required by your Convergence install (tested on 1.17.1)
[*]The Convergence (法魂) V3.0.3 — Chinese localization, YAFSML injector build (new YAFSML engine V0.10.4)
[*]Your own original regulation.bin and guide file; the tool backs them up on first run
[*]Single-player, offline. Back up your save. Disable Steam Cloud if you use multiple plans.
[/list]

[line]
[size=5][b]Installation[/b][/size]
[list=1]
[*]Put ConvergenceClassItemRandomizer.exe in the mod root folder (the folder that contains mod\regulation.bin), next to the mod folder and 启动法魂.bat.
[*]Run it. The Local Files panel checks the mod folder, game data, guide file, writability, original backup, guide baseline and engine. Missing required items disable the Start button.
[*]Choose what to randomize (items / enemies / both), configure, and press Start. This creates a plan and saves it to the plan library — no game files are written yet.
[*]Open the plan library and double-click the plan (or press Play). The first run generates the overlay layer (about a minute for items; 3–4 minutes with enemies), swaps in the plan's save, mounts the layer and launches the game.
[*]To return to the plain Convergence experience, press "Switch back to base mod". The layer stays in the plans folder and can be reused.
[/list]

[line]
[size=5][b]Notes and honest risks[/b][/size]
[list]
[*]Enemy randomization is newer than item randomization. Event-placed bosses, duo second units and the experimental switches can occasionally produce T-pose or floating enemies, or a stuck cutscene. If a placement breaks, switch back to the base mod or rebuild with preset 01 — the base mod is never damaged.
[*]Multi-phase mechanics are not portable: phase 2 depends on arena events (SpEffects, animations, scripted AI). Swapping a boss copies its identity, not its transformation sequence. Since 1.4.2, same-model bosses only contribute their phase-1 identity as a source, so you will no longer see a phase-2 name paired with phase-1 moves.
[*]Bosses entering regular-enemy slots are rebalanced as described above; since 1.4.1 their effective HP lands at the placement's intended strength instead of being cut twice.
[*]The UI is Chinese. The tool logic is language-agnostic, but guide rewriting and path checks are built for the Chinese Convergence build.
[*]The exe is unsigned; some antivirus software may warn on first run. The tool does not connect to the internet.
[*]Not for online play. Only local data files are modified; no game or mod files are redistributed.
[/list]

[line]
[size=5][b]Version 1.4.2 highlights[/b][/size] (initial public release)
[list]
[*]Item randomizer with coherence, mixing modes, optional merchant class gear, and guide rewriting.
[*]Enemy randomizer with 9 classes, 4 special pools, 7 presets, multi-phase and duo bosses, regional scaling and boss balance.
[*]Plan library with per-plan saves, overlay layers and one-click restore; the base mod stays untouched.
[*]1.4.1: fixed double scaling for bosses in regular slots; multi-phase/duo entities no longer misclassified; all four special pools wired into the built-in presets.
[*]1.4.2: multi-phase bosses contribute only their phase-1 identity as a source.
[/list]

[line]
[size=5][b]Credits[/b][/size]
[list]
[*][b]The Convergence[/b] — the total-conversion mod this tool is built for.
[*][b]YAFSML[/b] — mod loader and plan-layer mounting used by this tool.
[*][b]SoulsFormats[/b], [b]WitchyBND[/b], [b]Oodle[/b] — file formats, unpacking and compression.
[*]The Elden Ring randomizer community — reference behavior and years of prior work.
[*][b]FromSoftware[/b] / [b]Bandai Namco[/b] — ELDEN RING.
[/list]
This tool redistributes no game or mod files; it only reads your installation and writes its own plan/layer files.

[line]
[size=5][b]Permissions[/b][/size]
[list]
[*]Redistribution: allowed, with credit and a link back to this page.
[*]Modification: allowed, with credit.
[*]Inclusion in modpacks: allowed.
[*]Using assets from other authors: yes — The Convergence, YAFSML, SoulsFormats, WitchyBND and Oodle, with credit.
[/list]

[line]
[center][i]Same seed, a different world. 同一颗种子，完全不同的交界地。[/i][/center]
~~~

## 3. 中文补充段（贴在英文 Description 末尾）

~~~bbcode
[size=5][b]中文说明[/b][/size]
[list]
[*][b]两个模式，一份方案[/b]：物品随机与敌人随机可分开、也可一起生成；随机只生成「方案」，不写游戏文件。
[*][b]本体零改动[/b]：开玩时才生成覆盖层（regulation / 说明书 / 地图 / 事件），经 YAFSML 的 Plan= 挂上去；切回本体 = 一键删挂载，法魂本体一个字节不改。
[*][b]物品[/b]：只换说明书里的物品地点，名字 / 数量 / 概率 / 价格 / 解锁条件不动；合理度一个滑杆管档位跨度、越档率、武器掺入上限；商店职业装备可选（只动 69 行职业装备）。
[*][b]敌人[/b]：9 个可见类别 + 4 个特殊池（黄金树传送门 / 大锅钥石 / 追忆 / 劳弗圣龛）；7 份内置预设；多阶段 14 组 / 20 只 Boss / 33 个位置；双人 Boss 第二只 6 组默认开；A 批 9 个事件系 Boss（10 个位置）；区域缩放 + Boss 数值平衡。
[*][b]方案库与独立存档[/b]：每套方案一份存档，退出游戏自动存回；覆盖/删除前先备份到存档库回收站。
[*][b]风险如实说[/b]：双人第二只与事件系 Boss 属较新功能，个别位置可能出现 T-pose / 漂浮 / 演出卡住 —— 切回本体即可，本体不会坏。多阶段 Boss 的「二阶段变身」靠战场事件，换到别处带不过去；v1.4.2 起同模型 Boss 只用一阶段身份当来源，避免「二阶段名字 + 一阶段招式」。
[*][b]前置[/b]：中文法魂 V3.0.3 汉化本体（适配游戏 1.17.1，新 YAFSML 引擎 V0.10.4）；单机离线；先备份存档；多套方案请关 Steam 云存档。
[/list]
~~~

## 4. 上传字段

| 字段 | 值 |
|---|---|
| Game | Elden Ring |
| Name | Convergence Item & Enemy Randomizer (法魂 物品与敌人随机器) |
| Summary | 见第 1 节（319 字符 / 325 字节，上限 350） |
| Category | Gameplay（如需二级分类：Gameplay > Mechanics / Utilities） |
| Version | 1.4.2 |
| Adult content | No |
| Language | Chinese (Simplified) — UI；描述可用英文为主 |
| Requirements | ELDEN RING 1.17.1 + The Convergence（法魂）V3.0.3 汉化本体（YAFSML build, new engine V0.10.4）；原版 regulation.bin 与说明书；单机离线 |
| File display name | Convergence Item & Enemy Randomizer v1.4.2 |
| File version | 1.4.2 |
| File description | v1.4.2 initial public release. Chinese-localized Convergence only. ZIP includes the tool (exe), an offline HTML tutorial (使用教学.html), the player guide, README and changelog. |
| Tags | Randomizer, Items, Enemies, Bosses, Utility, Singleplayer, Chinese |
| Nexus Permissions | Redistribution: allowed with credit · Modification: allowed with credit · Modpacks: allowed · Uses other authors' assets: yes |
| Credits | The Convergence; YAFSML; SoulsFormats; WitchyBND; Oodle; Elden Ring randomizer community; FromSoftware / Bandai Namco |
| Changelog | See section 5 |

> 上传文件就用现成的 ..\发布包\ConvergenceClassItemRandomizer_v1.4.2.zip（20,560,835 B / SHA16 C4DD7B1251A1FD5A），文件展示名按上表改成新名字即可；exe 文件名保持 ConvergenceClassItemRandomizer.exe 不变（方案层路径、文档、自检都按这个名字写，改名反而引入风险）。

## 5. 文件描述 / 更新日志（可直接贴）

[b]v1.4.2 — initial public release[/b]
[list]
[*]Item randomizer: runes / armor / weapons, mixing modes, coherence slider, optional merchant class gear, guide rewriting, per-plan saves.
[*]Enemy randomizer: 9 visible classes, 4 special pools, 7 presets, multi-phase bosses (14 groups / 20 bosses / 33 placements), duo second units (6 groups on by default), 9 event-placed bosses, regional scaling, boss HP balance, bar names, manual CSV.
[*]Plan layers and plan library: base mod untouched, one-click switch back, per-plan independent saves.
[*]Included: tool exe, offline HTML tutorial (使用教学.html), player guide (使用说明（给玩家）.md), README, full changelog.
[*]Chinese-localized Convergence build only (V3.0.3 / ELDEN RING 1.17.1 / YAFSML V0.10.4). Single-player offline.
[/list]

## 6. 截图 / 首图建议

N 网首图建议用游戏内实拍，而不是宣传封面（封面可作视频缩略图）：
1. 主界面三页签 + 本地文件自检全绿。
2. 物品随机结果：同一件装备「原来 / 换成」对照（可截方案库详情）。
3. 敌人页：4 个特殊池 + 7 个开关 + 生命值倍率。
4. 编辑器或 7 份预设列表。
5. 游戏中换过 Boss 的血条名实拍（例如某个杂兵位站着「恶之蛇」梅瑟莫——v1.4.2 后不会再出现二阶段名）。
6. 方案层目录 + Plan= 挂载 / 切回说明。

## 7. 发布前检查

[list]
[*]名字、Summary、Description 三段都已按 v1.4.2 替换，不再出现 items-only 或「写入游戏/还原」旧流程。
[*]明确写了「仅中文法魂汉化本体」与「单机离线」。
[*]权限四项与 Credits 已填。
[*]文件用 v1.4.2 zip；文件展示名改新名字；版本号 1.4.2。
[*]旧 NEXUS_*.md（v1.1.0 时代）不要直接复制，以本文件为准。
[/list]
