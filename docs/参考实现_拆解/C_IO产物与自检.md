# 参考实现拆解 C：输入契约与选项面

> 对象：thefifthmatt/SoulsRandomizers（只读检出）。**本文所有路径都相对参考仓库根目录**，例如 `RandomizerCommon/Core/RandomizerOptions.cs:463`。
> 目的：回答"他是如何设计的"里**输入与选项**那一半——随机器认为"世界"是什么、哪些选择会改变结果、哪些不会。
> **不重叠**：`SaveEldenRing` 的产物清单 / 写集 / randobak 三分支 / `RuntimeParamChecker` 见 A、B 报告。

## 0 读法与证据边界

| 文件 | 覆盖 |
|---|---|
| `RandomizerCommon/Core/RandomizerOptions.cs` | 全文（重点 17-516） |
| `RandomizerCommon/Core/RandomizerOptionsFile.cs` | 全文 |
| `RandomizerCommon/Core/GameData.cs` | 234-290、695-880、1670-1805、2015-2160 |
| `RandomizerCommon/Core/Submaps.cs` | 全文（1-128） |
| `RandomizerCommon/Core/Util.cs` | 231-260（`PhraseRe` / `JavaStringHash` / `XxStringHash`） |
| `RandomizerCommon/Enemy/EnemyPreset.cs` | 173-294、308-404 |
| `RandomizerCommon/Item/Permutation.cs` | 331-427 |
| `RandomizerCommon/Item/LocationData.cs` | 94-440 |
| `RandomizerCommon/Item/PermutationWriter.cs` | 1-210 |
| `RandomizerCommon/Enemy/{EnemyPermutation,EnemyState,EnemyMapping}.cs` | 全文 |
| `RandomizerCommon/Randomizer.cs` | 60-205、340-580 |
| `EldenRingRandomizer/Program.cs`、`CommandRunner.cs` | 全文 |
| `RandomizerCommon/Misc/MiscSetup.cs` | 172-201、293-326、397-438 |

**未读、不作为依据**：`SoulsIds`（`Editor.LoadNames` / `Editor.LoadParams` / `Spec` 的实现）源码**不在本检出里** → 所有 `Editor.*` 只按调用契约引用，不解释内部；`EldenForm` 主窗体不在检出；`Permutation.Logic` 主体与 `PermutationWriter.Write` 200 行之后。凡写「不确定」处即为证据缺口。

---

## 1 输入契约

### 1.1 数据目录：一份 dist 目录，五种游戏共用一套布局

| FromGame | 目录 | 出处 |
|---|---|---|
| ER | `diste` | `RandomizerCommon/Randomizer.cs:63-71` |
| DS3 / DS1R / SDT / NR | `dist` / `dist1` / `dists` / `distnr` | 同上 |

`if (!Directory.Exists(distDir)) throw new Exception("Missing data directory")`（`Randomizer.cs:127-130`）。

`{distDir}` 下只有六件事（`RandomizerCommon/Core/GameData.cs:278-280`、`1708`、`RandomizerCommon/Enemy/EnemyPreset.cs:265-269`）：

| 位置 | 是什么 | 缺了会怎样 |
|---|---|---|
| `Base/files.txt` | 游戏文件清单 | 抽取阶段即失败 |
| `Base/submaps.txt` | 坐标→子区域名 | 直接 throw（见 1.5） |
| `Names/` | 显示名表 | 静默降级成 id |
| `Defs/` | paramdef | 静默少写（见 1.3） |
| `Vanilla/` | regulation.bin 等基线 | `LoadParams` throw（见 1.6） |
| `presets/` | 敌人预设 `.txt` | `LoadPreset` 报路径 |

**没有任何一处"从游戏本体现读"**——除首次 `UnpackVanillaFiles` 抽取外，随机器的世界完全由 dist 目录 + 用户指定的 gameDir 决定。

### 1.2 `Base/files.txt`：唯一的"这个游戏有多少文件"的权威

- 逐行切段（`GameData.cs:2047-2060`）：`path` / `archive` / `length` / `sha1`；`archive` 为 `None` 表示**散文件**（`regulation.bin` 这类）。少段直接 `throw Bad line {line} in {fileList}`（`2054`）。
- 校验强度**按类别不对称**：

| 类别 | 校验 | 不符后果 | 出处 |
|---|---|---|---|
| 散文件（含 `regulation.bin`） | 长度 + SHA1 双匹配 | `throw`，随机化中止 | `GameData.cs:2113-2120`、`2124-2127` |
| 归档内文件 | **只比长度** | 记 `mismatchedFiles`，**继续跑** | `GameData.cs:2140-2143` |
| 已存在于 Vanilla 的文件 | **只比长度**（注释明说不查 SHA1，I/O 太贵） | 视为 okay | `GameData.cs:2068-2082`（`2077`、`2075-2076`） |

