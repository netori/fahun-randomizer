# _patch_gui_joins.py — GUI：三项目时提供"两两混 + 一个独自"的三个选项，并翻译成 joins
import ast, os

WS = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(WS, "randgui.py")
s = open(P, encoding="utf-8").read()
before = s

# ① 下拉项：三项目时加三个"两两混、一个独自"
old1 = '''        if len(doms) <= 1:
            vals = ["只有一项：在自己范围里随机"]
        else:
            plus = " + ".join(names[d] for d in doms)
            dun = "、".join(names[d] for d in doms)
            vals = [f"全部混合（{plus} 一起混）", f"各自随机（{dun} 各随各的）"]'''
new1 = '''        if len(doms) <= 1:
            vals = ["只有一项：在自己范围里随机"]
        else:
            plus = " + ".join(names[d] for d in doms)
            dun = "、".join(names[d] for d in doms)
            vals = [f"全部混合（{plus} 一起混）"]
            if len(doms) == 3:
                a, b, c = doms
                vals += [f"{names[a]}+{names[b]} 混 · {names[c]} 独自",
                         f"{names[a]}+{names[c]} 混 · {names[b]} 独自",
                         f"{names[b]}+{names[c]} 混 · {names[a]} 独自"]
            vals.append(f"各自随机（{dun} 各随各的）")'''
assert old1 in s, "① 找不到下拉项构造"
s = s.replace(old1, new1, 1)

# ② _collect：把选中的模式翻译成 joins / cross_domain
old2 = '''        sep = ("各自" in self.mode.get()) or len(doms) <= 1'''
new2 = '''        sep = ("各自" in self.mode.get()) or len(doms) <= 1
        joins = []
        if not sep and len(doms) == 3 and "·" in self.mode.get():
            # "A+B 混 · C 独自" → joins=[[A,B]]
            left = self.mode.get().split("混 ·")[0]
            pair = [d for d in doms if names_for_join[d] in left]
            if len(pair) == 2:
                joins = [pair]'''
assert old2 in s, "② 找不到 _collect 判定"
s = s.replace(old2, new2, 1)

# ③ cross_domain 只在"全部混合"时为真
old3 = '''                "cross_domain": (not sep),           # “各自随机”= 不建混池'''
new3 = '''                "joins": joins,                      # 两两混：只给这一组建混池
                "cross_domain": (not sep) and not joins,   # 全部混合=建混池；两两混/各自=不建'''
assert old3 in s, "③ 找不到 cross_domain"
s = s.replace(old3, new3, 1)

# ④ 模块级：模式文字 → 域码 的对照表（供 ② 使用）
if "names_for_join" not in s.split("def _refresh_modes")[0]:
    s = s.replace("MODES = [",
                  'names_for_join = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}\n\nMODES = [', 1)
    # 把 _refresh_modes 里的局部 names 改成引用同一个表，避免两处定义漂移
    s = s.replace('        names = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}\n', '')

ast.parse(s)
open(P, "w", encoding="utf-8").write(s)
print(f"  ✓ 已写入（{len(before)} → {len(s)} 字符）")
print(f"  核对: 两两混选项 {'有' if '独自' in s else '无'} ｜ joins {'有' if '\"joins\": joins' in s else '无'}")
