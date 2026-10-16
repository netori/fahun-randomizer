# MSB 定点字段写入器 —— 走通报告（二期「真·换敌人」核心件）

* 作者：实现型子 agent
* 日期：2026-10-16
* 产物：`investigation/apply/msb_write.py`（新文件，未改 `msb_read.py` / `erio.py` / `enemy_randomizer.py`）
* 证据目录：`investigation/msb_write_probe/`
* **本票没有写任何游戏 / mod 目录里的文件**（mod 目录全程只读；写验证全部落在本目录）

---

## 0. 一句话结论

**能写了，而且证据很强**：634 张地图全部做到 `读 → patch(空 edits) → 重封装 → 再读` 后**明文逐字节相同**；
用 WitchyBND（SoulsFormatsNEXT）这一**独立解析器**交叉验证，一条真实换敌人操作在 11,606 个解包文件里
只让 **3 个文件**的字节变了（2 处是预期的 npc_id、1 处是解包器自己写的文件名）。
但**这一票不建议直接写回 mod 目录** —— 还缺"游戏内实跑"这一层，见 §7。

---

## 1. 结构定位方式（哪一段字节能改，为什么）

### 1.1 MSB 明文（沿用一期已有实证，未改）

| 位置 | 事实 |
|---|---|
| 文件头 | `MSB ` + `i32 1` + `i32 0x10`，标志字节 `00 00 01 FF`（0x0E=1 / 0x0F=0xFF） |
| param 链 | 6 个块，`[i32 version][i32 offsetCount][i64 nameOffset][i64 offs[offsetCount-1]][i64 nextParamOffset]` |
| param 名 | **UTF-16LE**，不是 ASCII |
| 条目内字段 | 全部**相对条目起点** |

敌方可改字段（都在一条**已有**的 Enemy part 里，全部 i32，等长就地改写）：

| 字段 | 位置 | 说明 |
|---|---|---|
| `ThinkParamID` | typeData `+0x08` | NpcThinkParam 行 id |
| `NPCParamID` | typeData `+0x0C` | **拿去 NpcParam 对账的就是它** |
| `TalkID` | typeData `+0x10` | |
| `CharaInitID` | typeData `+0x18` | |
| `ModelIndex` | 基记录 `+0x14` | 改模型 |

`entityDataOffset`(基记录 `+0x60`) / `typeDataOffset`(`+0x68`) 都是**相对条目起点**的既有值；
`EntityID` 在 entityData `+0x00`，`EntityGroupIDs` 在 `+0x1C`（8×u32）。

### 1.2 DCX 封装（本次新查清的部分）

对 634 张 `mod/map/MapStudio/*.msb.dcx` 全量实测：

```
+0x00 "DCX\0"
+0x04 u32BE unk04      DFLT=0x00010000(529/529)  KRAK=0x00011000(105/105)
+0x08 u32BE dcsOff = 24
+0x0C u32BE dcpOff = 36
+0x10 u32BE dcaOff = 68
+0x14 u32BE dataOff = 76          <- 634/634 全部 76，无一例外
+0x18 "DCS\0" | +0x1C u32BE unc | +0x20 u32BE comp
+0x24 "DCP\0" | +0x28 kind("DFLT"/"KRAK") | +0x2C u32BE 0x20
+0x30 u8 level  DFLT=9 / KRAK=6 | 15×00 | 00 01 01 00
+0x44 "DCA\0" | +0x48 u32BE 8
+0x4C payload
```

**决定性观察**：同一 kind 内，76 字节前缀**除 DCS 的两个大小字段外逐字节相同**
（529 张 DFLT 只出现 527 种前缀、105 张 KRAK 只出现 99 种 —— 差的就是 unc/comp 数值本身）。

于是封装策略是：**克隆原文件那 76 字节，只覆盖 kind / level / unk04 / 两个大小字段**。

### 1.3 顺手纠正任务书里的一处口误

