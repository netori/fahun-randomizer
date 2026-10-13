# randgui.py — 法魂职业道具和装备随机器（人话版界面）
#
#   · 只换物品，不搬位置；随时可一键还原
#   · 同一种子 = 完全一样的结果
#   · 命令行：--selftest 自检 ｜ --uicheck 只建界面不显示（供自动化测试）
#              --uitest 方案库交互自检 ｜ --planlib 方案库模块自检 ｜ --deploy plan.csv 部署
import importlib.util, json, os, queue, random, re, shutil, sys, threading, time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont


# ── 定位工作区：exe/脚本所在目录向上找 investigation/randomization-dryrun ──
def find_workspace(start):
    cur = os.path.abspath(start)
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, "investigation", "randomization-dryrun")):
            return cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return None


HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
BUNDLE = getattr(sys, "_MEIPASS", HERE)


def materialize_assets():
    """打包版首次运行时，把 exe 内置的运行时资源释放到 exe 旁边。

    为什么这么做：写入管线（AES/DCX/BND4/FMG）、说明书基准、目录数据本来是开发目录里的文件，
    玩家手里没有那套目录，所以直接跑会「找不到引擎/找不到工作区」。
    释放到 exe 旁边之后，磁盘上出现与开发目录一致的结构 —— 后续所有路径逻辑无需改动，
    而且备份、日志、计划表都落在真实磁盘上（临时解包目录重启就没了，不能放那儿）。

    幂等：已存在且大小、时间戳一致的文件不重复写。
    """
    src = os.path.join(BUNDLE, "_assets", "investigation")
    if not os.path.isdir(src):
        return False            # 开发模式：本来就有，什么都不用做
    dst = os.path.join(HERE, "investigation")
    n_new = n_skip = 0
    for dp, _dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in fn:
            s, t = os.path.join(dp, f), os.path.join(target, f)
            try:
                if os.path.exists(t) and os.path.getsize(t) == os.path.getsize(s) and os.path.getmtime(t) >= os.path.getmtime(s):
                    n_skip += 1
                    continue
            except OSError:
                pass
            try:
                shutil.copy2(s, t)
                n_new += 1
            except OSError as e:
                print(f"  释放资源失败：{f}（{e}）")
    # 写入过程中要用的目录先建好
    for d in ("apply/backup", "apply/out", "apply/logs", "apply/work/msg/zh"):
        os.makedirs(os.path.join(dst, d), exist_ok=True)
    return (n_new, n_skip)


if getattr(sys, "frozen", False):
    _r = materialize_assets()
    if isinstance(_r, tuple) and _r[0]:
        print(f"  首次运行：已释放运行时资源（{_r[0]} 个文件）→ {HERE}")

WORKSPACE = find_workspace(HERE) or find_workspace(os.getcwd())


def engine_dir():
    if WORKSPACE:
        return os.path.join(WORKSPACE, "investigation", "randomization-dryrun")
    return os.path.join(BUNDLE, "engine")


def load_engine():
    """加载引擎模块，并把它的路径常量指到真实工作区"""
    p = os.path.join(engine_dir(), "scripts", "randomizer.py")
    if not os.path.exists(p):
        p = os.path.join(BUNDLE, "randomizer.py")
    spec = importlib.util.spec_from_file_location("randomizer", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if WORKSPACE:
        inv = os.path.join(WORKSPACE, "investigation")
        m.ROOT = os.path.join(inv, "randomization-dryrun")
        m.CAT = os.path.join(inv, "randomization-catalog")
        m.REV = os.path.join(inv, "randomization-catalog-review")
    return m



# ── 本地文件识别 ───────────────────────────────────────────────
#   必需项（缺了就没法正确写入/还原）：原始备份、游戏内的 regulation 与说明书
def _looks_like_mod(d):
    return os.path.isfile(os.path.join(d, "mod", "regulation.bin"))


def publish_mod_root(root):
    """把确认过的 MOD 根目录告诉写入管线。

    打包发出去以后，玩家把 exe 放在自己的 MOD 目录里，管线必须按这个目录干活，
    而不是按开发期的目录约定去猜（被 import 的模块拿不到界面上的变量，所以用环境变量传）。
    """
    if root:
        os.environ["CONVERGENCE_MOD_ROOT"] = os.path.abspath(root)
        return True
    return False


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
    publish_mod_root(root)
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


# ── 随机组合（下拉框）──
names_for_join = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}

MODES = [("mix", "全部混合（勾选的几类一起混）"),
         ("sep", "各自随机（勾选的几类各随各的）")]
ITEMS = [("rune", "卢恩"), ("armor", "护甲"), ("weapon", "装备（武器）")]


# ── 把计划翻译成人话 ──
def plain_summary(plan, items, engine):
    CASTER = set(getattr(engine, "CASTER_ARCH", ()))
    moved = [p for p in plan if p.get("old") != p.get("new")]
    stat = {"total": len(moved), "armor_rune": 0, "armor_weapon": 0, "rune_weapon": 0,
            "weapon_any": 0, "caster_leak": 0}
    for p in moved:
        a = items.get(tuple(str(p["old"]).split(":")))
        b = items.get(tuple(str(p["new"]).split(":")))
        if not (a and b):
            continue
        da, db = a.get("domain"), b.get("domain")
        if da == db:
            continue
        pair = {da, db}
        if pair == {"armor", "rune"}:
            stat["armor_rune"] += 1
        elif pair == {"armor", "weapon"}:
            stat["armor_weapon"] += 1
        elif pair == {"rune", "weapon"}:
            stat["rune_weapon"] += 1
        if "weapon" in pair:
            stat["weapon_any"] += 1
        ca_ = lambda v: v.get("domain") == "armor" and v.get("arch") in CASTER
        me = lambda v: v.get("domain") == "armor" and v.get("arch") not in CASTER
        if (ca_(a) and me(b)) or (me(a) and ca_(b)):
            stat["caster_leak"] += 1
    return stat


# ══════════════════════════════════════════════════════════════════════
#  暗色金主题（法环味）—— 施工图见 docs/界面改版_方案库.md 第四节
# ══════════════════════════════════════════════════════════════════════
#  为什么必须 clam：vista / winnative 会**忽略**你设的 background / foreground，
#  界面上会一半暗一半亮。clam 是唯一会老实使用给定颜色的内置主题。
BG        = "#1a1714"   # 窗口底
PANEL     = "#232019"   # 面板底
FIELD     = "#15130f"   # 输入框底
EDGE      = "#3a342a"   # 边框 / 分隔
FG        = "#e8e2d4"   # 主文字
SUB       = "#a09884"   # 次文字（说明 / 时间）
GOLD      = "#c9a227"   # 金：标题 / 强调 / 选中
GOLD_LT   = "#e8c860"   # 亮金
DANGER    = "#b6433c"   # 危险（删除 / 还原）
SEL_BG    = "#3d3527"   # 选中行底
DISABLED  = "#6b665c"   # 禁用文字
BTN_HOVER = "#302a20"   # 按钮悬停
BTN_PRESS = "#3d3527"   # 按钮按下
HEAD_BG   = "#2b261d"   # 表头
WHITE     = "#ffffff"   # 选中时的文字

FONT_UI = ("Microsoft YaHei UI", 10)


