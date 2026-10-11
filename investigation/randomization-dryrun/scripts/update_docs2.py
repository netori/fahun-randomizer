# update_docs2.py — 把「说明书全量解析 + 部位码 bug 修复 + 推荐表交叉核对」的最终数字写进文档与 manifest
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

**解析结果**（`scripts/parse_guide_full.py`）：

| 类别 | 有入口（去重） |
|---|---:|
| 护甲 | **343**（27 职业合计 66 套完整套装：近战 23 / 法师·祷告混合 18 / 祷告 11 / 法师 9 / 祷告·感应 5） |
| 武器 | **284** |
| 卢恩/道具 | **95** |
| 合计 | **673** |

**两处关键修正（都在这一轮发现）**：

1. **部位尾号解析**：这个 MOD 的护甲 id 有 **6/7/8 三种长度**（`872000`、`5253000`、`5230100`），部位码是**末 3 位**（000 头 / 100 身 / 200 臂 / 300 腿），此前只按末 4 位判断 → **7 位 id 的护甲（神鸟/神兽/熔炉/塑灵者/玛雷家/黑夜女巫等 DLC 套装）被引擎整批跳过**。现已统一为 `part_code_of()`。
2. **名称解析**：说明书正文不是「名称(编号)」而是「名称 - 地点」，早先脚本因此只捞到 7 件防具。

**15 个疑难名称 → 推荐表交叉核对**（`scripts/crosscheck_rec_table.py`，同名 + 同地点证据）：

| 说明书名 | 推荐表证据 | 结论 |
|---|---|---|
| 铁斗笠 | 推荐表「铁笠帽」地点＝夏玻利利（与说明书同一事件） | → `铁笠帽` 150000 |
| 熔炉锤型盔 | 推荐表「熔炉槌形盔」地点＝熔炉骑士泥盆亚掉落（同地点） | → `熔炉槌形盔` 5310000 |
| 灵火火炬 | 推荐表「灵火火把」＝利耶尼亚死之鸟掉落（同地点） | → `灵火火把` 24050000 |
| 猎犬钩爪 | 推荐表「猎犬弯爪」地点＝火山官邸-猎犬骑士（同地点） | → `猎犬弯爪` 22020000 |
| 王室大剑 | 推荐表「王室大剑」（冰霜巫师）地点＝三姊妹塔击败布莱泽 | → `王室巨剑` 4060000（**推断**） |
| 马雷家/幼年狮子/神鸟战士/神兽战士/老翁/熔炉树/黑焰习武修士/黑夜女巫/诺克斯剑士/塑灵者 套装 | 推荐表同名、地点与说明书吻合 | → 按 MOD 命名前缀展开成整组 |

*（黑夜女巫套装＝`黑夜女巫双生冠/铠甲/手环/腿甲`；诺克斯剑士套装＝`292000/292100`(+轻装)；熔炉树套装＝`熔炉树形盔/铠`；老翁套装＝`老翁面具`；塑灵者套装＝`塑灵者鹿角/披风/腕带/长裤`；玛雷家套装＝`玛雷家面具/长袍…`）*

**唯一仍未定**：`黑夜套装 - 波尼监牢`（诺克斯神谕官）。按地点查，波尼监牢里唯一的防具是 **咒剑士面具 `5210000`**，疑似＝咒剑士套装，但**不敢直接认**，保留为未解析。

**三套基础对比**（GUI 顶部第一组单选可切换）：

| 基础 | 物品 | 池 | 置换行 |
|---|---:|---:|---:|
| **guide 说明书（现默认）** | 671 | 89 | 762 |
| xlsx 推荐表 | 723 | 116 | 775 |
| mix 说明书 ∪ 推荐表 | 786 | — | — |

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
        "parsed": {"armor_with_entrance": 343, "weapon_with_entrance": 284, "goods_with_entrance": 95, "unique_with_entrance": 673,
                   "complete_sets": {"近战": 23, "法师/祷告混合": 18, "祷告": 11, "法师": 9, "祷告/感应": 5}},
        "bases": {"guide": {"items": 671, "pools": 89, "rows": 762}, "xlsx": {"items": 723, "pools": 116, "rows": 775},
                  "mix": {"items": 786}},
        "bugs_fixed": ["部位码按末 3 位（MOD 护甲 id 有 6/7/8 位；此前 7 位 id 的 DLC 套装被整批跳过）",
                       "说明书正文为『名称 - 地点』行，早先脚本按『名称(编号)』解析导致只捞到 7 件防具",
                       "测试脚本 test_engine.js 仍在用旧的末 4 位判断（已改 partCodeOf）"],
        "crosscheck_rec_table": {"script": "scripts/crosscheck_rec_table.py", "evidence": "evidence/rec_table_crosscheck.json",
                                 "resolved": 14, "unresolved": ["黑夜套装（波尼监牢；该处唯一防具＝咒剑士面具 5210000，疑似咒剑士套装，未认）"]},
    }
    m["tests"] = {"python_config_matrix": {"runs": 360, "combos": 180, "failures": 0},
                  "js_engine_node": {"runs": 900, "failures": 0},
                  "gui_render_and_selftest": {"runs": 624, "failures": 0},
                  "note": "三套基础（guide/xlsx/mix）；部位码修复 + 交叉核对后重跑"}
    json.dump(m, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("manifest 已更新：", m["guide_basis"]["parsed"]["unique_with_entrance"], "条权威条目")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