任务书写「`erio.dcx_compress(payload, template, level)` 写 DFLT/zlib ✓」。**实测不是**：

* `erio.dcx_compress` 写的是 **ZSTD**（它拼的是 `DCP\0 + "ZSTD\0\0\0\0"`），且它是给 regulation 那条线用的口径。
* `erio.dcx_decompress` **只认 ZSTD / DEFLATE**，遇到 `DFLT` 会直接 `ValueError: 未知 DCX 压缩类型 DFLT`。

所以 `msb_write.py` 自带两条封装路（`_dflt_compress` 用 zlib、`_krak_compress` 走 `oodle.py`），
**解压一律走 `msb_read.dcx_payload`**（它 DFLT / ZSTD / KRAK 三条路都认）。

---

## 2. 验收 A —— 全量往返（634 张，最重要）

口径：对每一张图做 `读 → patch(空 edits) → 重封装 → 再读`，比对**每一条 part 的全部字段**。

判据（四条全过才算过）：

1. `plain_same` —— 重封装后再解出的明文与原明文**逐字节相同**（比逐字段更强：它覆盖了全部 6 个 param 块、所有模型名、事件、区域、路由、图层）
2. `fields_same` —— **全类型** part 逐字段指纹完全一致（基记录 0xC0 原始字节 SHA256 + entityData 0x3C SHA256 + 敌人 typeData 0x20 SHA256 + 坐标/旋转/缩放/名字/类型/id/ModelIndex/EntityID/8 个 GroupID）
3. `parts_before == parts_after`
4. `read_msb_enemies_same` —— 调 `msb_read.read_msb` 重新解析出来的结果与原文件一致

| 模式 | 结果 |
|---|---|
| **`out_kind="dflt"`（默认）** | **634 / 634 通过**（失败 0） |
| `out_kind="same"` | **634 / 634 通过**（失败 0，**无一条降级**） |

输入 kind 分布：`{DFLT: 529, KRAK: 105}`。

语料规模（同一次全量扫描）：

* part 条目总数（全类型） **728,264**
* 敌人 part 总数（PartType=2） **27,780**
* 明文总量 **1028.0 MB**（最大单图 23.69 MB，`m13_00_00_00`）

日志：`_accept_full.log`（每 50 张一行进度，逐张列出 parts 数 / plain_same / fields_same / read_msb）。

---

## 3. 验收 B —— 真换一个敌人

图：`m10_00_00_00.msb.dcx`（283 个敌人 part，9,015 条 part）

| | part 名 | EntityID | npc_id 原 | npc_id 新 |
|---|---|---|---|---|
| A | `c0000_9026` | 10000715 | 523250114 | **523250214** |
| B | `c0000_9027` | 10000740 | 523250214 | **523250114** |

两个 id 都确认为 `enemy_randomizer.load_units()` 里的**真行**（该 NpcParam 共 7,799 行），
两个 part 都确认 `PartType == 2`（Enemy）。

实测结果：

* 互换生效：**True**（读回后 A 的 npc_id = 523250214、B 的 = 523250114）
* 逐字段**只**变了 `npc_id` 的 part：**2 个**；其它字段变动：**0**
* part 数 **9015 → 9015**（结构零增删）
* 明文逐字节差异：**4 个字节**，范围 `[984156, 985117]`，预期窗口 `[984156, 985119]`
  —— 正好落在两个 npc_id 字段内（523250114 与 523250214 只在其中 2 个字节上取值不同，4 字节窗口里命中 4 个）
* 产物：`msb_write_probe/m10_00_00_00_patched.msb.dcx`，480,978 B（**没有覆盖原图**）

---

## 4. 独立解析器交叉验证（不是自己验自己）

`tools/witchybnd-3.0.1.0/WitchyBND.exe`（SoulsFormatsNEXT 派）分别解包**原图**与**我方的 patched 产物**
（原图先复制进 `_wx_test/`，**没有在 mod 目录里跑解包器**）：

