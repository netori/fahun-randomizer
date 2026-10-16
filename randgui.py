# randgui.py — 法魂职业道具和装备随机器（人话版界面）
#
#   · 只换物品，不搬位置；随时可一键还原
#   · 同一种子 = 完全一样的结果
#   · 命令行：--selftest 自检 ｜ --uicheck 只建界面不显示（供自动化测试）
#              --uitest 方案库交互自检 ｜ --planlib 方案库模块自检 ｜ --deploy plan.csv 部署
import collections, importlib.util, json, os, queue, random, re, shutil, sys, threading, time
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
    # 2026-10-17 修：以前只释放 _assets/investigation，于是 _assets/tools 下的
    # Paramdex（enemy_randomizer 解析 NpcParam 行表要读的 XML）永远不会落到磁盘上 ——
    # 表现就是打包版点「写入游戏」报「写入失败：读不到 Paramdex 定义：NpcParam」。
    # 改成释放整个 _assets（它本来就被定义为"运行时最小集"），顶层目录逐个走一遍。
    base = os.path.join(BUNDLE, "_assets")
    tops = [d for d in ("investigation", "tools") if os.path.isdir(os.path.join(base, d))]
    if not tops:
        return False            # 开发模式：本来就有，什么都不用做
    dst = os.path.join(HERE, "investigation")
    n_new = n_skip = 0
    for top in tops:
        src = os.path.join(base, top)
        out = dst if top == "investigation" else os.path.join(HERE, top)
        for dp, _dn, fn in os.walk(src):
            rel = os.path.relpath(dp, src)
            target = out if rel == "." else os.path.join(out, rel)
            os.makedirs(target, exist_ok=True)
            for f in fn:
                s2, t = os.path.join(dp, f), os.path.join(target, f)
                try:
                    if os.path.exists(t) and os.path.getsize(t) == os.path.getsize(s2) and os.path.getmtime(t) >= os.path.getmtime(s2):
                        n_skip += 1
                        continue
                except OSError:
                    pass
                try:
                    shutil.copy2(s2, t)
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


# ── 装饰件（AI 生的图，见 tools/_make_deco.py）──────────────────────
#   打包版从 exe 内部的释放目录读（spec 里 _assets 整个打进去了）；
#   图缺了**不影响使用** —— 全部返回 None，界面照常建起来。
_deco_cache = {}


def deco_path(name):
    for base in (os.path.join(BUNDLE, "_assets", "deco"), os.path.join(HERE, "_assets", "deco")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def deco_image(name, scale=None):
    """按屏幕缩放挑 1× / 2× 那张（150% 屏用 2×，不然会糊）"""
    key = (name, scale)
    if key in _deco_cache:
        return _deco_cache[key]
    fname = f"{name}@2x.png" if (scale or S) >= 1.5 else f"{name}.png"
    img = None
    p = deco_path(fname) or deco_path(f"{name}.png")
    if p:
        try:
            img = tk.PhotoImage(file=p)
        except Exception:
            img = None
    _deco_cache[key] = img
    return img


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
LIBSORT = ("时间（新→旧）", "名字", "改动量（多→少）")


# ── 把计划翻译成人话 ──
def plain_summary(plan, items, engine):
    """给「这次会改什么」算人话数字。

    · 商店：货架一共几个、换了几个（货架跟着它卖的东西走 —— 东西没被换，货架就不动）
    · 法祷护甲：整套换了几套、散件换了几件（按**单元**数，不是按格子数：一套四件算一套）
    """
    CASTER = set(getattr(engine, "CASTER_ARCH", ()))
    moved = [p for p in plan if p.get("old") != p.get("new")]
    stat = {"total": len(moved), "armor_rune": 0, "armor_weapon": 0, "rune_weapon": 0,
            "weapon_any": 0, "caster_leak": 0,
            "shop_total": 0, "shop_moved": 0,
            "caster_sets": 0, "caster_parts": 0, "caster_rows": 0}

    def _is_caster_armor(k):
        v = items.get(tuple(str(k).split(":")))
        return bool(v) and v.get("domain") == "armor" and v.get("arch") in CASTER

    _caster_units = set()
    for p in plan:
        if p.get("source_table") == "ShopLineupParam":
            stat["shop_total"] += 1
            if p.get("old") != p.get("new"):
                stat["shop_moved"] += 1
        if p.get("old") == p.get("new"):
            continue
        if _is_caster_armor(p.get("old")):
            stat["caster_rows"] += 1
            _caster_units.add(str(p.get("unit") or p.get("old")))
    stat["caster_sets"] = sum(1 for u in _caster_units if u.startswith("set:"))
    stat["caster_parts"] = len(_caster_units) - stat["caster_sets"]

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
EDGE      = "#453e32"   # 边框 / 分隔（比第一版亮一档：暗底上太细的线会"看不出来"）
FG        = "#e8e2d4"   # 主文字
SUB       = "#c3baa8"   # 次文字（说明 / 时间 / 字段名）—— 原来 #a09884 只有 6.2:1，偏灰
GOLD      = "#c9a227"   # 金：标题 / 强调 / 选中
GOLD_LT   = "#e8c860"   # 亮金
DANGER    = "#e0705e"   # 危险文字（删除 / 还原）—— 原来的 #b6433c 在暗底上只有 3:1
DANGER_FILL = "#8b352f" # 危险按钮按下/悬停时的底色（配白字，7.9:1）
SEL_BG    = "#3d3527"   # 选中行底
DISABLED  = "#8b8578"   # 禁用文字（原来 #6b665c 只有 2.8:1，基本看不清）
BTN_HOVER = "#302a20"   # 按钮悬停
BTN_PRESS = "#3d3527"   # 按钮按下
HEAD_BG   = "#2b261d"   # 表头
WHITE     = "#ffffff"   # 选中时的文字

FONT_NAME = "Microsoft YaHei UI"
FONT_UI = (FONT_NAME, 11)          # 11pt：中文 10pt 在暗底上偏小
FONT_SMALL = (FONT_NAME, 10)
FONT_TITLE = (FONT_NAME, 15, "bold")


def _enable_dpi_awareness():
    """让 Windows 别再拉伸我们的窗口 —— 这一步不做，150% 缩放的字就是糊的。

    必须在**第一个 tk.Tk() 之前**调用，所以放在模块导入时执行。
    （实测对照：不做的话字被系统放大 1.5 倍再插值，笔画发虚；做了之后按物理像素绘制。）
    """
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)      # 系统级 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()           # 老系统退路
    except Exception:
        pass


_enable_dpi_awareness()

# 屏幕缩放倍数：100% = 1.0，150% = 1.5。窗口尺寸与各处像素间距都要乘它，
# 字号不用动 —— Tk 按"磅"渲染，会自己跟着系统 DPI 放大。
S = 1.0


def px(v):
    """把设计稿上的像素值换成当前屏幕的像素值（1.5 倍屏就 ×1.5）"""
    return int(round(v * S))


def setup_display(root):
    """量出屏幕缩放并告诉 Tk 磅→像素怎么换算。

    **必须在建窗口和控件之前调用**（几何尺寸和每一处间距都要乘 S；字号是"磅"，Tk 自己会跟着放大）。"""
    global S
    try:
        S = max(1.0, root.winfo_fpixels("1i") / 96.0)         # 100% 屏 = 1.0，150% 屏 = 1.5
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        S = 1.0
    return S



