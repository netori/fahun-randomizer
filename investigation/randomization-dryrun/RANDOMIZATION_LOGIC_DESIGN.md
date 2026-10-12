# 随机化逻辑演进设计评审

状态：待执行代理审阅
范围：只评审设计，不授权代码修改
兼容基线：当前已经能工作的随机化功能

## 1. 评审任务

请执行代理先审阅本文件、当前干跑报告、候选审计报告以及现有 Python/JavaScript 引擎，再返回：

1. 当前实现中哪些行为必须保持不变。
2. 本设计是否能在不改变兼容基线的情况下提升逻辑质量。
3. 哪些数据字段、约束或测试仍然不足。
4. 分阶段实施的最小改动方案与风险。
5. 不得在本次审阅中修改代码、MOD、Excel、计划 CSV 或生成新的部署产物。

相关现有资料：

- `investigation/randomization-catalog/REPORT.md`
- `investigation/randomization-catalog-review/REPORT.md`
- `investigation/randomization-dryrun/DRYRUN_REPORT.md`
- `investigation/randomization-dryrun/scripts/dryrun.py`
- `investigation/randomization-dryrun/scripts/dryrun_by_item.py`
- `investigation/randomization-dryrun/scripts/randomizer.py`
- `investigation/randomization-dryrun/engine.js`
- `investigation/apply/`

## 2. 不可改变的兼容基线

当前功能是产品基线，不因为设计评审中的意见自动改变。

### 2.1 当前模式

现有按物品 M1 的行为继续保留：

- 物品身份使用 `(category, item_id)`，不能只使用数字 ID。
- 同一物品的多个获取处作为一个组处理。
- 同组所有获取处得到同一个新物品。
- 默认尽量保持物品的获取处数不变。
- 获取处数在某个子池中没有同伴时，可以按当前 M1 规则保持原样。
- 固定 seed 可以复现同一结果。
- 现有计划 CSV 的字段和含义保持兼容。

### 2.2 当前结构规则

以下行为属于现有功能的一部分，后续设计不能悄悄改变：

- 法师/祷告类护甲的独立池逻辑。
- 职业初始套装的整组处理规则。
- 护甲部位映射：头、身、臂、腿分别处理。
- 同一物品的多来源一致性。
- 冻结项不参加随机化。
- 商店、幽影卢恩、套装和域联合等现有开关的存在。
- 现有 seed、配置和 CSV 能继续被旧工具读取。

### 2.3 跨类别模式

如果当前联合池允许护甲、卢恩和武器跨类别置换，则把它视为显式的兼容模式，而不是删除它：

```text
legacy_cross_category
```

该模式可以继续支持现有玩法，但必须在计划和 manifest 中明确记录：

```text
old_category
new_category
category_field_change_required
```

新的默认设计不得把跨类别行为隐式混入普通独立池。

## 3. 当前逻辑的设计问题

这些问题是演进目标，不代表要立即改变当前玩法。

### 3.1 多个引擎存在规则漂移

当前至少存在：

- 旧版按物品干跑逻辑；
- 可配置 Python 引擎；
- GUI JavaScript 引擎。

它们的分组、候选读取、洗牌、校验和开关处理并不完全一致。长期目标是建立一个唯一的 assignment engine，GUI 只负责读取配置、展示结果和导出计划。

兼容要求：旧模式的输出仍然可生成；切换到新引擎必须有 engine version 和 golden plan 对照。

### 3.2 当前主要是均匀洗牌，不是强度加权

当前候选数据没有完整的 `strength` 字段，现有干跑主要采用固定 seed 洗牌。原设计希望支持：

```text
T = max(0.01, randomness * 0.5)
weight(a, b) = exp(-abs(strength_a - strength_b) / T) * type_factor
```

其中：

- `randomness` 范围为 0.0 到 1.0；
- 同类型 `type_factor = 1.0`；
- 允许跨类型时 `type_factor = 0.7`；
- 套装要按整体或对应部位计算，而不是把四件拆成四个互不相关的随机事件。

这应作为新增的可选模式，不改变当前默认均匀模式。