| 指标 | 实测 |
|---|---|
| 两边解出的文件数 | 11,606 / 11,606 |
| 只在原图有的文件 | **0** |
| 只在 patched 有的文件 | **0** |
| **字节不同的文件** | **3 / 11,606** |
| 这 3 个 XML 的节点比对 | 11,895 节点，**不同 3 个** |

3 个差异逐条：

| 文件 | 节点 | 原 | patched |
|---|---|---|---|
| `Part/Enemy/c0000_9026.xml` | `Enemy/NPCParamID` | 523250114 | **523250214** |
| `Part/Enemy/c0000_9027.xml` | `Enemy/NPCParamID` | 523250214 | **523250114** |
| `_witchy-msbe.xml` | `msbe/filename` | `m10_00_00_00_orig.msb.dcx` | `m10_00_00_00_patched.msb.dcx` |

第三项是解包器把**输入文件自己的名字**写进了索引，不是 MSB 内容。

也就是说：**除了我想改的那两处，SoulsFormatsNEXT 眼里这个 MSB 一个字都没变** —— 9,015 个 part、
所有模型、事件、区域、路由、图层全部一致。

* 脚本：`_xcheck_tree.py`（整树）、`_xcheck_witchybnd.py`（索引 XML）
* 留存证据：`_wx_test/_keep/`（两个 part 的 orig/patched XML 各一对 + 索引各一份）
* 大解包目录（158 MB）已删；复现方法见 §9

---

## 5. 封装方式的选择与理由

### 默认 `out_kind="dflt"`

理由是**依赖最少 + 与法魂自身的文件形态同类**：

* 法魂 634 张图里 **529 张本来就是 DFLT**，ER 原生支持；DFLT 就是**裸 zlib 流**
* 纯 Python `zlib` 就能写，**不依赖任何外部 DLL / 工具**
* 我方产物 payload 头是 `78 da`，与原始 DFLT 的 `78 da` **完全一致**（同窗口 32K、同级最大压缩标志）
* DCX 前缀是**克隆原文件**再改 3 个字段 —— 结构上与原文件同构

**前缀不变量实测**（`_stats_prefix.log`，634 张 × 两种模式）：

| 模式 | 输入 → 输出 | 76 字节前缀里不同的偏移 |
|---|---|---|
| `dflt` | DFLT → DFLT（529） | **只有 `0x20..0x24`（comp 大小）**；其中 1 张连大小都相同 → 整文件逐字节相同 |
| `dflt` | KRAK → DFLT（105） | `0x04..0x08`（unk04）+ `0x28..0x2C`（kind）+ `0x30`（level）+ comp —— **恰好就是"把它变成一张标准 DFLT 头"该动的那几处** |
| `same` | KRAK → KRAK（105） | **只有 comp 大小**；其中 **25 张连 comp 都同长**（前缀逐字节相同） |

> 顺带一条如实记录：**没能字节级复现 ER 自己产出的 zlib 流**。试了
> level ∈ {1,6,9} × memLevel ∈ {9,12,15} × windowBits ∈ {9,12,15} × 策略 ∈ {DEFAULT, FILTERED}，全不中。
> 唯一"整文件逐字节相同"的是 `m60_35_40_00.msb.dcx`（**384 B**，一张近乎空的图，属退化情形，不算证据）。
> 这不影响正确性（内容是逐字节相同的），只是说明 ER 的 DFLT 不是用标准 zlib 的默认参数压的。

### `out_kind="same"`（尽量保持原 kind）

* DFLT → DFLT（同上）
* KRAK → KRAK：用游戏自带的 `oo2core_6_win64.dll`，`OodleLZ_Compress(compressor=8 Kraken, level=6)`
  —— **105/105 全部成功**，`oodle.decompress` 解回来与明文一致
* 做不到时**不静默**：降级为 DFLT 并把原因写进返回的 `degraded` 列表
  （已实测的降级路径：`out_kind="same"` + 人为给 `in_kind="ZSTD"` → 如实降级为 DFLT 并给出原因字符串）