- 末尾汇总（`2150-2157`，原文）：`Extracted {fixPaths.Count} game files, but at least {mismatchedFiles.Count} files have unexpected contents. This could indicate this version of the randomizer may be incompatible with the installed game version.` + `Mismatched files in Vanilla directory: {...}`。
- **第二个用途（容易漏看）**：`unpackPaths = allPaths.Keys.ToList()`（`2083`）被 Save 阶段用来枚举"历史上可能写过"的地图（`1333-1337`）——**输入清单同时是输出清理的枚举源**。这就是"为什么旧产物能被清掉"的机制来源。

### 1.3 `Defs/*.xml`：paramdef 是"要不要重写这张表"的开关

- `Editor.Spec.DefDir = {dir}/Defs`（`GameData.cs:280`）；`LoadLayouts()` 在 `LayoutDir == null` 时 `Defs = Editor.LoadDefs()`（`1724-1734`）。
- `LoadParams()` 把 `defs` 传给 `Editor.LoadParams(...)`，最终 `Params = new ParamDictionary{ Inner=dict, Layouts=Layouts, Defs=Defs }`（`1736-1805`，`1799-1804`）。
- 写回：`Editor.OverrideBndRel(basePath, path, Params.Inner, f => f.AppliedParamdef == null ? null : f.Write(), dcx: DCX.Type.DCX_ZSTD)`（`1177`）。
- **机制要点**：返回 `null` 的 param **不覆盖、保留底本字节**。所以 paramdef 覆盖不全 ⇒ 某些表即使内存里改过也写不回去，**且不报错**。
- 对我们的直接教训：Python 侧若要自己写 param，必须有一份"我们敢写哪些表"的白名单；没有 schema 的表一律原样拷贝。

### 1.4 `Names/`：显示层，不是逻辑层

- `Editor.Spec.NameDir = {dir}/Names`（`GameData.cs:278`）。
- 六张表 + 六个 id 解析器（`1672-1676`）：`ModelName`(string)、`CharaInitParam`(`int.Parse`)、`ItemLotParam`(`int.Parse`)、`ShopQwc`(`int.Parse`)、`BonfireWarpParam`(`int.Parse`，`!EldenRing` 才读)。`characterSplits.Count == 0` 时塞 `characterSplits[0] = "UNUSED"`（`1687-1689`）。
- 缺省兜底：`?LOT?`（`703-706`）、`after {id}`（`708-711`）、`ModelName` 退回原 chr（`740-743`）、DS3 的 `CharacterName` 用"≤id 的最近分段"，`"UNUSED"` → `null`（`713-738`）。
- 消费点：`EntityName` 拼 `id N` / `group …` / FMG `NpcName` / `in MapLocationName`（`784-832`）、`ExtractModelName`（`755-770`，取最后一个下划线前的段，`mXX-YY` 形式取 `-` 后段）。
- 结论：**Names 只影响日志 / 提示文案**（`PermutationWriter` 的 hints，见 3.4），**不影响映射结果**。缺名字不崩，但玩家读到的就是 id —— 这是"日志可信度"的输入依赖。

### 1.5 `Base/submaps.txt`：坐标 → 子区域名

- 两级：`MapAreas` → `MultiMap{Map,Name,Comment,Areas}`（`Submaps.cs:70-87`）→ `MultiMapBound{XBelow,XAbove,YBelow,YAbove,ZBelow,ZAbove,Name,Comment}`（`89-128`）；`Match(pos)` 对六个阈值逐个做轴对齐判断（`118-128`）。
- 校验：`MapAreas == null` → `throw $"Invalid config {file}"`；某图 `Areas == null` → `throw $"Invalid config {file} - {map.Map} missing areas"`（`Submaps.cs:17-40`）。
- 加载点 `GameData.cs:1708`；顺带 `Submaps.Write("MapName.json", LocationNames)` 导出 map 名表（`1710`，`Submaps.cs:42-60` 按 map 排序输出 `{maps:[...]}`）。
- 解析：`LocationName(mapId, out extra, lowLevelMapId, pos)`（`GameData.cs:848-863`）——**有坐标且命中子区域就用它，否则退回 `LocationNames` 字典**；`MapLocationName` 拼 `{mapId} ({子区域})`（`834-845`）。
- 用途边界：只服务日志/提示定位，不参与映射。

### 1.6 `Vanilla/regulation.bin`：唯一的 param 底本

