# _patch_envcheck.py — 给 GUI 加「本地文件识别」：找 MOD 目录 + 逐项检查必需文件
import ast, os

WS = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(WS, "randgui.py")
s = open(P, encoding="utf-8").read()
before = s

# ── ① 模块级：环境探测 ──
BLOCK = '''

# ── 本地文件识别 ───────────────────────────────────────────────
#   必需项（缺了就没法正确写入/还原）：原始备份、游戏内的 regulation 与说明书
def _looks_like_mod(d):
    return os.path.isfile(os.path.join(d, "mod", "regulation.bin"))


def find_mod_root(start=None):
    """在若干候选目录里找 MOD 根目录（含 mod/regulation.bin）"""
    cands = []
    for base in [start, HERE, os.getcwd(), WORKSPACE,
                 os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]:
        if not base:
            continue
        cur = os.path.abspath(base)
        for _ in range(4):
            cands.append(cur)
            nxt = os.path.dirname(cur)
            if nxt == cur:
                break
            cur = nxt
    # 同级目录里带“法魂/COVERAGE”字样的也试一下
    try:
        parent = os.path.dirname(os.path.abspath(HERE))
        for name in os.listdir(parent):
            p = os.path.join(parent, name)
            if os.path.isdir(p):
                cands.append(p)
    except OSError:
        pass
    seen = set()
    for c in cands:
        c = os.path.abspath(c)
        if c in seen:
            continue
        seen.add(c)
        if _looks_like_mod(c):
            return c
    return None


def check_env(mod_root=None, apply_dir=None):
    """逐项检查本地必需文件。返回 [(项目, 状态, 说明, 路径)]"""
    root = mod_root or find_mod_root()
    ap = apply_dir or (os.path.join(WORKSPACE, "investigation", "apply") if WORKSPACE else None)
    rows = []

    def add(name, ok, note, path=""):
        rows.append((name, bool(ok), note, path))

    add("MOD 根目录", bool(root), "含 mod/regulation.bin" if root else "没找到（可手动指定）", root or "")
    if root:
        reg = os.path.join(root, "mod", "regulation.bin")
        msg = os.path.join(root, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
        add("游戏物品数据", os.path.isfile(reg), "regulation.bin", reg)
        add("游戏说明书", os.path.isfile(msg), "item_dlc02.msgbnd.dcx", msg)
        add("目录可写", os.access(root, os.W_OK), "写入前会自动备份", root)
    else:
        add("游戏物品数据", False, "需先指定 MOD 目录", "")
        add("游戏说明书", False, "需先指定 MOD 目录", "")
        add("目录可写", False, "需先指定 MOD 目录", "")

    n_orig = 0
    if ap:
        import glob as _g
        n_orig += len(_g.glob(os.path.join(ap, "backup", "regulation.bin.orig_*")))
        n_orig += len(_g.glob(os.path.join(ap, "backup", "item_dlc02.msgbnd.dcx.zhocn.orig_*")))
        add("原始备份（必需）", n_orig >= 2,
            f"找到 {n_orig}/2 份" if n_orig else "缺原始备份：不能「还原成原始」，也不建议写入",
            os.path.join(ap, "backup"))
        base_xml = os.path.join(ap, "work", "msg", "zh", "GoodsCaption.fmg.xml")
        add("说明书基准（必需）", os.path.isfile(base_xml),
            "说明书改地点的对照基准" if os.path.isfile(base_xml) else "缺失：说明书地点无法改写",
            base_xml)
        add("随机引擎", os.path.isfile(os.path.join(ap, "native_deploy.py")),
            "写入用的原生模块", os.path.join(ap, "native_deploy.py"))
    else:
        add("原始备份（必需）", False, "没找到 investigation/apply 目录", "")
        add("说明书基准（必需）", False, "没找到 investigation/apply 目录", "")
        add("随机引擎", False, "没找到 investigation/apply 目录", "")
    return rows

'''
anchor = "\n# ── 随机组合（下拉框）──"
assert anchor in s, "找不到插入锚点"
s = s.replace(anchor, BLOCK + anchor, 1)