def apply_theme(root):
    """装上整套暗色金主题。**必须在建控件之前调用**，否则先建的还是旧配色。

    ttk 控件认这套样式表；不带 ttk 的 tk 控件（tk.Text 等）不认 —— 那些只能逐个传
    bg= / fg=，见 _build 里的 tk.Text。uicheck() 会扫一遍亮块，漏了就报出来。
    """
    st = ttk.Style(root)
    try:
        st.theme_use("clam")                      # 唯一老实使用给定颜色的内置主题
    except tk.TclError:
        pass
    try:
        st.configure(".", font=FONT_UI)
    except tk.TclError:
        pass
    st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=EDGE)
    for w in ("TFrame", "TLabelframe", "TLabel", "TPanedwindow"):
        st.configure(w, background=BG, foreground=FG)
    st.configure("TLabelframe.Label", background=BG, foreground=GOLD)      # 分组框标题
    st.configure("TButton", background=PANEL, foreground=FG, borderwidth=1, focusthickness=0)
    st.map("TButton", background=[("active", BTN_HOVER), ("pressed", BTN_PRESS)],
           foreground=[("disabled", DISABLED)])
    st.configure("Accent.TButton", background=GOLD, foreground=BG, font=("Microsoft YaHei UI", 10, "bold"))
    st.map("Accent.TButton", background=[("active", GOLD_LT), ("pressed", GOLD)],
           foreground=[("disabled", DISABLED)])
    st.configure("Danger.TButton", background=PANEL, foreground=DANGER)
    st.map("Danger.TButton", background=[("active", DANGER), ("pressed", DANGER)],
           foreground=[("active", WHITE), ("pressed", WHITE), ("disabled", DISABLED)])
    st.configure("Link.TButton", background=BG, foreground=GOLD, borderwidth=0, focusthickness=0, padding=(2, 0))
    st.map("Link.TButton", background=[("active", BG)], foreground=[("active", GOLD_LT)])
    st.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, bordercolor=EDGE)
    st.map("TEntry", bordercolor=[("focus", GOLD)])
    st.configure("TCombobox", fieldbackground=FIELD, background=PANEL, foreground=FG,
                 arrowcolor=GOLD, bordercolor=EDGE)
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
           bordercolor=[("focus", GOLD)])
    # clam 的勾选框指示器不吃 indicatorcolor：它的元素选项是 indicatorbackground /
    # indicatorforeground（勾是用前景色画上去的），边框另有 upper/lowerbordercolor。
    st.configure("TCheckbutton", background=BG, foreground=FG,
                 indicatorbackground=FIELD, indicatorforeground=GOLD,
                 upperbordercolor=EDGE, lowerbordercolor=EDGE,
                 indicatormargin=(0, 1, 6, 1), focuscolor=BG)
    st.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", DISABLED)],
           indicatorbackground=[("selected", GOLD), ("active", "selected", GOLD_LT)],
           indicatorforeground=[("selected", BG)])
    # Scale 的滑块与槽是分开的两个东西：background=滑块、troughcolor=槽，配完要实际拖一下看
    st.configure("TScale", background=GOLD, troughcolor=FIELD,
                 lightcolor=GOLD, darkcolor=GOLD, bordercolor=EDGE, focuscolor=BG)
    st.configure("TNotebook", background=BG, bordercolor=EDGE, tabmargins=(6, 4, 6, 0))
    st.configure("TNotebook.Tab", background=PANEL, foreground=SUB, padding=(18, 8))
    st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", GOLD)])
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                 bordercolor=EDGE, rowheight=34)
    st.configure("Treeview.Heading", background=HEAD_BG, foreground=GOLD, relief="flat")  # 最容易漏
    st.map("Treeview.Heading", background=[("active", BTN_HOVER)])
    st.map("Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    # 方案库的列表：两行式行（第一行名字、第二行小字摘要），行高要够
    st.configure("Lib.Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                 borderwidth=0, rowheight=46)
    st.map("Lib.Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        st.configure(sb, background=PANEL, troughcolor=BG, bordercolor=EDGE, arrowcolor=SUB)
        st.map(sb, background=[("active", SEL_BG)])
    st.configure("TSeparator", background=EDGE)
    # 文字风格（tk 控件不认样式表；ttk 的用这些名字）
    st.configure("Title.TLabel", background=BG, foreground=GOLD,
                 font=("Microsoft YaHei UI", 13, "bold"))
    st.configure("Sub.TLabel", background=BG, foreground=SUB)
    st.configure("Hint.TLabel", background=BG, foreground=SUB, font=("Microsoft YaHei UI", 9))
    st.configure("Gold.TLabel", background=BG, foreground=GOLD_LT)
    st.configure("Status.TLabel", background=BG, foreground=GOLD_LT)
    st.configure("Bad.TLabel", background=BG, foreground=DANGER)
    st.configure("Card.TFrame", background=PANEL)
    # 标签筹码（详情面板里的小方块）
    st.configure("Chip.TLabel", background=PANEL, foreground=GOLD, padding=(6, 2),
                 borderwidth=1, relief="solid", bordercolor=EDGE)
    st.configure("ChipHot.TLabel", background=SEL_BG, foreground=GOLD_LT, padding=(6, 2),
                 borderwidth=1, relief="solid", bordercolor=GOLD)
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass
    return st


class App:
    def __init__(self, root):
        self.root = root
        root.title("法魂职业道具和装备随机器")
        root.geometry("1180x820")          # 两页都需要宽度
        root.minsize(1020, 720)
        self.engine = None
        self.plan = None
        self.pools = None
        self.items = None
        self.cfg = None
        self.q = queue.Queue()
        self._adv_open = False
        self._detail_open = False
        apply_theme(root)                 # 必须在建任何控件之前
        self._build()
        root.after(120, self._pump)
        self.log(f"工作区: {WORKSPACE or '未找到（请把本程序放到 随机mod 目录下）'}")
        self._coh_hint()
        self.mod_root = find_mod_root()
        publish_mod_root(self.mod_root)
        if self.mod_root:
            self.apply_mod_root()
        self._refresh_modes()
        self.refresh_env()

    # ══════════ 界面 ══════════
    def _build(self):
        """一屏两页：顶部标题 + 两个页签（随机设置 / 方案库）"""
        head = ttk.Frame(self.root, padding=(16, 12, 16, 2))
        head.pack(fill="x")
        ttk.Label(head, text="法魂职业道具和装备随机器", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="只换物品、不搬位置；随时可以一键还原",
                  style="Hint.TLabel").pack(side="left", padx=(12, 0), pady=(6, 0))

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.page_set = ttk.Frame(self.nb)
        self.nb.add(self.page_set, text="  ⚙ 随机设置  ")
        self.page_lib = ttk.Frame(self.nb, padding=(10, 8, 10, 4))
        self.nb.add(self.page_lib, text="  📚 方案库  ")
        self._build_settings(self._scrollable(self.page_set))
        self._build_library(self.page_lib)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _scrollable(self, parent):
        """给一页加竖向滚动，返回放内容的 frame。

        为什么需要：把「更多设置」和「详细记录」都展开时，内容比窗口高 —— 不滚动的话
        Tk 会把最后几块**压扁**（实测只剩 1 像素高），看着就是坏的。"""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0,
                           yscrollincrement=24)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(2, 4, 10, 10))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # 只在鼠标进这一页时接管滚轮，走了就还回去（否则会影响另一页的列表）
        outer.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        outer.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self.page_set_inner = inner
        return inner

    # ── 页 1 · 随机设置 ──
    def _build_settings(self, body):
        mid = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")

        # ── 第 1 步 ──
        s1 = ttk.LabelFrame(body, text=" 第 1 步 · 随机项目 ", padding=(12, 8))
        s1.pack(fill="x", pady=(0, 8))
        self.basis = tk.StringVar(value="guide")     # 固定：只动职业说明书里的物品
        r2 = ttk.Frame(s1); r2.pack(fill="x")
        ttk.Label(r2, text="随机项目：").pack(side="left")
        self.doms = {}
        for v, t in ITEMS:
            self.doms[v] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r2, text=t, variable=self.doms[v],
                            command=lambda k=v: self._toggle_dom(k)).pack(side="left", padx=(0, 12))
        r3 = ttk.Frame(s1); r3.pack(fill="x", pady=(6, 0))
        ttk.Label(r3, text="混合方式：").pack(side="left")
        self.mode = tk.StringVar(value=MODES[0][1])
        self.cb_mode = ttk.Combobox(r3, textvariable=self.mode, values=[t for _m, t in MODES],
                                    state="readonly", width=34)
        self.cb_mode.pack(side="left", padx=(4, 0))
        self.cb_mode.bind("<<ComboboxSelected>>", lambda _e: self._combo_hint())
        self.lbl_combo = ttk.Label(s1, text="", style="Hint.TLabel")
        self.lbl_combo.pack(anchor="w", pady=(4, 0))

        # ── 第 2 步 ──
        s2 = ttk.LabelFrame(body, text=" 第 2 步 · 合理度 ", padding=(12, 8))
        s2.pack(fill="x", pady=(0, 8))
        r3 = ttk.Frame(s2); r3.pack(fill="x")
        self.coherence = tk.DoubleVar(value=0.8)
        self.lbl_coh = ttk.Label(r3, text="80%", font=mid, width=6)
        ttk.Scale(r3, from_=0.0, to=1.0, variable=self.coherence, orient="horizontal", length=420,
                  command=lambda v: (self.lbl_coh.config(text=f"{float(v)*100:.0f}%"), self._coh_hint())
                  ).pack(side="left", padx=(0, 10))
        self.lbl_coh.pack(side="left")
        r4 = ttk.Frame(s2); r4.pack(fill="x", pady=(2, 0))
        ttk.Label(r4, text="100%  同等级互换      0%  等级完全放开", style="Hint.TLabel").pack(side="left")
        self.lbl_cohtxt = ttk.Label(s2, text="", style="Hint.TLabel")
        self.lbl_cohtxt.pack(anchor="w", pady=(2, 0))

        # ── 第 3 步 ──
        s3 = ttk.LabelFrame(body, text=" 第 3 步 · 随机种子 ", padding=(12, 8))
        s3.pack(fill="x", pady=(0, 8))
        r5 = ttk.Frame(s3); r5.pack(fill="x")
        self.seed = tk.StringVar(value="20261010")
        ttk.Entry(r5, textvariable=self.seed, width=16).pack(side="left")
        ttk.Button(r5, text="换一个", width=8, command=self._dice).pack(side="left", padx=8)

        # ── 按钮 ──
        # ── 本地文件识别 ──
        s4 = ttk.LabelFrame(body, text=" 本地文件 ", padding=(12, 6))
        s4.pack(fill="x", pady=(0, 8))
        self.lbl_env = ttk.Label(s4, text="检测中…", style="Hint.TLabel", justify="left")
        self.lbl_env.pack(anchor="w")
        r6 = ttk.Frame(s4); r6.pack(fill="x", pady=(4, 0))
        ttk.Button(r6, text="重新检测", width=10, command=self.refresh_env).pack(side="left")
        ttk.Button(r6, text="指定 MOD 目录…", width=16, command=self.pick_mod).pack(side="left", padx=6)
        ttk.Button(r6, text="补一份原始备份", width=16,
                   command=self.make_backup).pack(side="left")

        bar = ttk.Frame(body); bar.pack(fill="x", pady=(2, 8))
        self.b_gen = ttk.Button(bar, text="① 生成随机方案", command=self.generate, width=20)
        self.b_gen.pack(side="left")
        self.b_dep = ttk.Button(bar, text="② 写入游戏", command=self.deploy, width=16)
        self.b_dep.pack(side="left", padx=8)
        ttk.Button(bar, text="还原成原始", command=self.rollback, width=14).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="更多设置", command=self._toggle_adv, width=12).pack(side="left")
        ttk.Button(bar, text="方案库", command=self.open_library, width=10).pack(side="left", padx=(8, 0))
        self.status = tk.StringVar(value="先点 ① 生成方案，看过结果再点 ② 写入游戏")
        self.lbl_status = ttk.Label(bar, textvariable=self.status, style="Status.TLabel")
        self.lbl_status.pack(side="left", padx=14)

        # ── 结果（人话）──
        s4 = ttk.LabelFrame(body, text=" 这次会改什么 ", padding=(12, 8))
        s4.pack(fill="x", pady=(0, 8))
        self.summary = tk.StringVar(value="还没生成。点上面的「① 生成随机方案」看看会怎么改。")
        ttk.Label(s4, textvariable=self.summary, justify="left").pack(anchor="w")

        # ── 更多设置（默认折叠）──
        self.adv = ttk.LabelFrame(body, text=" 更多设置 ", padding=(12, 8))
        a1 = ttk.Frame(self.adv); a1.pack(fill="x")
        self.sets = tk.BooleanVar(value=True)
        self.shadow = tk.BooleanVar(value=False)
        self.guide = tk.BooleanVar(value=True)
        ttk.Checkbutton(a1, text="法祷护甲整套一起换", variable=self.sets).pack(side="left")
        ttk.Checkbutton(a1, text="幽影卢恩与普通卢恩一起换", variable=self.shadow).pack(side="left", padx=12)
        ttk.Checkbutton(a1, text="说明书跟着一起改", variable=self.guide).pack(side="left", padx=12)
        a2b = ttk.Frame(self.adv); a2b.pack(fill="x", pady=(6, 0))
        self.shops = tk.BooleanVar(value=False)      # 默认关：老玩法完全不受影响
        ttk.Checkbutton(a2b, text="商店里的职业装备也一起换",
                        variable=self.shops).pack(side="left")
        ttk.Label(a2b, text="· 只影响说明书里的装备；价格 / 限量 / 解锁条件都不动",
                  style="Hint.TLabel").pack(side="left", padx=8)
        a2 = ttk.Frame(self.adv); a2.pack(fill="x", pady=(6, 0))
        ttk.Label(a2, text="改动比例").pack(side="left")
        self.density = tk.DoubleVar(value=1.0)
        self.lbl_den = ttk.Label(a2, text="100%", width=6)
        ttk.Scale(a2, from_=0.05, to=1.0, variable=self.density, orient="horizontal", length=200,
                  command=lambda v: self.lbl_den.config(text=f"{float(v)*100:.0f}%")).pack(side="left", padx=6)
        self.lbl_den.pack(side="left")
        a3 = ttk.Frame(self.adv); a3.pack(fill="x", pady=(6, 0))
        for t, cmd in (("保存这套设置", self.save_cfg), ("读取设置", self.load_cfg),
                       ("导出方案表", self.export), ("打开输出文件夹", self.open_out)):
            ttk.Button(a3, text=t, command=cmd).pack(side="left", padx=(0, 8))

        # ── 详细记录（默认折叠）──
        self.detail = ttk.LabelFrame(body, text=" 详细记录 ", padding=(12, 8))
        d = ttk.Frame(self.detail); d.pack(fill="both", expand=True)
        left = ttk.Frame(d); left.pack(side="left", fill="both", expand=False)
        ttk.Label(left, text="检查项").pack(anchor="w")
        self.checks = ttk.Treeview(left, columns=("k", "v"), show="headings", height=7)
        self.checks.heading("k", text="检查项"); self.checks.heading("v", text="结果")
        self.checks.column("k", width=250); self.checks.column("v", width=90)
        self.checks.pack(fill="both", expand=True)
        right = ttk.Frame(d); right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(right, text="把什么换成了什么（前 300 条）").pack(anchor="w")
        cols = ("old", "new", "where")
        self.tbl = ttk.Treeview(right, columns=cols, show="headings", height=7)
        for c, w, t in (("old", 150, "原来"), ("new", 150, "换成"), ("where", 330, "在哪里")):
            self.tbl.heading(c, text=t); self.tbl.column(c, width=w)
        self.tbl.pack(fill="both", expand=True)
        # tk.Text 不带 ttk，样式表管不到它 —— 颜色必须逐个传（否则是一块白）
        self.txt = tk.Text(self.detail, height=6, wrap="word", bg=FIELD, fg=FG,
                           insertbackground=FG, selectbackground=SEL_BG, selectforeground=WHITE,
                           relief="flat", highlightthickness=1,
                           highlightbackground=EDGE, highlightcolor=GOLD)
        self.txt.pack(fill="both", expand=True, pady=(8, 0))

    # ══════════ 页 2 · 方案库 ══════════
    def _build_library(self, body):
        """方案库页：左边常驻列表 + 右边常驻详情面板。

        这一页取代了原来的「一扇独立小窗 + 一排 12 个按钮 + 每个动作都弹对话框」：
        列表行是两行式（第一行名字，第二行小字摘要），详情常驻右侧、单击哪行就显示哪行。"""
        head = ttk.Frame(body)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="方案库", style="Title.TLabel").pack(side="left")
        self.lib_hint = ttk.Label(head, text="", style="Hint.TLabel")
        self.lib_hint.pack(side="left", padx=(14, 0), pady=(8, 0))

        wrap = ttk.Frame(body)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=62, minsize=340)
        wrap.columnconfigure(1, weight=38, minsize=320)
        wrap.rowconfigure(0, weight=1)

        # ── 左：列表 ──
        left = ttk.Frame(wrap)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.lib_tree = ttk.Treeview(left, columns=(), show="tree", selectmode="browse",
                                     style="Lib.Treeview")
        self.lib_tree.column("#0", width=520, stretch=True)
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.lib_tree.yview)
        self.lib_tree.configure(yscrollcommand=vsb.set)
        self.lib_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.lib_tree.tag_configure("star", foreground=GOLD_LT)
        self.lib_tree.tag_configure("broken", foreground=DANGER)
        self.lib_tree.bind("<<TreeviewSelect>>", lambda _e: self._lib_on_select())

        # ── 右：详情（常驻，取代弹窗）──
        right = ttk.LabelFrame(wrap, text=" 详情 ", padding=(12, 8))
        right.grid(row=0, column=1, sticky="nsew")
        self.lib_title = ttk.Label(right, text="还没选方案", style="Title.TLabel", wraplength=300)
        self.lib_title.pack(anchor="w")
        self.lib_sub = ttk.Label(right, text="左边点一行，这里就是它的全部信息", style="Hint.TLabel")
        self.lib_sub.pack(anchor="w", pady=(2, 8))

        # ── 就地编辑：名字 / 备注 / 标签（点一下直接改，不再弹对话框）──
        self._lib_filling = False
        self.lib_name_e = self._lib_field(right, "名字")
        self.lib_note_e = self._lib_field(right, "备注")
        for e, fn in ((self.lib_name_e, self._lib_commit_name),
                      (self.lib_note_e, self._lib_commit_note)):
            e.bind("<Return>", fn)
            e.bind("<FocusOut>", fn)
        trow = ttk.Frame(right)
        trow.pack(fill="x", pady=3)
        ttk.Label(trow, text="标签", width=7, style="Sub.TLabel").pack(side="left")
        self.lib_tag_box = ttk.Frame(trow)
        self.lib_tag_box.pack(side="left", fill="x", expand=True)
        self.lib_tag_entry = ttk.Entry(trow, width=8)
        ttk.Button(trow, text="+ 添加", style="Link.TButton",
                   command=self._lib_tag_add).pack(side="left", padx=(6, 0))
        self.lib_tag_entry.bind("<Return>", lambda _e: self._lib_tag_commit())
        self.lib_tag_entry.bind("<Escape>", lambda _e: self.lib_tag_entry.pack_forget())

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=(8, 6))
        self.lib_vals = {}
        for key, label in (("seed", "种子"), ("coh", "合理度"), ("density", "改动比例"),
                           ("shops", "商店参与"), ("rows", "改动行"), ("engine", "引擎版本"),
                           ("fp", "指纹"), ("time", "保存时间")):
            row = ttk.Frame(right)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=7, style="Sub.TLabel").pack(side="left")
            v = ttk.Label(row, text="—", wraplength=280, justify="left")
            v.pack(side="left", fill="x", expand=True)
            self.lib_vals[key] = v
        # 底部一行：说清刚刚发生了什么（删除后可以从这里进回收站）
        self.lib_toast = ttk.Label(right, text="", style="Hint.TLabel", wraplength=340,
                                   justify="left")
        self.lib_toast.pack(side="bottom", anchor="w", pady=(8, 0))
        self._lib_cur = None
        self._lib_metas = {}

    def _lib_field(self, parent, label):
        """详情面板里的一行可编辑字段"""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=7, style="Sub.TLabel").pack(side="left")
        e = ttk.Entry(row)
        e.pack(side="left", fill="x", expand=True)
        return e

    def _lib_toast(self, text, bad=False):
        """底部的状态行（不弹窗）"""
        if hasattr(self, "lib_toast"):
            self.lib_toast.config(text=text, style="Bad.TLabel" if bad else "Gold.TLabel")

    # ── 方案库：读 ──
    def _lib_mod(self):
        """加载 planlib；拿不到就如实说明，不抛异常"""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE or "", "investigation", "apply"))
            import planlib
            return planlib
        except Exception as e:
            self.lib_hint.config(text=f"方案库不可用：{e}", style="Bad.TLabel")
            return None

    def _lib_refresh(self, keep=None):
        """重新读一遍方案库。keep=要保住的选中项（没有就选第一行）"""
        if not hasattr(self, "lib_tree"):
            return
        pl = self._lib_mod()
        if not pl:
            return
        want = keep or self._lib_cur
        tv = self.lib_tree
        tv.delete(*tv.get_children())
        try:
            metas = pl.list_plans()
        except Exception as e:
            self.lib_hint.config(text=f"读取方案库出错：{e}", style="Bad.TLabel")
            return
        self._lib_metas = {m["id"]: m for m in metas}
        for m in metas:
            if m.get("broken"):
                tv.insert("", "end", iid=m["id"], tags=("broken",),
                          text=f"⚠ {m['name']}（文件损坏）\n    {m.get('error', '')[:60]}")
                continue
            when = time.strftime("%m-%d %H:%M", time.localtime(m.get("modified") or 0))
            line2 = [when, f"{m.get('changed', 0)}/{m.get('rows', 0)} 行",
                     "商店 " + ("开" if (m.get("cfg") or {}).get("shops") else "关")]
            if m.get("tags"):
                line2.append("·".join(m["tags"]))
            star = "★ " if m.get("star") else "   "
            tv.insert("", "end", iid=m["id"], tags=("star",) if m.get("star") else (),
                      text=f"{star}{m['name']}\n     {' · '.join(line2)}")
        n = len(metas)
        broken = sum(1 for m in metas if m.get("broken"))
        tail = f"（其中 {broken} 个文件损坏）" if broken else ""
        self.lib_hint.config(
            text=f"共 {n} 个方案{tail} ｜ 存在 MOD 目录的 plans 文件夹里：{pl.plans_dir()}",
            style="Hint.TLabel")
        kids = tv.get_children()
        if kids:
            pick = want if want in kids else kids[0]
            tv.selection_set(pick)
            tv.focus(pick)
            tv.see(pick)
            self._lib_show(pick)
        else:
            self._lib_show(None)

    def _lib_on_select(self):
        sel = self.lib_tree.selection()
        if sel:
            self._lib_show(sel[0])

    def _lib_show(self, pid):
        """把某个方案摊在右侧详情面板上"""
        self._lib_cur = pid
        if not pid:
            self.lib_title.config(text="还没有方案")
            self.lib_sub.config(text="先到「随机设置」生成一套，再点「保存到方案库」")
            self._lib_set_field(self.lib_name_e, "")
            self._lib_set_field(self.lib_note_e, "")
            self._lib_tags_render([])
            for v in self.lib_vals.values():
                v.config(text="—")
            return
        m = self._lib_metas.get(pid)
        if m and m.get("broken"):
            self.lib_title.config(text=f"{m['name']}（文件损坏）")
            self.lib_sub.config(text=m.get("error", ""))
            self._lib_set_field(self.lib_name_e, "")
            self._lib_set_field(self.lib_note_e, "")
            self._lib_tags_render([])
            for v in self.lib_vals.values():
                v.config(text="—")
            return
        pl = self._lib_mod()
        if not pl:
            return
        try:
            d = pl.get_plan(pid)
        except Exception as e:
            self.lib_title.config(text="读不出来")
            self.lib_sub.config(text=str(e))
            return
        cfg = d.get("cfg") or {}
        rows = d.get("rows") or []
        changed = sum(1 for r in rows if r.get("old") != r.get("new"))
        self.lib_title.config(text=d.get("name") or pid)
        self.lib_sub.config(text="下面这些都能就地改：点一下直接编辑")
        t = d.get("modified") or d.get("created") or 0
        self._lib_set_field(self.lib_name_e, d.get("name") or "")
        self._lib_set_field(self.lib_note_e, d.get("note") or "")
        self._lib_tags_render(d.get("tags") or [])
        self.lib_vals["seed"].config(text=str(d.get("seed", "—")))
        self.lib_vals["coh"].config(text=f"{float(cfg.get('coherence', 0)) * 100:.0f}%")
        self.lib_vals["density"].config(text=f"{float(cfg.get('density', 1)) * 100:.0f}%")
        self.lib_vals["shops"].config(text="是" if cfg.get("shops") else "否")
        self.lib_vals["rows"].config(text=f"{changed} / {len(rows)}")
        self.lib_vals["engine"].config(text=str(d.get("engine_version") or "—"))
        self.lib_vals["fp"].config(text=(d.get("fingerprint") or "")[:16] + "…")
        self.lib_vals["time"].config(text=time.strftime("%Y-%m-%d %H:%M", time.localtime(t)))

    def _lib_set_field(self, entry, text):
        """程序填字段：期间把提交闸门关上，免得 FocusOut 把界面刷新当成"用户改完了" """
        self._lib_filling = True
        try:
            entry.delete(0, "end")
            entry.insert(0, text)
        finally:
            self._lib_filling = False

    # ── 方案库：就地改（名字 / 备注 / 标签）──
    def _lib_commit_name(self, *_a):
        if self._lib_filling or not self._lib_cur:
            return
        pl = self._lib_mod()
        if not pl:
            return
        new = self.lib_name_e.get().strip()
        old = (self._lib_metas.get(self._lib_cur) or {}).get("name", "")
        if not new:
            self._lib_toast("名字不能空着，已改回去", bad=True)
            self._lib_show(self._lib_cur)
            return
        if new == old:
            return
        try:
            pl.rename_plan(self._lib_cur, new)
        except Exception as e:
            self._lib_toast(f"改名没成功：{e}", bad=True)
            self._lib_show(self._lib_cur)
            return
        self._lib_refresh(keep=self._lib_cur)
        self._lib_toast(f"已改名：{old} → {new}")

    def _lib_commit_note(self, *_a):
        if self._lib_filling or not self._lib_cur:
            return
        pl = self._lib_mod()
        if not pl:
            return
        new = self.lib_note_e.get()
        try:
            old = (pl.get_plan(self._lib_cur).get("note") or "")
        except Exception:
            return
        if new == old:
            return
        try:
            pl.set_meta(self._lib_cur, note=new)
        except Exception as e:
            self._lib_toast(f"备注没存上：{e}", bad=True)
            return
        self._lib_refresh(keep=self._lib_cur)
        self._lib_toast("备注已保存" if new else "备注已清空")

    def _lib_tags_render(self, tags):
        """标签画成一排小筹码：点筹码上的 ✕ 就去掉"""
        for w in self.lib_tag_box.winfo_children():
            w.destroy()
        for tg in tags:
            chip = ttk.Label(self.lib_tag_box, text=f"{tg} ✕", style="Chip.TLabel")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda _e, t=tg: self._lib_tag_del(t))
            chip.bind("<Enter>", lambda _e, c=chip: c.config(style="ChipHot.TLabel"))
            chip.bind("<Leave>", lambda _e, c=chip: c.config(style="Chip.TLabel"))
        if not tags:
            ttk.Label(self.lib_tag_box, text="（还没标签）", style="Hint.TLabel").pack(side="left")

    def _lib_tag_add(self):
        """就地加标签：在原地冒出一个输入框，回车就加上（不弹对话框）"""
        self.lib_tag_entry.pack(side="right", padx=(6, 0))
        self.lib_tag_entry.delete(0, "end")
        self.lib_tag_entry.focus_set()

    def _lib_tag_commit(self):
        txt = self.lib_tag_entry.get().strip()
        self.lib_tag_entry.pack_forget()
        if not txt or not self._lib_cur:
            return
        self._lib_tag_del(txt, add=True)

    def _lib_tag_del(self, tag, add=False):
        """加成 / 去掉一个标签（同一套写回）"""
        pl = self._lib_mod()
        if not pl or not self._lib_cur:
            return
        try:
            d = pl.get_plan(self._lib_cur)
        except Exception as e:
            self._lib_toast(f"读不出来：{e}", bad=True)
            return
        tags = [t for t in (d.get("tags") or []) if t != tag]
        if add:
            tags.append(tag)
        try:
            pl.set_meta(self._lib_cur, tags=tags)
        except Exception as e:
            self._lib_toast(f"标签没存上：{e}", bad=True)
            return
        self._lib_refresh(keep=self._lib_cur)
        self._lib_toast(f"已添加标签「{tag}」" if add else f"已去掉标签「{tag}」")

    def open_library(self):
        """跳到方案库页（原来是一扇独立小窗）"""
        self.nb.select(self.page_lib)
        self._lib_refresh()

    def _on_tab_changed(self, *_a):
        if hasattr(self, "lib_tree") and self.nb.select() == str(self.page_lib):
            self._lib_refresh()

    def _picked_doms(self):
        return [d for d in ("rune", "armor", "weapon") if self.doms[d].get()]

    def _toggle_dom(self, key):
        """至少保留一项；勾选变化后智能刷新混合方式"""
        if not self._picked_doms():
            self.doms[key].set(True)                      # 不允许全不勾
            messagebox.showinfo("至少勾一项", "至少要保留一个随机项目。")
        self._refresh_modes()

    def _refresh_modes(self, *_a):
        """混合方式随勾选项目智能变更（下拉里的文字直接写出项目名）"""
        doms = self._picked_doms()
        if len(doms) <= 1:
            vals = ["只有一项：在自己范围里随机"]
        else:
            names = names_for_join
            plus = " + ".join(names[d] for d in doms)
            dun = "、".join(names[d] for d in doms)
            vals = [f"全部混合（{plus} 一起混）"]
            if len(doms) == 3:
                a, b, c = doms
                vals += [f"{names[a]}+{names[b]} 混 · {names[c]} 独自",
                         f"{names[a]}+{names[c]} 混 · {names[b]} 独自",
                         f"{names[b]}+{names[c]} 混 · {names[a]} 独自"]
            vals.append(f"各自随机（{dun} 各随各的）")
        old = self.mode.get()
        self.cb_mode.config(values=vals)
        self.mode.set(old if old in vals else vals[0])
        self._combo_hint()
        self._coh_hint()

    def _combo_hint(self, *_a):
        names = names_for_join
        """按当前勾选与混合方式，说明会怎么随"""
        doms = self._picked_doms()
        if not doms:
            self.lbl_combo.config(text="⚠ 一项都没勾：请至少勾选一个随机项目。")
            return
        sep = "各自" in self.mode.get() or len(doms) <= 1
        picked = "、".join(names[d] for d in doms)
        extra = "　法师/祷告护甲始终单独一组" if "armor" in doms else ""
        if sep:
            self.lbl_combo.config(text=f"{picked}：各自随机{extra}")
            return
        self.lbl_combo.config(text=f"{picked}：互相混合{extra}")

    def _toggle_adv(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self.adv.pack(fill="x", pady=(0, 8), before=self.detail if self._detail_open else None)
        else:
            self.adv.pack_forget()

    def _toggle_detail(self):
        self._detail_open = not self._detail_open
        if self._detail_open:
            self.detail.pack(fill="both", expand=True, pady=(0, 8))
        else:
            self.detail.pack_forget()

    # ══════════ 逻辑 ══════════
    def log(self, s):
        self.q.put(("log", s))

    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.txt.insert("end", str(payload) + "\n"); self.txt.see("end")
                elif kind == "status":
                    _s = str(payload)
                    self.status.set(_s)
                    # 失败一律用危险色，成功/进行中用亮金（暗底上的可读性靠这个）
                    self.lbl_status.config(style="Bad.TLabel" if _s.startswith(("失败", "出错", "写入失败", "还原出错"))
                                           else "Status.TLabel")
                elif kind == "done":
                    self.b_gen.config(state="normal")
                elif kind == "table":
                    for row in payload:
                        self.tbl.insert("", "end", values=row)
                elif kind == "checks":
                    for k, v in payload:
                        self.checks.insert("", "end", values=(k, v))
                elif kind == "summary":
                    self.summary.set(str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _coh_hint(self, *_a):
        """把 0-100% 翻译成一句人话（口径与引擎一致：统一 4 档）"""
        c = float(self.coherence.get())
        # 引擎里 steps = clamp(round((1-c)*3), 0, 3)，bucket = 档位 // (steps+1)
        steps = max(0, min(3, int(round((1 - c) * 3))))
        span = steps + 1                       # 可互换的档位跨度：1~4
        lvl = {1: "只能同档位互换", 2: "相邻两档可互换",
               3: "三档以内可互换", 4: "等级完全放开"}[span]
        # 档位共 4 级（卢恩 学徒/熟练/精通/大师·幽影；护甲 臂/腿/身/头）
        tier_mix = int(round(span / 4.0 * 100))
        doms = [d for d, v in self.doms.items() if v.get()]
        if len(doms) <= 1:
            wtxt = "单项随机，不涉及跨类"
        elif "weapon" not in doms:
            wtxt = "武器掺入 0%（未勾选装备）"
        else:
            wtxt = f"武器掺入上限 {int(round((1 - c) * 66))}%"
        rate = int(round((1 - c) * 100))
        self.lbl_cohtxt.config(
            text=f"{lvl}　档位跨度 {span}/4（{tier_mix}%）　越档率 ≤{rate}%　{wtxt}")


    # ── 本地文件相关 ──
    def refresh_env(self, *_a):
        rows = check_env(self.mod_root)
        lines = []
        for name, ok, note, path in rows:
            lines.append(("✓ " if ok else "✗ ") + f"{name}　{note}")
        self.env_rows = rows
        self.lbl_env.config(text="\n".join(lines), style="Hint.TLabel")
        bad = [n for n, ok, _note, _p in rows if not ok]
        self.b_dep.config(state="normal" if not bad else "disabled")
        if bad:
            self.lbl_env.config(style="Bad.TLabel")

    def pick_mod(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择 MOD 根目录（里面有 mod\\regulation.bin）")
        if not d:
            return
        if not _looks_like_mod(d):
            messagebox.showwarning("目录不对", "这个目录下没有 mod\\regulation.bin，请选 MOD 的根目录。")
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
                "将把**当前**的游戏文件登记为原始备份。\n\n"
                "请确认现在游戏里的 regulation.bin 与说明书**没有被随机过**（原版状态）。\n"
                "如果已经被改过，这样备份下来的“原始”是错的——那时请用你留的原版文件覆盖后再执行。\n\n继续吗？"):
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
            messagebox.showinfo("完成", "已登记：\n" + "\n".join(done))
        except Exception as e:
            messagebox.showerror("失败", str(e))
        self.refresh_env()

    def _dice(self):
        self.seed.set(str(random.randrange(1, 2 ** 31 - 1)))

    def _shops(self):
        """商店是否参与（默认关）。取不到就按关处理。"""
        try:
            return bool(self.shops.get())
        except Exception:
            return False

    def _collect(self):
        doms = [d for d, v in self.doms.items() if v.get()]
        sep = ("各自" in self.mode.get()) or len(doms) <= 1
        joins = []
        if not sep and len(doms) == 3 and "·" in self.mode.get():
            # "A+B 混 · C 独自" → joins=[[A,B]]
            left = self.mode.get().split("混 ·")[0]
            pair = [d for d in doms if names_for_join[d] in left]
            if len(pair) == 2:
                joins = [pair]
        return {"domains": doms or ["rune", "armor", "weapon"],
                "basis": "guide", "shops": self._shops(),  # 说明书范围固定；商店是否参与看「更多设置」
                "joins": joins,                      # 两两混：只给这一组建混池
                "cross_domain": (not sep) and not joins,   # 全部混合=建混池；两两混/各自=不建
                "merge_shadow": self.shadow.get(), "sets": self.sets.get(),
                "seed": int(self.seed.get()), "density": round(float(self.density.get()), 3),
                "coherence": round(float(self.coherence.get()), 3),
                "sync_guide": bool(self.guide.get())}

    def generate(self):
        if not WORKSPACE:
            messagebox.showerror("找不到游戏目录", "请把本程序放到 随机mod 目录（或其子目录）下再运行。")
            return
        if not [d for d, v in self.doms.items() if v.get()]:
            messagebox.showinfo("还没选随机项目", "请至少勾选一个随机项目（卢恩 / 护甲 / 装备）。")
            return
        self.b_gen.config(state="disabled")
        for t in (self.checks, self.tbl):
            t.delete(*t.get_children())
        if not self._detail_open:
            self._toggle_detail()
        threading.Thread(target=self._gen_worker, daemon=True).start()

    def _gen_worker(self):
        try:
            cfg = self._collect()
            self.log(f"生成中…（种子 {cfg['seed']}）")
            if self.engine is None:
                self.engine = load_engine()
            m = self.engine
            items = m.load_world(cfg["shops"], cfg["basis"])
            m.world_ref = items
            plan, pools, seed = m.run(items, cfg, cfg["seed"])
            ck, info = m.verify(items, cfg, plan, pools)
            self.plan, self.pools, self.items, self.cfg = plan, pools, items, cfg
            rows = [r for r in plan if r.get("old") != r.get("new")]
            st = plain_summary(plan, items, m)
            bad = [k for k, v in ck.items() if not v]
            _c = float(cfg.get("coherence", 0.8))
            _span = max(0, min(3, int(round((1 - _c) * 3)))) + 1
            _lv = {1: "只能同档位互换", 2: "相邻两档可互换", 3: "三档以内可互换", 4: "等级完全放开"}[_span]
            lines = [f"一共改动 {st['total']} 处东西。",
                     f"· 档位：{_lv}（合理度 {int(_c*100)}%，跨度 {_span}/4）。"]
            if st["armor_rune"]:
                lines.append(f"· 有 {st['armor_rune']} 件护甲和卢恩互换了。")
            if st["weapon_any"]:
                lines.append(f"· 有 {st['weapon_any']} 件武器掺进了混池。")
            else:
                lines.append("· 武器这次没有掺进混池（合理度较高时就是这样）。")
            lines.append("· 法师/祷告的护甲" + ("没有掺进混池 ✓" if st["caster_leak"] == 0 else f"有 {st['caster_leak']} 处混进来了 ✗"))
            lines.append(("· 检查：全部通过 ✓" if not bad else "· 检查有问题 ✗：" + "；".join(bad)))
            self.q.put(("summary", "\n".join(lines)))
            self.q.put(("checks", list(ck.items()) + [("· " + k, v) for k, v in info.items()]))
            self.q.put(("table", [(r["old"], r["new"],
                                   f"{r.get('row_name', '')[:52]}")
                                  for r in sorted(rows, key=lambda x: (x["old"]))[:300]]))
            self.log(f"完成：置换行 {len(rows)} ｜ 物品 {len(items)} ｜ 种子 {seed}")
            self.log("检查：" + "，".join(f"{k}={'通过' if v else '[X]失败'}" for k, v in ck.items()))
            self._coh_hint()
            self.q.put(("status", f"生成完成（种子 {seed}）：可以点 ② 写入游戏了"))
        except Exception as e:
            import traceback
            self.log("出错：" + traceback.format_exc(limit=3))
            self.q.put(("status", f"失败：{e}"))
        finally:
            self.q.put(("done", None))

    def export(self):
        if not self.plan:
            messagebox.showinfo("还没生成", "先点「① 生成随机方案」。")
            return
        out = os.path.join(WORKSPACE, "investigation", "apply", "out", f"plan_seed{self.cfg['seed']}.csv")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # 前 12 列保持原样（旧工具仍可读）；新增列一律追加在末尾
        cols = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
                "source_table", "row_id", "slot", "row_name",
                "engine_version", "algorithm_mode", "unchanged_reason", "preconditions"]
        import csv as _csv
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for p in sorted(self.plan, key=lambda x: (x["pool"], x["unit"], x["source_table"], x["row_id"], x["slot"])):
                w.writerow({k: p.get(k, "") for k in cols})
        self.log(f"已导出 → {out}")
        return out

    def open_out(self):
        p = os.path.join(WORKSPACE, "investigation", "apply", "out") if WORKSPACE else HERE
        if os.path.isdir(p):
            os.startfile(p)  # noqa


    def deploy(self):
        if not self.plan:
            messagebox.showinfo("还没生成", "先点「① 生成随机方案」。")
            return
        if not messagebox.askyesno("确认写入游戏",
                                   "会把这次的随机结果写进游戏文件：\n"
                                   "  · 物品与掉落\n  · 说明书文本\n\n"
                                   "写入前会自动备份，随时可以点「还原成原始」。开始？"):
            return
        plan = self.export()
        sync = bool(self.cfg.get("sync_guide", True))
        self.log(f"写入中…{'（含说明书）' if sync else '（不改说明书）'}")
        self.q.put(("status", "写入中…"))
        threading.Thread(target=self._deploy_worker, args=(plan, sync), daemon=True).start()

    def _deploy_worker(self, plan, sync_guide):
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import native_deploy
            rec = native_deploy.deploy(plan, sync_guide=sync_guide, log=self.log)
            self.log("写入完成 [OK] " + str(rec.get("verify")))
            self.q.put(("status", "写入完成 ✓ 可以进游戏了"))
        except Exception as e:
            import traceback
            self.log("写入出错：" + traceback.format_exc(limit=4))
            self.q.put(("status", f"写入失败：{e}"))

    def save_cfg(self):
        from tkinter import filedialog
        if not self.cfg:
            messagebox.showinfo("还没生成", "先生成一次方案，再保存设置。")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile=f"设置_种子{self.cfg['seed']}.json")
        if p:
            json.dump(self.cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            self.log(f"设置已保存 → {p}")

    def load_cfg(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=[("设置", "*.json")])
        if not p:
            return
        c = json.load(open(p, encoding="utf-8"))
        self.seed.set(str(c.get("seed", self.seed.get())))
        self.sets.set(c.get("sets", True))
        self.shadow.set(c.get("merge_shadow", False))
        self.density.set(float(c.get("density", 1.0)))
        self.coherence.set(float(c.get("coherence", 0.8)))
        self.lbl_coh.config(text=f"{float(c.get('coherence',0.8))*100:.0f}%")
        self.lbl_den.config(text=f"{float(c.get('density',1.0))*100:.0f}%")
        self.guide.set(c.get("sync_guide", True))
        _d = c.get("domains") or ["rune", "armor", "weapon"]
        for k, v in self.doms.items():
            v.set(k in _d)
        self._refresh_modes()
        _vals = list(self.cb_mode.cget("values"))
        if len(_vals) > 1:
            self.mode.set(_vals[1] if c.get("cross_domain") is False else _vals[0])
        self._combo_hint()
        self._coh_hint()
        self.log(f"设置已读入：{os.path.basename(p)}（点「① 生成随机方案」生效）")

    def rollback(self):
        if not messagebox.askyesno("还原成原始",
                                   "把物品与说明书都恢复成游戏原本的样子？\n（你之前写入的随机结果会被撤销）"):
            return
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import shutil
            import native_deploy
            reg = os.path.join(native_deploy.MOD, "mod", "regulation.bin")
            msg = os.path.join(native_deploy.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
            shutil.copy2(native_deploy.find_original("regulation.bin.orig_*"), reg)
            shutil.copy2(native_deploy.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), msg)
            self.log("已还原成原始版 [OK]")
            self.q.put(("status", "已还原成原始版 ✓"))
        except Exception as e:
            self.log("还原出错：" + str(e))
            self.q.put(("status", f"还原出错：{e}"))


def _lum(col):
    """把 #rrggbb 算成亮度 0~1；认不出的颜色返回 None（那些也算可疑）"""
    h = (col or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


# 主题色板：这些颜色一定是故意的（金色滑块之类的亮色不该被当成白块）
THEME_COLORS = {c.lower() for c in
                (BG, PANEL, FIELD, EDGE, FG, SUB, GOLD, GOLD_LT, DANGER, SEL_BG,
                 BTN_HOVER, BTN_PRESS, HEAD_BG, DISABLED)}

_TTK_STYLE_OF = {
    "TLabel": "TLabel", "TFrame": "TFrame", "TLabelframe": "TLabelframe", "TButton": "TButton",
    "TEntry": "TEntry", "TCombobox": "TCombobox", "TCheckbutton": "TCheckbutton",
    "TRadiobutton": "TRadiobutton", "TScale": "TScale", "TNotebook": "TNotebook",
    "Treeview": "Treeview", "TSpinbox": "TSpinbox", "TProgressbar": "TProgressbar",
}
# 「有输入区」的控件：真正露出来的是 fieldbackground，不是 background
_CTL_WITH_FIELD = ("TEntry", "TCombobox", "Treeview", "TSpinbox", "TProgressbar")


def _widget_colors(w, st):
    """这个控件实际会用到的颜色（用来找白块）"""
    cols = []
    try:
        bg = str(w.cget("background")).strip()
    except Exception:
        bg = ""                       # ttk 的多数控件没有 background 选项
    if bg:
        cols.append(bg)               # 显式设过的（tk 控件都是这一路）
    if isinstance(w, ttk.Widget):
        cls = w.winfo_class()
        style = str(w.cget("style")).strip() or _TTK_STYLE_OF.get(cls, "")
        if cls == "TScrollbar":
            style = style or f"{str(w.cget('orient')).capitalize()}.TScrollbar"
            opts = ("background", "troughcolor")
        elif cls in _CTL_WITH_FIELD:
            opts = ("fieldbackground", "background")
        else:
            opts = ("background",)
        for opt in opts:
            try:
                v = str(st.lookup(style, opt)).strip()
            except Exception:
                v = ""
            if v:
                cols.append(v)
    return cols


def audit_light_widgets(root, limit=0.80):
    """扫出「暗色应用里的一块白」。

    判定：颜色**不在**主题色板里，而且亮度超过 limit —— 认不出的颜色（SystemButtonFace
    之类）同样算可疑。ttk 控件认样式表，不带 ttk 的（tk.Text / tk.Frame / tk.Label）不认，
    只能逐个查背景色。"""
    st = ttk.Style(root)
    bad = []

    def walk(w):
        for c in w.winfo_children():
            for col in _widget_colors(c, st):
                if str(col).strip().lower() in THEME_COLORS:
                    continue
                L = _lum(col)
                if L is None or L > limit:
                    bad.append((c.winfo_class(), str(c), col))
                    break
            walk(c)

    walk(root)
    return bad


# 页 1 上必须存在的控件（拆页签时最容易漏掉几个）——「功能没少」的机械证据
SETTINGS_WIDGETS = ("b_gen", "b_dep", "lbl_env", "cb_mode", "lbl_combo", "lbl_coh", "lbl_cohtxt",
                    "lbl_den", "checks", "tbl", "txt", "summary", "status", "adv", "detail",
                    "doms", "mode", "seed", "coherence", "density", "sets", "shadow", "guide",
                    "shops")


def uicheck():
    """只建界面不进入事件循环（自动化测试用）。

    这是施工单第五节每步都要过的闸门：界面建得起来 + 用的是 clam 主题 + 扫不到白块
    + 两页页签都在 + 页 1 的控件一个不少。"""
    root = tk.Tk()
    app = App(root)
    root.update_idletasks()
    root.update()
    st = ttk.Style(root)
    theme = st.theme_use()
    bad = audit_light_widgets(root)
    print(f"UICHECK: 主题 {theme} ｜ 窗口 {root.winfo_width()}x{root.winfo_height()} ｜ 亮块 {len(bad)} 处")
    for cls, path, col in bad[:10]:
        print(f"   ✗ 疑似白块：{cls} {path} 背景 {col}")

    problems = []
    tabs = [str(app.nb.tab(t, "text")).strip() for t in app.nb.tabs()]
    print(f"   页签：{' ｜ '.join(tabs)}")
    if len(tabs) != 2:
        problems.append(f"页签不是两个：{tabs}")
    for want, page in (("随机设置", app.page_set), ("方案库", app.page_lib)):
        if not any(want in t for t in tabs):
            problems.append(f"缺页签：{want}")
        if not str(page).startswith(str(app.nb)):
            problems.append(f"{want} 页不在页签控件里")
    missing = [a for a in SETTINGS_WIDGETS if not hasattr(app, a)]
    print(f"   页 1 控件：{len(SETTINGS_WIDGETS) - len(missing)}/{len(SETTINGS_WIDGETS)}")
    if missing:
        problems.append("页 1 缺控件：" + ", ".join(missing))

    if theme != "clam":
        problems.append(f"主题不是 clam：{theme}")
    ok = not problems and not bad
    for p in problems:
        print(f"   ✗ {p}")
    print("UICHECK PASS: 界面构建成功" if ok else "UICHECK FAIL: 见上面的问题")
    root.destroy()
    return 0 if ok else 1


def _fake_rows(n=60, tag="weapon"):
    """造几行假方案（只给方案库用，不碰引擎）"""
    out = []
    for j in range(n):
        ch = tag if j % 3 else "armor"
        out.append({"old": f"{ch}:{1000+j}", "new": f"{ch}:{2000+j}",
                    "source_table": "ItemLotParam_map", "row_id": str(700000 + j),
                    "slot": str(j % 4), "unit": f"u{j}", "old_cat": ch, "new_cat": ch,
                    "engine_version": "1.1.0", "pool": "p", "role": "r", "part": "",
                    "row_name": f"箱{j}", "algorithm_mode": "guide",
                    "unchanged_reason": "", "preconditions": ""})
    return out


def uitest():
    """方案库的交互自检：建出来、列出来、点一下看详情对不对。

    全程用**临时目录**当方案库（绝不碰玩家真正的 plans/），所以在打包版的空目录里
    也能跑。施工单第 3~6 步的每一步都往这张检查表里加行。"""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="_uitest_plans_")
    rows = _fake_rows()
    checks = []

    def ck(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    root = None
    try:
        sys.path.insert(0, os.path.join(WORKSPACE or HERE, "investigation", "apply"))
        import planlib
        planlib.plans_dir = lambda ws=None: tmp
        sys.modules["planlib"] = planlib
        a = planlib.save_plan(rows, "稳健档", cfg={"seed": 20261010, "shops": False,
                                                   "coherence": 0.8, "density": 1.0},
                              seed=20261010, note="主打流程用", tags=["主打"])
        planlib.set_meta(a["id"], star=True)
        b = planlib.save_plan(rows[:40], "放开档", cfg={"seed": 20261011, "shops": True,
                                                        "coherence": 0.0, "density": 0.5},
                              seed=20261011)

        root = tk.Tk()
        app = App(root)
        root.update_idletasks()
        root.update()
        app.nb.select(app.page_lib)
        app._lib_refresh()
        root.update()

        kids = app.lib_tree.get_children()
        ck("列表列出来了", len(kids) == 2, f"{len(kids)} 行")
        ck("收藏排在最前", bool(kids) and kids[0] == a["id"], f"第一行={kids[0] if kids else '—'}")
        ck("列表是两行式", "\n" in (app.lib_tree.item(kids[0], "text") if kids else ""),
           "行里含换行符")

        # 单击第二行 → 详情面板要跟着变（这一步就是「取代弹窗」的核心）
        if len(kids) > 1:
            app.lib_tree.selection_set(kids[1])
            app.lib_tree.focus(kids[1])
            app._lib_on_select()
            root.update()
        ck("单击换详情：名字", app.lib_title.cget("text") == "放开档",
           f"标题={app.lib_title.cget('text')!r}")
        ck("单击换详情：种子", app.lib_vals["seed"].cget("text") == "20261011",
           f"种子={app.lib_vals['seed'].cget('text')!r}")
        ck("单击换详情：商店参与", app.lib_vals["shops"].cget("text") == "是",
           f"商店={app.lib_vals['shops'].cget('text')!r}")
        ck("单击换详情：合理度", app.lib_vals["coh"].cget("text") == "0%",
           f"合理度={app.lib_vals['coh'].cget('text')!r}")
        ck("详情是常驻面板（不是弹窗）", not getattr(app, "_libwin", None),
           "没有额外的 Toplevel")

        # 切回方案库页要自己刷新（不然在别处存了方案、回到这页看不见）
        planlib.save_plan(rows[:30], "新来的", cfg={"seed": 20261012}, seed=20261012)
        app.nb.select(app.page_set)
        root.update()
        app.nb.select(app.page_lib)
        root.update()
        ck("切到方案库页会自动刷新", len(app.lib_tree.get_children()) == 3,
           f"{len(app.lib_tree.get_children())} 行")

        # ── 第 4 步：就地编辑名字 / 备注 / 标签 ──
        app.lib_tree.selection_set(a["id"])
        app._lib_on_select()
        root.update()
        app.lib_name_e.delete(0, "end")
        app.lib_name_e.insert(0, "稳健档（改过）")
        app._lib_commit_name()
        root.update()
        ck("就地改名：列表里也跟着变",
           app.lib_tree.item(a["id"], "text").startswith("★ 稳健档（改过）"),
           repr(app.lib_tree.item(a["id"], "text")[:14]))
        ck("就地改名：详情标题跟着变", app.lib_title.cget("text") == "稳健档（改过）",
           repr(app.lib_title.cget("text")))
        ck("就地改名：落到盘上", planlib.get_plan(a["id"])["name"] == "稳健档（改过）",
           repr(planlib.get_plan(a["id"])["name"]))

        app.lib_note_e.delete(0, "end")
        app.lib_note_e.insert(0, "改成这条备注")
        app._lib_commit_note()
        root.update()
        ck("就地改备注：落到实处", planlib.get_plan(a["id"])["note"] == "改成这条备注",
           repr(planlib.get_plan(a["id"])["note"]))

        app._lib_tag_del("第二标签", add=True)
        root.update()
        ck("就地改标签：加一个", planlib.get_plan(a["id"])["tags"] == ["主打", "第二标签"],
           repr(planlib.get_plan(a["id"])["tags"]))
        ck("就地改标签：筹码画出来了", len(app.lib_tag_box.winfo_children()) == 2,
           f"{len(app.lib_tag_box.winfo_children())} 个筹码")
        app._lib_tag_del("主打")
        root.update()
        ck("就地改标签：去掉一个", planlib.get_plan(a["id"])["tags"] == ["第二标签"],
           repr(planlib.get_plan(a["id"])["tags"]))

        # 重新读一遍：改完的东西要还在（这正是「刷新仍在」）
        app._lib_refresh()
        root.update()
        ck("改完刷新仍在", app.lib_name_e.get() == "稳健档（改过）"
           and app.lib_note_e.get() == "改成这条备注",
           f"{app.lib_name_e.get()!r} / {app.lib_note_e.get()!r}")

        # 空名字要被挡回去，不能把方案改成没名字
        app.lib_name_e.delete(0, "end")
        app._lib_commit_name()
        root.update()
        ck("空名字被挡回去", planlib.get_plan(a["id"])["name"] == "稳健档（改过）",
           repr(planlib.get_plan(a["id"])["name"]))

        root.destroy()
        root = None
    except Exception:
        import traceback
        ck("自检过程没抛异常", False, traceback.format_exc(limit=3))
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)

    n_bad = 0
    for name, ok, detail in checks:
        if ok:
            print(f"   ✓ {name}")
        else:
            n_bad += 1
            print(f"   ✗ {name}　{detail}")
    print("UITEST PASS: 方案库交互正常" if not n_bad else f"UITEST FAIL: {n_bad} 项没过")
    return 0 if not n_bad else 1


def selftest(seed=20261010):
    """不需要开窗口：验证引擎可用 + 同种子可复现 + 不同种子不同"""
    print(f"工作区: {WORKSPACE}")
    if not WORKSPACE:
        print("SELFTEST FAIL: 找不到工作区"); return 1
    m = load_engine()
    cfg = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide",
           "shops": True, "merge_shadow": False, "sets": True, "seed": seed}
    sigs = []
    import hashlib
    for _ in range(2):
        items = m.load_world(cfg["shops"], cfg["basis"])
        m.world_ref = items
        plan, pools, _s = m.run(items, cfg, cfg["seed"])
        ck, _info = m.verify(items, cfg, plan, pools)
        rows = sorted((r["pool"], r["old"], r["new"], r["source_table"], r["row_id"], r["slot"])
                      for r in plan if r.get("old") != r["new"])
        sigs.append(hashlib.sha256(repr(rows).encode()).hexdigest())
        if not all(ck.values()):
            print("SELFTEST FAIL: 校验未全过", ck); return 1
    items_b = m.load_world(cfg["shops"], cfg["basis"])
    m.world_ref = items_b
    plan_b, _pools_b, _ = m.run(items_b, {**cfg, "seed": seed + 1}, seed + 1)
    rows_b = sorted((r["pool"], r["old"], r["new"], r["source_table"], r["row_id"], r["slot"])
                    for r in plan_b if r.get("old") != r["new"])
    sig_b = hashlib.sha256(repr(rows_b).encode()).hexdigest()
    same = sigs[0] == sigs[1]
    diff = sig_b != sigs[0]
    print(f"  置换行 {len(rows_b)} ｜ 同种子一致: {same} ｜ 换种子结果不同: {diff}")
    msg = "SELFTEST PASS" if (same and diff) else "SELFTEST FAIL"
    print(msg)
    try:
        d = os.path.join(WORKSPACE, "investigation", "apply", "logs") if WORKSPACE else HERE
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "gui_selftest.txt"), "w", encoding="utf-8").write(
            f"{msg}\n工作区: {WORKSPACE}\n置换行: {len(rows_b)}\n同种子一致: {same}\n换种子不同: {diff}\n")
    except Exception:
        pass
    return 0 if (same and diff) else 1