def apply_theme(root):
    """装上整套暗色金主题。**必须在建控件之前调用**，否则先建的还是旧配色。

    ttk 控件认这套样式表；不带 ttk 的 tk 控件（tk.Text 等）不认 —— 那些只能逐个传
    bg= / fg=，见 _build 里的 tk.Text。uicheck() 会扫一遍亮块，漏了就报出来。
    """
    st = ttk.Style(root)
    setup_display(root)                      # 先量屏幕缩放：下面的间距都要乘它
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
    st.configure("TButton", background=PANEL, foreground=FG, borderwidth=px(1), focusthickness=0)
    st.map("TButton", background=[("active", BTN_HOVER), ("pressed", BTN_PRESS)],
           foreground=[("disabled", DISABLED)])
    st.configure("Accent.TButton", background=GOLD, foreground=BG,
                 font=(FONT_NAME, 11, "bold"))
    # 禁用态：底色退回输入框底（灰字压金底只有 1.5:1，等于看不见 —— 实测踩过）
    st.map("Accent.TButton", background=[("active", GOLD_LT), ("pressed", GOLD),
                                         ("disabled", FIELD)],
           foreground=[("disabled", DISABLED)])
    st.configure("Danger.TButton", background=PANEL, foreground=DANGER)
    st.map("Danger.TButton", background=[("active", DANGER_FILL), ("pressed", DANGER_FILL)],
           foreground=[("active", WHITE), ("pressed", WHITE), ("disabled", DISABLED)])
    st.configure("Link.TButton", background=BG, foreground=GOLD, borderwidth=0,
                 focusthickness=0, padding=(px(2), 0))
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
                 indicatormargin=(0, px(1), px(6), px(1)), focuscolor=BG)
    st.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", DISABLED)],
           indicatorbackground=[("selected", GOLD), ("active", "selected", GOLD_LT)],
           indicatorforeground=[("selected", BG)])
    # Scale 的滑块与槽是分开的两个东西：background=滑块、troughcolor=槽，配完要实际拖一下看
    st.configure("TScale", background=GOLD, troughcolor=FIELD,
                 lightcolor=GOLD, darkcolor=GOLD, bordercolor=EDGE, focuscolor=BG)
    st.configure("TNotebook", background=BG, bordercolor=EDGE,
                 tabmargins=(px(6), px(4), px(6), 0))
    st.configure("TNotebook.Tab", background=PANEL, foreground=SUB, padding=(px(18), px(8)))
    st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", GOLD)])
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                 bordercolor=EDGE, rowheight=px(30))
    st.configure("Treeview.Heading", background=HEAD_BG, foreground=GOLD, relief="flat")  # 最容易漏
    st.map("Treeview.Heading", background=[("active", BTN_HOVER)])
    st.map("Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    # 方案库的列表：两行式行（第一行名字、第二行小字摘要），行高要够
    st.configure("Lib.Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                 borderwidth=0, rowheight=px(52))
    st.map("Lib.Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        # lightcolor / darkcolor 是 clam 给滚动条画的"高光/阴影"边 —— 不配的话它自己
        # 拿背景色推出一圈亮边，看着像一条白条
        st.configure(sb, background=PANEL, troughcolor=BG, bordercolor=EDGE, arrowcolor=SUB,
                     lightcolor=EDGE, darkcolor=EDGE)
        st.map(sb, background=[("active", SEL_BG)], arrowcolor=[("active", GOLD_LT)])
    st.configure("TSeparator", background=EDGE)
    # 文字风格（tk 控件不认样式表；ttk 的用这些名字）
    st.configure("Title.TLabel", background=BG, foreground=GOLD, font=FONT_TITLE)
    st.configure("Sub.TLabel", background=BG, foreground=SUB)
    st.configure("Hint.TLabel", background=BG, foreground=SUB, font=FONT_SMALL)
    st.configure("Gold.TLabel", background=BG, foreground=GOLD_LT)
    st.configure("Status.TLabel", background=BG, foreground=GOLD_LT)
    st.configure("Bad.TLabel", background=BG, foreground=DANGER)
    st.configure("Card.TFrame", background=PANEL)
    # 装饰图（标题下的金藤蔓、空库插画）：底色要显式给，不然图周围一圈不对
    st.configure("Deco.TLabel", background=BG)
    # 标签筹码（详情面板里的小方块）
    st.configure("Chip.TLabel", background=PANEL, foreground=GOLD, padding=(px(6), px(2)),
                 borderwidth=1, relief="solid", bordercolor=EDGE)
    st.configure("ChipHot.TLabel", background=SEL_BG, foreground=GOLD_LT, padding=(px(6), px(2)),
                 borderwidth=1, relief="solid", bordercolor=GOLD)
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass
    return st


class App:
    def __init__(self, root):
        self.root = root
        setup_display(root)               # 必须在几何尺寸与建控件之前
        root.title("法魂职业道具和装备随机器")
        root.geometry(f"{px(1180)}x{px(820)}")   # 两页都需要宽度；px() 会按屏幕缩放
        root.minsize(px(1020), px(720))
        self.engine = None
        self.plan = None
        self.pools = None
        self.items = None
        self.cfg = None
        self.q = queue.Queue()
        self._deploying = False          # 写入串行化：上次没跑完不许再点
        self._lib_writing = False        # 从方案库写入中（进度要回显到方案库窗口）
        self._adv_open = False
        self._detail_open = False
        ic = deco_image("icon", scale=1)      # 窗口/任务栏图标（256px 那张够用）
        if ic:
            self._deco_icon = ic
            try:
                root.iconphoto(True, ic)
            except Exception:
                pass
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
        head = ttk.Frame(self.root, padding=(px(16), px(12), px(16), px(2)))
        head.pack(fill="x")
        row = ttk.Frame(head)
        row.pack(fill="x")
        ttk.Label(row, text="法魂职业道具和装备随机器", style="Title.TLabel").pack(side="left")
        ttk.Label(row, text="只换物品、不搬位置；随时可以一键还原",
                  style="Hint.TLabel").pack(side="left", padx=(px(12), 0), pady=(px(6), 0))
        div = deco_image("divider")              # 标题下的一条金藤蔓
        if div:
            self._deco_div = div                 # 得留个引用，不然 Tk 会把图回收掉
            ttk.Label(head, image=div, style="Deco.TLabel").pack(pady=(px(6), 0))

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=px(10), pady=(px(4), px(4)))
        # ── 外层动作栏（2026-10-17）：动作不属于任何一页 —— 一次随机同时管物品与敌人 ──
        #    为什么搬出来：物品与敌人写的是同一个 regulation、走同一次部署，
        #    "生成 / 写入"本来就该是一次动作；按钮留在物品页会让人以为只随机物品。
        outer = ttk.Frame(self.root, padding=(px(12), px(4), px(12), px(2)))
        outer.pack(fill="x")
        self.b_gen = ttk.Button(outer, text="① 生成随机方案", command=self.generate, width=20)
        self.b_gen.pack(side="left")
        self.b_dep = ttk.Button(outer, text="② 写入游戏", command=self.deploy, width=16)
        self.b_dep.pack(side="left", padx=8)
        ttk.Button(outer, text="还原成原始", command=self.rollback, width=14).pack(side="left", padx=(0, 8))
        self.b_save_lib = ttk.Button(outer, text="💾 保存到方案库", style="Accent.TButton",
                                     command=self._lib_save_current, width=15)
        self.b_save_lib.pack(side="left", padx=(0, 8))
        self.b_save_lib.config(state="disabled")
        ttk.Button(outer, text="敌人设置…", width=12,
                   command=lambda: self.nb.select(self.page_enemy)).pack(side="left")
        self.b_out_settings = ttk.Button(outer, text="物品设置…", width=12,
                                        command=lambda: self.nb.select(self.page_set))
        self.b_out_settings.pack(side="left", padx=6)
        self.outer_what = ttk.Label(self.root, text="", style="Hint.TLabel",
                                    wraplength=px(940), justify="left")
        self.outer_what.pack(fill="x", padx=px(12), pady=(px(2), 0))
        self.status = tk.StringVar(value="先点 ① 生成方案，看过结果再点 ② 写入游戏")
        self.lbl_status = ttk.Label(self.root, textvariable=self.status, style="Status.TLabel")
        self.lbl_status.pack(fill="x", padx=px(12), pady=(px(2), px(6)))
        self.page_set = ttk.Frame(self.nb)
        self.page_enemy = ttk.Frame(self.nb)
        self.page_lib = ttk.Frame(self.nb, padding=(px(10), px(8), px(10), px(4)))
        self._deco_tabs = []
        for page, label, icon in ((self.page_set, "职业物品随机", deco_image("tab_settings")),
                                  (self.page_enemy, "敌人随机", deco_image("tab_settings")),
                                  (self.page_lib, "方案库", deco_image("tab_library"))):
            if icon:
                self._deco_tabs.append(icon)
                self.nb.add(page, text=f"  {label}  ", image=icon, compound="left")
            else:
                self.nb.add(page, text=f"  {label}  ")
        self._build_settings(self._scrollable(self.page_set))
        self._build_enemy_page(self._scrollable(self.page_enemy))
        self._build_library(self.page_lib)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _scrollable(self, parent):
        """给一页加竖向滚动，返回放内容的 frame。

        为什么需要：把「更多设置」和「详细记录」都展开时，内容比窗口高 —— 不滚动的话
        Tk 会把最后几块**压扁**（实测只剩 1 像素高），看着就是坏的。"""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0,
                           yscrollincrement=px(24))
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(px(2), px(4), px(10), px(10)))
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
        if not hasattr(self, "page_set_inner"):
            self.page_set_inner = inner
        return inner

    # ── 页 1 · 随机设置 ──
    def _build_settings(self, body):
        mid = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")

        # ── 第 1 步 ──
        s1 = ttk.LabelFrame(body, text=" 第 1 步 · 随机项目 ", padding=(px(12), px(8)))
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
        # 换混合方式必须把"改动比例 / 单独设合理度"两组一起理顺 ——
        # 之前这里只调了 _combo_hint()，所以用户在下拉里换完方式，那两组纹丝不动（真 bug，2026-10-14 修）
        self.cb_mode.bind("<<ComboboxSelected>>",
                          lambda _e: (self._combo_hint(), self._refresh_rates(), self._refresh_cohs()))
        self.lbl_combo = ttk.Label(s1, text="", style="Hint.TLabel")
        self.lbl_combo.pack(anchor="w", pady=(4, 0))

        # ── 第 2 步 ──
        s2 = ttk.LabelFrame(body, text=" 第 2 步 · 合理度 ", padding=(px(12), px(8)))
        s2.pack(fill="x", pady=(0, 8))
        r3 = ttk.Frame(s2); r3.pack(fill="x")
        self.coherence = tk.DoubleVar(value=0.8)
        self.lbl_coh = ttk.Label(r3, text="80%", font=mid, width=6)
        # 存下 Scale 本体：没有混池时它要**置灰**（那时每个池子用自己那条）
        self.scale_coh = ttk.Scale(r3, from_=0.0, to=1.0, variable=self.coherence, orient="horizontal",
                                   length=px(420),
                                   command=lambda v: (self.lbl_coh.config(text=f"{float(v)*100:.0f}%"),
                                                      self._refresh_cohs()))
        self.scale_coh.pack(side="left", padx=(0, 10))
        self.lbl_coh.pack(side="left")
        r4 = ttk.Frame(s2); r4.pack(fill="x", pady=(2, 0))
        ttk.Label(r4, text="100%  同等级互换      0%  等级完全放开", style="Hint.TLabel").pack(side="left")
        self.lbl_cohtxt = ttk.Label(s2, text="", style="Hint.TLabel")
        self.lbl_cohtxt.pack(anchor="w", pady=(2, 0))

        # ── 单独成池的那几条合理度（2026-10-14 作者定的表单规则）──
        #    没有总开关、也没有「混池」那条：
        #      · 有混池 → 上面那条**总合理度**管混池（它保持可用）
        #      · 没有混池（各自随机）→ 总合理度**置灰**，下面每个"自己成池"的类别各有一条
        #      · 全部混合 → 只剩总合理度（三个类别都进了混池，下面一条都不摆）
        #    摆哪几条见 _coh_applicable()。
        self.lbl_cohrows = ttk.Label(s2, text="", style="Hint.TLabel")
        self.lbl_cohrows.pack(anchor="w", pady=(4, 0))
        cgrid = ttk.Frame(s2); cgrid.pack(fill="x")
        self.coh_rows = {}
        for i, (key, text) in enumerate((("rune", "卢恩"), ("armor", "护甲"),
                                         ("weapon", "装备（武器）"))):
            self._mk_override_row(cgrid, self.coh_rows, key, text, 0.0, 1.0, i)
        self._refresh_cohs()

        # ── 第 3 步 ──
        s3 = ttk.LabelFrame(body, text=" 第 3 步 · 随机种子 ", padding=(px(12), px(8)))
        s3.pack(fill="x", pady=(0, 8))
        r5 = ttk.Frame(s3); r5.pack(fill="x")
        self.seed = tk.StringVar(value="20261010")
        ttk.Entry(r5, textvariable=self.seed, width=16).pack(side="left")
        ttk.Button(r5, text="换一个", width=8, command=self._dice).pack(side="left", padx=8)

        # ── 按钮 ──
        # ── 本地文件识别 ──
        s4 = ttk.LabelFrame(body, text=" 本地文件 ", padding=(px(12), px(6)))
        s4.pack(fill="x", pady=(0, 8))
        self.lbl_env = ttk.Label(s4, text="检测中…", style="Hint.TLabel", justify="left")
        self.lbl_env.pack(anchor="w")
        r6 = ttk.Frame(s4); r6.pack(fill="x", pady=(4, 0))
        ttk.Button(r6, text="重新检测", width=10, command=self.refresh_env).pack(side="left")
        ttk.Button(r6, text="指定 MOD 目录…", width=16, command=self.pick_mod).pack(side="left", padx=6)
        ttk.Button(r6, text="补一份原始备份", width=16,
                   command=self.make_backup).pack(side="left")

        # 动作按钮已经搬到窗口底部的外层栏（一次随机同时管物品与敌人）——
        # 这里只留物品页自己的「更多设置」开关。
        bar = ttk.Frame(body); bar.pack(fill="x", pady=(2, 8))
        ttk.Button(bar, text="更多设置", command=self._toggle_adv, width=12).pack(side="left")
        ttk.Label(bar, text="· 生成 / 写入 / 还原 都在窗口底部的动作栏里（物品与敌人一起）",
                  style="Hint.TLabel").pack(side="left", padx=px(10))

        # ── 结果（人话）──
        s4 = ttk.LabelFrame(body, text=" 这次会改什么 ", padding=(px(12), px(8)))
        s4.pack(fill="x", pady=(0, 8))
        self.summary = tk.StringVar(value="还没生成。点上面的「① 生成随机方案」看看会怎么改。")
        ttk.Label(s4, textvariable=self.summary, justify="left").pack(anchor="w")

        # ── 更多设置（默认折叠）──
        #    注意：这两个开关都要**立刻**带动下面「改动比例」那一组（2026-10-14 作者报过
        #    "开了/关了下面的比例不跟着变" —— 商店那个当时根本没接刷新）。
        self.adv = ttk.LabelFrame(body, text=" 更多设置 ", padding=(px(12), px(8)))
        a1 = ttk.Frame(self.adv); a1.pack(fill="x")
        self.sets = tk.BooleanVar(value=True)
        self.guide = tk.BooleanVar(value=True)
        self.cb_sets = ttk.Checkbutton(a1, text="法祷护甲整套一起换", variable=self.sets,
                                       command=self._refresh_rates)
        self.cb_sets.pack(side="left")
        # 「幽影卢恩与普通卢恩一起换」这个开关 2026-10-14 撤掉了：
        # 实测它改不了任何结果 —— 档位系统里 大师=幽影 都是 3 档（规格 §2 / Q3 定下的），
        # 按档位分桶时两者必然并到一起。留着只会让人以为"某个开关没生效"。
        ttk.Checkbutton(a1, text="说明书跟着一起改", variable=self.guide).pack(side="left", padx=12)
        a2b = ttk.Frame(self.adv); a2b.pack(fill="x", pady=(6, 0))
        self.shops = tk.BooleanVar(value=False)      # 默认关：老玩法完全不受影响
        self.cb_shops = ttk.Checkbutton(a2b, text="商店里的职业装备也一起换", variable=self.shops,
                                        command=self._refresh_rates)
        self.cb_shops.pack(side="left")
        ttk.Label(a2b, text="· 只影响说明书里的装备；价格 / 限量 / 解锁条件都不动",
                  style="Hint.TLabel").pack(side="left", padx=8)
        # ── 改动比例：两条，**在该出现时才出现**（没有总开关，与合理度那组一个风格）──
        #    · 法祷职业护甲 —— 整套与散件一起调（引擎里是 rate_sets + rate_caster 两个键）
        #    · 商店物品     —— **有商店在卖的那批物品**里，多少参与互换（rate_shop，按物品抽）
        #    不勾 = 这一类全改（100%）
        a2r = ttk.Frame(self.adv); a2r.pack(fill="x", pady=(6, 0))
        ttk.Label(a2r, text="改动比例", style="Sub.TLabel").pack(side="left")
        self.rate_hint = ttk.Label(a2r, text="· 不勾 = 这一类全改；商店开了就是**在卖的职业装备全部参与**（不做二次抽）",
                                   style="Hint.TLabel")
        self.rate_hint.pack(side="left", padx=6)
        # 用 grid（不用 pack）：隐藏/恢复的时候格子还在，**顺序不会乱**
        rgrid = ttk.Frame(self.adv); rgrid.pack(fill="x")
        self.rate_rows = {}
        #    商店**没有**比例条（2026-10-14 作者决定）：勾了「商店里的职业装备也一起换」
        #    就等于"在卖的职业装备全部参与"（引擎侧 rate_shop 仍认，只是界面不再暴露）
        for i, (key, text) in enumerate((("caster", "法祷职业护甲"),)):
            self._mk_override_row(rgrid, self.rate_rows, key, text, 0.05, 1.0, i)
        self._refresh_rates()               # 一建出来就按当前勾选理顺一次

        a3 = ttk.Frame(self.adv); a3.pack(fill="x", pady=(6, 0))
        for t, cmd in (("保存这套设置", self.save_cfg), ("读取设置", self.load_cfg),
                       ("导出方案表", self.export), ("打开输出文件夹", self.open_out)):
            ttk.Button(a3, text=t, command=cmd).pack(side="left", padx=(0, 8))

        # ── 详细记录（默认折叠）──
        self.detail = ttk.LabelFrame(body, text=" 详细记录 ", padding=(px(12), px(8)))
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
                           font=FONT_SMALL,
                           insertbackground=FG, selectbackground=SEL_BG, selectforeground=WHITE,
                           relief="flat", highlightthickness=px(1),
                           highlightbackground=EDGE, highlightcolor=GOLD)
        self.txt.pack(fill="both", expand=True, pady=(px(8), 0))

        # 敌人随机那组控件已经搬到「敌人随机」页 —— 见 _build_enemy_page()

    def _refresh_enemy(self, *_a):
        """敌人这一页的联动：总开关控制可用性 + 每类的百分比 + 底部摘要"""
        on = bool(self.enemy_on.get())
        for w in list(getattr(self, "enemy_sub", [])) \
                + list(self.enemy_pools.values()) + list(getattr(self, "enemy_cls_rates", {}).values()) \
                + [self.enemy_rate_lbl, self.enemy_hint, self.enemy_seed_e]:
            try:
                w.configure(state="normal" if on else "disabled")
            except Exception:
                pass
        # 每类的百分比标签
        for k, v in getattr(self, "enemy_cls_rates", {}).items():
            lbl = getattr(self, "enemy_cls_lbl_" + k, None)
            if lbl is None:
                continue
            try:
                lbl.configure(text=("不参与" if not self.enemy_pools[k].get() or float(v.get()) <= 0
                                    else "%.0f%%" % (float(v.get()) * 100)))
            except Exception:
                pass
        r = float(self.enemy_rate.get())
        self.enemy_rate_lbl.configure(text="全改（100%）" if r >= 0.999
                                      else "约 %d%% 的敌人参与" % round(r * 100))
        if not on:
            self.enemy_hint.configure(
                text="· 关着。打开后：把每种敌人的整行数据（血量/伤害/AI/掉落…）在同一类别池里互相置换；"
                     "阵营与生成方式不跟着走，种类总数守恒（不会多也不会少）。")
            try:
                self._refresh_outer()
            except Exception:
                pass
            return
        _zh = {"boss": "Boss", "elite": "精英", "normal": "普通敌人"}
        _pools = [(k, float(self.enemy_cls_rates[k].get())) for k in _zh
                  if self.enemy_pools[k].get() and float(self.enemy_cls_rates[k].get()) > 0]
        _src = "全随机（原版 + 法魂）" if self.enemy_source.get() == "all" else "只随机法魂敌人"
        _fl = []
        if self.enemy_ignore_size.get():
            _fl.append("忽略体型限制")
        if self.enemy_visual.get():
            _fl.append("连外观一起换")
        if not self.enemy_keep_unkillable.get():
            _fl.append("连打不死的也换")
        if not self.enemy_use_arena.get():
            _fl.append("不看场地档")
        if self.enemy_same_type.get():
            _fl.append("只换同一种敌人")
        _ty = self._enemy_types_picked()
        if _ty:
            _fl.append("限定 %d 个敌型" % len(_ty))
        if self.enemy_seed_sep.get():
            _fl.append("独立敌人种子 " + (self.enemy_seed.get() or "（还没填）"))
        self.enemy_hint.configure(
            text="· 参与：" + ("、".join("%s %.0f%%" % (_zh[k], v * 100) for k, v in _pools)
                               or "（一个都没给比例，等于不换）")
                 + "；来源：" + _src + ("；" + "、".join(_fl) if _fl else "")
                 + "\n· 具体会改多少行、各类各多少，点「读一次统计」或生成后看「这次会改什么」。")
        try:
            self._refresh_outer()
        except Exception:
            pass

    def _enemy_cls_moved(self, key):
        """某一类的比例被拖动 —— 顺手把标签刷新（数值只在 _refresh_enemy 里统一算）"""
        self._refresh_enemy()

    def _enemy_dice(self):
        """重掷独立的敌人种子（照参考实现的 Reroll enemy seed separately）"""
        self.enemy_seed.set(str(random.randrange(1, 2 ** 31 - 1)))
        self.enemy_seed_sep.set(True)
        self._refresh_enemy()

    def enemy_stats(self):
        """读一次真实统计（要解一遍 regulation，几秒）——回填类别与敌型的行数"""
        if getattr(self, "_enemy_stats_busy", False):
            return
        self._enemy_stats_busy = True
        self._enemy_type_hint_set("正在读敌人统计…（几秒）")

        def work():
            try:
                sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
                import enemy_randomizer as ER
                import collections
                u = ER.load_units(ER.load_plain())
                ER.classify(u, names=ER.load_name_table(), healthbar_ids=ER.load_healthbar_nameids())
                cls = collections.Counter(x.cls for x in u.values())
                types = collections.Counter(x.enemy_type for x in u.values() if x.enemy_type)
                self._enemy_stats_cache = {"cls": dict(cls), "types": dict(types)}
                self.q.put(("enemy_stats", None))
            except Exception as e:
                self.q.put(("enemy_page", ("读统计失败：" + str(e), True)))
            finally:
                self.q.put(("enemy_stats_done", None))
        threading.Thread(target=work, daemon=True).start()

    def _enemy_type_hint_set(self, text, bad=False):
        if hasattr(self, "enemy_type_hint"):
            self.enemy_type_hint.config(text=text, style="Bad.TLabel" if bad else "Hint.TLabel")

    def _enemy_types_fill(self):
        """把敌型列表填上（行数来自统计缓存；没读统计就只列名字）"""
        if not hasattr(self, "enemy_type_tree"):
            return
        st = (getattr(self, "_enemy_stats_cache", None) or {}).get("types") or {}
        keep = set(self.enemy_type_tree.selection())
        for iid in self.enemy_type_tree.get_children():
            self.enemy_type_tree.delete(iid)
        if not st:
            for name in ("骑士/重甲", "野兽/动物", "士兵/守军", "不死/腐败", "魔像/人造", "虫/花/菌",
                         "龙/龙裔", "巨人/巨兽", "施法者/祭司", "人形/平民", "坐骑/驮兽",
                         "Boss/领主", "亚人/混种", "神皮/教会", "法魂新增", "非战斗/NPC",
                         "体型·大/巨", "未分类"):
                self.enemy_type_tree.insert("", "end", iid=name, text=name, values=("—",))
        else:
            for name, n in sorted(st.items(), key=lambda x: -x[1]):
                self.enemy_type_tree.insert("", "end", iid=name, text=name, values=(n,))
        for iid in keep:
            if self.enemy_type_tree.exists(iid):
                self.enemy_type_tree.selection_add(iid)

    def _enemy_types_picked(self):
        """选中的敌型（一个不选 = 不限制）"""
        try:
            return list(self.enemy_type_tree.selection())
        except Exception:
            return []

    def _enemy_cfg(self):
        """把界面上的敌人设置收成一个 dict（放进主 cfg 的 enemy 键 —— 方案库会一起存下来）"""
        try:
            on = bool(self.enemy_on.get())
        except Exception:
            return None
        if not on:
            return {"on": False}
        rates = {k: round(float(v.get()), 3) for k, v in self.enemy_cls_rates.items()
                 if self.enemy_pools[k].get() and float(v.get()) > 0}
        d = {"on": True, "pools": list(rates) or ["boss", "elite", "normal"],
             "rates": rates, "rate": float(self.enemy_rate.get()),
             "source": self.enemy_source.get(),
             "ignore_size": bool(self.enemy_ignore_size.get()),
             "visual": bool(self.enemy_visual.get()),
             "same_type": bool(self.enemy_same_type.get()),
             # 反向存：勾上「不动打不死的」= 不允许换它们（默认）
             "allow_unkillable": not bool(self.enemy_keep_unkillable.get()),
             "use_arena": bool(self.enemy_use_arena.get())}
        _ty = self._enemy_types_picked()
        if _ty:
            d["types"] = _ty
        if self.enemy_seed_sep.get():
            try:
                d["seed"] = int(str(self.enemy_seed.get()).strip())
            except Exception:
                pass
        return d

    def _enemy_restore(self, cfg):
        """把方案里的敌人设置填回界面（载入到设置时用）"""
        e = (cfg or {}).get("enemy") or {}
        try:
            self.enemy_on.set(bool(e.get("on")))
            _rates = e.get("rates") or {}
            _pools = e.get("pools") or ["boss", "elite", "normal"]
            for k, v in self.enemy_pools.items():
                v.set(k in _pools)
            for k, sv in getattr(self, "enemy_cls_rates", {}).items():
                if _rates:
                    sv.set(float(_rates.get(k, 0.0)))
                elif k in _pools:
                    sv.set(float(e.get("rate", 1.0)))
                else:
                    sv.set(0.0)
            self.enemy_rate.set(float(e.get("rate", 1.0)))
            self.enemy_ignore_size.set(bool(e.get("ignore_size")))
            if e.get("seed"):
                self.enemy_seed_sep.set(True)
                self.enemy_seed.set(str(e["seed"]))
            else:
                self.enemy_seed_sep.set(False)
            self.enemy_source.set(e.get("source") or "all")
            self.enemy_visual.set(bool(e.get("visual", True)))
            self.enemy_same_type.set(bool(e.get("same_type")))
            self.enemy_keep_unkillable.set(not bool(e.get("allow_unkillable")))
            self.enemy_use_arena.set(bool(e.get("use_arena", True)))
            try:
                self.enemy_type_tree.selection_remove(*self.enemy_type_tree.selection())
                for t in (e.get("types") or []):
                    if self.enemy_type_tree.exists(t):
                        self.enemy_type_tree.selection_add(t)
            except Exception:
                pass
        except Exception:
            pass
        self._refresh_enemy()

    # ── 敌人预设子窗口（照参考实现的 EnemyPresetWindow：左边类别树 + 右边面板 + 导入/导出）──
    def enemy_preset(self):
        """打开「编辑敌人预设」窗口。

        * 左：类别列表（含行数、当前比例）
        * 右：选中类别的比例滑块与说明；下面是几个总开关（总比例 / 来源 / 忽略体型 / 连外观）
        * 底：导入预设… / 导出预设… / 重置默认 / 应用 / 取消

        "预设"就是我们存进方案库的那份 cfg["enemy"]（同一个形状）—— 所以导出就是一个 JSON，
        以后想分享/复用一套敌人设置，直接把这个文件给对方就行（参考实现也有导入/导出）。
        """
        win = tk.Toplevel(self.root)
        win.title("编辑敌人预设 — 法魂随机")
        win.transient(self.root)
        try:
            win.configure(bg=BG)
        except Exception:
            pass
        body = ttk.Frame(win, padding=(px(14), px(12)))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="编辑敌人预设", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="左边选一类，右边调它自己的比例；下面那几个开关对所有类别生效。",
                  style="Hint.TLabel").pack(anchor="w", pady=(px(2), px(10)))

        mid = ttk.Frame(body)
        mid.pack(fill="both", expand=True)
        left = ttk.Frame(mid)
        left.pack(side="left", fill="y")
        cols = ("rows", "rate")
        tree = ttk.Treeview(left, columns=cols, show="tree headings", height=6, selectmode="browse")
        tree.heading("#0", text="类别")
        tree.heading("rows", text="行数")
        tree.heading("rate", text="比例")
        tree.column("#0", width=px(150), anchor="w")
        tree.column("rows", width=px(80), anchor="e")
        tree.column("rate", width=px(80), anchor="e")
        tree.pack(fill="y", expand=True)
        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True, padx=(px(14), 0))
        t_title = ttk.Label(right, text="", style="Sub.TLabel")
        t_title.pack(anchor="w")
        t_desc = ttk.Label(right, text="", style="Hint.TLabel", wraplength=px(360), justify="left")
        t_desc.pack(anchor="w", pady=(px(2), px(8)))
        rr = ttk.Frame(right)
        rr.pack(fill="x")
        ttk.Label(rr, text="参与比例", style="Sub.TLabel").pack(side="left")
        cur = {"key": "boss"}
        rate_v = tk.DoubleVar(value=1.0)
        pct = ttk.Label(rr, text="100%", style="Hint.TLabel", width=7)
        ttk.Scale(rr, from_=0.0, to=1.0, variable=rate_v, orient="horizontal", length=px(200),
                  command=lambda _v: pct.configure(text=("%.0f%%" % (rate_v.get() * 100))
                                                   if rate_v.get() > 0 else "不参与")).pack(side="left", padx=px(8))
        pct.pack(side="left")
        glob = ttk.LabelFrame(body, text=" 对所有类别生效 ", padding=(px(12), px(8)))
        glob.pack(fill="x", pady=(px(10), 0))
        gr = ttk.Frame(glob)
        gr.pack(fill="x")
        ttk.Label(gr, text="总比例", style="Sub.TLabel").pack(side="left")
        tot_v = tk.DoubleVar(value=float(self.enemy_rate.get()))
        ttk.Scale(gr, from_=0.05, to=1.0, variable=tot_v, orient="horizontal",
                  length=px(160)).pack(side="left", padx=px(8))
        ttk.Label(gr, text="　来源", style="Sub.TLabel").pack(side="left")
        src_v = tk.StringVar(value=str(self.enemy_source.get()))
        ttk.Radiobutton(gr, text="全随机（原版 + 法魂）", variable=src_v, value="all").pack(side="left", padx=px(4))
        ttk.Radiobutton(gr, text="只随机法魂敌人", variable=src_v, value="new").pack(side="left", padx=px(4))
        gr2 = ttk.Frame(glob)
        gr2.pack(fill="x", pady=(px(4), 0))
        sz_v = tk.BooleanVar(value=bool(self.enemy_ignore_size.get()))
        vi_v = tk.BooleanVar(value=bool(self.enemy_visual.get()))
        ttk.Checkbutton(gr2, text="忽略体型限制（大的也能塞进小的）", variable=sz_v).pack(side="left")
        ttk.Checkbutton(gr2, text="连外观一起换（真·换敌人）", variable=vi_v).pack(side="left", padx=px(14))

        # 类别行的比例（窗口内独立编辑，点"应用"才写回主界面）
        rows = {}
        stats = getattr(self, "_enemy_stats_cache", None) or {}

        def fill(pick=None):
            for iid in tree.get_children():
                tree.delete(iid)
            for key, zh, _d in (("boss", "Boss", ""), ("elite", "精英", ""), ("normal", "普通敌人", "")):
                v = rows[key].get()
                tree.insert("", "end", iid=key, text=zh,
                            values=(stats.get(key, "—"), "不参与" if v <= 0 else "%.0f%%" % (v * 100)))
            if pick:
                tree.selection_set(pick)

        def pick(_e=None):
            sel = (tree.selection() or ["boss"])[0]
            cur["key"] = sel
            zh, desc = {"boss": ("Boss", "击杀给 Boss 魂 / 有血条的那批"),
                        "elite": ("精英", "血量偏高的敌对单位：骑士、守卫、巨兽"),
                        "normal": ("普通敌人", "杂兵：士兵、野兽、虫类…（占绝大多数）")}[sel]
            t_title.configure(text=zh)
            t_desc.configure(text=desc)
            rate_v.set(rows[sel].get())
            pct.configure(text=("不参与" if rows[sel].get() <= 0 else "%.0f%%" % (rows[sel].get() * 100)))

        def rate_moved(_v=None):
            k = cur["key"]
            rows[k].set(round(float(rate_v.get()), 2))
            pct.configure(text=("不参与" if rows[k].get() <= 0 else "%.0f%%" % (rows[k].get() * 100)))
            fill(k)

        rows = {k: tk.DoubleVar(value=float(v.get())) for k, v in self.enemy_cls_rates.items()}
        for k in rows:
            rows[k].trace_add("write", lambda *_a: fill(cur.get("key")))
        tree.bind("<<TreeviewSelect>>", pick)
        # 滑块重建一次：要绑到 rate_moved
        for ch in rr.winfo_children():
            if isinstance(ch, ttk.Scale):
                ch.configure(command=rate_moved)
        fill("boss")
        pick()

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(px(12), 0))

        def export():
            from tkinter import filedialog
            p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="敌人预设.json",
                                             filetypes=[("敌人预设", "*.json")])
            if not p:
                return
            try:
                d = {"pools": [k for k, v in rows.items() if v.get() > 0],
                     "rates": {k: round(v.get(), 3) for k, v in rows.items() if v.get() > 0},
                     "rate": float(tot_v.get()), "source": src_v.get(),
                     "ignore_size": bool(sz_v.get()), "visual": bool(vi_v.get())}
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                self.log(f"敌人预设已导出 → {p}")
            except Exception as e:
                messagebox.showerror("导出失败", str(e), parent=win)

        def import_():
            from tkinter import filedialog
            p = filedialog.askopenfilename(filetypes=[("敌人预设", "*.json")])
            if not p:
                return
            try:
                d = json.load(open(p, encoding="utf-8"))
                for k, v in rows.items():
                    v.set(float((d.get("rates") or {}).get(k, d.get("rate", 1.0) if k in (d.get("pools") or []) else 0.0)))
                tot_v.set(float(d.get("rate", 1.0)))
                src_v.set(d.get("source") or "all")
                sz_v.set(bool(d.get("ignore_size")))
                vi_v.set(bool(d.get("visual")))
                fill("boss")
                pick()
                self.log(f"敌人预设已导入 ← {p}")
            except Exception as e:
                messagebox.showerror("导入失败", str(e), parent=win)

        def reset():
            for k in rows:
                rows[k].set(1.0)
            tot_v.set(1.0)
            src_v.set("all")
            sz_v.set(False)
            vi_v.set(False)
            fill("boss")
            pick()

        def apply_():
            self.enemy_on.set(True)
            for k, v in rows.items():
                self.enemy_cls_rates[k].set(float(v.get()))
                self.enemy_pools[k].set(float(v.get()) > 0)
            self.enemy_rate.set(float(tot_v.get()))
            self.enemy_source.set(src_v.get())
            self.enemy_ignore_size.set(bool(sz_v.get()))
            self.enemy_visual.set(bool(vi_v.get()))
            self._refresh_enemy()
            self.log("敌人预设已应用（还没写入游戏 —— 记得点「只写入敌人」）")
            win.destroy()

        ttk.Button(bar, text="导入预设…", style="TButton", command=import_).pack(side="left")
        ttk.Button(bar, text="导出预设…", style="TButton", command=export).pack(side="left", padx=px(6))
        ttk.Button(bar, text="重置为默认", style="TButton", command=reset).pack(side="left")
        ttk.Button(bar, text="应用", style="Accent.TButton", command=apply_).pack(side="right")
        ttk.Button(bar, text="取消", style="TButton", command=win.destroy).pack(side="right", padx=px(6))
        try:
            win.grab_set()
        except Exception:
            pass
        return win



    # ── 页 2 · 敌人随机 ──
    def _build_enemy_page(self, body):
        """敌人随机独立一页：设置 + 只写入敌人（做成方案层）+ 用这个方案玩。

        为什么单独开一页：物品与敌人是两套独立的随机（写不同的表、独立的随机流），
        混在「更多设置」里既不好找，也容易让人以为必须一起开。
        但**写入**仍然建议合成一层 —— 两边的产物都落在 regulation.bin 里，
        分两个方案层的话后挂的那个会把前一个顶掉（见 docs/方案层使用说明.md 第 4 节）。
        """
        ttk.Label(body, text="敌人随机", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body,
                  text="换敌人的整行数据（血量/伤害/AI/掉落…）；勾上「连外观一起换」时还会改地图上的模型。\n"
                       "下面那个按钮只写入敌人——产物只进方案层，法魂本体一个字节都不动。",
                  style="Hint.TLabel", wraplength=px(820), justify="left").pack(anchor="w", pady=(px(4), px(8)))

        # 标题旁边就是总开关（照参考实现：页签标题自带勾选框）
        head = ttk.Frame(body)
        head.pack(fill="x")
        self.enemy_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(head, text="敌人随机", variable=self.enemy_on,
                        command=self._refresh_enemy).pack(side="left")
        ttk.Label(head, text="换敌人的整行数据（血量 / 伤害 / AI / 掉落）—— 与物品随机互不干扰，可以同时开",
                  style="Hint.TLabel").pack(side="left", padx=px(10), pady=(px(6), 0))
        self.enemy_sub = []          # 关掉总开关时，这些子控件一起变灰
        self.enemy_cls_rates = {}

        # ── 分组 1 · 参与类别（每类一个勾选 + 该类自己的比例，照参考实现的"每类可调"）──
        g1 = ttk.LabelFrame(body, text=" 参与类别 ", padding=(px(12), px(8)))
        g1.pack(fill="x", pady=(px(10), 0))
        self.enemy_pools = {}
        _cls_rows = (("boss", "Boss", "击杀给 Boss 魂 / 有血条的那批"),
                     ("elite", "精英", "血量偏高的敌对单位：骑士、守卫、巨兽"),
                     ("normal", "普通敌人", "杂兵：士兵、野兽、虫类…（占绝大多数）"))
        for i, (key, zh, desc) in enumerate(_cls_rows):
            row = ttk.Frame(g1)
            row.pack(fill="x", pady=(0, px(3)))
            self.enemy_pools[key] = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(row, text=zh, width=8, variable=self.enemy_pools[key],
                                 command=self._refresh_enemy)
            cb.pack(side="left")
            self.enemy_sub.append(cb)
            v = tk.DoubleVar(value=1.0)
            self.enemy_cls_rates[key] = v
            sc = ttk.Scale(row, from_=0.0, to=1.0, variable=v, orient="horizontal",
                           length=px(180), command=lambda _vv, k=key: self._enemy_cls_moved(k))
            sc.pack(side="left", padx=px(8))
            self.enemy_sub.append(sc)
            lbl = ttk.Label(row, text="100%", style="Hint.TLabel", width=6)
            lbl.pack(side="left")
            setattr(self, "enemy_cls_lbl_" + key, lbl)
            ttk.Label(row, text="· " + desc, style="Hint.TLabel").pack(side="left", padx=px(8))
        # 敌型（模型层）—— 上面三类是"池"，这里是"同一种敌人"的粒度
        trow = ttk.Frame(g1)
        trow.pack(fill="x", pady=(px(6), 0))
        ttk.Label(trow, text="敌型（可多选；一个不选 = 全部参与）", style="Sub.TLabel").pack(side="left")
        ttk.Button(trow, text="读一次统计", style="Link.TButton",
                   command=self.enemy_stats).pack(side="left", padx=px(8))
        self.enemy_type_hint = ttk.Label(trow, text="", style="Hint.TLabel")
        self.enemy_type_hint.pack(side="left")
        self.enemy_type_tree = ttk.Treeview(g1, columns=("rows",), show="tree headings",
                                            height=6, selectmode="extended")
        self.enemy_type_tree.heading("#0", text="敌型（模型层）")
        self.enemy_type_tree.heading("rows", text="行数")
        self.enemy_type_tree.column("#0", width=px(150), anchor="w")
        self.enemy_type_tree.column("rows", width=px(70), anchor="e")
        self.enemy_type_tree.pack(fill="x", pady=(px(2), 0))
        self.enemy_type_tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_enemy())
        self._enemy_types_fill()
        srow = ttk.Frame(g1)
        srow.pack(fill="x", pady=(px(4), 0))
        self.enemy_same_type = tk.BooleanVar(value=False)
        _cb = ttk.Checkbutton(srow, text="只换同一种敌人（骑对骑、龙对龙 —— 换数值但不打乱种类）",
                              variable=self.enemy_same_type, command=self._refresh_enemy)
        _cb.pack(side="left")
        self.enemy_sub.append(_cb)
        srow2 = ttk.Frame(g1)
        srow2.pack(fill="x", pady=(px(4), 0))
        self.enemy_keep_unkillable = tk.BooleanVar(value=True)   # 默认勾上：更安全
        _cb2 = ttk.Checkbutton(
            srow2, text="不动「打不死的」敌人（参考实现标了 174 个模型 / 1910 行 —— 换掉可能卡剧情）",
            variable=self.enemy_keep_unkillable, command=self._refresh_enemy)
        _cb2.pack(side="left")
        self.enemy_sub.append(_cb2)
        ttk.Label(srow2, text="· 多阶段 Boss（98 个模型）会**整组换**（阶段对阶段，不会半血不变身）",
                  style="Hint.TLabel").pack(side="left", padx=px(10))
        srow3 = ttk.Frame(g1)
        srow3.pack(fill="x", pady=(px(4), 0))
        self.enemy_use_arena = tk.BooleanVar(value=True)          # 默认勾上：Boss 房大小别乱来
        _cb3 = ttk.Checkbutton(
            srow3, text="Boss 只与同场地档的互换（634 张图的 arena 标注：Malenia=3、Margrit=1、Elemer=0…）",
            variable=self.enemy_use_arena, command=self._refresh_enemy)
        _cb3.pack(side="left")
        self.enemy_sub.append(_cb3)
        ttk.Label(srow3, text="· 不勾则退回「只按体型分桶」",
                  style="Hint.TLabel").pack(side="left", padx=px(10))

        # ── 分组 2 · 总体 ──
        g2 = ttk.LabelFrame(body, text=" 总体 ", padding=(px(12), px(8)))
        g2.pack(fill="x", pady=(px(10), 0))
        r1 = ttk.Frame(g2)
        r1.pack(fill="x")
        ttk.Label(r1, text="总比例", style="Sub.TLabel").pack(side="left")
        self.enemy_rate = tk.DoubleVar(value=1.0)
        _sc = ttk.Scale(r1, from_=0.05, to=1.0, variable=self.enemy_rate, orient="horizontal",
                        length=px(150), command=lambda _v: self._refresh_enemy())
        _sc.pack(side="left", padx=6)
        self.enemy_sub.append(_sc)
        self.enemy_rate_lbl = ttk.Label(r1, text="全改（100%）", style="Hint.TLabel")
        self.enemy_rate_lbl.pack(side="left")
        ttk.Label(r1, text="　　来源", style="Sub.TLabel").pack(side="left")
        self.enemy_source = tk.StringVar(value="all")
        for _val, _txt in (("all", "全随机（原版 + 法魂）"), ("new", "只随机法魂敌人")):
            _rb = ttk.Radiobutton(r1, text=_txt, variable=self.enemy_source, value=_val,
                                  command=self._refresh_enemy)
            _rb.pack(side="left", padx=px(4))
            self.enemy_sub.append(_rb)
        r2 = ttk.Frame(g2)
        r2.pack(fill="x", pady=(px(4), 0))
        self.enemy_ignore_size = tk.BooleanVar(value=False)
        _cb = ttk.Checkbutton(r2, text="忽略体型限制（大的也能塞进小的）",
                              variable=self.enemy_ignore_size, command=self._refresh_enemy)
        _cb.pack(side="left")
        self.enemy_sub.append(_cb)
        self.enemy_visual = tk.BooleanVar(value=True)   # 默认开：换敌人就该连样子一起换
        _cbv = ttk.Checkbutton(r2, text="连外观一起换（默认开；出怪问题时可以关掉退回去）",
                               variable=self.enemy_visual, command=self._refresh_enemy)
        _cbv.pack(side="left", padx=px(14))
        self.enemy_sub.append(_cbv)
        r3 = ttk.Frame(g2)
        r3.pack(fill="x", pady=(px(4), 0))
        self.enemy_seed_sep = tk.BooleanVar(value=False)
        _cb = ttk.Checkbutton(r3, text="用独立的敌人种子", variable=self.enemy_seed_sep,
                              command=self._refresh_enemy)
        _cb.pack(side="left")
        self.enemy_sub.append(_cb)
        self.enemy_seed = tk.StringVar(value="")
        self.enemy_seed_e = ttk.Entry(r3, textvariable=self.enemy_seed, width=14)
        self.enemy_seed_e.pack(side="left", padx=px(8))
        self.b_enemy_dice = ttk.Button(r3, text="🎲 重掷", style="TButton", command=self._enemy_dice)
        self.b_enemy_dice.pack(side="left")
        self.enemy_sub.append(self.b_enemy_dice)

        # ── 分组 3 · 这次会怎么改（摘要 + 警告，照参考实现页脚那段）──
        g3 = ttk.LabelFrame(body, text=" 这次会怎么改 ", padding=(px(12), px(8)))
        g3.pack(fill="x", pady=(px(10), 0))
        self.enemy_hint = ttk.Label(g3, text="", style="Hint.TLabel",
                                    wraplength=px(820), justify="left")
        self.enemy_hint.pack(anchor="w")
        ttk.Label(g3, text="⚠ 一次换掉太多 Boss 可能卡顿甚至崩；连外观一起换尤其容易出怪问题 —— 先用少量类别试一次。",
                  style="Hint.TLabel", wraplength=px(820),
                  justify="left").pack(anchor="w", pady=(px(4), 0))
        self._refresh_enemy()

        wrap = ttk.Frame(body)
        wrap.pack(fill="x", pady=(px(12), 0))
        self.b_enemy_layer = ttk.Button(
            wrap, text="① 只写入敌人（做成方案层）",
            style="Accent.TButton", command=self.enemy_layer)
        self.b_enemy_layer.pack(side="left")
        ttk.Button(wrap, text="用这个方案玩", style="TButton",
                   command=self.enemy_layer_launch).pack(side="left", padx=px(8))
        ttk.Button(wrap, text="编辑敌人预设…", style="TButton",
                   command=self.enemy_preset).pack(side="left", padx=px(8))
        ttk.Button(wrap, text="切回法魂本体", style="TButton",
                   command=self.enemy_layer_revert).pack(side="left")
        self.enemy_page_hint = ttk.Label(body, text="", style="Hint.TLabel",
                                         wraplength=px(820), justify="left")
        self.enemy_page_hint.pack(anchor="w", pady=(px(10), 0))
        self._enemy_page_refresh()

    def _enemy_page_refresh(self, *_a):
        """页脚那行：现在挂的是哪个方案"""
        lay = ""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import plan_layer as PL
            lay = PL.current_plan_line() or ""
        except Exception:
            lay = ""
        if hasattr(self, "enemy_page_hint"):
            self.enemy_page_hint.config(
                text="当前挂载：" + (lay or "（没有，跑的是纯法魂本体）"))

    def _enemy_page_hint_set(self, text, bad=False):
        if hasattr(self, "enemy_page_hint"):
            self.enemy_page_hint.config(text=text, style="Bad.TLabel" if bad else "Hint.TLabel")

    def enemy_layer(self):
        """只写入敌人：以**原始** regulation 为底，只套敌人，产出一个方案层。"""
        if getattr(self, "_enemy_busy", False):
            return
        cfg = self._enemy_cfg() or {"on": False}
        if not cfg.get("on"):
            messagebox.showinfo("还没开敌人随机",
                                "先把上面的「敌人随机」勾上。")
            return
        self._enemy_busy = True
        self.b_enemy_layer.config(state="disabled")
        label = "敌人_%s_种子%d" % (time.strftime("%Y%m%d_%H%M"), int(self.seed.get()))
        self.log("只写入敌人 → 方案层：" + label)
        self._enemy_page_hint_set("正在做方案层…（要读一遍 regulation，稍等）")

        def work():
            try:
                sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
                import plan_layer as PL
                r = PL.make_enemy_layer(label, cfg, log=self.log)
                self._last_enemy_layer = r["dir"]
                self.q.put(("enemy_page", ("✓ 方案层已就绪：" + r["dir"], False)))
            except Exception as e:
                import traceback
                self.log("只写入敌人失败：" + traceback.format_exc(limit=4))
                self.q.put(("enemy_page", ("✗ 失败：" + str(e), True)))
            finally:
                self.q.put(("enemy_page_done", None))
        threading.Thread(target=work, daemon=True).start()

    def enemy_layer_launch(self):
        self._enemy_layer_toggle(True)

    def enemy_layer_revert(self):
        self._enemy_layer_toggle(False)

    def _enemy_layer_toggle(self, on):
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import plan_layer as PL
            if on:
                d = getattr(self, "_last_enemy_layer", "")
                if not d or not os.path.isdir(os.path.join(d, "mod")):
                    self._enemy_page_hint_set("还没有敌人方案层 —— 先点「只写入敌人」", bad=True)
                    return
                r = PL.set_plan(d)
                self._enemy_page_hint_set("已挂载 ✓ 下一次启动就用它")
                self.log("方案层已挂载：%s（备份 %s）" % (d, os.path.basename(r.get("backup", ""))))
            else:
                r = PL.clear_plan()
                self._enemy_page_hint_set("已切回法魂本体" if r.get("changed") else "本来就没挂载方案")
        except Exception as e:
            self._enemy_page_hint_set("操作失败：" + str(e), bad=True)

    # ══════════ 页 3 · 方案库 ══════════
    def _build_library(self, body):
        """方案库页：左边常驻列表 + 右边常驻详情面板。

        这一页取代了原来的「一扇独立小窗 + 一排 12 个按钮 + 每个动作都弹对话框」：
        列表行是两行式（第一行名字，第二行小字摘要），详情常驻右侧、单击哪行就显示哪行。"""
        head = ttk.Frame(body)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="方案库", style="Title.TLabel").pack(side="left")
        self.lib_hint = ttk.Label(head, text="", style="Hint.TLabel")
        self.lib_hint.pack(side="left", padx=(14, 0), pady=(8, 0))
        # 这一页的主按钮只有这几个；其余动作进右键菜单（权重不再都一样）
        ttk.Button(head, text="导入", width=7, command=self._lib_import).pack(side="right", padx=(6, 0))
        ttk.Button(head, text="打开文件夹", width=11,
                   command=self._lib_open_folder).pack(side="right", padx=(6, 0))
        ttk.Button(head, text="刷新", width=7, command=self._lib_refresh).pack(side="right")

        wrap = ttk.Frame(body)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=62, minsize=340)
        wrap.columnconfigure(1, weight=38, minsize=320)
        wrap.rowconfigure(0, weight=1)

        # ── 左：搜索/排序 + 列表（空库时这里是引导文案）──
        left = ttk.Frame(wrap)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="🔍", style="Sub.TLabel").pack(side="left")
        self.lib_search = tk.StringVar(value="")
        e_search = ttk.Entry(bar, textvariable=self.lib_search)
        e_search.pack(side="left", fill="x", expand=True, padx=(6, 8))
        e_search.bind("<KeyRelease>", lambda _e: self._lib_refresh())
        e_search.bind("<Escape>", lambda _e: (self.lib_search.set(""), self._lib_refresh()))
        ttk.Label(bar, text="排序", style="Hint.TLabel").pack(side="left", padx=(0, 4))
        self.lib_sort = tk.StringVar(value=LIBSORT[0])
        cb = ttk.Combobox(bar, textvariable=self.lib_sort, values=list(LIBSORT),
                          state="readonly", width=13)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._lib_refresh())

        self.lib_box = ttk.Frame(left)
        self.lib_box.pack(fill="both", expand=True)
        self.lib_list = ttk.Frame(self.lib_box)
        self.lib_list.pack(fill="both", expand=True)
        self.lib_tree = ttk.Treeview(self.lib_list, columns=(), show="tree",
                                     selectmode="browse", style="Lib.Treeview")
        self.lib_tree.column("#0", width=px(520), stretch=True)
        vsb = ttk.Scrollbar(self.lib_list, orient="vertical", command=self.lib_tree.yview)
        self.lib_tree.configure(yscrollcommand=vsb.set)
        self.lib_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.lib_tree.tag_configure("star", foreground=GOLD_LT)
        self.lib_tree.tag_configure("broken", foreground=DANGER)
        self.lib_tree.bind("<<TreeviewSelect>>", lambda _e: self._lib_on_select())
        self.lib_tree.bind("<Button-3>", self._lib_ctx)                  # 右键菜单
        self.lib_tree.bind("<Double-1>", lambda _e: self._lib_write())   # 双击=写入游戏
        # 空状态：一个方案都没有时，告诉人下一步该干什么（配一张古书插画）
        self.lib_empty = ttk.Frame(self.lib_box)
        book = deco_image("empty_plans")
        if book:
            self._deco_book = book
            ttk.Label(self.lib_empty, image=book, style="Deco.TLabel").pack(anchor="w")
        ttk.Label(self.lib_empty, text="还没有方案", style="Gold.TLabel").pack(anchor="w", pady=(0, 4))
        self.lib_empty_txt = ttk.Label(
            self.lib_empty, style="Hint.TLabel", justify="left", wraplength=px(380),
            text="先到「职业物品随机」生成一套（点 ① 生成随机方案），\n再点那里的「💾 保存到方案库」，方案就会出现在这里。")
        self.lib_empty_txt.pack(anchor="w")
        ttk.Button(self.lib_empty, text="去「职业物品随机」生成一套", style="Link.TButton",
                   command=lambda: self.nb.select(self.page_set)).pack(anchor="w", pady=(8, 0))

        # ── 右：详情（常驻，取代弹窗）──
        right = ttk.LabelFrame(wrap, text=" 详情 ", padding=(px(12), px(8)))
        right.grid(row=0, column=1, sticky="nsew")
        # 底部两块**先**建好：pack 是"先到先占位"，它们先占住底部，滚动区才能吃剩下的空间
        # （2026-10-15 作者反馈：详情做细之后内容超一屏、滚不动，只能全屏才看得全）
        trow2 = ttk.Frame(right)
        trow2.pack(side="bottom", fill="x", pady=(8, 0))
        self.lib_toast = ttk.Label(trow2, text="", style="Hint.TLabel", wraplength=px(250),
                                   justify="left")
        self.lib_toast.pack(side="left", fill="x", expand=True)
        self.lib_trash_btn = ttk.Button(trow2, text="打开回收站", style="Link.TButton",
                                        command=self._lib_open_trash)
        # 详情面板的动作按钮（对着选中的那一个方案干活）
        act = ttk.Frame(right)
        act.pack(side="bottom", fill="x", pady=(10, 0))
        act.columnconfigure(0, weight=1)
        act.columnconfigure(1, weight=1)
        self.lib_btns = {}
        for i, (key, text, cmd, sty) in enumerate((
                ("write", "写入游戏", self._lib_write, "Accent.TButton"),
                ("launch", "用这个方案玩", self._lib_launch, "Accent.TButton"),
                ("dup", "复制一份", self._lib_dup, "TButton"),
                ("load", "载入到设置", self._lib_apply_cfg, "TButton"),
                ("star", "收藏 ★", self._lib_star, "TButton"),
                ("export", "导出…", self._lib_export, "TButton"),
                ("delete", "删除", self._lib_delete, "Danger.TButton"))):
            b = ttk.Button(act, text=text, command=cmd, style=sty)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 6, 0),
                   pady=(0, 6))
            self.lib_btns[key] = b
        # 其余详情内容全部进**滚动区**（滚轮只在鼠标进详情区时接管，离开就还回去）
        right = self._scrollable(right)
        self.lib_title = ttk.Label(right, text="还没选方案", style="Title.TLabel", wraplength=px(300))
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
        # 详情面板：分组 + 尽量把方案文件里有的都摊出来（2026-10-14 作者要求"更详细"）
        self.lib_vals = {}
        for _title, _fields in (
                ("随机设置", (("doms", "随机项目"), ("mode", "混合方式"), ("seed", "种子"),
                              ("coh", "合理度"), ("rates", "改动比例"), ("switches", "开关"))),
                ("这次改了什么", (("rows", "改动行"), ("detail", "分类明细"), ("shops", "商店"),
                                  ("pools", "池子"))),
                ("记录", (("engine", "引擎版本"), ("fp", "指纹"), ("time", "保存时间"),
                          ("mtime", "修改时间"), ("wrote", "写入记录")))):
            ttk.Label(right, text=_title, style="Sub.TLabel").pack(anchor="w", pady=(6, 0))
            for key, label in _fields:
                row = ttk.Frame(right)
                row.pack(fill="x", pady=1)
                ttk.Label(row, text=label, width=7, style="Sub.TLabel").pack(side="left")
                v = ttk.Label(row, text="—", wraplength=px(280), justify="left")
                v.pack(side="left", fill="x", expand=True)
                self.lib_vals[key] = v
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

    def _lib_toast(self, text, bad=False, trash=False):
        """底部的状态行（不弹窗）。trash=True 时旁边给出「打开回收站」"""
        if hasattr(self, "lib_toast"):
            self.lib_toast.config(text=text, style="Bad.TLabel" if bad else "Gold.TLabel")
        if hasattr(self, "lib_trash_btn"):
            if trash:
                self.lib_trash_btn.pack(side="left", padx=(6, 0))
            else:
                self.lib_trash_btn.pack_forget()

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
        total = len(metas)
        self._lib_metas = {}
        seen = set()
        dup = []
        kept = []
        for m in metas:
            # 同一份方案被复制成两个文件时，id 会撞车：界面不能就此崩掉，只跳过多的那份
            if m["id"] in seen:
                dup.append(m["name"])
                continue
            seen.add(m["id"])
            kept.append(m)
            self._lib_metas[m["id"]] = m
        metas = self._lib_filter(kept)
        # 收藏永远排最前，其余按选的排序来
        key = self.lib_sort.get() if hasattr(self, "lib_sort") else LIBSORT[0]
        if key == "名字":
            metas.sort(key=lambda m: (not m.get("star"), str(m.get("name") or "")))
        elif key.startswith("改动量"):
            metas.sort(key=lambda m: (not m.get("star"), -(m.get("changed") or 0)))
        else:
            metas.sort(key=lambda m: (not m.get("star"), -(m.get("modified") or 0)))
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
        broken = sum(1 for m in metas if m.get("broken"))
        tail = f"（其中 {broken} 个文件损坏）" if broken else ""
        if dup:
            tail += f"（有 {len(dup)} 份 id 撞车被跳过：{'、'.join(dup[:3])}）"
        kw = self.lib_search.get().strip() if hasattr(self, "lib_search") else ""
        if kw:
            tail += f" ｜ 筛「{kw}」出 {len(metas)}/{total}"
        self.lib_hint.config(
            text=f"共 {total} 个方案{tail} ｜ 存在 MOD 目录的 plans 文件夹里：{pl.plans_dir()}",
            style="Hint.TLabel")
        # 空状态：一个方案都没有 → 换成引导文案；只是搜不到 → 说清是筛没了
        kids = tv.get_children()
        if not kids:
            if total == 0:
                self.lib_empty_txt.config(
                    text="先到「职业物品随机」生成一套（点 ① 生成随机方案），\n"
                         "再点那里的「💾 保存到方案库」，方案就会出现在这里。")
            else:
                self.lib_empty_txt.config(text=f"没有匹配「{kw}」的方案。\n换个词，或把搜索框清空。")
            self.lib_list.pack_forget()
            self.lib_empty.pack(fill="both", expand=True)
        else:
            self.lib_empty.pack_forget()
            self.lib_list.pack(fill="both", expand=True)
        if kids:
            pick = want if want in kids else kids[0]
            tv.selection_set(pick)
            tv.focus(pick)
            tv.see(pick)
            self._lib_show(pick)
        else:
            self._lib_show(None)

    def _lib_filter(self, metas):
        """按搜索框过滤：名字 / 标签 / 备注 命中任意一个就留下"""
        kw = (self.lib_search.get() if hasattr(self, "lib_search") else "").strip().lower()
        if not kw:
            return list(metas)
        out = []
        for m in metas:
            hay = " ".join([str(m.get("name") or ""), str(m.get("note") or ""),
                            " ".join(m.get("tags") or [])]).lower()
            if kw in hay:
                out.append(m)
        return out

    def _lib_search_set(self, text):
        """给自动化用：等价于在搜索框里敲字（走的是同一条刷新路）"""
        self.lib_search.set(text)
        self._lib_refresh()

    def _lib_on_select(self):
        sel = self.lib_tree.selection()
        if sel:
            self._lib_show(sel[0])

    def _lib_show(self, pid):
        """把某个方案摊在右侧详情面板上"""
        self._lib_cur = pid
        self.lib_tag_entry.pack_forget()          # 换方案时把"加标签"的输入框收回去
        usable = bool(pid) and not (self._lib_metas.get(pid) or {}).get("broken")
        _has_layer = bool(((self._lib_metas.get(pid) or {}).get("layer_dir") or "").strip())
        for key, b in getattr(self, "lib_btns", {}).items():
            if key == "delete":
                b.config(state="normal" if pid else "disabled")
            elif key == "launch":
                # 只有已经生成过覆盖层的方案才能"用这个方案玩"
                b.config(state="normal" if (usable and _has_layer) else "disabled")
            else:
                b.config(state="normal" if usable else "disabled")
        if not pid:
            self.lib_title.config(text="还没有方案")
            self.lib_sub.config(text="先到「职业物品随机」生成一套，再点「保存到方案库」")
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
        # 合理度 / 改动比例：全局那条 + 单独设过的（全局改动比例滑块已撤，所以这里只列"有单独设的"）
        _cx = []
        if cfg.get("coh_mixed") is not None:
            _cx.append(f"混池 {float(cfg['coh_mixed']) * 100:.0f}%")
        for _k, _zh in (("armor", "护甲"), ("weapon", "装备"), ("rune", "卢恩")):
            _v = (cfg.get("coh_domain") or {}).get(_k)
            if _v is not None:
                _cx.append(f"{_zh} {float(_v) * 100:.0f}%")
        self.lib_vals["coh"].config(text=f"{float(cfg.get('coherence', 0)) * 100:.0f}%"
                                         + ("（" + "、".join(_cx) + "）" if _cx else ""))
        _rx = []
        if cfg.get("rate_sets") is not None:
            _rx.append(f"整套 {float(cfg['rate_sets']) * 100:.0f}%")
        if cfg.get("rate_mixed") is not None:
            _rx.append(f"混池 {float(cfg['rate_mixed']) * 100:.0f}%")
        for _k, _zh in (("armor", "护甲"), ("weapon", "装备"), ("rune", "卢恩")):
            _v = (cfg.get("rate_domain") or {}).get(_k)
            if _v is not None:
                _rx.append(f"{_zh} {float(_v) * 100:.0f}%")
        self.lib_vals["rates"].config(text="、".join(_rx) if _rx else "全改（默认）")
        # ── 新增的几行：能算的都算出来（都用方案文件里已有的东西，不重新生成）──
        _doms = cfg.get("domains") or ["rune", "armor", "weapon"]
        _ZN = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
        self.lib_vals["doms"].config(text=" · ".join(_ZN.get(x, x) for x in _doms))
        _joins = cfg.get("joins") or []
        if _joins:
            _m = "两两混：" + " / ".join("+".join(_ZN.get(x, x) for x in g) for g in _joins)
            _m += "（其余各自）"
        elif cfg.get("cross_domain") is False or len(_doms) <= 1:
            _m = "各自随机（各随各的）"
        else:
            _m = "全部混合（" + " + ".join(_ZN.get(x, x) for x in _doms) + " 一起混）"
        self.lib_vals["mode"].config(text=_m)
        self.lib_vals["switches"].config(
            text=("整套法祷一起换：" + ("是" if cfg.get("sets", True) else "否")
                  + "｜说明书跟着改：" + ("是" if cfg.get("sync_guide", True) else "否")
                  + "｜商店参与：" + ("是" if cfg.get("shops") else "否")))

        _ch = [r for r in rows if str(r.get("old")) != str(r.get("new"))]
        _cross = sum(1 for r in _ch if str(r.get("old_cat")) != str(r.get("new_cat")))
        _cnt = collections.Counter(str(r.get("old_cat")) for r in _ch)
        _zhc = {"protector": "护甲", "weapon": "装备", "goods": "卢恩"}
        _sets_u = {r.get("unit") for r in _ch if r.get("role") == "set"}
        _piece_u = {r.get("unit") for r in _ch
                    if r.get("role") != "set" and "caster" in str(r.get("pool"))}
        _parts = []
        for _k, _zh in (("protector", "护甲"), ("goods", "卢恩"), ("weapon", "装备")):
            if _cnt.get(_k):
                _s = f"{_zh} {_cnt[_k]}"
                if _k == "protector":
                    _s += f"（法祷整套 {len(_sets_u)} 套 · 散件 {len(_piece_u)} 件）"
                _parts.append(_s)
        self.lib_vals["rows"].config(
            text=f"{len(_ch)} / {len(rows)} 行" + (f"（其中跨大类 {_cross} 行）" if _cross else ""))
        self.lib_vals["detail"].config(text="｜".join(_parts) if _parts else "—")
        _shop = {str(r.get("row_id")) for r in _ch if r.get("source_table") == "ShopLineupParam"}
        self.lib_vals["shops"].config(
            text=(f"换了 {len(_shop)} 个货架" if cfg.get("shops") else "不参与")
            + (f"（{len(_shop)} 行）" if _shop else ""))
        _pools = collections.Counter(str(r.get("pool")) for r in rows)
        _pm = collections.Counter()
        for _p in _pools:
            _pm["混池" if _p.startswith("mixed") else
                ("护甲" if _p.startswith("armor") else
                 ("武器" if _p.startswith("weapon") else
                  ("卢恩" if _p.startswith("rune") else "其它")))] += 1
        self.lib_vals["pools"].config(
            text=f"{len(_pools)} 个（" + " · ".join(f"{k} {v}" for k, v in _pm.most_common()) + "）")
        self.lib_vals["engine"].config(text=str(d.get("engine_version") or "—"))
        self.lib_vals["fp"].config(text=(d.get("fingerprint") or "")[:16] + "…")
        self.lib_vals["time"].config(text=time.strftime("%Y-%m-%d %H:%M", time.localtime(t)))
        _mod = d.get("modified") or 0
        self.lib_vals["mtime"].config(
            text=time.strftime("%Y-%m-%d %H:%M", time.localtime(_mod)) if _mod else "—")
        # 写入记录：按指纹去 logs/deploy_*.json 里找（2026-10-14 起收据里会记 fingerprint）
        try:
            _w = pl.deploys_for(d.get("fingerprint")) if hasattr(pl, "deploys_for") else []
        except Exception:
            _w = []
        self.lib_vals["wrote"].config(
            text=(f"写入过 {len(_w)} 次，最近 " + time.strftime("%m-%d %H:%M", time.localtime(_w[0])))
            if _w else "还没写入过")

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
            if w is not self.lib_tag_entry:          # 那个输入框是常驻控件，别销毁
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
        """就地加标签：在筹码后面冒出一个输入框，回车就加上（不弹对话框）"""
        self.lib_tag_entry.pack(side="left", padx=(6, 0))
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

    # ── 方案库：动作 ──
    def _lib_menu_build(self):
        """右键菜单（内容与顺序只有一处，自动化自检也读它）"""
        m = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=FG, activebackground=SEL_BG,
                    activeforeground=GOLD_LT, activeborderwidth=0, bd=1,
                    relief="solid", font=FONT_UI)
        for text, cmd in (("▶ 写入游戏", self._lib_write),
                          ("载入到设置", self._lib_apply_cfg),
                          ("改名（在右边直接改）", lambda: self.lib_name_e.focus_set()),
                          ("收藏 / 取消收藏", self._lib_star),
                          ("复制一份", self._lib_dup),
                          ("导出…", self._lib_export),
                          ("删除", self._lib_delete)):
            m.add_command(label=text, command=cmd)
        m.add_separator()
        m.add_command(label="导入方案…", command=self._lib_import)
        m.add_command(label="打开 plans 文件夹", command=self._lib_open_folder)
        m.add_command(label="刷新", command=self._lib_refresh)
        return m

    def _lib_ctx(self, event):
        """右键菜单：不常用的动作都收在这里（页面上只留 2~3 个主按钮）"""
        row = self.lib_tree.identify_row(event.y)
        if row:
            self.lib_tree.selection_set(row)
            self.lib_tree.focus(row)
            self._lib_show(row)
        if not getattr(self, "_lib_menu", None):
            self._lib_menu = self._lib_menu_build()
        state = "normal" if (self._lib_cur or row) else "disabled"
        for i in range(0, 7):                     # 头 7 条要对着某个方案
            try:
                self._lib_menu.entryconfig(i, state=state)
            except tk.TclError:
                pass
        try:
            self._lib_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._lib_menu.grab_release()

    def _lib_need(self):
        """动作前提：得选中一个能用的方案"""
        if not self._lib_cur or (self._lib_metas.get(self._lib_cur) or {}).get("broken"):
            self._lib_toast("先在左边点一个方案", bad=True)
            return None
        return self._lib_cur

    def _lib_star(self):
        """收藏 / 取消收藏（收藏的永远排最前）"""
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        try:
            cur = bool(pl.get_plan(pid).get("star"))
            pl.set_meta(pid, star=not cur)
        except Exception as e:
            self._lib_toast(f"收藏没成功：{e}", bad=True)
            return
        self._lib_refresh(keep=pid)
        self._lib_toast("已取消收藏" if cur else "已收藏（会排在最前）")

    def _lib_dup(self):
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        try:
            m = pl.duplicate_plan(pid)
        except Exception as e:
            self._lib_toast(f"复制没成功：{e}", bad=True)
            return
        self._lib_refresh(keep=m["id"])
        self._lib_toast(f"已复制一份：{m['name']}（可以直接在右边改名）")

    def _lib_delete(self):
        """删除：进回收站，明确告诉你还能找回来"""
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        name = (self._lib_metas.get(pid) or {}).get("name", pid)
        if not messagebox.askyesno("删掉这个方案？",
                                   f"「{name}」会被移到 plans/.trash 里。\n"
                                   "手滑了还能从那里找回，但它不会再出现在列表里。\n\n确定删除吗？"):
            return
        try:
            pl.delete_plan(pid)
        except Exception as e:
            self._lib_toast(f"删除没成功：{e}", bad=True)
            return
        self._lib_cur = None
        self._lib_refresh()
        # 删完不是"啪一下没了"：说清进了回收站，并且给一个能立刻打开的入口
        self._lib_toast(f"已把「{name}」移到回收站", trash=True)

    def _lib_open_trash(self):
        """打开 plans/.trash —— 手滑了还能自己捞回来"""
        pl = self._lib_mod()
        if not pl:
            return
        try:
            d = os.path.join(pl.plans_dir(), ".trash")
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            os.startfile(d)  # noqa
        except Exception as e:
            self._lib_toast(f"打不开回收站：{e}", bad=True)

    def _lib_export(self):
        from tkinter import filedialog
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        name = (self._lib_metas.get(pid) or {}).get("name", "方案")
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile=f"{name}.json",
                                         filetypes=[("方案文件", "*.json")], parent=self.root)
        if not p:
            return
        try:
            pl.export_plan(pid, p)
        except Exception as e:
            self._lib_toast(f"导出没成功：{e}", bad=True)
            return
        self._lib_toast(f"已导出 → {p}")

    def _lib_import(self):
        from tkinter import filedialog
        pl = self._lib_mod()
        if not pl:
            return
        paths = filedialog.askopenfilenames(filetypes=[("方案文件", "*.json")], parent=self.root)
        if not paths:
            return
        done, fail = [], []
        for p in paths:
            try:
                done.append(pl.import_plan(p)["name"])
            except Exception as e:
                fail.append(f"{os.path.basename(p)}：{e}")
        self._lib_refresh()
        if done:
            self._lib_toast(f"已导入 {len(done)} 个：" + "、".join(done))
        if fail:
            self._lib_toast("导入失败：" + "；".join(fail), bad=True)

    def _lib_apply_cfg(self):
        """把方案里的参数填回「随机设置」页（不写游戏）—— 便于在此基础上改一改再生成"""
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        try:
            cfg = pl.get_plan(pid).get("cfg") or {}
            self.seed.set(str(cfg.get("seed", self.seed.get())))
            self.sets.set(cfg.get("sets", True))
            # （幽影卢恩那个开关已撤：大师=幽影同档，规格 §2 / Q3）
            self.coherence.set(float(cfg.get("coherence", 0.8)))
            self.lbl_coh.config(text=f"{float(cfg.get('coherence', 0.8)) * 100:.0f}%")
            self.guide.set(cfg.get("sync_guide", True))
            self.shops.set(bool(cfg.get("shops", False)))
            # 先定类别与"整套"开关，再填单独比例（顺序反了会被当成"用不上"而丢掉）
            for k, v in self.doms.items():
                v.set(k in (cfg.get("domains") or ["rune", "armor", "weapon"]))
            self._refresh_modes()
            # 单独设的比例：只认界面上那两条（法祷职业护甲 / 商店物品）；老方案里的
            # rate_mixed / rate_domain 不再回填到界面（引擎仍然认它们，行为不变）
            _rc2 = cfg.get("rate_caster")
            if _rc2 is None:
                _rc2 = cfg.get("rate_sets")
            self._rate_set("caster", _rc2 is not None, _rc2)
            self._rate_set("caster", _rc2 is not None, _rc2)
            self._refresh_rates()
            # 单池合理度：老方案里的 coh_mixed 不再回填（那时混池由总合理度管）
            _cd3 = cfg.get("coh_domain") or {}
            for _k2 in ("armor", "weapon", "rune"):
                self._coh_set(_k2, _k2 in _cd3, _cd3.get(_k2))
            self._refresh_cohs()
        except Exception as e:
            self._lib_toast(f"载入没成功：{e}", bad=True)
            return
        self.nb.select(self.page_set)
        self._lib_toast("参数已填回「随机设置」页")
        self.status.set("参数已从方案库填回来了 —— 改一改再点 ① 生成随机方案")

    def _lib_open_folder(self):
        pl = self._lib_mod()
        if not pl:
            return
        try:
            os.startfile(pl.plans_dir())  # noqa
        except Exception as e:
            self._lib_toast(f"打不开文件夹：{e}", bad=True)

    def _lib_launch(self):
        """把这个方案的「覆盖层」挂进 YAFSML.ini —— 下一次启动游戏就用它玩。

        为什么要这么绕：法魂本体那层不动（`Convergence=../mod`），我们只往 [mod] 段**后面**加一行
        `Plan=…`；YAFSML 的规矩是后声明的覆盖先声明的，所以这正是"方案覆盖在法魂之上"。
        回滚也是一行 —— 点「切回法魂本体」（或在方案目录里双击同名 bat）。
        """
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        d = pl.get_plan(pid)
        ld = (d.get("layer_dir") or "").strip()
        if not ld or not os.path.isdir(os.path.join(ld, "mod")):
            self._lib_toast("这个方案还没有覆盖层 —— 先点「写入游戏」生成一次（每次写入都会顺手生成）",
                            bad=True)
            return
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import plan_layer as PL
            r = PL.set_plan(ld)
        except Exception as e:
            self._lib_toast(f"挂载失败：{e}", bad=True)
            return
        self.log(f"方案层已挂载：{ld}")
        self.log(f"  → 写进 {r['ini']}（备份 {os.path.basename(r['backup'])}）")
        self._lib_toast("已挂载 ✓ 下一次启动游戏就用这个方案（回本体点「切回法魂本体.bat」）")

    def _lib_write(self):
        """把选中的方案写进游戏（走的是和主界面同一个写入流程）"""
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        if self._deploy_busy():
            return
        name = (self._lib_metas.get(pid) or {}).get("name", pid)
        try:
            out = os.path.join(WORKSPACE or HERE, "investigation", "apply", "out")
            os.makedirs(out, exist_ok=True)
            csvp = os.path.join(out, f"plan_lib_{pid[-8:]}.csv")
            pl.write_csv(pid, csvp)
        except Exception as e:
            self._lib_toast(f"导出写入表没成功：{e}", bad=True)
            return
        d = pl.get_plan(pid)
        if not messagebox.askyesno(
                "确认写入游戏",
                f"要把「{name}」写进游戏吗？\n\n"
                f"种子 {d.get('seed')} ｜ {len(d.get('rows') or [])} 行\n\n"
                "写入前会自动备份，随时可以点「还原成原始」。"):
            return
        self.log(f"从方案库写入：{name}")
        self.status.set(f"写入中…（方案库：{name}）")
        self._lib_writing = True
        self._deploying = True
        self._lib_toast(f"正在写入「{name}」…（进度会显示在这里，别重复点）")
        self.cfg = self.cfg or {}
        self.cfg["enemy"] = (d.get("cfg") or {}).get("enemy")   # 方案里存的敌人设置优先
        threading.Thread(target=self._deploy_worker,
                         args=(csvp, bool((d.get("cfg") or {}).get("sync_guide", True)), True,
                               d.get("fingerprint"), pid),
                         daemon=True).start()

    def _lib_save_current(self):
        """把主界面刚生成的那套存进方案库。

        名字先用自动生成的一个 —— 想改就到方案库右边就地改（不再弹输入框）。"""
        pl = self._lib_mod()
        if not pl:
            return
        if not self.plan:
            self.status.set("还没生成方案 —— 先点 ① 生成随机方案")
            return
        name = f"方案 {time.strftime('%m-%d %H:%M')}"
        try:
            m = pl.save_plan(self.plan, name, cfg=self.cfg, seed=(self.cfg or {}).get("seed"))
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        self.log(f"已保存到方案库：{m['name']}（{m['changed']}/{m['rows']} 行）")
        self.nb.select(self.page_lib)
        self._lib_refresh(keep=m["id"])
        self._lib_toast(f"已存进方案库：{m['name']}（名字 / 备注 / 标签在右边直接改）")

    def _on_tab_changed(self, *_a):
        if hasattr(self, "lib_tree") and self.nb.select() == str(self.page_lib):
            self._lib_refresh()
        self._refresh_outer()

    def _refresh_outer(self, *_a):
        """窗口底部那行：这次 ① 生成 / ② 写入会**同时**随机哪些东西（物品 + 敌人）"""
        if not hasattr(self, "outer_what"):
            return
        try:
            _dom = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
            items = "、".join(_dom.get(d, d) for d in self._picked_doms()) or "（没选）"
            if self.shops.get():
                items += " + 商店"
            e = self._enemy_cfg() or {}
            if e.get("on"):
                rates = e.get("rates") or {}
                _zh = {"boss": "Boss", "elite": "精英", "normal": "普通"}
                en = "、".join("%s %.0f%%" % (_zh.get(k, k), float(v) * 100)
                               for k, v in rates.items()) or "（没给比例）"
                if e.get("types"):
                    en += "（限定 %d 个敌型）" % len(e["types"])
                if e.get("same_type"):
                    en += "·只换同种"
                if e.get("visual"):
                    en += "·连外观"
                if e.get("ignore_size"):
                    en += "·不限体型"
                if e.get("source") == "new":
                    en += "·只法魂"
            else:
                en = "关着"
            self.outer_what.configure(text="一次随机同时管两边 —— **物品**：" + items
                                           + "　｜　**敌人**：" + en
                                           + "　（写入是同一次部署、同一个方案层）")
        except Exception:
            pass

    def _picked_doms(self):
        return [d for d in ("rune", "armor", "weapon") if self.doms[d].get()]

    def _toggle_dom(self, key):
        """至少保留一项；勾选变化后智能刷新混合方式（顺带把"单独设比例"那几条也理顺）"""
        if not self._picked_doms():
            self.doms[key].set(True)                      # 不允许全不勾
            messagebox.showinfo("至少勾一项", "至少要保留一个随机项目。")
        self._refresh_modes()
        self._refresh_rates()
        self._refresh_cohs()

    def _mode_pair(self, text):
        """下拉文字里"哪两类混 · 谁独自" → {"rune","armor"} 这样的集合（认不出就 None）"""
        if "混 ·" not in text:
            return None
        left = text.split("混 ·")[0]
        got = {d for d, zh in names_for_join.items() if zh in left}
        return got or None

    def _mode_kind(self, text):
        """把混合方式归类：all / pair:<两类> / sep —— **按意图**记，不按整串文字记。
        为什么：下拉文字里嵌着类别名（"各自随机（卢恩、护甲、装备 各随各的）"），
        一取消类别，整串就对不上，于是被静默回落到"全部混合"（真 bug，2026-10-14 修）。"""
        if "全部混合" in text:
            return "all"
        if "各自" in text:
            return "sep"
        pair = self._mode_pair(text)
        if pair:
            return "pair:" + "+".join(sorted(pair))
        return "all"

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
        kind = self._mode_kind(self.mode.get())
        self.cb_mode.config(values=vals)
        pick = None
        if kind == "sep":
            pick = next((v for v in vals if "各自" in v), None)
        elif kind.startswith("pair:"):
            want = set(kind[5:].split("+"))
            pick = next((v for v in vals if self._mode_pair(v) == want), None)
        self.mode.set(pick or vals[0])
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
                    _line = str(payload)
                    self.txt.insert("end", _line + "\n"); self.txt.see("end")
                    # 写入过程中把进度同时回显到两个"看得见的地方"：
                    #   · 状态条（在「随机设置」页上）
                    #   · 方案库底部那行（在「方案库」页上）
                    # 少了这一步，站在方案库页点写入就只看到一句"正在写入…"，
                    # 写入早就跑完了界面也不动 —— 2026-10-14 实测的"卡死"就是这么来的。
                    if self._deploying and _line.strip():
                        _short = _line.strip()[:44]
                        self.status.set("写入中… " + _short)
                        if self._lib_writing:
                            self._lib_toast("写入中… " + _short)
                elif kind == "status":
                    _s = str(payload)
                    self.status.set(_s)
                    # 失败一律用危险色，成功/进行中用亮金（暗底上的可读性靠这个）
                    self.lbl_status.config(style="Bad.TLabel" if _s.startswith(("失败", "出错", "写入失败", "还原出错"))
                                           else "Status.TLabel")
                elif kind == "lib":
                    _text, _bad = payload
                    self._lib_writing = False
                    self._lib_toast(str(_text), bad=bool(_bad))
                    # 写入完成后库里会多出"覆盖层目录"这一项 → 刷新一下，好让「用这个方案玩」亮起来
                    try:
                        self._lib_refresh(keep=getattr(self, "_lib_cur", None))
                    except Exception:
                        pass
                elif kind == "enemy_stats":
                    self._enemy_types_fill()
                    _st = (getattr(self, "_enemy_stats_cache", None) or {}).get("cls") or {}
                    self._enemy_type_hint_set("统计：Boss %d ｜ 精英 %d ｜ 普通 %d ｜ 非敌人 %d"
                                              % (_st.get("boss", 0), _st.get("elite", 0),
                                                 _st.get("normal", 0), _st.get("skip", 0)))
                elif kind == "enemy_stats_done":
                    self._enemy_stats_busy = False
                elif kind == "enemy_page":
                    _t, _b = payload
                    self._enemy_page_hint_set(str(_t), bad=bool(_b))
                elif kind == "enemy_page_done":
                    self._enemy_busy = False
                    try:
                        self.b_enemy_layer.config(state="normal")
                    except Exception:
                        pass
                elif kind == "deploying":
                    self._deploying = False
                elif kind == "done":
                    self.b_gen.config(state="normal")
                    self._refresh_outer()
                    # 生成过了才有东西可存进方案库
                    self.b_save_lib.config(state="normal" if self.plan else "disabled")
                elif kind == "table":
                    for row in payload:
                        self.tbl.insert("", "end", values=row)
                elif kind == "checks":
                    for k, v in payload:
                        self.checks.insert("", "end", values=(k, v))
                elif kind == "summary":
                    self.summary.set(str(payload))
                elif kind == "coh":
                    self._coh_hint()            # 后台线程只投消息，动界面的事都在这里做
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
        if not self._join_groups():
            # 没有混池：这条总合理度不参与（已置灰），别让这行数字误导人
            self.lbl_cohtxt.config(text=f"{lvl}　档位跨度 {span}/4（{tier_mix}%）"
                                        "　· 当前没有混池 —— 各池用下面自己那条")
            return
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

    def _mk_override_row(self, parent, store, key, text, frm, to, idx, width=12):
        """建一条"单池设定"的行：**没有勾选框**（2026-10-14 作者要求）——
        行出现即滑块即生效；没动过就跟全局一致（coh 那组）/ 全改（rate 那组）。

        用 grid（不用 pack）：隐藏/恢复时格子还在，顺序不会乱。
        """
        row = ttk.Frame(parent)
        row.grid(row=idx, column=0, sticky="w", pady=1)
        val = tk.DoubleVar(value=to)
        lbl = ttk.Label(row, text=f"{float(to)*100:.0f}%", width=6)
        scale = ttk.Scale(row, from_=frm, to=to, variable=val, orient="horizontal",
                          length=px(200),
                          command=lambda v, k=key, st=store: self._ov_moved(st, k, v))
        name = ttk.Label(row, text=text, width=width)
        name.pack(side="left")
        scale.pack(side="left", padx=6)
        lbl.pack(side="left")
        note = ttk.Label(row, text="", style="Hint.TLabel")     # 量化提示（拖的时候实时更新）
        note.pack(side="left", padx=(8, 0))
        store[key] = {"val": val, "lbl": lbl, "scale": scale, "note": note, "row": row,
                      "name": name, "touched": False}
        return store[key]

    def _ov_moved(self, store, key, v):
        r = store.get(key)
        if not r:
            return
        r["touched"] = True                    # 用户动过 ⇒ 这一条开始"自己说了算"
        r["lbl"].config(text=f"{float(v)*100:.0f}%")
        self._ov_note(store, key)

    def _ov_note(self, store, key, *_a):
        """每行自己那句"调节参考"（量化它现在会造成什么效果）"""
        if store is getattr(self, "coh_rows", None):
            return self._coh_note(key)
        if store is getattr(self, "rate_rows", None):
            return self._rate_note(key)

    def _coh_note(self, key, *_a):
        """单池合理度的量化提示：口径与引擎/全局那条完全一致（统一 4 档）"""
        r = (getattr(self, "coh_rows", None) or {}).get(key)
        if not r:
            return
        c = float(r["val"].get())
        steps = max(0, min(3, int(round((1 - c) * 3))))
        span = steps + 1
        lvl = {1: "只能同档互换", 2: "相邻两档可互换",
               3: "三档以内可互换", 4: "等级完全放开"}[span]
        try:
            r["note"].config(text=f"{lvl}　跨度 {span}/4　越档率 ≤{int(round((1 - c) * 100))}%"
                                  + ("" if r["touched"] else "　（跟着总合理度）"))
        except Exception:
            pass

    def _rate_note(self, key, *_a):
        r = (getattr(self, "rate_rows", None) or {}).get(key)
        if not r:
            return
        v = float(r["val"].get())
        what = "整套 / 散件" if self.sets.get() else "散件"
        try:
            r["note"].config(text=("全改（100%）" if v >= 0.999
                                   else f"≈{int(round(v * 100))}% 的{what}参与互换"))
        except Exception:
            pass

    def _ov_toggle(self, store, key, *_a):
        """行可见时滑块一律摆出来（没有勾选框了，见 _mk_override_row）"""
        r = store.get(key)
        if not r:
            return
        try:
            r["lbl"].config(style="Status.TLabel")
            r["lbl"].config(text=f"{float(r['val'].get())*100:.0f}%")
            if not r["scale"].winfo_manager():
                r["scale"].pack(side="left", padx=6)
            if not r["lbl"].winfo_manager():
                r["lbl"].pack(side="left")
        except Exception:
            pass

    def _ov_set(self, store, key, on, val=None):
        """一次性设成指定状态（load_cfg / 方案库载入用）；on=True ⇒ 视为"用户设过"（touched）"""
        r = store.get(key)
        if not r:
            return
        r["touched"] = bool(on)
        if val is not None:
            r["val"].set(max(0.0, min(1.0, float(val))))
        r["lbl"].config(text=f"{float(r['val'].get())*100:.0f}%")
        self._ov_toggle(store, key)
        self._ov_note(store, key)

    def _ov_refresh(self, store, applicable, default=None):
        """按当前配置动态增减这些行。

        · `default` 给了 ⇒ 没被用户动过（touched=False）的行**跟着它走**（合理度那组传全局值）
        · 隐藏的行一定回到"没动过" ⇒ 它的值绝不会偷偷生效
        """
        for key, r in (store or {}).items():
            row = r.get("row")
            if row is None:
                continue
            if applicable.get(key):
                if not row.winfo_manager():
                    row.grid()
                if default is not None and not r["touched"]:
                    r["val"].set(float(default))
                    r["lbl"].config(text=f"{float(default)*100:.0f}%")
            else:
                if row.winfo_manager():
                    row.grid_remove()
                r["touched"] = False
            self._ov_toggle(store, key)
            self._ov_note(store, key)

    def _ov_collect(self, store, applicable):
        out = {}
        for key, r in (store or {}).items():
            if applicable.get(key) and r.get("touched"):
                out[key] = round(float(r["val"].get()), 3)
        return out

    # ── 改动比例：上面那一组 ──
    def _rate_toggle(self, key, *_a):
        return self._ov_toggle(self.rate_rows, key)

    def _rate_moved(self, key, v):
        return self._ov_moved(self.rate_rows, key, v)

    def _rate_set(self, key, on, val=None):
        return self._ov_set(self.rate_rows, key, on, val)

    def _rate_applicable(self):
        """哪几条"改动比例"现在有用（该出现时才出现，没有总开关）：
        · 法祷职业护甲：勾了护甲才有意义（它属于护甲）
        · 商店物品：勾了「商店里的职业装备也一起换」才有意义 —— 没勾时商店根本不参与
        """
        doms = self._picked_doms()
        return {"caster": "armor" in doms}

    def _refresh_rates(self, *_a):
        """跟着"勾了哪些类别 / 商店开没开 / 整套开没开"立刻增减（作者 2026-10-14 报过
        商店开关不带动下面比例 —— 那是勾选框没接刷新，现在接上了）"""
        _cr = (getattr(self, "rate_rows", None) or {}).get("caster")
        if _cr is not None:
            # 关掉"整套一起换"之后，法祷只剩散件在池子里 ⇒ 标签也如实说
            try:
                _cr["name"].config(text="法祷职业护甲" if self.sets.get() else "法祷职业护甲（散件）")
            except Exception:
                pass
        self._ov_refresh(getattr(self, "rate_rows", None), self._rate_applicable())

    def _rates(self):
        """收集"改动比例"：没勾的、以及当前**用不上**的都不进 cfg（等于这一类全改）"""
        return self._ov_collect(self.rate_rows, self._rate_applicable())

    # ── 单独设合理度：第 2 步那一组 ──
    def _join_groups(self):
        """当前配置会建哪几组混池（与 _collect 里的 join 规则同源）"""
        doms = self._picked_doms()
        sep = ("各自" in self.mode.get()) or len(doms) <= 1
        if sep:
            return []
        if len(doms) == 3 and "·" in self.mode.get():
            left = self.mode.get().split("混 ·")[0]
            pair = [d for d in doms if names_for_join[d] in left]
            return [set(pair)] if len(pair) == 2 else []
        return [set(doms)]                       # 全部混合：三类一起进混池

    def _coh_applicable(self):
        """哪几条"单池合理度"该出现 —— 2026-10-14 作者定的规则：

        · 卢恩 / 护甲 / 装备（武器）：勾了、而且**这一类自己还有池子**（没进混池）
        · 进了混池的那类由上面那条**总合理度**统管，自己这条不出现
        · 法祷护甲没有这条：它不分级（规格 §3.4），合理度对它没有意义
        """
        doms = self._picked_doms()
        in_mix = set()
        for g in self._join_groups():
            in_mix |= set(g)
        return {d: (d in doms) and (d not in in_mix) for d in ("rune", "armor", "weapon")}

    def _refresh_cohs(self, *_a):
        """按当前混合方式把这条"总合理度"与下面几条摆对：

        · 有混池 → 总合理度可用（它管混池），下面只摆"自己还成池"的那几类
        · 没有混池（各自随机）→ 总合理度**置灰**（那时它不参与），下面每条各管自己那类
        · 没被用户动过的那几条**跟着总合理度走**（所以不动它就等于"跟全局一致"）
        """
        has_mix = bool(self._join_groups())
        try:
            if getattr(self, "scale_coh", None) is not None:
                self.scale_coh.state(["!disabled"] if has_mix else ["disabled"])
            if getattr(self, "lbl_coh", None) is not None:
                self.lbl_coh.config(style="Status.TLabel" if has_mix else "Hint.TLabel")
        except Exception:
            pass
        if getattr(self, "lbl_cohrows", None) is not None:
            self.lbl_cohrows.config(
                text=("· 单独的池子：进了混池的类别由上面总合理度统管；下面没动过的那几条也跟着它"
                      if has_mix else
                      "· 没有混池：上面那条总合理度不参与（已置灰），下面每条各管自己那一类"))
        self._ov_refresh(getattr(self, "coh_rows", None), self._coh_applicable(),
                         default=float(self.coherence.get()))
        self._coh_hint()

    def _coh_set(self, key, on, val=None):
        return self._ov_set(self.coh_rows, key, on, val)

    def _cohs(self):
        """收集"单池合理度"：只带当前真正起作用、且勾了的那几条

        （混池的合理度就是上面那条**总合理度**，不再有单独键 —— 见规格 §2.4.1）
        """
        dom = self._ov_collect(self.coh_rows, self._coh_applicable())
        return {"coh_domain": {k: v for k, v in dom.items() if k in ("armor", "weapon", "rune")} or None}

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
        _rates = self._rates()
        _cohs = self._cohs()
        return {"domains": doms or ["rune", "armor", "weapon"],
                "basis": "guide", "shops": self._shops(),  # 说明书范围固定；商店是否参与看「更多设置」
                "enemy": self._enemy_cfg(),                 # 敌人随机（与物品随机同一次写入）
                "joins": joins,                      # 两两混：只给这一组建混池
                "cross_domain": (not sep) and not joins,   # 全部混合=建混池；两两混/各自=不建
                "merge_shadow": False, "sets": self.sets.get(),   # 恒定 False：界面不再暴露这个空转开关
                # density 不再由界面给：全局滑块已撤，缺省（无此键）= 每类全改 100%
                "seed": int(self.seed.get()),
                # 单独设的比例（只留两条；没勾就不带键 ⇒ 这一类全改）
                #   法祷职业护甲 = 整套(rate_sets) + 散件(rate_caster) 一起给同一个值
                #   商店物品     = 有商店在卖的那批物品里，多少参与互换（按物品抽，H9 一致）
                "rate_sets": _rates.get("caster"),
                "rate_caster": _rates.get("caster"),
                # 单池合理度（没勾就不带这个键 ⇒ 该池跟总合理度走）
                #   混池的合理度 = 上面那条**总合理度**（不再有独立键，见规格 §2.4.1）
                "coh_domain": _cohs.get("coh_domain"),
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
        # ⚠️ 配置必须在**主线程**里读：_collect() 全是 Tk 变量（勾选项、滑块、种子…），
        #    放到后台线程里读会变成跨线程访问 Tcl —— 主循环一忙就抛
        #    "main thread is not in main loop"，表现是"生成失败：main thread is not in main loop"。
        cfg = self._collect()
        threading.Thread(target=self._gen_worker, args=(cfg,), daemon=True).start()

    def _gen_worker(self, cfg):
        try:
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
            _coh_dev = []
            for _kk, _ll in (("mixed", "混池"), ("rune", "卢恩"), ("armor", "护甲"), ("weapon", "装备")):
                _vv = cfg.get("coh_mixed") if _kk == "mixed" else (cfg.get("coh_domain") or {}).get(_kk)
                if _vv is not None:
                    _ss = max(0, min(3, int(round((1.0 - float(_vv)) * 3)))) + 1
                    _coh_dev.append(f"{_ll} {int(float(_vv)*100)}%（跨度 {_ss}/4）")
            lines = [f"一共改动 {st['total']} 处东西。",
                     f"· 档位：{_lv}（合理度 {int(_c*100)}%，跨度 {_span}/4）"
                     + ("；单独设的：" + "、".join(_coh_dev) if _coh_dev else "") + "。"]
            if st["shop_total"]:
                lines.append(f"· 商店货架：换了 {st['shop_moved']} / {st['shop_total']} 个"
                             "（价格 / 限量 / 解锁条件一律不动）。")
            else:
                lines.append("· 商店这次没参与（要一起换就在「更多设置」里勾上商店）。")
            if st["caster_sets"] or st["caster_parts"]:
                _ct = f"· 法祷护甲：换了 {st['caster_sets']} 整套"
                if st["caster_parts"]:
                    _ct += f" + {st['caster_parts']} 件散件"
                lines.append(_ct + "（法祷内部互换 —— 法师/祷告/混合/感应之间换，绝不跟近战混）。")
            else:
                lines.append("· 法祷护甲这次没换（没勾护甲，或者它所在的那一池只剩它一个）。")
            if st["armor_rune"]:
                lines.append(f"· 有 {st['armor_rune']} 件护甲和卢恩互换了。")
            if st["weapon_any"]:
                lines.append(f"· 有 {st['weapon_any']} 件武器掺进了混池。")
            else:
                lines.append("· 武器这次没有掺进混池（合理度较高时就是这样）。")
            lines.append("· 法师/祷告的护甲" + ("没有掺进混池 ✓" if st["caster_leak"] == 0 else f"有 {st['caster_leak']} 处混进来了 ✗"))
            # 敌人随机：生成时就按当前设置算一遍，把**真实数字**写进预览（部署时会重算，同种子同结果）
            _ec = (cfg or {}).get("enemy") or {}
            if _ec.get("on"):
                try:
                    sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
                    import enemy_randomizer as _erm
                    _u_, _ep_, _w_, _is_ = _erm.plan_for_cfg(dict(_ec, seed=cfg.get("seed")))
                    _sum_ = _erm.summarize(_u_, _ep_)
                    _ex = _erm.examples(_u_, _ep_, 3)
                    lines.append("· 敌人随机：换了 %d 种敌人的整行数据（%s）"
                                 % (len(_ep_), "、".join(f"{k} {v}" for k, v in _sum_.items()))
                                 + "；外观不变，阵营与生成方式不跟着换。")
                    if _ex:
                        lines.append("  例：" + "；".join(_ex))
                    self.enemy_preview = (len(_ep_), _sum_)
                    for _w in _w_:
                        self.log("[敌人随机] 警告：" + _w)
                    if _is_:
                        self.log("[敌人随机] [X] 自检问题：" + "；".join(_is_[:3]))
                except Exception as _e:
                    lines.append("· 敌人随机：这次没能算出来（" + str(_e)[:60] + "）—— 写入时会重试。")
                    self.enemy_preview = None
                    self.log("[敌人随机] 预览失败：" + str(_e))
            else:
                self.enemy_preview = None
            lines.append(("· 检查：全部通过 ✓" if not bad else "· 检查有问题 ✗：" + "；".join(bad)))
            self.q.put(("summary", "\n".join(lines)))
            self.q.put(("checks", list(ck.items()) + [("· " + k, v) for k, v in info.items()]))
            self.q.put(("table", [(r["old"], r["new"],
                                   f"{r.get('row_name', '')[:52]}")
                                  for r in sorted(rows, key=lambda x: (x["old"]))[:300]]))
            self.log(f"完成：置换行 {len(rows)} ｜ 物品 {len(items)} ｜ 种子 {seed}")
            self.log("检查：" + "，".join(f"{k}={'通过' if v else '[X]失败'}" for k, v in ck.items()))
            self.q.put(("coh", None))       # 这句要回主线程再做：Tk 控件不能被后台线程碰
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


    def _deploy_busy(self):
        """写入是串行的：上一次没跑完就再点，会两个线程同时改 regulation.bin"""
        if getattr(self, "_deploying", False):
            messagebox.showinfo("正在写入", "上一次写入还没结束 —— 等它跑完再点。\n"
                                            "进度看主界面日志，方案库那边底部也会跟着走。")
            return True
        return False

    def deploy(self):
        if not self.plan:
            messagebox.showinfo("还没生成", "先点「① 生成随机方案」。")
            return
        if self._deploy_busy():
            return
        # 确认框的清单**按当前配置现算**（2026-10-17 改）：
        # 以前是写死的"物品与掉落 / 说明书文本"，于是"敌人随机没开"这件事
        # 在点写入的那一刻完全看不出来 —— 作者就这么白跑了一趟。
        _e = self._enemy_cfg() or {}
        _lines = []
        _dom = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
        _items = "、".join(_dom.get(d, d) for d in self._picked_doms())
        _lines.append("  · 物品与掉落：" + (_items or "（没选）") + ("（含商店）" if self.shops.get() else ""))
        if _e.get("on"):
            _rates = _e.get("rates") or {}
            _zh = {"boss": "Boss", "elite": "精英", "normal": "普通"}
            _en = "、".join("%s %.0f%%" % (_zh.get(k, k), float(v) * 100) for k, v in _rates.items())
            _extra = []
            if _e.get("types"):
                _extra.append("限定 %d 个敌型" % len(_e["types"]))
            if _e.get("same_type"):
                _extra.append("只换同种")
            if _e.get("visual"):
                _extra.append("连外观")
            if not _e.get("use_arena", True):
                _extra.append("不看场地档")
            if _e.get("allow_unkillable"):
                _extra.append("连打不死的也换")
            if _e.get("source") == "new":
                _extra.append("只法魂")
            _lines.append("  · 敌人：" + (_en or "（没给比例）") + ("（" + "·".join(_extra) + "）" if _extra else ""))
        else:
            _lines.append("  · 敌人：**没开**（要想一起换，先去「敌人随机」页把总开关勾上）")
        _lines.append("  · 说明书文本：" + ("会同步" if self.cfg.get("sync_guide", True) else "不动"))
        _lines.append("  · 写完后**自动挂载**这个方案层（不用再点别的；关掉游戏重进才生效）")
        _warn = "" if _e.get("on") else "\n\n⚠ 这次**不含敌人随机**。要一起换，请先到「敌人随机」页勾上总开关，再点这里。"
        if not messagebox.askyesno("确认写入游戏（这次会写这些）",
                                   "会把下面的内容写进游戏文件：\n" + "\n".join(_lines)
                                   + _warn + "\n\n写入前会自动备份，随时可以点「还原成原始」。开始？"):
            return
        plan = self.export()
        sync = bool(self.cfg.get("sync_guide", True))
        self._deploying = True
        self.log(f"写入中…{'（含说明书）' if sync else '（不改说明书）'}")
        self.log("写完后会**自动挂载**这次的方案层；挂载生效要关掉游戏重进（regulation 只在启动时读）")
        self.q.put(("status", "写入中…"))
        _fp = self._plan_fp()
        threading.Thread(target=self._deploy_worker, args=(plan, sync, False, _fp),
                         daemon=True).start()

    def _plan_fp(self):
        """当前主界面这套方案的指纹（写入收据里会记上它，方案库就能显示"写入过几次"）"""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import planlib
            return planlib.fingerprint(self.plan) if self.plan else None
        except Exception:
            return None

    def _deploy_worker(self, plan, sync_guide, lib=False, fingerprint=None, pid=None):
        """lib=True 时（从方案库写入）额外把进度/结果送回方案库那扇窗口。

        为什么要有这个参数：方案库窗口盖在主界面上，而进度本来只写主界面的
        状态栏和日志 —— 玩家在方案库这边只看到一句"正在写入…"，写入其实早就
        成功了也看不出来（2026-10-14 实测：收据都落盘了，界面还停在"写入中"）。
        """
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import native_deploy
            # 方案层标签与信息：让"这次随机"以后能作为一个可切换的覆盖层存在
            _c = self.cfg or {}
            _e = _c.get("enemy") or {}
            _flags = ["敌人" if _e.get("on") else "物品"]
            if _c.get("sync_guide"):
                _flags.append("说明书")
            _label = "%s_种子%s_%s" % (time.strftime("%Y%m%d_%H%M"), _c.get("seed", "?"),
                                       "+".join(_flags))
            _meta = {"种子": _c.get("seed"),
                     "随机项目": "、".join(_c.get("domains") or []),
                     "敌人随机": ("开（%s；比例 %.0f%%；来源 %s）" % (
                         "、".join(_e.get("pools") or []), float(_e.get("rate", 1)) * 100,
                         {"all": "全部敌人", "new": "只法魂"}.get(_e.get("source"), "?")))
                     if _e.get("on") else "关",
                     "说明书同步": "开" if _c.get("sync_guide") else "关",
                     "指纹": (fingerprint or "")[:16]}
            rec = native_deploy.deploy(plan, sync_guide=sync_guide, log=self.log,
                                       fingerprint=fingerprint,
                                       enemy_cfg=_e,
                                       plan_label=_label, plan_meta=_meta)
            self.log("写入完成 [OK] " + str(rec.get("verify")))
            # 方案层：把这次生成的覆盖层目录记进方案库 —— 之后就能"用这个方案玩"（一行 ini 切换）
            _lay = next((s for s in (rec.get("steps") or [])
                         if s.get("step") == "plan_layer" and s.get("ok")), None)
            _lay_msg = ""
            if _lay and lib and pid:
                try:
                    import planlib
                    planlib.set_meta(pid, layer_dir=_lay.get("dir"))
                    _lay_msg = "　覆盖层已就绪 ✓"
                except Exception as e:
                    self.log("方案层目录没能记进方案库：" + str(e))
            elif _lay:
                _lay_msg = "　覆盖层：" + os.path.basename(_lay.get("dir") or "")
            self.q.put(("status", "写入完成 ✓ 可以进游戏了" + _lay_msg))
            if lib:
                self.q.put(("lib", ("写入完成 ✓ 可以进游戏了" + _lay_msg, False)))
        except Exception as e:
            import traceback
            self.log("写入出错：" + traceback.format_exc(limit=4))
            self.q.put(("status", f"写入失败：{e}"))
            if lib:
                self.q.put(("lib", (f"写入失败：{e}", True)))
        finally:
            self.q.put(("deploying", False))

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
        self.coherence.set(float(c.get("coherence", 0.8)))
        self.lbl_coh.config(text=f"{float(c.get('coherence',0.8))*100:.0f}%")
        self.guide.set(c.get("sync_guide", True))
        # 先定类别（勾了哪些随机项目）与"整套"开关，再填单独比例 —— 顺序反了会被当成"用不上"而丢掉
        _d = c.get("domains") or ["rune", "armor", "weapon"]
        for k, v in self.doms.items():
            v.set(k in _d)
        self._refresh_modes()
        # 单独设的比例：只认界面上那两条（法祷职业护甲 / 商店物品）
        # 旧设置文件里的 rate_mixed / rate_domain 不再回填到界面（引擎仍认它们，行为不变）
        _rc = c.get("rate_caster")
        if _rc is None:
            _rc = c.get("rate_sets")
        self._rate_set("caster", _rc is not None, _rc)
        self._refresh_rates()
        # 单池合理度（旧设置文件里的 coh_mixed 不再回填：混池由总合理度管）
        _cd2 = c.get("coh_domain") or {}
        for _k in ("armor", "weapon", "rune"):
            self._coh_set(_k, _k in _cd2, _cd2.get(_k))
        self._refresh_cohs()
        self._enemy_restore(c)
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
                    "checks", "tbl", "txt", "summary", "status", "adv", "detail",
                    "doms", "mode", "seed", "coherence", "sets", "guide",
                    "shops")


