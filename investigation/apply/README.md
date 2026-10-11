# 真机写入（apply）— 操作说明 v2（已跑通）

> 目标：把干跑出来的置换表真正写进 MOD 的 `mod/regulation.bin`，供游戏内测试。
> 现状：**首测包已部署**（36 行 / 4 个池），完整包随时可出。
> 纪律：只在 `investigation/` 里做工具操作；写入 MOD 前自动双备份；每步留哈希与回执。

## 0. 备份（已做）

| 文件 | 原大小 | sha256（前 16） | 备份位置 |
|---|---|---|---|
| `MOD/mod/regulation.bin` | 2,984,544 B | `7bcd46b957ac49cf…` | `backup/regulation.bin.orig_20261011_080825` |
| （部署时另存）| | | `backup/regulation.bin.before_deploy_<ts>` + MOD 内 `mod/regulation.bin.bak_<ts>` |
| `MOD/version.txt` / `YAFSML.ini` | 7 B / 4,248 B | `d57819fefc715b1f…` / `182d3a305b0bb000…` | 同目录 `.orig_<ts>` |

## 1. 注入点（加载器日志实证）

```
[asset-hooks] file override: request=regulation:/regulation.bin
   expanded=<游戏>\Game\regulation.bin
   mod=<MOD>\mod\regulation.bin
prevent_regulation_save_write=1
```

YAFSML 是**运行时注入**，游戏本体不改；参数表装在 `MOD/mod/regulation.bin` 里，该文件是**混淆容器**（无 `PARAM`/`DCX` 明文、无表名字符串），必须用工具解包/重打包。

## 2. 工具与三个必须先解决的坑

工具：`tools/witchybnd-3.0.1.0/WitchyBND.exe`（原样未动）；实际用**副本** `apply/tools/witchybnd/`。

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | 命令行跑 `WitchyBND` **不烧 CPU 地卡死** | 配置 `PauseOnError: true`（出错等按键）+ `GitBackup: true` | 副本配置改 `PauseOnError=false`、`GitBackup=false`、`EndDelay=0` |
| 2 | 重打包报 `RegulationOutOfBoundsException` | 工具自带 Paramdex 只认到 **1.16.1.1000**，本 MOD 是 `11711000`（1.17.1.1000） | 副本改 `Assets/Paramdex/ER/Upgrader/version.txt` → **单行** `1_17_1_1000L`（**必须单行**，多行会 `FormatException`） |
| 3 | 打完补丁重打包，产物**没变化** | 目录重打包用的是现成的 `.param` 二进制，**不读 XML** | 先对改过的 XML 逐个单独跑一次（XML→`.param` 序列化），再重打包 |

另外：传**文件**＝解包/序列化，传**目录**＝重打包；必须给真实控制台（用第一轮留下的 ConPTY 承载器 `_conpty_run.py`，封装在 `apply/logs/run_witchy2.sh`）。

## 3. 管线（已跑通的六步）

```bash
APPLY=investigation/apply
# ① 解包（对 MOD 副本操作）
python _conpty_run.py --exe .../WitchyBND.exe --cwd $APPLY/work/x --raw-out $APPLY/logs/x.console.txt \
     --timeout 1800 --cols 220 --rows 60 -- $APPLY/work/x/regulation.bin
# ② 打补丁（改 XML 属性；写前校验"当前值==置换表原值"，不符即跳过并记冲突）
python $APPLY/apply_swaps.py --plan $APPLY/out/plan_pilot.csv --tree $APPLY/work/x/regulation-bin --dry-run   # 先预演
python $APPLY/apply_swaps.py --plan ... --tree ... --report $APPLY/logs/pilot_apply.json                      # 再真改
# ③ 把改过的 XML 序列化成二进制（关键！目录重打包不读 XML）
python _conpty_run.py ... -- $APPLY/work/x/regulation-bin/ItemLotParam_map.param.xml      # 每张改过的表跑一次
# ④ 重打包（目录 + 同级放一份 regulation.bin 作为目标）
cd $APPLY/work/x && python _conpty_run.py ... -r "regulation-bin"
# ⑤ 校验（产物再解包，逐文件比对）
python $APPLY/verify_tree.py --a $APPLY/work/x_unpacked/regulation-bin --b $APPLY/work/orig/regulation-bin --only param
# ⑥ 部署（自动双备份；不加 --yes 只预演）
python $APPLY/deploy.py --new $APPLY/work/x/regulation.bin --yes
```