def cli_deploy(argv):
    """命令行写入：法魂职业道具和装备随机器.exe --deploy <plan.csv> [--no-guide]"""
    sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
    import native_deploy
    plan = argv[argv.index("--deploy") + 1]
    rec = native_deploy.deploy(os.path.abspath(plan), sync_guide="--no-guide" not in argv, log=print)
    print("写入完成", rec.get("verify"))
    return 0


def cli_planlib():
    """命令行自检：方案库能不能真用（保存 / 列出 / 读取 / 改名 / 收藏 / 删除）"""
    import shutil, tempfile
    sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
    import planlib
    ws = tempfile.mkdtemp(prefix="_pllib_")
    try:
        os.makedirs(os.path.join(ws, "investigation", "apply"), exist_ok=True)
        rows = [{"old": f"weapon:{100+i}", "new": f"weapon:{200+i}", "source_table": "ItemLotParam_map",
                 "row_id": str(700000 + i), "slot": "1", "unit": f"u{i}", "old_cat": "weapon",
                 "new_cat": "weapon", "engine_version": "1.1", "pool": "p", "role": "r", "part": "",
                 "row_name": f"箱{i}", "algorithm_mode": "guide", "unchanged_reason": "", "preconditions": ""}
                for i in range(6)]
        m = planlib.save_plan(rows, "自检方案", cfg={"seed": 1, "shops": True}, seed=1, ws=ws)
        assert planlib.list_plans(ws=ws), "列不出来"
        assert len(planlib.get_plan(m["id"], ws=ws)["rows"]) == 6, "读回不是 6 行"
        planlib.rename_plan(m["id"], "改名后", ws=ws)
        planlib.set_meta(m["id"], star=True, note="n", tags=["t"], ws=ws)
        d = planlib.get_plan(m["id"], ws=ws)
        assert d["name"] == "改名后" and d["star"] and d["tags"] == ["t"], "改名/收藏/标签没生效"
        csvp = os.path.join(ws, "p.csv")
        planlib.write_csv(m["id"], csvp, ws=ws)
        import csv as _c
        assert len(list(_c.DictReader(open(csvp, encoding="utf-8-sig")))) == 6, "导出的 CSV 不是 6 行"
        planlib.delete_plan(m["id"], ws=ws)
        assert not planlib.list_plans(ws=ws), "删完还有"
        print("PLANLIB PASS: 保存/列出/读取/改名/收藏/标签/导出/删除 全部正常")
        print(f"  存放位置（正式运行时会在这个目录）: {planlib.plans_dir()}")
        return 0
    except Exception as e:
        import traceback
        print("PLANLIB FAIL: " + traceback.format_exc(limit=4))
        return 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main():
    # 尽早发布 MOD 路径：写入管线在 import 时就会读取它（打包版尤其重要）
    try:
        publish_mod_root(find_mod_root())
    except Exception:
        pass
    if "--deploy" in sys.argv:
        return cli_deploy(sys.argv)
    if "--selftest" in sys.argv:
        return selftest()
    if "--planlib" in sys.argv:
        return cli_planlib()
    if "--uitest" in sys.argv:
        return uitest()
    if "--uicheck" in sys.argv:
        return uicheck()
    root = tk.Tk()
    App(root)                      # App 起来时自己会装暗色金主题
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