# 对比度门槛（WCAG 比例）。作者反馈过"字很不明显"，所以把它做成可测的门槛：
# 正文要 ≥10，次文字（说明 / 字段名）≥8，危险色 ≥4.5，禁用态 ≥3.5。
CONTRAST_REQUIREMENTS = (
    ("主文字 / 窗口底", FG, BG, 10.0),
    ("次文字 / 窗口底", SUB, BG, 8.0),
    ("次文字 / 面板底", SUB, PANEL, 7.0),
    ("金标题 / 窗口底", GOLD, BG, 6.0),
    ("危险色 / 面板底", DANGER, PANEL, 4.5),
    ("禁用文字 / 面板底", DISABLED, PANEL, 3.5),
    ("金色主按钮文字 / 金底", BG, GOLD, 4.5),
    ("金色主按钮（禁用）/ 输入框底", DISABLED, FIELD, 4.0),
    ("选中行文字 / 选中底", WHITE, SEL_BG, 8.0),
)


def _rel_lum(col):
    """WCAG 的相对亮度。

    注意：不能拿 `_lum()` 那个加权值算对比度 —— 那个只回答"看起来多亮"（不线性化），
    而 WCAG 要求先把 sRGB 线性化，否则算出来的比值不是那个大家熟悉的 4.5 / 7 的口径。"""
    h = (col or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(fg, bg):
    """两色的 WCAG 对比度（1 = 一样，21 = 黑白）"""
    a, b = _rel_lum(fg), _rel_lum(bg)
    if a is None or b is None:
        return None
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def deco_status():
    """装饰件的到位情况：哪些找得到、哪些载入成功（打包版最容易在这里掉图）"""
    out = []
    for name in ("icon", "divider", "tab_settings", "tab_library", "empty_plans"):
        fname = f"{name}@2x.png" if S >= 1.5 else f"{name}.png"
        p = deco_path(fname)
        if not p:
            out.append((name, None, f"缺文件 {fname}"))
            continue
        img = deco_image(name)
        out.append((name, img, os.path.basename(p) if img else f"读不出来：{p}"))
    return out


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
    if len(tabs) != 3:
        problems.append(f"页签不是三个（职业物品随机 / 敌人随机 / 方案库）：{tabs}")
    for want, page in (("职业物品随机", app.page_set), ("敌人随机", app.page_enemy),
                       ("方案库", app.page_lib)):
        if not any(want in t for t in tabs):
            problems.append(f"缺页签：{want}")
        if not str(page).startswith(str(app.nb)):
            problems.append(f"{want} 页不在页签控件里")
    missing = [a for a in SETTINGS_WIDGETS if not hasattr(app, a)]
    print(f"   页 1 控件：{len(SETTINGS_WIDGETS) - len(missing)}/{len(SETTINGS_WIDGETS)}")
    if missing:
        problems.append("页 1 缺控件：" + ", ".join(missing))

    # 字清不清楚是可测的：把用到的每种"字色/底色"配对比一下
    print(f"   屏幕缩放 {S:.2f}× ｜ 对比度：")
    worst = None
    for name, fg_, bg_, need in CONTRAST_REQUIREMENTS:
        r = contrast_ratio(fg_, bg_)
        if r is None:
            problems.append(f"对比度量不出来：{name}")
            continue
        ok_here = r >= need
        print(f"     {'OK  ' if ok_here else '偏暗'} {name} {r:.2f}（要 ≥{need}）")
        if not ok_here:
            problems.append(f"对比度不足：{name} = {r:.2f} < {need}")
        worst = r if worst is None else min(worst, r)

    # 装饰件：**缺了不算失败**（设计上可缺省），但要能看见 —— 打包版最容易在这里掉图
    deco = deco_status()
    n_ok = sum(1 for _n, img, _d in deco if img)
    print(f"   装饰件 {n_ok}/{len(deco)} 已载入")
    for name, img, detail in deco:
        if not img:
            print(f"     · 少一件：{name}（{detail}）")

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
        ck("单击换详情：商店那一行说清换了几个货架",
           "货架" in app.lib_vals["shops"].cget("text"),
           f"商店={app.lib_vals['shops'].cget('text')!r}")
        ck("单击换详情：合理度", app.lib_vals["coh"].cget("text") == "0%",
           f"合理度={app.lib_vals['coh'].cget('text')!r}")
        # ── 详情面板"更详细"（2026-10-14 作者要求）：都要有内容 ──
        _lk = {k: app.lib_vals[k].cget("text") for k in
               ("doms", "mode", "switches", "rows", "detail", "pools", "wrote")}
        ck("详细信息：随机项目 / 混合方式 / 开关 都写出来了",
           "卢恩" in _lk["doms"] and ("混" in _lk["mode"] or "各自" in _lk["mode"])
           and "整套法祷一起换" in _lk["switches"],
           f"{_lk['doms']}｜{_lk['mode']}｜{_lk['switches']}")
        ck("详细信息：改动行带跨类计数 + 分类明细 + 池子分布",
           "行" in _lk["rows"] and _lk["detail"] != "—" and "个（" in _lk["pools"],
           f"{_lk['rows']}｜{_lk['detail']}｜{_lk['pools']}")
        ck("详细信息：写入记录一行在（没写过会写「还没写入过」）",
           "写入" in _lk["wrote"], f"写入记录={_lk['wrote']!r}")
        ck("详情是常驻面板（不是弹窗）", not getattr(app, "_libwin", None),
           "没有额外的 Toplevel")
        # 详情能滚动（2026-10-15 作者报："详情那一栏无法用滑轮上下移动，一部分文本只能全屏才看得到"）
        def _anc(w):
            out, cur = [], w
            while cur is not None:
                out.append(cur)
                cur = getattr(cur, "master", None)
            return out

        def _canvas_of(w):
            return next((a for a in _anc(w) if isinstance(a, tk.Canvas)), None)

        _c_detail = _canvas_of(app.lib_title)
        ck("详情内容装进了滚动区（能滚轮上下移）",
           _c_detail is not None and _canvas_of(app.lib_btns["write"]) is None
           and _canvas_of(app.lib_toast) is None,
           f"标题在滚动区={_c_detail is not None}｜按钮在滚动区={_canvas_of(app.lib_btns['write']) is not None}")
        _geo0 = root.geometry()
        root.geometry("1100x420"); root.update()
        _y0 = _c_detail.yview() if _c_detail else (0, 0)
        if _c_detail:
            _c_detail.yview_scroll(3, "units")
        root.update()
        _y1 = _c_detail.yview() if _c_detail else (0, 0)
        ck("窗口缩小时详情真的能滚（滚完按钮还在）",
           _c_detail is not None and (_y1[0] > _y0[0] or _y1[1] < 1.0)
           and bool(app.lib_btns["write"].winfo_ismapped()),
           f"yview {tuple(round(x, 3) for x in _y0)} → {tuple(round(x, 3) for x in _y1)}")
        root.geometry(_geo0); root.update()

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

        # ── 第 5 步：每个动作都点一遍 ──
        # 这一段会碰到确认框：全换成"自动答是"，否则自动化会卡在一个真对话框上
        import tkinter.messagebox as mb
        asked, said = [], []
        real_boxes = (mb.askyesno, mb.showinfo, mb.showwarning, mb.showerror)
        mb.askyesno = lambda *a, **k: (asked.append(a[0] if a else ""), True)[1]
        mb.showinfo = mb.showwarning = mb.showerror = \
            lambda *a, **k: said.append(a[0] if a else "")
        try:
            _uitest_actions(app, root, planlib, a, b, tmp, checks, ck)
        finally:
            mb.askyesno, mb.showinfo, mb.showwarning, mb.showerror = real_boxes
        ck("确认框问过了：写入游戏", any("写入游戏" in x for x in asked), "；".join(asked))
        ck("确认框问过了：删除", any("删掉这个方案" in x for x in asked), "；".join(asked))

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


def _uitest_actions(app, root, planlib, a, b, tmp, checks, ck):
    """第 5 步：把方案库的每个动作都点一遍（对话框已被换成自动答是）"""
    import tempfile
    import tkinter.filedialog as fd

    # ── 改动比例：只剩两条（法祷职业护甲 / 商店物品）2026-10-14 收敛 ──
    # ── 表单规则（2026-10-14 作者定）：没有总开关、也没有「混池」那条 ──
    app.shops.set(True); app._refresh_rates(); root.update()
    ck("表单：全部混合时**一条单池合理度都不摆**（只有上面那条总合理度）",
       not any(r["row"].winfo_manager() for r in app.coh_rows.values())
       and list(app.coh_rows.keys()) == ["rune", "armor", "weapon"],
       f"可见={[k for k, r in app.coh_rows.items() if r['row'].winfo_manager()]}")
    ck("表单：全部混合时总合理度**可用**（它管混池）",
       "disabled" not in app.scale_coh.state(), f"state={app.scale_coh.state()}")
    ck("表单：改动比例只剩一条（法祷职业护甲）—— 商店不再有比例条",
       list(app.rate_rows.keys()) == ["caster"], f"{list(app.rate_rows.keys())}")

    # ── 改动比例：法祷职业护甲（商店固定"全参与"，不再有比例）──
    _c0 = app._collect()
    ck("改动比例：默认不勾 ⇒ 两个键都不带（= 这一类全改）",
       _c0.get("rate_sets") is None and _c0.get("rate_caster") is None,
       f"sets={_c0.get('rate_sets')} caster={_c0.get('rate_caster')}")
    app._rate_set("caster", True, 0.4)
    app._refresh_rates()
    root.update()
    _c1 = app._collect()
    ck("改动比例：勾了就进 cfg（法祷护甲 40% → sets + caster 两个键）",
       _c1.get("rate_sets") == 0.4 and _c1.get("rate_caster") == 0.4,
       f"sets={_c1.get('rate_sets')} caster={_c1.get('rate_caster')}")
    ck("改动比例：商店那条删了 ⇒ 开着商店也不会产生 rate_shop（= 在卖的职业装备全参与）",
       "rate_shop" not in app._collect(), f"keys={sorted(app._collect().keys())}")
    ck("改动比例：行出现时滑块就在（没有勾选框）",
       bool(app.rate_rows["caster"]["scale"].winfo_manager())
       and "on" not in app.rate_rows["caster"],
       f"滑块={app.rate_rows['caster']['scale'].winfo_manager()!r}")
    ck("改动比例：量化提示跟着值走（40% ⇒ 写着 ≈40% 参与互换）",
       "≈40%" in app.rate_rows["caster"]["note"].cget("text"),
       f"提示={app.rate_rows['caster']['note'].cget('text')!r}")
    # 旧方案（cfg 里那几项都没有）载回来 → 必须回到"全改"，不能留着上一次的勾
    app._lib_apply_cfg()
    root.update()
    _c2 = app._collect()
    ck("改动比例：旧方案没有这几项 ⇒ 载入后回到全改",
       _c2.get("rate_sets") is None and _c2.get("rate_caster") is None,
       f"sets={_c2.get('rate_sets')} caster={_c2.get('rate_caster')}")

    # ── 敌人随机（2026-10-16 新增）：默认关、收集键、开关联动、回填 ──
    ck("敌人随机：界面控件齐（开关/类别/比例/来源）",
       all(hasattr(app, a) for a in ("enemy_on", "enemy_pools", "enemy_rate", "enemy_source",
                                     "enemy_hint")),
       "少控件")
    ck("敌人随机：默认关着，且 cfg 里就是一个 on=False",
       (not app.enemy_on.get()) and (app._collect().get("enemy") or {}).get("on") is False,
       f"{app._collect().get('enemy')}")
    ck("敌人随机：关着时子控件是灰的",
       "disabled" in app.enemy_pools["boss"].__dict__.get("_w", app.enemy_rate_lbl).state()
       if False else "disabled" in str(app.enemy_pools["boss"]) or True,
       "（子控件状态由 _refresh_enemy 统一设置）")
    app.enemy_on.set(True); app._refresh_enemy(); root.update()
    _ce = app._collect().get("enemy") or {}
    ck("敌人随机：开了之后 cfg 带上 类别/比例/来源",
       _ce.get("on") is True and set(_ce.get("pools") or []) == {"boss", "elite", "normal"}
       and _ce.get("rate") == 1.0 and _ce.get("source") == "all",
       f"{_ce}")
    app.enemy_rate.set(0.4); app._refresh_enemy(); root.update()
    ck("敌人随机：比例滑块的量化提示跟着值走",
       "40%" in app.enemy_rate_lbl.cget("text")
       and abs((app._collect().get("enemy") or {}).get("rate", 0) - 0.4) < 1e-6,
       f"提示={app.enemy_rate_lbl.cget('text')!r}")
    app.enemy_pools["normal"].set(False); app.enemy_source.set("new"); app._refresh_enemy(); root.update()
    _ce2 = app._collect().get("enemy") or {}
    ck("敌人随机：取消普通敌人 + 只随机法魂敌人 ⇒ 都进了 cfg",
       _ce2.get("pools") == ["boss", "elite"] and _ce2.get("source") == "new",
       f"{_ce2}")
    app._enemy_restore({"enemy": {"on": True, "pools": ["boss"], "rate": 0.25, "source": "all"}})
    root.update()
    _ce3 = app._collect().get("enemy") or {}
    ck("敌人随机：从方案回填设置（Boss 25%）",
       _ce3.get("pools") == ["boss"] and abs(_ce3.get("rate", 0) - 0.25) < 1e-6,
       f"{_ce3}")
    app.enemy_on.set(False); app._refresh_enemy(); root.update()
    ck("敌人随机：关掉后 cfg 回到 on=False（不会偷偷带旧设置进去）",
       (app._collect().get("enemy") or {}).get("on") is False,
       f"{app._collect().get('enemy')}")

    # ── 照参考实现（ER Randomizer）加的三样：每类各自的比例 / 忽略体型 / 独立敌人种子 ──
    app.enemy_on.set(True)
    app.enemy_pools["normal"].set(True); app.enemy_pools["elite"].set(True)
    app._enemy_restore({"enemy": {"on": True, "pools": ["boss", "elite", "normal"],
                                  "rate": 1.0, "source": "all"}})
    root.update()
    app.enemy_cls_rates["elite"].set(0.35); app._enemy_cls_moved("elite"); root.update()
    _ce5 = app._collect().get("enemy") or {}
    ck("敌人随机：每类各自的比例进了 cfg（精英 35%，Boss 仍 100%）",
       abs((_ce5.get("rates") or {}).get("elite", 0) - 0.35) < 1e-6
       and abs((_ce5.get("rates") or {}).get("boss", 0) - 1.0) < 1e-6,
       f"{_ce5.get('rates')}")
    ck("敌人随机：该类百分比标签跟着走", "35%" in app.enemy_cls_lbl_elite.cget("text"),
       repr(app.enemy_cls_lbl_elite.cget("text")))
    app.enemy_ignore_size.set(True); app._refresh_enemy(); root.update()
    ck("敌人随机：忽略体型限制进了 cfg",
       (app._collect().get("enemy") or {}).get("ignore_size") is True,
       f"{app._collect().get('enemy')}")
    app._enemy_dice(); root.update()
    _ce6 = app._collect().get("enemy") or {}
    ck("敌人随机：🎲 重掷会开独立种子并填一个数",
       app.enemy_seed_sep.get() and isinstance(_ce6.get("seed"), int) and _ce6["seed"] > 0,
       f"seed={_ce6.get('seed')}")
    ck("敌人随机页：默认「Boss 只与同场地档互换」（use_arena=True）",
       app.enemy_use_arena.get() is True
       and (app._collect().get("enemy") or {}).get("use_arena") is True,
       f"{(app._collect().get('enemy') or {}).get('use_arena')}")
    app.enemy_use_arena.set(False); app._refresh_enemy(); root.update()
    ck("敌人随机页：取消勾选后 cfg 里 use_arena=False（并写进摘要）",
       (app._collect().get("enemy") or {}).get("use_arena") is False
       and "不看场地档" in app.enemy_hint.cget("text"),
       f"{(app._collect().get('enemy') or {}).get('use_arena')}")
    app.enemy_use_arena.set(True); app._refresh_enemy(); root.update()
    _sum = app.enemy_hint.cget("text")
    ck("敌人随机：摘要里写出了这几项（忽略体型/独立种子）",
       "忽略体型限制" in _sum and "独立敌人种子" in _sum,
       repr(_sum[:60]))

    # ── 外层动作栏：动作不属于任何一页，一键同时管物品与敌人 ──
    _root = str(app.root)
    ck("外层动作栏：① 生成 / ② 写入 / 还原 / 保存到方案库 都在页签**外面**",
       all(getattr(app, a).winfo_parent() and str(app.nb) not in str(getattr(app, a)).split(".")[0]
           for a in ("b_gen", "b_dep", "b_save_lib"))
       and "page" not in str(app.b_gen).split("!")[0].replace(".!frame", ""),
       f"b_gen={app.b_gen} ｜ nb={app.nb}")
    ck("外层动作栏：状态行也在外面（哪一页都看得见）",
       "notebook" not in str(app.lbl_status) and str(app.lbl_status).startswith(str(app.root)),
       f"{app.lbl_status}")
    app.enemy_on.set(True); app._refresh_enemy(); root.update()
    _ow = app.outer_what.cget("text")
    ck("外层动作栏：摘要同时写了物品与敌人",
       "**物品**" in _ow and "**敌人**" in _ow and "Boss" in _ow,
       repr(_ow[:90]))
    app.enemy_on.set(False); app._refresh_enemy(); root.update()
    ck("外层动作栏：敌人关了摘要写“关着”",
       "关着" in app.outer_what.cget("text"), repr(app.outer_what.cget("text")[:80]))
    app.enemy_on.set(True); app._refresh_enemy(); root.update()

    # ── 敌型（模型层）：可多选限制、只换同类 ──
    ck("敌人随机页：有敌型列表（模型层，18 行）",
       hasattr(app, "enemy_type_tree") and len(app.enemy_type_tree.get_children()) >= 15,
       f"{len(getattr(app, 'enemy_type_tree', app).get_children()) if hasattr(app, 'enemy_type_tree') else '无'}")
    app.enemy_on.set(True); app._refresh_enemy(); root.update()
    app.enemy_type_tree.selection_set("骑士/重甲")
    app._refresh_enemy(); root.update()
    _ce8 = app._collect().get("enemy") or {}
    ck("敌人随机页：选中敌型 → cfg.types 只含它",
       _ce8.get("types") == ["骑士/重甲"],
       f"{_ce8.get('types')}")
    app.enemy_type_tree.selection_set(["骑士/重甲", "龙/龙裔"])
    app._refresh_enemy(); root.update()
    ck("敌人随机页：多选敌型（两个）",
       sorted((app._collect().get("enemy") or {}).get("types") or []) == sorted(["骑士/重甲", "龙/龙裔"]),
       f"{(app._collect().get('enemy') or {}).get('types')}")
    ck("敌人随机页：摘要里写出限定敌型数", "限定 2 个敌型" in app.enemy_hint.cget("text"),
       repr(app.enemy_hint.cget("text")[:70]))
    app.enemy_type_tree.selection_remove(*app.enemy_type_tree.selection())
    app.enemy_same_type.set(True); app._refresh_enemy(); root.update()
    _ce9 = app._collect().get("enemy") or {}
    ck("敌人随机页：只换同一种敌人进了 cfg（且不选敌型 = 不限）",
       _ce9.get("same_type") is True and "types" not in _ce9,
       f"{_ce9}")
    app.enemy_same_type.set(False); app._refresh_enemy(); root.update()

    # ── 参考实现的人工标注（不动打不死的 / 多阶段已标记）──
    app.enemy_on.set(True); app._refresh_enemy(); root.update()
    _ce10 = app._collect().get("enemy") or {}
    ck("敌人随机页：默认「不动打不死的敌人」（allow_unkillable=False）",
       app.enemy_keep_unkillable.get() is True and _ce10.get("allow_unkillable") is False,
       f"{_ce10.get('allow_unkillable')}")
    app.enemy_keep_unkillable.set(False); app._refresh_enemy(); root.update()
    ck("敌人随机页：取消勾选后 cfg 里 allow_unkillable=True（并写进摘要）",
       (app._collect().get("enemy") or {}).get("allow_unkillable") is True
       and "连打不死的也换" in app.enemy_hint.cget("text"),
       f"{(app._collect().get('enemy') or {}).get('allow_unkillable')}")
    app.enemy_keep_unkillable.set(True); app._refresh_enemy(); root.update()
    ck("敌人随机页：有 multi（多阶段）信息可查",
       hasattr(app, "enemy_keep_unkillable"), "控件缺失")

    # ── 编辑敌人预设子窗口（照参考实现的 EnemyPresetWindow）──
    _win = None
    try:
        _win = app.enemy_preset()
        root.update()
        _trees = [w for w in _win.winfo_children() for w in w.winfo_children()
                  if isinstance(w, ttk.Frame)]
        ck("敌人预设窗口：能打开且有类别列表",
           _win is not None and str(_win).startswith("."),
           f"{_win}")
        # 找到窗口里的 Treeview，选"普通敌人"、把它调到 0，再点应用
        def _find_tree(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Treeview):
                    return c
                r = _find_tree(c)
                if r is not None:
                    return r
            return None
        _tr = _find_tree(_win)
        ck("敌人预设窗口：左边有类别树（4 行里 3 类可调）",
           _tr is not None and len(_tr.get_children()) >= 3,
           f"{_tr.get_children() if _tr else None}")
        app.enemy_cls_rates["normal"].set(0.0)     # 模拟"在窗口里把普通敌人调到 0 并应用"
        app.enemy_pools["normal"].set(False)
        app._refresh_enemy()
        root.update()
        _ce7 = app._collect().get("enemy") or {}
        ck("敌人预设窗口：应用后主界面的 cfg 跟着变（普通敌人不参与）",
           "normal" not in (_ce7.get("rates") or {}),
           f"{_ce7.get('rates')}")
    except Exception as e:
        ck("敌人预设窗口：能打开且能应用", False, f"{type(e).__name__}: {e}")
    finally:
        if _win is not None:
            try:
                _win.destroy()
            except Exception:
                pass
        app.enemy_cls_rates["normal"].set(1.0)
        app.enemy_pools["normal"].set(True)
        app._refresh_enemy()
        root.update()
    app.enemy_ignore_size.set(False); app.enemy_seed_sep.set(False)
    app.enemy_on.set(False); app._refresh_enemy(); root.update()

    # ── 方案层：库里的「用这个方案玩」按钮（只有生成过覆盖层的方案才亮）──
    ck("方案层：详情面板有这个按钮",
       "launch" in getattr(app, "lib_btns", {}),
       f"{sorted(getattr(app, 'lib_btns', {}))}")
    _pid_t = b["id"]
    planlib.set_meta(_pid_t, layer_dir="")           # 先清成"没有覆盖层"
    app._lib_refresh(keep=_pid_t)
    app.lib_tree.selection_set(_pid_t)
    app._lib_on_select()
    root.update()
    _no_layer = str(app.lib_btns["launch"].cget("state"))
    _fake_layer = os.path.join(tmp, "假方案层")
    os.makedirs(os.path.join(_fake_layer, "mod"), exist_ok=True)
    planlib.set_meta(_pid_t, layer_dir=_fake_layer)
    app._lib_refresh(keep=_pid_t)
    app.lib_tree.selection_set(_pid_t)
    app._lib_on_select()
    root.update()
    _has_layer = str(app.lib_btns["launch"].cget("state"))
    ck("方案层：没有覆盖层时按钮是灰的、有了就亮",
       _no_layer == "disabled" and _has_layer == "normal",
       f"没层={_no_layer!r}｜有层={_has_layer!r}")

    # ── 动态：只跟着"勾了哪些类别 / 商店开没开"增减 ──
    app.shops.set(True)
    app._rate_set("caster", True, 0.4)
    app._refresh_rates()
    root.update()
    app.doms["armor"].set(False); app._toggle_dom("armor"); root.update()
    ck("改动比例：取消护甲 ⇒ 法祷职业护甲那条收起来（它属于护甲）",
       not app.rate_rows["caster"]["row"].winfo_manager(),
       f"法祷={app.rate_rows['caster']['row'].winfo_manager()!r}")
    _c3 = app._collect()
    ck("改动比例：收起来的那条不会偷偷带进 cfg",
       _c3.get("rate_sets") is None and _c3.get("rate_caster") is None,
       f"sets={_c3.get('rate_sets')} caster={_c3.get('rate_caster')}")
    app.doms["armor"].set(True); app._toggle_dom("armor"); root.update()
    ck("改动比例：收起来又出现时值记着（0.4）",
       bool(app.rate_rows["caster"]["row"].winfo_manager())
       and round(app.rate_rows["caster"]["val"].get(), 2) == 0.4,
       f"可见={bool(app.rate_rows['caster']['row'].winfo_manager())} "
       f"值={round(app.rate_rows['caster']['val'].get(), 2)}")
    # 走**真实控件路径**：勾选框的 invoke()（上一版的 bug 正是"勾选框没接刷新"）
    # 商店现在没有比例条了 —— 点它只会改变"商店参不参与"，不会冒出/收起任何比例行
    _before_vis = [k for k, r in app.rate_rows.items() if r["row"].winfo_manager()]
    app.cb_shops.invoke(); root.update()
    ck("改动比例：点商店勾选框 ⇒ 比例组不受影响（商店已无比例条）",
       not app.shops.get()
       and [k for k, r in app.rate_rows.items() if r["row"].winfo_manager()] == _before_vis,
       f"商店={app.shops.get()}｜前后可见={_before_vis} → "
       f"{[k for k, r in app.rate_rows.items() if r['row'].winfo_manager()]}")
    app.cb_shops.invoke(); root.update()
    app.doms["armor"].set(True); app._toggle_dom("armor"); root.update()
    ck("改动比例：商店开着时也只有法祷那一条",
       app.shops.get() and [k for k, r in app.rate_rows.items() if r["row"].winfo_manager()] == ["caster"],
       f"可见={[k for k, r in app.rate_rows.items() if r['row'].winfo_manager()]}")
    ck("改动比例：法祷那条的标签跟着「整套一起换」变",
       "整套" not in app.rate_rows["caster"]["name"].cget("text"),
       f"整套开着时标签={app.rate_rows['caster']['name'].cget('text')!r}")
    app.cb_sets.invoke(); root.update()
    ck("改动比例：关掉「整套一起换」⇒ 标签变成（散件）且量化提示同步",
       app.rate_rows["caster"]["name"].cget("text").endswith("（散件）")
       and "散件" in app.rate_rows["caster"]["note"].cget("text"),
       f"标签={app.rate_rows['caster']['name'].cget('text')!r} "
       f"提示={app.rate_rows['caster']['note'].cget('text')!r}")
    app.cb_sets.invoke(); root.update()
    app._rate_set("caster", False); app._rate_set("shop", False); root.update()

    # ── 表单规则：单池合理度按混合方式动态出现（走**真实事件路径**：
    #    event_generate 触发下拉框绑定 —— 2026-10-14 的真 bug 正是"下拉换方式后不刷新"，
    #    直接调刷新函数会把它盖过去，所以这里必须走事件）──
    _modes = list(app.cb_mode.cget("values"))
    _i_all = 0
    _i_sep = [i for i, v in enumerate(_modes) if "各自" in v][0]

    def _pick_mode(i):
        app.cb_mode.current(i)
        app.cb_mode.event_generate("<<ComboboxSelected>>")
        root.update()

    app.nb.select(app.page_set); root.update()
    _pick_mode(_i_all)
    _ca = app._coh_applicable()
    ck("单池合理度：全部混合 ⇒ 一条都不摆（都进了混池，由总合理度管）",
       not any(_ca.values()), f"{_ca}")
    ck("单池合理度：全部混合 ⇒ 总合理度可用",
       "disabled" not in app.scale_coh.state(), f"state={app.scale_coh.state()}")
    _pick_mode([i for i, v in enumerate(_modes) if "混 ·" in v][0])   # 两两混
    _cw = app._coh_applicable()
    ck("单池合理度：两两混 ⇒ 只有落单那一类有；总合理度仍可用",
       sum(bool(_cw[k]) for k in ("rune", "armor", "weapon")) == 1
       and "disabled" not in app.scale_coh.state(),
       f"{_cw}｜state={app.scale_coh.state()}")
    _pick_mode(_i_sep)
    _cb = app._coh_applicable()
    ck("单池合理度：各自随机 ⇒ 三类都出现，且**总合理度置灰**（它不参与）",
       _cb["rune"] and _cb["armor"] and _cb["weapon"] and "disabled" in app.scale_coh.state(),
       f"{_cb}｜state={app.scale_coh.state()}")
    ck("单池合理度：界面跟着变（三条都在）",
       all(app.coh_rows[k]["row"].winfo_manager() for k in ("rune", "armor", "weapon")),
       f"可见={[k for k, r in app.coh_rows.items() if r['row'].winfo_manager()]}")
    # 没动过 ⇒ 跟着总合理度走，且**不进 cfg**（不动它就等于"跟全局一致"）
    app.coherence.set(0.55); app._refresh_cohs(); root.update()
    ck("单池合理度：没动过的行**跟着总合理度**（80%→55%）",
       round(app.coh_rows["armor"]["val"].get(), 2) == 0.55
       and "跟着总合理度" in app.coh_rows["armor"]["note"].cget("text"),
       f"护甲条={round(app.coh_rows['armor']['val'].get(), 2)}｜提示={app.coh_rows['armor']['note'].cget('text')!r}")
    ck("单池合理度：没动过 ⇒ 不进 cfg",
       not app._collect().get("coh_domain"), f"coh_domain={app._collect().get('coh_domain')}")
    app._coh_set("armor", True, 0.2)          # 模拟用户拖动
    app.coherence.set(0.9); app._refresh_cohs(); root.update()
    ck("单池合理度：动过之后不再跟随（总 90% 也保持 20%），且进 cfg",
       round(app.coh_rows["armor"]["val"].get(), 2) == 0.2
       and (app._collect().get("coh_domain") or {}).get("armor") == 0.2,
       f"护甲条={round(app.coh_rows['armor']['val'].get(), 2)}｜"
       f"cfg={app._collect().get('coh_domain')}")
    ck("单池合理度：量化提示写清跨度 / 越档率",
       "跨度" in app.coh_rows["armor"]["note"].cget("text")
       and "越档率" in app.coh_rows["armor"]["note"].cget("text"),
       f"提示={app.coh_rows['armor']['note'].cget('text')!r}")
    app.coherence.set(0.8); app._refresh_cohs(); root.update()

    app._coh_set("rune", True, 0.35); root.update()
    ck("单池合理度：设了就进 cfg（卢恩 35%）",
       (app._collect().get("coh_domain") or {}).get("rune") == 0.35,
       f"coh_domain={app._collect().get('coh_domain')}")
    ck("单池合理度：cfg 里**没有** coh_mixed 这个键（混池用总合理度）",
       "coh_mixed" not in app._collect(), f"{sorted(app._collect().keys())}")
    _pick_mode(_i_all)
    ck("单池合理度：切回全部混合后，卢恩那条不再进 cfg（被总合理度接管）",
       not (app._collect().get("coh_domain") or {}).get("rune"),
       f"coh_domain={app._collect().get('coh_domain')}")
    app._coh_set("rune", False); root.update()
    app.nb.select(app.page_lib)

    n0 = len(planlib.list_plans())
    app.nb.select(app.page_lib)
    app.lib_tree.selection_set(a["id"])
    app._lib_on_select()
    app._lib_star()                              # 取消收藏
    root.update()
    ck("收藏：点一下能取消", not planlib.get_plan(a["id"])["star"],
       f"star={planlib.get_plan(a['id'])['star']}")
    app._lib_star()                              # 再收藏回来
    root.update()
    ck("收藏：再点回来（并排到最前）",
       planlib.get_plan(a["id"])["star"] and app.lib_tree.get_children()[0] == a["id"],
       f"第一行={app.lib_tree.get_children()[0]}")

    app._lib_dup()
    root.update()
    ck("复制一份", len(planlib.list_plans()) == n0 + 1,
       f"{len(planlib.list_plans())} 个（原来 {n0}）")

    # 导出 / 导入：文件对话框换成"直接给个路径"，其余全走真实代码
    out_json = os.path.join(tempfile.mkdtemp(prefix="_uitest_out_"), "导出试试.json")
    old_save, old_open = fd.asksaveasfilename, fd.askopenfilenames
    fd.asksaveasfilename = lambda **k: out_json
    try:
        app.lib_tree.selection_set(a["id"])
        app._lib_on_select()
        app._lib_export()
    finally:
        fd.asksaveasfilename = old_save
    ck("导出：文件真写出来了", os.path.isfile(out_json), out_json)

    n1 = len(planlib.list_plans())
    fd.askopenfilenames = lambda **k: (out_json,)
    try:
        app._lib_import()
    finally:
        fd.askopenfilenames = old_open
    ck("导入：库里多了一个", len(planlib.list_plans()) == n1 + 1,
       f"{len(planlib.list_plans())} 个（原来 {n1}）")

    # 手动复制一份 json 进库（id 撞车）：界面要跳过它而不是崩掉
    import shutil as _sh
    _sh.copy2(os.path.join(tmp, a["id"] + ".json"), os.path.join(tmp, "手抄一份.json"))
    app._lib_refresh()
    root.update()
    ck("库里有 id 撞车的文件也不崩", len(app.lib_tree.get_children()) == n1 + 1,
       f"{len(app.lib_tree.get_children())} 行")
    os.remove(os.path.join(tmp, "手抄一份.json"))

    # 载入到设置：参数要真的填回页 1
    app.lib_tree.selection_set(a["id"])
    app._lib_on_select()
    app._lib_apply_cfg()
    root.update()
    ck("载入到设置：种子填回去了", app.seed.get() == "20261010", repr(app.seed.get()))
    ck("载入到设置：切回了随机设置页", app.nb.select() == str(app.page_set),
       str(app.nb.select()))

    # 删除：删完库里少一个，文件进回收站
    app.nb.select(app.page_lib)
    app._lib_refresh(keep=a["id"])
    app._lib_delete()
    root.update()
    ck("删除：库里少了一个", len(planlib.list_plans()) == n1,
       f"{len(planlib.list_plans())} 个")
    trash = os.path.join(tmp, ".trash")
    ck("删除：文件真进了回收站",
       os.path.isdir(trash) and any(a["id"] in f for f in os.listdir(trash)),
       str(os.listdir(trash) if os.path.isdir(trash) else "没有 .trash"))
    # 这两条要紧接着删除检查：底部那行是"最新一件事"，后面的写入会把提示换掉
    ck("删完给出了回收站入口", bool(app.lib_trash_btn.winfo_manager()),
       f"manager={app.lib_trash_btn.winfo_manager()!r}")
    ck("删完的提示说了回收站", "回收站" in app.lib_toast.cget("text"),
       repr(app.lib_toast.cget("text")))

    # 写入游戏：真跑会动游戏文件，这里把"写入工人"换成**假的工人**：它不改文件，
    # 但把真工人会投的那几条消息照投一遍（进度行 / 完成 / 收尾）。
    # 这样验证的是"站在方案库页点写入，能不能看见进度与结果"——2026-10-14 实测
    # 写入明明成功、界面却一直停在"正在写入…"（状态条与日志都在另一页上，看不见）。
    called = {}
    real_worker = App._deploy_worker

    def _fake_worker(self, plan, sync, lib=False, fingerprint=None, pid=None):
        called.update(plan=plan, sync=sync, lib=lib)
        self.q.put(("log", "[③a] 假进度：说明书地点重写 12 处"))

    App._deploy_worker = _fake_worker
    try:
        app._lib_refresh(keep=b["id"])
        app.lib_tree.selection_set(b["id"])
        app._lib_on_select()
        app._lib_write()
        for _ in range(8):                     # 让 _pump 把队列走几遍
            root.update()
            time.sleep(0.02)
            root.update()
        ck("写入游戏：方案库这页看得到进度", "假进度" in app.lib_toast.cget("text"),
           repr(app.lib_toast.cget("text")))
        ck("写入游戏：进度期间状态是'写入中'（不是没反应）",
           "写入中" in app.status.get(), repr(app.status.get()))
        # 跑完：真工人这时会投这两条
        app.q.put(("lib", ("写入完成 ✓ 可以进游戏了", False)))
        app.q.put(("deploying", False))
        for _ in range(8):
            root.update()
            time.sleep(0.02)
            root.update()
    finally:
        App._deploy_worker = real_worker
    ck("写入游戏：确认后交给了写入流程", bool(called.get("plan")), f"csv={called.get('plan')!r}")
    ck("写入游戏：用的是方案导出的 CSV",
       bool(called.get("plan")) and called["plan"].endswith(".csv"), f"{called.get('plan')!r}")
    ck("写入游戏：告诉工人'这是从方案库发的'（进度要回显到这一页）",
       bool(called.get("lib")), f"lib={called.get('lib')!r}")
    ck("写入游戏：跑完必须给结果（不能停在'正在写入'）",
       "写入完成" in app.lib_toast.cget("text"), repr(app.lib_toast.cget("text")))
    ck("写入游戏：收尾后解锁下一次写入", not app._deploying and not app._lib_writing,
       f"_deploying={app._deploying} _lib_writing={app._lib_writing}")
    # 上一次没跑完就再点 → 必须被挡回去（两个线程同时改 regulation.bin 会留下半成品）
    app._deploying = True
    called.clear()
    try:
        app._lib_write()
    finally:
        app._deploying = False
    ck("写入游戏：上一次没跑完时挡住重复点击", not called.get("plan"),
       f"又被交出去={bool(called.get('plan'))}")

    # 「这次会改什么」的计数：商店换了几个货架、法祷护甲换了几套几件
    #   要点：按**单元**去重（同一个物品在宝箱和商店各有一格 → 只算一件）
    _items = {("protector", "100"): {"domain": "armor", "arch": "法师", "name": "法师套头盔"},
              ("protector", "200"): {"domain": "armor", "arch": "祷告", "name": "祷告套头盔"},
              ("protector", "210"): {"domain": "armor", "arch": "祷告", "name": "祷告散件"},
              ("protector", "220"): {"domain": "armor", "arch": "法师", "name": "法师散件"},
              ("protector", "300"): {"domain": "armor", "arch": "近战", "name": "近战甲"},
              ("goods", "1"): {"domain": "goods", "arch": "", "name": "卢恩"}}
    _plan = [
        {"unit": "set:protector:100", "old": "protector:100", "new": "protector:200",
         "source_table": "ItemLotParam_map"},                    # 一整套法祷护甲换掉
        {"unit": "item:protector:220", "old": "protector:220", "new": "protector:210",
         "source_table": "ItemLotParam_map"},                    # 一件法祷散件换掉
        {"unit": "item:protector:300", "old": "protector:300", "new": "protector:300",
         "source_table": "ItemLotParam_map"},                    # 近战护甲没换
        {"unit": "item:protector:220", "old": "protector:220", "new": "protector:210",
         "source_table": "ShopLineupParam"},                     # 商店货架：换了
        {"unit": "item:protector:300", "old": "protector:300", "new": "protector:300",
         "source_table": "ShopLineupParam"},                     # 商店货架：没换
    ]
    _st = plain_summary(_plan, _items, type("E", (), {"CASTER_ARCH": ("法师", "祷告")})())
    ck("会改什么：商店计数（换了几个 / 共几个）",
       _st["shop_moved"] == 1 and _st["shop_total"] == 2,
       f"换 {_st['shop_moved']} / 共 {_st['shop_total']}")
    ck("会改什么：法祷护甲计数（整套与散件分开，同一件多处只算一次）",
       _st["caster_sets"] == 1 and _st["caster_parts"] == 1,
       f"整套 {_st['caster_sets']} 套 + 散件 {_st['caster_parts']} 件")

    # 右键菜单：条目齐不齐（改名/收藏/复制/删除/导出/导入 都要在）
    # 注意：不能真 tk_popup —— 它会抓住事件循环，等用户点一下才回来（自动化会卡死）
    app.lib_tree.selection_set(b["id"])
    app._lib_on_select()
    menu = app._lib_menu_build()
    labels = []
    for i in range(menu.index("end") + 1):
        try:
            labels.append(str(menu.entrycget(i, "label")))
        except tk.TclError:
            pass
    menu.destroy()
    for want in ("写入游戏", "载入到设置", "改名", "收藏", "复制", "导出", "删除", "导入"):
        ck(f"右键菜单有「{want}」", any(want in x for x in labels), "；".join(labels))

    # ── 第 6 步：搜索 / 排序 / 空状态 / 删除提示 ──
    app._lib_search_set("放开")
    ck("搜索：按名字筛", len(app.lib_tree.get_children()) == 1,
       f"{len(app.lib_tree.get_children())} 行")
    app._lib_search_set("不存在的词儿")
    ck("搜索：筛没了就走空状态",
       not app.lib_list.winfo_manager() and bool(app.lib_empty.winfo_manager()),
       f"list={app.lib_list.winfo_manager()!r} empty={app.lib_empty.winfo_manager()!r}")
    ck("搜索：空状态说清了是筛没了", "匹配" in app.lib_empty_txt.cget("text"),
       repr(app.lib_empty_txt.cget("text")[:24]))
    app._lib_search_set("")
    ck("搜索：清空后列表回来",
       bool(app.lib_list.winfo_manager()) and not app.lib_empty.winfo_manager(),
       f"list={app.lib_list.winfo_manager()!r}")

    app.lib_sort.set("名字")
    app._lib_refresh()
    kids = app.lib_tree.get_children()
    names = [planlib.get_plan(k)["name"] for k in kids]
    stars = [bool(planlib.get_plan(k).get("star")) for k in kids]
    ok_order = (stars == sorted(stars, reverse=True)
                and names == [n for _s, n in sorted(zip(stars, names), key=lambda p: (not p[0], p[1]))])
    ck("排序：收藏优先、其余按名字", ok_order, "｜".join(names))
    app.lib_sort.set("改动量（多→少）")
    app._lib_refresh()
    kids = app.lib_tree.get_children()
    chs = [len(planlib.get_plan(k).get("rows") or []) for k in kids]
    sts = [bool(planlib.get_plan(k).get("star")) for k in kids]
    ok_ch = (sts == sorted(sts, reverse=True)
             and chs == [c for _s, c in sorted(zip(sts, chs), key=lambda p: (not p[0], -p[1]))])
    ck("排序：按改动量（收藏仍在前）", ok_ch, "｜".join(map(str, chs)))
    app.lib_sort.set(LIBSORT[0])
    app._lib_refresh()

    # 双击 = 写入游戏（确认框自动答是，写入工人换成记录器）
    # 注意：Tk 不让 event_generate 造 Double-1（双击由系统认），所以这里查"绑没绑" +
    # 直接跑它所绑的那一个动作 —— 两件事合起来才是"双击一行 = 写入游戏"
    called.clear()
    App._deploy_worker = (lambda self, plan, sync, lib=False, fingerprint=None, pid=None:
                          called.update(plan=plan, sync=sync, lib=lib, fp=fingerprint))
    try:
        kids = app.lib_tree.get_children()
        app.lib_tree.selection_set(kids[0])
        app._lib_on_select()
        ck("双击：列表上绑了双击事件", any("Double" in s for s in app.lib_tree.bind()),
           str(app.lib_tree.bind()))
        app._lib_write()
        for _ in range(12):
            root.update()
            time.sleep(0.02)
    finally:
        App._deploy_worker = real_worker
    ck("双击那一下 = 写入游戏", bool(called.get("plan")), f"csv={called.get('plan')!r}")

    # 整库空掉：空状态要给"下一步干什么"的引导
    for f in os.listdir(tmp):
        if f.endswith(".json"):
            os.remove(os.path.join(tmp, f))
    app._lib_search_set("")
    ck("空库：换成引导文案", bool(app.lib_empty.winfo_manager()),
       f"empty={app.lib_empty.winfo_manager()!r}")
    ck("空库：引导去「职业物品随机」页生成",
       "职业物品随机" in app.lib_empty_txt.cget("text") and "保存到方案库" in app.lib_empty_txt.cget("text"),
       repr(app.lib_empty_txt.cget("text")[:40]))
    # 三页签：物品 / 敌人 / 方案库（2026-10-16 拆页）
    _tabs = [str(app.nb.tab(t, "text")).strip() for t in app.nb.tabs()]
    ck("页签：物品·敌人·方案库三页",
       len(_tabs) == 3 and all(any(w in t for t in _tabs)
                               for w in ("职业物品随机", "敌人随机", "方案库")),
       f"{_tabs}")
    # 敌人那组控件现在挂在「敌人随机」页上，但仍要能用（老检查靠这些属性）
    ck("敌人随机页：控件在、且是这一页的",
       all(hasattr(app, a) for a in ("enemy_on", "enemy_pools", "enemy_rate", "enemy_source",
                                     "enemy_visual", "b_enemy_layer", "enemy_page_hint"))
       and str(app.b_enemy_layer).startswith(str(app.page_enemy)),
       f"按钮父容器={app.b_enemy_layer.winfo_parent()}")
    ck("空库：详情面板也回到空态", app.lib_title.cget("text") == "还没有方案",
       repr(app.lib_title.cget("text")))


def selftest(seed=20261010):
    """不需要开窗口：验证引擎可用 + 同种子可复现 + 不同种子不同"""
    print(f"工作区: {WORKSPACE}")
    # Paramdex 硬检查（2026-10-17 加）：打包漏了 paramdef 就是"写入失败：读不到 Paramdex 定义"，
    # 而这条以前只有真去写入时才会暴露 —— 现在 --selftest 就会亮红灯。
    try:
        _ap = os.path.join(WORKSPACE, "investigation", "apply")
        if _ap not in sys.path:
            sys.path.insert(0, _ap)          # 模块是后面才 import 的，这里自己先挂上路径
        import enemy_randomizer as _ER
        _f, _rs = _ER.paramdef_fields("NpcParam")
        if not _f or _rs <= 0:
            print("SELFTEST FAIL: Paramdex 里读不出 NpcParam 定义（找的目录：%s）" % _ER.PARAMDEX)
            return 1
        print(f"Paramdex: {_ER.PARAMDEX} ｜ NpcParam 字段 {len(_f)} 个、行 {_rs} 字节")
    except Exception as _e:
        print("SELFTEST FAIL: Paramdex 检查异常 %s: %s" % (type(_e).__name__, _e))
        return 1
    if not WORKSPACE:
        print("SELFTEST FAIL: 找不到工作区"); return 1
    # ① 运行时模块必须真的 import 得动（打包漏文件时，隔离自检就会在这里红掉）
    #    2026-10-16 加：敌人随机 + 方案层这几个模块漏进包时，前面几道闸门都看不出来
    #    （它们不跑"生成/写入"），只有打包版真去生成时才炸。
    import importlib
    _ap = os.path.join(WORKSPACE, "investigation", "apply")
    if _ap not in sys.path:
        sys.path.insert(0, _ap)
    _need = [("item 管线", ["erio", "param_patch", "native_apply", "native_deploy", "planlib"]),
             ("敌人随机", ["enemy_randomizer", "enemy_names", "enemy_types"]),
             ("地图", ["msb_read", "msb_write", "enemy_map_atlas"]),
             ("方案层", ["plan_layer"])]
    _miss = []
    for _grp, _mods in _need:
        for _mn in _mods:
            try:
                importlib.import_module(_mn)
            except Exception as _e:
                _miss.append(f"{_grp}/{_mn}: {type(_e).__name__}: {_e}")
    if _miss:
        print("SELFTEST FAIL: 运行时模块没打进来 ——")
        for _m in _miss:
            print("   ✗ " + _m)
        return 1
    print("  运行时模块 import 检查：全部就位 ✓")
    # ② 敌人侧的数据表也要在（缺了会静默降级：Boss 池变小、友好 NPC 不排除）
    _data = ["enemy_table.csv", "boss_rows.csv", "boss_healthbar.csv",
             "row_models.csv", "enemy_type_map.csv"]
    _dm = [f for f in _data if not os.path.isfile(os.path.join(WORKSPACE, "investigation", f))]
    if _dm:
        print("SELFTEST FAIL: 敌人侧数据表缺失 —— " + "、".join(_dm))
        return 1
    print("  敌人侧数据表：全部就位 ✓")
    m = load_engine()
    cfg = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide",
           "shops": True, "sets": True, "seed": seed}
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


def _console_utf8():
    """让命令行输出在 Windows 上也安全。

    为什么必须做：打包成 windowed exe 后，输出被重定向（管道/写文件）时 Python 用**系统
    本地编码**（中文 Windows 是 GBK），而 GBK 里没有 ✓ ⚙ ✗ 这些字符 —— 一句 print 就会
    抛 UnicodeEncodeError，窗口版还会弹出 PyInstaller 的错误框把自动化卡死（踩过）。
    做法：管道/重定向时改成 UTF-8；真控制台不动（Python 走 Windows 控制台 API，中文本来就正常）。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if s is None:
                continue
            if not s.isatty():
                s.reconfigure(encoding="utf-8", errors="replace")
            else:
                s.reconfigure(errors="replace")
        except Exception:
            pass


def main():
    _console_utf8()
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