### 3.3 约束检查与候选选择需要分层

候选筛选、原子单元构建、兼容判断、随机匹配、计划输出和写回校验目前有部分混合。新设计应把它们分为独立阶段：

```text
snapshot
  -> normalize
  -> freeze / eligibility
  -> build atomic units
  -> build compatibility graph
  -> assign
  -> emit plan
  -> verify plan
```

任何阶段失败都应返回结构化报告，不使用空值、默认值或“继续执行”掩盖缺失证据。

## 4. 建议的领域模型

### 4.1 ItemKey

```json
{
  "category": "protector|weapon|goods|accessory|gem",
  "item_id": "整数或规范字符串"
}
```

`ItemKey` 是唯一身份。任何比较、分组、去重和计划引用都必须使用完整的 `(category, item_id)`。

### 4.2 AcquisitionCell

```json
{
  "source_table": "ItemLotParam_map|ItemLotParam_enemy|ShopLineupParam",
  "row_id": "字符串",
  "slot": "字符串或空",
  "old_item": {"category": "", "item_id": ""},
  "quantity": "原值",
  "base_point": "原值",
  "cumulate_lot_point": "原值",
  "get_flag": "原值",
  "shop_price": "原值或空",
  "shop_stock": "原值或空",
  "conditions": {},
  "row_name": "原值",
  "evidence": []
}
```

`AcquisitionCell` 描述固定位置和原始内容。随机化只能产生该 cell 的新内容映射，不改变位置字段和未授权属性。

### 4.3 ItemGroup

同一 `(category, item_id)` 的所有获取处组成一个 `ItemGroup`：

```json
{
  "group_id": "category:item_id",
  "item": {"category": "", "item_id": ""},
  "cells": [],
  "acquisition_count": 0,
  "part": "head|chest|arms|legs|none",
  "archetype": "",
  "strength": null,
  "eligibility": "approved|pending|excluded",
  "evidence": []
}
```

M1 模式下，组是最小置换单位。组内所有 cell 必须得到同一个新物品。

### 4.4 BundleUnit

完整四件套作为一个 BundleUnit：

```json
{
  "unit_id": "bundle:<bundle_id>",
  "members": {
    "head": "protector:<id>",
    "chest": "protector:<id>",
    "arms": "protector:<id>",
    "legs": "protector:<id>"
  },
  "source_groups": {},
  "archetype": "",
  "strength": null,
  "eligibility": "approved|pending|excluded",
  "evidence": []
}
```

BundleUnit 只能与具有相同结构的 BundleUnit 配对。替换时头对头、身对身、臂对臂、腿对腿。

## 5. 兼容性策略

### 5.1 模式定义

建议保留以下模式：

```text
legacy_uniform_m1
weighted_m1
legacy_cross_category
```

`legacy_uniform_m1` 是默认兼容模式。它的输出必须保持当前行为和字段语义。

`weighted_m1` 是可选新模式，只有用户明确选择时才启用。

`legacy_cross_category` 用于兼容当前已经存在的跨类别联合玩法；它不应被新的普通独立池默认启用。

### 5.2 硬约束与软权重分离

硬约束先过滤边，软权重只对合法边排序：

硬约束包括：

- 冻结项不得参与；
- pending/excluded 不得进入 approved 置换；
- 完整套装只能与完整套装配对；
- 套装部位必须对应；
- 同一物品组的所有 cell 必须同步；
- 同一目标 cell 只能被一个源单元占用；
- 未启用跨类别策略时类别必须相同；
- 未启用跨部位策略时部位必须相同；
- 计划不能改变未授权的数量、权重、flag、价格、库存和条件。

软权重包括：

- strength 差距；
- 同类型偏好；
- 获取阶段或地区档位；
- 职业倾向相似度。

硬约束不应由随机性或低合理度覆盖。

## 6. 建议的分配算法

### 6.1 兼容模式：legacy_uniform_m1

保持现有功能，但将算法明确化：

1. 按 `ItemGroup` 或 `BundleUnit` 建池。
2. 按当前 M1 规则保留获取处数层。
3. 使用固定 seed 生成确定性排列。
4. 对不可完全错排的层记录 `unchanged_reason`。
5. 输出旧格式计划和新 manifest。

