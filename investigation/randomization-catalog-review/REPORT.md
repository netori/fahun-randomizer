# 候选清单质量审计报告（法魂随机化 · 干跑准入）

**审计对象**：`investigation/randomization-catalog/`（职业装备与职业法术卢恩候选资料）
**审计者定位**：本地**只读**质量审计代理。未重新解包、未运行 WitchyBND、未修改 MOD / 游戏 / 存档 / Excel / 工具 / 已有调查产物。
**本轮产物**：只写入 `investigation/randomization-catalog-review/`（candidate_review.csv / slot_conflicts.csv / REPORT.md / manifest.json / evidence/ / logs/ / scripts/）。
**判定语义**：`approved` **只表示可以进入随机化干跑**，不表示可以直接写回 MOD。

---

## 0. 输入完整性（先决条件）

| 输入 | 大小 | SHA256（前 16） | 与输入自带记录 |
|---|---|---|---|
| `items.csv` | 239,334 | `662a6160e913b818` | MATCH |
| `reward_slots.csv` | 699,310 | `094c61c3590854f2` | MATCH |
| `bundles.json` | 28,366 | `cb4882d7a354c413` | MATCH |
| `guide_entries.csv` | 60,380 | `1a8a5828cf1a8eda` | MATCH |
| `REPORT.md` | 15,179 | `14c1cd684146a72c` | MATCH |
| `manifest.json` | 11,761 | `d005657baf175e68` | MATCH |

核对基准 = 输入自带的 `evidence/source_integrity_final.json`（`baseline_all_match: true`）。**六项全部 MATCH → 未触发 BLOCKED 条件**，审计继续（日志 `logs/001_input_hash_check.*`）。

> 附注（不构成 BLOCKED）：`输入目录内的 CSV 与 items.csv 之间存在一处内部缺口`——见 §6.1。

---

## 1. 判据与 reason_code 字典

| 决策 | 含义 | 判据 |
|---|---|---|
| `approved` | 可进入干跑 | 身份（FMG + 参数行 + 部位标志）∧ 有类别正确的真实奖励槽 ∧ 池归属有独立证据（Bundle 成员 / 职业说明点名 / 卢恩等级+流派+说明书点名） |
| `pending` | 暂不可进入干跑 | 缺槽、池归属无证据、Bundle 不完整、或需人工决策 |
| `excluded` | 排除 | 经验卢恩、中间物（碎片）、关键/剧情类卢恩 |

| reason_code | 计数 | 说明 |
|---|---:|---|
| `POOL_ASSIGNMENT_UNSUPPORTED` | 416 | 防具身份/部位有证据，但**池归属无独立证据**（仅凭资料表效果文本被标成 poolB_candidate） |
| `RUNE_IDENTITY_TIER_SLOT_OK` | 90 | 卢恩身份+等级+流派+槽位+说明书点名齐全 |
| `NO_REWARD_SLOT_EVIDENCE` | 81 | 既无 `reward_slots.csv` 行，也无法在 `evidence/lot_reward_index.json` 里找到类别匹配的槽 |
| `OUT_OF_SCOPE_EXP_RUNE` | 34 | 普通经验卢恩（含描述"使用后能获得…"的幽影之地卢恩等） |
| `OUT_OF_SCOPE_KEY_OR_OTHER_RUNE` | 19 | 大卢恩/修复卢恩/卢恩弯弧等关键或剧情类 |
| `CLASS_AFFINITY_UNVERIFIED` | 18 | 完整卢恩但**职业说明书未点名**（全部为「微光＊卢恩」= 新手级） |
| `MISSING_TARGET_SLOT` | 9 | Bundle 四件不齐或四槽不齐 |
| `BUNDLE_MEMBER_APPROVED` | 8 | 已批准 Bundle 的成员 |
| `GUIDE_ATTRIBUTED_SINGLE_PIECE` | 7 | 职业说明书点名的单件（池B 散件） |
| `BUNDLE_MEMBER_BUNDLE_NOT_APPROVED` | 6 | 属于未批准 Bundle 的成员（**不得当场降级当散件用**，需人工决策） |
| `OK_FOUR_PARTS_FOUR_SLOTS_INDEX_VERIFIED` | 2 | 四件齐/四槽齐/槽位与索引一致 |
| `WEAPON_PENDING_USER_APPROVAL` | 2 | 两把新武器，按用户指示待批准 |
| `INTERMEDIATE_ITEM_EXCLUDED` | 1 | 岩浆卢恩碎片（中间物） |

---

## 2. 分类统计（验收要求：装备 / 武器 / 卢恩 / Bundle 分别统计）

