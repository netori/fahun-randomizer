# _gui_items.py — 界面：随机项目（勾选）+ 混合方式（下拉），两者正交、组合天然兼容
import os, re

P = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "randgui.py")
s = open(P, encoding="utf-8").read()

# ① 组合表 → 两种“混合方式”
s = re.sub(r"COMBOS = \[.*?COMBO_LABEL = \{[^\n]*\}\n",
'''MODES = [("mix", "全部混合（勾选的几类一起混）"),
         ("sep", "各自随机（勾选的几类各随各的）")]
ITEMS = [("rune", "卢恩"), ("armor", "护甲"), ("weapon", "装备（武器）")]
''', s, flags=re.S)

# ② 界面：把“要随机的”下拉框换成 勾选框 + 混合方式下拉
s = s.replace('''        r2 = ttk.Frame(s1); r2.pack(fill="x")
        ttk.Label(r2, text="要随机的：").pack(side="left")
        self.combo = tk.StringVar(value=COMBOS[0][2])
        cb = ttk.Combobox(r2, textvariable=self.combo, values=[t for _d, _s, t in COMBOS],
                          state="readonly", width=34)
        cb.pack(side="left", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._combo_hint())
''', '''        r2 = ttk.Frame(s1); r2.pack(fill="x")
        ttk.Label(r2, text="随机项目：").pack(side="left")
        self.doms = {}
        for v, t in ITEMS:
            self.doms[v] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r2, text=t, variable=self.doms[v],
                            command=self._combo_hint).pack(side="left", padx=(0, 12))
        r3 = ttk.Frame(s1); r3.pack(fill="x", pady=(6, 0))
        ttk.Label(r3, text="混合方式：").pack(side="left")
        self.mode = tk.StringVar(value=MODES[0][1])
        cb = ttk.Combobox(r3, textvariable=self.mode, values=[t for _m, t in MODES],
                          state="readonly", width=30)
        cb.pack(side="left", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._combo_hint())
''')

# ③ 说明文字随“勾选 + 方式”变化
s = re.sub(r"    def _combo_hint\(self, \*_a\):.*?self\.lbl_combo\.config\(text=t \+ \"。\"\)\n",
'''    def _combo_hint(self, *_a):
        """按当前勾选与混合方式，说明会怎么随"""
        doms = [d for d, v in self.doms.items() if v.get()]
        names = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
        if not doms:
            self.lbl_combo.config(text="⚠ 一项都没勾：请至少勾选一个随机项目。")
            return
        sep = (self.mode.get() == MODES[1][1])
        picked = "、".join(names[d] for d in ("rune", "armor", "weapon") if d in doms)
        if sep or len(doms) == 1:
            extra = "（法师/祷告的护甲仍然单独一组）" if "armor" in doms else ""
            self.lbl_combo.config(text=f"{picked} 各自在自己的范围里换，互不混合{extra}。")
            return
        if "rune" in doms and "armor" in doms:
            t = f"{picked} 会互相换（法师/祷告的护甲除外，它们永远单独一组）"
        else:
            t = f"{picked} 会互相换"
        if "weapon" in doms and len(doms) > 1:
            t += "；装备是不是掺进来由下面的“合理度”决定"
        self.lbl_combo.config(text=t + "。")
''', s, flags=re.S)

# ④ collect
s = s.replace('''        doms, sep = COMBO_BY_LABEL.get(self.combo.get(), (("rune", "armor", "weapon"), False))
        doms = list(doms)''',
'''        doms = [d for d, v in self.doms.items() if v.get()]
        sep = (self.mode.get() == MODES[1][1])''')

# ⑤ load_cfg
s = re.sub(r"        _d = \[x for x in \(\"rune\", \"armor\", \"weapon\"\) if x in \(c\.get\(\"domains\"\) or \[\]\)\]\n"
           r"        _sep = \(c\.get\(\"cross_domain\"\) is False\)\n"
           r"        _k = \", \"\.join\(_d\) \+ \(\"\|sep\" if _sep else \"\"\)\n"
           r"        self\.combo\.set\(COMBO_LABEL\.get\(_k, COMBOS\[0\]\[2\]\)\)\n",
'''        _d = c.get("domains") or ["rune", "armor", "weapon"]
        for k, v in self.doms.items():
            v.set(k in _d)
        self.mode.set(MODES[1][1] if c.get("cross_domain") is False else MODES[0][1])
''', s)

# ⑥ 生成前的兼容性检查
s = s.replace('''        if not WORKSPACE:
            messagebox.showerror("找不到游戏目录", "请把本程序放到 随机mod 目录（或其子目录）下再运行。")
            return''',
'''        if not WORKSPACE:
            messagebox.showerror("找不到游戏目录", "请把本程序放到 随机mod 目录（或其子目录）下再运行。")
            return
        if not [d for d, v in self.doms.items() if v.get()]:
            messagebox.showinfo("还没选随机项目", "请至少勾选一个随机项目（卢恩 / 护甲 / 装备）。")
            return''')

open(P, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  界面已改：随机项目（勾选）+ 混合方式（下拉）")