# ── ② 界面：在按钮行下方加一块「本地文件」 ──
old_ui = '''        bar = ttk.Frame(body); bar.pack(fill="x", pady=(2, 8))'''
new_ui = '''        # ── 本地文件识别 ──
        s4 = ttk.LabelFrame(body, text=" 本地文件 ", padding=(12, 6))
        s4.pack(fill="x", pady=(0, 8))
        self.lbl_env = ttk.Label(s4, text="检测中…", font=hint, justify="left")
        self.lbl_env.pack(anchor="w")
        r6 = ttk.Frame(s4); r6.pack(fill="x", pady=(4, 0))
        ttk.Button(r6, text="重新检测", width=10, command=self.refresh_env).pack(side="left")
        ttk.Button(r6, text="指定 MOD 目录…", width=16, command=self.pick_mod).pack(side="left", padx=6)
        ttk.Button(r6, text="补一份原始备份", width=16,
                   command=self.make_backup).pack(side="left")

        bar = ttk.Frame(body); bar.pack(fill="x", pady=(2, 8))'''
assert old_ui in s
s = s.replace(old_ui, new_ui, 1)

# ── ③ 方法：检测 / 选择目录 / 补备份 ──
METHODS = '''
    # ── 本地文件相关 ──
    def refresh_env(self, *_a):
        rows = check_env(self.mod_root)
        lines = []
        for name, ok, note, path in rows:
            lines.append(("✓ " if ok else "✗ ") + f"{name}　{note}")
        self.env_rows = rows
        self.lbl_env.config(text="\\n".join(lines), foreground="#333")
        bad = [n for n, ok, _note, _p in rows if not ok]
        self.b_dep.config(state="normal" if not bad else "disabled")
        if bad:
            self.lbl_env.config(foreground="#a00")

    def pick_mod(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择 MOD 根目录（里面有 mod\\\\regulation.bin）")
        if not d:
            return
        if not _looks_like_mod(d):
            messagebox.showwarning("目录不对", "这个目录下没有 mod\\\\regulation.bin，请选 MOD 的根目录。")
            return
        self.mod_root = d
        self.apply_mod_root()
        self.refresh_env()

    def apply_mod_root(self):
        """把选定的 MOD 目录同步给写入模块"""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE or "", "investigation", "apply"))
            import native_guide, native_deploy
            native_guide.MOD = self.mod_root
            native_deploy.MOD = self.mod_root
        except Exception:
            pass

    def make_backup(self):
        """把当前的游戏文件登记为“原始备份”（仅在当前文件确为原版时使用）"""
        if not messagebox.askyesno(
                "补原始备份",
                "将把**当前**的游戏文件登记为原始备份。\\n\\n"
                "请确认现在游戏里的 regulation.bin 与说明书**没有被随机过**（原版状态）。\\n"
                "如果已经被改过，这样备份下来的“原始”是错的——那时请用你留的原版文件覆盖后再执行。\\n\\n继续吗？"):
            return
        try:
            import shutil, time
            ap = os.path.join(WORKSPACE, "investigation", "apply")
            bdir = os.path.join(ap, "backup")
            os.makedirs(bdir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            src = [(os.path.join(self.mod_root, "mod", "regulation.bin"), f"regulation.bin.orig_{ts}"),
                   (os.path.join(self.mod_root, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx"),
                    f"item_dlc02.msgbnd.dcx.zhocn.orig_{ts}")]
            done = []
            for s_, name in src:
                if os.path.isfile(s_):
                    shutil.copy2(s_, os.path.join(bdir, name))
                    done.append(name)
            messagebox.showinfo("完成", "已登记：\\n" + "\\n".join(done))
        except Exception as e:
            messagebox.showerror("失败", str(e))
        self.refresh_env()

'''
m_anchor = "    def _dice(self):"
assert m_anchor in s
s = s.replace(m_anchor, METHODS + m_anchor, 1)

# ── ④ 初始化：探测 MOD 目录 + 首次检测 ──
old_init = '''        self._refresh_modes()'''
new_init = '''        self.mod_root = find_mod_root()
        if self.mod_root:
            self.apply_mod_root()
        self._refresh_modes()
        self.refresh_env()'''
assert old_init in s
s = s.replace(old_init, new_init, 1)

# 线程里用到的 hint 字体需在 UI 之前定义——确认已存在
ast.parse(s)
open(P, "w", encoding="utf-8").write(s)
print(f"  ✓ 已写入（{len(before)} → {len(s)} 字符）")