| 类别 | approved | pending | excluded | 合计 |
|---|---:|---:|---:|---:|
| 装备（protector） | **15** | 503 | 0 | 518 |
| 武器（weapon） | **0** | 2 | 0 | 2 |
| 卢恩（goods） | **90** | 18 | 54 | 162 |
| Bundle（套装） | **2** | 9 | 0 | 11 |
| （明细行合计） | 107 | 532 | 54 | 693 |

**approved 明细**

- 装备 15 件：火山术士四件（`1210000/1210100/1210200/1210300` → LOT `16000090`–`16000093`·slot1）、基本主义者四件（`1310000`–`1310300` → LOT `1045370050`–`1045370053`·slot1）、说明书点名单件 7 件（`5230100`→`20010500`、`5183000`→`21011991`、`5182000`→`21001995`、`5272000`→`20011981`、`5020000`→`30930`、`5400000`→`10561`、`5300000`→`107400`，均 slot1）。
- 卢恩 90 条：`rune:学徒级 18 / rune:熟练级 18 / rune:精通级 18 / rune:大师级 18 / rune:大师级(幽影) 18`。
- Bundle 2 组：火山术士、基本主义者（四部位 head/chest/arms/legs 各 1，四个**不同**目标槽，且与 `evidence/lot_reward_index.json` 逐槽核对一致）。

**pending 明细**：503 装备（416 池归属无证据 + 81 无槽 + 6 未批准 Bundle 成员）、18 卢恩（全部为新手级「微光＊卢恩」，缺职业说明书点名）、2 武器。
**excluded 明细**：34 经验卢恩 + 19 关键/剧情卢恩 + 1 中间物（碎片）。

---

## 3. 两把新武器：职业标签与机械类别约束（验收要求）

