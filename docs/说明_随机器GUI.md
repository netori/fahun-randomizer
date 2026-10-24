# 法魂随机器 GUI（法魂随机器.exe）

放在 `随机mod` 目录下双击即可（也可放任意子目录，程序会向上找存在 `investigation\randomization-dryrun` 的目录当工作区）。

## 一、怎么用

| 控件 | 说明 |
|---|---|
| **种子** | 决定本次随机结果。**同一种子 → 同一结果（逐字节一致）**，换种子 → 结果不同。点【骰子】随机取一个 |
| **候选基础** | `职业说明书`（默认，最权威）/ `推荐表` / `两者合并` |
| **域** | 卢恩 / 护甲 / 武器，可勾选参与哪些域 |
| **联合池** | 勾上则两个域 **合并成一个池**互随机（例：卢恩↔武器）。职业护甲池永不与别的池合并 |
| **套装整组不拆** | 勾上则同套装的 4 件必须同进同出 |
| **含商店行** | 是否把商店出售的物品也纳入池子 |
| **幽影卢恩并入普通池** | 默认不并；勾上则 DLC 幽影卢恩与本体卢恩同池 |
| 【生成计划】 | 演算并显示：校验结果 + 池统计 + 置换表（前 300 行） |
| 【导出 CSV】 | 写到 `investigation\apply\out\plan_seed<种子>.csv` |
| 【部署到 MOD】 | 走 `pipeline_deploy.py`：**备份 → 打补丁 → 逐个序列化 → 重打包 → 重解包校验 → 写入 MOD**；说明书按"物品不变·地点变"同步改写 |

## 二、可复现性（已验证）

- 同种子连续生成两次：置换表**逐字节相同**；
- 换种子：结果不同；
- 命令行自检：`法魂随机器.exe --selftest` → 打印 `SELFTEST PASS` 并把结果写到
  `investigation\apply\logs\gui_selftest.txt`。

## 三、部署与回滚

部署会写两个文件（各自先备份，MOD 内也有 `.bak_<时间戳>`）：

- `mod\regulation.bin`（物品置换）
- `mod\msg\zhocn\item_dlc02.msgbnd.dcx`（职业说明书文本）

回滚：把同名 `.bak_<时间戳>` 改回原名即可。investigation 侧备份在
`investigation\apply\backup`，回执在 `backup\deploy_<时间戳>.json`。

## 四、这套流水线的硬规矩（都是排查出来的）

1. **WitchyBND 必须经 ConPTY 调用**（直接跑会因无控制台而卡死）；`PauseOnError`/`GitBackup` 已关。
2. **重打包必须传"文件夹 + -r"**，且文件夹里的 `.param` 二进制才是数据源（XML 不生效）→ 所以**每个改过的 XML 都要单独序列化**。
3. **7 位 id 护甲的部位码取末 3 位**（000 头 / 100 身 / 200 臂 / 300 腿），否则 DLC 套装会整批漏掉。
4. **来源按 Lot 行统计**，同名行合并（忽略大小写）；**NPC/剧情行不算来源**；有剧情"给与/返还"的格子进 `fixed_cells.json`（永不随机）。
5. **说明书方向**：物品名不动，只把它那几行的地点换成"它现在真在的地方"；行数不够就整组不动（宁可不改也不写错）。

---

## v2：全自研管线（不再需要 WitchyBND）

从 v2 起，部署不再调用任何外部工具，全部由 exe 内部完成：

| 层 | 自研实现 |
|---|---|
| regulation 加密 | 16 字节 IV + AES-256-CBC（零 IV、PKCS7），密钥为公开格式事实 |
| DCX 压缩 | 大端头 + DCS/DCP/DCA 段；ZSTD 与 Oodle(KRAK) 两种都支持 |
| Oodle | 通过**游戏自带**的 `oo2core_6_win64.dll`（注意：rawSize 必须给精确值，多给会返回 0） |
| BND4 | 条目 0x24：flags + id + size(u64)×2 + 数据偏移(u32) + 序号(u32) + 名字偏移(u32) |
| PARAM | 行表条目 0x18：id + 数据偏移 + 名字偏移（文件内相对）；字段偏移取自 Paramdex：lotItemId +0x00、lotItemCategory +0x20、商店 equipType +0x17 |
| FMG（说明书） | 头 + 每组一张 u64 绝对偏移表 + 数据区；改文本 = 新串写文件末尾 + 只改该条表项（其它偏移不动） |

**部署顺序**（`native_deploy.py`，GUI 的【部署到 MOD】按钮与 `--deploy` 命令行都走它）：
1. 备份当前 `regulation.bin` 与 `item_dlc02.msgbnd.dcx` 到 `backup/deploy_<时间戳>/`
2. 把两者**复原成原始版**（每次都从干净状态出发，不会叠加）
3. 说明书：`fix_guide` 按该计划生成新的 GoodsCaption XML
4. regulation：把计划写进 params（逐格校验原值，不符即跳过并记录）
5. 说明书：把新 XML **全文**写进 msgbnd
6. 回读校验 + 收据（`logs/deploy_<时间戳>.json`）

**可复现性**：同一 `plan_<种子>.csv` 部署出的两个文件 sha256 恒定（实测多次部署逐字节一致）。

**校验手段**：除自研 reader 回读外，还让 WitchyBND（独立实现）解过自研产物 —— `Successfully parsed`、79 个文件、52/52 条新文本命中。

**新增选项**：随机密度（子集置换，池内守恒）、同步说明书开关、保存/载入配置（JSON）、一键回滚 MOD。

**回滚**：GUI 的【回滚 MOD】按钮，或手工把 `backup/regulation.bin.orig_*` 与
`backup/item_dlc02.msgbnd.dcx.zhocn.orig_*` 覆盖回 MOD。