> ⚠ Oodle 压缩依赖本机找得到的 `oo2core*.dll`。`oodle.py` 的搜索路径包含游戏安装目录，
> 本机命中 `...\ELDEN RING Tarnished Edition v1.17\Game\oo2core_6_win64.dll`。
> 这是**游戏本体目录**，不是其它 mod 目录；而且 `msb_read.dcx_payload` 要解 105 张 KRAK 图本来就必须用它。

---

## 6. 磁盘体量影响

`patch(空 edits)` 后重封装的字节数（`_stats_size.log`）：

| kind | 图数 | 明文总量 | 原 DCX 总量 | 我方 DFLT 总量 | 变化 |
|---|---:|---:|---:|---:|---:|
| DFLT | 529 | 911.9 MB | 36.7 MB | 34.5 MB | **−6.0%** |
| KRAK | 105 | 116.1 MB | 2.9 MB | 4.2 MB | **+45.4%** |
| **合计** | **634** | 1028.0 MB | 39.6 MB | 38.7 MB | **−2.2%** |

即：**整体不涨反降**，代价只在 105 张 KRAK 图上（合计 +1.3 MB）。
这 634 张在 mod 目录里是**裸文件**（`MapStudio/` 下没有 BND 归档），所以单文件变大 = 磁盘占用变大，没有二级后果。

---

## 7. 能不能安全地写回 mod 目录？

**我的判断：技术上已经具备"写"的全部结构条件，但这一票的证据链还差"游戏内实跑"一环；
建议先只写 1 张图做游戏内验证，通过了再放开全量。**

### 已经具备的（都有实测数字）

1. **结构零漂移**：634/634 明文逐字节相同 —— 这是一个比"逐字段相同"更强的判据
2. **独立实现认可**：WitchyBND/SoulsFormatsNEXT 把原图与产物各自展开成 11,606 个文件，只有 3 个字节不同，且三处都可解释
3. **字节级最小改动**：一次真实换敌人只动了明文里 **4 个字节**
4. **封装头与原文件同构**：前缀只动必须动的那几个字段
5. **体量不涨**：整体 −2.2%
6. **文件集合不变**：不新增/不删除/不改名 → `mod/map/MapStudio/` 的 634 个文件一一对应，
   `mod/map/worldmsblist*.worldloadlistlist.dcx` 之类的清单**不需要同步更新**

### 还缺的（缺了这些我不敢说"可以直接写"）

1. **游戏内实跑（最关键）**。上面所有结论都停在**解析器层面**。ER 1.17.1 到底收不收这两个字节，
   只有真进游戏才算数。最小验证：备份 → 只写 `m10_00_00_00.msb.dcx` → 进游戏 → 走到那张图 → 退出看崩不崩。
2. **KRAK 保持模式的 Oodle 产物**只在 Oodle 自己的解压器上闭环过，没有第三方或游戏侧验证。
   保守起见，**第一期写回建议一律用 DFLT**：DFLT 在法魂自己 529 张上就是原生形态，且整体体量还降。
3. **备份 / 回滚链路还没接**。仓库里 `native_apply.py` 的既有约定是
   `shutil.copy2(source, source + f".bak_{TS}")` + 在 `investigation/apply/backup/` 落一份 JSON 记录。
   本期**故意没实现**"自动写 mod 目录"的函数，避免被误调；接口设计见 §8。
4. **寻址方式要先定下来**（见 §8.2）—— 不是安全问题，但会决定二期怎么写。

---

## 8. 接口（`investigation/apply/msb_write.py`）

### 8.1 函数

```python
patch(path_or_bytes, edits, out_kind="dflt", template=None,
      allow_multi=False, strict=False, level=None) -> bytes          # 主入口
patch_ex(...) -> (bytes, report)                                     # 带诊断报告
read_back(data, tmp_dir=None)                                        # 落临时文件 → 调 msb_read.read_msb
verify_roundtrip(path, out_kind="dflt")                              # 单图四项判据
dcx_unpack / dcx_repack / enemy_parts / iter_parts / part_fingerprint
accept_a(...) / accept_b(...) / main()                               # 验收 A / B
```