- `LoadParams()` 读 `{Dir}/Vanilla/regulation.bin`（`GameData.cs:1774-1787`）；只有 `Mods.Resolve("regulation.bin")` 命中才换成 mod 文件（`1777-1781`）；文件不存在 `throw Missing param file {path} - make sure to completely extract *all* files from the randomizer zip`（`1784`）。
- 同一 pattern 在 Save 阶段复现（basePath 永远是 `{Dir}/Vanilla/...`，见 B 报告）——**输入 = 只读基线，输出 ≠ 输入**，代码里不存在"以上一轮产物为输入"的路径。
- **不确定**：DLC 参数是否在同一 `regulation.bin` 内——本检出未见单独的 dlc regulation 路径，只有 `dlc` 选项影响写集。

### 1.7 输入契约一览（缺什么、在哪一步炸）

| 缺项 | 暴露时机 | 表现 |
|---|---|---|
| `Base/files.txt` | 抽取 | 早期失败 / `Bad line …` |
| `Defs/*.xml` | **永不暴露** | 静默少写（`AppliedParamdef == null`） |
| `Names/` | 永不暴露 | 日志里出现 `?LOT?`、`after N`、裸 id |
| `Base/submaps.txt` | 加载 | `throw Invalid config …` |
| `Vanilla/regulation.bin` | `LoadParams` | `throw Missing param file …` |
| `presets/*.txt` | 加载预设 | 报路径（`EnemyPreset.cs:265-269`） |
| 游戏本体版本不匹配 | 抽取最后一行 | 只有**警告**（例外：散文件即时中止） |

---

## 2 选项面

### 2.1 选项不是结构体，是两个有序字典

- `private SortedDictionary<string,bool> opt` / `SortedDictionary<string,string> str`（`RandomizerOptions.cs:70-71`）。
- 索引器（`239-262`）：名字以 `invert` 开头 → 改写成 `no`+后缀并取反；名字里含 `default` → **直接不入 opt**。
- `IsSwitchEnabled`（`264-269`）：`"always"`/null → true；值按空格分词，`!` 前缀取反 → 一个选项值里可以写多个子条件。

### 2.2 解析语法（`Parse(IEnumerable<string> args, FromGame game, Predicate<string> optionsFilter = null)`，`151-237`）

| 形态 | 含义 | 行 |
|---|---|---|
| 裸词 | `options[word] = true` | `201-205` |
| `k:v` | `str[k] = v` | `191-196` |
| `bias:N` | `Difficulty = N`，并从 str 删 | `211-215` |
| `seed:N` / `seed2:N` | `Seed` / `Seed2`，并删 | `216-234` |
| `vN` | `StoredVersion = Math.Max(N, StoredVersion)` | `197-200` |
| `--preset` 之后 | 后面的裸词全归 `Preset`（空格 join） | `162-174`、`235` |
| 位置参数（仅 DS3/SDT） | 依次 `difficulty` / `seed` / `seed2` | `175-190` |

- **没有白名单、没有拼写纠错**：`opt["enmy"]` 与 `opt["enemy"]` 是两个不同的键——前者不触发任何逻辑，却会进 `ConfigString`/seed 串。这是"改了选项但没变化"的经典来源。
- `Preset` 是**名字串**（`235`），可空格分隔多个名字。

### 2.3 seed 家族：三个概念必须分开

- `Seed`/`Seed2`(uint) + `SeedStr`（`17-43`）；setter（`20-43`）在 `TryParseSeed` 失败时 `throw $"Invalid string seed {value}"`（`38`）。
- `TryParseSeed`（`50-68`）：先 `uint.TryParse`；否则匹配 `^[a-zA-Z0-9]+$`（`SeedStrRe`，`49`）→ `Util.XxStringHash(str)`（`60`）。
- 版本位：`EldenRingVersion = 16`（`90-93`）；ER 的 `Parse` 把 `v1..v15` 置 false、`v16` 置 true（`126-133`）。
- `UseSeedStr` 只有 NR 为真（`146`）。

| 名字 | 来源 | 干什么 | 出处 |
|---|---|---|---|
| `opt.Seed` | 用户输入 | **放置随机流的唯一来源** | `Randomizer.cs:172`、`493`、`499` |
| `trueSeed` | `(int)Util.JavaStringHash(opt.LogicString() + "&&" + (enemyPreset == null ? "" : enemyPreset.ToStableString()))` | **只喂 `CharacterWriter`**（角色数据/外观/属性） | `Randomizer.cs:436`、`519` |
| `ConfigHash()` | `(Util.JavaStringHash(ConfigString(false,true,true)) % 99999).PadLeft(5,'0')` | 给"这组选项+预设"一个 5 位短标识 | `RandomizerOptions.cs:511` |

**推论（最容易搞错的一处）**：`new Random(seed)` 只用 `opt.Seed`（`Randomizer.cs:493`、`499`、`350`、`353`），**logic 选项不进放置流的 RNG 种子**——它们只改候选池与编辑结果；但它们改 `trueSeed`，所以**会改角色数据**。因此"同 seed 不同选项"既不等于同结果，也不等于完全无关的两轮。

