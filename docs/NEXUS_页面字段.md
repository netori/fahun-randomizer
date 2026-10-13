# N 网新表单 · 五个字段的英文内容（整段复制粘贴）

> 对应表单里的五个框：**Description / Installation instructions / Main features / Requirements / Shout outs**
> 每段都是**独立完整**的 ✓ 可以整段粘 ✓
> 刻意**不用表格** ✗（N 网对 BBCode 表格时好时坏 ✓）—— 只用加粗与列表 ✓

---

## 1. Description

```
[b]Chinese-localized build only — there is no English version yet.[/b]

This tool is built for the Chinese localization of The Convergence (法魂 / 汉化本体). The user interface is entirely in Chinese, and the guide-text rewriting expects the Chinese guide file. If you play the English (or any other language) version of The Convergence, this tool is not usable yet — the item pool and the file layout differ, so it is not a matter of translating a few strings. A proper English build is possible later; it is not done.

[line]

[b]What it does[/b]

The Convergence locks you into a build. Playing a Glintstone Sorcerer means the same gear, the same runes and the same route every run. Most randomizers either ignore total conversions like this or shuffle everything at once — chaos, but your build is dead.

This tool does something narrower, and we think more useful:

[b]It swaps the items that appear in the in-game class guides (职业说明书), and nothing else.[/b]

You are still a Glintstone Sorcerer — but this run, your key items are somewhere else, and you have to find them again.

[line]

[b]Design principles[/b]

[b]1. Items only — never locations.[/b] A chest stays a chest, a drop stays a drop. Only what is inside changes. Quantities, probabilities, prices, stock, unlock flags and event flow are never touched. Merchants are off by default — an advanced option can include the class gear merchants sell, and even then only the item changes: prices, stock limits and unlock conditions are never touched.

[b]2. The class guides are the source of truth.[/b] The randomization pool is exactly the set of items listed in the mod's own class guides. After randomizing, opening a guide shows you the true state of the world.

[b]3. "Coherence" (合理度) is one slider, but its meaning is precise.[/b] It controls three independent things at once:

[list]
[*][b]Tier span[/b] — how far apart two items may be swapped
[*][b]Cross-tier rate[/b] — what fraction of items actually cross a tier boundary
[*][b]Weapon mix-in[/b] — how many weapons join the mixed pool
[/list]

At 100% only same-tier swaps are allowed and nothing crosses a boundary. At 0% tiers are fully open. Tiers follow the game's own sense of progression, and armor and runes are both naturally four-tiered, so in a mixed pool they line up one-to-one.

[b]The rule in one sentence: every swap must happen inside the same tier bucket.[/b]

[b]4. Caster armor never mixes with melee armor.[/b] Mage and incantation armor stays in its own pool, always.

[b]5. If it cannot be written safely, it is not written.[/b] Every write is backed up first — one button restores the original — and every write is audited afterwards.

[line]

[b]The guides stay honest[/b]

After randomizing, the class guides are rewritten so that [b]item names never change — only their listed locations do[/b]. Item X moved into the cell that used to hold item Y, so X's listed location becomes Y's original listed location. No translation, no guessing: the location is read straight out of the original guide text.

Font size, font color and text length are preserved, and the rewrite is audited on every write with eight checks. Three real bugs found this way are worth mentioning, because they shaped this release: a byte-correct file that still crashed the game on startup (re-compression frame parameters), guide text silently truncated by fixed-size text boxes, and two guide pages overwriting each other because they share an identical first line.

[line]

[b]Same seed, same world.[/b] Write the seed down to reproduce a run, or share it with a friend.
```

---

## 2. Installation instructions

```
[b]You need The Convergence (法魂, Chinese localization, V3.0.3) and your own original game files. This download contains the tool only.[/b]

[list=1]
[*]Put [b]ConvergenceClassItemRandomizer.exe[/b] into the [b]mod's root folder[/b] — the folder that contains [b]mod\regulation.bin[/b]. Your save folder is not involved.
[*]Run the exe. The [b]Local Files[/b] panel checks everything it needs: the mod folder, the game data, the guide file, your original backups, the guide baseline and the randomizer engine. Anything missing is shown in red and [b]Write to game[/b] stays disabled until it is fixed. Two buttons next to it let you point at the mod folder or create a missing original backup.
[*]Choose what to randomize (runes / armor / weapons), choose how they mix, drag the [b]coherence[/b] slider and type a [b]seed[/b].
[*]Click [b]① Generate plan[/b] and read the summary of what will change.
[*]Click [b]② Write to game[/b]. The tool backs up your current files automatically, restores the original ones, then writes the new distribution and rewrites the class guides.
[/list]

[line]

[b]Not happy with the result?[/b]

Click [b]Restore original[/b] in the same window. That is all it takes — the original files are put back exactly as they were. You can randomize again with a different seed as many times as you like.

[line]

[b]Notes[/b]

[list]
[*]Only data files are modified: [b]mod\regulation.bin[/b] and the guide message file. The game itself is never modified.
[*]Your files are backed up before the first write. Keep that backup safe — the tool needs it for generating the plan.
[*]Single-player use only. Please back up your save.
[*]The exe is unsigned, so some antivirus suites may show a first-run warning.
[*]The interface is in Chinese.
[/list]
```

