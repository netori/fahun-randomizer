# N网（Nexus Mods）发布页文案 —— 直接复制粘贴用

> 上传入口：<https://www.nexusmods.com/> → 右上头像 → **Upload a mod** → 游戏选 **Elden Ring** →
> 类型选 **Modding Tools / Utilities**（不是 "Gameplay"）→ 上传 `发布包/ConvergenceClassItemRandomizer_v1.0.0.zip`。

---

## 页面字段（Short description 有字数限制，用这一段）

```
法魂职业道具与装备随机器：只换物品、不搬位置。合理度控制"越档幅度 / 越档率 / 掺入比例"，
说明书写了它现在真正的所在地；一键还原。仅支持中文（汉化本体）。
```

English（放 Short description 也行，二选一）：

```
A class-item randomizer for The Convergence: swaps items in place, keeps counts identical,
with a "reasonableness" slider. Chinese version only.
```

---

## 正文（Description）—— 中文

```markdown
# 法魂职业道具和装备随机器 v1.0.0

给「法魂」（The Convergence）用的**物品随机化工具**：把职业说明书里那些道具，
在**合理**的范围内互相对调 —— 让每一周目都得重新找东西、重新搭流派。

## 它做了什么

- **只换物品，不搬位置**：宝箱还是那个宝箱、敌人还是那个敌人，里面的东西换成别处的另一件。
- **以「职业说明书」为准**：只动说明书里那批职业道具；消耗品、材料、剧情道具一律不碰。
- **说明书写得对**：写入时同步改说明书的取得地点（"这件现在在哪拿"），并过了三道审计
  （标签结构 / 文字长度 / 串页）。
- **一键还原**：写入前自动备份，随时点「还原成原始」回到原版。
- **同一种子 = 完全一样的结果**，种子记下来就能复盘、也能发给别人复现。

## 两个核心旋钮

### 1）合理度（0~100%）

它控制的是**允许互换的两个格子离多远**：

| 合理度 | 效果 |
|---|---|
| 100% | 只能同档位互换（最保险） |
| 80% | 相邻两档可互换（默认） |
| 50% | 三档以内可互换 |
| 0% | 等级完全放开 |

**它还会跟着「混合方式」自己变**：有混池时，上面那条总合理度管混池；
"各自随机"时总合理度置灰，卢恩 / 护甲 / 装备三条各管自己那一类（没动过的那几条跟着总合理度走）。
每行末尾实时写着这条设定会造成什么（`相邻两档可互换　跨度 2/4　越档率 ≤20%`）。

### 2）混合方式

- **全部混合**：卢恩 + 护甲 + 装备一起混（宝箱里可能开出别的类别的东西）。
- **两两混**：勾三类时可选"哪两类混、另一类独自"。
- **各自随机**：三类各随各的，绝不跨类别。

（法师 / 祷告倾向的护甲**永远**单独成池 —— 只与同倾向、同部位的护甲互换。）

## 现在换得动了吗？（v1.0.0 修的重点）

修掉了"**法祷护甲与商店货架一件都不换**"的老问题：池键里补回了「部位 / 套装」轴，
实测 835 行里法祷护甲 355/355 全部参与、商店货架 69/69 都会变。
「这次会改什么」里会直接给出换了几个货架、法祷换了几套几件。

## 商店参与范围（先说清，免得误会）

工具只管**说明书里那批职业装备**：商店里在卖的这类装备实测 **69 行**
（法祷护甲 50 / 近战护甲 16 / 武器 2），**这些全部会变**。
商店里其余 1485 行不是职业装备（904 行卖的装备不在说明书里、425 行价格 0/-1 并非在售、
143 行是消耗品/骨灰之类、13 行是职业初始装备表），按设计不动 —— 这是工具的定位，不是"改少了"。

## 安装 / 使用

1. 把 `ConvergenceClassItemRandomizer.exe` 放到 **MOD 根目录**（该目录下应有 `mod\regulation.bin`）——
   也就是你放法魂 mod 的那个文件夹，**不是**游戏根目录。
2. 双击运行。界面「本地文件」会逐项自检；缺哪项会标红并禁用写入，按提示处理即可
   （「指定 MOD 目录…」/「补一份原始备份」）。
3. 选随机项目 → 选混合方式 → 拉合理度 → 生成方案 → 写入游戏。不满意点「还原成原始」。
4. 方案可以存进**方案库**（存在 MOD 目录下的 `plans` 文件夹，重装工具也不会丢），
   详情里能看到这套方案改了哪些东西、写进游戏过几次。

## 要求

- 游戏版本 **1.17.x**（适配中）。
- **法魂（The Convergence）MOD** —— 本工具是它的配套工具，单独用没有意义。
- **仅支持中文版**（法魂汉化本体）：界面、说明书改地点、文件自检都按中文版做的。
  **英文版及其它语言暂不支持** —— 英文玩家玩的是原版 Convergences，物品池与文件结构都不同，
  不是翻译几个字就能用。
- 已知目录布局：`mod\regulation.bin`、`mod\msg\zhocn\item_dlc02.msgbnd.dcx`。

## 安全 / 边界

- 写入前会**自动备份** `regulation.bin` 与说明书；发现文件与预期不符会**中止写入**（原文件一个字节都不改）。
- **不搬位置、不刷物品**：每个格子换走一件、换进一件，总量守恒；套装整组进出、不拆散。
- 本工具**不联网**、不改存档、不动 `regulation.bin` 以外的文件。

## 免责声明

非官方粉丝工具，与 FromSoftware / Bandai Namco / The Convergence 制作组均无隶属关系。
使用前请自行备份存档。因使用本工具造成的任何损失由使用者自负。

## 致谢

- **The Convergence** 制作组（本工具服务的 MOD）。
- 法魂汉化组（中文文本基准）。
- 测试与反馈来自社区玩家。
```

