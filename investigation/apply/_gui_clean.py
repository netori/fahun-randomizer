# _gui_clean.py — 去掉多余的说明性文字（副标题、括号解释、种子说明等），只留控件与必要信息
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "randgui.py")
s = open(P, encoding="utf-8").read()

# ① 去掉副标题
s = s.replace('''        ttk.Label(head, text="法魂物品随机器", font=big).pack(side="left")
        ttk.Label(head, text="只换物品、不搬位置；不满意随时一键还原", font=hint,
                  foreground="#777").pack(side="left", padx=12)''',
'''        ttk.Label(head, text="法魂物品随机器", font=big).pack(side="left")''')

# ② 第 1 步标题去掉括号解释
s = s.replace('''        s1 = ttk.LabelFrame(body, text=" 第 1 步 · 要随机哪些东西（只动职业说明书里列到的物品） ", padding=(12, 8))''',
              '''        s1 = ttk.LabelFrame(body, text=" 第 1 步 · 随机项目 ", padding=(12, 8))''')

# ③ 第 2 步标题与刻度说明
s = s.replace('''        s2 = ttk.LabelFrame(body, text=" 第 2 步 · 随机得多合理 ", padding=(12, 8))''',
              '''        s2 = ttk.LabelFrame(body, text=" 第 2 步 · 合理度 ", padding=(12, 8))''')
s = s.replace('''        ttk.Label(r4, text="100% = 只和同等级换；0% = 随心配", font=hint, foreground="#777").pack(side="left")''',
              '''        ttk.Label(r4, text="100%  同等级互换      0%  等级完全放开", font=hint, foreground="#777").pack(side="left")''')

# ④ 第 3 步标题与种子行说明
s = s.replace('''        s3 = ttk.LabelFrame(body, text=" 第 3 步 · 随机种子（同一种子 = 完全一样的结果） ", padding=(12, 8))''',
              '''        s3 = ttk.LabelFrame(body, text=" 第 3 步 · 随机种子 ", padding=(12, 8))''')
s = s.replace('''        ttk.Button(r5, text="换一个", width=8, command=self._dice).pack(side="left", padx=8)
        ttk.Label(r5, text="记下这个数字，下次填一样的就能得到完全一样的随机。", font=hint,
                  foreground="#777").pack(side="left", padx=8)''',
'''        ttk.Button(r5, text="换一个", width=8, command=self._dice).pack(side="left", padx=8)''')

# ⑤ 更多设置里的口语说明
s = s.replace('''        ttk.Label(a2, text="调小就少改一些（只想换个口味时用）", font=hint, foreground="#777").pack(side="left", padx=8)
''', '')

# ⑥ 滑块下方那句人话 → 精简为参数化描述
s = s.replace('''        if c >= 0.95:
            t = "东西基本只和同等级的换；武器自己玩，不掺进混池。"
        elif c >= 0.6:
            t = "偶尔会换到相邻的等级；开始有少量武器掺进来。"
        elif c >= 0.4:
            t = "等级会混得更多；大约三分之一的武器掺进来。"
        elif c >= 0.15:
            t = "跨档很宽；大约一半的武器掺进来。"
        else:
            t = "高低等级随便配；最多六成多的武器掺进来。"
        wsel = int(round((1 - c) * 66))
        self.lbl_cohtxt.config(text=f"{t}（武器最多掺进混池约 {wsel}%）")''',
'''        steps = int(round((1 - c) * 4))
        lvl = {0: "跨 0 档", 1: "跨 1 档", 2: "跨 2 档", 3: "跨 3 档", 4: "跨 4 档"}[steps]
        wsel = int(round((1 - c) * 66))
        self.lbl_cohtxt.config(text=f"{lvl}　武器掺入上限 {wsel}%")''')

# ⑦ 混合方式说明 → 短句
s = s.replace('''        if sep:
            extra = "（法师/祷告的护甲仍然单独一组）" if "armor" in doms else ""
            self.lbl_combo.config(text=f"{picked} 各自在自己的范围里换，互不混合{extra}。")
            return
        if "rune" in doms and "armor" in doms:
            t = f"{picked} 会互相换（法师/祷告的护甲除外，它们永远单独一组）"
        else:
            t = f"{picked} 会互相换"
        if "weapon" in doms and len(doms) > 1:
            t += "；装备是不是掺进来由下面的“合理度”决定"
        self.lbl_combo.config(text=t + "。")''',
'''        extra = "　法师/祷告护甲始终单独一组" if "armor" in doms else ""
        if sep:
            self.lbl_combo.config(text=f"{picked}：各自随机{extra}")
            return
        self.lbl_combo.config(text=f"{picked}：互相混合{extra}")''')

open(P, "w", encoding="utf-8").write(s)
import ast
ast.parse(s)
print("  已清理多余说明文字")