---

## 3. Main features

```
[list]
[*][b]Randomizes only the class-guide items[/b] — the set of items the mod's own guides describe. Nothing outside that list is touched.
[*][b]Plan library.[/b] Save any generated plan, rename it, favourite it, tag it, duplicate it, export it as a file, and write it to the game again at any time. Plans are stored next to the tool, so reinstalling the tool never loses them.
[*][b]Items only, never locations.[/b] Quantities, probabilities, prices, stock, unlock flags and event conditions are left exactly as they were. Merchants are off by default; when enabled in the advanced settings, only the item changes — prices, stock limits and unlock conditions stay exactly as they were.
[*][b]One coherence slider[/b] that separately controls tier span, cross-tier rate and weapon mix-in — so "not too crazy" is something you can actually dial in, instead of a vague promise.
[*][b]Four-tier model taken from the game itself[/b] — runes, armor parts and region progression. Armor and runes line up one-to-one, so a mixed pool stays sane.
[*][b]Caster armor is isolated[/b] from melee armor at every setting, including 0%.
[*][b]Sets are swapped as whole sets.[/b] You never receive half of an armor set.
[*][b]The class guides are rewritten[/b] to show where things actually are. Item names stay untouched; only the listed locations change. Font size, color and layout match the original.
[*][b]Seed-based and reproducible[/b] — the same seed gives you exactly the same world, so you can share a seed or re-roll just by changing one number.
[*][b]One-click restore[/b] at any time.
[*][b]Automatic backup and audit[/b] on every write, plus a pre-write check that compares your files against the plan and refuses to write if they do not match.
[/list]

[line]

[b]A note on how it was tested[/b]

[list]
[*]A matrix test of 90 runs (15 configurations × 6 seeds) covering conservation, reproducibility and caster isolation
[*]Every configuration actually launched the game and reached the main menu
[*]An eight-check audit of the guide text, including an audit of the audit itself
[*]A frozen reference plan, compared line by line on every engine change, to catch unintended changes to results
[/list]
```

---

## 4. Requirements

```
[b]Required[/b]

[list]
[*][b]ELDEN RING[/b] — the version your Convergence install is built for (this build targets 1.17.1)
[*][b]The Convergence (法魂), Chinese localization, V3.0.3[/b], YAFSML build — this tool randomizes that mod's data files, it does not work standalone
[*]Your own [b]original[/b] game files: the unmodified [b]regulation.bin[/b] and the guide message file, as shipped with your Convergence install. The tool backs them up before it writes anything.
[/list]

[line]

[b]Not required[/b]

[list]
[*]No mod manager, no script extender, no additional tools. Everything the randomizer needs is inside the download.
[*]No new save. You can randomize at any point in an existing playthrough.
[/list]

[line]

[b]Important[/b]

[list]
[*][b]Chinese-localized build only.[/b] The English (and other language) versions of The Convergence are [b]not supported yet[/b] — different item pool and different file layout. Please do not install this expecting it to run there.
[*]Single-player only. Do not use it while playing online.
[*]Back up your save before your first write, as you would before any mod change.
[/list]
```

---

## 5. Shout outs

```
This tool stands on a lot of other people's work, so here is each one.

[b]The Convergence (法魂)[/b] — the mod itself, and the class guides that make this randomizer possible at all. Without that "which class gets what, and where" guide, there would be nothing to randomize against.

[b]YAFSML[/b] — the runtime-injection loader. Because it never touches the game folder, we can safely randomize data files and leave everything else alone.

[b]SoulsFormats[/b] — the AES scheme for regulation.bin was read out of its RegulationDecryptor. Public documentation for this format is scarce, and without it we would still be guessing initialization vectors.

[b]WitchyBND[/b] — used during development for cross-validation: the same file parsed by two independent tools, to make sure our own reader was not quietly drifting.

[b]Oodle (RAD Game Tools)[/b] — the compression algorithm ships with the game; we only call it.

[b]The wider Elden Ring randomizer community[/b] — for showing what the ceiling on randomization freedom looks like, and for the general lesson that restraint is a feature.

[b]FromSoftware and Bandai Namco[/b] — ELDEN RING. None of this would exist otherwise.

[line]

And thanks to everyone who tries this and reports back — especially anyone who breaks it. The most useful bug report we got during development was two guide pages quietly overwriting each other, and we only found it because someone was paying attention.
```