`edits` 形如 `{key: {"npc_id": …, "think_id": …, "talk_id": …, "chara_id": …, "model": …}}`，
**只改给了的字段**。字段名容忍常见别名（`npc` / `NPCParamID` / `chara_init_id` …）。

**不抛异常的那一类**：找不到目标、EntityID 有歧义、字段名不认识 —— 一律写进报告的 `issues[]`
（`enemy-part-not-found` / `ambiguous-key` / `unknown-field` / `field-out-of-range`），
`allow_multi=False` 时**歧义直接不改**，`strict=True` 才升级成异常。
返回值里同时给出 `plain_sha256_before/after`、`applied[]`（每条改了什么、旧值→新值、在哪个偏移）。

`("idx", N)` 键实测：

```
patch_ex(d, {("idx", 346): {"chara_id": 999999, "model": 309}})
  -> applied=[('entry-index', {'chara_id': [23252, 999999], 'model': [309, 309]})]  issues=[]
  -> read_back 里 chara_id=999999 的敌人: c0000_9028 / entity_id=10000716
patch_ex(d, {("idx", 999999): {"npc_id": 1}})
  -> issues=[{'code': 'enemy-part-not-found', ...}]        # 未命中如实报，不静默
```

### 8.2 ⚠ EntityID 不是可靠主键（这条要带回给二期）

27,780 个敌人 part 的实测可达性（`_stats_addressing.log` / `_addressing.json`）：

| 寻址方式 | 可覆盖 | 占比 |
|---|---:|---:|
| EntityID（`id>0` 且本图唯一） | 8,309 | **29.9%** |
| part 名（本图唯一） | 27,712 | **99.8%** |
| 条目序号 `("idx", N)` | 27,780 | **100%**（永远可用） |

* **447 / 634 张图**存在"多个敌人 part 共用同一 EntityID"
* 14 / 634 张图的 part 名有重复

所以任务书里 `{entity_id: {...}}` 这个接口**能用，但只能覆盖三成敌人**。
本模块额外收 `str`（part 名）与 `("idx", N)`（`PARTS_PARAM_ST` 条目序号）两种键，
并提供 `enemy_parts(raw)` 让调用方**先枚举、再寻址**。
二期做"真·换敌人"时，建议用 `(map, 条目序号)` 或 `(map, part 名)` 当稳定标识，EntityID 只当辅助对账。

### 8.3 建议的写回流程（本期未实现，留给二期）

```
1. 对每张要改的图：patch_ex(原字节, edits, out_kind="dflt")
2. strict=True 跑一遍，issues 非空就停（不许带病写）
3. 备份源文件 → mod/map/MapStudio/<name>.msb.dcx.bak_<TS>
4. 原子替换（写 .tmp → os.replace）
5. 回读校验：dcx_unpack(落盘字节) 的明文 SHA256 必须等于第 1 步的 plain_sha256_after
6. 在 investigation/apply/backup/ 落一份 JSON（时间、目标、改前/改后 SHA256、逐条 edits）
```

---

## 9. 复现方法

```bash
cd "F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod"

# 验收 A + A2 + B（全量，约 10 分钟，产物落 msb_write_probe/_accept_full.log）
python -u investigation/apply/msb_write.py

# 只跑验收 B（单图，约 20 秒）
python -c "import sys;sys.path.insert(0,'investigation/apply');import msb_write;msb_write.accept_b()"

# 体量 / 寻址 / 前缀不变量统计
python -u investigation/msb_write_probe/_stats_size.py
python -u investigation/msb_write_probe/_stats_addressing.py
python -u investigation/msb_write_probe/_stats_prefix.py
```

独立解析器交叉验证（**注意先复制再解包，别在 mod 目录里跑**）：