| 项 | 女猎手刺剑 | 欺诈者的大戟 |
|---|---|---|
| 用户确认的职业标签（`profession_affinity`） | **秘契职业** | **神皮流派** |
| 标签性质 | **仅会话元数据**：不作 item_id / EquipParamWeapon 行 / 奖励入口 / FMG entry 的证据 | 同左 |
| 真实参数证据（引用上一轮 `evidence_path`） | [weapon_mapping.csv](../weapon-baseline/weapon_mapping.csv)（row 5100000，`weaponCategory=2`、`wepType=15`）+ [weapon-baseline/REPORT.md](../weapon-baseline/REPORT.md#L1) | `weapon_mapping.csv`（row 18530000，`weaponCategory=7`、`wepType=29`） |
| 机械子池（建议） | `weapon:category=2` | `weapon:category=7` |
| 合法目标槽（类别=2 武器） | `ItemLotParam_map:30203:slot1`（flag 530201） | `ItemLotParam_map:20701:slot1`（flag 520701） |
| 准入状态 | `pending / WEAPON_PENDING_USER_APPROVAL` | 同左 |
| 已剔除的错误槽 | `107111`/`107121`/`117102`（cat=3 防具，同名 ID 跨类别）与 2 条商店行（equipType=1 防具） | 无 |

**机械类别约束（写入子池时不可违反）**：`weapon:category=2` 与 `weapon:category=7` 之间可互换（同为大类"武器"）的前提是**双方都是武器类别**；**禁止** weapon↔armor、weapon↔rune、armor↔rune 互换；未知类别一律不得参与互换。

---

## 4. 机械子池建议（现状）

| 子池键 | approved 数 | 来源 |
|---|---:|---|
| `armor:head` | 8 | EquipParamProtector `headEquip=1` |
| `armor:chest` | 3 | `bodyEquip=1`（原字段名 body → 统一命名 chest） |
| `armor:arms` | 2 | `armEquip=1`（arm → arms） |
| `armor:legs` | 2 | `legEquip=1`（leg → legs） |
| `armor:set_bundle(4件)` | 2（Bundle 行） | 四部位整体置换 |
| `rune:学徒级 / 熟练级 / 精通级 / 大师级 / 大师级(幽影)` | 各 18 | FMG 描述中的实际等级名（"使用后学会一些…级…"） |
| `weapon:category=2 / =7` | 0（武器均 pending） | 被引用证据 `weapon_mapping.csv` |

`goods:<实际类别>`：**输入资料没有 goods 子类别字段**，且进入 approved 的 goods 全部是卢恩（已用 `rune:<等级>` 表达），故未生成 `goods:*` 子池——不猜值。部位字段名映射（body→chest、arm→arms、leg→legs）已在 `candidate_review.csv` 的 `mechanical_subpool` 中统一。

---

## 5. 重复与冲突清单（明细：`slot_conflicts.csv`，203 行）

| conflict_type | 条数 | 严重度 | 处理 |
|---|---:|---|---|
| `SHOP_SEMANTICS_UNVERIFIED` | 178 | medium | 价格=1/0 或库存=−1 的商店行（行名疑为 Paramdex 回退），语义未确认前不纳入干跑 |
| `LOT_OTHER_SLOTS_PRESENT` | 15 | info | 目标 Lot 还有其它 slot（例：`ItemLotParam_enemy:340051304` 另有 s2:cat1:id190），干跑/写回**必须保留** |
| `INPUT_GAP_REWARD_SLOTS_MISSING` | 5 | medium | 见 §6.1 |
| `ITEM_CATEGORY_MISMATCH` | 3 | **high** | 见 §3：两把武器的同名跨类别槽已剔除 |
| `FINAL_PRODUCT_CRAFT_REF_MISSING` | 1 | medium | `8460 幽影岩浆卢恩` 缺合成引用证据（只记录候选，不改合成逻辑） |
| `INTERMEDIATE_IN_POOL` | 1 | info | `8550 岩浆卢恩碎片` 已排除 |

其它检查结果：`同一(类别,ID)多个语义名称` = **0**；`同一奖励槽被多个物品候选占用` = **0**（`SLOT_MULTI_CLAIM` 未触发）；`Bundle 之间共享目标槽` = **0**（`BUNDLE_SLOT_SHARED` 未触发）；`Bundle 成员跨 Bundle 重叠` = **0**（`MEMBER_SHARED_WITH_APPROVED_BUNDLE` 未触发）。

---

## 6. 输入资料本身的缺陷（审计发现，未修改输入）

### 6.1 `reward_slots.csv` 缺 22 行（中等）
`items.csv` 含 22 行后来补入的防具（18 个 Bundle 成员 + 其余说明书件），但**同批次的 `reward_slots.csv` 没有这些物品的入口行**（生成顺序问题）。影响：5 个 Bundle 的成员槽位无法从 `reward_slots.csv` 直接读到。
**本次处置**：审计用输入内另一份证据 `evidence/lot_reward_index.json` 逐槽核对（`verify_map`：表/行/slot 的 item_id 与 category 必须完全一致），全部通过；受影响的 5 组在 `slot_conflicts.csv` 中标记为 `INPUT_GAP_REWARD_SLOTS_MISSING`，并在相关行的 `slot_evidence` 中写明证据来自索引文件。**未替输入补行**。

### 6.2 商店路径语义不确定（178 条）
价格=1/0、库存=−1 或行名回退的商店行，`equipType=1`（防具）语义正确但**售卖意图不明**（可能是"回退/灰烬"占位行）。凡是**仅**有商店入口的候选不应进入首批干跑。

### 6.3 池归属标注口径偏松（416 条）
输入把 601 件防具统一标为 `poolB_candidate`，但其中 416 件**除了资料表效果文本外没有任何职业/散件归属证据**。审计将其降为 pending（`POOL_ASSIGNMENT_UNSUPPORTED`），未改动输入。

---

## 7. 是否具备进入干跑的条件

**部分具备。可以立即干跑的最小集合**（全部满足：身份+部位/等级+类别正确的真实槽+独立归属证据）：

1. **2 个 Bundle**（火山术士、基本主义者）——整体置换，各 4 槽；
2. **7 件说明书点名散件**（`5230100`/`5183000`/`5182000`/`5272000`/`5020000`/`5400000`/`5300000`）；
3. **90 条完整职业法术卢恩**（按 `rune:<等级>` 子池内互换）。

**暂不可干跑**：503 件防具（无归属证据或无槽）、18 条新手级卢恩（缺说明书点名）、2 把武器（待用户批准）、178 条商店口径（语义未确认）；**不得**把未批准 Bundle 的 6 个成员直接当散件使用（需人工决策）。

**干跑前必须人工拍板的 4 件事**：
1. `微光＊卢恩`（新手级，18 条）是否可用（缺说明书点名，但身份/等级/槽位齐全）；
2. 未批准 Bundle 的 6 个成员能否作为散件入池 B；
3. 商店路径是否允许参与（现 178 条语义未确认）；
4. `幽影` 系列是否与同等级的普通卢恩共用 `rune:大师级` 子池（现分列 `rune:大师级(幽影)`）。

---

## 8. 未伪造声明

- 报告中所有 ID / 槽位 / entry / 类别均来自输入资料的**已解析字段**或被引用证据；**没有**为缺失项编造数值。
- `world_position` 一律为 `hint_only`（仅 lot 行名/资料表文本），**未**声称已核实世界位置；`single_acquisition` 一律 `unverified`。
- 两把武器的职业标签**只**作为 `profession_affinity` 标签记录，未参与任何身份或槽位判定。
- 未修改任何只读输入；收尾哈希复核见 §9 与 `logs/005_final_verify.*`。

## 9. 收尾复核

`logs/005_final_verify.*`：6 个只读输入重算 SHA256 与 §0 完全一致（`INPUT_ALL_MATCH: true`），本目录产物哈希记入 `evidence/final_verify.json`。**原 MOD / 游戏 / 存档 / Excel / 工具 / 已有调查产物均未被修改。**