---

---

# 中文版（五个字段 · 原生中文，不是翻译腔）

> 用途：贴在英文版下方 ✓（N 网有不少中文玩家 ✓），或直接发中文社区 ✓（B 站 / 贴吧 / 3DM 等 ✓）
> 同样**不用表格** ✗ —— 只用加粗与列表 ✓

---

## 1. 描述（Description）

```
[b]本工具为「法魂」（The Convergence 汉化本体）制作。[/b]

它不是通用随机器：换的是法魂职业说明书里那些道具，别的都不动。

[line]

[b]它解决什么问题[/b]

法魂这类大改 MOD，职业流派基本是钉死的：玩辉石法师就那几件装备、就那几个卢恩，开局路线几乎固定。市面上的随机器要么只管原版，要么"一键全乱"——东西是乱了，但流派也废了。

我们做的更窄一点，也更实用一点：

[b]只把游戏内职业说明书里出现的道具互相对调，其他一律不动。[/b]

你还是辉石法师，只是这一周目的关键道具换到别的地方去了，你得重新去找。这就是它和"全乱"的区别。

[line]

[b]设计理念[/b]

[b]1. 只换物品，不搬位置。[/b] 宝箱还是那个宝箱、掉落还是那个掉落，我们只改里面放什么。数量、概率、价格、库存、解锁条件、事件流程一律不动。[b]商店默认不参与[/b]（可在「更多设置」里开启；开启后也只换职业专属装备，价格、限量、解锁条件一律不动）。

[b]2. 以职业说明书为准。[/b] 随机范围严格等于说明书里出现过的物品。换完之后翻开说明书，看到的就是这座世界的真实分布。

[b]3. 合理度是一个旋钮，但它的含义必须精确。[/b] 它同时控制三件互相独立的事：

[list]
[*][b]越档幅度[/b] —— 最远能跨几档
[*][b]越档率[/b] —— 多少东西真的跨档
[*][b]武器掺入混池的比例[/b]
[/list]

100% 时只能同档互换、一件都不跨；0% 时等级完全放开。档位是按游戏自身的推进感分的，而护甲与卢恩天然都是四级，所以混池里能逐档直接对应。

[b]一句话：任何一次互换，都必须发生在同一个档位桶里。[/b]

[b]4. 法师/祷告护甲永不与近战混池。[/b] 无论合理度拉到多少，都单独一组。

[b]5. 写不进去的东西等于没写。[/b] 每次写入前自动备份，界面一个按钮还原；写入后自动审计。

[line]

[b]说明书会跟着改，但只说真话[/b]

[b]物品名不动，只换它现在所在的地点。[/b] 规则很直白：X 搬进了原本放 Y 的格子，X 的地点就写成 Y 在原版说明书里的地点。零翻译、零猜测。

字体、字号、文本长度都与原版一致；每次写入自动跑八项审计。这套审计在开发中抓出过三个真实的坑，也正因如此才有现在这个版本：一个"内容全对但一启动就崩"的压缩参数问题、说明书被固定文本框悄悄截尾、以及两页说明书因为首行相同而互相覆盖。

[line]

[b]同一种子 = 完全一样的世界。[/b] 把种子记下来就能复盘，也能分享给别人复现。
```

---

## 2. 安装说明（Installation instructions）

```
[b]前置：你需要「法魂」汉化本体（V3.0.3）与你自己那份原版游戏文件。这个下载里只有工具本身。[/b]

[list=1]
[*]把 [b]ConvergenceClassItemRandomizer.exe[/b] 放到 [b]MOD 根目录[/b]——就是含 [b]mod\regulation.bin[/b] 的那一层。跟存档目录无关。
[*]双击打开。界面里的 [b]本地文件[/b] 会逐项自检：MOD 目录、游戏数据、说明书、原始备份、说明书基准、随机引擎。缺哪项会标红，并[b]禁用「写入游戏」[/b]直到修好；旁边两个按钮可以直接指定 MOD 目录、或补一份原始备份。
[*]勾选要随机的东西（卢恩 / 护甲 / 装备），选混合方式，拉合理度，填种子。
[*]点 [b]① 生成随机方案[/b]，看一眼「这次会改什么」。
[*]点 [b]② 写入游戏[/b]。工具会先自动备份当前文件、复原成原始，再写入新的分布并重写职业说明书。
[/list]

[line]

[b]不满意怎么办[/b]

在同一个窗口点 [b]还原成原始[/b] 就行，原文件会被原样放回。想重来就换个种子再生成一次，随便试多少次都可以。

[line]

[b]注意[/b]

[list]
[*]只改数据文件：[b]mod\regulation.bin[/b] 与说明书文件。游戏本体一个字节都不动。
[*]首次写入前会自动备份，那份备份请保留——生成方案时要用它。
[*]仅限单人游戏，建议先备份存档。
[*]exe 未签名，部分杀软首次运行会提示。
[/list]
```