### 2.4 进 seed / 不进 seed 的四层划分

| 层 | 内容 | 进 `LogicString`（→ `trueSeed`） | 进放置流 seed | 出处 |
|---|---|---|---|---|
| logic 布尔选项 | 除 logicless 外所有 `true` 键 | 是 | 否（只改候选池） | `RandomizerOptions.cs:453-456` |
| logicless 布尔选项 | `mergemods mergegame uxm me3 loose hideseed bossbgm noenvbgm crashfix utility patchseed runseed` | 否 | 否 | `445-450` |
| `str` 的 `k:v` | 除 logicless 键外 | 是 | 否 | `466` |
| 敌人预设内容 | `ToStableString()` | 是（拼在 `&&` 后） | 否 | `Randomizer.cs:436` |
| 物品预设 | `ItemPreset` | **否** | 否 | `436` 只拼 enemyPreset |

- 注释原文（`445-446`）：`Options which are purely aesthetic or related to installation` ——`uxm`/`mergemods` 被归为"安装相关"，于是**不影响逻辑一致性判断，但影响输出根与写集**（见 B）。

### 2.5 四个序列化串

| 方法 | 定义 | 含 seed | 含 preset | 只 logic |
|---|---|---|---|---|
| `ConfigString()` | `463-506` | 否（默认） | 否（默认） | 是（默认） |
| `FullString()` | `508` | 是 | 是 | 否 |
| `LogicString()` | `509` | 是 | **否** | 是 |
| `ToString()` | `510` | 是 | 是 | 否 |
| `ConfigHash()` | `511` | 否 | 是 | 是 |

- `ConfigString` 细节：词表 = `GetLogicOptions()` 或 `GetOptions()`（`465`），并入 `str` 的 `k:v`（`466`，`onlyLogic` 时跳过 logicless 键）；`UseDifficulty` 时追加 ` bias:{Difficulty}`（`470-473`，`WriteIndexArguments` 时只追加裸数字）；`includeSeed` 时 ` seed:{Seed}`，`Seed2 != 0 && Seed2 != Seed` 再补 ` seed2:{Seed2}`（`474-499`）；`includePreset` 时 ` --preset {Preset}`（`501-504`）。
- `Equals` 用 `ToString()` 字符串相等（`513-516`，注释 `Bad simple implementation for change checking`）。
- **为什么天生有序**：`SortedDictionary`/`SortedSet` ⇒ 同一组选项**无论用户以何顺序输入**都产生同一个串。这是"可分享、可比较、可缓存"的基础，也是 `ConfigHash` 能当稳定标识的前提。

### 2.6 敌人预设：名字→文件，以及 `ToStableString`

- 名字解析：`presets/{name}.txt`（`EnemyPreset.cs:265-269`）；`GetPresetNames` 扫目录、去掉 `README`/`Template`、排序（`173-183`）；`LoadPreset(name, extractOopsAll, checkDir)`（`273-294`）支持 `"Oops All X"` → 读 `"Oops All".txt` 并把 `OopsAll = name.Substring(9)`。
- 保留名/默认名：`InvalidPresetNames = {"CustomItem"}`、`OldDefaultName = "Custom"`、`DefaultName = "CustomEnemy"`、`DefaultFileName = presets\CustomEnemy.txt`（`186-189`）；`SavePreset` 拒绝非法名（`244-255`）。
- 序列化：`ToYamlString()` 走 `GameData.Serializer`（`228-233`）；`CloneConfiguration` 走 YAML 往返（`235-242`）。
- **`ToStableString()`（`308-390`），唯一调用点 `Randomizer.cs:436`**：
  - 目的注释（`310`）：`For basic cross-person comparison, even when order of things is different.`
  - 稳定化算子 `sortUniq`（`316`）：按 `PhraseRe`（`\s*;\s*`，`Util.cs:231`）拆 → `ToLowerInvariant` → `Distinct` → `OrderBy(x, StringComparer.InvariantCulture)`；承载容器 `SortedDictionary<string,string>`。
  - 只写"有内容"的池：非空且 `!= "none"`。
  - 全局键：`OopsAll`（`322-325`）、`RemoveSource`（`326-329`）、`DontRandomize`（`330-333`）、`AdjustSource`（`334-337`，取每个 `.Source`）、`EnemyMultiplier`（`338-341`，>0 才写）。
  - 逐 Class（`342-388`）：跳过 `Scarab` 与 `null`（`347`）；`MergeParent` → `MergeParent=true`（`349-352`）；**`InheritParent` 故意不记录**（`353-358`，注释理由是更要紧地保证 default preset「看起来是 default」）；`NoRandom` → `NoRandom=true`（`359-362`）；非 inherit/merge 时再按需写类级 `EnemyMultiplier`（`363-369`）、`Pools`（`372-379`，小写等于 `default` 时不写）、`RemoveSource`（`380-384`）。
  - 拼装：类内 `"|"` 连 `k=v`（`386`），类间 `"||"`（`389`）。
