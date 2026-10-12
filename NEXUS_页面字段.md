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

[b]1. Items only — never locations.[/b] A chest stays a chest, a drop stays a drop. Only what is inside changes. Quantities, probabilities, prices, stock, unlock flags and event flow are never touched. Merchants are excluded entirely, because shops involve unlock and stock logic and the risk is not worth the reward.

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
[*][b]Items only, never locations.[/b] Quantities, probabilities, prices, stock, unlock flags and event conditions are left exactly as they were. Merchants never take part.
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