这一步只做结构整理和验证增强，不改变随机结果。

### 6.2 新模式：weighted_m1

建议使用确定性二分图匹配或最大权匹配，而不是随机洗牌加重试：

- 左侧：目标位置单元；
- 右侧：候选来源单元；
- 边：满足硬约束的合法配对；
- 边权：strength 权重、类型偏好和职业相似度的组合；
- 结果：一一匹配，保证数量守恒。

同一 seed 下必须先按规范化 `ItemKey` 排序，再使用固定 tie-breaker，避免字典顺序或文件遍历顺序改变结果。

匹配失败时按固定顺序降级并记录：

```text
保持获取处数层
  -> 放宽 strength 差距
  -> 使用同一机械子池的全部合法单元
  -> 保持无法匹配的单元原样
```

任何降级都必须进入计划报告，不能静默发生。

## 7. 计划输出要求

每条计划至少包含：

```json
{
  "engine_version": "",
  "algorithm_mode": "legacy_uniform_m1|weighted_m1|legacy_cross_category",
  "seed": 0,
  "pool": "",
  "unit_id": "",
  "source_table": "",
  "row_id": "",
  "slot": "",
  "old_category": "",
  "old_item_id": "",
  "new_category": "",
  "new_item_id": "",
  "old_strength": null,
  "new_strength": null,
  "category_field_change_required": false,
  "unchanged_reason": "",
  "preconditions": {},
  "evidence": []
}
```

`preconditions` 必须包含写回前应再次确认的原始 ID 和类别。原值不一致时，写回必须停止，而不是跳过后继续生成半成品。

## 8. 计划校验标准

执行代理必须提供以下测试：

### 8.1 兼容性测试

- legacy 模式仍生成当前计划格式；
- 相同输入、相同配置、相同 seed 得到相同计划；
- 当前已认可的 M1 多来源一致性保持；
- 套装不拆分；
- 未授权字段不出现在变更集合中；
- 现有 GUI 选项仍能表达当前玩法。

### 8.2 负例测试

至少覆盖：

- 相同数字 ID、不同 category；
- 一个物品有多个获取处；
- 一个 Lot 有多个 slot；
- 获取处数层只有一个物品；
- 完整套装缺一个部位；
- pending 或 excluded 候选；
- old ID 正确但 old category 错误；
- 目标 slot 已被另一映射占用；
- shop_stock 不符合当前配置；
- FMG 文本重复但 entry ID 不同。

### 8.3 加权模式测试

- `randomness=0` 只允许最接近强度的合法匹配；
- `randomness=1` 在合法范围内接近均匀；
- 结果对 seed 可复现；
- 权重不会破坏硬约束；
- 套装按对应部位保持结构；
- 多处来源仍然整组一致。

## 9. 实施边界

执行顺序建议：

1. 只读审阅并确认当前兼容模式的真实输入、输出和默认配置。
2. 抽取 canonical model，但暂不改变旧引擎输出。
3. 用 golden plan 对照验证 `legacy_uniform_m1` 与当前结果一致。
4. 把 Python 和 GUI 接到同一个核心引擎。
5. 以 opt-in 方式加入 `weighted_m1`。
6. 只读生成新旧计划 diff，等待人工确认。
7. 最后才考虑部署链的改进。

执行代理在第 1 至第 5 步完成前，不应修改 MOD、写回参数、重打包、更新 FMG 或启动游戏。

## 10. 完成标准

本设计评审完成的条件：

- 执行代理明确列出当前功能基线；
- 执行代理明确区分兼容模式和新加权模式；
- 所有硬约束都有对应的数据字段和测试；
- 旧模式不会被新模式静默替换；
- Python、GUI 和计划生成入口的差异被记录；
- 未经用户批准，没有任何代码或 MOD 文件变更；
- 评审报告明确列出仍需用户决策的事项。

本文件本身不是实施授权。任何代码变更必须在单独任务中得到明确批准，并先提供变更范围和预期兼容性证明。
