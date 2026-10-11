# N 网发布文案（复制粘贴用）

> 说明：N 网的 Description 支持 **BBCode**。下面两套（英文 / 中文）可以直接整段贴进 BBCode 编辑器。
> 需要在 N 网站点上另填的字段（Name / Summary / Permissions 等）在最后一节列出。
>
> ⚠️ **关于表格**：N 网的 BBCode 对 `[table]` 的支持时好时坏。如果贴上去表格散掉，
> 就把 `[table]…[/table]` 去掉、改成 `[list]` 或纯文本行（内容不用动）。

---

## 一、英文版（建议作为主描述）

```
[center][size=6][b]Convergence Class Item Randomizer[/b][/size]
[size=4]法魂职业道具和装备随机器[/size]

[i]Randomizes the class-guide items of The Convergence — items only, locations and quantities untouched.[/i][/center]

[size=5][b][color=orange]Language notice: Chinese only for now.[/color][/b][/size]

[b]This tool does not support the English version yet.[/b] It is built for the [b]Chinese localization[/b] of The Convergence (法魂 · 汉化本体):

[list]
[*]The [b]user interface is entirely in Chinese[/b] — there is no English build.
[*]The [b]guide-text rewriting[/b] (the part that makes the in-game class guides show the new locations) only works with the Chinese guide file.
[*]Install checks and "restore original" also expect the Chinese localization's file layout.
[/list]

In practice: on the [b]Chinese localized build[/b], everything below applies. On the English (or any other language) version of The Convergence this tool is [b]not usable yet[/b] — the item pool and file layout differ, so it is not a matter of translating a few strings.

A proper English build is possible later (the pipeline can rebuild the item catalog from another language), but it is not done. Better to say this up front than to have you install something that cannot run.

[line]

[line]

[size=5][b]What this does[/b][/size]

The Convergence locks you into a build: playing a Glintstone Sorcerer means the same gear and the same runes, the same route, every run. Other randomizers either ignore the mod or shuffle everything at once — chaos, but your build is dead.

This tool does something narrower and, we think, more useful:

[b]It swaps the items that appear in the in-game class guides (职业说明书), and nothing else.[/b]

You are still a Glintstone Sorcerer — but [b]this run, your key items are somewhere else[/b], and you have to find them again.

[line]

[size=5][b]Design principles[/b][/size]

[b]1. Items only — never locations.[/b] A chest stays a chest, a drop stays a drop. We only change [i]what[/i] is inside. Quantities, probabilities, prices, stock, unlock flags and event flow are never touched. [b]Merchants are excluded entirely[/b] (shops involve unlock/stock logic — the risk isn't worth the reward).

[b]2. The class guides are the source of truth.[/b] The randomization pool is exactly the set of items listed in the mod's own class guides. After randomizing, opening the guide shows you the [b]true[/b] state of the world.

[b]3. "Coherence" (合理度) is one slider, but its meaning is precise.[/b] It controls three independent things at once:

[list]
[*][b]Tier span[/b] — how far apart two items may be swapped
[*][b]Cross-tier rate[/b] — what fraction of items actually cross a tier boundary
[*][b]Weapon mix-in[/b] — how many weapons join the mixed pool (capped at 66%)
[/list]

[table]
[tr][th]Coherence[/th][th]Tier span[/th][th]Cross-tier rate[/th][th]Weapon mix-in[/th][/tr]
[tr][td]100%[/td][td]1 (same tier only)[/td][td]0%[/td][td]0%[/td][/tr]
[tr][td]67%[/td][td]2 tiers[/td][td]33%[/td][td]22%[/td][/tr]
[tr][td]33%[/td][td]3 tiers[/td][td]67%[/td][td]44%[/td][/tr]
[tr][td]0%[/td][td]4 tiers (free)[/td][td]100%[/td][td]66%[/td][/tr]
[/table]

Tiers follow the game's own sense of progression:

[table]
[tr][th]Tier[/th][th]Runes[/th][th]Armor[/th][th]Weapons[/th][/tr]
[tr][td]0[/td][td]Apprentice[/td][td]Gauntlets[/td][td]Limgrave / Weeping Peninsula / Stormveil…[/td][/tr]
[tr][td]1[/td][td]Adept[/td][td]Greaves[/td][td]Liurnia / Raya Lucaria / Caelid…[/td][/tr]
[tr][td]2[/td][td]Expert[/td][td]Chest armor[/td][td]Altus Plateau / Leyndell / Mountaintops…[/td][/tr]
[tr][td]3[/td][td]Master / Shadow[/td][td]Helmets[/td][td]Haligtree / Farum Azula / Deeproot / Shadow Realm…[/td][/tr]
[/table]

Armor and runes are both naturally four-tiered, so in the mixed pool they line up [b]one-to-one[/b] (gauntlets ↔ apprentice, helmets ↔ master) with no conversion at all.

[b]The rule in one sentence: every swap must happen inside the same tier bucket.[/b]

[b]4. Caster armor never mixes with melee armor.[/b] Mage/incantation armor stays in its own pool, always.

[b]5. If it can't be written safely, it isn't written.[/b] Every write is backed up first (one button restores the original), and every write is audited afterwards.

[line]

[size=5][b]Guide text stays honest[/b][/size]

After randomizing, the class guides are rewritten so that [b]item names never change — only their listed locations do[/b]:

[quote]X moved into the cell that used to hold Y  ⇒  X's listed location becomes Y's original listed location[/quote]

No translation, no guessing: we read the location straight out of the original guide text. The rewrite is audited on every write (8 checks: font tags preserved, length within the original text box, item names unchanged, no empty locations, no cross-page overwrite, line counts, on-disk verification, idempotency).

[line]

[size=5][b]Requirements[/b][/size]

[list]
[*][b]ELDEN RING[/b] — the version required by your Convergence install (built and tested against 1.17.1)
[*][b]The Convergence (法魂)[/b] mod, V3.0.3 — Chinese localization, YAFSML injector build
[*]Your own [b]original[/b] `regulation.bin` and guide msg file (the tool backs them up on first write)
[/list]

[line]

[size=5][b]Installation[/b][/size]

[list=1]
[*]Put `ConvergenceClassItemRandomizer.exe` in the [b]mod's root folder[/b] (the folder that contains `mod\regulation.bin`).
[*]Run it. The [b]Local Files[/b] panel checks everything it needs: mod folder, game data, guide file, original backups, guide baseline, engine. Anything missing is shown in red and [b]Write to game[/b] is disabled until it's fixed.
[*]Pick categories (runes / armor / weapons) → pick a mixing mode → set coherence → set a seed.
[*]Click [b]① Generate plan[/b], read the summary, then [b]② Write to game[/b].
[/list]

Not happy with it? Click [b]Restore original[/b]. Same seed = exactly the same result, so you can share a seed with a friend.

[line]

[size=5][b]How it was tested[/b][/size]

[list]
[*][b]Matrix test[/b] — 15 configurations × 6 seeds = 90 runs (engine checks, conservation, reproducibility, caster isolation, compression-frame check)
[*][b]Real game launches[/b] — every configuration actually started the game and reached the main menu (14/14)
[*][b]Guide audit[/b] — 0 issues on the released build
[*][b]Audit self-test[/b] — 5 deliberately injected failures, all caught, no false positives
[/list]

Two bugs found this way are worth mentioning, because they shaped the release:

[list]
[*]The first version produced a [b]byte-correct regulation.bin that crashed the game on startup[/b] — everything validated, yet it wouldn't load. Cause: re-compression parameters. The game's decoder only accepts its own frame layout; we now match it, and the matrix test fails loudly if that ever regresses.
[*]Guide text that grew longer than the original got [b]silently truncated by the game's fixed-size text box[/b] — which looked like "melee classes are missing their weapons, casters missing their runes" (those entries sit at the end of each entry). Text is now fitted to a safe length.
[/list]

[line]

[size=5][b]Credits[/b][/size]

[list]
[*][b]The Convergence[/b] (法魂) — the mod itself and its class guides. Without that guide, this tool would have nothing to work from.
[*][b]YAFSML[/b] — the runtime-injection loader. Because it never touches the game folder, we can safely randomize data files only.
[*][b]SoulsFormats[/b] — the `regulation.bin` AES scheme was read out of its `RegulationDecryptor`. Public documentation for this format is scarce; without it we'd still be guessing IVs.
[*][b]WitchyBND[/b] — used during development for cross-validation (the same file parsed by both tools) to make sure our own reader wasn't drifting.
[*][b]Oodle[/b] (RAD Game Tools) — the compression algorithm ships with the game; we only call it.
[*][b]The wider randomizer community[/b] (Elden Ring Randomizer / Item Randomiser and friends) — for showing what the ceiling on randomization freedom looks like.
[*][b]FromSoftware and Bandai Namco[/b] — ELDEN RING.
[/list]

[line]

[size=5][b]Notes / permissions[/b][/size]

[list]
[*]This tool [b]only modifies data files[/b] (item distribution and guide text). It does [b]not[/b] modify the game itself and does [b]not[/b] bypass anti-cheat or online checks.
[*]No game or mod files are redistributed here — the download contains this tool only. You must own the game and the mod, and you must have your own original files.
[*]Single-player use only. Back up your save.
[*]The exe is unsigned, so some antivirus suites may raise a first-run warning.
[*]The UI is Chinese (this is built for the Chinese localization of The Convergence); the tool logic is language-agnostic.
[*]Credits and permissions: you're welcome to reuse the code with attribution. All names and content belong to their respective owners.
[/list]
```

