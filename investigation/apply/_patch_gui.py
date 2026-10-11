# _patch_gui.py — 把 randgui.py 接到原生部署管线，并加"更自由的随机选项"
import os, sys

WS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # …\随机mod
GUI = os.path.join(WS, "randgui.py")
s = open(GUI, encoding="utf-8").read()
orig = s[:]

# ① 新控件：随机密度滑块 + 同步说明书
old = '        ttk.Label(opt, text="联合池").pack(side="left", padx=(16, 2))'
new = ('        ttk.Label(opt, text="随机密度").pack(side="left", padx=(16, 2))\n'
       '        self.density = tk.DoubleVar(value=1.0)\n'
       '        self.lbl_den = ttk.Label(opt, text="100%", width=5)\n'
       '        ttk.Scale(opt, from_=0.05, to=1.0, variable=self.density, orient="horizontal", length=110,\n'
       '                  command=lambda v: self.lbl_den.config(text=f"{float(v)*100:.0f}%")).pack(side="left")\n'
       '        self.lbl_den.pack(side="left")\n'
       '        self.guide = tk.BooleanVar(value=True)\n'
       '        ttk.Checkbutton(opt, text="同步说明书", variable=self.guide).pack(side="left", padx=8)\n'
       '        ttk.Label(opt, text="联合池").pack(side="left", padx=(16, 2))')
assert old in s, "① 找不到联合池那一行"
s = s.replace(old, new, 1)

# ② 工具条：配置存取 + 回滚
old = '        ttk.Button(bar, text="打开 out 目录", command=self.open_out).pack(side="left", padx=6)'
new = ('        ttk.Button(bar, text="打开 out 目录", command=self.open_out).pack(side="left", padx=6)\n'
       '        ttk.Button(bar, text="保存配置", command=self.save_cfg).pack(side="left", padx=6)\n'
       '        ttk.Button(bar, text="载入配置", command=self.load_cfg).pack(side="left", padx=6)\n'
       '        ttk.Button(bar, text="回滚 MOD", command=self.rollback).pack(side="left", padx=6)')
assert old in s, "② 找不到打开 out 目录那一行"
s = s.replace(old, new, 1)

# ③ cfg 收集：密度 + 说明书同步
old = ('                "merge_shadow": self.shadow.get(), "sets": self.sets.get(),\n'
       '                "seed": int(self.seed.get())}')
new = ('                "merge_shadow": self.shadow.get(), "sets": self.sets.get(),\n'
       '                "seed": int(self.seed.get()), "density": round(float(self.density.get()), 3),\n'
       '                "sync_guide": bool(self.guide.get())}')
assert old in s, "③ 找不到 cfg 收集"
s = s.replace(old, new, 1)

# ④ 部署改走原生管线 + 新增三个方法
old = '''        self.export()
        script = os.path.join(WORKSPACE, "investigation", "apply", "pipeline_deploy.py")
        plan = os.path.join(WORKSPACE, "investigation", "apply", "out", f"plan_seed{self.cfg['seed']}.csv")
        self.log(f"部署中：{script}")
        threading.Thread(target=self._deploy_worker, args=(script, plan), daemon=True).start()

    def _deploy_worker(self, script, plan):
        try:
            p = subprocess.Popen([sys.executable, script, "--plan", plan, "--lang", "zh", "--yes"],
                                 cwd=os.path.dirname(script), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                self.log(line.rstrip())
            self.log(f"部署结束，退出码 {p.wait()}")
        except Exception as e:
            self.log("部署出错：" + str(e))'''
new = '''        self.export()
        plan = os.path.join(WORKSPACE, "investigation", "apply", "out", f"plan_seed{self.cfg['seed']}.csv")
        sync = bool(self.cfg.get("sync_guide", True))
        self.log(f"部署中（原生管线，{'含说明书同步' if sync else '不改说明书'}）：{plan}")
        self.q.put(("status", "部署中…"))
        threading.Thread(target=self._deploy_worker, args=(plan, sync), daemon=True).start()

    def _deploy_worker(self, plan, sync_guide):
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import native_deploy
            rec = native_deploy.deploy(plan, sync_guide=sync_guide, log=self.log)
            self.log("部署完成 ✓ " + str(rec.get("verify")))
            self.q.put(("status", "部署完成"))
        except Exception as e:
            import traceback
            self.log("部署出错：" + traceback.format_exc(limit=4))
            self.q.put(("status", f"部署失败：{e}"))

    def save_cfg(self):
        import json
        from tkinter import filedialog
        if not self.cfg:
            messagebox.showinfo("还没生成", "先生成一次计划，再保存配置。")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                         initialfile=f"cfg_seed{self.cfg['seed']}.json")
        if p:
            json.dump(self.cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            self.log(f"配置已保存 → {p}")

    def load_cfg(self):
        import json
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=[("配置", "*.json")])
        if not p:
            return
        c = json.load(open(p, encoding="utf-8"))
        self.seed.set(str(c.get("seed", self.seed.get())))
        self.basis.set(c.get("basis", "guide"))
        self.shops.set(c.get("shops", True)); self.sets.set(c.get("sets", True))
        self.shadow.set(c.get("merge_shadow", False))
        self.density.set(float(c.get("density", 1.0)))
        self.lbl_den.config(text=f"{float(c.get('density',1.0))*100:.0f}%")
        self.guide.set(c.get("sync_guide", True))
        for d, v in self.doms.items():
            v.set(d in (c.get("domains") or []))
        for g, v in self.joins.items():
            v.set([x for x in g.split(",")] in (c.get("joins") or []))
        self.log(f"已载入配置：{os.path.basename(p)}（点【生成计划】生效）")

    def rollback(self):
        if not messagebox.askyesno("回滚 MOD", "把 regulation.bin 与说明书恢复成原始版（干净状态）？"):
            return
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import shutil
            import native_deploy
            reg = os.path.join(native_deploy.MOD, "mod", "regulation.bin")
            msg = os.path.join(native_deploy.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
            shutil.copy2(native_deploy.find_original("regulation.bin.orig_*"), reg)
            shutil.copy2(native_deploy.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), msg)
            self.log("已回滚到原始版 ✓")
            self.q.put(("status", "已回滚"))
        except Exception as e:
            self.log("回滚出错：" + str(e))'''
assert old in s, "④ 找不到部署段"
s = s.replace(old, new, 1)

if s == orig:
    print("没有变化（可能已经打过补丁）")
else:
    open(GUI, "w", encoding="utf-8").write(s)
    print("randgui.py 已更新：密度滑块 / 同步说明书 / 保存·载入配置 / 回滚 MOD / 原生部署")

import ast
ast.parse(open(GUI, encoding="utf-8").read())
print("语法 OK")