- **为什么值得抄**：它是**语义等价类**的哈希输入，不是文件内容哈希——"两个人调出来的同一套预设"能对上；而 `InheritParent` 这类"不改变映射语义"的字段被显式排除。我们做"预设是否变了"的判断可以直接搬这一层。

### 2.7 选项文件（`RandomizerOptionsFile`）

- 字段（`14-19`）：`Game` / `Version` / `Options` / `EnemyPreset` / `ItemPreset` / `HelperConfig`（后四个 `[YamlIgnore]`，只作 Create/Load 的中间载体）。
- `Create`（`29-61`）：`Options = opt.FullString()`；`EnemyPreset = preset.ToYamlString()`；`HelperConfig` 先剔除 `;` 开头与空行再逐行换行连接（`36-41` 注释抱怨格式怪异）。
- `Save`（`63-68`）：`SerializerBuilder().DisableAliases()`。
- `Load`（`70-101`）：缺 `Options`/`Game`/`Version` → `Error: missing required field in options file`（`78-81`）；`Game != "ER"` → `Error: unsupported or unknown game "{ret.Game}" in options file`（`82-85`）；`Options` 按空格切再走 `RandomizerOptions.Parse`（`86`）；只有 `customenemy` 或 `Preset` 非空才解析 `EnemyPreset`（`88-91`）；只有 `customitem` 才解析 `ItemPreset`（`92-95`）；非 helper 选项丢弃 `HelperConfig`（`96-99`）。
- **不确定**：代码里**没有 `.rpreset` 扩展名逻辑**（`Load(string path)` 直接交给 YamlDotNet）——扩展名是 GUI 侧约定，缺 form 源码无法核实；GUI"另存预设"是否写这套结构，同样不确定。
- 选项清单的权威注释在 `EnemyPreset.cs:392-404`：`Currently this is the authoritative source of options`。

---

## 3 物品侧位置池：与敌人侧是不是同一抽象

**结论：是同一抽象**——桶 = `{类别 × 区域}`，桶内有 `Sources/Targets/Mapping`，桶间永不互通。物品侧只多一个维度。

### 3.1 三层坐标

| 类型 | 组成 | 出处 |
|---|---|---|
| `LocationScope` | `ScopeType Type + UniqueID + ShopIDs + ModelLots + OnlyShops`；`IDStr = "{Type}:{id:D10}:{shops}:{lots}"`（等值与排序都靠这串）；`OnlyShops` 时 id 归零/-1 → **多个商店折叠成一个位置** | `LocationData.cs:231-271` |
| `ItemLocation` | `Item` + `Locs: List<Location>` + `LocScope` + `DLC` + `Silo = AreaSilo.Default` + `Quantity` | `LocationData.cs:109-146` |
| `LocationSilo` | `{RandomSilo Type, AreaSilo Area, ItemSilo Item}`，`CompareTo` 按 `(Type, Area.Type, Area.Index, Item.Type, Item.Index)` | `Permutation.cs:384-402` |
| 容器 | `ItemLocations : SortedDictionary<LocationScope, ItemLocation>` | `LocationData.cs:94-106` |

### 3.2 `ScopeType` 七种 = "世界上的七类位置"

`Event` / `Entity` / `Material` / `ShopInfinite` / `ShopInfiniteEvent` / `Model` / `Special` / `Asset`（`LocationData.cs:273-293`，每项带含义注释）。

映射到 silo：`canPermuteTo`（`Permutation.cs:354-364`）——`Event/Material/Entity/Special → Finite`；`ShopInfinite → InfiniteShop`；`Model → Infinite`；`ShopInfiniteEvent → Mixed`。注释（`362`）明说有限↔无限成对互通"超级复杂"**没做** → **物品侧自己承认了一个不可通约的边界**。

`RandomSilo` 九种（`331-351`）：`Finite`（事件旗标）/ `Infinite`（模型无限掉落）/ `Mixed`（商店有限+无限成对）/ `Self`（不随机）/ `Remove`（移除）/ `Crow`（资源掉落）/ `InfiniteShop` / `InfiniteGear` / `InfiniteCertain`；`gearSiloVariants`（`366-370`）把 `Infinite`/`InfiniteShop` 映到 `InfiniteGear`；`isGear`（`372-380`）：`Protector` 为真，ER 里 `Weapon` 且 id 不在 `50000000-60000000` 视为箭矢。

### 3.3 桶内的结构

`SiloPermutation`（`Permutation.cs:414-427`）：`Sources` / `PrevTargets` / `Targets` / `ExcludeTargets` / `MainOnlyTargets` / `Mapping: target → List<source>`。