---

## 二、中文版（备用 / 贴在同页或用中文社区）

```
[center][size=6][b]法魂职业道具和装备随机器[/b][/size]
[size=4]Convergence Class Item Randomizer[/size]

[i]只换物品、不搬位置 —— 让法魂的每一周目都得重新找东西。[/i][/center]

[b][color=orange]语言说明：目前仅支持中文版（法魂汉化本体）。[/color][/b]

[b]本工具暂不支持英文版。[/b] 界面、说明书写地点、文件自检与「还原成原始」都是按[b]法魂汉化本体[/b]做的：

[list]
[*]界面[b]全中文[/b]，没有英文版；
[*]说明书改地点只认中文说明书文件；
[*]英文（或其它语言）版的 The Convergence 物品池与文件结构都不一样，[b]不是翻译几个字就能用[/b]。
[/list]

以后可以做英文版（管线本身支持从别的语言重建物品目录），但现在没有。先把话说明白，总比让人装上一个跑不起来的东西好。

[line]

[line]

[size=5][b]这个工具解决什么[/b][/size]

法魂这类大改 MOD，职业流派基本是钉死的：玩辉石法师就那几件装备、就那几个卢恩，开局路线几乎固定。
市面上的随机器要么只管原版、要么"一键全乱"——东西是乱了，但流派也废了。

我们做的更窄一点，也更实用一点：

[b]只把游戏内「职业说明书」里出现的道具互相对调，别的都不动。[/b]

你还是辉石法师，只是[b]这一周目的关键道具换到别的地方去了[/b]，你得重新去找。

[line]

[size=5][b]设计理念[/b][/size]

[b]1. 只换物品，不搬位置。[/b] 宝箱还是那个宝箱、掉落还是那个掉落，我们只改"里面放什么"。数量、概率、价格、库存、解锁条件、事件流程一律不动。[b]商店完全不参与[/b]（商店牵扯解锁与库存，风险不成比例）。

[b]2. 以职业说明书为准。[/b] 随机范围严格等于说明书里出现过的物品。换完之后翻开说明书，看到的就是这座世界的真实分布。

[b]3. 合理度是一个旋钮，但含义必须精确。[/b] 它同时控制三件互相独立的事：

[list]
[*][b]越档幅度[/b] —— 最远能跨几档
[*][b]越档率[/b] —— 多少东西真的跨档
[*][b]武器掺入混池的比例[/b] —— 上限 66%
[/list]

[table]
[tr][th]合理度[/th][th]越档幅度[/th][th]越档率[/th][th]武器掺入[/th][/tr]
[tr][td]100%[/td][td]1 档（只能同档）[/td][td]0%[/td][td]0%[/td][/tr]
[tr][td]67%[/td][td]2 档[/td][td]33%[/td][td]22%[/td][/tr]
[tr][td]33%[/td][td]3 档[/td][td]67%[/td][td]44%[/td][/tr]
[tr][td]0%[/td][td]4 档（完全放开）[/td][td]100%[/td][td]66%[/td][/tr]
[/table]

[b]4. 法师/祷告护甲永不与近战混池。[/b]

[b]5. 写不进去的东西等于没写。[/b] 每次写入前自动备份（界面一个按钮还原），写入后自动审计。

[line]

[size=5][b]说明书会跟着改[/b][/size]

[b]物品名不动，只换它现在所在的地点：[/b]

[quote]X 搬进了原本放 Y 的格子 ⇒ X 的地点写成 Y 在原版说明书里的地点[/quote]

零翻译、零猜测。每次写入都会自动审计 8 项（字体标签、长度、物品名、空地点、串页、行数、落盘核对、幂等）。

[line]

[size=5][b]安装[/b][/size]

[list=1]
[*]把 `ConvergenceClassItemRandomizer.exe` 放到[b] MOD 根目录[/b]（有 `mod\regulation.bin` 的那一层），双击打开。
[*]界面里的「本地文件」会逐项自检，缺项会标红并禁用「写入游戏」。
[*]选随机项目 → 选混合方式 → 拉合理度 → 填种子。
[*]点 ① 生成随机方案 → 看「这次会改什么」→ 点 ② 写入游戏。不满意点「还原成原始」。
[/list]

[line]

[size=5][b]致谢[/b][/size]

[list]
[*][b]The Convergence（法魂）[/b] —— MOD 本体与那套职业说明书。
[*][b]YAFSML[/b] —— 运行时注入式加载器，正因为它不动游戏本体，我们才敢只改数据文件。
[*][b]SoulsFormats[/b] —— `regulation.bin` 的 AES 方案从它的 `RegulationDecryptor` 读出。
[*][b]WitchyBND[/b] —— 开发期做交叉验证用。
[*][b]Oodle[/b]（RAD Game Tools）—— 压缩由游戏自带 DLL 提供。
[*][b]社区随机器[/b] —— "自由度的上限该长什么样"是从它们那学的。
[*][b]FromSoftware / 万代南梦宫[/b] —— ELDEN RING。
[/list]

[line]

[size=5][b]注意[/b][/size]

[list]
[*]只改数据文件，不改游戏本体，不绕过任何反作弊/联网校验。
[*]不包含任何游戏或 MOD 文件；下载里只有本工具，需要你自备原版文件。
[*]仅限单人游戏，请先备份存档。
[*]exe 未签名，部分杀软首次运行会提示。
[/list]
```