回滚：

```bash
python $APPLY/deploy.py --rollback $APPLY/backup/regulation.bin.orig_20261011_080825 --yes
# 或直接把 MOD 里 mod/regulation.bin.bak_<ts> 改名回 regulation.bin
```

## 4. 已做的校验（可复算）

| 校验 | 方法 | 结果 |
|---|---|---|
| **往返保真** | 纯净树 → 重打包 → 再解包，逐文件比 `.param` | **194/194 字节一致** ⇒ 重打包无损 |
| 补丁只动该动的表 | 打补丁产物 vs 原始树 | 仅 `ItemLotParam_map`（67 字节）与 `ShopLineupParam`（3 字节）不同，其余 192 个 param 一致 |
| 产物内容正确 | 产物再解包 vs 打补丁后的树 | **194/194 一致** |
| 语义抽检 | 从产物里读回目标行的字段值 | 见 `logs/pilot_apply.json` / 抽检脚本输出 |

## 5. 首测（pilot，已部署）

- 置换表：`out/plan_pilot.csv`（**36 行 / 4 个池**）
- 核对清单：`out/首测核对清单.md`
- 部署时间/哈希：见 `backup/deploy_20261011_085253.json`（产物 sha256 `d6044af0d273e848…`）
- 怎么测：双击 `MOD/启动法魂.bat` 进游戏，按清单去对应位置看拿到的东西。

## 6. 风险与还原

| 风险 | 缓解 |
|---|---|
| 重打包产物损坏 | 已做往返保真（194/194 字节一致）；部署前双备份 |
| 写错值 | `apply_swaps.py` 写前校验原值；`--dry-run` 预演；产物回读抽检 |
| 想反悔 | `deploy.py --rollback`（秒级还原）；游戏本体从未被改 |
| 存档 | `prevent_regulation_save_write=1`，MOD 的 regulation 不会写进存档 |

## 7. 说明书（局内获取地区文本）跟着变 —— 已打通

随机化会改"哪个位置给哪件东西"，所以 `mod/msg/zhocn/item_dlc02.msgbnd.dcx` 里的 `GoodsCaption.fmg`
（说明书正文，条目 8800-8826 / 8870-8895）必须一起改，否则指南会指错地方。

**做法**（`update_guide.py`）：

1. 从 `PlaceName.fmg`（中/英两份，按条目 id 配对，1130 条）建地名对照；
2. MOD 的行名方括号里是「地点 - 敌人」混合（如 `[Limgrave Tunnels - Stonedigger Troll]`），
   所以**优先用说明书自己出现过的地名词汇**挑，取最具体的一段；
3. 说明书里物品 X 的行数 == X 的格数 → 把 X 的那几行地点**整组换成** `{地点(C) : NEW(C)==X}`；
4. `GoodsCaption.updated.fmg.xml` → `.fmg` → 放回解包目录 → 重打包 msgbnd → 部署。

**校验**：产物再解包 vs 原始 → 79 个文件里 **78 个字节一致**，只有 `GoodsCaption.fmg` 变（−82 B）；
逐项核验"说明书里写的物品地点 == 计划里它现在所在格子的地点" → **12/12 一致**。

**当前局限**：① 13 行（多为商店行 / 行名里没有方括号地点的）认不出地点 → 这些物品的指南行**保持原样**；
② 指南里的**套装行**（"XX套装 - 地点"）暂未改，等上完整包时按"集合级置换"处理；
③ 目前只改了 **zhocn**（其他语言未动）。

**备份**：`backup/item_dlc02.msgbnd.dcx.zhocn.orig_<ts>` + MOD 内 `item_dlc02.msgbnd.dcx.bak_<ts>`；
回滚就是把这个 .bak 改名回 `item_dlc02.msgbnd.dcx`。