---

## 正文（Description）—— English（简版，放同一页或备用）

```markdown
# Convergence Class Item Randomizer v1.0.0

A companion tool for **The Convergence** (Elden Ring): it swaps the class-specific items inside
chests / drops / shops **in place** — same containers, same enemies, different loot — so every
playthrough makes you re-find your gear and re-build your build.

**Chinese version only** (the tool targets the Chinese-localized Convergence build; item pools and
file layout differ in the English build).

## What it does
- Swaps items **in place**; counts are conserved (one item out, one item in; armor sets stay whole).
- Only touches the class items listed in the in-game guide; consumables / key items are never touched.
- Rewrites the guide's "where to find it" text so the description always tells the truth.
- One-click **restore to vanilla**; automatic backup before every write.
- Same seed ⇒ exactly the same result.

## Two knobs
- **Reasonableness (0–100%)**: how far apart two swappable items may be (100% = same tier only,
  0% = tiers fully open). Per-pool overrides appear automatically depending on the mixing mode,
  and each row shows its quantified effect live.
- **Mixing mode**: all-merged / two-of-three merged / fully separate. Mage-priest armor always stays
  in its own pool.

## Requirements
- Elden Ring **1.17.x**, **The Convergence** mod, **Chinese localization**.
- Known layout: `mod\regulation.bin`, `mod\msg\zhocn\item_dlc02.msgbnd.dcx`.

## Safety
Automatic backup, pre-write verification (aborts instead of writing garbage), offline tool,
never touches saves.

Unofficial fan tool; not affiliated with FromSoftware, Bandai Namco or The Convergence's authors.
```

---

## 上传时还要填的零碎项

| 字段 | 建议 |
|---|---|
| Category | **Modding Tools / Utilities**（别选 Gameplay） |
| Version | `1.0.0`（引擎版本 1.1） |
| Requirements | 无硬依赖；正文里写出"要装 The Convergence + 中文版" |
| Permissions | 建议：**允许转载/整合**（Mod packs: Yes / Other authors: Yes，看你自己意愿；不允许上传到别站收费） |
| Credits | The Convergence 团队、法魂汉化组（写进正文了） |
| Images | 建议放 2~3 张：主界面、合理度表单、方案库详情（`docs/素材/界面改版/` 里有现成的） |
| 语言标记 | 页面语言建议选 **Chinese**；标题可写 "Convergence Class Item Randomizer (中文)" |