---

## 3. 主要特性（Main features）

```
[list]
[*][b]只随机「职业说明书」里出现的道具[/b]——范围就是法魂自己那份指南写到的那些，名单之外的东西一概不碰。
[*][b]方案库。[/b]生成出来的方案可以保存下来，随时改名、收藏、打标签、复制、导出成文件，并随时写回游戏；方案存放在工具旁边，重装工具不会丢。
[*][b]只换物品，不搬位置。[/b] 数量、概率、价格、库存、解锁条件、事件条件全部原样保留；商店默认不参与，可在「更多设置」里开启（开启后价格、限量、解锁条件仍然不动）。
[*][b]一个合理度旋钮[/b]，分别控制越档幅度、越档率和武器掺入比例——"别太离谱"是一个能调出来的东西，不是一句承诺。
[*][b]四级档位取自游戏本身[/b]：卢恩阶位、护甲部位、地区推进度。护甲与卢恩逐档一一对应，混池也不乱。
[*][b]法师/祷告护甲全程隔离[/b]，0% 也不例外。
[*][b]套装整组进出[/b]，不会只给你半套。
[*][b]说明书同步改写[/b]，物品名不动、只改地点；字体、颜色、排版与原版一致。
[*][b]种子确定、完全可复现[/b]：同一种子得到同一个世界，换个数字就是另一套。
[*][b]一键还原[/b]，随时可用。
[*][b]每次写入自动备份 + 自动审计[/b]；写入前还有一道复核，文件与方案对不上就直接中止，绝不写半成品。
[/list]

[line]

[b]怎么测的[/b]

[list]
[*]矩阵测试 90 组（15 配置 × 6 种子），覆盖守恒、可复现、法祷零违规
[*]每一种配置都真实启动过一次游戏，确认能进主菜单
[*]说明书八项审计，连审计本身也做了变异测试
[*]冻结了一份基准方案，每次改引擎都逐行对比，防止"无意改动了随机结果"
[/list]
```

---

## 4. 前置要求（Requirements）

```
[b]必需[/b]

[list]
[*][b]ELDEN RING[/b]——版本要与你那份法魂本体一致（本版针对 1.17.1）
[*][b]「法魂」（The Convergence 汉化本体）V3.0.3[/b]，YAFSML 构建——本工具改的就是这份 MOD 的数据文件，不能单独使用
[*]你自己那份[b]原版[/b]文件：未改动过的 [b]regulation.bin[/b] 与说明书文件。写入前工具会自动备份它们。
[/list]

[line]

[b]不需要[/b]

[list]
[*]不需要 mod 管理器、不需要脚本扩展、不需要任何外部工具——随机器要用的东西都在这个压缩包里。
[*]不需要开新档，任何阶段的存档都能用。
[/list]

[line]

[b]重要[/b]

[list]
[*]本工具面向[b]法魂汉化本体[/b]。英文版（以及其它语言版）的 The Convergence 物品池与文件结构都不同，[b]目前不支持[/b]——不是翻译几个字就能用，请勿抱着这个预期安装。
[*]仅限单人游戏，请勿在联机时使用。
[*]首次写入前请备份存档，和装任何 MOD 前一样。
[/list]
```

---

## 5. 致谢（Shout outs）

```
这个工具站在很多东西上面，逐个谢过。

[b]「法魂」（The Convergence）[/b]——MOD 本体，以及那套职业说明书。没有这份"哪个职业该拿什么、去哪儿拿"的指南，这个随机器根本无从谈起。

[b]YAFSML[/b]——运行时注入式加载器。正因为它不动游戏本体，我们才敢只改数据文件、别的一概不碰。

[b]SoulsFormats[/b]——[b]regulation.bin[/b] 的 AES 方案是从它的 RegulationDecryptor 里读出来的。这个格式的公开资料极少，没有它我们可能还在猜初始化向量。

[b]WitchyBND[/b]——开发早期用来做交叉验证：同一份文件交给它和我们的代码各解析一遍，确认自己的实现没悄悄跑偏。

[b]Oodle（RAD Game Tools）[/b]——压缩算法由游戏自带，我们只是调用。

[b]Elden Ring 随机器社区[/b]——"自由度的上限该长什么样"，是从它们那里学的；也顺带学到一个道理：克制是特性，不是缺点。

[b]FromSoftware 与万代南梦宫[/b]——ELDEN RING。没有这个游戏，就没有这一切。

[line]

也谢谢每一个试了它、并且回来反馈的人——尤其是那些把它玩坏的人。开发中收到的最有用的一次报错，是"两页说明书悄悄覆盖了彼此"；能找到它，正是因为有人在认真看。
```