注释（`422`）解释 `MainOnlyTargets`：防止钥匙类物品因**按武器类型分桶**而无处可放——**这正是"桶化"的代价，被显式补偿**。这条值得记：桶化一定会产生"某物品无处可放"，参考实现用一张专用位表兜住，而不是放宽桶边界。

### 3.4 谁填、谁打乱、谁写

- `PermutationWriter`（`PermutationWriter.cs:102` 起）**不决定映射**：先把 hints 打出来（`106-131`，`-- Hints for {hintType}` + `GetLocationHint`，`fullhint` 时再打 `GetLocationDescription`，`silent` 时截断），再按类别收集价格/掉率（`136-207`）。
- `Result`（`95-100`）：`ItemEventFlags: Dictionary<ItemKey,int>` / `SlotEventFlags: Dictionary<ItemLocKey,int>` / `MerchantGiftFlags: Dictionary<int,int>`。
- **职责三分**：`Permutation.Logic` 算映射 → `PermutationWriter` 落 param/EMEVD 并产日志 → `HintMarker`（`Randomizer.cs:502-505`）另写提示标记。

### 3.5 敌人侧并排对比

| 维度 | 物品侧 | 敌人侧 |
|---|---|---|
| 容器 | `ItemLocations: SortedDictionary<LocationScope, ItemLocation>`（`LocationData.cs:94-106`） | `Silos: SortedDictionary<EnemySiloType, EnemySilo>`（`EnemyPermutation.cs:14`） |
| 桶键 | `LocationSilo{Type, Area, Item}`（`Permutation.cs:384-402`） | `EnemySiloType{EnemyClass Type, AreaSilo Area}`（`EnemyPermutation.cs:35-48`） |
| 桶内容 | `SiloPermutation{Sources, PrevTargets, Targets, ExcludeTargets, MainOnlyTargets, Mapping}` | `EnemySilo{Sources, Targets, TempTargets, Mapping, SwapMapping}`（`50-63`） |
| 映射方向 | `Mapping: target → List<source>` | `Mapping: target → source`（一对一；注释 `54` `entity IDs are unique and not collapsed`） |
| 额外机制 | `MainOnlyTargets`（钥匙类专用位） | `TempTargets`（临时 boss）+ `SwapMapping`（换掉某个 helper 的源） |
| 填充点 | `LoadLocations` / `Logic` | `EnemyRandomizer.cs:1523-1567` |
| 阶段不可变 | — | `EnemyState.cs:9-11` `Once a field is set here, it shouldn't be mutated.` |

敌人桶填充的关键判断（`EnemyRandomizer.cs`）：
- `allowSubsilo = overallSilo == AreaSiloType.None && opt["dlc"] && preset != null`（`1522`）
- 桶类型 = `preset.Classes[class].ClassSilo`（`1530-1533`）；DLC 时 `siloType.WithArea(AreaSilo.ForDlc(info.DLC))`（`1534-1537`；`AreaSilo.ForDlc` → `(DLC,1,"dlc")` / `(DLC,0,"base")`，`LocationData.cs:172-182`）
- `perm.GetOrCreateSilo(siloType)`（`1538`）→ **桶只增不减**
- 分支：`forceMap` 直接写 `silo.Mapping[target] = source`（+ `SwapMapping`，`1550`）；`DupeOnly` 只能被 force（`1554-1557`）；`tempBosses` → `TempTargets`（`1558-1562`）；其余 `Targets.Add`（`1566`）
- 源池剔除（`1569-1590`）：被 force 到同 silo 的不再当源 / `RemoveSourceIDs` / `reducepassive` 砍 90% / `AdjustSource` 按比例留

`EnemyMapping`（`EnemyMapping.cs:19-27`）是**映射完成后的只读视图**：`Mapping(source→List<target>)` / `RevMapping(target→source)` / `HelperMapping` / `SwapMapping`，另有 `IsRandomizedTarget`/`IsRandomizedSource`/`GetRandomizedSource`（`33-66`）、`GetBaseTarget`（`69-81`）、`GetHelperTargets`（`83-108`）。**写入端只读这张表，不重算映射**。

### 3.6 这条抽象为什么是"两轮失败"的解药

物品与敌人两侧都遵守同一条纪律：**先把世界枚举成"位置/槽"，再在桶内做映射，最后只把映射写成字节**；桶是"允许互通的边界"，桶外永不互换。我们的两轮失败恰好缺这条边界——写集按 map 猜、映射与写入混在同一段代码里，于是"写入端全报 ok"与"玩家看到一半变了"能同时成立。

---

## 4 GUI 与命令行边界

- 入口只有两条（`EldenRingRandomizer/Program.cs:15-21`）：
  1. `if (CommandRunner.Run(args, FromGame.ER)) return;`
  2. 否则 `Application.Run(new EldenForm(args.Contains("dumpmessages"), args.Contains("loadempty")))` ——**命令行参数只用来开关 GUI 的两个 flag**
