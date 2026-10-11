# _gui_plain.py — 把界面改成"说人话"并加入「合理度 0-100%」滑块
import os, sys

WS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUI = os.path.join(WS, "randgui.py")
s = open(GUI, encoding="utf-8").read()
orig = s[:]

PAIRS = [
    ('ttk.Label(top, text="种子")', 'ttk.Label(top, text="随机种子")'),
    ('ttk.Button(top, text="骰子", width=6, command=self._dice)', 'ttk.Button(top, text="换一个", width=7, command=self._dice)'),
    ('ttk.Label(top, text="候选基础")', 'ttk.Label(top, text="随机范围")'),
    ('(("guide", "职业说明书"), ("xlsx", "推荐表"), ("mix", "两者合并"))',
     '(("guide", "说明书上的物品"), ("xlsx", "推荐表"), ("mix", "两者都算"))'),
    ('ttk.Label(top, text="域")', 'ttk.Label(top, text="随机哪些")'),
    ('ttk.Checkbutton(opt, text="套装整组不拆", variable=self.sets)', 'ttk.Checkbutton(opt, text="套装整套一起换", variable=self.sets)'),
    ('ttk.Checkbutton(opt, text="含商店行", variable=self.shops)', 'ttk.Checkbutton(opt, text="商店也随机", variable=self.shops)'),
    ('ttk.Checkbutton(opt, text="幽影卢恩并入普通池", variable=self.shadow)', 'ttk.Checkbutton(opt, text="幽影卢恩与普通卢恩一起换", variable=self.shadow)'),
    ('ttk.Label(opt, text="随机密度")', 'ttk.Label(opt, text="改动比例")'),
    ('ttk.Checkbutton(opt, text="同步说明书", variable=self.guide)', 'ttk.Checkbutton(opt, text="说明书跟着改", variable=self.guide)'),
    ('ttk.Label(opt, text="联合池")', 'ttk.Label(opt, text="允许跨类互换")'),
    ('ttk.Button(bar, text="生成计划", command=self.generate)', 'ttk.Button(bar, text="① 生成随机方案", command=self.generate)'),
    ('ttk.Button(bar, text="导出 CSV", command=self.export)', 'ttk.Button(bar, text="导出方案表", command=self.export)'),
    ('ttk.Button(bar, text="部署到 MOD", command=self.deploy)', 'ttk.Button(bar, text="② 写入游戏", command=self.deploy)'),
    ('ttk.Button(bar, text="打开 out 目录", command=self.open_out)', 'ttk.Button(bar, text="打开输出文件夹", command=self.open_out)'),
    ('ttk.Button(bar, text="保存配置", command=self.save_cfg)', 'ttk.Button(bar, text="保存设置", command=self.save_cfg)'),
    ('ttk.Button(bar, text="载入配置", command=self.load_cfg)', 'ttk.Button(bar, text="读取设置", command=self.load_cfg)'),
    ('ttk.Button(bar, text="回滚 MOD", command=self.rollback)', 'ttk.Button(bar, text="还原成原始", command=self.rollback)'),
    ('left = ttk.LabelFrame(mid, text="校验 / 统计", padding=6)', 'left = ttk.LabelFrame(mid, text="检查结果", padding=6)'),
    ('right = ttk.LabelFrame(mid, text="置换表（前 300 行）", padding=6)', 'right = ttk.LabelFrame(mid, text="把什么换成了什么（前 300 条）", padding=6)'),
    ('logs = ttk.LabelFrame(self.root, text="日志", padding=6)', 'logs = ttk.LabelFrame(self.root, text="过程记录", padding=6)'),
    ('self.status = tk.StringVar(value="就绪")', 'self.status = tk.StringVar(value="就绪：先点①生成方案，再点②写入游戏")'),
    ('self.checks.heading("k", text="项目"); self.checks.heading("v", text="结果")',
     'self.checks.heading("k", text="检查项"); self.checks.heading("v", text="结果")'),
    ('for c, w, t in (("pool", 150, "池"), ("old", 120, "原物品"), ("new", 120, "新物品"), ("where", 420, "位置")):',
     'for c, w, t in (("pool", 130, "范围"), ("old", 130, "原来是什么"), ("new", 130, "换成了"), ("where", 400, "在哪里")):'),
    ('self.repro.set(f"种子 {seed}：再点一次生成即得到完全相同的结果")',
     'self.repro.set(f"种子 {seed}：同一种子再生成一次，结果完全一样")'),
]
for a, b in PAIRS:
    if a not in s:
        print(f"  ⚠ 未找到：{a[:48]}")
    s = s.replace(a, b, 1)

# 插入「合理度」滑块（放在"改动比例"之前）
anchor = '        ttk.Label(opt, text="改动比例").pack(side="left", padx=(16, 2))'
if anchor in s and "self.coherence" not in s:
    ins = ('        ttk.Label(opt, text="合理度").pack(side="left", padx=(16, 2))\n'
           '        self.coherence = tk.DoubleVar(value=0.8)\n'
           '        self.lbl_coh = ttk.Label(opt, text="80%", width=5)\n'
           '        ttk.Scale(opt, from_=0.0, to=1.0, variable=self.coherence, orient="horizontal", length=150,\n'
           '                  command=lambda v: (self.lbl_coh.config(text=f"{float(v)*100:.0f}%"), self._coh_hint())).pack(side="left")\n'
           '        self.lbl_coh.pack(side="left")\n'
           '        self.lbl_cohtxt = ttk.Label(opt, text="", foreground="#666")\n'
           '        self.lbl_cohtxt.pack(side="left", padx=6)\n' + anchor)
    s = s.replace(anchor, ins, 1)
    # 提示文字方法
    s = s.replace('''    def _dice(self):''',
        '''    def _coh_hint(self, *_a):
        """把 0-100% 翻译成一句人话"""
        c = float(self.coherence.get())
        if c >= 0.95:
            t = "只和同等级、同流派的换（最合理）"
        elif c >= 0.6:
            t = "基本只和同等级、同流派的换"
        elif c >= 0.4:
            t = "偶尔跨等级，但流派不乱"
        elif c >= 0.15:
            t = "等级和流派都可以跨"
        else:
            t = "完全不管等级和流派（只保证部位/大类不乱）"
        self.lbl_cohtxt.config(text=t)

    def _dice(self):''', 1)
    # 初始提示
    s = s.replace('''        self._pump()''', '''        self._pump()''', 1)

# cfg 收集里带上合理度
s = s.replace('''                "seed": int(self.seed.get()), "density": round(float(self.density.get()), 3),''',
              '''                "seed": int(self.seed.get()), "density": round(float(self.density.get()), 3),
                "coherence": round(float(self.coherence.get()), 3),''')
s = s.replace('''        self.density.set(float(c.get("density", 1.0)))''',
              '''        self.density.set(float(c.get("density", 1.0)))
        self.coherence.set(float(c.get("coherence", 0.8)))
        self.lbl_coh.config(text=f"{float(c.get('coherence',0.8))*100:.0f}%")''')
# 生成完刷新提示
s = s.replace('''            self.repro.set(''', '''            self._coh_hint()
            self.repro.set(''')

if s != orig:
    open(GUI, "w", encoding="utf-8").write(s)
    import ast; ast.parse(s)
    print("  界面已改：术语换成人话 + 合理度滑块；语法 OK")
else:
    print("  没有变化（可能已打过补丁）")
