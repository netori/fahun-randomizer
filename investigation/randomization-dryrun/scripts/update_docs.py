# update_docs.py — 把「说明书护甲全量解析」的结果写进 说明_池子选项.md 与 manifest.json（含对旧结论的更正）
import json, os

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(DRY, "说明_池子选项.md")
MAN = os.path.join(DRY, "manifest.json")

NEW_SECTION = """## 八、局内《职业说明书》= 权威职业专属来源

说明书正文在 `GoodsCaption.fmg`：**8800-8826（护甲 + 卢恩）、8870-8895（武器）**；8850-8866 是卷轴/祷告书，不属于说明书。
**每个职业都有三节**：

| 节 | 内容 | 例（无畏者 entry 8804） |
|---|---|---|
| `XX值得注意的防具套装` | 护甲清单，**每个部件都带获取位置** | 大山羊臂甲 - 帕奇出售 / 大山羊腿甲 - 法洛斯要塞 / 大山羊铠甲 - 击杀“大角”忒拉格斯 / 大山羊头盔 - 法姆·亚兹拉 |
| `以下地点可获得XX法术卢恩` | 卢恩清单（法术职业） | 闪光… / 明亮… / 闪耀… / 辉光… / 幽影… + 地点 |
| `XX值得注意的武器` | 武器清单 | 老将的军旗 - 老将欧尼尔 / 基萨的刺轮 - 火山官邸 … |

**解析结果**（`scripts/parse_guide_full.py`：逐条取「名称 - 地点」行，用四张名称表判定类别）：

| 类别 | 有入口（去重） |
|---|---:|
| 护甲 | **327**（含 65 套完整套装：近战 22 / 法师·祷告混合 18 / 祷告 11 / 法师 9 / 祷告·感应 5） |
| 武器 | **281** |
| 卢恩/道具 | **95** |
| 合计 | **650**（27 职业） |

> **更正**：先前“说明书里护甲只有 7 件、近战职业只写重量偏好”的结论是**错的**。原因是早先脚本按关键词筛条目、且只解析「名称(编号)」格式；说明书正文其实是「名称 - 地点」行，8800-8806 与 8826 的护甲节从未被读到。现已全量重解析。

**三套基础对比**（GUI 顶部第一组单选可切换）：

| 基础 | 物品 | 武器 | 卢恩 | 护甲 | 池 | 置换行 |
|---|---:|---:|---:|---:|---:|---:|
| **guide 说明书（现默认）** | 648 | 236 | 95 | 317 | 91 | 727 |
| mix 说明书 ∪ 推荐表 | 786 | — | — | — | — | — |
| xlsx 推荐表 | 723 | 265 | 99 | 359 | 116 | 775 |

**仍未解析的 15 个名称**（原样保留、不入池）：铁斗笠、熔炉锤型盔、灵火火炬、王室大剑、神兽战士套装、黑夜女巫套装、诺克斯剑士套装、幼年狮子套装、熔炉树套装、神鸟战士套装、黑焰习武修士套装、马雷家套装、老翁套装、塑灵者套装。

"""


def main():
    s = open(DOC, encoding="utf-8").read()
    start, end = s.index("## 八、局内《职业说明书》"), s.index("## 七、文件")
    s = s[:start] + NEW_SECTION + s[end:]
    open(DOC, "w", encoding="utf-8").write(s)
    print("文档已更新：", "更正" in s)

    m = json.load(open(MAN, encoding="utf-8"))
    m["guide_basis"] = {
        "source": "GoodsCaption.fmg 8800-8826（护甲+卢恩）+ 8870-8895（武器）；8850-8866 为卷轴/祷告书",
        "sections_per_class": ["XX值得注意的防具套装（每件带地点）", "以下地点可获得XX法术卢恩", "XX值得注意的武器"],
        "parsed": {"armor_with_entrance": 327, "weapon_with_entrance": 281, "goods_with_entrance": 95, "unique_with_entrance": 650,
                   "complete_sets": {"近战": 22, "法师/祷告混合": 18, "祷告": 11, "法师": 9, "祷告/感应": 5}},
        "bases": {"guide": {"items": 648, "pools": 91, "rows": 727}, "xlsx": {"items": 723, "pools": 116, "rows": 775},
                  "mix": {"items": 786}},
        "correction": "此前'说明书护甲只有 7 件'错误：早先脚本按关键词筛条目且只解析『名称(编号)』格式，漏读 8800-8806/8826 护甲节；正文实为『名称 - 地点』行",
        "unresolved": ["铁斗笠", "熔炉锤型盔", "灵火火炬", "王室大剑", "神兽战士套装", "黑夜女巫套装", "诺克斯剑士套装",
                       "幼年狮子套装", "熔炉树套装", "神鸟战士套装", "黑焰习武修士套装", "马雷家套装", "老翁套装", "塑灵者套装"],
    }
    m["tests"] = {"python_config_matrix": {"runs": 360, "combos": 180, "failures": 0},
                  "js_engine_node": {"runs": 900, "failures": 0},
                  "gui_render_and_selftest": {"runs": 624, "failures": 0},
                  "note": "三套基础（guide/xlsx/mix）；说明书护甲全量解析后重跑"}
    json.dump(m, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("manifest 已更新：armor_with_entrance =", m["guide_basis"]["parsed"]["armor_with_entrance"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