- `CommandRunner.Run`（`CommandRunner.cs:10-26`）：DEBUG 下 `MiscSetup.SetWorkingDirectoryForDevelopment()`（`13-15`）；`args` 空 → `false`（`17`）；DEV 构建交给 `DevRunner`（`19-21`）；**发行版直接 `return false`**（`25`）。
  - 注释原文（`23-24`）：`In the future this could look at randomizeopt files. In that case it won't return a boolean, but data needed to initialize the randomizer.`
  - → **发行版没有真 CLI**；选项文件的 `Load` 是给 GUI 用的。
- 逻辑层真正的"接口"是 `Randomizer.Input`（`Randomizer.cs:73-82`）：
  `record Input(RandomizerOptions Options, Action<string> Notify = null, string OutPath = null, EnemyPreset EnemyPreset = null, ItemPreset ItemPreset = null, ExternalItemPreset ExternalItemPreset = null, Messages Messages = null, string GameExe = null, MergedMods ModDirs = null)`
  - 输出 = `Notify(string)` + `Console.WriteLine`（报告正文 `157-170`）；错误 = `throw new Exception(可读英文)`，**没有错误码**
  - 旧签重载（`84-109`）在 game 不匹配时抛 `Mismatched game {type} for options {opt.Game}`
- 进度：`notifyMap(double)` → `saveMapPhase` 百分比（`554-567`）。
- 设置持久化：`SaveOptions(opt.FullString())` / `ReadOptions()`（`RandomizerOptions.cs:520-530`，注释 `setting options from string is a per-game operation`）；另有 `Exe`/`Mod`/`ViewedTabs`/`Locale`/`WindowPosition`/`ExtraDlls`（`533-601`）。
- **GUI 源码不在本检出**：`EldenRingRandomizer/` 下只有 `Program.cs`、`App.config`、`elden.ico`、`EldenRingRandomizer.csproj`、`locations.txt`、`README.md`、`Properties/{Resources,Settings}.*`；只有 21 处 `EldenForm_*` 本地化 key 引用（`Misc/MiscSetup.cs:128,291,375-395`、`Messages.cs:354-356,392`、`Enemy/EnemyPreset.cs:397-408`）→ **UI 布局、预设另存格式、进度条粒度：不确定（缺 form 源码）**。

---

## 5 `UnpackVanillaFiles` 的校验强度

| 级 | 检查什么 | 失败表现 | 出处 |
|---|---|---|---|
| 1 | exe 存在 / `{gameDir}/regulation.bin` / `oo2core_6_win64.dll`；uxm 模式还要 `event/` 目录与 `_backup/eldenring.exe` | `fileRegulationMissingError` / `fileOodleMissingError` / `fileUxmUnpackError`（`Error: Nuxe output is selected, but the game is not unpacked (event subdirectory not found)`）直接拦；`_backup` 缺只是警告 `fileUxmPatchWarning` | `MiscSetup.cs:397-438`（`412-416`、`417-421`、`426-430`、`432-435`） |
| 2 | `Base/files.txt` 里**散文件**的长度 + SHA1 | `Error: {gameFile.FullName} is not compatible with this version of randomizer.` + `Make sure the randomizer version and game version are compatible. If they are, verify integrity of installed files in Steam.` + `(expected {Hash}, got {GetSHA1FileHash(...)})`，**中止** | `GameData.cs:2113-2120`、`2124-2127`、`2132` |
| 3 | 归档内文件只比长度 | **不中止**，只在末尾打印 `Extracted … but at least … files have unexpected contents. This could indicate this version of the randomizer may be incompatible with the installed game version.` + `Mismatched files in Vanilla directory: {...}` | `GameData.cs:2140-2143`、`2150-2157` |
| （Debug only） | Vanilla 已存在且不完整 | `throw Incorrect or incomplete files were found in Vanilla directory!` | `GameData.cs:2090-2103` |

- 为什么第 2、3 级不对称：注释（`2075-2076`）明说对**已存在**的文件不查 SHA1（I/O 太贵），只有首次 copy 进 Vanilla 的散文件才验 SHA1（`2113-2120`）。
- **实际后果**：用 mod 覆盖过 `event/`、`map/` 的玩家能一路跑到最后一行警告才看到"版本不匹配"；而 `regulation.bin` 被换过会当场中止。这解释了社区里"能跑但结果诡异"的常见形态。
- 对 Python 侧的意义：**把"底本版本"做成一次性 explicit 校验**（导入时哈希整份清单成本可接受，因为只做一次，而不是每轮）。

---

## §可迁移性

### ① 可直接照抄的机制

