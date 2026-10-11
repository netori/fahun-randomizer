# update_docs3.py — 收尾：说明书解析「未解析归零」+ 黑夜套装更正 + 最终数字
import json, os

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(DRY, "说明_池子选项.md")
MAN = os.path.join(DRY, "manifest.json")

SECTION = """## 八、局内《职业说明书》= 权威职业专属来源

说明书正文在 `GoodsCaption.fmg`：**8800-8826（护甲 + 卢恩）、8870-8895（武器）**；8850-8866 是卷轴/祷告书，不属于说明书。
**每个职业都有三节**，正文是「名称 - 地点」一行一件：

| 节 | 内容 | 例（无畏者 entry 8804） |
|---|---|---|
| `XX值得注意的防具套装` | 护甲清单，**每个部件都带获取位置** | 大山羊臂甲 - 帕奇出售 / 大山羊腿甲 - 法洛斯要塞 / 大山羊铠甲 - 击杀“大角”忒拉格斯 / 大山羊头盔 - 法姆·亚兹拉 |
| `以下地点可获得XX法术卢恩` | 卢恩清单（法术职业） | 闪光… / 明亮… / 闪耀… / 辉光… / 幽影… + 地点 |
| `XX值得注意的武器` | 武器清单 | 老将的军旗 - 老将欧尼尔 / 基萨的刺轮 - 火山官邸 … |

**解析结果**（`scripts/parse_guide_full.py`，**未解析 = 0**）：

| 类别 | 有入口（去重） |
|---|---:|
| 护甲 | **353**（76 套完整套装：近战 23 / 法师·祷告混合 23 / 祷告 12 / 法师 9 / 祷告·感应 8 / 感应 1） |
| 武器 | **284** |
| 卢恩/道具 | **95** |
| 合计 | **683** |

### 套装名怎么展开（关键规则）

正文里的「拉塔恩套装」「黑夜套装」是**套装名**，MOD 里没有同名物品，只有件名。规则：

1. 用「基名 + 部位词」的信号定位 **id 家族** —— 例：`黑夜套装` → 找到件名恰好是 **黑夜头盔/黑夜铠甲/黑夜臂甲/黑夜腿甲** 的家族 `5090`；
2. 取**该家族全部件**（不看件名是否规整）—— 这样 `黑夜女巫套装` 的 **双生冠 / 手环** 也不会漏；
3. 件名不规整时退化为「前缀命中 ≤12 件」。

**更正**：上一轮我把 `黑夜套装 - 波尼监牢` 猜成 `咒剑士面具 5210000`（只因两者箱子号相邻），是**错的**。MOD 里确实有独立的一套：`5090000 黑夜头盔 / 5090100 黑夜铠甲 / 5090200 黑夜臂甲 / 5090300 黑夜腿甲`（`Helm/Armor/Gauntlets/Greaves of Night`，`ItemLotParam_map:41010300~0303`）。现在它按家族正确展开。

### 两处早先的 bug（都已修）

1. **部位尾号**：护甲 id 有 **6/7/8 三种长度**（`872000`、`5253000`、`5230100`），部位码是**末 3 位**；此前只按末 4 位判断 → **7 位 id 的护甲（神鸟/神兽/熔炉/塑灵者/玛雷家/黑夜女巫 等 DLC 套装）被引擎整批跳过**。现统一为 `part_code_of()`。
2. **正文格式**：说明书是「名称 - 地点」，早先脚本按「名称(编号)」解析，只捞到 7 件防具。

### 三套基础对比（GUI 顶部第一组单选可切换）

| 基础 | 物品 | 池 | 置换行 |
|---|---:|---:|---:|
| **guide 说明书（现默认）** | 681 | 84 | 777 |
| xlsx 推荐表 | 723 | 116 | 775 |
| mix 说明书 ∪ 推荐表 | 800 | — | — |

"""


def main():
    s = open(DOC, encoding="utf-8").read()
    start, end = s.index("## 八、局内《职业说明书》"), s.index("## 七、文件")
    s = s[:start] + SECTION + s[end:]
    open(DOC, "w", encoding="utf-8").write(s)
    print("文档第八节已重写")

    m = json.load(open(MAN, encoding="utf-8"))
    m["guide_basis"] = {
        "source": "GoodsCaption.fmg 8800-8826（护甲+卢恩）+ 8870-8895（武器）；8850-8866 为卷轴/祷告书",
        "sections_per_class": ["XX值得注意的防具套装（每件带地点）", "以下地点可获得XX法术卢恩", "XX值得注意的武器"],
        "parsed": {"armor_with_entrance": 353, "weapon_with_entrance": 284, "goods_with_entrance": 95,
                   "unique_with_entrance": 683, "unresolved_names": 0,
                   "complete_sets": {"近战": 23, "法师/祷告混合": 23, "祷告": 12, "法师": 9, "祷告/感应": 8, "感应": 1}},
        "set_expansion_rule": "套装名 → 用『基名+部位词』定位 id 家族 → 取该家族全部件（黑夜套装→黑夜头盔/铠甲/臂甲/腿甲 5090000-5090300）",
        "bases": {"guide": {"items": 681, "pools": 84, "rows": 777}, "xlsx": {"items": 723, "pools": 116, "rows": 775},
                  "mix": {"items": 800}},
        "bugs_fixed": ["部位码按末 3 位（护甲 id 有 6/7/8 位；此前 7 位 id 的 DLC 套装被整批跳过）",
                       "说明书正文为『名称 - 地点』行，早先按『名称(编号)』解析只捞到 7 件防具",
                       "套装名展开改为 id 家族（黑/黑夜女巫等非规整件名不再漏）",
                       "测试脚本 test_engine.js 仍在用旧末 4 位判断（已改 partCodeOf）"],
        "corrections": ["『说明书护甲只有 7 件』— 错（漏读 8800-8806/8826 护甲节）",
                        "『黑夜套装 = 咒剑士面具』— 错（MOD 里确有独立黑夜套装 5090000-5090300）"],
    }
    m["tests"] = {"python_config_matrix": {"runs": 360, "combos": 180, "failures": 0},
                  "js_engine_node": {"runs": 900, "failures": 0},
                  "gui_render_and_selftest": {"runs": 624, "failures": 0},
                  "note": "三套基础（guide/xlsx/mix）；说明书未解析归零后重跑"}
    json.dump(m, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("manifest 已更新：", m["guide_basis"]["parsed"]["unique_with_entrance"], "条权威条目，未解析",
          m["guide_basis"]["parsed"]["unresolved_names"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
