# 真换敌人产出器 —— 自检报告

> 由 `investigation/apply/enemy_swapper.py` 自动生成。所有数字都是**这一跑实测**出来的，不是估计。

## 结论

| 判据 | 结果 |
|---|---|
| 产出图数 | 4 张（要求 ≥3） |
| 输出目录 | `F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\swapper_probe` |
| 源地图目录 | `F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）\mod\map\MapStudio`（**只读**） |
| mod 目录是否被改动 | **否**（前后逐文件 sha256 相同） |
| 校验：意外变的 part | **0 个**（要求 0） |
| 校验：明文里越界的改动字节 | 0 个（要求 0） |
| 校验：明文长度是否一致 | 一致 |
| 校验：该变的 part 字段不符 | 0 个（要求 0） |
| 校验：条目序号不符 | 0 个（要求 0） |
| 校验总体 | **通过** |
| 能否交给 `plan_layer.export_layer(extra_files=[…])` | **能** —— 见文末接线说明 |

## 这一跑改了什么

| 指标 | 值 |
|---|---|
| 替换关系（pairs） | 14 条 |
| 扫过的图 | 4 张 |
| 有改动的图 | 4 张 |
| 写出的图 | 4 张 |
| **改动的 enemy part** | **71 个** |
| 命中的 part（含跳过/未变） | 84 个 |
| **跳过的 part** | **13 个** |
| 命中但值本来就相同 | 0 个 |
| 因 think/chara 过小未当匹配轴 | 0 个 |
| 匹配轴分布 | {"npc_id": 71} |
| 耗时 | 2.9 s |

### 跳过原因分布

| 原因 | 个数 | 含义 |
|---|---|---|
| `target-model-not-in-map` | 13 | 目标行的主模型**不在那张图的 MODEL 段**里。加模型要改 MODEL 数组长度与一堆偏移（结构改动），定点写做不到 → 按硬规则跳过。 |

### 逐图明细

| 地图 | 改的 part | 跳过 | 源字节 | 产出字节 | 产出 DCX kind | sha256(前16) |
|---|---|---|---|---|---|---|
| `m10_00_00_00.msb.dcx` | 14 | 5 | 529554 | 480983 | DFLT | `ebf217e36e0d1f9f` |
| `m11_00_00_00.msb.dcx` | 20 | 0 | 846679 | 778835 | DFLT | `1c2a8c8f01649706` |
| `m12_02_00_00.msb.dcx` | 32 | 6 | 575892 | 517105 | DFLT | `2c52af27d87b773e` |
| `m30_04_00_00.msb.dcx` | 5 | 2 | 19792 | 18700 | KRAK | `9f338750da50cc19` |

## 校验：逐字段比对

`verify_outputs` 把每张输出图读回来，与源图对齐（对齐键 = PARTS_PARAM_ST **条目序号**，因为实测 EntityID 只有 29.9% 唯一）后：

1. **该换的 part**：每个字段都必须等于计划里的新值（不是「变了就行」）；
2. **不该换的 part**：`entity_id / npc_id / think_id / chara_id / model / model_index / 坐标` 逐字段相同；
3. **条目序号集合**必须一致（没有增删条目）；
4. **字节级（最硬的一条，不依赖字段解释）**：两张图的明文长度相同，且**每一处 4 字节不同**都落在「某个该改的 part 的某个该改字段」的原地偏移上 —— 落在别处就算越界。

| 地图 | 源 part 数 | 期望变 | 实际变 | 意外变 | 越界字节 |
|---|---|---|---|---|---|
| `m10_00_00_00.msb.dcx` | 283 | 14 | 14 | 0 | 0 |
| `m11_00_00_00.msb.dcx` | 309 | 20 | 20 | 0 | 0 |
| `m12_02_00_00.msb.dcx` | 808 | 32 | 32 | 0 | 0 |
| `m30_04_00_00.msb.dcx` | 14 | 5 | 5 | 0 | 0 |

**合计：期望变 71 个 / 实际变 71 个 / 意外变 0 个。**

### 校验器本身可信吗（反面测试）

一个**永远说 OK** 的校验器没有价值，所以模块自带反面测试（`negative_selftest`，跑在 `<out_dir>/_neg/` 的副本上，真产出只被读）：故意弄坏三份产出，要求 `verify_outputs` 各自抓到。

| 案例 | 怎么弄坏 | 必须由哪一条抓到 | 结果 |
|---|---|---|---|
| `A_not_target` | 改一个不该改的 part 的 npc_id | `unexpected_changed` | **抓到了**（unexpected_changed=1） |
| `B_reverted` | 把该改的 part 改回原值 | `value_mismatch` | **抓到了**（value_mismatch=1） |
| `C_untracked_field` | 改旋转（不参与字段比对） | `stray_bytes` | **抓到了**（stray_bytes=1） |

案例 C 是关键：改的是**旋转**，字段级比对**看不见**它（它不在比对字段里），只有**字节级**那条能抓到 —— 这就是字节级校验存在的意义。

**总结论：三例全被抓到，`verify_outputs` 不是空转的。**

## 自检配对是怎么挑的