1. **输入 = 只读基线，输出 = 另一棵树**；任何阶段不得把上一轮产物当输入（`GameData.cs:1774-1787` + B 报告）。
2. **清单驱动**：一份 `files.txt` 级别的"我处理哪些文件"权威表，**同时**用于枚举输出清理范围（`2083` → `1333-1337`）。
3. **桶化映射**：`{类别 × 区域}` 作 key 的 `SortedDictionary` 桶 + 桶内 `{Sources,Targets,Mapping}`（`EnemyPermutation.cs:14-63`）；桶只增不减、桶外永不互通。
4. **职责三分**：`Logic`（算映射）/ `Writer`（落字节 + 出日志）/ `Checker`（事后校验）；Writer 绝不重算映射，只读 `EnemyMapping`。
5. **阶段不可变**（`EnemyState.cs:9-11`）：每阶段产物写完即只读，后阶段只读不写。
6. **选项用有序容器 + 语义等价串**（`RandomizerOptions.cs:70-71`、`463-516`）：同一组选项无论输入顺序都产出同一个串 → 可比较、可分享、可做缓存键。
7. **`ToStableString` 的思路**：把"会改变结果的字段"投影成排序去重后的 `k=v|k=v` 串（`EnemyPreset.cs:308-390`），用来区分"真变了"与"只是重排"；并把不改变语义的字段（`InheritParent`）显式排除。
8. **logicless 划分**（`445-450`）：安装/外观类选项排除在逻辑一致性之外（`uxm`/`mergemods`）。
9. **预设是文件、名字是引用**（`presets/{name}.txt`）；保留名/非法名显式拒绝（`EnemyPreset.cs:186-189`、`244-255`）。
10. **输入清单分级校验**：能验的验到底，验不动的（归档内文件）**明确降级成警告**并在末尾汇总，而不是假装通过（`GameData.cs:2135-2157`）。

### ② 照搬不了的部分 + 替代做法

| 参考实现 | 为什么 Python 侧照搬不了 | 替代做法 |
|---|---|---|
| `Editor.LoadNames` / `Editor.LoadParams` / `Editor.OverrideBndRel`（paramdef + BND 写回，`GameData.cs:280`、`1724-1805`、`1177`） | 依赖 SoulsFormats 的完整 paramdef/BND 实现；我们只有 YAFSML 方案层与零散读写 | 保留"有 schema 才写"的**语义**：Python 侧维护 `writable_params` 白名单，不在白名单的表原样拷贝旧字节；白名单来源可以是 YAFSML 已能解析的表 |
| `AppliedParamdef == null ? null : f.Write()` 的隐式判定（`1177`） | 同上 | 用现有 `investigation/apply` 写回路径，但**显式记录"这次实际改了哪几列"**并与白名单比对，不一致就报错（把隐式变显式） |
| WinForms `EldenForm`（不在检出） | 无源码 | 已有 Tk GUI 更可控：把"选项 → 串 → 预设"做成纯数据层（见 ①-6），GUI 只读写 |
| 发行版无 CLI（`CommandRunner.cs:25`） | 参考实现自己也没做 | Python 侧顺手把 `--preset` 做成真 CLI——对我们排障的价值远大于对参考实现 |
| `MergeModManifest`（yml + 千位区间，`MergeModManifest.cs:117-125`、`169-216`） | 我们的目标是"不合并 mod、只验证" | 不必实现合并；可借用"区间列表表达 id 集合"的写法 |
| `submaps.txt` 的坐标阈值判定（`Submaps.cs:118-128`） | 需要 MSB 坐标 | 敌人随机若要按子区域分桶，得先从 map 取坐标；取不到就退化为"按 map 分桶"，但要**在报告里承认粒度更粗** |

### ③ 我们条件更好的地方

1. **有 Python**：能直接生成/校验 `files.txt` 级别的清单、算哈希、对比两轮产物的**字节级差异**；参考实现只能靠 `RuntimeParamChecker` 在游戏内自检。
2. **有 YAFSML 方案层 + `ini Plan=`**：写入层已有"声明改什么"的位置，可以把参考实现的"写集 HashSet"直接表达成 Plan 条目，天然产出"写了哪些文件"的清单。
3. **有 GUI**：可以把 `logiclessOptions` / `GetLogicOptions` / `ConfigHash` 直接显示给用户（"这组选项的短标识 + 哪些选项算逻辑"）；参考实现只能给文本串。
4. **可以做到真 CLI + 可重放**：把 `{seed, LogicString, preset.ToStableString()}` 三件套写成一次随机的完整复现清单（参考实现的 `Equals` 用 `ToString()` 比较，注释自称 `Bad simple implementation`）。
5. **不必继承 Unpack 的分级妥协**：我们可以在**导入时**一次性全量校验底本（含归档内文件哈希），把"版本不匹配"提前到导入那一刻，而不是运行到最后一行警告。
