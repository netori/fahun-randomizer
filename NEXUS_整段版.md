# N 网 · 整段版（一次复制粘贴，五段已合并）

> 用法：**整段选中 → 复制 → 粘进 N 网的 Description 框** ✓
> 里面用 `【】` 分小节 ✓ —— 想拆到另外四个字段里的话 ✓，按这些小标题拆开即可 ✓

---

## 中文整段版（贴中文社区 / 或补在英文下方）

```
【这是什么】

本工具为「法魂」（The Convergence 汉化本体）制作。它换的是法魂职业说明书里那些道具，别的都不动。

【它解决什么问题】

法魂这类大改 MOD，职业流派基本是钉死的：玩辉石法师就那几件装备、就那几个卢恩，开局路线几乎固定。市面上的随机器要么只管原版，要么一键全乱——东西是乱了，但流派也废了。我们做的更窄一点，也更实用一点：只把游戏内职业说明书里出现的道具互相对调，其他一律不动。你还是辉石法师，只是这一周目的关键道具换到别的地方去了，你得重新去找。这就是它和"全乱"的区别。

【五条设计理念】

一、只换物品，不搬位置。宝箱还是那个宝箱、掉落还是那个掉落，我们只改里面放什么。数量、概率、价格、库存、解锁条件、事件流程一律不动。商店完全不参与——商店牵扯解锁与库存，风险不成比例。

二、以职业说明书为准。随机范围严格等于说明书里出现过的物品；换完之后翻开说明书，看到的就是这座世界的真实分布。

三、合理度是一个旋钮，但含义必须精确。它同时控制三件互相独立的事：越档幅度（最远能跨几档）、越档率（多少东西真的跨档）、武器掺入混池的比例。100% 时只能同档互换、一件都不跨；0% 时等级完全放开。档位按游戏自身的推进感划分，而护甲与卢恩天然都是四级，所以混池里能逐档直接对应。一句话：任何一次互换，都必须发生在同一个档位桶里。

四、法师/祷告护甲永不与近战混池。无论合理度拉到多少，都单独一组。

五、写不进去的东西等于没写。每次写入前自动备份，界面一个按钮还原；写入后自动审计。

【说明书会跟着改，但只说真话】

物品名不动，只换它现在所在的地点。规则很直白：X 搬进了原本放 Y 的格子，X 的地点就写成 Y 在原版说明书里的地点，零翻译、零猜测。字体、字号、文本长度都与原版一致；每次写入自动跑八项审计。这套审计在开发中抓出过三个真实的坑，也正因如此才有现在这个版本：一个"内容全对但一启动就崩"的压缩参数问题、说明书被固定文本框悄悄截尾、以及两页说明书因为首行相同而互相覆盖。

最后：同一种子 = 完全一样的世界，把种子记下来就能复盘，也能分享给别人复现。

【安装】

前置：你需要「法魂」汉化本体（V3.0.3）与你自己那份原版游戏文件，这个下载里只有工具本身。

一、把 ConvergenceClassItemRandomizer.exe 放到 MOD 根目录，也就是含 mod\regulation.bin 的那一层，跟存档目录无关。
二、双击打开。界面的「本地文件」会逐项自检：MOD 目录、游戏数据、说明书、原始备份、说明书基准、随机引擎。缺哪项会标红并禁用「写入游戏」直到修好；旁边两个按钮可以直接指定 MOD 目录、或补一份原始备份。
三、勾选要随机的东西（卢恩 / 护甲 / 装备），选混合方式，拉合理度，填种子。
四、点「① 生成随机方案」，看一眼"这次会改什么"。
五、点「② 写入游戏」。工具会先自动备份当前文件、复原成原始，再写入新分布并重写职业说明书。

不满意怎么办：在同一个窗口点「还原成原始」就行，原文件会被原样放回；换个种子再生成一次也可以，随便试多少次。

注意：只改数据文件（mod\regulation.bin 与说明书文件），游戏本体一个字节都不动；首次写入前会自动备份，那份备份请保留，生成方案时要用它；仅限单人游戏，建议先备份存档；exe 未签名，部分杀软首次运行会提示。

【主要特性】

只随机职业说明书里出现的道具，名单之外一概不碰。只换物品不搬位置，数量、概率、价格、库存、解锁条件、事件条件全部原样保留，商店永不参与。一个合理度旋钮分别控制越档幅度、越档率和武器掺入比例——"别太离谱"是一个能调出来的东西，不是一句承诺。四级档位取自游戏本身（卢恩阶位、护甲部位、地区推进度），护甲与卢恩逐档一一对应，混池也不乱。法师/祷告护甲全程隔离，0% 也不例外。套装整组进出，不会只给你半套。说明书同步改写，物品名不动、只改地点，字体颜色排版与原版一致。种子确定、完全可复现。一键还原，随时可用。每次写入自动备份与自动审计；写入前还有一道复核，文件与方案对不上就直接中止，绝不写半成品。

怎么测的：矩阵测试 90 组（15 配置 × 6 种子），覆盖守恒、可复现、法祷零违规；每一种配置都真实启动过一次游戏、确认能进主菜单；说明书八项审计，连审计本身也做了变异测试；另外冻结了一份基准方案，每次改引擎都逐行对比，防止"无意改动了随机结果"。

【前置要求】

必需：ELDEN RING，版本要与你那份法魂本体一致（本版针对 1.17.1）；「法魂」（The Convergence 汉化本体）V3.0.3，YAFSML 构建——本工具改的就是这份 MOD 的数据文件，不能单独使用；以及你自己那份原版文件（未改动过的 regulation.bin 与说明书文件），写入前工具会自动备份它们。

不需要：mod 管理器、脚本扩展、任何外部工具——需要的东西都在这个压缩包里；也不需要开新档，任何阶段的存档都能用。

重要：本工具面向法魂汉化本体。英文版（以及其它语言版）的 The Convergence 物品池与文件结构都不同，目前不支持——不是翻译几个字就能用，请勿抱着这个预期安装。仅限单人游戏，请勿联机时使用。首次写入前请备份存档，和装任何 MOD 前一样。

【致谢】

这个工具站在很多东西上面，逐个谢过。「法魂」（The Convergence）——MOD 本体，以及那套职业说明书；没有这份"哪个职业该拿什么、去哪儿拿"的指南，这个随机器根本无从谈起。YAFSML——运行时注入式加载器，正因为它不动游戏本体，我们才敢只改数据文件。SoulsFormats——regulation.bin 的 AES 方案是从它的 RegulationDecryptor 里读出来的，这个格式的公开资料极少，没有它我们可能还在猜初始化向量。WitchyBND——开发早期用来做交叉验证，同一份文件交给它和我们的代码各解析一遍。Oodle（RAD Game Tools）——压缩算法由游戏自带，我们只是调用。Elden Ring 随机器社区——"自由度的上限该长什么样"是从它们那里学的，也顺带学到：克制是特性，不是缺点。FromSoftware 与万代南梦宫——ELDEN RING，没有这个游戏就没有这一切。

也谢谢每一个试了它、并且回来反馈的人，尤其是那些把它玩坏的人：开发中收到的最有用的一次报错是"两页说明书悄悄覆盖了彼此"，能找到它，正是因为有人在认真看。
```

