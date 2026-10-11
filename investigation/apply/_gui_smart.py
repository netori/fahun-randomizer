# _gui_smart.py — ① 混合方式随勾选智能变更 ② 保证至少勾一项
import os, re

P = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "randgui.py")
s = open(P, encoding="utf-8").read()

# ① 勾选框：改为走 _toggle_dom（带"至少一项"保护）
s = s.replace('''        for v, t in ITEMS:
            self.doms[v] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r2, text=t, variable=self.doms[v],
                            command=self._combo_hint).pack(side="left", padx=(0, 12))''',
'''        for v, t in ITEMS:
            self.doms[v] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r2, text=t, variable=self.doms[v],
                            command=lambda k=v: self._toggle_dom(k)).pack(side="left", padx=(0, 12))''')

# ② 下拉框：保存引用，后面要动态改它的选项
s = s.replace('''        cb = ttk.Combobox(r3, textvariable=self.mode, values=[t for _m, t in MODES],
                          state="readonly", width=30)
        cb.pack(side="left", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._combo_hint())''',
'''        self.cb_mode = ttk.Combobox(r3, textvariable=self.mode, values=[t for _m, t in MODES],
                                    state="readonly", width=34)
        self.cb_mode.pack(side="left", padx=(4, 0))
        self.cb_mode.bind("<<ComboboxSelected>>", lambda _e: self._combo_hint())''')

# ③ 新增/替换：智能刷新混合方式 + 说明
s = re.sub(r"    def _combo_hint\(self, \*_a\):.*?self\.lbl_combo\.config\(text=t \+ \"。\"\)\n",
'''    def _picked_doms(self):
        return [d for d in ("rune", "armor", "weapon") if self.doms[d].get()]

    def _toggle_dom(self, key):
        """至少保留一项；勾选变化后智能刷新混合方式"""
        if not self._picked_doms():
            self.doms[key].set(True)                      # 不允许全不勾
            messagebox.showinfo("至少勾一项", "至少要保留一个随机项目。")
        self._refresh_modes()

    def _refresh_modes(self, *_a):
        """混合方式随勾选项目智能变更（下拉里的文字直接写出项目名）"""
        names = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
        doms = self._picked_doms()
        if len(doms) <= 1:
            vals = ["只有一项：在自己范围里随机"]
        else:
            plus = " + ".join(names[d] for d in doms)
            dun = "、".join(names[d] for d in doms)
            vals = [f"全部混合（{plus} 一起混）", f"各自随机（{dun} 各随各的）"]
        old = self.mode.get()
        self.cb_mode.config(values=vals)
        self.mode.set(old if old in vals else vals[0])
        self._combo_hint()

    def _combo_hint(self, *_a):
        """按当前勾选与混合方式，说明会怎么随"""
        names = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
        doms = self._picked_doms()
        if not doms:
            self.lbl_combo.config(text="⚠ 一项都没勾：请至少勾选一个随机项目。")
            return
        sep = "各自" in self.mode.get() or len(doms) <= 1
        picked = "、".join(names[d] for d in doms)
        if sep:
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

# ④ collect：方式判定改成看文字（因为标签会变）
s = s.replace('''        sep = (self.mode.get() == MODES[1][1])''',
              '''        sep = ("各自" in self.mode.get()) or len(doms) <= 1''')

# ⑤ 初始化时刷新一次
s = s.replace('''        self._coh_hint()
        self._combo_hint()''', '''        self._coh_hint()
        self._refresh_modes()''')
s = s.replace('''        self.mode.set(MODES[1][1] if c.get("cross_domain") is False else MODES[0][1])
        self._combo_hint()''',
'''        self._refresh_modes()
        _vals = list(self.cb_mode.cget("values"))
        if len(_vals) > 1:
            self.mode.set(_vals[1] if c.get("cross_domain") is False else _vals[0])
        self._combo_hint()''')

open(P, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  界面已改：智能联动 + 至少一项保护")