---

## 三、N 网站点上要单独填的字段

| 字段 | 建议填写 |
|---|---|
| **Name** | `Convergence Class Item Randomizer (法魂职业道具和装备随机器)` |
| **Summary**（短，一行） | `Randomizes The Convergence's class-guide items — items only, locations untouched. Coherence controls tier span, cross-tier rate and weapon mix-in. The guides are rewritten to show where things really are.` |
| **Category** | `Gameplay` → `Game Mechanics`（或 `Items`） |
| **Version** | `1.0.0` |
| **Requirements** | ELDEN RING（1.17.1）· The Convergence 法魂 V3.0.3（汉化本体 / YAFSML 注入式） |
| **Permissions** | 见下方建议 ✓ |
| **Files** | 上传 `ConvergenceClassItemRandomizer_v1.0.0.exe` ✓ |
| **Credits / 必要的致谢** | 直接粘贴上面 Credits / 致谢 那一段 ✓（N 网有独立的 Credits 区块，建议贴那里 + 描述里也留一份 ✓） |

### Permissions 建议

| 项 | 建议 | 理由 |
|---|---|---|
| 其他人可否**再分发**这个工具 | **允许，需注明出处** ✓ | 工具本身是我们写的，允许传播对社区更好 ✓ |
| 其他人可否**在这个工具基础上改** | **允许，需注明出处** ✓（若你希望严格一些，可改为"需先联系"） | — |
| 其他人可否**把本工具打包进整合包** | **允许** ✓ | 整合包里通常没法自动随 —— 带上它反而方便 ✓ |
| 是否**使用了其他人的资源** | **是** ✓ —— 列出 The Convergence / YAFSML / SoulsFormats / WitchyBND / Oodle | N 网会追问这一点；我们**没有再分发**任何资源 ✓，只是读取玩家自己的文件 ✓ |

---

## 四、发布前建议顺手做的三件事

1. **贴截图**：主界面（含「本地文件」那块全绿 ✓）、合理度 100% 与 0% 的对照、说明书页面对照（改前/改后）。N 网没截图会掉很多信任 ✓。
2. **写清"只改目录里那两个文件"** ✓：`mod\regulation.bin` 与 `mod\msg\zhocn\item_dlc02.msgbnd.dcx` —— 让玩家知道范围、也方便他们自己备份 ✓。
3. **附一段 30 秒上手** ✓：`放 MOD 目录 → 双击 → 100% 试一次 → 不满意点还原` ✓。