---

## 英文整段版（贴 N 网 Description）

```
[b]Chinese-localized build only — there is no English version yet.[/b] This tool is built for the Chinese localization of The Convergence (法魂 / 汉化本体): the interface is in Chinese and the guide rewriting expects the Chinese guide file. On the English (or any other language) version the item pool and file layout differ, so it is not a matter of translating a few strings — a proper English build is possible later, but it is not done.

[line]

[b]What it does.[/b] The Convergence locks you into a build: playing a Glintstone Sorcerer means the same gear, the same runes and the same route every run. Most randomizers either ignore total conversions like this or shuffle everything at once — chaos, but your build is dead. This tool does something narrower and, we think, more useful: [b]it swaps the items that appear in the in-game class guides (职业说明书), and nothing else.[/b] You are still a Glintstone Sorcerer — but this run, your key items are somewhere else, and you have to find them again.

[line]

[b]Design principles.[/b] [b]1) Items only — never locations.[/b] A chest stays a chest, a drop stays a drop; only what is inside changes. Quantities, probabilities, prices, stock, unlock flags and event flow are never touched, and merchants are excluded entirely, because shops involve unlock and stock logic and the risk is not worth the reward. [b]2) The class guides are the source of truth.[/b] The pool is exactly the set of items listed in the mod's own guides, so after randomizing, opening a guide shows you the true state of the world. [b]3) "Coherence" (合理度) is one slider with a precise meaning[/b] — it controls three independent things at once: the tier span (how far apart two items may be swapped), the cross-tier rate (what fraction actually crosses a boundary), and how many weapons join the mixed pool. At 100% only same-tier swaps are allowed and nothing crosses; at 0% tiers are fully open. Tiers follow the game's own sense of progression, and since armor and runes are both naturally four-tiered, a mixed pool lines up one-to-one. The rule in one sentence: [b]every swap must happen inside the same tier bucket.[/b] [b]4) Caster armor never mixes with melee armor[/b] — at any setting, including 0%. [b]5) If it cannot be written safely, it is not written[/b] — every write is backed up first, one button restores the original, and every write is audited afterwards.

[line]

[b]The guides stay honest.[/b] After randomizing, the class guides are rewritten so that [b]item names never change — only their listed locations do[/b]: item X moved into the cell that used to hold item Y, so X's listed location becomes Y's original listed location. No translation, no guessing — the location is read straight out of the original guide text. Font size, color and length are preserved, and each write passes eight checks. Three real bugs found this way shaped this release: a byte-correct file that still crashed the game on startup (re-compression frame parameters), guide text silently truncated by fixed-size text boxes, and two guide pages overwriting each other because they share an identical first line. Finally: [b]same seed, same world[/b] — write the seed down to reproduce a run, or share it with a friend.

[line]

[b]Installation.[/b] You need The Convergence (法魂, Chinese localization, V3.0.3) and your own original game files; this download contains the tool only. 1) Put [b]ConvergenceClassItemRandomizer.exe[/b] into the [b]mod's root folder[/b] — the folder containing [b]mod\regulation.bin[/b]; your save folder is not involved. 2) Run it: the [b]Local Files[/b] panel checks the mod folder, the game data, the guide file, your original backups, the guide baseline and the engine — anything missing shows red and [b]Write to game[/b] stays disabled until fixed. 3) Pick what to randomize, pick a mixing mode, drag the [b]coherence[/b] slider, type a [b]seed[/b]. 4) Click [b]① Generate plan[/b] and read the summary. 5) Click [b]② Write to game[/b]: the tool backs up your current files, restores the originals, then writes the new distribution and rewrites the guides. Not happy? Click [b]Restore original[/b] — the original files go back exactly as they were, and you can re-roll with a different seed as often as you like. Only data files are modified ([b]mod\regulation.bin[/b] and the guide message file); the game itself is never touched. Single-player only — please back up your save, and note the exe is unsigned so some antivirus suites may warn on first run.

[line]

[b]Main features.[/b] Randomizes only the class-guide items — nothing outside that list is touched. Items only, never locations: quantities, probabilities, prices, stock, unlock flags and event conditions are left exactly as they were, and merchants never take part. One coherence slider separately controls tier span, cross-tier rate and weapon mix-in, so "not too crazy" is something you can actually dial in instead of a vague promise. The four-tier model is taken from the game itself (rune ranks, armor parts, region progression), and armor and runes line up one-to-one, so a mixed pool stays sane. Caster armor is isolated from melee armor at every setting. Sets are swapped as whole sets, so you never receive half of an armor set. The class guides are rewritten to show where things actually are, with names, fonts, colors and layout matching the original. Seed-based and reproducible: the same seed gives exactly the same world. One-click restore at any time, automatic backup and audit on every write, and a pre-write check that compares your files against the plan and refuses to write if they do not match. It was tested with a 90-run matrix (15 configurations × 6 seeds) covering conservation and reproducibility, every configuration actually launched to the main menu, an eight-check guide audit including an audit of the audit itself, and a frozen reference plan compared line by line on every engine change.

[line]

[b]Requirements.[/b] [b]Required:[/b] ELDEN RING at the version your Convergence install targets (this build targets 1.17.1); The Convergence (法魂, Chinese localization) V3.0.3, YAFSML build — the tool randomizes that mod's data files and does not work standalone; and your own original files (an unmodified [b]regulation.bin[/b] and guide message file), which the tool backs up before writing. [b]Not required:[/b] no mod manager, no script extender, no extra tools — everything needed is in the download — and no new save; you can randomize at any point in an existing playthrough. [b]Important:[/b] [b]Chinese-localized build only[/b] — the English and other language versions are not supported yet; single-player only; back up your save before your first write, as you would before any mod change.

[line]

[b]Shout outs.[/b] This tool stands on a lot of other people's work. [b]The Convergence (法魂)[/b] — the mod itself and the class guides that make this randomizer possible at all. [b]YAFSML[/b] — the runtime-injection loader; because it never touches the game folder, we can safely randomize data files and leave everything else alone. [b]SoulsFormats[/b] — the AES scheme for regulation.bin was read out of its RegulationDecryptor; public documentation for this format is scarce, and without it we would still be guessing initialization vectors. [b]WitchyBND[/b] — used during development for cross-validation, the same file parsed by two independent tools. [b]Oodle (RAD Game Tools)[/b] — the compression algorithm ships with the game; we only call it. [b]The wider Elden Ring randomizer community[/b] — for showing what the ceiling on randomization freedom looks like, and for the lesson that restraint is a feature. [b]FromSoftware and Bandai Namco[/b] — ELDEN RING. And thanks to everyone who tries this and reports back, especially anyone who breaks it: the most useful bug report we got during development was two guide pages quietly overwriting each other, and we only found it because someone was paying attention.
```