```bash
cd investigation/msb_write_probe/_wx_test
cp "<mod>/mod/map/MapStudio/m10_00_00_00.msb.dcx" ./m10_00_00_00_orig.msb.dcx
# 对 orig 与 m10_00_00_00_patched.msb.dcx 各跑一次 WitchyBND：
powershell -NoProfile -Command "\$p=Start-Process -FilePath '<repo>\tools\witchybnd-3.0.1.0\WitchyBND.exe' -ArgumentList '\"<绝对路径>.msb.dcx\"' -WorkingDirectory '<repo>\tools\witchybnd-3.0.1.0' -PassThru -Wait"
python -u ../_xcheck_tree.py      # 整树比对（会重新生成 158 MB 解包目录，跑完记得删）
```

> WitchyBND 的 CLI **必须给它一个真控制台**：直接重定向 stdout 会被
> `PromptPlus requires a terminal/console without redirection environment!` 挡下。
> 上面的 `Start-Process`（不重定向）是实测可用的走法。

---

## 10. 未走通 / 如实记录

| 事项 | 状态 |
|---|---|
| 字节级复现 ER 自己的 DFLT zlib 流 | **未走通**。36 组参数组合全不中；只有 384 B 的空图凑巧相同。不影响正确性（内容逐字节相同），仅记录 |
| WitchyBND 命令行直接调用 | **未走通**（PromptPlus 要求真终端）。改用 `Start-Process` 起独立控制台后可用 |
| 游戏内实跑 | **本票未做**（也做不了：不进游戏）。这是 §7 里唯一还缺的一环 |
| 写回 mod 目录 | **本票按纪律未做**：mod 目录全程只读，一个字节都没写（`MapStudio/` 634 个文件，mtime 全为 10-10，今天被改动的文件数 = **0**） |
| 结构级改动（增/删/移条目） | **不在本方案内**。本写入器只做等长就地改写；需要增删条目时 MSB 的偏移链要整体重算，那是另一件工作 |

### 开发过程中真踩到并修掉的一个 bug（留痕）

`("idx", N)` 分支里把局部变量 `n` 复用了 —— 而 `n` 在函数开头已经被赋成**明文总长度**
（`n = len(buf)`），于是后面的边界检查 `a + 4 > n` 变成拿"条目序号"去比，任何字段都判越界。
症状是 `field-out-of-range: chara_id @0xf0be8 越界`（而明文有 13 MB）。
已被**故意设计成不抛异常**的那条路掩盖成一条 issue，靠单独测这个键型才暴露出来。
已改名为 `want_idx` 并复测通过。
**注**：`accept_a` / `accept_b` 走的是 int / str 键，不经过这个分支，所以 §2 / §3 的结论不受影响；
但本票最后仍用**修好之后的代码**把全量验收 A/A2/B 重跑了一遍（见 §2 数字）。

---

## 11. 本目录产物清单

| 文件 | 用途 |
|---|---|
| `report.md` | 本报告 |
| `m10_00_00_00_patched.msb.dcx` | 验收 B 产物（480,978 B，两个 npc_id 已互换） |
| `_accept_full.log` | **验收 A / A2 / B 的完整日志（主证据）** |
| `_stats_size.log` | 体量影响统计 |
| `_stats_addressing.log` / `_addressing.json` | 27,780 个敌人 part 的寻址可达性（含逐图明细） |
| `_stats_prefix.log` | DCX 76 字节前缀不变量 |
| `_recon_kinds.py` / `_recon_heads.py` / `_recon_comp.py` | 侦察脚本（kind 分布 / 前缀一致性 / zlib 与 Oodle 试压） |
| `_verify_packaging.py` | 封装细节 + edits 语义（歧义 / 未命中 / 别名 / model 改写）验证 |
| `_xcheck_witchybnd.py` / `_xcheck_tree.py` | 独立解析器交叉验证 |
| `_wx_test/` | 交叉验证工作区（两个 dcx + `_keep/` 下的 6 个小证据 XML） |