* m10_00_00_00：配了 4 行（含 Boss）
* m11_00_00_00：配了 4 行（含 Boss）
* m12_02_00_00：配了 4 行（含 Boss）
* m30_04_00_00：配了 2 行（普通）

挑法：每张图取本图实际出现的行（排除占位行 0/1），Boss 与普通分组、组内**循环配**（A→B→C→D→A）。这样每个键都是本图的 npc_id，且两端的模型都在本图 MODEL 段里 —— 实测：行被放在某图上 ⇒ 它的模型必在该图 MODEL 段。

## 全量外推：同一份计划在**全部 634 张图**上跑一遍

（dry-run，不写任何文件；数字是这一跑实测）

| 指标 | 值 |
|---|---|
| 扫过的图 | 634 |
| 会改动的图 | 222 |
| 会改动的 part | 541 |
| 会跳过的 part | 891 |
| 读+计划耗时 | 4.7 s（0.007 s/图） |

注意这份计划只配了 **14 条**关系、且是围绕自检那几张图配的，所以它落到别的图上是「外来客」、跳过率被放大；真正按图配的计划跳过率≈0（见上）。

## 外部证据（不在本报告自动流程里，命令可复现）

| 证据 | 命令 | 实测结果 |
|---|---|---|
| 独立阅读器交叉验证 | `python investigation/swapper_probe/_xcheck.py` | 4 张图**全部一致**：敌人条数相同、`part_name` 序列相同、产出 DCX kind 不变；并用 `msb_write.part_fingerprint` 覆盖**所有类型** part（地图块/物件/碰撞/玩家）确认**非敌人 part 一个都没动** |
| 写出速率 | `python investigation/apply/enemy_swapper.py --maps 40 --out <tmp>` | 40 张读+写 13.1 s（33 张真写、11 MB）→ **0.33 s/图**；外推 634 张全量写出约 **3.5 分钟** |
| 全量扫一遍 | `python investigation/apply/enemy_swapper.py --maps 634 --dry-run` | 634 张 **4.3 s**（0.007 s/图） |

## 能不能直接交给 `plan_layer.export_layer(extra_files=[…])`


**能。** 方案层按 `plan_layer.py` 的约定是 `mod/map/MapStudio/<改过的>.msb.dcx`（那个文件的注释第 14 行就是这么写的），所以：

```python
import os, sys
sys.path.insert(0, r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\apply")
import enemy_swapper as ES, plan_layer as PL

plan = ES.plan_swaps(pairs, out_dir=r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\随机mod\investigation\swapper_probe")
extra = [(f["out"], os.path.join("map", "MapStudio", f["map"]))
         for f in plan["files"]]
PL.export_layer(label="20261016_敌人全随", extra_files=extra)
```

`export_layer` 只对**存在**的文件拷贝（不存在会打印跳过），所以 `plan["files"]` 可以直接喂进去。注意它同时会把 `regulation.bin` 抄进层里 —— 那是它本来的职责。

## 两条必须知道的上游约束（实测，会改变随机器怎么抽）

### 1. 从全局池盲抽目标行 → 66%~85% 的 part 会被跳过

在 60 张图上做随机配对实测：

| 配对来源 | 主模型在图内（可用） | all_models 兜底救回 | **跳过** |
|---|---|---|---|
| 普通→普通 | 26.13% | 0.00% | **73.87%** |
| Boss→Boss | 14.96% | 0.00% | **85.04%** |
| 任意→任意 | 33.64% | 0.00% | **66.36%** |

这不是 bug，是硬规则的必然结果：一张图的 MODEL 段只有它自己用到的模型，而全游戏的角色模型远多于一张图。`all_models` 兜底几乎没用 —— 实测 3806 个行里 **3788 个只有 1 个模型**。

### 2. 从**每图可达行池**抽 → 跳过率≈0

但每张图的可达行池其实很大（`--pool` 会导出 `reachable_rows.csv`）：

| 每图可达行数 | min | p10 | median | p90 | max |
|---|---|---|---|---|---|
| 值 | 1 | 76 | 521 | 739 | 1717 |

所以「真换敌人」要做得干净，随机器应当**按图抽目标**：先 `ES.pool_table()` 拿到每张图的可达行池，再在池内配对。全局池配出来的计划会被本模块如实跳过并计数 —— 不会静默失败，但应用率会很低。

**已经实测过这条**（`_permap_experiment`）：对前 20 张图，每张都用**本图的行**两两循环配对、再只对那张图跑一次 `plan_swaps(dry_run=True)`：

| 按图抽目标 | 值 |
|---|---|
| 参与图数 | 20 |
| 这些图上的 enemy part | 3311 |
| 会改动 | 3301 |
| **跳过** | **0** |

跳过 = 0，因为按图抽目标时「目标模型不在该图」这件事**不可能发生**。这就是给随机机的结论：**按图抽，不要全局抽**。

### 3. `think_id` 是启发式的（不确定度已量出）

同一个 npc_id 在不同图上可以用不同的 think_id：3807 个行里 **469 个（12.32%）**有多个。本模块取**地图实测众数**。上游 `pairs` 只给了行 id，没给 think，所以这是能做到的最好选择；但它确实是启发式 —— 要更准就得让随机器把 think_id 一起给出（本模块的 `write_fields` 可关掉它）。

