# randgui.py — 法魂职业道具和装备随机器（人话版界面）
#
#   · 只换物品，不搬位置；随时可一键还原
#   · 同一种子 = 完全一样的结果
#   · 命令行：--selftest 自检 ｜ --uicheck 只建界面不显示（供自动化测试）
#              --uitest 方案库交互自检 ｜ --planlib 方案库模块自检 ｜ --deploy plan.csv 部署
import collections, importlib.util, json, os, queue, random, re, shutil, sys, threading, time
import tkinter as tk
from tkinter import messagebox, ttk


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

# 敌人分类的中文显示名（引擎/预设 JSON 里仍用英文 key，只有界面显示中文）
ENEMY_CLASS_CN = {
    "Basic": "常规敌人",
    "Wildlife": "被动野生动物",
    "Mob": "法魂杂兵",
    "Boss": "主要BOSS",
    "MinorBoss": "次要BOSS",
    "Miniboss": "野外BOSS",
    "NightMiniboss": "夜间BOSS",
    "DragonMiniboss": "龙类BOSS",
    "Evergaol": "封印监牢BOSS",
    "HostileNPC": "敌对型人类",
    "Scarab": "粪金龟",
    "CaravanTroll": "商队巨魔",
    "Helper": "随从 / 召唤物",
    "DupeOnly": "复制体",
    "None": "未分类",
    "Dummy": "假人 / 测试体",
}
ENEMY_RULE_CN = {
    "multiphase_boss": "多阶段BOSS组",
    "waygate_guardian": "黄金树传送门守卫",
    "bossbar_position": "有BOSS血条的位置",
    "boss_any": "全类别BOSS互随",
    "fauna": "常规敌人 / 被动野生动物（含法魂杂兵）",
    "scarab": "粪金龟",
    "caravan_troll": "商队巨魔",
}


def enemy_class_cn(cls):
    """英文类名 → 中文显示（界面用；引擎与 JSON 仍用英文 key）。"""
    return ENEMY_CLASS_CN.get(cls, cls)


def enemy_rule_cn(rid):
    """规则 id → 中文显示（预览结果里用）。"""
    if rid.startswith("preset:"):
        return "预设：" + enemy_class_cn(rid.split(":", 1)[1])
    return ENEMY_RULE_CN.get(rid, rid)


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


def _is_layer_dir(d):
    """方案层里也有 mod/regulation.bin —— 别把它当成法魂包本体。

    2026-10-23 实测：双击方案层的「用这个方案启动.bat」时工作目录就是层根，
    旧逻辑把层根发布成 CONVERGENCE_MOD_ROOT，接着 pack_root() 找不到 yafsml/、
    整条启动就断了。
    """
    try:
        return os.path.basename(os.path.dirname(os.path.abspath(d))) == "方案"
    except OSError:
        return False


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
        if _looks_like_mod(c) and not _is_layer_dir(c):
            return c
    return None


def _pack_of_layer(layer):
    """从方案层往上找法魂包根目录（判据：那一层有 yafsml/）；找不到返回 ""。"""
    cur = os.path.abspath(layer)
    for _ in range(4):
        nxt = os.path.dirname(cur)
        if not nxt or nxt == cur:
            break
        cur = nxt
        if os.path.isdir(os.path.join(cur, "yafsml")):
            return cur
    return ""


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
        _regs = sorted(_g.glob(os.path.join(ap, "backup", "regulation.bin.orig_*")))
        n_orig += len(_regs)
        n_orig += len(_g.glob(os.path.join(ap, "backup", "item_dlc02.msgbnd.dcx.zhocn.orig_*")))
        _ok, _note = n_orig >= 2, (f"找到 {n_orig}/2 份" if n_orig
                                   else "缺原始备份：不能「还原成原始」，也不建议写入")
        if _ok and _regs:
            # 2026-10-23：备份本身也可能是错的 —— 把"已经被随机过的本体"登记成了原始。
            # 那样写入会整批对不上（实测 766/766），但报错只会说"换过 MOD 版本？"。
            try:
                if ap not in sys.path:
                    sys.path.insert(0, ap)
                import native_apply as _na
                _pr = _na.pristine_probe(_regs[-1])
                if _pr.get("rate") is not None and _pr["rate"] < 0.97:
                    _ok = False
                    _note = ("⚠ 这份「原始备份」不像原始版（%d/%d 个格子与工具快照不符）："
                             "可能备份了已经随机过的本体 —— 写入会整批对不上" %
                             (_pr["match"], _pr["checked"]))
            except Exception:
                pass
        add("原始备份（必需）", _ok, _note, os.path.join(ap, "backup"))
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
#  视觉系统 · 暗色金（法环味，2026-10-17 重做）
# ══════════════════════════════════════════════════════════════════════
#  为什么必须 clam：vista / winnative 会**忽略**你设的 background / foreground，
#  界面上会一半暗一半亮。clam 是唯一会老实使用给定颜色的内置主题。
#
#  设计口径（这一版刻意收着）：
#   · 底色再压暗一档，让"金"只出现在该出现的地方（标题、主按钮、选中线）；
#   · 用**细边框 + 留白**分组（卡片），不再让 LabelFrame 的浮雕边框把界面切成碎块；
#   · 一屏只留一个金色主按钮，其余按钮降级为描边/文字按钮 —— 权重靠明度排，不靠框；
#   · 正文/次文/三级文三档字色，说明文字不再和主内容抢视线。
BG        = "#131009"   # 窗口底（近黑、偏暖）
BG_ELEV   = "#1a1510"   # 顶栏 / 底栏
PANEL     = "#1e1a14"   # 按钮底 / 表头
PANEL_2   = "#262118"   # 更高一档：悬停 / 选中 / 描边按钮
FIELD     = "#0d0b08"   # 输入框底
EDGE      = "#3a3226"   # 结构线
EDGE_SOFT = "#2a241b"   # 分隔线
FG        = "#ece5d6"   # 主文字
SUB       = "#b6aa94"   # 次文字（说明 / 字段名）
MUTED     = "#8e8473"   # 三级文字（脚注 / 占位）
GOLD      = "#d6b45f"   # 金：标题 / 强调 / 选中
GOLD_LT   = "#f0d894"   # 亮金
GOLD_DIM  = "#8a7334"   # 暗金：装饰线 / 未选中
DANGER    = "#e57b6e"   # 危险文字（删除 / 还原）
DANGER_FILL = "#8f3b33" # 危险按钮按下/悬停时的底色
SUCCESS   = "#93c39a"   # 通过 / 就绪
SEL_BG    = "#38301f"   # 选中行底
DISABLED  = "#8b8478"   # 禁用文字
BTN_HOVER = "#2b251b"   # 按钮悬停
BTN_PRESS = "#342c1f"   # 按钮按下
HEAD_BG   = "#231e16"   # 表头
WHITE     = "#ffffff"   # 选中时的文字
INK       = "#171208"   # 金底上的字

FONT_NAME = "Microsoft YaHei UI"
FONT_UI = (FONT_NAME, 11)          # 11pt：中文 10pt 在暗底上偏小
FONT_SMALL = (FONT_NAME, 10)
FONT_MICRO = (FONT_NAME, 9)        # 眉标 / 脚注
FONT_H1 = (FONT_NAME, 20, "bold")  # 页面标题
FONT_H2 = (FONT_NAME, 13, "bold")  # 卡片标题
FONT_H3 = (FONT_NAME, 11, "bold")  # 小节标题 / 导航
FONT_NUM = ("Georgia", 20, "bold")  # 数字（合理度 / 百分比）
FONT_TITLE = FONT_H2               # 兼容旧引用：库详情等地方的小标题


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

    ttk 控件认这套样式表；不带 ttk 的 tk 控件（tk.Text / tk.Frame / tk.Label）不认 ——
    那些只能逐个传 bg= / fg=（卡片、顶栏、底栏都是这种）。uicheck() 会扫一遍亮块。
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
    st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=EDGE,
                 lightcolor=BG, darkcolor=BG, focuscolor=GOLD)
    for w in ("TFrame", "TPanedwindow"):
        st.configure(w, background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Card.TFrame", background=BG)          # 卡片内容区（与窗口同底，靠描边分组）
    st.configure("Head.TFrame", background=BG_ELEV)
    st.configure("Footer.TFrame", background=BG_ELEV)

    # ── 文字层级（ttk 用样式；tk.Label 在 helpers 里直接给色）──
    st.configure("PageTitle.TLabel", background=BG, foreground=FG, font=FONT_H1)
    st.configure("PageDesc.TLabel", background=BG, foreground=SUB, font=FONT_SMALL)
    st.configure("Eyebrow.TLabel", background=BG, foreground=GOLD, font=FONT_MICRO)
    st.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_H2)
    st.configure("CardTitle.TLabel", background=BG, foreground=FG, font=FONT_H2)
    st.configure("CardDesc.TLabel", background=BG, foreground=SUB, font=FONT_SMALL)
    st.configure("Body.TLabel", background=BG, foreground=FG)
    st.configure("Sub.TLabel", background=BG, foreground=SUB)
    st.configure("Hint.TLabel", background=BG, foreground=SUB, font=FONT_SMALL)
    st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
    st.configure("Gold.TLabel", background=BG, foreground=GOLD_LT)
    st.configure("Num.TLabel", background=BG, foreground=GOLD_LT, font=FONT_NUM)
    st.configure("Good.TLabel", background=BG, foreground=SUCCESS)
    st.configure("Bad.TLabel", background=BG, foreground=DANGER)
    st.configure("Status.TLabel", background=BG_ELEV, foreground=GOLD_LT, font=FONT_SMALL)
    st.configure("HeadEyebrow.TLabel", background=BG_ELEV, foreground=GOLD, font=FONT_MICRO)
    st.configure("HeadTitle.TLabel", background=BG_ELEV, foreground=FG, font=FONT_H1)
    st.configure("HeadSub.TLabel", background=BG_ELEV, foreground=SUB, font=FONT_SMALL)
    st.configure("Footer.TLabel", background=BG_ELEV, foreground=SUB, font=FONT_SMALL)
    st.configure("FooterGold.TLabel", background=BG_ELEV, foreground=GOLD_LT, font=FONT_SMALL)
    st.configure("FooterBad.TLabel", background=BG_ELEV, foreground=DANGER, font=FONT_SMALL)
    st.configure("Deco.TLabel", background=BG)          # 装饰图（空库插画等）

    # ── 按钮：四级权重（金主 / 描边 / 文字 / 危险），一屏只给一个金主按钮 ──
    st.configure("TButton", background=PANEL, foreground=FG, bordercolor=EDGE,
                 lightcolor=PANEL, darkcolor=PANEL, focuscolor=PANEL,
                 borderwidth=1, relief="flat", padding=(px(14), px(7)))
    st.map("TButton",
           background=[("disabled", FIELD), ("pressed", BTN_PRESS), ("active", BTN_HOVER)],
           foreground=[("disabled", DISABLED)],
           bordercolor=[("focus", GOLD), ("disabled", EDGE_SOFT)])
    st.configure("Primary.TButton", background=GOLD, foreground=INK, bordercolor=GOLD,
                 lightcolor=GOLD, darkcolor=GOLD, focuscolor=GOLD,
                 borderwidth=0, relief="flat", font=(FONT_NAME, 11, "bold"),
                 padding=(px(22), px(9)))
    st.map("Primary.TButton",
           background=[("disabled", FIELD), ("pressed", GOLD_LT), ("active", GOLD_LT)],
           foreground=[("disabled", DISABLED)], bordercolor=[("disabled", FIELD)])
    # 兼容旧名字（敌人预设「应用」等还在用 Accent）
    st.configure("Accent.TButton", background=GOLD, foreground=INK, bordercolor=GOLD,
                 lightcolor=GOLD, darkcolor=GOLD, focuscolor=GOLD,
                 borderwidth=0, relief="flat", font=(FONT_NAME, 11, "bold"),
                 padding=(px(18), px(8)))
    st.map("Accent.TButton",
           background=[("disabled", FIELD), ("pressed", GOLD_LT), ("active", GOLD_LT)],
           foreground=[("disabled", DISABLED)], bordercolor=[("disabled", FIELD)])
    st.configure("Secondary.TButton", background=PANEL_2, foreground=FG, bordercolor=EDGE,
                 lightcolor=PANEL_2, darkcolor=PANEL_2, borderwidth=1, padding=(px(16), px(8)))
    st.map("Secondary.TButton",
           background=[("disabled", FIELD), ("pressed", BTN_PRESS), ("active", SEL_BG)],
           foreground=[("disabled", DISABLED)], bordercolor=[("focus", GOLD)])
    st.configure("Ghost.TButton", background=BG, foreground=SUB, bordercolor=BG,
                 lightcolor=BG, darkcolor=BG, borderwidth=0, padding=(px(10), px(7)))
    st.map("Ghost.TButton", background=[("active", BG), ("pressed", BG)],
           foreground=[("active", FG), ("pressed", FG), ("disabled", DISABLED)])
    st.configure("Link.TButton", background=BG, foreground=GOLD, borderwidth=0,
                 focusthickness=0, padding=(px(2), px(1)))
    st.map("Link.TButton", background=[("active", BG)], foreground=[("active", GOLD_LT),
                                                                    ("disabled", DISABLED)])
    st.configure("Danger.TButton", background=BG, foreground=DANGER, bordercolor=EDGE,
                 lightcolor=BG, darkcolor=BG, borderwidth=1, padding=(px(14), px(7)))
    st.map("Danger.TButton",
           background=[("active", DANGER_FILL), ("pressed", DANGER_FILL), ("disabled", FIELD)],
           foreground=[("active", WHITE), ("pressed", WHITE), ("disabled", DISABLED)],
           bordercolor=[("active", DANGER_FILL), ("disabled", EDGE_SOFT)])
    # 紧凑版（方案库详情里按钮多，不能每个都占一行 40px）
    st.configure("SmallPrimary.TButton", background=GOLD, foreground=INK, bordercolor=GOLD,
                 lightcolor=GOLD, darkcolor=GOLD, borderwidth=0, relief="flat",
                 font=(FONT_NAME, 10, "bold"), padding=(px(10), px(6)))
    st.map("SmallPrimary.TButton",
           background=[("disabled", FIELD), ("pressed", GOLD_LT), ("active", GOLD_LT)],
           foreground=[("disabled", DISABLED)], bordercolor=[("disabled", FIELD)])
    st.configure("SmallSecondary.TButton", background=PANEL, foreground=FG, bordercolor=EDGE,
                 lightcolor=PANEL, darkcolor=PANEL, borderwidth=1,
                 font=(FONT_NAME, 10), padding=(px(10), px(5)))
    st.map("SmallSecondary.TButton",
           background=[("disabled", FIELD), ("active", BTN_HOVER), ("pressed", BTN_PRESS)],
           foreground=[("disabled", DISABLED)], bordercolor=[("focus", GOLD)])
    st.configure("SmallGhost.TButton", background=BG, foreground=SUB, bordercolor=BG,
                 lightcolor=BG, darkcolor=BG, borderwidth=0,
                 font=(FONT_NAME, 10), padding=(px(8), px(5)))
    st.map("SmallGhost.TButton", background=[("active", BG), ("pressed", BG)],
           foreground=[("active", FG), ("pressed", FG), ("disabled", DISABLED)])
    st.configure("SmallDanger.TButton", background=BG, foreground=DANGER, bordercolor=EDGE_SOFT,
                 lightcolor=BG, darkcolor=BG, borderwidth=1,
                 font=(FONT_NAME, 10), padding=(px(10), px(5)))
    st.map("SmallDanger.TButton",
           background=[("active", DANGER_FILL), ("pressed", DANGER_FILL), ("disabled", FIELD)],
           foreground=[("active", WHITE), ("pressed", WHITE), ("disabled", DISABLED)])

    # ── 输入类 ──
    st.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG,
                 bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE, padding=(px(8), px(5)))
    st.map("TEntry", bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)],
           darkcolor=[("focus", GOLD)])
    st.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                 arrowcolor=GOLD, bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE,
                 padding=(px(8), px(4)))
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
           bordercolor=[("focus", GOLD)], arrowcolor=[("active", GOLD_LT)])
    st.configure("TScrollbar", background=PANEL, troughcolor=BG, bordercolor=BG,
                 arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL, width=px(11))
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        st.configure(sb, background=PANEL, troughcolor=BG, bordercolor=BG, arrowsize=px(7),
                     arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL)
        st.map(sb, background=[("active", SEL_BG)], arrowcolor=[("active", GOLD_LT)])

    # ── 勾选 / 单选 ──
    # clam 的勾选框指示器不吃 indicatorcolor：它的元素选项是 indicatorbackground /
    # indicatorforeground（勾是用前景色画上去的），边框另有 upper/lowerbordercolor。
    for cls in ("TCheckbutton", "TRadiobutton"):
        st.configure(cls, background=BG, foreground=FG,
                     indicatorbackground=FIELD, indicatorforeground=GOLD,
                     upperbordercolor=EDGE, lowerbordercolor=EDGE,
                     indicatormargin=(0, px(2), px(8), px(2)), focuscolor=BG,
                     padding=(0, px(2)))
        st.map(cls, background=[("active", BG)], foreground=[("disabled", DISABLED)],
               indicatorbackground=[("selected", GOLD_DIM), ("active", "selected", GOLD_LT)],
               indicatorforeground=[("selected", INK), ("disabled", DISABLED)])
    st.configure("Muted.TCheckbutton", background=BG, foreground=MUTED,
                 indicatorbackground=FIELD, indicatorforeground=MUTED,
                 upperbordercolor=EDGE_SOFT, lowerbordercolor=EDGE_SOFT,
                 indicatormargin=(0, px(2), px(8), px(2)), focuscolor=BG)
    st.configure("Title.TCheckbutton", background=BG, foreground=FG, font=FONT_H2,
                 indicatorbackground=FIELD, indicatorforeground=GOLD,
                 upperbordercolor=EDGE, lowerbordercolor=EDGE,
                 indicatormargin=(0, px(2), px(10), px(2)), focuscolor=BG)
    st.map("Title.TCheckbutton", foreground=[("disabled", DISABLED)],
           indicatorbackground=[("selected", GOLD), ("active", "selected", GOLD_LT)],
           indicatorforeground=[("selected", INK)])

    # ── 滑块：细槽 + 金色滑块 ──
    st.configure("TScale", background=GOLD, troughcolor=FIELD, bordercolor=EDGE,
                 lightcolor=GOLD_DIM, darkcolor=GOLD_DIM, focuscolor=BG,
                 sliderlength=px(14), sliderthickness=px(14))
    st.map("TScale", background=[("active", GOLD_LT)],
           lightcolor=[("active", GOLD_LT)], darkcolor=[("active", GOLD_LT)])

    # ── 页签：界面自己画导航条，Notebook 只当内容容器（把 tab 头整个藏掉）──
    st.configure("TNotebook", background=BG, bordercolor=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    st.configure("TNotebook.Tab", background=BG, foreground=SUB, padding=(px(16), px(8)))
    st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", GOLD)])

    # ── 列表 / 表格 ──
    st.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG,
                 bordercolor=EDGE, borderwidth=0, rowheight=px(32))
    st.configure("Treeview.Heading", background=HEAD_BG, foreground=GOLD,
                 relief="flat", font=(FONT_NAME, 10, "bold"), padding=(px(8), px(6)))
    st.map("Treeview.Heading", background=[("active", BTN_HOVER)])
    st.map("Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    # 方案库的列表：两行式行（第一行名字、第二行小字摘要），行高要够
    st.configure("Lib.Treeview", background=BG, fieldbackground=BG, foreground=FG,
                 borderwidth=0, rowheight=px(54))
    st.map("Lib.Treeview", background=[("selected", SEL_BG)], foreground=[("selected", WHITE)])
    st.configure("TSeparator", background=EDGE_SOFT)

    # 标签筹码（详情面板里的小方块）
    st.configure("Chip.TLabel", background=PANEL_2, foreground=GOLD_LT, font=FONT_MICRO,
                 padding=(px(8), px(3)), borderwidth=1, relief="solid", bordercolor=EDGE)
    st.configure("ChipHot.TLabel", background=SEL_BG, foreground=GOLD_LT, font=FONT_MICRO,
                 padding=(px(8), px(3)), borderwidth=1, relief="solid", bordercolor=GOLD)
    # 兼容旧用法：LabelFrame（敌人预设子窗还在用）
    st.configure("TLabelframe", background=BG, bordercolor=EDGE, relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=BG, foreground=GOLD, font=FONT_H3)
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass
    return st


# ══════════════════════════════════════════════════════════════════════
#  视觉积木：卡片 / 筹码 / 缩图 / 页面抬头（tk 控件，颜色直接给）
# ══════════════════════════════════════════════════════════════════════

def _deco_scaled(name, target):
    """取装饰图并缩到 ≈target 设计像素（PhotoImage 是物理像素，px() 会乘屏幕缩放）。

    返回的 PhotoImage 必须由调用方留引用，否则 Tk 会回收（这是老坑）。"""
    img = deco_image(name)
    if not img:
        return None
    try:
        want = max(1.0, float(target) * S)
        f = max(1, int(round(img.width() / want)))
        if f > 1:
            img = img.subsample(f, f)
    except Exception:
        pass
    return img


def _chip(parent, text, fg=SUB, bg=None, border=EDGE, font=None):
    """一枚小筹码：细描边 + 小字。用它替掉满屏的方括号说明。"""
    bg = bg if bg is not None else PANEL_2
    try:
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=font or FONT_MICRO,
                        padx=px(9), pady=px(3), bd=0, highlightthickness=1,
                        highlightbackground=border, highlightcolor=border)
    except tk.TclError:
        return tk.Label(parent, text=text)


def _card(parent, eyebrow="", title="", desc="", pad=px(16)):
    """一张卡片：1px 描边 + 标题区（眉标 / 标题 / 说明 / 细线）+ 内容区。

    返回 `(外壳, 内容区)`。外壳用来 pack/grid/隐藏；内容区往里面塞控件。
    底色跟窗口一致（只靠描边分组），这样卡片里**原有那批 ttk 控件不用逐个改底色**。"""
    outer = tk.Frame(parent, bg=EDGE)
    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if eyebrow or title or desc:
        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x", padx=pad, pady=(px(10), 0))
        tk.Frame(head, bg=GOLD_DIM, width=px(3)).pack(side="left", fill="y", padx=(0, px(12)))
        col = tk.Frame(head, bg=BG)
        col.pack(side="left", fill="x", expand=True)
        if eyebrow:
            tk.Label(col, text=eyebrow, bg=BG, fg=GOLD, font=FONT_MICRO).pack(anchor="w")
        if title:
            tk.Label(col, text=title, bg=BG, fg=FG, font=FONT_H2).pack(anchor="w", pady=(px(2), 0))
        if desc:
            tk.Label(col, text=desc, bg=BG, fg=SUB, font=FONT_SMALL, justify="left",
                     wraplength=px(960)).pack(anchor="w", pady=(px(5), 0))
        tk.Frame(inner, bg=EDGE_SOFT, height=1).pack(fill="x", padx=pad, pady=(px(8), 0))
        body = tk.Frame(inner, bg=BG)
        body.pack(fill="both", expand=True, padx=pad, pady=(px(8), px(11)))
    else:
        body = tk.Frame(inner, bg=BG)
        body.pack(fill="both", expand=True, padx=pad, pady=px(14))
    outer.card_body = body
    return outer, body


def _page_head(parent, eyebrow, title, desc, right=None):
    """页面抬头（参考实现没有大标题区，这里压成一行：眉标 + 标题 + 一句说明 + 细线）。"""
    head = tk.Frame(parent, bg=BG)
    head.pack(fill="x", pady=(px(2), px(9)))
    row = tk.Frame(head, bg=BG)
    row.pack(fill="x")
    tk.Label(row, text=eyebrow, bg=BG, fg=GOLD, font=FONT_MICRO).pack(side="left",
                                                                    padx=(0, px(10)))
    tk.Label(row, text=title, bg=BG, fg=FG, font=FONT_H2).pack(side="left")
    tk.Label(row, text=desc, bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left",
                                                                  padx=(px(12), 0),
                                                                  pady=(px(4), 0))
    tk.Frame(head, bg=EDGE_SOFT, height=1).pack(fill="x", pady=(px(6), 0))
    return head


class Switch(tk.Canvas):
    """一个像样的开关（ttk 的 checkbox 在 clam 下太小、太像表单）。

    用法与 BooleanVar 绑：`Switch(parent, var, command=...)`。支持 `configure(state=...)`
    与 `config(state=...)`，这样它跟 ttk.Checkbutton 可以互换着放进 `enemy_sub`。"""

    def __init__(self, parent, variable, command=None, bg=BG, enabled=True):
        self._sw_w = px(44)
        self._sw_h = px(24)
        super().__init__(parent, width=self._sw_w, height=self._sw_h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var = variable
        self.command = command
        self._enabled = enabled
        self.var.trace_add("write", lambda *_a: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.redraw())
        self.redraw()

    def _rr(self, x0, y0, x1, y1, fill):
        r = (y1 - y0) / 2.0
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=fill, outline="")
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=fill, outline="")
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")

    def redraw(self):
        try:
            self.delete("all")
            w, h = self._sw_w, self._sw_h
            on = bool(self.var.get())
            track = GOLD if on else PANEL_2
            edge = GOLD if on else EDGE
            self._rr(1, 1, w - 1, h - 1, track)
            if not on:
                self.create_line(1 + h / 2, 1, w - 1 - h / 2, 1, fill=edge)
                self.create_line(1 + h / 2, h - 1, w - 1 - h / 2, h - 1, fill=edge)
            d = h - px(6)
            x = (w - d - px(3)) if on else px(3)
            self.create_oval(x, px(3), x + d, px(3) + d,
                             fill=INK if on else SUB, outline="")
            if not self._enabled:
                self.create_rectangle(0, 0, w, h, fill=BG, outline="", stipple="gray50")
        except tk.TclError:
            pass

    def _click(self, _e=None):
        if not self._enabled:
            return
        self.var.set(not bool(self.var.get()))
        if callable(self.command):
            self.command()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            try:
                super().configure(cursor="hand2" if self._enabled else "arrow")
            except tk.TclError:
                pass
            self.redraw()
        return super().configure(cnf, **kw)

    config = configure


class NavBook(ttk.Frame):
    """ttk.Notebook 的替身：只保留这个界面用到的 API（add / select / tabs / tab / bind）。

    为什么不用真的 Notebook：clam 会把 tab 头画成方块、金色下划线改不了。
    这里用普通 Frame + 自己画的导航条，内容页由 pack/pack_forget 切换。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._pages, self._titles = [], {}
        self._current = None
        self._cb = None

    def add(self, child, text="", **_kw):
        self._pages.append(child)
        self._titles[str(child)] = text
        if self._current is None:
            self.select(child)

    def tabs(self):
        return tuple(str(p) for p in self._pages)

    def tab(self, which, option=None):
        p = self._resolve(which)
        if option in (None, "text"):
            return self._titles.get(str(p), "")
        return ""

    def select(self, which=None):
        if which is None:
            return str(self._current) if self._current is not None else ""
        p = self._resolve(which)
        if p is None:
            return ""
        for x in self._pages:
            if x is p:
                x.pack(fill="both", expand=True)
            else:
                x.pack_forget()
        changed = p is not self._current
        self._current = p
        if changed and callable(self._cb):
            try:
                self._cb()
            except Exception:
                pass
        return str(p)

    def _resolve(self, which):
        if isinstance(which, str):
            for p in self._pages:
                if str(p) == which:
                    return p
            return None
        if isinstance(which, int):
            return self._pages[which] if 0 <= which < len(self._pages) else None
        return which

    def bind(self, seq, func=None, add=None):
        if seq == "<<NotebookTabChanged>>" and func is not None:
            self._cb = func
            return None
        return super().bind(seq, func, add)


class GoldCheck(tk.Frame):
    """自绘勾选行：金色小方框 + 文案（ttk 在 clam 下的指示器太小、太像表单）。

    接口对齐 ttk.Checkbutton 的常用子集：text / variable / command / state / width。"""

    def __init__(self, parent, text="", variable=None, command=None, bg=BG,
                 state="normal", width=None, font=None, fg=None):
        super().__init__(parent, bg=bg)
        self.var = variable if variable is not None else tk.BooleanVar(value=False)
        self.command = command
        self._enabled = state != "disabled"
        self._bg = bg
        self._fg = fg or FG
        self._size = max(14, int(round(17 * S)))
        self.cv = tk.Canvas(self, width=self._size, height=self._size, bg=bg,
                            highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(side="left", pady=px(2))
        self.lbl = tk.Label(self, text=text, bg=bg, fg=self._fg, anchor="w",
                            font=font or FONT_UI, cursor="hand2", padx=px(8))
        if width:
            self.lbl.configure(width=width)
        self.lbl.pack(side="left")
        for w in (self.cv, self.lbl):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)
        try:
            self.var.trace_add("write", lambda *_a: self.draw())
        except Exception:
            pass
        self.draw()

    def _click(self, _e=None):
        if not self._enabled:
            return
        self.var.set(not bool(self.var.get()))
        if callable(self.command):
            self.command()

    def _hover_on(self, _e=None):
        if self._enabled:
            self.lbl.configure(fg=GOLD_LT)

    def _hover_off(self, _e=None):
        if self._enabled:
            self.lbl.configure(fg=self._fg)

    def invoke(self):
        """等价于点一下（自动化测试/脚本会用到，和 ttk.Checkbutton 同名）。"""
        self._click()
        return bool(self.var.get())

    def select(self):
        self.var.set(True)

    def deselect(self):
        self.var.set(False)

    def draw(self):
        try:
            self.cv.delete("all")
            s = self._size
            on = bool(self.var.get())
            if not self._enabled:
                border = EDGE_SOFT
                fill = PANEL_2 if on else FIELD
                mark = DISABLED
                self.lbl.configure(fg=MUTED, cursor="arrow")
            else:
                border, fill = (GOLD, GOLD) if on else (EDGE, FIELD)
                mark = INK if on else GOLD
                self.lbl.configure(fg=self._fg, cursor="hand2")
            self.cv.create_rectangle(0, 0, s - 1, s - 1, outline=border, fill=fill)
            if on:
                pad = max(2, int(round(s * 0.22)))
                wdt = max(1, int(round(px(2))))
                self.cv.create_line(pad, s * 0.52, s * 0.42, s - pad,
                                    fill=mark, width=wdt, capstyle="round")
                self.cv.create_line(s * 0.42, s - pad, s - pad, pad + px(1),
                                    fill=mark, width=wdt, capstyle="round")
        except tk.TclError:
            pass

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            self.draw()
        return super().configure(cnf, **kw)

    config = configure


class App:
    def __init__(self, root):
        self.root = root
        setup_display(root)               # 必须在几何尺寸与建控件之前
        root.title("法魂职业道具和装备随机器")
        # 高 DPI 下 px(820) 可能比屏幕还高（150% 时 1230 > 1080），底栏会被系统任务栏盖住。
        # 这里按屏幕再夹一次：窗口最多占屏幕 92%，保证底部种子/按钮永远看得见。
        _w = min(px(1180), int(root.winfo_screenwidth() * 0.94))
        _h = min(px(820), int(root.winfo_screenheight() * 0.90))
        root.geometry(f"{_w}x{_h}")
        root.minsize(min(px(1020), _w), min(px(680), _h))
        self.engine = None
        self.plan = None
        self.pools = None
        self.items = None
        self.cfg = None
        self.q = queue.Queue()
        self._deploying = False          # 写入串行化：上次没跑完不许再点
        self._lib_writing = False        # 从方案库写入中（进度要回显到方案库窗口）
        # 参考实现的「页签启用勾」：关掉整块功能，页签标题变灰；物品关掉后
        # 底部的「开始随机…」也不可用（另一类的勾还在时仍可用）。
        self.item_on = tk.BooleanVar(value=True)
        self.ev1_on = tk.BooleanVar(value=True)
        # 2026-10-23：默认**每次开始随机都重掷种子**。以前默认关，种子一直是
        # 20261010 —— 玩家会以为"随机器每次都出同一套 / 根本没随机"
        # （作者实测反馈）。想复现某一套就取消勾、把种子填回去。
        self.reroll_seed = tk.BooleanVar(value=True)
        self.seed = tk.StringVar(value="20261010")
        self._ev1_widgets = []
        self.ev1_preset = None          # 逐类预设（None = 内置规则）
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
        """外壳：顶栏 / 自绘导航 / 内容页签 / 底部动作栏。

        页签头由 `apply_theme` 里的 TNotebook layout 藏掉了 —— 导航条是我们自己画的，
        这样选中态能做成「金色下划线」，比 clam 的默认 tab 干净得多。"""
        # ── 顶栏（参考实现是菜单条；这里压成一行：图标 + 标题 + 环境状态）──
        self.head = tk.Frame(self.root, bg=BG_ELEV)
        self.head.pack(fill="x")
        hrow = tk.Frame(self.head, bg=BG_ELEV)
        hrow.pack(fill="x", padx=px(26), pady=(px(9), px(8)))
        ic = _deco_scaled("icon", 30)
        if ic:
            self._deco_head = ic                     # 留引用，不然 Tk 回收
            tk.Label(hrow, image=ic, bg=BG_ELEV).pack(side="left", padx=(0, px(12)))
        hcol = tk.Frame(hrow, bg=BG_ELEV)
        hcol.pack(side="left", fill="x", expand=True)
        tk.Label(hcol, text="C O N V E R G E N C E   ·   R A N D O M I Z E R",
                 bg=BG_ELEV, fg=GOLD, font=FONT_MICRO).pack(anchor="w")
        trow = tk.Frame(hcol, bg=BG_ELEV)
        trow.pack(anchor="w")
        tk.Label(trow, text="法魂随机器", bg=BG_ELEV, fg=FG,
                 font=FONT_H2).pack(side="left")
        tk.Label(trow, text="物品与敌人随机 · 每一步都能还原", bg=BG_ELEV, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(px(12), 0), pady=(px(5), 0))
        chips = tk.Frame(hrow, bg=BG_ELEV)
        chips.pack(side="right", anchor="e")
        self.head_chip_engine = _chip(chips, "引擎 待载入", fg=SUB, bg=BG_ELEV)
        self.head_chip_engine.pack(side="right", padx=(px(8), 0))
        self.head_chip_mod = _chip(chips, "MOD 检测中", fg=SUB, bg=BG_ELEV)
        self.head_chip_mod.pack(side="right")
        tk.Frame(self.head, bg=EDGE, height=1).pack(fill="x")

        # ── 内容页签（NavBook：tab 头藏掉，导航条自己画）──
        self.nb = NavBook(self.root)
        self.page_set = ttk.Frame(self.nb)
        self.page_enemy = ttk.Frame(self.nb)
        self.page_lib = ttk.Frame(self.nb)
        self._deco_tabs = []
        # 参考实现的页签头里带一个启用勾：勾掉 = 整块功能关闭，标题变灰。
        # 我们的「方案库」不是随机功能，所以没有勾。
        _specs = ((self.page_set, "职业物品随机", self.item_on, self._refresh_item_on),
                  (self.page_enemy, "敌人随机", self.ev1_on, self._refresh_ev1_on),
                  (self.page_lib, "方案库", None, None))
        for page, label, _var, _cmd in _specs:
            self.nb.add(page, text=label)

        # ── 自绘导航 ──
        self.nav = tk.Frame(self.root, bg=BG)
        self.nav.pack(fill="x", padx=px(26), pady=(px(2), 0))
        self._nav_items = []
        for page, label, var, cmd in _specs:
            holder = tk.Frame(self.nav, bg=BG)
            holder.pack(side="left", padx=(0, px(26)))
            line = tk.Frame(holder, bg=BG, height=px(2))
            line.pack(side="bottom", fill="x")
            row = tk.Frame(holder, bg=BG)
            row.pack(side="bottom")
            check = None
            if var is not None:
                check = GoldCheck(row, text="", variable=var, command=cmd,
                                  bg=BG, state="normal")
                check.pack(side="left", padx=(0, px(2)))
            lbl = tk.Label(row, text=label, bg=BG, fg=SUB,
                           font=FONT_H3, padx=px(2), pady=px(8), bd=0, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, p=page: self.nb.select(p))
            lbl.bind("<Enter>", lambda _e, h=holder: self._nav_hover(h, True))
            lbl.bind("<Leave>", lambda _e, h=holder: self._nav_hover(h, False))
            self._nav_items.append({"page": page, "holder": holder, "label": lbl,
                                    "line": line, "var": var, "check": check})
        tk.Frame(self.root, bg=EDGE_SOFT, height=1).pack(fill="x", padx=px(26))

        # ── 三页内容（每页内容限宽居中，宽屏上不会拉成一整条）──
        self._build_settings(self._scrollable(self.page_set, maxw=px(1060),
                                              pad=(px(26), px(18), px(18), px(24))))
        self._build_enemy_page(self._scrollable(self.page_enemy, maxw=px(1060),
                                                pad=(px(26), px(18), px(18), px(24))))
        self._build_library(self.page_lib)

        # ── 底部动作栏（照参考实现：种子与主按钮固定在底部，内容区吃剩下的空间）──
        self.footer = tk.Frame(self.root, bg=BG_ELEV)
        self.footer.pack(side="bottom", fill="x")
        tk.Frame(self.footer, bg=EDGE, height=1).pack(side="top", fill="x")
        self.outer_what = ttk.Label(self.footer, text="", style="Footer.TLabel",
                                    wraplength=px(1000), justify="left")
        self.outer_what.pack(fill="x", padx=px(26), pady=(px(8), px(0)))
        # 种子行：参考实现把 Seed + Reroll seed 放在 Randomize 旁边
        srow = tk.Frame(self.footer, bg=BG_ELEV)
        srow.pack(fill="x", padx=px(26), pady=(px(7), px(0)))
        self.footer_seedrow = srow
        tk.Label(srow, text="种子", bg=BG_ELEV, fg=SUB, font=FONT_SMALL).pack(side="left",
                                                                             padx=(0, px(8)))
        self.seed_e = ttk.Entry(srow, textvariable=self.seed, width=18)
        self.seed_e.pack(side="left")
        ttk.Button(srow, text="换一个", style="Ghost.TButton",
                   command=self._dice).pack(side="left", padx=px(8))
        GoldCheck(srow, text="每次开始随机都换种子", variable=self.reroll_seed,
                  bg=BG_ELEV).pack(side="left", padx=(px(4), 0))
        tk.Label(srow, text="勾着 = 每次都是新世界；取消勾 = 同种子复现同一套",
                 bg=BG_ELEV, fg=MUTED, font=FONT_MICRO).pack(side="right")
        bar = tk.Frame(self.footer, bg=BG_ELEV)
        bar.pack(fill="x", padx=px(26), pady=(px(7), px(2)))
        self.footer_bar = bar
        # 唯一入口：文案随勾选的随机类型变（物品 / 敌人 / 物品和敌人）
        self.b_start = ttk.Button(bar, text="开始随机", style="Primary.TButton",
                                  command=self.start_randomize, width=22)
        self.b_start.pack(side="left")
        self.start_hint = ttk.Label(bar, text="", style="Footer.TLabel")
        self.start_hint.pack(side="left", padx=(px(12), 0))
        self.b_rollback = ttk.Button(bar, text="还原成原始", style="Ghost.TButton",
                                     command=self.rollback)
        self.b_rollback.pack(side="left", padx=(px(14), 0))
        self.b_lib = ttk.Button(bar, text="打开方案库", style="Ghost.TButton",
                                command=self._goto_library)
        self.b_lib.pack(side="right")
        self.status = tk.StringVar(value="勾选要随机的类型，然后点左侧的金色按钮")
        self.lbl_status = ttk.Label(self.footer, textvariable=self.status, style="Footer.TLabel")
        self.lbl_status.pack(fill="x", padx=px(26), pady=(px(7), px(9)))

        self.nb.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._sync_nav()
        self._sync_footer()
        self._refresh_item_on()
        self._refresh_ev1_on()
        self._refresh_start_action()

    def _sync_nav(self):
        """把导航条同步成当前页（金色下划线 + 主文字）。"""
        try:
            cur = str(self.nb.select())
        except Exception:
            return
        for it in getattr(self, "_nav_items", []):
            on = str(it["page"]) == cur
            _var = it.get("var")
            enabled = _var is None or bool(_var.get())
            try:
                it["label"].config(fg=(FG if on else SUB) if enabled else MUTED)
                it["line"].config(bg=(GOLD if on else BG) if enabled else EDGE_SOFT)
            except tk.TclError:
                pass

    def _nav_hover(self, holder, inside):
        try:
            cur = str(self.nb.select())
        except Exception:
            cur = ""
        for it in getattr(self, "_nav_items", []):
            if it["holder"] is holder and str(it["page"]) != cur:
                _var = it.get("var")
                if _var is not None and not bool(_var.get()):
                    continue
                it["label"].config(fg=FG if inside else SUB)

    def _scrollable(self, parent, maxw=None, pad=(px(4), px(2), px(12), px(16))):
        """给一页加竖向滚动，返回放内容的 frame（宽度受限、居中）。

        为什么需要：把「更多设置」和「详细记录」都展开时，内容比窗口高 —— 不滚动的话
        Tk 会把最后几块**压扁**（实测只剩 1 像素高），看着就是坏的。"""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0,
                           yscrollincrement=px(24))
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        holder = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        content = tk.Frame(holder, bg=BG)
        content.pack(fill="x", padx=pad[0], pady=(pad[1], pad[3]))
        content._scroll_canvas = canvas      # 调用方可据此把滚动条复位（切换面板时用）
        holder.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _resize(e):
            w = min(e.width, maxw) if maxw else e.width
            canvas.itemconfigure(win, width=max(1, w))
            canvas.coords(win, max(0, (e.width - w) // 2), 0)

        canvas.bind("<Configure>", _resize)

        def wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # 只在鼠标进这一页时接管滚轮，走了就还回去（否则会影响另一页的列表）
        outer.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        outer.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return content

    # ── 页 1 · 随机设置 ──
    def _build_settings(self, body):
        _page_head(body, "ITEM RANDOMIZER", "随机设置",
                   "选好随机项目与合理度，点窗口底部的「开始随机」—— 生成与写入一次完成；随时可以还原。")

        # 第一行两列：左「随机项目」、右「这次会改什么」——参考实现的分组框密度
        _top = tk.Frame(body, bg=BG)
        _top.pack(fill="x", pady=(0, px(12)))
        _col_l = tk.Frame(_top, bg=BG)
        _col_l.pack(side="left", fill="both", expand=True, padx=(0, px(7)))
        _col_r = tk.Frame(_top, bg=BG)
        _col_r.pack(side="left", fill="both", expand=True, padx=(px(7), 0))

        # ── 第 1 步 ──
        s1, b1 = _card(_col_l, "第 1 步", "随机项目",
                       "只换职业说明书里出现过的物品；格子的位置、数量与解锁条件一律不动。")
        s1.pack(fill="x")
        self.basis = tk.StringVar(value="guide")     # 固定：只动职业说明书里的物品
        r2 = tk.Frame(b1, bg=BG); r2.pack(fill="x")
        tk.Label(r2, text="随机项目", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left", padx=(0, px(18)))
        self.doms = {}
        for v, t in ITEMS:
            self.doms[v] = tk.BooleanVar(value=True)
            GoldCheck(r2, text=t, variable=self.doms[v],
                      command=lambda k=v: self._toggle_dom(k)).pack(side="left", padx=(0, px(18)))
        r3 = tk.Frame(b1, bg=BG); r3.pack(fill="x", pady=(px(12), 0))
        tk.Label(r3, text="混合方式", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left", padx=(0, px(18)))
        self.mode = tk.StringVar(value=MODES[0][1])
        self.cb_mode = ttk.Combobox(r3, textvariable=self.mode, values=[t for _m, t in MODES],
                                    state="readonly", width=40)
        self.cb_mode.pack(side="left")
        # 换混合方式必须把"改动比例 / 单独设合理度"两组一起理顺 ——
        # 之前这里只调了 _combo_hint()，所以用户在下拉里换完方式，那两组纹丝不动（真 bug，2026-10-14 修）
        self.cb_mode.bind("<<ComboboxSelected>>",
                          lambda _e: (self._combo_hint(), self._refresh_rates(), self._refresh_cohs()))
        self.lbl_combo = ttk.Label(b1, text="", style="Hint.TLabel")
        self.lbl_combo.pack(anchor="w", pady=(px(8), 0))

        # ── 结果（人话，放在右列）──
        s5, b5 = _card(_col_r, "结果", "这次会改什么",
                       "生成之后，这里会把「改了哪些格子、分别变成了什么」摊成人话。")
        s5.pack(fill="x")
        self.summary = tk.StringVar(value="还没生成。点底部的「开始随机…」看看会怎么改。")
        ttk.Label(b5, textvariable=self.summary, style="Body.TLabel",
                  justify="left", wraplength=px(430)).pack(anchor="w")
        # 「小提示」三条删掉（2026-10-23）：和底栏、按钮旁注说的是同一件事，
        # 常显三行只会把「结果」这块最该被读的区域挤小。

        # ── 第 2 步 ──
        s2, b2 = _card(body, "第 2 步", "合理度",
                       "一个滑块同时管三件事：最远跨几档、多少东西真的跨、武器掺进混池的比例。")
        s2.pack(fill="x", pady=(0, px(12)))
        r3 = tk.Frame(b2, bg=BG); r3.pack(fill="x")
        self.coherence = tk.DoubleVar(value=0.8)
        # 存下 Scale 本体：没有混池时它要**置灰**（那时每个池子用自己那条）
        self.scale_coh = ttk.Scale(r3, from_=0.0, to=1.0, variable=self.coherence,
                                   orient="horizontal", length=px(560),
                                   command=lambda v: (self.lbl_coh.config(text=f"{float(v)*100:.0f}%"),
                                                      self._refresh_cohs()))
        self.scale_coh.pack(side="left", fill="x", expand=True, padx=(0, px(14)))
        self.lbl_coh = ttk.Label(r3, text="80%", style="Num.TLabel", width=5, anchor="e")
        self.lbl_coh.pack(side="right")
        r4 = tk.Frame(b2, bg=BG); r4.pack(fill="x", pady=(px(6), 0))
        tk.Label(r4, text="0%   等级完全放开", bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left")
        tk.Label(r4, text="100%   同等级互换", bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="right")
        self.lbl_cohtxt = ttk.Label(b2, text="", style="Gold.TLabel")
        self.lbl_cohtxt.pack(anchor="w", pady=(px(4), 0))

        # ── 单独成池的那几条合理度（2026-10-14 作者定的表单规则）──
        #    没有总开关、也没有「混池」那条：
        #      · 有混池 → 上面那条**总合理度**管混池（它保持可用）
        #      · 没有混池（各自随机）→ 总合理度**置灰**，下面每个"自己成池"的类别各有一条
        #      · 全部混合 → 只剩总合理度（三个类别都进了混池，下面一条都不摆）
        #    摆哪几条见 _coh_applicable()。
        self.lbl_cohrows = ttk.Label(b2, text="", style="Hint.TLabel")
        self.lbl_cohrows.pack(anchor="w", pady=(px(8), px(2)))
        cgrid = tk.Frame(b2, bg=BG); cgrid.pack(fill="x")
        self.coh_rows = {}
        for i, (key, text) in enumerate((("rune", "卢恩"), ("armor", "护甲"),
                                         ("weapon", "装备（武器）"))):
            self._mk_override_row(cgrid, self.coh_rows, key, text, 0.0, 1.0, i)
        self._refresh_cohs()

        # ── 环境（2026-10-23 压成一行）：诊断信息属于"出问题时才看"，
        #    平时不该占一张卡；逐项清单收进「详情」。 ──
        s4, b4 = _card(body, "环境", "本地文件",
                       "缺项会禁用「写入游戏」。")
        s4.pack(fill="x", pady=(0, px(12)))
        _er = tk.Frame(b4, bg=BG); _er.pack(fill="x")
        self.lbl_env = ttk.Label(_er, text="检测中…", style="Muted.TLabel")
        self.lbl_env.pack(side="left")
        ttk.Button(_er, text="重新检测", style="Ghost.TButton",
                   command=self.refresh_env).pack(side="left", padx=(px(14), 0))
        ttk.Button(_er, text="指定 MOD 目录…", style="Ghost.TButton",
                   command=self.pick_mod).pack(side="left", padx=px(6))
        ttk.Button(_er, text="补一份原始备份", style="Ghost.TButton",
                   command=self.make_backup).pack(side="left", padx=px(6))
        self.b_env_more = ttk.Button(_er, text="逐项详情 ▸", style="Ghost.TButton",
                                     command=self._toggle_env)
        self.b_env_more.pack(side="right")
        self.env_box = tk.Frame(b4, bg=BG)

        # ── 折叠开关 ──
        bar = tk.Frame(body, bg=BG); bar.pack(fill="x", pady=(px(2), px(12)))
        ttk.Button(bar, text="更多设置", style="Ghost.TButton",
                   command=self._toggle_adv).pack(side="left")
        ttk.Label(bar, text="生成 / 写入 / 还原 在这一页底部；敌人与方案库的动作在各自页里",
                  style="Muted.TLabel").pack(side="left", padx=px(12))

        # ── 更多设置（默认折叠）──
        #    注意：这两个开关都要**立刻**带动下面「改动比例」那一组（2026-10-14 作者报过
        #    "开了/关了下面的比例不跟着变" —— 商店那个当时根本没接刷新）。
        self.adv, ab = _card(body, "进阶", "更多设置",
                             "影响商店、法祷护甲与说明书；不确定就保持默认。")
        a1 = tk.Frame(ab, bg=BG); a1.pack(fill="x")
        self.sets = tk.BooleanVar(value=True)
        self.guide = tk.BooleanVar(value=True)
        self.cb_sets = GoldCheck(a1, text="法祷护甲整套一起换", variable=self.sets,
                                 command=self._refresh_rates)
        self.cb_sets.pack(side="left")
        # 「幽影卢恩与普通卢恩一起换」这个开关 2026-10-14 撤掉了：
        # 实测它改不了任何结果 —— 档位系统里 大师=幽影 都是 3 档（规格 §2 / Q3 定下的），
        # 按档位分桶时两者必然并到一起。留着只会让人以为"某个开关没生效"。
        GoldCheck(a1, text="说明书跟着一起改", variable=self.guide).pack(side="left", padx=px(18))
        a2b = tk.Frame(ab, bg=BG); a2b.pack(fill="x", pady=(px(10), 0))
        self.shops = tk.BooleanVar(value=False)      # 默认关：老玩法完全不受影响
        self.cb_shops = GoldCheck(a2b, text="商店里的职业装备也一起换", variable=self.shops,
                                  command=self._refresh_rates)
        self.cb_shops.pack(side="left")
        ttk.Label(a2b, text="只影响说明书里的装备；价格 / 限量 / 解锁条件都不动",
                  style="Muted.TLabel").pack(side="left", padx=px(12))
        # ── 改动比例：两条，**在该出现时才出现**（没有总开关，与合理度那组一个风格）──
        #    · 法祷职业护甲 —— 整套与散件一起调（引擎里是 rate_sets + rate_caster 两个键）
        #    · 商店物品     —— **有商店在卖的那批物品**里，多少参与互换（rate_shop，按物品抽）
        #    不勾 = 这一类全改（100%）
        a2r = tk.Frame(ab, bg=BG); a2r.pack(fill="x", pady=(px(10), 0))
        tk.Label(a2r, text="改动比例", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left", padx=(0, px(12)))
        self.rate_hint = ttk.Label(a2r, text="不勾 = 这一类全改；商店开了就是在卖的职业装备全部参与",
                                   style="Muted.TLabel")
        self.rate_hint.pack(side="left", padx=px(6))
        # 用 grid（不用 pack）：隐藏/恢复的时候格子还在，**顺序不会乱**
        rgrid = tk.Frame(ab, bg=BG); rgrid.pack(fill="x")
        self.rate_rows = {}
        #    商店**没有**比例条（2026-10-14 作者决定）：勾了「商店里的职业装备也一起换」
        #    就等于"在卖的职业装备全部参与"（引擎侧 rate_shop 仍认，只是界面不再暴露）
        for i, (key, text) in enumerate((("caster", "法祷职业护甲"),)):
            self._mk_override_row(rgrid, self.rate_rows, key, text, 0.05, 1.0, i)
        self._refresh_rates()               # 一建出来就按当前勾选理顺一次

        a3 = tk.Frame(ab, bg=BG); a3.pack(fill="x", pady=(px(12), 0))
        for t, cmd in (("保存这套设置", self.save_cfg), ("读取设置", self.load_cfg),
                       ("导出方案表", self.export), ("打开输出文件夹", self.open_out)):
            ttk.Button(a3, text=t, style="Secondary.TButton",
                       command=cmd).pack(side="left", padx=(0, px(8)))

        # ── 详细记录（默认折叠）──
        self.detail, db = _card(body, "记录", "详细记录",
                                "生成后自动展开：左边是检查项，右边是逐条替换与运行日志。")
        d = tk.Frame(db, bg=BG); d.pack(fill="both", expand=True)
        left = tk.Frame(d, bg=BG); left.pack(side="left", fill="both", expand=False)
        ttk.Label(left, text="检查项", style="Sub.TLabel").pack(anchor="w", pady=(0, px(4)))
        self.checks = ttk.Treeview(left, columns=("k", "v"), show="headings", height=7)
        self.checks.heading("k", text="检查项"); self.checks.heading("v", text="结果")
        self.checks.column("k", width=px(250)); self.checks.column("v", width=px(90))
        self.checks.pack(fill="both", expand=True)
        right = tk.Frame(d, bg=BG); right.pack(side="left", fill="both", expand=True, padx=(px(12), 0))
        ttk.Label(right, text="把什么换成了什么（前 300 条）", style="Sub.TLabel").pack(
            anchor="w", pady=(0, px(4)))
        cols = ("old", "new", "where")
        self.tbl = ttk.Treeview(right, columns=cols, show="headings", height=7)
        for c, w, t in (("old", 150, "原来"), ("new", 150, "换成"), ("where", 330, "在哪里")):
            self.tbl.heading(c, text=t); self.tbl.column(c, width=px(w))
        self.tbl.pack(fill="both", expand=True)
        # tk.Text 不带 ttk，样式表管不到它 —— 颜色必须逐个传（否则是一块白）
        self.txt = tk.Text(db, height=6, wrap="word", bg=FIELD, fg=FG,
                           font=FONT_SMALL, padx=px(10), pady=px(8),
                           insertbackground=FG, selectbackground=SEL_BG, selectforeground=WHITE,
                           relief="flat", highlightthickness=px(1),
                           highlightbackground=EDGE, highlightcolor=GOLD)
        self.txt.pack(fill="both", expand=True, pady=(px(10), 0))

    # ── 页 2 · 敌人随机 ──
    def _build_enemy_page(self, body):
        """敌人随机页 —— 分组名与项目顺序照参考实现（thefifthmatt ER Randomizer）的原文。

        依据是它 MainWindow.axaml 里敌人页的控件清单（顺序即原文顺序）：
            游戏进程：缩放敌人血量 / 多阶段 Boss 仅轻微缩放
            杂项：改 Boss 名字 / 随机 Boss 背景音乐 / 换 Boss 时一并换卢恩 /
                  多 Boss 战之间互换（只对小地牢 Boss 生效）/ 夜之 Boss 全天出现
            敌人摆放：来源 / 忽略场地与体型限制 / Boss 只与同场地档互换 / 连外观一起换 /
                      不动打不死的 / 只换同一种敌人 / 独立种子 + 单独重掷 / 编辑敌人预设…
        我们**没做**的项目收进最后一张「规划中」卡片（灰着 + 标规划中），不假装有。
        """
        _page_head(body, "02  ·  ENEMY RANDOMIZER", "敌人随机",
                   "把每种敌人的整行数据（血量 / AI / 掉落）在同一类别池里互相置换；"
                   "打开后与物品随机可以同时生效。")

        # ── 敌人随机 v1（新管线，2026-10-21 M5）──
        # 参考实现是「左分组框 + 右说明/操作」的两列；旧管线（下面那个折叠块）仍在，
        # 但 v1 是现在部署用的：规则矩阵 + 位置对齐 + 方案层。
        _erow = tk.Frame(body, bg=BG)
        _erow.pack(fill="x", pady=(0, px(2)))
        self._enemy_row = _erow
        _eleft = tk.Frame(_erow, bg=BG)
        _eleft.pack(side="left", fill="both", expand=True, padx=(0, px(7)))
        _eright = tk.Frame(_erow, bg=BG, width=px(390))
        _eright.pack(side="left", fill="y", padx=(px(7), 0))
        _eright.pack_propagate(False)
        g0, b0 = _card(_eleft, "敌人摆放", "随机规则",
                       "任意类别之间互换、比例可调；数值 / 防御 / 掉落按位置对齐；"
                       "写进独立方案层，不动法魂本体。")
        g0.pack(fill="x")
        self.ev1_pools = {}
        _prow = tk.Frame(b0, bg=BG); _prow.pack(fill="x")
        tk.Label(_prow, text="特殊池", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(0, px(12)))
        for _pid, _ptxt, _pon in (("waygate", "黄金树传送门", True),
                                  ("keystone", "大锅钥石", True),
                                  ("remembrance", "追忆", True),
                                  ("reliquary", "劳弗圣龛", True)):
            _pv = tk.BooleanVar(value=_pon)
            self.ev1_pools[_pid] = _pv
            GoldCheck(_prow, text=_ptxt, variable=_pv,
                      command=self._ev1_status_refresh).pack(side="left", padx=(0, px(14)))
        # v1.3.15：多阶段 Boss 的位置默认也参与替换、身份也可当来源，两件事常开，不再给开关。
        # v1.3.16：按「模型」拆 Boss —— 同模型（跨阶段/多管血条）算一只，异模型拆成多只。
        tk.Label(b0, text="多阶段BOSS：位置默认也参与替换（14 组 / 20 个 Boss，按模型拆），身份也可当来源；"
                          "这一项默认常开，不提供开关。",
                 bg=BG, fg=SUB, font=FONT_MICRO, justify="left",
                 wraplength=px(980)).pack(anchor="w", pady=(px(8), 0))
        # 参考实现敌人页的安全/演出开关（写盘层消费；默认按安全值）
        self.ev1_bar_names = tk.BooleanVar(value=True)
        self.ev1_night = tk.BooleanVar(value=False)
        self.ev1_ignore_size = tk.BooleanVar(value=False)
        self.ev1_bgm = tk.BooleanVar(value=False)
        self.ev1_soul = tk.BooleanVar(value=False)
        self.ev1_rainbow = tk.BooleanVar(value=False)
        _rf = tk.Frame(b0, bg=BG)
        _rf.pack(fill="x", pady=(px(6), 0))
        GoldCheck(_rf, text="改BOSS血条名", variable=self.ev1_bar_names,
                  command=self._ev1_status_refresh).pack(side="left", padx=(0, px(16)))
        GoldCheck(_rf, text="夜间BOSS全天出现", variable=self.ev1_night,
                  command=self._ev1_status_refresh).pack(side="left", padx=(0, px(16)))
        GoldCheck(_rf, text="忽略场地/体型限制", variable=self.ev1_ignore_size,
                  command=self._ev1_status_refresh).pack(side="left")
        _rf2 = tk.Frame(b0, bg=BG)
        _rf2.pack(fill="x", pady=(px(4), 0))
        GoldCheck(_rf2, text="BGM跟新BOSS", variable=self.ev1_bgm,
                  command=self._ev1_status_refresh).pack(side="left", padx=(0, px(16)))
        GoldCheck(_rf2, text="卢恩跟新BOSS", variable=self.ev1_soul,
                  command=self._ev1_status_refresh).pack(side="left", padx=(0, px(16)))
        GoldCheck(_rf2, text="随机化敌人颜色", variable=self.ev1_rainbow,
                  command=self._ev1_status_refresh).pack(side="left")
        # 参考实现的全局数值倍率 + Oops All（全替换为某一类）
        _rf3 = tk.Frame(b0, bg=BG)
        _rf3.pack(fill="x", pady=(px(6), 0))
        tk.Label(_rf3, text="生命值倍率（只改血量）", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(0, px(6)))
        self.ev1_scale = tk.DoubleVar(value=1.0)
        ttk.Scale(_rf3, from_=0.5, to=2.0, variable=self.ev1_scale,
                  orient="horizontal", length=px(120),
                  command=lambda _v: self._ev1_status_refresh()).pack(side="left")
        self.ev1_scale_lbl = ttk.Label(_rf3, text="1.00×", style="Gold.TLabel", width=6)
        self.ev1_scale_lbl.pack(side="left", padx=(px(2), px(16)))
        tk.Label(_rf3, text="全替换为", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(0, px(6)))
        self.ev1_oops = tk.StringVar(value="不启用（按规则表）")
        ttk.Combobox(_rf3, textvariable=self.ev1_oops, state="readonly", width=14,
                     values=["不启用（按规则表）"] + [enemy_class_cn(k) for k in
                                                    self._ev1_visible_class_ids()]).pack(side="left")
        # 参考实现的 Enemy Onslaught（实验）：只复制普通敌人，默认关。
        _rf4 = tk.Frame(b0, bg=BG)
        _rf4.pack(fill="x", pady=(px(6), 0))
        tk.Label(_rf4, text="敌人倍增（实验：只对普通敌人）", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(0, px(6)))
        self.ev1_ons = tk.DoubleVar(value=1.0)
        ttk.Scale(_rf4, from_=1.0, to=2.0, variable=self.ev1_ons,
                  orient="horizontal", length=px(120),
                  command=lambda _v: self._ev1_status_refresh()).pack(side="left")
        self.ev1_ons_lbl = ttk.Label(_rf4, text="1.00×", style="Gold.TLabel", width=6)
        self.ev1_ons_lbl.pack(side="left", padx=(px(2), px(12)))
        tk.Label(_rf4, text="（复制普通敌人；Boss/传送门/多阶段不动）", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left")
        # 2026-10-23：法魂本体永不写 —— 不再给「写本体」这个开关（流程固定走方案层）。
        # 变量留给部署代码与自检读（恒 True），界面上没有这个表单。
        self.ev1_overlay = tk.BooleanVar(value=True)
        _r1 = tk.Frame(b0, bg=BG); _r1.pack(fill="x", pady=(px(10), 0))
        tk.Label(_r1, text="种子", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(0, px(8)))
        self.ev1_seed = tk.StringVar(value=str(self.seed.get() or 1))
        ttk.Entry(_r1, textvariable=self.ev1_seed, width=10).pack(side="left")
        tk.Label(_r1, text="比例", bg=BG, fg=SUB,
                 font=FONT_SMALL).pack(side="left", padx=(px(18), px(8)))
        self.ev1_mult = tk.DoubleVar(value=1.0)
        ttk.Scale(_r1, from_=0.05, to=1.0, variable=self.ev1_mult,
                  orient="horizontal", length=px(180),
                  command=lambda _v: self._ev1_status_refresh()).pack(side="left")
        self.ev1_mult_lbl = ttk.Label(_r1, text="100%", style="Gold.TLabel", width=5)
        self.ev1_mult_lbl.pack(side="left", padx=px(8))
        _r2 = tk.Frame(b0, bg=BG); _r2.pack(fill="x", pady=(px(12), 0))
        # 生成入口统一在窗口底部那一个金色按钮上（这里只留「预览」这种不写盘的动作）
        self.b_ev1_preview = ttk.Button(_r2, text="预览这次会换什么（不写盘）",
                                        style="Secondary.TButton",
                                        command=self.enemy_v1_preview)
        self.b_ev1_preview.pack(side="left")
        tk.Label(_r2, text="开始按钮在窗口底部：勾着哪几个类型，就随机哪几个",
                 bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left", padx=px(12))
        _r3 = tk.Frame(b0, bg=BG)
        _r3.pack(fill="x", pady=(px(8), 0))
        ttk.Button(_r3, text="自定义敌人配置…", style="Ghost.TButton",
                   command=self.enemy_v1_preset_editor).pack(side="left")
        ttk.Button(_r3, text="手动指定…", style="Ghost.TButton",
                   command=self.enemy_v1_manual).pack(side="left", padx=px(8))
        self.ev1_preset_lbl = ttk.Label(_r3, text="配置：内置规则（按类别调权重 / 目标）",
                                        style="Hint.TLabel")
        self.ev1_preset_lbl.pack(side="left", padx=px(10))
        self.ev1_hint = ttk.Label(b0, text="", style="Hint.TLabel",
                                  wraplength=px(700), justify="left")
        self.ev1_hint.pack(anchor="w", pady=(px(10), 0))
        # 规则说明压成一行（详细六条见 docs/敌人随机_区域档位依据 与 README）：
        # 常显六行说明属于"文档"，不属于"表单" —— 想细看的人去读文档。
        tk.Label(b0, text="规则：传送门守卫 / 有血条的位 → BOSS；六类 BOSS 互换；"
                          "常规敌人与野生动物互换；其它不动。",
                 bg=BG, fg=MUTED, font=FONT_MICRO, wraplength=px(700),
                 justify="left").pack(anchor="w", pady=(px(12), 0))

        # ── 右列：当前方案（唯一的状态与挂载入口）──
        g5, b5 = _card(_eright, "当前方案", "挂载状态")
        g5.pack(fill="x", pady=(0, px(10)))
        self.enemy_page_hint = ttk.Label(b5, text="", style="Hint.TLabel",
                                         wraplength=px(320), justify="left")
        self.enemy_page_hint.pack(anchor="w")
        self.b_enemy_play = ttk.Button(b5, text="到方案库开始玩", style="Secondary.TButton",
                                       command=self._goto_library)
        self.b_enemy_play.pack(fill="x", pady=(px(12), px(6)))
        self.b_enemy_revert = ttk.Button(b5, text="切回法魂本体", style="Ghost.TButton",
                                         command=self.enemy_v1_revert)
        self.b_enemy_revert.pack(fill="x")
        g6, b6 = _card(_eright, "说明", "这一层是什么")
        g6.pack(fill="x")
        tk.Label(b6, text="方案层 = 盖在法魂本体上的一层文件。\n"
                          "切回 = 删掉 Plan= 一行；本体始终干净。",
                 bg=BG, fg=MUTED, font=FONT_MICRO, wraplength=px(250),
                 justify="left").pack(anchor="w", fill="x")

        # 页签启用勾要能一次禁掉 v1 卡片里的所有可点控件
        self._ev1_widgets = []

        def _walk_ev1(w):
            for _c in w.winfo_children():
                self._ev1_widgets.append(_c)
                _walk_ev1(_c)
        _walk_ev1(b0)

        self._refresh_ev1_on()
        self._enemy_page_refresh()
    def enemy_v1_play(self):
        """用当前方案玩：换档 + 挂载 + 启动（与方案库那个按钮同一条路）"""
        d = self._ev1_layer_dir()
        if not d:
            self._ev1_hint_set("还没有方案层 —— 先点底部的「开始随机…」生成一个", bad=True)
            return
        self._play_layer(d)

    def _launch_gl(self, gl, ld):
        """换档 + 挂载 + 起游戏（游戏在跑就先问人，同意就自动关掉它）

        2026-10-23 作者要求：别让人先去手动退游戏 —— 点一下就把在跑的关掉再开。
        但强杀会丢最近一小段进度，所以**先问一次**；gamelib 先请它自己退，等不到才强杀。
        成功返回 gamelib.launch 的结果；失败 / 人取消返回 None（对话框已经弹过）。
        """
        name = os.path.basename(str(ld).rstrip("\\/"))
        # ① 有没有这个方案的存档槽：没有就先问"用新角色开局"，别等关了游戏才问
        try:
            _lab = gl.plan_label(ld)
        except Exception:
            _lab = name
        try:
            _has = bool(gl.bank_status(_lab).get("has"))
        except Exception:
            _has = True                 # 查不到就交给 launch 自己判断
        _allow_new = False
        if not _has:
            if not messagebox.askyesno(
                    "这个方案还没有存档",
                    "「%s」还没有自己的存档。\n\n"
                    "现在就用新角色开始吗？\n\n"
                    "（你现在的档会先留底，不会丢；选「否」就先不动）" % name,
                    parent=self.root):
                self._lib_toast("没启动：存档保持原样")
                return None
            _allow_new = True
        # ② 游戏在跑：先问，同意就自动关掉
        _running = False
        try:
            _running = bool(gl.game_running())
        except Exception:
            _running = False
        _kill = False
        if _running:
            if not messagebox.askyesno(
                    "游戏正在运行",
                    "要用「%s」开局，得先把正在跑的《艾尔登法环》关掉。\n\n"
                    "现在自动关掉它并启动吗？\n\n"
                    "（先请它自己退出；实在不退才强制结束 —— 强杀会丢最近一小段进度）" % name,
                    parent=self.root):
                self._lib_toast("没启动：游戏还开着")
                return None
            _kill = True
        # ③ 换档 + 挂载 + 起游戏
        try:
            return gl.launch(ld, allow_new_save=_allow_new, kill_running=_kill)
        except gl.NeedsNewSave as e:
            if not messagebox.askyesno(
                    "这个方案还没有存档",
                    str(e) + "\n\n现在就用新角色启动吗？\n\n"
                    "（选「否」就先不动 —— 你可以继续沿用现在这份档）",
                    parent=self.root):
                self._lib_toast("没启动：存档保持原样")
                return None
            try:
                return gl.launch(ld, allow_new_save=True, kill_running=_kill)
            except Exception as e2:
                messagebox.showerror("启动失败", str(e2), parent=self.root)
                return None
        except gl.GameError as e:
            messagebox.showwarning(
                "还不能启动", str(e) + "\n\n覆盖层没问题 —— 退出游戏后再点一次就行。",
                parent=self.root)
            self._lib_toast(str(e), bad=True)
            return None
        except Exception as e:
            messagebox.showerror("启动失败", str(e), parent=self.root)
            return None

    def _play_layer(self, layer_dir):
        """换档 → 挂载 → 起游戏；退出后由 _lib_game_watch 把存档存回它的槽"""
        if self._deploy_busy():
            self._lib_toast("正在写盘 —— 等写完再启动（不然启动的是写了一半的层）", bad=True)
            return
        gl = self._lib_gamemod()
        if not gl:
            return
        name = os.path.basename(layer_dir)
        r = self._launch_gl(gl, layer_dir)
        if not r:
            return
        self.log("用方案启动：" + name + "（层 " + layer_dir + "）")
        if r.get("restored"):
            _what = "用它的存档开局"
        elif r.get("fresh"):
            _what = "新角色开局"
        else:
            _what = "沿用当前存档"
        self._ev1_hint_set("已启动 ✓ 下次退出游戏时，进度会存回这个方案的槽")
        self._enemy_page_refresh()
        self.status.set("已启动「%s」（%s）—— 退出游戏后进度会自动存回它的槽" % (name, _what))
        self._lib_game_seen = False
        self.root.after(2000, lambda: self._lib_game_watch(gl, name, 2))

    def _enemy_page_refresh(self, *_a):
        """页脚那行：现在挂的是哪个方案（P0-1：如果是坏的层路径要如实标出来）"""
        hint = ""
        bad = False
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import plan_layer as PL
            st = PL.plan_status()
            if st.get("valid"):
                # 只显示层名（完整 Plan= 是一条很长的相对路径，在窄列里会被硬折成两半）
                _line = st.get("line") or ""
                _lbl = os.path.basename(os.path.dirname(_line.rstrip("/\\"))) or _line
                hint = "当前挂载：" + _lbl
            elif st.get("line"):
                hint = "当前挂载无效：" + (st.get("reason", "") or "路径不对")
                bad = True
            else:
                hint = "当前挂载：" + (st.get("reason") or "（没有，跑的是纯法魂本体）")
        except Exception:
            hint = "当前挂载：（读不出来）"
        if hasattr(self, "enemy_page_hint"):
            self.enemy_page_hint.config(text=hint,
                                        style="Bad.TLabel" if bad else "Hint.TLabel")
    def _enemy_page_hint_set(self, text, bad=False):
        if hasattr(self, "enemy_page_hint"):
            self.enemy_page_hint.config(text=text, style="Bad.TLabel" if bad else "Hint.TLabel")

    # ── 敌人随机 v1（新管线）──
    def _ev1_options(self):
        pools = {k: bool(v.get()) for k, v in (getattr(self, "ev1_pools", None) or {}).items()}
        try:
            mult = float(self.ev1_mult.get())
        except Exception:
            mult = 1.0
        opts = {"pools": pools, "rates": {"multiplier": max(0.0, min(1.0, mult))},
                "constraints": {
                    # v1.3.15：多阶段 Boss 的位置默认也换、身份也能当来源；常开，界面无开关。
                    "multiphase_swap": True,
                    "multiphase_as_source": True,
                    "ignore_size": bool(getattr(self, "ev1_ignore_size", None) and self.ev1_ignore_size.get()),
                },
                "features": {
                    "bar_names": bool(getattr(self, "ev1_bar_names", None) and self.ev1_bar_names.get()),
                    "nightday": bool(getattr(self, "ev1_night", None) and self.ev1_night.get()),
                    "bgm_follow": bool(getattr(self, "ev1_bgm", None) and self.ev1_bgm.get()),
                    "soul_follow": bool(getattr(self, "ev1_soul", None) and self.ev1_soul.get()),
                    "rainbow": bool(getattr(self, "ev1_rainbow", None) and self.ev1_rainbow.get()),
                    "onslaught": float(getattr(self, "ev1_ons", None).get())
                                 if getattr(self, "ev1_ons", None) else 1.0,
                },
                "scaling": {"hp": float(getattr(self, "ev1_scale", None).get())
                            if getattr(self, "ev1_scale", None) else 1.0}}
        _oops = str(getattr(self, "ev1_oops", None).get()) if getattr(self, "ev1_oops", None) else ""
        if _oops and not _oops.startswith("不启用"):
            for _k, _v in ENEMY_CLASS_CN.items():
                if _v == _oops:
                    opts["oops_all"] = _k
                    break
        p = getattr(self, "ev1_preset", None)
        if p and (p.get("classes") or p.get("pools") or p.get("bar")):
            opts["preset"] = p
        return opts

    def _ev1_seed_value(self):
        try:
            return int(str(self.ev1_seed.get()).strip() or "1")
        except Exception:
            return 1

    def _ev1_hint_set(self, text, bad=False):
        if hasattr(self, "ev1_hint"):
            self.ev1_hint.config(text=text, style="Bad.TLabel" if bad else "Hint.TLabel")

    def _ev1_status_refresh(self, *_a):
        try:
            self.ev1_mult_lbl.config(text="%d%%" % int(round(float(self.ev1_mult.get()) * 100)))
        except Exception:
            pass
        try:
            self.ev1_scale_lbl.config(text="%.2f×" % float(self.ev1_scale.get()))
        except Exception:
            pass
        try:
            self.ev1_ons_lbl.config(text="%.2f×" % float(self.ev1_ons.get()))
        except Exception:
            pass
        self._ev1_preset_refresh()
        self._refresh_outer()

    def _ev1_preset_refresh(self):
        if not hasattr(self, "ev1_preset_lbl"):
            return
        p = getattr(self, "ev1_preset", None)
        if not p or not (p.get("classes") or p.get("pools") or p.get("bar")):
            self.ev1_preset_lbl.config(text="预设：内置规则（按类别调换入来源）")
        else:
            _mode = "权重叠加" if (p.get("rate_mode") or "independent") == "weight" else "独立概率"
            self.ev1_preset_lbl.config(text="预设：%s（%d 个类别 / %d 个池 · %s）" % (
                p.get("name") or "自定义", len(p.get("classes") or {}),
                len(p.get("pools") or {}), _mode))

    def _ev1_visible_class_ids(self):
        """界面上可选的敌人类别（yaml 里 ui:false 的内部标记类不出现）。读不到就用保守清单。"""
        try:
            self._apply_path()
            import enemy_plan as _EP
            return _EP.visible_classes(_EP.load_yaml()[0])
        except Exception:
            return ["Basic", "Wildlife", "HostileNPC", "Boss", "MinorBoss", "Miniboss",
                    "NightMiniboss", "DragonMiniboss", "Evergaol"]

    def _apply_path(self):
        p = os.path.join(WORKSPACE, "investigation", "apply")
        if p not in sys.path:
            sys.path.insert(0, p)
        return p

    def _ev1_enabled(self):
        if bool(getattr(self, "ev1_on", tk.BooleanVar(value=True)).get()):
            return True
        self._ev1_hint_set("「敌人随机」页签没勾 —— 先在页签上勾上再操作。", bad=True)
        return False

    def enemy_v1_manual(self):
        """手动指定表：map,entity_id,npc_id,model,note（参考实现的 Manual Placement）。"""
        import csv
        p = os.path.join(WORKSPACE, "investigation", "enemy_manual.csv")
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8-sig", newline="") as fh:
                csv.writer(fh).writerow(["map", "entity_id", "npc_id", "model", "note"])
        self.log("手动指定表：" + p)
        try:
            os.startfile(p)
        except Exception as e:
            messagebox.showinfo("手动指定表",
                                "表在：\n%s\n\n用记事本打开，按列填：\n"
                                "map,entity_id,npc_id,model,note\n"
                                "（npc_id 与 model 二选一；每行指定一个位置）\n\n%s" % (p, e))

    def enemy_v1_preset_editor(self):
        """逐类预设编辑器（照参考实现的 EnemyPresetView：左边类别树 + 右边参数面板）。

        每一类可以单独设：开关、百分比、换入来源百分比、来源区域、目标区域、体型上限。
        预设存成 investigation/enemy_presets/<名字>.json；不保存就直接「应用」= 只在本次界面里生效。
        特殊规则（多阶段 / 传送门守门 / 有血条的位置）先于类别规则，类别预设不会把它们抢走。
        """
        import copy as _copy
        self._apply_path()
        import enemy_plan as EP
        if getattr(self, "_ev1_preset_win", None) and self._ev1_preset_win.winfo_exists():
            self._ev1_preset_win.lift()
            return
        try:
            data = EP.load_data()
        except Exception as exc:
            messagebox.showerror("打不开预设编辑器", "读不到敌人数据：%s" % exc, parent=self.root)
            return
        units = EP.unitize(data["places"])
        cfg = data["cfg"]
        classes = EP.visible_classes(cfg)
        # 2026-10-24：特殊池升级成「可当来源、也能单独配来源」的虚拟类。
        _pool_ids = EP.visible_pools(cfg)                 # 4 个池（排序后的 id）
        _pool_defs = EP.pool_defs(cfg)                    # pid → {id,name,status,default_on,note}
        _pool_members = {str(_p.get("id")): len(_p.get("members") or [])
                         for _p in (cfg.get("pools") or [])}
        # 来源 = 9 个可见类 + 4 个池 + 「同类型 Boss」引用（"pool:<pid>" / "@sameboss"，与 enemy_plan 同一口径）
        _sources = (list(classes) + [EP.pool_ref(_pid) for _pid in _pool_ids]
                    + [EP.SAME_BOSS_REF])
        default = EP.default_preset(cfg, units)
        # 2026-10-24：旧预设先迁移（Mob→Basic 合并、内部标记类丢弃），再填默认值。
        _norm = EP.normalize_preset(self.ev1_preset, cfg) if self.ev1_preset else None
        cur = _copy.deepcopy(_norm or default)
        _blank_cls = {"enabled": False, "rate": 0.0, "weight": 0.0, "targets": [],
                      "donor_weights": None, "source_areas": ["base", "dlc"],
                      "target_areas": "same", "size_max": None}
        _blank_pool = _copy.deepcopy(_blank_cls)

        def _ensure_cur_entries():
            """补齐 classes 与 pools 两段的全部键（老预设 / 缺字段的条目都走这里）。

            2026-10-24 起预设多了顶层 "pools"：旧预设没有这一段、default_preset 也只给
            命中内置规则的那几个池写全字段，所以编辑器打开 / 载入预设时都要补齐。
            """
            cur.setdefault("classes", {})
            cur.setdefault("pools", {})
            cur.setdefault("rate_mode", "independent")  # 老预设没有这个字段：当时是各自独立概率
            for _c in list(cur["classes"]):
                if _c not in classes:
                    cur["classes"].pop(_c, None)
            for _pid in list(cur["pools"]):
                if _pid not in _pool_ids:
                    cur["pools"].pop(_pid, None)
            _def_c = default.get("classes") or {}
            for _c in classes:
                cur["classes"].setdefault(_c, _copy.deepcopy(_def_c.get(_c) or _blank_cls))
                _d = _def_c.get(_c) or {}
                cur["classes"][_c].setdefault("weight", _d.get("weight", 0.0))
                cur["classes"][_c].setdefault("rate", _d.get("rate", 1.0))
            _def_p = default.get("pools") or {}
            for _pid in _pool_ids:
                cur["pools"].setdefault(_pid, _copy.deepcopy(_def_p.get(_pid) or _blank_pool))
                _d = _def_p.get(_pid) or {}
                _e = cur["pools"][_pid]
                _e.setdefault("enabled", _d.get("enabled", False))
                _e.setdefault("weight", _d.get("weight", 0.0))
                _e.setdefault("rate", _d.get("rate", 1.0))
                _e.setdefault("targets", list(_d.get("targets") or []))
                _e.setdefault("donor_weights", _d.get("donor_weights"))
                _e.setdefault("source_areas", list(_d.get("source_areas") or ["base", "dlc"]))
                _e.setdefault("target_areas", _d.get("target_areas") or "same")
                _e.setdefault("size_max", _d.get("size_max"))
            # 2026-10-24 v1.3.13：顶层 "bar" = 血条位条目（可 None）。default_preset 不带它；
            # 07 这类预设带了就原样保留，只补字段 —— 打开 07 → 只改类别 → 应用不会改坏它。
            cur.setdefault("bar", None)
            _bar_e = cur.get("bar")
            if isinstance(_bar_e, dict):
                for _bk, _bv in _blank_pool.items():
                    _bar_e.setdefault(_bk, _copy.deepcopy(_bv))
        _ensure_cur_entries()
        counts = {}
        for _u in units:
            counts[_u["cls"]] = counts.get(_u["cls"], 0) + 1
        n_models = len(EP.load_model_names())
        preset_dir = os.path.join(WORKSPACE, "investigation", "enemy_presets")
        # 「只同族」按钮的候选集合（2026-10-24：法魂杂兵并入 Basic、粪金龟/商队巨魔退出界面）
        _BOSSES = [c for c in ("Boss", "MinorBoss", "Miniboss", "NightMiniboss",
                               "DragonMiniboss", "Evergaol") if c in classes]
        groups = {c: list(_BOSSES) for c in _BOSSES}
        groups.update({"Basic": ["Basic", "Wildlife"], "Wildlife": ["Basic", "Wildlife"]})
        groups = {c: [x for x in v if x in classes]
                  for c, v in groups.items() if c in classes}

        win = tk.Toplevel(self.root)
        self._ev1_preset_win = win
        win.title("编辑逐类预设 — 敌人随机 v1")
        win.transient(self.root)
        try:
            win.configure(bg=BG)
        except Exception:
            pass
        win.geometry("%dx%d" % (px(1100), px(700)))
        win.minsize(px(880), px(600))
        try:
            win.grab_set()
        except Exception:
            pass

        body = ttk.Frame(win, padding=(px(14), px(12)))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="编辑逐类预设", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="左边选类别、特殊池或血条位，右边调它的换入来源百分比。"
                             "%d 个类别 / %d 个池 / 1 个血条位 / %d 个分组 / %d 个模型；"
                             "特殊规则（多阶段BOSS、黄金树传送门、有BOSS血条的位置）永远先行。"
                             % (len(classes), len(_pool_ids), len(groups), n_models),
                  style="Hint.TLabel").pack(anchor="w", pady=(px(2), px(2)))
        title_lbl = ttk.Label(body, text="", style="Gold.TLabel")
        title_lbl.pack(anchor="w", pady=(0, px(8)))

        def _refresh_title():
            _nm = cur.get("name") or "自定义预设"
            _mode = "按类百分比" if (cur.get("rate_mode") or "weight") == "weight" else "各自独立概率"
            try:
                title_lbl.config(text="预设：%s ｜ %s ｜ %s" % (
                    _nm, "内置规则" if cur.get("builtin") else "已改动（未应用）", _mode))
            except Exception:
                pass

        def _mark_dirty():
            cur["builtin"] = False
            _refresh_title()
        _refresh_title()

        # 底部动作栏先占位（否则中栏的类别树会把窗口撑满，保存/应用按钮被挤出可视区）
        foot = tk.Frame(body, bg=BG)
        foot.pack(side="bottom", fill="x", pady=(px(10), 0))
        mid = tk.Frame(body, bg=BG)
        mid.pack(fill="both", expand=True)
        left = tk.Frame(mid, bg=BG)
        left.pack(side="left", fill="y")
        tree = ttk.Treeview(left, show="tree", height=22, selectmode="browse")
        tree.column("#0", width=px(240), minwidth=px(200))
        _lsb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=_lsb.set)
        tree.pack(side="left", fill="both", expand=True)
        _lsb.pack(side="right", fill="y")
        self._ev1_preset_tree = tree
        # 右侧面板可滚动：池面板内容比窗口高（成员/说明 + 13 个来源 + 区域/体型），
        # 不滚动的话最后一行会被压扁看不见（与方案库详情同一套 _scrollable）。
        _rcol = ttk.Frame(mid)
        _rcol.pack(side="left", fill="both", expand=True, padx=(px(12), 0))
        right = self._scrollable(_rcol, maxw=px(760))
        self._ev1_preset_right = right

        tree.insert("", "end", iid="global", text="全局设置")
        tree.insert("", "end", iid="classes", text="类别（%d）" % len(classes), open=True)
        for _c in classes:
            tree.insert("classes", "end", iid="cls:" + _c,
                        text="%s   %d" % (enemy_class_cn(_c), counts.get(_c, 0)))
        tree.insert("", "end", iid="pools", text="特殊池（%d）" % len(_pool_ids), open=True)
        for _pid in _pool_ids:
            tree.insert("pools", "end", iid=EP.pool_ref(_pid),
                        text=(_pool_defs.get(_pid) or {}).get("name") or _pid)
        # 2026-10-24 v1.3.13：血条位条目（preset.bar）—— 覆盖内置「有血条位置」规则
        tree.insert("", "end", iid="bar", text="血条位（真 BOSS 战）")
        # uitest / 脚本要能验「池面板写进 cur 了吗」：把当前模型与最近一次面板提交函数挂出来
        self._ev1_preset_cur = cur
        self._ev1_preset_weights = {}
        self._ev1_preset_commit = None

        def clear():
            for _w in right.winfo_children():
                _w.destroy()
            _cv = getattr(right, "_scroll_canvas", None)
            if _cv is not None:
                try:
                    _cv.yview_moveto(0)
                except Exception:
                    pass

        def head(title, desc):
            clear()
            ttk.Label(right, text=title, style="Sub.TLabel").pack(anchor="w")
            ttk.Label(right, text=desc, style="Hint.TLabel", wraplength=px(720),
                      justify="left").pack(anchor="w", pady=(px(2), px(10)))

        def _ref_weight(ref):
            """某个来源的默认权重：类看 classes 条目，池看 pools 条目；@sameboss 只是引用。"""
            if EP.is_same_boss_ref(ref):
                return 1.0      # 旧预设 targets 里只有 @sameboss 时的兜底（等分即可）
            if EP.is_pool_ref(ref):
                _e = (cur.get("pools") or {}).get(EP.pool_id_of(ref)) or {}
            else:
                _e = cur["classes"].get(ref) or {}
            try:
                return float(_e.get("weight") or 0.0)
            except (TypeError, ValueError):
                return 0.0

        def _source_label(ref):
            """来源网格的标签：类用中文名，池写「池：<中文名>」，@sameboss 写「同类型 Boss」。"""
            if EP.is_same_boss_ref(ref):
                return "同类型 Boss"
            if EP.is_pool_ref(ref):
                _pid = EP.pool_id_of(ref)
                return "池：%s" % ((_pool_defs.get(_pid) or {}).get("name") or _pid)
            return enemy_class_cn(ref)

        def _init_donor_weights(st):
            """把 donor_weights 或 targets 折成 {来源引用: 初始权重}（旧预设没有 donor_weights）。"""
            _init = {}
            _dw = st.get("donor_weights")
            if _dw:
                for _k, _w in _dw.items():
                    try:
                        _w = float(_w)
                    except (TypeError, ValueError):
                        continue
                    if _w > 0:
                        _init[str(_k)] = _w
            else:
                for _ref in (st.get("targets") or []):
                    _w = _ref_weight(_ref)
                    if _w > 0:
                        _init[_ref] = _w
                if not _init:
                    for _ref in (st.get("targets") or []):
                        _init[_ref] = 1.0
            return _init

        def _build_donor_editor(st, family, on_change):
            """来源百分比网格（9 类 + 4 池同款）+ 合计 + 自动平衡 + 四个快捷按钮。

            写回由返回的 sync() 做：sync() 把网格读成 donor_weights / targets。
            family 是「只同族」按钮的候选（池面板传 None，不摆这个按钮）。
            """
            tk.Label(right, text="换入来源百分比（换进来的敌人里，各来源占多少）", bg=BG, fg=GOLD,
                     font=FONT_MICRO).pack(anchor="w", pady=(px(14), px(4)))
            mix = tk.Frame(right, bg=BG)
            mix.pack(anchor="w")
            _init = _init_donor_weights(st)
            _sum = sum(_init.values())
            pct_v = {}
            for _i, _ref in enumerate(_sources):
                cell = tk.Frame(mix, bg=BG)
                cell.grid(row=_i // 4, column=_i % 4, sticky="w",
                          padx=(0, px(10)), pady=px(2))
                tk.Label(cell, text=_source_label(_ref), bg=BG, fg=SUB, font=FONT_MICRO,
                         width=13, anchor="w").pack(side="left")
                _val = (100.0 * _init.get(_ref, 0.0) / _sum) if _sum else 0.0
                _v = tk.StringVar(value="%.1f" % _val)
                pct_v[_ref] = _v
                _e = ttk.Entry(cell, textvariable=_v, width=5)
                _e.pack(side="left")
                tk.Label(cell, text="%", bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left")
                _e.bind("<FocusOut>", lambda _ev, _r=_ref: _on_pct_focus(_ev, _r))
                _e.bind("<Return>", lambda _ev, _r=_ref: _on_pct_focus(_ev, _r))
            mr = tk.Frame(right, bg=BG)
            mr.pack(anchor="w", pady=(px(4), 0))
            total_lbl = tk.Label(mr, text="合计 100.0%", bg=BG, fg=GOLD, font=FONT_MICRO)
            total_lbl.pack(side="left")
            auto_v = tk.BooleanVar(value=True)
            GoldCheck(mr, text="自动平衡到 100%", variable=auto_v,
                      command=lambda: _balance()).pack(side="left", padx=(px(16), 0))
            br = tk.Frame(right, bg=BG)
            br.pack(anchor="w", pady=(px(4), 0))

            def _read_pcts():
                out = {}
                for _ref in _sources:
                    try:
                        _v = float(pct_v[_ref].get())
                    except (TypeError, ValueError):
                        _v = 0.0
                    out[_ref] = max(0.0, min(100.0, _v))
                return out

            def _refresh_total():
                total_lbl.config(text="合计 %.1f%%" % sum(_read_pcts().values()))

            def _set_pcts(vals):
                for _ref in _sources:
                    pct_v[_ref].set("%.1f" % max(0.0, min(100.0, float(vals.get(_ref, 0.0)))))
                _refresh_total()

            def _balance():
                vals = _read_pcts()
                _tot = sum(vals.values())
                if _tot <= 0:
                    return
                _set_pcts({r: v * 100.0 / _tot for r, v in vals.items()})
                on_change()

            def _on_pct_focus(_ev, keep):
                vals = _read_pcts()
                if auto_v.get():
                    _keep = vals[keep]
                    _rest = sum(v for r, v in vals.items() if r != keep)
                    if _keep >= 100.0:
                        vals = {r: (100.0 if r == keep else 0.0) for r in _sources}
                    elif _rest > 0:
                        _target = 100.0 - _keep
                        for r in _sources:
                            if r != keep:
                                vals[r] = vals[r] * _target / _rest
                    else:
                        vals[keep] = 100.0
                    _set_pcts(vals)
                on_change()

            def _preset_pcts(refs):
                vals = {r: 0.0 for r in _sources}
                _refs = [r for r in (refs or []) if r in vals]
                if _refs:
                    _share = 100.0 / len(_refs)
                    for r in _refs:
                        vals[r] = _share
                _set_pcts(vals)
                on_change()

            if family:
                ttk.Button(br, text="只同族", style="Ghost.TButton",
                           command=lambda: _preset_pcts(family)).pack(side="left")
            ttk.Button(br, text="全部类别平均", style="Ghost.TButton",
                       command=lambda: _preset_pcts(_sources)).pack(side="left", padx=(px(6), 0))
            ttk.Button(br, text="清零", style="Ghost.TButton",
                       command=lambda: _preset_pcts([])).pack(side="left")
            ttk.Button(br, text="自动平衡", style="Ghost.TButton",
                       command=_balance).pack(side="left", padx=px(6))
            _refresh_total()
            self._ev1_preset_weights = pct_v

            def sync():
                vals = _read_pcts()
                st["donor_weights"] = {r: round(v, 2) for r, v in vals.items() if v > 0}
                st["targets"] = sorted(st["donor_weights"])
                _refresh_total()
            return sync, pct_v

        def _build_scope_editor(st, on_change):
            """来源区域 / 目标区域 / 体型上限（类面板与池面板共用）。返回写回条目的 apply()。"""
            ar = tk.Frame(right, bg=BG)
            ar.pack(anchor="w", pady=(px(12), 0))
            tk.Label(ar, text="来源区域", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
            src_v = tk.StringVar(value="both" if len(st.get("source_areas") or []) > 1
                                 else (st.get("source_areas") or ["base"])[0])
            for _txt, _val in (("本体+DLC", "both"), ("仅本体游戏", "base"), ("仅DLC", "dlc")):
                ttk.Radiobutton(ar, text=_txt, value=_val, variable=src_v,
                                command=on_change).pack(side="left", padx=px(4))
            tr = tk.Frame(right, bg=BG)
            tr.pack(anchor="w", pady=(px(6), 0))
            tk.Label(tr, text="目标区域", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
            tgt_v = tk.StringVar(value=st.get("target_areas") or "same")
            for _txt, _val in (("同区域", "same"), ("可跨本体与DLC", "any")):
                ttk.Radiobutton(tr, text=_txt, value=_val, variable=tgt_v,
                                command=on_change).pack(side="left", padx=px(4))
            sr = tk.Frame(right, bg=BG)
            sr.pack(anchor="w", pady=(px(6), 0))
            tk.Label(sr, text="体型上限", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
            size_v = tk.StringVar(value="" if st.get("size_max") is None else str(st["size_max"]))
            ttk.Entry(sr, textvariable=size_v, width=6).pack(side="left", padx=px(8))
            tk.Label(sr, text="倍（空 = 用全局 3.0×；勾「忽略场地/体型限制」后不拦）", bg=BG, fg=MUTED,
                     font=FONT_MICRO).pack(side="left")

            def apply():
                st["source_areas"] = (["base", "dlc"] if src_v.get() == "both" else [src_v.get()])
                st["target_areas"] = tgt_v.get()
                try:
                    st["size_max"] = float(size_v.get()) if size_v.get().strip() else None
                except ValueError:
                    st["size_max"] = None
            return apply

        def show_global():
            head("全局设置", "这些是整次随机的开关；每一类自己的换入来源百分比在左边类别里调。")
            mr = tk.Frame(right, bg=BG)
            mr.pack(fill="x", pady=(px(2), 0))
            tk.Label(mr, text="比例语义", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
            mode_v = tk.StringVar(value=cur.get("rate_mode") or "weight")
            for _txt, _val in (("按类百分比（推荐）", "weight"),
                               ("各自独立概率", "independent")):
                ttk.Radiobutton(mr, text=_txt, value=_val, variable=mode_v,
                                command=lambda: _set_mode(mode_v.get())).pack(
                    side="left", padx=px(4))
            tk.Label(right, text="按类百分比：每个类别各有一组来源百分比（合计 100%），"
                                 "决定这一类换进来的敌人里各来源占多少；换多少个由下面的总替换比例控制。"
                                 "各自独立概率：每类按自己的比例抽，互不影响。",
                     bg=BG, fg=MUTED, font=FONT_MICRO, wraplength=px(720),
                     justify="left").pack(anchor="w", pady=(px(4), px(2)))

            def _set_mode(m):
                cur["rate_mode"] = m
                _mark_dirty()
                _sel = (tree.selection() or ["global"])[0]
                show()
            r1 = tk.Frame(right, bg=BG)
            r1.pack(fill="x", pady=(px(8), 0))
            tk.Label(r1, text="总替换比例", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
            ttk.Scale(r1, from_=0.05, to=1.0, variable=self.ev1_mult, orient="horizontal",
                      length=px(260), command=lambda _v: self._ev1_status_refresh()).pack(
                side="left", padx=px(10))
            mult_lbl = ttk.Label(r1, text="%d%%" % int(self.ev1_mult.get() * 100),
                                 style="Gold.TLabel")
            mult_lbl.pack(side="left")
            _scale = r1.winfo_children()[-2] if len(r1.winfo_children()) >= 2 else None
            if _scale is not None:
                try:
                    _scale.configure(command=lambda _v: (
                        self._ev1_status_refresh(),
                        mult_lbl.config(text="%d%%" % int(self.ev1_mult.get() * 100))))
                except Exception:
                    pass
            tk.Label(right, text="每个类别都有自己的换入来源百分比（左边类别页里设置，合计 100%）；"
                                 "这里只调总替换比例。", bg=BG, fg=GOLD,
                     font=FONT_MICRO, wraplength=px(720), justify="left").pack(
                anchor="w", pady=(px(12), px(4)))

            def _merge(group, label):
                """参考实现的「合并全BOSS / 合并全敌人」：把一组类别并成同一个来源池。"""
                _g = [c for c in group if c in cur["classes"]]
                if not _g:
                    return
                _pct = 100.0 / len(_g)
                for _c in _g:
                    _e = cur["classes"][_c]
                    _e["enabled"] = True
                    _e["rate"] = 1.0
                    _e["targets"] = list(_g)
                    _e["donor_weights"] = {c: _pct for c in _g}
                    _e["weight"] = 1.0
                _mark_dirty()
                self.log("预设：%s（%d 类并成一个来源池）" % (label, len(_g)))
                show()
            _mrg = tk.Frame(right, bg=BG)
            _mrg.pack(anchor="w", pady=(px(6), 0))
            ttk.Button(_mrg, text="合并全BOSS", style="Ghost.TButton",
                       command=lambda: _merge(
                           ["Boss", "MinorBoss", "Miniboss", "NightMiniboss",
                            "DragonMiniboss", "Evergaol"], "合并全BOSS")).pack(side="left")
            ttk.Button(_mrg, text="合并全敌人", style="Ghost.TButton",
                       command=lambda: _merge(
                           [c for c in classes if counts.get(c, 0) > 0
                            and c not in ("Dummy", "None", "Helper", "DupeOnly")],
                           "合并全敌人")).pack(side="left", padx=(px(8), 0))
            tk.Label(right, text="多阶段首领：位置默认也换、按模型拆 Boss、身份也能当来源（常开，无开关）",
                     bg=BG, fg=SUB, font=FONT_MICRO).pack(anchor="w", pady=(px(12), 0))
            tk.Label(right, text="参与池（池只决定哪些位置参与；具体换谁由下面类别规则决定）",
                     bg=BG, fg=GOLD, font=FONT_MICRO).pack(anchor="w", pady=(px(14), px(4)))
            prow = tk.Frame(right, bg=BG)
            prow.pack(anchor="w")
            _pnames = {p["id"]: (p.get("name") or p["id"]) for p in (cfg.get("pools") or [])}
            for _pid, _pv in (getattr(self, "ev1_pools", None) or {}).items():
                GoldCheck(prow, text=_pnames.get(_pid, _pid), variable=_pv,
                          command=self._ev1_status_refresh).pack(side="left", padx=(0, px(12)))
            tk.Label(right, text="注意：黄金树传送门守卫 / 本来有BOSS血条的位置 / 多阶段BOSS组由特殊规则先接管，"
                                 "类别预设不会改变它们能不能换；多阶段 Boss 的位置与身份都默认参与（常开）。",
                     bg=BG, fg=MUTED, font=FONT_MICRO, wraplength=px(700),
                     justify="left").pack(anchor="w", pady=(px(14), 0))

        def show_class(cls):
            st = cur["classes"].setdefault(cls, _copy.deepcopy(default["classes"].get(cls) or {}))
            _weight_mode = (cur.get("rate_mode") or "weight") == "weight"
            head("%s —— %d 个替换位置组" % (enemy_class_cn(cls), counts.get(cls, 0)),
                 ("只改这一类：关掉 = 这一类保持原样；下面每个来源的百分比 = 这一类换进来的敌人里它占多少。"
                  "（权重模式统一由底部总替换比例控制换多少个。）") if _weight_mode else
                 "只改这一类：比例 = 这一类里换多少个；下面每个来源的百分比 = 换进来的敌人里它占多少。")
            en_v = tk.BooleanVar(value=bool(st.get("enabled", True)))
            GoldCheck(right, text="参与随机（关掉 = 这一类保持原样）", variable=en_v,
                      command=lambda: _upd()).pack(anchor="w")
            rr = tk.Frame(right, bg=BG)
            rr.pack(fill="x", pady=(px(10), 0))
            rate_v = None
            if _weight_mode:
                tk.Label(rr, text="替换率", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
                tk.Label(rr, text="权重模式：由底部「总替换比例」统一控制；来源组成在下面按来源设置。",
                         bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left", padx=px(10))
            else:
                tk.Label(rr, text="比例", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
                rate_v = tk.DoubleVar(value=float(st.get("rate", 1.0)))
                rate_lbl = ttk.Label(rr, text="%d%%" % int(rate_v.get() * 100), style="Gold.TLabel",
                                     width=6)
                ttk.Scale(rr, from_=0.0, to=1.0, variable=rate_v, orient="horizontal",
                          length=px(240),
                          command=lambda _v: (rate_lbl.config(text="%d%%" % int(rate_v.get() * 100)),
                                              _upd())).pack(side="left", padx=px(10))
                rate_lbl.pack(side="left")

            def _upd(*_a):
                cur["builtin"] = False
                st["enabled"] = bool(en_v.get())
                if rate_v is not None:
                    st["rate"] = round(float(rate_v.get()), 3)
                _sync_donor()
                _apply_scope()
                _mark_dirty()

            _sync_donor, _pct_v = _build_donor_editor(st, groups.get(cls, [cls]), _upd)
            _apply_scope = _build_scope_editor(st, _upd)
            self._ev1_preset_commit = _upd


        def show_pool(pid):
            _pd = _pool_defs.get(pid) or {}
            st = cur["pools"].setdefault(pid, _copy.deepcopy(
                (default.get("pools") or {}).get(pid) or {}))
            head("%s —— %d 个池内位置" % (_pd.get("name") or pid, _pool_members.get(pid, 0)),
                 "池成员由分类表决定（不是这里增删）。两件事分开："
                 "①「这次随机纳入这个池」= 池内位置参不参与随机；"
                 "②「池内的位置按下面来源换」= 参与时，池内位置能从哪些来源换。")
            tk.Label(right, text="成员：%d 个位置\n状态：%s\n%s" % (
                _pool_members.get(pid, 0), _pd.get("status") or "ready", _pd.get("note") or ""),
                bg=BG, fg=SUB, font=FONT_SMALL, justify="left",
                wraplength=px(700)).pack(anchor="w", pady=(0, px(10)))
            # ① 这次随机用不用这个池（options.pools 的开关 —— 与预设条目 enabled 是两件事）
            if pid in (getattr(self, "ev1_pools", None) or {}):
                GoldCheck(right, text="这次随机纳入这个池（池内位置参与随机；与下面是否换来源是两件事）",
                          variable=self.ev1_pools[pid],
                          command=self._ev1_status_refresh).pack(anchor="w")
            # ② 池内位置换不换来源（预设条目 enabled）
            en_v = tk.BooleanVar(value=bool(st.get("enabled", False)))
            GoldCheck(right, text="池内的位置按下面来源换（关掉 = 池内位置保持原样）",
                      variable=en_v, command=lambda: _upd()).pack(anchor="w", pady=(px(8), 0))

            def _upd(*_a):
                cur["builtin"] = False
                st["enabled"] = bool(en_v.get())
                _sync_donor()
                _apply_scope()
                _mark_dirty()

            _sync_donor, _pct_v = _build_donor_editor(st, None, _upd)
            _apply_scope = _build_scope_editor(st, _upd)
            self._ev1_preset_commit = _upd


        def show_bar():
            """血条位（真 BOSS 战）：preset.bar —— 覆盖内置「有血条位置」规则（bossbar）。

            cur["bar"] 是单条目（可 None）。打开面板本身不算改动 —— 只有真的改了
            （勾选/百分比/区域/体型）才把条目挂回 cur；这样 07 预设的 bar 不会被
            打开编辑器这一下改坏，没写 bar 的预设也不会平白多出一条禁用条目。
            """
            _st0 = cur.get("bar")
            st = _st0 if isinstance(_st0, dict) else _copy.deepcopy(_blank_pool)
            head("血条位（真 BOSS 战）",
                 "有 BOSS 血条的位置（内置规则是 Boss 六类互抽）。勾上 = 用下面选的来源覆盖内置规则；"
                 "关掉 = 走内置规则。「同类型 Boss」= 原来是什么种类就换同种类的 Boss。")
            en_v = tk.BooleanVar(value=bool(st.get("enabled", False)))
            GoldCheck(right, text="覆盖内置血条规则（这些位置按下面来源换）",
                      variable=en_v, command=lambda: _upd()).pack(anchor="w", pady=(0, px(6)))

            def _upd(*_a):
                cur["bar"] = st
                cur["builtin"] = False
                st["enabled"] = bool(en_v.get())
                st["rate"] = 1.0            # 单条目：覆盖就是全量，不摆比例滑块
                _sync_donor()
                _apply_scope()
                _mark_dirty()

            _sync_donor, _pct_v = _build_donor_editor(st, None, _upd)
            _apply_scope = _build_scope_editor(st, _upd)
            self._ev1_preset_commit = _upd


        def show(_e=None):
            sel = (tree.selection() or ["global"])[0]
            if sel == "global":
                show_global()
            elif sel == "classes":
                show_class(classes[0])
            elif sel == "pools":
                if _pool_ids:
                    show_pool(_pool_ids[0])
                else:
                    show_global()
            elif sel == "bar":
                show_bar()
            elif sel.startswith("cls:"):
                show_class(sel[4:])
            elif sel.startswith("pool:"):
                show_pool(sel[5:])

        tree.bind("<<TreeviewSelect>>", show)
        self._ev1_preset_show = show
        tree.selection_set("global")
        show()

        # ── 底部：保存 / 载入 / 恢复默认 / 应用（foot 已在上面占好位）──
        tk.Label(foot, text="预设名", bg=BG, fg=SUB, font=FONT_SMALL).pack(side="left")
        name_v = tk.StringVar(value=cur.get("name") or "自定义预设")
        ttk.Entry(foot, textvariable=name_v, width=22).pack(side="left", padx=px(8))

        def _files():
            if not os.path.isdir(preset_dir):
                return []
            return sorted(f[:-5] for f in os.listdir(preset_dir) if f.endswith(".json"))

        def _apply():
            p = _copy.deepcopy(cur)
            if p.get("builtin"):
                self.ev1_preset = None
            else:
                try:
                    _n = EP.normalize_preset(p, cfg)
                except (SystemExit, Exception) as exc:
                    messagebox.showerror("预设不合法", str(exc), parent=win)
                    return
                self.ev1_preset = _n          # 归一化后的这份才算数（旧类名已合并）
            self._ev1_preset_refresh()
            win.destroy()

        def _save():
            name = (name_v.get() or "").strip() or "自定义预设"
            cur["name"] = name
            cur["builtin"] = False
            os.makedirs(preset_dir, exist_ok=True)
            fn = re.sub(r'[\\/:*?"<>|]+', "_", name) + ".json"
            with open(os.path.join(preset_dir, fn), "w", encoding="utf-8") as fh:
                json.dump(cur, fh, ensure_ascii=False, indent=1)
            self.ev1_preset = _copy.deepcopy(cur)
            self._ev1_preset_refresh()
            _refresh_title()
            self._ev1_hint_set("预设已保存：%s（%d 个类别 / %d 个池）" % (
                name, len(cur.get("classes") or {}), len(cur.get("pools") or {})))

        def _load(_e=None):
            pick = load_v.get()
            if not pick:
                return
            if pick == "内置规则":
                cur.clear()
                cur.update(_copy.deepcopy(default))
            else:
                fp = os.path.join(preset_dir, pick + ".json")
                if not os.path.isfile(fp):
                    return
                with open(fp, encoding="utf-8") as fh:
                    got = json.load(fh)
                # 旧预设迁移（Mob→Basic / 内部标记类丢弃），保证编辑面板只显示现行类别；
                # 没有 "pools" 段的旧预设由 _ensure_cur_entries() 补齐（normalize 会给空段）。
                got = EP.normalize_preset(got, cfg) or got
                cur.clear()
                cur.update(got)
            _ensure_cur_entries()
            _refresh_title()
            name_v.set(cur.get("name") or pick)
            show_class(classes[0])
            tree.selection_set("cls:" + classes[0])

        load_v = tk.StringVar(value="内置规则")
        combo = ttk.Combobox(foot, textvariable=load_v, width=18, state="readonly",
                             values=["内置规则"] + _files())
        combo.pack(side="left", padx=(px(12), px(6)))
        combo.bind("<<ComboboxSelected>>", _load)
        ttk.Button(foot, text="保存为预设", style="Ghost.TButton",
                   command=_save).pack(side="left", padx=px(4))
        ttk.Button(foot, text="恢复默认", style="Ghost.TButton",
                   command=lambda: (_load_pick_default())).pack(side="left", padx=px(4))
        ttk.Button(foot, text="应用并关闭", style="Secondary.TButton",
                   command=_apply).pack(side="right")
        ttk.Button(foot, text="取消", style="Ghost.TButton",
                   command=win.destroy).pack(side="right", padx=px(6))

        def _load_pick_default():
            load_v.set("内置规则")
            _load()

    def enemy_v1_preview(self):
        """v1 预览：只算计划，不写盘（约 6 秒）。"""
        if not self._ev1_enabled():
            return
        if getattr(self, "_ev1_busy", False):
            return
        self._ev1_busy = True
        self._ev1_hint_set("正在算计划（约 6 秒，不写盘）…")
        opts, seed = self._ev1_options(), self._ev1_seed_value()

        def work():
            try:
                self._apply_path()
                import enemy_plan as EP
                plan = EP.build_plan(EP.load_data(), opts, seed)
                c = plan["meta"]["counts"]
                hits = c.get("by_rule") or {}
                self._ev1_last_plan = plan
                _pn = (plan["meta"].get("preset") or {}).get("name")
                self.q.put(("ev1_page", (
                    "%s替换 %d 单元 / %d 位置；跳过 %d；规则命中 %s；没有写盘。"
                    % (("预设「%s」：" % _pn) if _pn else "预览 ✓ ",
                       c.get("replaced_units", 0), c.get("replaced_places", 0),
                       c.get("skipped_units", 0),
                       "、".join("%s %d" % (enemy_rule_cn(k), v) for k, v in sorted(hits.items()))), False)))
            except Exception as e:
                import traceback
                self.log("v1 预览失败：" + traceback.format_exc(limit=4))
                self.q.put(("ev1_page", ("✗ 预览失败：" + str(e)[:220], True)))
            finally:
                self.q.put(("ev1_page_done", None))
        threading.Thread(target=work, daemon=True).start()

    def enemy_v1_deploy(self):
        """v1 部署：算计划 → 写方案层（约 2 分钟）。"""
        if not self._ev1_enabled():
            return
        if getattr(self, "_ev1_busy", False):
            return
        self._ev1_busy = True
        seed = self._ev1_seed_value()
        label = "敌人v1_种子%d_%s" % (seed, time.strftime("%m%d_%H%M"))
        opts = self._ev1_options()
        self._ev1_hint_set("正在生成计划并写盘（约 2 分钟：497 张图 + regulation）…")
        self.log("[v1] 部署 → " + label)

        def work():
            try:
                self._apply_path()
                import enemy_plan as EP
                import enemy_write as EW
                plan = EP.build_plan(EP.load_data(), opts, seed)
                pp = os.path.join(WORKSPACE, "investigation", "enemy_plan.json")
                EP.dump_plan(plan, pp)
                man = EW.build(plan_path=pp, label=label, log=self.log)
                self._last_enemy_v1_layer = label
                self.q.put(("ev1_page", (
                    "✓ 方案层已就绪：%s（%d 张图 / %d 位置 / %d 条克隆行）。点「用这个方案玩」挂载。"
                    % (label, man["counts"]["maps"], man["counts"]["places"],
                       man["counts"]["npc_clone_rows"]), False)))
            except Exception as e:
                import traceback
                self.log("[v1] 部署失败：" + traceback.format_exc(limit=5))
                self.q.put(("ev1_page", ("✗ 部署失败：" + str(e)[:220], True)))
            finally:
                self.q.put(("ev1_page_done", None))
        threading.Thread(target=work, daemon=True).start()

    def enemy_v1_deploy_combined(self):
        """一次写入：物品 + 敌人 v1（2026-10-22）。

        以前是两条独立写盘：物品部署会先复原本体、写物品、自动挂一个“只有物品”的层；
        敌人 v1 再从本体建层、但不自动挂。于是后点的那个会把前一个顶掉。
        这里把它们串成一次：物品先写进本体（不导出物品层）→ 敌人从这份本体建层 →
        只挂这一个同时含物品与敌人的层。失败时 native_deploy 会把本体与 Plan= 一起回滚。
        """
        if not self._ev1_enabled():
            return
        if getattr(self, "_ev1_busy", False):
            return
        if not bool(getattr(self, "item_on", tk.BooleanVar(value=True)).get()):
            messagebox.showinfo("物品随机已关闭",
                                "「职业物品随机」页签没勾，这次没有物品方案可写。\n"
                                "要只写敌人：把物品页签的勾取消，再点「开始随机敌人」。")
            return
        if not self.plan:
            messagebox.showinfo("还没生成物品方案", "先在底部点一次「开始随机…」生成物品方案。")
            return
        if self._deploy_busy():
            return
        seed = self._ev1_seed_value()
        label = "敌人v1_物品+敌人_种子%d_%s" % (seed, time.strftime("%m%d_%H%M%S"))
        opts = self._ev1_options()
        _ovl = bool(getattr(self, "ev1_overlay", None) and self.ev1_overlay.get())
        _what = ("  · 物品随机只写进方案层的工作副本（同步说明书）\n"
                 "  · 敌人 v1 接着在同一份副本上构建\n"
                 "  · **法魂本体一个字节都不改**；层里同时含物品与敌人\n\n"
                 "失败不会留下半套（本体没碰，删掉 Plan= 就是纯法魂）。\n"
                 if _ovl else
                 "  · 把物品随机写进本体（并同步说明书）\n"
                 "  · 紧接着从这份本体构建敌人 v1 层\n"
                 "  · 只挂这一个层（同时含物品与敌人，不会再互相顶掉）\n\n"
                 "写入前自动备份；任何一步失败都会回滚本体与当前 Plan=。\n")
        if not messagebox.askyesno(
                "一次写入：物品 + 敌人 v1",
                "这一次会：\n" + _what + "\n写完关掉游戏重进才生效。开始？"):
            return
        plan_csv = self.export()
        if not plan_csv:
            return
        sync = bool(self.cfg.get("sync_guide", True))
        fp = self._plan_fp()
        self._ev1_busy = True
        self._deploying = True
        self._ev1_hint_set("正在一次写入：物品 + 敌人 v1（%s，约 3–4 分钟）…"
                           % ("只进方案层" if _ovl else "写本体"))
        self.status.set("一次写入：物品 + 敌人 v1…")
        self.log("[合并] 一次写入 → " + label)
        threading.Thread(target=self._deploy_worker,
                         args=(plan_csv, sync, False, fp, None),
                         kwargs={"enemy_merge": {"label": label, "seed": seed,
                                                 "options": opts, "mount": True},
                                 "overlay": _ovl},
                         daemon=True).start()

    def _ev1_layer_dir(self):
        lbl = getattr(self, "_last_enemy_v1_layer", "")
        try:
            self._apply_path()
            import plan_layer as PL
            if lbl:
                d = os.path.join(PL.plans_root(), lbl)
                if os.path.isdir(os.path.join(d, "mod")):
                    return d
            root = PL.plans_root()
            cands = [os.path.join(root, n) for n in os.listdir(root)
                     if n.startswith("敌人v1_") and os.path.isdir(os.path.join(root, n, "mod"))]
            cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return cands[0] if cands else ""
        except Exception:
            return ""

    def enemy_v1_launch(self):
        if not self._ev1_enabled():
            return
        d = self._ev1_layer_dir()
        if not d:
            self._ev1_hint_set("还没有 v1 方案层 —— 先点底部的「开始随机…」生成一个", bad=True)
            return
        try:
            self._apply_path()
            import plan_layer as PL
            PL.set_plan(d)
            self._ev1_hint_set("已挂载 ✓ 下一次启动就用它：" + os.path.basename(d))
            self._enemy_page_refresh()
        except Exception as e:
            self._ev1_hint_set("挂载失败：" + str(e), bad=True)

    def enemy_v1_revert(self):
        if not self._ev1_enabled():
            return
        try:
            self._apply_path()
            import plan_layer as PL
            r = PL.clear_plan()
            self._ev1_hint_set("已切回法魂本体" if r.get("changed") else "本来就没挂载方案")
            self._enemy_page_refresh()
        except Exception as e:
            self._ev1_hint_set("切回失败：" + str(e), bad=True)

    # ══════════ 页 3 · 方案库 ══════════
    def _build_library(self, body):
        """方案库页：左边常驻列表 + 右边常驻详情面板。

        这一页取代了原来的「一扇独立小窗 + 一排 12 个按钮 + 每个动作都弹对话框」：
        列表行是两行式（第一行名字，第二行小字摘要），详情常驻右侧、单击哪行就显示哪行。"""
        shell = tk.Frame(body, bg=BG)
        shell.pack(fill="both", expand=True, padx=px(26), pady=(px(18), px(18)))
        head = tk.Frame(shell, bg=BG)
        head.pack(fill="x", pady=(px(2), px(14)))
        acts = tk.Frame(head, bg=BG)
        acts.pack(side="right", anchor="ne", pady=(px(2), 0))
        ttk.Button(acts, text="刷新", style="SmallGhost.TButton",
                   command=self._lib_refresh).pack(side="right", padx=(px(8), 0))
        ttk.Button(acts, text="打开文件夹", style="SmallSecondary.TButton",
                   command=self._lib_open_folder).pack(side="right", padx=(px(8), 0))
        ttk.Button(acts, text="导入方案…", style="SmallSecondary.TButton",
                   command=self._lib_import).pack(side="right")
        hcol = tk.Frame(head, bg=BG)
        hcol.pack(side="left", fill="x", expand=True)
        tk.Label(hcol, text="03  ·  PLAN LIBRARY", bg=BG, fg=GOLD,
                 font=FONT_MICRO).pack(anchor="w")
        tk.Label(hcol, text="方案库", bg=BG, fg=FG, font=FONT_H1).pack(anchor="w", pady=(px(3), 0))
        tk.Label(hcol, text="每个方案是一份可切换的覆盖层；点一行看详情，双击用这个方案玩。",
                 bg=BG, fg=SUB, font=FONT_SMALL).pack(anchor="w", pady=(px(5), 0))
        self.lib_hint = ttk.Label(shell, text="", style="Muted.TLabel", wraplength=px(1020))
        self.lib_hint.pack(anchor="w", pady=(0, px(12)))

        wrap = tk.Frame(shell, bg=BG)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=62, minsize=px(360))
        wrap.columnconfigure(1, weight=38, minsize=px(340))
        wrap.rowconfigure(0, weight=1)

        # ── 左：搜索/排序 + 列表（空库时这里是引导文案）──
        left_card, left = _card(wrap, "LIBRARY", "全部方案", pad=px(16))
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, px(14)))
        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", pady=(0, px(10)))
        tk.Label(bar, text="搜索", bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left", padx=(0, px(8)))
        self.lib_search = tk.StringVar(value="")
        e_search = ttk.Entry(bar, textvariable=self.lib_search)
        e_search.pack(side="left", fill="x", expand=True)
        e_search.bind("<KeyRelease>", lambda _e: self._lib_refresh())
        e_search.bind("<Escape>", lambda _e: (self.lib_search.set(""), self._lib_refresh()))
        tk.Label(bar, text="排序", bg=BG, fg=MUTED, font=FONT_MICRO).pack(side="left", padx=(px(12), px(6)))
        self.lib_sort = tk.StringVar(value=LIBSORT[0])
        cb = ttk.Combobox(bar, textvariable=self.lib_sort, values=list(LIBSORT),
                          state="readonly", width=13)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._lib_refresh())

        self.lib_box = tk.Frame(left, bg=BG)
        self.lib_box.pack(fill="both", expand=True)
        self.lib_list = tk.Frame(self.lib_box, bg=BG)
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
        self.lib_tree.bind("<Double-1>", self._lib_on_dbl)                # 双击=用这个方案玩
        # 空状态：一个方案都没有时，告诉人下一步该干什么（配一张古书插画）
        self.lib_empty = tk.Frame(self.lib_box, bg=BG)
        book = _deco_scaled("empty_plans", 90)
        if book:
            self._deco_book = book
            tk.Label(self.lib_empty, image=book, bg=BG).pack(anchor="w", pady=(px(4), px(8)))
        tk.Label(self.lib_empty, text="还没有方案", bg=BG, fg=GOLD_LT,
                 font=FONT_H2).pack(anchor="w", pady=(0, px(4)))
        self.lib_empty_txt = ttk.Label(
            self.lib_empty, style="Hint.TLabel", justify="left", wraplength=px(360),
            text="点窗口底部的「开始随机…」—— 生成的方案会自动存到这里。\n"
                 "双击一行就开始玩（第一次会先生成覆盖层，不写法魂本体）。")
        self.lib_empty_txt.pack(anchor="w")
        ttk.Button(self.lib_empty, text="去「职业物品随机」生成一套", style="Link.TButton",
                   command=lambda: self.nb.select(self.page_set)).pack(anchor="w", pady=(px(8), 0))

        # ── 右：详情（常驻，取代弹窗）──
        right_card, right = _card(wrap, "DETAIL", "方案详情", pad=px(16))
        right_card.grid(row=0, column=1, sticky="nsew")
        # 底部两块**先**建好：pack 是"先到先占位"，它们先占住底部，滚动区才能吃剩下的空间
        # （2026-10-15 作者反馈：详情做细之后内容超一屏、滚不动，只能全屏才看得全）
        trow2 = tk.Frame(right, bg=BG)
        trow2.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.lib_toast = ttk.Label(trow2, text="", style="Muted.TLabel", wraplength=px(250),
                                   justify="left")
        self.lib_toast.pack(side="left", fill="x", expand=True)
        self.lib_trash_btn = ttk.Button(trow2, text="打开回收站", style="Link.TButton",
                                        command=self._lib_open_trash)
        # 详情面板的动作按钮（对着选中的那一个方案干活）
        act = tk.Frame(right, bg=BG)
        act.pack(side="bottom", fill="x", pady=(px(8), 0))
        for _c in range(3):
            act.columnconfigure(_c, weight=1)
        self.lib_btns = {}
        # 主次分明（2026-10-23 第二版）：流程里不再有「写入游戏」这一步 ——
        # 生成只进方案库，覆v层由「用这个方案玩」在起步时按需生成。
        for i, (key, text, cmd, sty) in enumerate((
                ("launch", "用这个方案玩", self._lib_launch, "SmallPrimary.TButton"),
                ("star", "收藏 ★", self._lib_star, "SmallGhost.TButton"),
                ("load", "载入到设置", self._lib_apply_cfg, "SmallGhost.TButton"),
                ("dup", "复制一份", self._lib_dup, "SmallGhost.TButton"),
                ("export", "导出…", self._lib_export, "SmallGhost.TButton"),
                ("delete", "删除", self._lib_delete, "SmallDanger.TButton"))):
            b = ttk.Button(act, text=text, command=cmd, style=sty)
            b.grid(row=i // 3, column=i % 3, sticky="ew",
                   padx=(0 if i % 3 == 0 else px(5), 0), pady=(0, px(5)))
            self.lib_btns[key] = b
        # 其余详情内容全部进**滚动区**（滚轮只在鼠标进详情区时接管，离开就还回去）
        right = self._scrollable(right, pad=(0, 0, 0, 0))
        self.lib_title = ttk.Label(right, text="还没选方案", style="PageTitle.TLabel",
                                   wraplength=px(320))
        self.lib_title.pack(anchor="w")
        self.lib_sub = ttk.Label(right, text="左边点一行，这里就是它的全部信息", style="Hint.TLabel")
        self.lib_sub.pack(anchor="w", pady=(px(4), px(14)))

        # ── 就地编辑：名字 / 备注 / 标签（点一下直接改，不再弹对话框）──
        self.lib_detail_empty = ttk.Label(
            right, text="从左边选一个方案，这里会显示它的随机设置、改动结果与写入记录。",
            style="Muted.TLabel", wraplength=px(340), justify="left")
        self.lib_detail_empty.pack(anchor="w", pady=(px(14), 0))
        box = tk.Frame(right, bg=BG)
        box.pack(fill="both", expand=True)
        self.lib_detail_box = box
        self._lib_filling = False
        self.lib_name_e = self._lib_field(box, "名字")
        self.lib_note_e = self._lib_field(box, "备注")
        for e, fn in ((self.lib_name_e, self._lib_commit_name),
                      (self.lib_note_e, self._lib_commit_note)):
            e.bind("<Return>", fn)
            e.bind("<FocusOut>", fn)
        trow = tk.Frame(box, bg=BG)
        trow.pack(fill="x", pady=px(4))
        tk.Label(trow, text="标签", bg=BG, fg=SUB, font=FONT_SMALL, width=7,
                 anchor="w").pack(side="left")
        self.lib_tag_box = tk.Frame(trow, bg=BG)
        self.lib_tag_box.pack(side="left", fill="x", expand=True)
        self.lib_tag_entry = ttk.Entry(trow, width=10)
        ttk.Button(trow, text="+ 添加", style="Link.TButton",
                   command=self._lib_tag_add).pack(side="left", padx=(px(8), 0))
        self.lib_tag_entry.bind("<Return>", lambda _e: self._lib_tag_commit())
        self.lib_tag_entry.bind("<Escape>", lambda _e: self.lib_tag_entry.pack_forget())

        ttk.Separator(box, orient="horizontal").pack(fill="x", pady=(px(12), px(8)))
        # 详情面板：分组 + 尽量把方案文件里有的都摊出来（2026-10-14 作者要求"更详细"）
        self.lib_vals = {}
        for _title, _fields in (
                ("随机设置", (("doms", "随机项目"), ("mode", "混合方式"), ("seed", "种子"),
                              ("coh", "合理度"), ("rates", "改动比例"), ("switches", "开关"),
                              ("enemy", "敌人随机"))),
                ("这次改了什么", (("rows", "改动行"), ("detail", "分类明细"), ("shops", "商店"),
                                  ("pools", "池子"))),
                ("记录", (("engine", "引擎版本"), ("fp", "指纹"), ("time", "保存时间"),
                          ("mtime", "修改时间"), ("layer", "覆盖层"))),
                ("存档", (("save", "方案存档"), ("live", "游戏存档")))):
            tk.Label(box, text=_title, bg=BG, fg=GOLD, font=FONT_MICRO).pack(
                anchor="w", pady=(px(10), px(2)))
            for key, label in _fields:
                row = tk.Frame(box, bg=BG)
                row.pack(fill="x", pady=px(2))
                tk.Label(row, text=label, bg=BG, fg=SUB, font=FONT_SMALL, width=7,
                         anchor="w").pack(side="left")
                v = ttk.Label(row, text="—", style="Body.TLabel",
                              wraplength=px(280), justify="left")
                v.pack(side="left", fill="x", expand=True)
                self.lib_vals[key] = v
        self._lib_cur = None
        self._lib_metas = {}
        self._lib_game_seen = False
        # 上次游戏退出时程序没开着（或者被杀了）：补一次"退出回存"
        self.root.after(1500, self._lib_recover_save)

    def _lib_field(self, parent, label):
        """详情面板里的一行可编辑字段"""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=px(4))
        tk.Label(row, text=label, bg=BG, fg=SUB, font=FONT_SMALL, width=7,
                 anchor="w").pack(side="left")
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
                          text=f"〔损坏〕{m['name']}\n    {m.get('error', '')[:60]}")
                continue
            when = time.strftime("%m-%d %H:%M", time.localtime(m.get("modified") or 0))
            _kz = {"both": "物品+敌人", "enemy": "敌人",
                   "item": "物品"}.get(m.get("kind") or "", "物品")
            _rn = m.get("rows", 0)
            line2 = [when, _kz + (f" {m.get('changed', 0)}/{_rn} 行" if _rn else " · 开玩时生成"),
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
        _pd = pl.plans_dir()
        _parts = _pd.replace("/", "\\").split("\\")
        _short = "…\\" + "\\".join(_parts[-3:]) if len(_parts) > 3 else _pd
        self.lib_hint.config(
            text=f"共 {total} 个方案{tail} ｜ 位置：{_short}",
            style="Muted.TLabel")
        # 空状态：一个方案都没有 → 换成引导文案；只是搜不到 → 说清是筛没了
        kids = tv.get_children()
        if not kids:
            if total == 0:
                self.lib_empty_txt.config(
                    text="点窗口底部的「开始随机…」—— 生成的方案会自动存到这里。\n"
                         "双击一行就开始玩（第一次会先生成覆盖层，不写法魂本体）。")
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

    def _lib_on_dbl(self, *_a):
        """双击一行 = 用这个方案玩（成熟产品的"打开"语义，不是破坏性的写入）"""
        if not self._lib_cur:
            sel = self.lib_tree.selection()
            if not sel:
                return
            self._lib_cur = sel[0]
        self._lib_launch()

    def _lib_show(self, pid):
        """把某个方案摊在右侧详情面板上"""
        self._lib_cur = pid
        self.lib_tag_entry.pack_forget()          # 换方案时把"加标签"的输入框收回去
        if hasattr(self, "lib_detail_box"):
            if pid:
                self.lib_detail_empty.pack_forget()
                self.lib_detail_box.pack(fill="both", expand=True)
            else:
                self.lib_detail_box.pack_forget()
                self.lib_detail_empty.pack(anchor="w", pady=(px(14), 0))
        usable = bool(pid) and not (self._lib_metas.get(pid) or {}).get("broken")
        for key, b in getattr(self, "lib_btns", {}).items():
            if key == "delete":
                b.config(state="normal" if pid else "disabled")
            elif key == "launch":
                # 覆盖层按需生成：只要能读的方案就能直接开玩
                b.config(state="normal" if usable else "disabled")
            else:
                b.config(state="normal" if usable else "disabled")
        if not pid:
            self.lib_title.config(text="还没有方案")
            self.lib_sub.config(text="点底部的「开始随机…」，方案会自动存到这里")
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
        _ev = cfg.get("enemy_v1") or {}
        if _ev.get("on"):
            _o = _ev.get("options") or {}
            _np = len([k for k, v in (_o.get("pools") or {}).items() if v])
            _mu = float((_o.get("rates") or {}).get("multiplier", 1.0) or 1.0)
            _hp = float((_o.get("scaling") or {}).get("hp") or 1.0)
            _t = "开（%d 个特殊池 · 换 %.0f%%" % (_np, _mu * 100)
            if abs(_hp - 1.0) > 1e-6:
                _t += " · 血量 ×%.2g" % _hp
            self.lib_vals["enemy"].config(text=_t + "）")
        else:
            self.lib_vals["enemy"].config(text="不参与（只随机物品）")

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
        if rows:
            self.lib_vals["rows"].config(
                text=f"{len(_ch)} / {len(rows)} 行" + (f"（其中跨大类 {_cross} 行）" if _cross else ""))
        else:
            self.lib_vals["rows"].config(text="敌人方案（没有物品行；开玩时生成覆盖层）")
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
        # 覆盖层：没生成 / 已生成 / 设置改过要重建（开玩时自动处理，不需要人点「写入」）
        _b = d.get("built") or {}
        if not _b:
            _ltxt = "还没生成 —— 第一次点「用这个方案玩」时自动生成"
        elif self._lib_layer_fresh(d):
            _ltxt = "已生成 · " + time.strftime("%m-%d %H:%M", time.localtime(_b.get("at") or 0))
        else:
            _ltxt = "设置改过 —— 下次开玩会重新生成"
        self.lib_vals["layer"].config(text=_ltxt)
        # 存档：这个方案自己那一份 + 游戏当前那一份（"每个方案独立存档"的可视化判据）
        try:
            _lab = (os.path.basename(self._layer_path(d)) or self._lib_layer_label(d))
        except Exception:
            _lab = ""
        gl = self._lib_gamemod(quiet=True)
        try:
            _on = bool(gl and _lab and gl.current_label() == _lab)
        except Exception:
            _on = False
        if gl and _lab:
            try:
                _bk = gl.bank_status(_lab)
            except Exception:
                _bk = None
            if _bk and _bk.get("has"):
                _bt = time.strftime("%m-%d %H:%M", time.localtime(_bk.get("at") or 0))
                self.lib_vals["save"].config(
                    text=f"{_bt}（{(_bk.get('size') or 0) / 1048576:.1f} MB）"
                         + ("｜现在挂着的就是它" if _on else ""))
            else:
                self.lib_vals["save"].config(
                    text="还没有 —— 第一次用它玩会新建一个角色"
                         + ("（现在挂着的就是它）" if _on else ""))
            try:
                _liv = gl.live_dir()
                _lf = os.path.join(_liv, "ER0000.sl2") if _liv else ""
                if _lf and os.path.isfile(_lf):
                    _lt = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(_lf)))
                    self.lib_vals["live"].config(
                        text=f"{os.path.basename(_liv)} ｜ {_lt}"
                             f"（{os.path.getsize(_lf) / 1048576:.1f} MB）")
                else:
                    self.lib_vals["live"].config(text="找不到存档目录")
            except Exception:
                self.lib_vals["live"].config(text="—")
        else:
            self.lib_vals["save"].config(text="—")
            self.lib_vals["live"].config(text="—")

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
        for text, cmd in (("▶ 用这个方案玩", self._lib_launch),
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
        self.status.set("参数已从方案库填回来了 —— 改一改再点「开始随机…」")

    def _lib_open_folder(self):
        pl = self._lib_mod()
        if not pl:
            return
        try:
            os.startfile(pl.plans_dir())  # noqa
        except Exception as e:
            self._lib_toast(f"打不开文件夹：{e}", bad=True)

    def _lib_gamemod(self, quiet=False):
        """加载 gamelib（方案库启动 + 独立存档）；拿不到就如实说明，不抛异常"""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE or "", "investigation", "apply"))
            import gamelib
            return gamelib
        except Exception as e:
            if not quiet:
                self._lib_toast(f"存档模块不可用：{e}", bad=True)
            return None

    def _lib_recover_save(self):
        """启动补回存：上一次游戏退出时程序没开着（或被杀），那份进度还只在 live 档里"""
        gl = self._lib_gamemod(quiet=True)
        if not gl or not hasattr(self, "lib_tree"):
            return
        try:
            if not gl.read_state():
                return
            r = gl.recover()
        except Exception:
            return
        if r and r.get("ok"):
            self.log(f"补回存：{r.get('label')} → {r.get('saved')}")
            self._lib_toast(f"上次玩「{r.get('label')}」的进度已存回它的槽（{r.get('saved')}）")
            self._lib_refresh(keep=self._lib_cur)

    def _lib_game_watch(self, gl, name, waited=0):
        """游戏起来之后盯着进程：一退出就把这次的存档存回这个方案的槽

        为什么要盯着：存档只能等游戏**关掉**才写完整 —— 游戏在跑的时候去复制，多半拿到半截档。
        """
        try:
            running = gl.game_running()
        except Exception:
            running = False
        if running:
            self._lib_game_seen = True
            self.root.after(4000, lambda: self._lib_game_watch(gl, name, waited + 4))
            return
        if not self._lib_game_seen and waited < 180:
            # YAFSML 起游戏要几秒（还可能弹 Steam 登录）：先等进程真的出现，别急着判"退出了"
            self.root.after(2000, lambda: self._lib_game_watch(gl, name, waited + 2))
            return
        self._lib_game_seen = False
        try:
            r = gl.finish()
        except Exception as e:
            self._lib_toast(f"退出回存失败：{e}", bad=True)
            return
        if r and r.get("ok"):
            self.log(f"退出回存：{name} → {r.get('saved')}（{r.get('live')}）")
            self._lib_toast(f"「{name}」已退出，存档已存回它的槽（{r.get('saved')}）")
            self._lib_refresh(keep=self._lib_cur)
            self._lib_show(self._lib_cur)
        elif r:
            self._lib_toast("游戏退出了，但没找到存档可存（下次启动会重新看）", bad=True)

    def _lib_launch(self):
        """用这个方案玩：覆盖层按需生成 → 换档 → 挂载 → 启动（全程不写法魂本体）

        2026-10-23 作者定的流程：随机只造方案（存方案库），玩的时候才生成覆盖层。
        于是「生成」可以在游戏运行中做；「换档 + 挂载 + 起游戏」必须等游戏退出。
        """
        pid = self._lib_need()
        pl = self._lib_mod()
        if not pid or not pl:
            return
        d = pl.get_plan(pid)
        name = (self._lib_metas.get(pid) or {}).get("name") or pid
        gl = self._lib_gamemod()
        if not gl:
            return
        if getattr(self, "_lib_building", False):
            messagebox.showinfo(
                "正在生成覆盖层",
                "「%s」的覆盖层还在生成（含敌人时约 2–4 分钟）——\n"
                "生成完会自动接着换档、起游戏，不用再点。" % name,
                parent=self.root)
            return
        if self._deploy_busy():
            messagebox.showwarning(
                "别的任务还在跑",
                "另一个生成 / 写入任务还没结束。\n等它跑完再点「用这个方案玩」。",
                parent=self.root)
            return
        # 生成覆盖层**不需要**游戏退出（它只读原始基底、不碰本体）——
        # 所以先让它在后台生成；真正换档 / 挂载那一步再要求游戏已退出。
        if not self._lib_layer_fresh(d):
            self._lib_start_build(pid, d, name)
            return
        self._lib_launch_layer(self._layer_path(d), name, pid)

    def _enemy_sig(self, enemy):
        """敌人设置的指纹：改过任何一项 ⇔ 覆盖层要重建"""
        try:
            import hashlib as _h
            txt = json.dumps(enemy or {}, ensure_ascii=False, sort_keys=True, default=str)
            return _h.sha256(txt.encode("utf-8")).hexdigest()[:16]
        except Exception:
            return ""

    def _lib_layer_label(self, d):
        """覆盖层目录名 = 这个方案的玩法标识（也是它的存档槽名字）

        改名不改目录：否则改名之后已存的档就找不回来了。唯一性靠 id 尾巴。
        """
        import re as _re
        _nm = _re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", str(d.get("name") or "plan")).strip("_")[:20]
        return "方案_%s_%s" % (_nm or "plan", str(d.get("id") or "")[-6:])

    def _layer_path(self, d):
        """方案覆盖层目录 —— 每次现算，不信任记录里的绝对路径。

        为什么要现算：方案 json 里存的是「生成当时」的绝对路径；整合包换盘、改名、
        从一台机器拷到另一台，那个路径就不存在了。覆盖层目录名本来就是按方案算的
        （built.label），方案目录又跟着法魂包走，所以 label → 现路径永远是对的。
        """
        try:
            self._apply_path()          # 保证 investigation/apply 在 sys.path 上
        except Exception:
            try:
                sys.path.insert(0, os.path.join(WORKSPACE or HERE, "investigation", "apply"))
            except Exception:
                pass
        try:
            import plan_layer as PL
        except Exception:
            return ""
        b = d.get("built") or {}
        try:
            plans = PL.plans_root()      # 没有法魂包时这里会抛 —— 不能因此放弃后面的旧路径
        except Exception:
            plans = ""
        label = str(b.get("label") or "").strip()
        if plans and label:
            p = os.path.join(plans, label)
            if os.path.isdir(os.path.join(p, "mod")):
                return p
        ld = str(d.get("layer_dir") or "").strip()
        if ld and os.path.isdir(os.path.join(ld, "mod")):
            return ld
        if plans and ld:                 # 绝对路径失效：拿目录名回方案库里找
            p = os.path.join(plans, os.path.basename(ld.rstrip("\\/")))
            if os.path.isdir(os.path.join(p, "mod")):
                return p
        return ""

    def _lib_layer_fresh(self, d):
        """现有覆盖层还对不对得上这份方案（对不上 = 设置改过/从没生成 = 要重建）"""
        ld = self._layer_path(d)
        if not ld or not os.path.isdir(os.path.join(ld, "mod")):
            return False
        b = d.get("built") or {}
        if not b:
            return False        # 老记录：不知道按哪版生成，重建一次最稳
        return (b.get("fingerprint") == (d.get("fingerprint") or "")
                and b.get("enemy_sig") == self._enemy_sig((d.get("cfg") or {}).get("enemy_v1")))

    def _lib_start_build(self, pid, d, name):
        self._lib_building = True
        self._lib_toast("正在生成「%s」的覆盖层（第一次约 2–4 分钟，不写法魂本体）…" % name)
        self.log("[方案库] 生成覆盖层 → " + name)
        self.status.set("生成覆盖层中…（%s）" % name)
        _b = getattr(self, "lib_btns", {}).get("launch")
        if _b is not None:
            try:
                _b.config(state="disabled", text="正在生成覆盖层…")
            except Exception:
                pass
        threading.Thread(target=self._lib_build_worker, args=(pid, d, name),
                         daemon=True).start()

    def _lib_build_worker(self, pid, d, name):
        """后台：按方案重建覆盖层（物品 / 敌人 / 两者），不写 mod 本体；挂载交给启动那一步"""
        try:
            self._apply_path()
            import planlib, plan_layer as PL, native_deploy
            cfg = d.get("cfg") or {}
            enemy = cfg.get("enemy_v1") or {}
            rows = d.get("rows") or []
            label = self._lib_layer_label(d)
            root = PL.plans_root()
            ld = os.path.join(root, label)
            if os.path.isdir(ld):
                shutil.rmtree(ld, ignore_errors=True)   # 整层替换：旧设置的文件不能留在层里
            if rows:
                out = os.path.join(WORKSPACE, "investigation", "apply", "out")
                os.makedirs(out, exist_ok=True)
                csvp = planlib.write_csv(pid, os.path.join(out, "plan_lib_%s.csv" % str(pid)[-8:]))
                em = None
                if enemy.get("on"):
                    em = {"label": label, "seed": enemy.get("seed"),
                          "options": enemy.get("options") or {}, "mount": False}
                rec = native_deploy.deploy(
                    csvp, sync_guide=bool(cfg.get("sync_guide", True)), log=self.log,
                    fingerprint=d.get("fingerprint"), plan_label=label,
                    plan_meta={"方案": name, "种子": d.get("seed"), "来源": "方案库"},
                    enemy_merge=em, overlay=True, mount=False)
                _lay = next((s for s in (rec.get("steps") or [])
                             if s.get("step") == "plan_layer" and s.get("ok")), None)
                if not _lay:
                    raise RuntimeError("覆盖层没产出（看上面的日志）")
                ld = _lay["dir"]
            else:
                if not enemy.get("on"):
                    raise RuntimeError("这个方案里既没有物品行、也没有敌人设置")
                import enemy_plan as EP, enemy_write as EW
                pp = os.path.join(WORKSPACE, "investigation", "enemy_plan_lib.json")
                plan = EP.build_plan(EP.load_data(), enemy.get("options") or {},
                                     enemy.get("seed") or 1)
                EP.dump_plan(plan, pp)
                EW.build(plan_path=pp, label=label, out_root=root,
                         base_reg=PL.find_pristine_reg(), log=self.log)
            built = {"fingerprint": d.get("fingerprint") or "",
                     "enemy_sig": self._enemy_sig(enemy),
                     "at": time.time(), "label": label}
            planlib.set_meta(pid, layer_dir=ld, built=built)
            self.q.put(("lib_ready", {"pid": pid, "ld": ld, "name": name}))
        except Exception as e:
            import traceback
            self.log("[方案库] 覆盖层生成失败：" + traceback.format_exc(limit=5))
            self.q.put(("lib_build_fail", "覆盖层没生成：%s" % (e,)))

    def _lib_launch_layer(self, ld, name, pid=None):
        """层已就绪：换档（每个方案一份）→ 挂载 → 起游戏"""
        gl = self._lib_gamemod()
        if not gl:
            return
        r = self._launch_gl(gl, ld)
        if not r:
            return
        self.log(f"用方案启动：{name}（层 {ld}）")
        if r.get("banked_from"):
            self.log(f"  · 上一个方案「{r['banked_from']}」的进度已先存回它的槽")
        if r.get("restored"):
            self.log(f"  · 已换入这个方案的存档：{r.get('live')}")
            _what = "用它的存档开局"
        elif r.get("fresh"):
            self.log(f"  · 没有存档 —— 用新档开局（旧档已留底，见 存档库\\_回收）")
            _what = "新角色开局"
        else:
            _what = "沿用当前存档"
        self._lib_toast(f"已启动「{name}」（{_what}）—— 退出游戏后进度会自动存回它的槽")
        self._lib_game_seen = False
        self.root.after(2000, lambda: self._lib_game_watch(gl, name, 2))
        self._lib_show(pid)

    def _lib_save_current(self):
        """把主界面刚生成的那套存进方案库。

        名字先用自动生成的一个 —— 想改就到方案库右边就地改（不再弹输入框）。"""
        pl = self._lib_mod()
        if not pl:
            return
        if not self.plan:
            self.status.set("还没生成方案 —— 先点底部的「开始随机…」")
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

    def _sync_footer(self, *_a):
        """底栏按页签显隐：物品/敌人页显示（种子 + 开始随机 + 还原/保存/启动），方案库收起。

        开始按钮是全局唯一入口，所以物品页与敌人页都要看得见它；方案库页的动作
        全在详情面板里，整条收起。"""
        try:
            cur = str(self.nb.select())
        except Exception:
            return
        _show = cur in (str(self.page_set), str(self.page_enemy))
        _foot = getattr(self, "footer", None)
        try:
            if _show:
                if _foot is not None and not _foot.winfo_manager():
                    _foot.pack(side="bottom", fill="x", before=self.nb)
                for _w, _opts in ((getattr(self, "footer_seedrow", None),
                                   dict(fill="x", padx=px(26), pady=(px(7), px(0)))),
                                  (getattr(self, "footer_bar", None),
                                   dict(fill="x", padx=px(26), pady=(px(7), px(2))))):
                    if _w is not None and not _w.winfo_manager():
                        _w.pack(before=getattr(self, "lbl_status", None), **_opts)
            else:
                # 方案库页：整条底栏都收起（动作都在详情面板里）
                if _foot is not None and _foot.winfo_manager():
                    _foot.pack_forget()
        except Exception:
            pass

    def _on_tab_changed(self, *_a):
        self._sync_nav()
        self._sync_footer()
        if hasattr(self, "lib_tree") and self.nb.select() == str(self.page_lib):
            self._lib_refresh()
        self._refresh_outer()

    def _refresh_outer(self, *_a):
        """窗口底部那行：现在这一套会**同时**随机哪些东西（物品 + 敌人 v1）"""
        if not hasattr(self, "outer_what"):
            return
        try:
            _dom = {"rune": "卢恩", "armor": "护甲", "weapon": "装备"}
            if bool(getattr(self, "item_on", tk.BooleanVar(value=True)).get()):
                items = "、".join(_dom.get(d, d) for d in self._picked_doms()) or "（没选）"
                if self.shops.get():
                    items += "＋商店"
            else:
                items = "关着"
            _pools = [k for k, v in (getattr(self, "ev1_pools", None) or {}).items()
                      if v.get()]
            if _pools:
                try:
                    _mult = float(self.ev1_mult.get())
                except Exception:
                    _mult = 1.0
                en = "%d 个特殊池 · 换 %.0f%%" % (len(_pools), _mult * 100)
                try:
                    _hp = float(self.ev1_scale.get())
                except Exception:
                    _hp = 1.0
                if abs(_hp - 1.0) > 1e-6:
                    en += " · 血量 ×%.2g" % _hp
            else:
                en = "关着"
            self.outer_what.configure(text="这次会随机　物品：" + items
                                           + "　｜　敌人：" + en)
        except Exception:
            pass

    def _refresh_item_on(self, *_a):
        """物品页签的启用勾：勾 = 这次的主按钮包含物品；取消勾 = 只随机敌人"""
        try:
            self._sync_nav()
        except Exception:
            pass
        self._refresh_start_action()
        self._refresh_outer()

    def _refresh_ev1_on(self, *_a):
        """敌人页签的启用勾：关掉 = v1 卡片整块不可点（部署按钮会拒绝）。"""
        on = bool(getattr(self, "ev1_on", tk.BooleanVar(value=True)).get())
        for w in list(getattr(self, "_ev1_widgets", [])):
            try:
                w.configure(state="normal" if on else "disabled")
            except Exception:
                pass
        try:
            self._sync_nav()
        except Exception:
            pass
        self._refresh_start_action()

    def launch_game(self):
        """照参考实现的「Launch Elden Ring」：直接起法魂包根目录的启动脚本。"""
        try:
            mr = getattr(self, "mod_root", None) or find_mod_root()
            if not mr:
                messagebox.showerror("找不到 MOD", "还没找到法魂 MOD 目录，请先在物品页指定。")
                return
            pkg = os.path.dirname(mr.rstrip("\\/"))
            bat = os.path.join(pkg, "启动法魂.bat")
            if not os.path.isfile(bat):
                messagebox.showerror("找不到启动脚本",
                                     "没找到：\n%s\n\n请确认法魂包是完整的。" % bat)
                return
            os.startfile(bat)
            self.status.set("已启动游戏（窗口可能要等几秒）")
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

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
            self.lbl_combo.config(text="注意：一项都没勾，请至少勾选一个随机项目。")
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
                    self.lbl_status.config(style="FooterBad.TLabel" if _s.startswith(("失败", "出错", "写入失败", "还原出错"))
                                           else "FooterGold.TLabel")
                elif kind == "lib":
                    _text, _bad = payload
                    self._lib_writing = False
                    self._lib_toast(str(_text), bad=bool(_bad))
                    # 写入完成后库里会多出"覆盖层目录"这一项 → 刷新一下，好让「用这个方案玩」亮起来
                    try:
                        self._lib_refresh(keep=getattr(self, "_lib_cur", None))
                    except Exception:
                        pass
                elif kind == "head_engine":
                    try:
                        self.head_chip_engine.config(text="引擎 " + str(payload),
                                                     fg=GOLD_LT, highlightbackground=EDGE)
                    except Exception:
                        pass
                elif kind == "ev1_page":
                    _t, _b = payload
                    self._ev1_hint_set(str(_t), bad=bool(_b))
                elif kind == "ev1_page_done":
                    self._ev1_busy = False
                    self._refresh_start_action()
                elif kind == "deploying":
                    self._deploying = False
                    self._refresh_start_action()
                elif kind == "gen_ok":
                    self._start_gen_ok(bool(payload))
                elif kind == "lib_ready":
                    # 覆盖层生成完了：刷新详情，然后**接着**换档 + 启动
                    self._lib_building = False
                    self._lib_refresh(keep=(payload or {}).get("pid"))
                    self._lib_toast("覆盖层已生成 —— 正在换档并启动…")
                    self._lib_launch_layer((payload or {}).get("ld"),
                                           (payload or {}).get("name"),
                                           (payload or {}).get("pid"))
                elif kind == "lib_build_fail":
                    self._lib_building = False
                    self._lib_toast(str(payload), bad=True)
                    self.status.set(str(payload))
                    _b = getattr(self, "lib_btns", {}).get("launch")
                    if _b is not None:
                        try:
                            _b.config(state="normal", text="用这个方案玩")
                        except Exception:
                            pass
                    messagebox.showerror(
                        "覆盖层没生成",
                        str(payload) + "\n\n详情见窗口里的日志。改完设置再点「用这个方案玩」重试。",
                        parent=self.root)
                elif kind == "done":
                    self._generating = False
                    self._refresh_start_action()
                    self._refresh_outer()
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
        self.env_rows = rows
        ok_n = sum(1 for _n, ok, _note, _p in rows if ok)
        bad = [n for n, ok, _note, _p in rows if not ok]
        if hasattr(self, "lbl_env"):
            self.lbl_env.config(text="%d / %d 项通过" % (ok_n, len(rows)),
                                style="Good.TLabel" if not bad else "Bad.TLabel")
        # 逐项摊成两列：圆点 + 名称 + 说明（比一整段 \n 文本好扫）
        if hasattr(self, "env_box"):
            for w in self.env_box.winfo_children():
                w.destroy()
            self.env_box.columnconfigure(0, weight=1, uniform="env")
            self.env_box.columnconfigure(1, weight=1, uniform="env")
            for i, (name, ok, note, _path) in enumerate(rows):
                row = tk.Frame(self.env_box, bg=BG)
                row.grid(row=i // 2, column=i % 2, sticky="w", pady=px(3))
                tk.Label(row, text="●", bg=BG, fg=SUCCESS if ok else DANGER,
                         font=(FONT_NAME, 7)).pack(side="left", padx=(0, px(7)))
                tk.Label(row, text=name, bg=BG, fg=FG, font=FONT_SMALL).pack(side="left")
                tk.Label(row, text=note, bg=BG, fg=MUTED, font=FONT_MICRO).pack(
                    side="left", padx=(px(8), 0))
        # 顶栏的 MOD 状态筹码
        if hasattr(self, "head_chip_mod"):
            if self.mod_root:
                self.head_chip_mod.config(text="MOD 已连接", fg=SUCCESS,
                                          highlightbackground=EDGE)
            else:
                self.head_chip_mod.config(text="MOD 未找到", fg=DANGER,
                                          highlightbackground=DANGER_FILL)
        self._env_bad = bool(bad)
        self._refresh_start_action()

    def _toggle_env(self):
        """环境的逐项清单：默认收起（平时不需要看，坏的时候才展开）"""
        self._env_open = not getattr(self, "_env_open", False)
        try:
            if self._env_open:
                self.env_box.pack(fill="x", pady=(px(10), px(4)))
                self.b_env_more.config(text="收起 ▴")
            else:
                self.env_box.pack_forget()
                self.b_env_more.config(text="逐项详情 ▸")
        except Exception:
            pass

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
            # 2026-10-23：登记完当场自检 —— 本体如果已经被随机过，这份"原始"是错的，
            # 不拦住的话以后每次写入都会整批对不上（实测 766/766），玩家无从下手。
            if done:
                _reg_new = os.path.join(bdir, [n for n in done if n.startswith("regulation.bin.orig_")][0])
                try:
                    if ap not in sys.path:
                        sys.path.insert(0, ap)
                    import native_apply as _na
                    _pr = _na.pristine_probe(_reg_new)
                except Exception:
                    _pr = {"rate": None}
                if _pr.get("rate") is not None and _pr["rate"] < 0.97:
                    for n in done:                      # 这份不能留：它会把写入永远卡死
                        try:
                            os.remove(os.path.join(bdir, n))
                        except OSError:
                            pass
                    messagebox.showerror(
                        "这份不是原始版，没登记",
                        "本体里的物品数据已经被随机过了（%d/%d 个格子与工具自带的快照不符）。\n\n"
                        "把这种文件当「原始」登记下来，之后每次写入都会被写前复核拦下。\n\n"
                        "怎么修：把法魂 mod **原版**的 mod\\regulation.bin 放回本体（重装那个 MOD，"
                        "或换成你留的原版文件），再点「补一份原始备份」。"
                        % (_pr.get("match", 0), _pr.get("checked", 0)))
                    self.refresh_env()
                    return
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
            r["lbl"].config(style="Gold.TLabel")
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
                self.lbl_coh.config(style="Num.TLabel" if has_mix else "Hint.TLabel")
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

    # ── 唯一入口：按勾选的随机类型决定这次随机什么（2026-10-23）──
    def _start_kinds(self):
        """这次要随机哪些类型 —— 两个页签的启用勾就是「要不要随机它」"""
        item = bool(getattr(self, "item_on", tk.BooleanVar(value=True)).get())
        enemy = bool(getattr(self, "ev1_on", tk.BooleanVar(value=True)).get())
        return item, enemy

    def _refresh_start_action(self, *_a):
        """主按钮文案随勾选变：物品 / 敌人 / 物品和敌人；都关着就禁用

        参考实现只有一个 Randomize 按钮：做什么由上面的勾选决定，人不用记
        "先点 ① 再点 ②"这种流程。
        """
        if not hasattr(self, "b_start"):
            return
        item, enemy = self._start_kinds()
        if item and enemy:
            txt, tip = "开始随机物品和敌人", "一次写入：物品 + 敌人同一层"
        elif item:
            txt, tip = "开始随机物品", "生成并写入方案层"
        elif enemy:
            txt, tip = "开始随机敌人", "生成并写入方案层"
        else:
            txt, tip = "开始随机（先勾选类型）", "两个页签都取消勾了"
        busy = (getattr(self, "_generating", False)
                or getattr(self, "_deploying", False)
                or getattr(self, "_ev1_busy", False))
        ok = (item or enemy) and not busy and not getattr(self, "_env_bad", False)
        try:
            self.b_start.config(text=txt, state=("normal" if ok else "disabled"))
            if hasattr(self, "start_hint"):
                self.start_hint.config(text=tip)
        except tk.TclError:
            pass

    def start_randomize(self):
        """唯一的开始入口：按勾选决定随机哪些类型，然后生成 + 写入

        * 只勾物品 → 生成物品方案并写入（默认只进方案层）
        * 只勾敌人 → 生成敌人 v1 方案层
        * 两个都勾 → 先生成物品方案，之后一次写入物品 + 敌人（同一层）
        """
        item, enemy = self._start_kinds()
        if not (item or enemy):
            messagebox.showinfo("都关着", "「职业物品随机」和「敌人随机」两个页签都没勾。\n"
                                          "先勾一个要随机的类型再点开始。")
            return
        if (getattr(self, "_generating", False) or getattr(self, "_deploying", False)
                or getattr(self, "_ev1_busy", False)):
            return
        if not item:
            self._pending_start = None
            self.log("[开始] 这次只随机敌人（只存方案库，不写盘）")
            self._save_enemy_to_library()
            return
        if not WORKSPACE:
            messagebox.showerror("找不到游戏目录", "请把本程序放到 随机mod 目录（或其子目录）下再运行。")
            return
        if not [d for d, v in self.doms.items() if v.get()]:
            messagebox.showinfo("还没选随机项目", "请至少勾选一个随机项目（卢恩 / 护甲 / 装备）。")
            return
        self._pending_start = ("combined" if enemy else "item")
        self.log("[开始] 目标：" + ("物品和敌人（先生成，再存方案库）"
                                    if enemy else "只随机物品（生成后存方案库）"))
        self._refresh_start_action()
        self.generate()

    def _save_started_to_library(self, mode):
        """生成完之后：只存方案库（不写盘、不挂载）—— 覆盖层等开玩时再按需生成

        2026-10-23 作者定的流程：随机 = 造一个方案；玩 = 到方案库选它，
        启动器生成覆盖层 → 换档 → 开局。法魂本体永远不参与。
        """
        pl = self._lib_mod()
        if not pl:
            return
        if not self.plan:
            self.status.set("生成完了，但没有方案可存（这次不写盘）")
            return
        cfg = dict(self.cfg or {})
        kind = "物品+敌人" if mode == "combined" else "物品"
        if mode == "combined":
            cfg["enemy_v1"] = {"on": True, "seed": self._ev1_seed_value(),
                               "options": self._ev1_options()}
        name = "%s · 种子 %s · %s" % (kind, cfg.get("seed", "?"),
                                     time.strftime("%m-%d %H:%M"))
        try:
            m = pl.save_plan(self.plan, name, cfg=cfg, seed=cfg.get("seed"),
                             kind=("both" if mode == "combined" else "item"))
        except Exception as e:
            self.log("存进方案库失败：" + str(e))
            self.status.set("生成好了，但存方案库失败：%s" % (e,))
            return
        self.log("已存进方案库：%s（%d/%d 行）" % (m["name"], m["changed"], m["rows"]))
        self._after_saved_to_library(m)

    def _save_enemy_to_library(self):
        """只随机敌人：只把敌人设置存成一个方案（不写盘、不建层）"""
        pl = self._lib_mod()
        if not pl:
            return
        seed = self._ev1_seed_value()
        opts = self._ev1_options()
        cfg = {"enemy_v1": {"on": True, "seed": seed, "options": opts},
               "sync_guide": True}
        name = "敌人 · 种子 %s · %s" % (seed, time.strftime("%m-%d %H:%M"))
        try:
            m = pl.save_plan([], name, cfg=cfg, seed=seed, kind="enemy")
        except Exception as e:
            self.log("存进方案库失败：" + str(e))
            self.status.set("存方案库失败：%s" % (e,))
            return
        self.log("已存进方案库：%s（敌人方案，开玩时再生成覆盖层）" % m["name"])
        self._after_saved_to_library(m)

    def _after_saved_to_library(self, m):
        """存好之后：跳到方案库、选中它，把下一步说清楚"""
        self.nb.select(self.page_lib)
        try:
            self._lib_refresh(keep=m.get("id"))
        except Exception:
            pass
        _tip = ("✓ 已存进方案库：%s —— 双击它就开始玩"
                "（第一次会先生成覆盖层，不写法魂本体）" % m.get("name"))
        self.status.set(_tip)
        self._lib_toast(_tip)
        self._refresh_start_action()

    def _goto_library(self):
        self.nb.select(self.page_lib)

    def _start_gen_ok(self, ok):
        """生成结果回来：成功 → 存方案库；失败 → 把待办清掉，不留半套"""
        _pend = getattr(self, "_pending_start", None)
        self._pending_start = None
        self._generating = False
        self._refresh_start_action()
        if not ok:
            if _pend:
                self.status.set("生成失败：这次没有保存（改完设置再点开始）")
            return
        if _pend:
            self._save_started_to_library(_pend)

    def generate(self):
        if not WORKSPACE:
            messagebox.showerror("找不到游戏目录", "请把本程序放到 随机mod 目录（或其子目录）下再运行。")
            return
        if not bool(getattr(self, "item_on", tk.BooleanVar(value=True)).get()):
            messagebox.showinfo("物品随机已关闭",
                                "左上的「职业物品随机」页签没勾。\n"
                                "要只随机敌人：把物品页签的勾取消，再点底部的「开始随机敌人」。")
            return
        if bool(getattr(self, "reroll_seed", tk.BooleanVar(value=False)).get()):
            self._dice()
        if not [d for d, v in self.doms.items() if v.get()]:
            messagebox.showinfo("还没选随机项目", "请至少勾选一个随机项目（卢恩 / 护甲 / 装备）。")
            return
        self._generating = True
        self._refresh_start_action()
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
                try:
                    _ev = str(getattr(self.engine, "ENGINE_VERSION", "") or "1.1.0")
                    self.q.put(("head_engine", _ev))     # 界面更新只在主线程做
                except Exception:
                    pass
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
            self.q.put(("gen_ok", True))
            self.q.put(("status", f"生成完成（种子 {seed}）"))
        except Exception as e:
            import traceback
            self.log("出错：" + traceback.format_exc(limit=3))
            self.q.put(("gen_ok", False))
            self.q.put(("status", f"失败：{e}"))
        finally:
            self.q.put(("done", None))

    def export(self):
        if not self.plan:
            messagebox.showinfo("还没生成", "先点底部的「开始随机…」。")
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
        if not bool(getattr(self, "item_on", tk.BooleanVar(value=True)).get()):
            messagebox.showinfo("物品随机已关闭",
                                "「职业物品随机」页签没勾，这次没有物品方案可写。\n"
                                "要只随机敌人：把物品页签的勾取消，再点底部的「开始随机敌人」。")
            return
        if not self.plan:
            messagebox.showinfo("还没生成", "先点底部的「开始随机…」。")
            return
        if self._deploy_busy():
            return
        # 确认框的清单**按当前配置现算**（2026-10-17 改）：
        # 以前是写死的"物品与掉落 / 说明书文本"，于是"敌人随机没开"这件事
        # 在点写入的那一刻完全看不出来 —— 作者就这么白跑了一趟。
        # 2026-10-21：旧敌人管线（v0）已停用 —— 敌人随机改由「敌人随机」页顶部的
        # v1 卡片单独部署（它有自己的写盘程序与方案层）。主部署若再带旧 enemy_cfg，
        # 会把那套失败管线重跑一遍（半换、错位），所以这里恒为关。
        _e = {"on": False}
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
                _extra.append("血条名/BGM" if _e.get("emevd", True) else "血条名/BGM 不跟")
            else:
                _extra.append("只换数值")
            if not _e.get("use_arena", True):
                _extra.append("不看场地档")
            if _e.get("allow_unkillable"):
                _extra.append("连打不死的也换")
            if _e.get("source") == "new":
                _extra.append("只法魂")
            _lines.append("  · 敌人：" + (_en or "（没给比例）") + ("（" + "·".join(_extra) + "）" if _extra else ""))
        else:
            _lines.append("  · 敌人随机：不在这次写入里（请用「敌人随机」页顶部的 v1 卡片单独部署）")
        _lines.append("  · 说明书文本：" + ("会同步" if self.cfg.get("sync_guide", True) else "不动"))
        _ovl = bool(getattr(self, "ev1_overlay", None) and self.ev1_overlay.get())
        _lines.append("  · 写入方式：" + ("**只生成方案层**（法魂本体不改）" if _ovl
                                       else "直接改法魂本体（旧行为）"))
        _lines.append("  · 写完后**自动挂载**这个方案层（不用再点别的；关掉游戏重进才生效）")
        _warn = ("\n\n注意：敌人随机 v1 是**另一条独立写盘路径**（它自己一套方案层）。"
                 "方案层一次只能挂一个 —— 如果之前部署过敌人 v1，这次只写物品会把它顶掉。"
                 "两个页签都勾着时，底部那一个按钮会一次写完物品 + 敌人（同一层）。")
        _ask = ("会按下面的内容生成一个方案层（法魂本体一个字节都不改）：\n" if _ovl
                else "会把下面的内容写进游戏文件：\n")
        if not messagebox.askyesno("确认写入游戏（这次会写这些）",
                                   _ask + "\n".join(_lines) + _warn
                                   + ("\n\n随时可以点「切回法魂本体」把 Plan= 清掉。开始？" if _ovl
                                      else "\n\n写入前会自动备份，随时可以点「还原成原始」。开始？")):
            return
        plan = self.export()
        sync = bool(self.cfg.get("sync_guide", True))
        self._deploying = True
        self.log(("生成方案层中…（本体不动）" if _ovl else "写入中…") + ('（含说明书）' if sync else '（不改说明书）'))
        self.log("写完后会**自动挂载**这次的方案层；挂载生效要关掉游戏重进（regulation 只在启动时读）")
        self.q.put(("status", "写入中…"))
        _fp = self._plan_fp()
        threading.Thread(target=self._deploy_worker, args=(plan, sync, False, _fp),
                         kwargs={"overlay": _ovl},
                         daemon=True).start()

    def _plan_fp(self):
        """当前主界面这套方案的指纹（写入收据里会记上它，方案库就能显示"写入过几次"）"""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import planlib
            return planlib.fingerprint(self.plan) if self.plan else None
        except Exception:
            return None

    def _deploy_worker(self, plan, sync_guide, lib=False, fingerprint=None, pid=None,
                        enemy_merge=None, overlay=False):
        """lib=True 时（从方案库写入）额外把进度/结果送回方案库那扇窗口。

        enemy_merge 不为空时 = 一次写入：物品先写进本体，再从这份本体构建敌人 v1 层，
        只挂这一个同时含物品与敌人的层（交给 native_deploy.deploy 的 enemy_merge 参数）。

        为什么要有这个参数：方案库窗口盖在主界面上，而进度本来只写主界面的
        状态栏和日志 —— 玩家在方案库这边只看到一句"正在写入…"，写入其实早就
        成功了也看不出来（2026-10-14 实测：收据都落盘了，界面还停在"写入中"）。
        """
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import native_deploy
            if enemy_merge:
                # 一次写入：先把敌人计划算出来，等物品写进本体后再由 native_deploy 建层
                import enemy_plan as EP
                enemy_merge = dict(enemy_merge)
                if not enemy_merge.get("plan_path"):
                    self.log("[合并] 正在生成敌人计划（种子 %s）…" % enemy_merge.get("seed"))
                    _plan = EP.build_plan(EP.load_data(),
                                          enemy_merge.get("options") or {},
                                          enemy_merge.get("seed") or 1)
                    _pp = os.path.join(WORKSPACE, "investigation", "enemy_plan.json")
                    EP.dump_plan(_plan, _pp)
                    enemy_merge["plan_path"] = _pp
                    self.log("[合并] 敌人计划已生成：%s" % _pp)
            # 方案层标签与信息：让"这次随机"以后能作为一个可切换的覆盖层存在
            _c = self.cfg or {}
            # 2026-10-23：旧敌人管线（v0）已整块移除。这条「物品部署」只写物品；
            # 敌人 v1 走自己的卡片；部署入口是底栏的「开始随机…」（组合时一次写入）。
            _flags = ["物品"]
            if _c.get("sync_guide"):
                _flags.append("说明书")
            _label = "%s_种子%s_%s" % (time.strftime("%Y%m%d_%H%M"), _c.get("seed", "?"),
                                       "+".join(_flags))
            _meta = {"种子": _c.get("seed"),
                     "随机项目": "、".join(_c.get("domains") or []),
                     "敌人随机": ("与物品同层（一次写入）" if enemy_merge
                                 else "不在这条路径（v1 卡片单独部署）"),
                     "说明书同步": "开" if _c.get("sync_guide") else "关",
                     "指纹": (fingerprint or "")[:16]}
            rec = native_deploy.deploy(plan, sync_guide=sync_guide, log=self.log,
                                       fingerprint=fingerprint,
                                       enemy_cfg=None,
                                       plan_label=None if enemy_merge else _label,
                                       plan_meta=_meta,
                                       enemy_merge=enemy_merge, overlay=overlay)
            self.log(("方案层生成完成 [OK] " if overlay else "写入完成 [OK] ")
                     + str(rec.get("verify"))
                     + ("　工作副本：" + os.path.basename((rec.get("work") or {}).get("reg") or "")
                        if overlay else ""))
            if enemy_merge:
                _em = rec.get("enemy_merge") or {}
                self._last_enemy_v1_layer = _em.get("label") or enemy_merge.get("label") or ""
                self.log("[合并] 敌人 v1 已进同一个层：%s" % self._last_enemy_v1_layer)
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
            if enemy_merge:
                _msg = (("✓ 一次写入完成：物品 + 敌人 v1 已进同一个层（%s），法魂本体一个字节都没改。"
                         if overlay else
                         "✓ 一次写入完成：物品 + 敌人 v1 已进同一个层（%s）。")
                        % (self._last_enemy_v1_layer or "")) + "关掉游戏重进就生效。"
                self.q.put(("status", _msg))
                self.q.put(("ev1_page", (_msg, False)))
                if lib:
                    self.q.put(("lib", (_msg, False)))
            else:
                _done = ("✓ 方案层已就绪（法魂本体未改）—— 到「方案库」点「用这个方案玩」就行"
                         if overlay else "写入完成 ✓ 可以进游戏了")
                self.q.put(("status", _done + _lay_msg))
                if lib:
                    self.q.put(("lib", (_done + _lay_msg, False)))
        except Exception as e:
            import traceback
            self.log("写入出错：" + traceback.format_exc(limit=4))
            _msg = f"写入失败：{e}"
            # 2026-10-23：写前复核整批失败，最常见的原因其实是"工作区里的原始备份不是原始版"
            # （便携目录第一次运行时，把已经随机过的本体登记成了"原始"）。当场诊断，
            # 别让人对着"换过 MOD 版本？"猜。
            try:
                if "写前复核" in str(e):
                    sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
                    import native_deploy as _nd, native_apply as _na
                    _orig = _nd.find_original("regulation.bin.orig_*")
                    _pr = _na.pristine_probe(_orig)
                    if _pr.get("rate") is not None and _pr["rate"] < 0.97:
                        self.log(
                            "诊断：工作区里的「原始备份」本身就不像原始版（%d/%d 个格子与工具快照不符）。\n"
                            "　　　写入是拿它当基底的，所以计划里每条都对不上 —— 不是种子的问题。\n"
                            "　　　处理：把法魂 mod 原版里的 regulation.bin 放回本体，再点「补一份原始备份」。"
                            % (_pr.get("match", 0), _pr.get("checked", 0)))
                        _msg += "（诊断见日志：工作区里的原始备份不是原始版）"
            except Exception:
                pass
            self.q.put(("status", _msg))
            if enemy_merge:
                self.q.put(("ev1_page", ("✗ 一次写入失败：" + str(e)[:220], True)))
            if lib:
                self.q.put(("lib", (f"写入失败：{e}", True)))
        finally:
            self.q.put(("deploying", False))
            if enemy_merge:
                self.q.put(("ev1_page_done", None))

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
        _vals = list(self.cb_mode.cget("values"))
        if len(_vals) > 1:
            self.mode.set(_vals[1] if c.get("cross_domain") is False else _vals[0])
        self._combo_hint()
        self._coh_hint()
        self.log(f"设置已读入：{os.path.basename(p)}（点「开始随机…」生效）")

    def rollback(self):
        if not messagebox.askyesno("还原成原始",
                                   "把物品与说明书都恢复成游戏原本的样子？\n（你之前写入的随机结果会被撤销）\n\n"
                                   "注意：如果当前挂着一个方案层（Plan=），这次也会**切回法魂本体**（删掉 Plan= 行），\n"
                                   "否则下次启动仍会加载覆盖层里的敌人数值/地图。"):
            return
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
            import shutil
            import native_deploy
            import plan_layer
            reg = os.path.join(native_deploy.MOD, "mod", "regulation.bin")
            msg = os.path.join(native_deploy.MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
            shutil.copy2(native_deploy.find_original("regulation.bin.orig_*"), reg)
            shutil.copy2(native_deploy.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), msg)
            _p = plan_layer.clear_plan()
            if _p.get("changed"):
                self.log("已切回法魂本体（删掉 YAFSML.ini 里的 Plan= 行；备份 "
                         + os.path.basename(_p.get("backup") or "") + "）")
            self.log("已还原成原始版 [OK]")
            self.q.put(("status", "已还原成原始版 ✓" + ("（并切回本体）" if _p.get("changed") else "")))
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
                (BG, BG_ELEV, PANEL, PANEL_2, FIELD, EDGE, EDGE_SOFT, FG, SUB, MUTED,
                 GOLD, GOLD_LT, GOLD_DIM, DANGER, DANGER_FILL, SUCCESS, SEL_BG,
                 BTN_HOVER, BTN_PRESS, HEAD_BG, DISABLED, WHITE, INK)}

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
SETTINGS_WIDGETS = ("b_start", "lbl_env", "cb_mode", "lbl_combo", "lbl_coh", "lbl_cohtxt",
                    "checks", "tbl", "txt", "summary", "status", "adv", "detail",
                    "doms", "mode", "seed", "coherence", "sets", "guide",
                    "shops")


# 对比度门槛（WCAG 比例）。作者反馈过"字很不明显"，所以把它做成可测的门槛：
# 正文要 ≥10，次文字（说明 / 字段名）≥8，危险色 ≥4.5，禁用态 ≥3.5。
CONTRAST_REQUIREMENTS = (
    ("主文字 / 窗口底", FG, BG, 10.0),
    ("次文字 / 窗口底", SUB, BG, 8.0),
    ("次文字 / 面板底", SUB, PANEL, 7.0),
    ("三级文字 / 窗口底", MUTED, BG, 4.5),
    ("金标题 / 窗口底", GOLD, BG, 6.0),
    ("危险色 / 面板底", DANGER, PANEL, 4.5),
    ("禁用文字 / 面板底", DISABLED, PANEL, 3.5),
    ("金色主按钮文字 / 金底", INK, GOLD, 4.5),
    ("金色主按钮（禁用）/ 输入框底", DISABLED, FIELD, 4.0),
    ("选中行文字 / 选中底", WHITE, SEL_BG, 8.0),
    ("顶栏次文字 / 顶栏底", SUB, BG_ELEV, 7.0),
    ("就绪色 / 窗口底", SUCCESS, BG, 4.5),
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
               ("doms", "mode", "switches", "rows", "detail", "pools", "layer")}
        ck("详细信息：随机项目 / 混合方式 / 开关 都写出来了",
           "卢恩" in _lk["doms"] and ("混" in _lk["mode"] or "各自" in _lk["mode"])
           and "整套法祷一起换" in _lk["switches"],
           f"{_lk['doms']}｜{_lk['mode']}｜{_lk['switches']}")
        ck("详细信息：改动行带跨类计数 + 分类明细 + 池子分布",
           "行" in _lk["rows"] and _lk["detail"] != "—" and "个（" in _lk["pools"],
           f"{_lk['rows']}｜{_lk['detail']}｜{_lk['pools']}")
        ck("详细信息：覆盖层状态写清了（没生成 / 已生成 / 要重建）",
           any(x in _lk["layer"] for x in ("还没生成", "已生成", "设置改过")),
           f"覆盖层={_lk['layer']!r}")
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
           _c_detail is not None and _canvas_of(app.lib_btns["launch"]) is None
           and _canvas_of(app.lib_toast) is None,
           f"标题在滚动区={_c_detail is not None}｜按钮在滚动区={_canvas_of(app.lib_btns['launch']) is not None}")
        _geo0 = root.geometry()
        root.geometry("1100x420"); root.update()
        _y0 = _c_detail.yview() if _c_detail else (0, 0)
        if _c_detail:
            _c_detail.yview_scroll(3, "units")
        root.update()
        _y1 = _c_detail.yview() if _c_detail else (0, 0)
        ck("窗口缩小时详情真的能滚（滚完按钮还在）",
           _c_detail is not None and (_y1[0] > _y0[0] or _y1[1] < 1.0)
           and bool(app.lib_btns["launch"].winfo_ismapped()),
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
        ck("确认框只出现在删除这种破坏动作上（不再有「写入游戏」确认）",
           any("删掉这个方案" in x for x in asked)
           and not any("写入游戏" in x for x in asked), "；".join(asked))
        # 敌人随机 v1（新管线，2026-10-21 M5）：控件存在 + 选项进得去
        ck("敌人页 v1 卡片在（池 / 种子 / 比例 / 预览 / 挂载）",
           all(hasattr(app, _n) for _n in ("ev1_pools", "ev1_seed", "ev1_mult",
                                           "ev1_hint", "enemy_v1_preview",
                                           "enemy_v1_play", "enemy_v1_revert")),
           "缺属性")
        ck("唯一的开始按钮在底栏，文案跟着勾选走",
           hasattr(app, "b_start") and hasattr(app, "start_randomize")
           and "开始随机" in str(app.b_start.cget("text")),
           f"b_start={getattr(app, 'b_start', None)}")
        ck("敌人页 v1：四个池都在（传送门 / 钥石 / 追忆 / 圣龛）",
           set(getattr(app, "ev1_pools", {})) == {"waygate", "keystone", "remembrance", "reliquary"},
           str(sorted(getattr(app, "ev1_pools", {}).keys())))
        ck("敌人页 v1：默认只进方案层（法魂本体不改）",
           hasattr(app, "ev1_overlay") and bool(app.ev1_overlay.get()),
           "缺 ev1_overlay 或默认不是 True")
        _o = app._ev1_options()
        ck("敌人页 v1：池开关与比例进了 options",
           set(_o.get("pools", {})) == {"waygate", "keystone", "remembrance", "reliquary"}
           and "multiplier" in (_o.get("rates") or {}), repr(_o))
        ck("敌人页 v1：多阶段位置默认也换、身份也能当来源，且没有开关（constraints 恒真）",
           (not hasattr(app, "ev1_mp")) and (not hasattr(app, "ev1_mp_src"))
           and (_o.get("constraints") or {}).get("multiphase_swap") is True
           and (_o.get("constraints") or {}).get("multiphase_as_source") is True, repr(_o))

        # ── 方案库「用这个方案玩」+ 每方案独立存档（2026-10-23）──
        ck("方案库详情：多出「存档」两行（方案存档 / 游戏存档）",
           set(app.lib_vals) >= {"save", "live"}, str(sorted(app.lib_vals)))
        _gl = app._lib_gamemod(quiet=True)
        ck("存档模块能加载（gamelib）", _gl is not None, "import gamelib 失败")
        if _gl:
            ck("存档模块该有的都在（启动/换档/回存/自查）",
               all(hasattr(_gl, _n) for _n in ("launch", "prepare_save", "finish", "recover",
                                               "bank_status", "bank_save", "status",
                                               "game_running")),
               "缺函数")
            try:
                _nm = _gl.save_names()
            except Exception:
                _nm = {"main": "", "bak": ""}
            ck("换档认 YAFSML 的存档改名（.cnv，法魂包默认）且连 .bak 一起换",
               hasattr(_gl, "save_names") and _gl.BANK_DIRNAME == "存档库"
               and (not _nm["main"] or _nm["bak"] == _nm["main"] + ".bak"), str(_nm))
            ck("切回法魂本体会换档（不只是清 Plan=）",
               hasattr(_gl, "switch_to_body"), "缺 switch_to_body")
            ck("查进程不再起 tasklist 黑框（Toolhelp 快照 + 隐藏窗口）",
               hasattr(_gl, "_enum_game_pids") and hasattr(_gl, "_CREATE_NO_WINDOW"),
               "缺 _enum_game_pids/_CREATE_NO_WINDOW")
            ck("游戏进程判定会跳过已退出的残留（僵尸壳），动作口径一致",
               hasattr(_gl, "_pid_is_gone") and hasattr(_gl, "zombie_pids")
               and _gl.game_running() == bool(_gl.game_pids()),
               "缺 _pid_is_gone/zombie_pids 或口径不一致")
        ck("详情面板把存档时间摊出来了（不是空字符串）",
           bool(str(app.lib_vals["save"].cget("text")).strip()), repr(app.lib_vals["save"].cget("text")))

        # ── 方案层 ≠ 法魂包（2026-10-23：从层目录双击启动 bat 时报「没有 yafsml\」）──
        _fakepack = os.path.join(tmp, "假法魂包")
        _fakelayer = os.path.join(_fakepack, "方案", "测试层")
        os.makedirs(os.path.join(_fakelayer, "mod"))
        os.makedirs(os.path.join(_fakepack, "mod"), exist_ok=True)
        os.makedirs(os.path.join(_fakepack, "yafsml"), exist_ok=True)
        open(os.path.join(_fakelayer, "mod", "regulation.bin"), "wb").write(b"L")
        open(os.path.join(_fakepack, "mod", "regulation.bin"), "wb").write(b"B")
        ck("方案层目录不会被当成法魂包本体（层里也有 mod/regulation.bin）",
           _is_layer_dir(_fakelayer) and not _is_layer_dir(_fakepack),
           "layer=%r pack=%r" % (_is_layer_dir(_fakelayer), _is_layer_dir(_fakepack)))
        ck("从层目录能反推出法魂包根（双击 bat 时 cwd 就是层根）",
           _pack_of_layer(_fakelayer) == os.path.abspath(_fakepack),
           repr(_pack_of_layer(_fakelayer)))
        try:
            app._apply_path()
            import modpaths as _mp
            ck("modpaths 也不把方案层当 MOD 根（环境变量被层占住时仍能找到包）",
               _mp.is_layer_root(_fakelayer) and not _mp.is_mod_root(_fakelayer),
               "is_mod_root(layer)=%r" % _mp.is_mod_root(_fakelayer))
        except Exception as _exc:
            ck("modpaths 也不把方案层当 MOD 根（环境变量被层占住时仍能找到包）",
               False, repr(_exc))

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

    # ── 敌人随机 v1（2026-10-23 重排后）：只剩一套控件，旧管线表单已整块删除 ──
    _v0 = [a for a in ("enemy_on", "enemy_pools", "enemy_source", "enemy_hint",
                       "enemy_hp_scale_on", "enemy_hp_scale", "enemy_visual",
                       "enemy_emevd", "enemy_keep_unkillable", "enemy_same_type",
                       "enemy_seed", "enemy_seed_sep", "enemy_type_tree",
                       "enemy_cls_rates", "enemy_hint", "enemy_sub")
          if hasattr(app, a)]
    ck("敌人页：旧管线（v0）的死表单已删干净", not _v0, f"残留={_v0}")
    _v1 = ("ev1_pools", "ev1_mult", "ev1_bar_names", "ev1_night",
           "ev1_ignore_size", "ev1_bgm", "ev1_soul", "ev1_rainbow", "ev1_scale",
           "ev1_oops", "ev1_ons", "ev1_seed", "ev1_overlay", "ev1_hint")
    ck("敌人页：v1 控件齐（特殊池 4 个 + 8 个开关 + 3 个滑块 + 种子）",
       all(hasattr(app, a) for a in _v1), "少控件")
    ck("敌人页：不再有自己的生成按钮（唯一入口是底栏的开始随机）",
       (not hasattr(app, "b_ev1_apply"))
       and hasattr(app, "b_ev1_preview")
       and str(app.b_ev1_preview.cget("style")) == "Secondary.TButton",
       f"b_ev1_apply={getattr(app, 'b_ev1_apply', None)}")
    ck("敌人页：右列就是挂载状态 + 两个动作（用这个方案玩 / 切回本体）",
       all(hasattr(app, a) for a in ("enemy_page_hint", "b_enemy_play", "b_enemy_revert")),
       "少控件")
    _txts = []
    def _walktext(w, acc):
        for _c in w.winfo_children():
            try:
                acc.append(str(_c.cget("text")))
            except Exception:
                pass
            _walktext(_c, acc)
        return acc
    _txts = _walktext(app.page_enemy, [])
    ck("敌人页：重复的部署入口与旧规则说明都清掉了",
       (not any("只写入敌人" in t for t in _txts))
       and (not any("旧管线" in t for t in _txts))
       and (not any("当前生效的规则" in t for t in _txts)),
       f"残留={[t[:16] for t in _txts if '只写入敌人' in t or '旧管线' in t][:4]}")
    ck("物品页只写物品：_collect 不再带 enemy 键",
       "enemy" not in app._collect(), f"keys={sorted(app._collect().keys())}")
    _o0 = app._ev1_options()
    ck("v1：默认四个特殊池全开、比例 100%、血量倍率 1.0",
       set(_o0.get("pools") or {}) == {"waygate", "keystone", "remembrance", "reliquary"}
       and all(_o0["pools"].values())
       and abs(_o0["rates"]["multiplier"] - 1.0) < 1e-6
       and abs(_o0["scaling"]["hp"] - 1.0) < 1e-6,
       f"{_o0.get('pools')}")
    ck("v1：安全默认值（血条名开、多阶段常开且无开关、夜间关、忽略体型关、纯方案层开）",
       app.ev1_bar_names.get() is True
       and (not hasattr(app, "ev1_mp")) and (not hasattr(app, "ev1_mp_src"))
       and app._ev1_options()["constraints"]["multiphase_swap"] is True
       and app._ev1_options()["constraints"]["multiphase_as_source"] is True
       and app.ev1_night.get() is False and app.ev1_ignore_size.get() is False
       and app.ev1_overlay.get() is True, "默认值不对")
    app.ev1_mult.set(0.4); app.ev1_scale.set(1.5); root.update()
    _o1 = app._ev1_options()
    ck("v1：比例 / 血量倍率进了选项",
       abs(_o1["rates"]["multiplier"] - 0.4) < 1e-6
       and abs(_o1["scaling"]["hp"] - 1.5) < 1e-6, f"{_o1.get('scaling')}")
    app.ev1_pools["waygate"].set(False); root.update()
    _o2 = app._ev1_options()
    ck("v1：关一个特殊池如实进选项；多阶段常开",
       _o2["pools"]["waygate"] is False
       and _o2["constraints"]["multiphase_swap"] is True, f"{_o2.get('constraints')}")
    app.ev1_oops.set(ENEMY_CLASS_CN["Boss"]); root.update()
    ck("v1：全替换为某一类 → oops_all 带类别键",
       app._ev1_options().get("oops_all") == "Boss",
       f"{app._ev1_options().get('oops_all')}")
    app.ev1_oops.set("不启用（按规则表）")
    app.ev1_pools["waygate"].set(True)
    app.ev1_mult.set(1.0); app.ev1_scale.set(1.0)
    app._ev1_status_refresh(); root.update()
    _ow = app.outer_what.cget("text")
    ck("底栏：摘要同时写物品与敌人（敌人按 v1 口径：几个特殊池 + 比例）",
       "物品：" in _ow and "敌人：" in _ow and "特殊池" in _ow, repr(_ow[:90]))
    for _k, _v in app.ev1_pools.items():
        _v.set(False)
    app._ev1_status_refresh(); root.update()
    ck("底栏：一个特殊池都不勾 ⇒ 敌人写“关着”",
       "敌人：关着" in app.outer_what.cget("text"),
       repr(app.outer_what.cget("text")[:80]))
    for _k, _v in app.ev1_pools.items():
        _v.set(True)
    app._ev1_status_refresh(); root.update()
    ck("v1：状态行写出了挂载状态", bool(str(app.enemy_page_hint.cget("text")).strip()),
       repr(app.enemy_page_hint.cget("text")[:60]))
    ck("v1：动作函数都在（开始随机 / 预览 / 用这个方案玩）",
       all(hasattr(app, a) for a in ("start_randomize", "enemy_v1_preview",
                                     "enemy_v1_play", "_play_layer")), "缺函数")
    ck("v1：层目录探针不抛异常（有就返回路径，没有就空串）",
       isinstance(app._ev1_layer_dir(), str), repr(app._ev1_layer_dir())[:80])

    # ── 方案层：库里的「用这个方案玩」按钮（只有生成过覆盖层的方案才亮）──
    ck("方案层：详情面板有这个按钮",
       "launch" in getattr(app, "lib_btns", {}),
       f"{sorted(getattr(app, 'lib_btns', {}))}")
    _pid_t = b["id"]
    planlib.set_meta(_pid_t, layer_dir="", built={})   # 先清成没有覆盖层
    app._lib_refresh(keep=_pid_t)
    app.lib_tree.selection_set(_pid_t)
    app._lib_on_select()
    root.update()
    _no_layer = str(app.lib_btns["launch"].cget("state"))
    _no_txt = str(app.lib_vals["layer"].cget("text"))
    _fake_layer = os.path.join(tmp, "假方案层")
    os.makedirs(os.path.join(_fake_layer, "mod"), exist_ok=True)
    planlib.set_meta(_pid_t, layer_dir=_fake_layer)
    app._lib_refresh(keep=_pid_t)
    app.lib_tree.selection_set(_pid_t)
    app._lib_on_select()
    root.update()
    _has_layer = str(app.lib_btns["launch"].cget("state"))
    ck("开玩：没有覆盖层也能点（点一下按需生成），详情如实写还没生成",
       _no_layer == "normal" and _has_layer == "normal" and "还没生成" in _no_txt,
       f"没层={_no_layer!r}｜有层={_has_layer!r}｜状态={_no_txt!r}")

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

    # 方案库开玩（2026-10-23 第二版流程）：界面上不再有「写入游戏」；
    # 点「用这个方案玩」= 没层就后台生成覆盖层，生成完才换档 + 起游戏。
    called = {}

    class _FakeGL:
        running = False
        kills = []

        class GameError(Exception):
            pass

        class NeedsNewSave(Exception):
            pass

        @staticmethod
        def game_running():
            return _FakeGL.running

        @staticmethod
        def plan_label(ld):
            return os.path.basename(str(ld).rstrip("\\/"))

        @staticmethod
        def launch(*a, **k):
            if _FakeGL.running and not k.get("kill_running"):
                raise _FakeGL.GameError(
                    "游戏正在运行 —— 先退出游戏再切方案（运行中换档会写坏存档）")
            if k.get("kill_running"):
                _FakeGL.kills.append(True)
                _FakeGL.running = False
            return {"started": time.time()}

        @staticmethod
        def current_label():
            return None

        @staticmethod
        def bank_status(label):
            return {"has": True}

        @staticmethod
        def live_dir():
            return ""

    _real_gl = App._lib_gamemod
    _real_build = App._lib_start_build
    _real_launch_layer = App._lib_launch_layer
    App._lib_gamemod = lambda self, quiet=False: _FakeGL
    App._lib_start_build = lambda self, pid, d, name: called.update(build=pid)
    App._lib_launch_layer = lambda self, ld, name, pid=None: called.update(layer=ld, name=name)
    try:
        app._lib_refresh(keep=b["id"])
        app.lib_tree.selection_set(b["id"])
        app._lib_on_select()
        app._lib_launch()
        ck("开玩：还没有覆盖层就去生成（不用先点写入）",
           called.get("build") == b["id"] and not called.get("layer"),
           f"build={called.get('build')!r} layer={called.get('layer')!r}")
        # 造一份已经按这版生成过的记录：再点就直接开局，不重复生成
        _ld = os.path.join(tmp, "_layer_probe")
        os.makedirs(os.path.join(_ld, "mod"), exist_ok=True)
        _doc = planlib.get_plan(b["id"])
        planlib.set_meta(b["id"], layer_dir=_ld,
                         built={"fingerprint": _doc.get("fingerprint") or "",
                                "enemy_sig": app._enemy_sig((_doc.get("cfg") or {}).get("enemy_v1")),
                                "at": time.time(), "label": "probe"})
        called.clear()
        app._lib_refresh(keep=b["id"])
        app.lib_tree.selection_set(b["id"])
        app._lib_on_select()
        app._lib_launch()
        ck("开玩：覆盖层已是最新就直接启动（换档 + 挂层由 gamelib 做）",
           called.get("layer") == _ld and not called.get("build"),
           f"layer={called.get('layer')!r} build={called.get('build')!r}")
        # 游戏开着时不再"只弹警告"：照样进启动流程 —— 由 _launch_gl 问人"自动关掉并启动"
        called.clear()
        _FakeGL.running = True
        app.lib_tree.selection_set(b["id"])
        app._lib_on_select()
        app._lib_launch()
        ck("开玩：游戏在跑也会进入启动流程（不再只是干等）",
           called.get("layer") == _ld,
           f"layer={called.get('layer')!r}")
        # 真把启动交给 gamelib：游戏在跑 → 先问 → 带 kill_running 调用（关了再开）
        _FakeGL.running = True
        _FakeGL.kills.clear()
        _r = app._launch_gl(_FakeGL, _ld)
        ck("开玩：同意自动关掉时，启动带 kill_running（关掉游戏再开）",
           bool(_r) and _FakeGL.kills == [True] and not _FakeGL.running,
           f"r={_r!r} kills={_FakeGL.kills!r} running={_FakeGL.running}")
        _seen = []
        _real_ask = messagebox.askyesno
        messagebox.askyesno = lambda t, m=None, **k: (_seen.append((str(t), str(m))), True)[1]
        try:
            _FakeGL.running = True
            _FakeGL.kills.clear()
            _r2 = app._launch_gl(_FakeGL, _ld)
        finally:
            messagebox.askyesno = _real_ask
        ck("开玩：问的话说清了会自动关掉它（不是直接强杀）",
           bool(_r2) and any("自动关掉它并启动" in str(m) for _t, m in _seen),
           f"seen={_seen!r}")
        # 人拒绝自动关掉 → 不启动，游戏原样开着
        _FakeGL.running = True
        _real_ask = messagebox.askyesno
        try:
            messagebox.askyesno = lambda *a, **k: False
            _r = app._launch_gl(_FakeGL, _ld)
        finally:
            messagebox.askyesno = _real_ask
        ck("开玩：人拒绝自动关掉 → 不启动（游戏不动）",
           _r is None and _FakeGL.running,
           f"r={_r!r} running={_FakeGL.running}")
        # 但建层不需要退出游戏：没层时照样先建
        called.clear()
        _FakeGL.running = True
        planlib.set_meta(b["id"], layer_dir="", built={})
        app._lib_refresh(keep=b["id"])
        app.lib_tree.selection_set(b["id"])
        app._lib_on_select()
        app._lib_launch()
        ck("开玩：游戏运行中也能先建覆盖层（建层不碰本体）",
           called.get("build") == b["id"] and not called.get("layer"),
           f"build={called.get('build')!r} layer={called.get('layer')!r}")
        _FakeGL.running = False
        # 方案改过（指纹变了）→ 下次开玩要重建，不能拿旧层凑合
        _doc = planlib.get_plan(b["id"])
        _doc["fingerprint"] = "changed"
        ck("开玩：方案改过就重建（旧层不凑合）", not app._lib_layer_fresh(_doc),
           f"fresh={app._lib_layer_fresh(_doc)}")
    finally:
        App._lib_gamemod = _real_gl
        App._lib_start_build = _real_build
        App._lib_launch_layer = _real_launch_layer

    # 敌人专属方案：没有物品行也能存进方案库（2026-10-23 起）
    _em = planlib.save_plan([], "只随机敌人 · 探针",
                            cfg={"enemy_v1": {"on": True, "seed": 7,
                                              "options": {"pools": {"waygate": True}}}},
                            seed=7, kind="enemy")
    ck("敌人方案：没有物品行也能存进方案库",
       _em.get("rows") == 0 and _em.get("kind") == "enemy",
       f"rows={_em.get('rows')} kind={_em.get('kind')}")
    planlib.delete_plan(_em["id"])          # 探针方案别留在库里（后面要断言空态）

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
    for want in ("用这个方案玩", "载入到设置", "改名", "收藏", "复制", "导出", "删除", "导入"):
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

    # 双击 = 用这个方案玩（成熟产品的"打开"语义；写入是破坏性动作，必须走显式按钮）
    called.clear()
    _real_launch = App._lib_launch
    App._lib_launch = lambda self: called.update(launch=True)
    try:
        kids = app.lib_tree.get_children()
        app.lib_tree.selection_set(kids[0])
        app._lib_on_select()
        ck("双击：列表上绑了双击事件", any("Double" in s for s in app.lib_tree.bind()),
           str(app.lib_tree.bind()))
        app._lib_on_dbl()
    finally:
        App._lib_launch = _real_launch
    ck("双击那一下 = 用这个方案玩（不是写入）", bool(called.get("launch")), f"{called}")
    ck("详情按钮主次：用这个方案玩是主按钮，且不再有「写入游戏」",
       str(app.lib_btns["launch"].cget("style")) == "SmallPrimary.TButton"
       and "write" not in app.lib_btns,
       f"{app.lib_btns['launch'].cget('style')} / {sorted(app.lib_btns)}")

    # 整库空掉：空状态要给"下一步干什么"的引导
    for f in os.listdir(tmp):
        if f.endswith(".json"):
            os.remove(os.path.join(tmp, f))
    app._lib_search_set("")
    ck("空库：换成引导文案", bool(app.lib_empty.winfo_manager()),
       f"empty={app.lib_empty.winfo_manager()!r}")
    ck("空库：引导去底部「开始随机…」生成",
       "开始随机" in app.lib_empty_txt.cget("text")
       and ("覆盖层" in app.lib_empty_txt.cget("text") or "双击" in app.lib_empty_txt.cget("text")),
       repr(app.lib_empty_txt.cget("text")[:40]))
    # 三页签：物品 / 敌人 / 方案库（2026-10-16 拆页）
    _tabs = [str(app.nb.tab(t, "text")).strip() for t in app.nb.tabs()]
    ck("页签：物品·敌人·方案库三页",
       len(_tabs) == 3 and all(any(w in t for t in _tabs)
                               for w in ("职业物品随机", "敌人随机", "方案库")),
       f"{_tabs}")
    # 参考实现式页签启用勾 + 底部固定条（2026-10-21 界面重塑）
    _chk_nav = [it for it in app._nav_items if it.get("check") is not None]
    ck("页签启用勾：物品与敌人各一个、方案库没有",
       len(_chk_nav) == 2 and str(_chk_nav[0]["page"]) == str(app.page_set)
       and str(_chk_nav[1]["page"]) == str(app.page_enemy),
       f"{[(str(it['page']), it['check'] is not None) for it in app._nav_items]}")
    app.item_on.set(False)
    app._refresh_item_on()
    # 隔离自检目录里没有法魂包（环境不就绪）时按钮本来就该灰：这里只看"勾选对了就该可点"
    _env_bad_was = bool(getattr(app, "_env_bad", False))
    app._env_bad = False
    app._refresh_start_action()
    root.update()
    ck("只勾敌人 ⇒ 主按钮变成「开始随机敌人」且可点",
       str(app.b_start.cget("text")) == "开始随机敌人"
       and "disabled" not in str(app.b_start.cget("state")),
       f"{app.b_start.cget('text')!r}/{app.b_start.cget('state')!r}")
    app._env_bad = _env_bad_was
    app._refresh_start_action()
    app.item_on.set(True)
    app._refresh_item_on()
    root.update()
    ck("两个都勾 ⇒ 主按钮变成「开始随机物品和敌人」",
       str(app.b_start.cget("text")) == "开始随机物品和敌人",
       repr(app.b_start.cget("text")))
    app.ev1_on.set(False)
    app._refresh_ev1_on()
    root.update()
    ck("只勾物品 ⇒ 主按钮变成「开始随机物品」、预览仍按勾选禁用",
       str(app.b_start.cget("text")) == "开始随机物品"
       and "disabled" in str(app.b_ev1_preview.cget("state")),
       f"{app.b_start.cget('text')!r}/{app.b_ev1_preview.cget('state')!r}")
    app.item_on.set(False)
    app._refresh_item_on()
    root.update()
    ck("两个都取消勾 ⇒ 主按钮禁用并提示先勾类型",
       "disabled" in str(app.b_start.cget("state"))
       and "勾选" in str(app.b_start.cget("text")),
       f"{app.b_start.cget('text')!r}/{app.b_start.cget('state')!r}")
    app.item_on.set(True); app.ev1_on.set(True)
    app._refresh_item_on(); app._refresh_ev1_on()
    root.update()
    # 一键开始：只触发一条路径；生成完只存方案库（不写盘 —— stub 掉真生成/真存库）
    _calls = []
    _og = app.generate
    _ols, _ole = app._save_started_to_library, app._save_enemy_to_library
    app.generate = lambda: _calls.append("gen")
    app._save_started_to_library = lambda m: _calls.append("save:" + str(m))
    app._save_enemy_to_library = lambda: _calls.append("save:enemy")
    try:
        app.item_on.set(True); app.ev1_on.set(True); app._refresh_start_action()
        app.start_randomize(); root.update()
        _one = (_calls == ["gen"] and app._pending_start == "combined")
        app._start_gen_ok(True); root.update()
        _two = (_calls == ["gen", "save:combined"] and app._pending_start is None)
        _calls.clear()
        app.item_on.set(False); app.ev1_on.set(True); app._refresh_start_action()
        app.start_randomize(); root.update()
        _three = (_calls == ["save:enemy"])
        _calls.clear()
        app.item_on.set(True); app.ev1_on.set(False); app._refresh_start_action()
        app.start_randomize(); root.update()
        _four = (_calls == ["gen"] and app._pending_start == "item")
        app._start_gen_ok(True); root.update()
        _five = (_calls == ["gen", "save:item"])
    finally:
        app.generate = _og
        app._save_started_to_library, app._save_enemy_to_library = _ols, _ole
        app._pending_start = None; app._generating = False
        app.item_on.set(True); app.ev1_on.set(True); app._refresh_start_action()
    ck("一键开始：两个都勾 ⇒ 先生成，再整条存进方案库（不写盘）",
       _one and _two, f"{_one}/{_two}/{_calls}")
    ck("一键开始：只勾敌人 ⇒ 直接把敌人方案存进库（不生成物品方案）", _three, f"{_calls}")
    ck("一键开始：只勾物品 ⇒ 生成后存方案库（不写盘）", _four and _five,
       f"{_four}/{_five}/{_calls}")
    app.nb.select(app.page_set)
    root.update()
    ck("种子输入框在底部动作栏（不属于任何一页）",
       str(app.seed_e).startswith(str(app.root))
       and not str(app.seed_e).startswith(str(app.page_set))
       and not str(app.seed_e).startswith(str(app.page_enemy)),
       str(app.seed_e))
    ck("种子：默认每次开始随机都换（不再固定成 20261010）",
       bool(app.reroll_seed.get()), repr(app.reroll_seed.get()))
    ck("种子：那一行的说明写清「勾着=新世界 / 取消=复现」",
       any("复现" in str(w.cget("text")) for w in app.footer_seedrow.winfo_children()
           if w.winfo_class() == "TLabel" or w.winfo_class() == "Label"), "")
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
        import native_apply as _na
        _pr0 = _na.pristine_probe(os.path.join(tmp, "没有这个文件.bin"))
        ck("原始备份自检：pristine_probe 在、缺文件时如实返回 unknown",
           callable(getattr(_na, "pristine_probe", None))
           and _pr0.get("rate") is None and _pr0.get("checked") == 0,
           repr(_pr0))
    except Exception as _e:
        ck("原始备份自检：pristine_probe 在、缺文件时如实返回 unknown", False, repr(_e))
    ck("底部动作栏：物品页上有「打开方案库」",
       app.b_lib.winfo_manager() == "pack", repr(app.b_lib.winfo_manager()))
    app.nb.select(app.page_lib)
    root.update()
    ck("底栏跟页签走：方案库页整条收起（动作在详情面板里）",
       app.footer.winfo_manager() == "",
       f"footer={app.footer.winfo_manager()!r}")
    app.nb.select(app.page_enemy)
    root.update()
    ck("底栏跟页签走：敌人页也显示（开始随机是全局唯一入口）",
       app.footer.winfo_manager() == "pack"
       and app.b_ev1_preview.winfo_manager() == "pack",
       f"footer={app.footer.winfo_manager()!r}")
    app.nb.select(app.page_set)
    root.update()
    ck("旧管线（v0）的折叠块与开关彻底删掉（不是藏起来）",
       (not hasattr(app, "enemy_legacy")) and (not hasattr(app, "_toggle_enemy_legacy")),
       "还有残留")
    # 逐类预设编辑器（2026-10-21）：能打开、类别/池齐全、关掉不残留 grab
    ck("敌人页 v1：有「编辑逐类预设」入口", hasattr(app, "ev1_preset_lbl"),
       "缺 ev1_preset_lbl")
    ck("敌人页 v1：有「手动指定」入口", hasattr(app, "enemy_v1_manual"),
       "缺 enemy_v1_manual")
    app.enemy_v1_preset_editor()
    root.update()
    ck("v1 预设编辑器：能打开", bool(getattr(app, "_ev1_preset_win", None)
                                   and app._ev1_preset_win.winfo_exists()))
    _pt = getattr(app, "_ev1_preset_tree", None)
    # 2026-10-24：可见类从 16 收到 9（Mob 并入 Basic；None/Helper/DupeOnly/Dummy/Scarab/CaravanTroll 退出界面）
    _cls_n = len(_pt.get_children("classes")) if _pt else 0
    ck("v1 预设编辑器：9 个可见类别", bool(_pt and _cls_n == 9), str(_cls_n))
    _cls_txt = "\n".join(_pt.item(_i, "text") for _i in _pt.get_children("classes")) if _pt else ""
    ck("v1 预设编辑器：不再出现无用分类",
       bool(_pt) and not any(x in _cls_txt for x in (
           "法魂杂兵", "粪金龟", "商队巨魔", "未分类", "假人", "随从", "复制体")), _cls_txt)
    ck("v1 预设编辑器：四个特殊池", bool(_pt and len(_pt.get_children("pools")) == 4),
       str(len(_pt.get_children("pools"))) if _pt else "没有树")
    _first_cls_txt = _pt.item(_pt.get_children("classes")[0], "text") if _pt else ""
    ck("v1 预设编辑器：类别已汉化", "常规敌人" in str(_first_cls_txt), repr(_first_cls_txt))
    # ── 2026-10-24：特殊池既能当来源、也能单独配来源（GUI 侧断言）──
    _pool_kids = list(_pt.get_children("pools")) if _pt else []
    ck("v1 预设编辑器：pools 节点 4 个子项、iid 都是 pool:<pid>",
       len(_pool_kids) == 4 and all(str(k).startswith("pool:") for k in _pool_kids),
       str(_pool_kids))
    # 2026-10-24 v1.3.13：血条位条目（preset.bar）在左树有一个顶层节点
    _bar_kid = [k for k in _pt.get_children("") if str(k) == "bar"] if _pt else []
    ck("v1 预设编辑器：血条位节点在（「血条位（真 BOSS 战）」）",
       bool(_bar_kid and "血条位" in str(_pt.item("bar", "text"))),
       str(_pt.item("bar", "text")) if _bar_kid else "没有 bar 节点")
    # 类面板：来源网格要含池来源（9 类 + 4 池 = 13 个 Entry）
    _cw, _ctxt, _cls_pool_ok = {}, [], False
    try:
        _pt.selection_set("cls:Basic")
        app._ev1_preset_show()
        root.update()
        _cw = dict(getattr(app, "_ev1_preset_weights", {}) or {})

        def _collect_texts(w):
            for _ch in w.winfo_children():
                try:
                    if _ch.winfo_class() in ("Label", "TLabel"):
                        _ctxt.append(str(_ch.cget("text")))
                except Exception:
                    pass
                _collect_texts(_ch)
        _collect_texts(getattr(app, "_ev1_preset_right", app.root))
        _cls_pool_ok = ("pool:waygate" in _cw and "pool:reliquary" in _cw
                        and "@sameboss" in _cw
                        and any(str(t).startswith("池：") for t in _ctxt)
                        and any("同类型 Boss" in str(t) for t in _ctxt))
    except Exception:
        import traceback as _tb
        print("   · 类面板来源网格自检异常：" + _tb.format_exc(limit=2))
    ck("v1 预设编辑器：类面板来源网格 = 9 类 + 4 池 + 同类型 Boss（14 个 Entry，池行写「池：<中文名>」）",
       len(_cw) == 14 and _cls_pool_ok, "%d 个｜%s" % (len(_cw), sorted(_cw)[:3]))
    # 池面板：改权重 → cur["pools"][pid]["donor_weights"] 生效 + builtin 置 False
    _cur_ed = getattr(app, "_ev1_preset_cur", {}) or {}
    _pst = ((_cur_ed.get("pools") or {}).get("waygate")) or {}
    _dw, _pw, _pool_commit_ok = {}, {}, False
    try:
        _pt.selection_set("pool:waygate")
        app._ev1_preset_show()
        root.update()
        _pw = dict(getattr(app, "_ev1_preset_weights", {}) or {})
        _pcommit = getattr(app, "_ev1_preset_commit", None)
        for _k in _pw:                  # 先把网格清零（否则旧百分比会一起写进 donor_weights）
            _pw[_k].set("0")
        _pw["Basic"].set("60.0")
        _pw["pool:waygate"].set("40.0")
        _pcommit()
        root.update()
        _dw = _pst.get("donor_weights") or {}
        _pool_commit_ok = (abs(float(_dw.get("Basic", 0)) - 60.0) < 1e-6
                           and abs(float(_dw.get("pool:waygate", 0)) - 40.0) < 1e-6
                           and _pst.get("targets") == ["Basic", "pool:waygate"])
    except Exception:
        import traceback as _tb2
        print("   · 池面板写入自检异常：" + _tb2.format_exc(limit=2))
    ck("v1 预设编辑器：池面板来源网格 14 个 Entry（9 类 + 4 池 + 同类型 Boss）",
       len(_pw) == 14, "%d 个" % len(_pw))
    ck("v1 预设编辑器：池面板写入 cur[pools][pid][donor_weights] 生效（含 pool: 引用）",
       _pool_commit_ok, repr(_dw))
    ck("v1 预设编辑器：池面板写入后 builtin=False（标题显示已改动）",
       _cur_ed.get("builtin") is False, repr(_cur_ed.get("builtin")))
    # ── v1.3.13：@sameboss（同类型 Boss）既是来源，也会出现在池/血条位条目的 donor_weights 里 ──
    _sb_ok, _sb_dw = False, {}
    try:
        _pst["enabled"] = True
        _pst["donor_weights"] = {"@sameboss": 100.0}
        _pst["targets"] = ["@sameboss"]
        _pt.selection_set("pool:waygate")
        app._ev1_preset_show()
        root.update()
        _pw2 = dict(getattr(app, "_ev1_preset_weights", {}) or {})
        _pcommit2 = getattr(app, "_ev1_preset_commit", None)
        _pcommit2()                     # 什么都不改：sync 应把 100% 的 @sameboss 原样写回
        root.update()
        _sb_dw = ((_cur_ed.get("pools") or {}).get("waygate") or {}).get("donor_weights") or {}
        _sb_ok = (len(_pw2) == 14 and "@sameboss" in _pw2
                  and list(_sb_dw) == ["@sameboss"]
                  and abs(float(_sb_dw.get("@sameboss", 0)) - 100.0) < 1e-6)
    except Exception:
        import traceback as _tb_sb
        print("   · @sameboss 池条目自检异常：" + _tb_sb.format_exc(limit=2))
    ck("v1 预设编辑器：池条目 donor_weights=@sameboss 打开池面板再提交仍保留（不被清零）",
       _sb_ok, repr(_sb_dw))
    # 血条位面板：来源网格 14 行（含 @sameboss，标签「同类型 Boss」）
    _bw, _bar_ok = {}, False
    try:
        _pt.selection_set("bar")
        app._ev1_preset_show()
        root.update()
        _bw = dict(getattr(app, "_ev1_preset_weights", {}) or {})
        _btxt = []

        def _collect_bar_texts(_w):
            for _ch in _w.winfo_children():
                try:
                    if _ch.winfo_class() in ("Label", "TLabel"):
                        _btxt.append(str(_ch.cget("text")))
                except Exception:
                    pass
                _collect_bar_texts(_ch)
        _collect_bar_texts(getattr(app, "_ev1_preset_right", app.root))
        _bar_ok = (len(_bw) == 14 and "@sameboss" in _bw
                   and any("同类型 Boss" in str(t) for t in _btxt))
    except Exception:
        import traceback as _tb_bar
        print("   · 血条位面板自检异常：" + _tb_bar.format_exc(limit=2))
    ck("v1 预设编辑器：血条位面板来源网格 14 行（含 @sameboss / 「同类型 Boss」）",
       _bar_ok, "%d 个" % len(_bw))
    app._ev1_preset_win.destroy()
    root.update()
    # ── v1.3.13：07「Boss 同类·杂兵同族」的 bar 条目不能被打开/保存/应用流程悄悄改坏 ──
    _old_pre07 = app.ev1_preset
    try:
        import copy as _copy07
        app._apply_path()
        import enemy_plan as _EP07
        _cfg07 = _EP07.load_data()["cfg"]
        # 不读磁盘上的 07 文件：打包 exe 的隔离自检（空目录里只有 exe）也要能跑，
        # 这里内联构造「Boss 同类 + 池/血条位用同类型 Boss」的等价预设。
        _raw07 = {
            "name": "07 同类（自检内联）", "rate_mode": "independent",
            "classes": {
                _c: {"enabled": True, "rate": 1.0, "weight": 100.0,
                     "targets": [_c], "donor_weights": {_c: 100.0},
                     "source_areas": ["base", "dlc"], "target_areas": "same",
                     "size_max": None}
                for _c in _EP07.visible_classes(_cfg07)},
            "pools": {
                _pid: {"enabled": True, "rate": 1.0, "weight": 100.0,
                       "targets": ["@sameboss"],
                       "donor_weights": {"@sameboss": 100.0},
                       "source_areas": ["base", "dlc"], "target_areas": "same",
                       "size_max": None}
                for _pid in _EP07.visible_pools(_cfg07)},
            "bar": {"enabled": True, "rate": 1.0, "weight": 100.0,
                    "targets": ["@sameboss"],
                    "donor_weights": {"@sameboss": 100.0},
                    "source_areas": ["base", "dlc"], "target_areas": "same",
                    "size_max": None},
        }
        _n07 = _EP07.normalize_preset(_raw07, _cfg07)
        _b07 = (_n07 or {}).get("bar") or {}
        ck("v1 预设编辑器：同类 Boss 预设（内联 07）的 bar 经 normalize 仍 enabled 且 donor_weights 含 @sameboss",
           bool(_b07.get("enabled")) and "@sameboss" in (_b07.get("donor_weights") or {}),
           repr(_b07)[:180])
        app.ev1_preset = _n07
        app.enemy_v1_preset_editor()
        root.update()
        _cur07 = getattr(app, "_ev1_preset_cur", {}) or {}
        _bcur = _cur07.get("bar") or {}
        ck("v1 预设编辑器：打开同类 Boss 预设后 cur[bar] 仍是 dict、enabled、含 @sameboss",
           isinstance(_bcur, dict) and bool(_bcur.get("enabled"))
           and "@sameboss" in (_bcur.get("donor_weights") or {}), repr(_bcur)[:180])
        _p07 = _copy07.deepcopy(_cur07)
        _p07["builtin"] = False
        _n07b = _EP07.normalize_preset(_p07, _cfg07)
        _b07b = (_n07b or {}).get("bar") or {}
        ck("v1 预设编辑器：模拟 _apply（normalize(cur)）后 bar 仍 enabled 且含 @sameboss",
           bool(_b07b.get("enabled")) and "@sameboss" in (_b07b.get("donor_weights") or {}),
           repr(_b07b)[:180])
        _p07c = _copy07.deepcopy(_cur07)
        _p07c["builtin"] = False
        _p07c["classes"].setdefault("Basic", {})["enabled"] = False
        _n07c = _EP07.normalize_preset(_p07c, _cfg07)
        _b07c = (_n07c or {}).get("bar") or {}
        ck("v1 预设编辑器：只改类别后 bar 原样保留（打开/保存流程不改坏同类预设）",
           bool(_b07c.get("enabled"))
           and (_b07c.get("donor_weights") or {}).get("@sameboss") == 100.0,
           repr(_b07c)[:180])
    except Exception:
        import traceback as _tb07
        print("   · 07 预设 bar 自检异常：" + _tb07.format_exc(limit=2))
        ck("v1 预设编辑器：07 预设 bar 自检（异常即失败）", False, _tb07.format_exc(limit=1))
    finally:
        try:
            app._ev1_preset_win.destroy()
        except Exception:
            pass
        root.update()
        app.ev1_preset = _old_pre07
    # 权重叠加语义：预设里的 rate_mode/weight 必须原样进 options（引擎按它分「换入占比」）
    _old_pre = app.ev1_preset
    app.ev1_preset = {"version": 1, "name": "权重测试", "rate_mode": "weight",
                      "classes": {"Boss": {"enabled": True, "rate": 1.0, "weight": 20.0,
                                           "targets": ["Boss"], "source_areas": ["base", "dlc"],
                                           "target_areas": "same", "size_max": 3.0}}}
    _opts_w = app._ev1_options()
    ck("v1 预设：权重语义进 options", (_opts_w.get("preset") or {}).get("rate_mode") == "weight",
       repr((_opts_w.get("preset") or {}).get("rate_mode")))
    ck("v1 预设：每类权重进 options",
       (_opts_w.get("preset") or {}).get("classes", {}).get("Boss", {}).get("weight") == 20.0,
       repr(_opts_w.get("preset")))
    app.ev1_preset = _old_pre
    _old_scale, _old_oops = app.ev1_scale.get(), app.ev1_oops.get()
    app.ev1_scale.set(1.35)
    app.ev1_oops.set("主要BOSS")
    _opts_f = app._ev1_options()
    ck("v1 新功能：生命值倍率进 options", abs((_opts_f.get("scaling") or {}).get("hp", 1) - 1.35) < 1e-9,
       repr(_opts_f.get("scaling")))
    ck("v1 新功能：全替换为进 options", _opts_f.get("oops_all") == "Boss",
       repr(_opts_f.get("oops_all")))
    _old_rainbow = app.ev1_rainbow.get()
    app.ev1_rainbow.set(True)
    _opts_c = app._ev1_options()
    ck("v1 新功能：敌人颜色进 options",
       bool((_opts_c.get("features") or {}).get("rainbow")), repr(_opts_c.get("features")))
    app.ev1_rainbow.set(_old_rainbow)
    _old_ons = app.ev1_ons.get()
    app.ev1_ons.set(1.5)
    _opts_o = app._ev1_options()
    ck("v1 新功能：敌人倍增进 options",
       abs(float((_opts_o.get("features") or {}).get("onslaught", 1.0)) - 1.5) < 1e-9,
       repr(_opts_o.get("features")))
    app.ev1_ons.set(_old_ons)
    app.ev1_scale.set(_old_scale)
    app.ev1_oops.set(_old_oops)

    # v1 卡片与右列动作都长在「敌人随机」页的子树里（开始随机在底栏，是全局的）
    ck("敌人随机页：v1 卡片与挂载状态都在这一页里",
       all(str(getattr(app, a)).startswith(str(app.page_enemy))
           for a in ("b_ev1_preview", "b_enemy_play", "b_enemy_revert", "enemy_page_hint")),
       f"preview父容器={app.b_ev1_preview.winfo_parent()}")
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
             ("敌人 v1", ["enemy_plan", "enemy_write", "param_bin", "msb_edit",
                          "evd_edit", "enemy_gate", "bar_names"]),
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
             "row_models.csv", "enemy_type_map.csv",
             # v1 新管线（M0 产物）：位置主键表 / 模型名字表 / 分类配置
             "enemy_places.csv", "enemy_model_names.csv", "enemy_bar_names.csv",
             os.path.join("apply", "data", "enemy_classes_v3.yaml")]
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


def _play_log_path(layer_root):
    return os.path.join(layer_root, "启动日志.txt")


def _play_say(logp, msg):
    """--play 的日志：窗口版 exe 没有控制台，所以一律写进方案目录"""
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + str(msg)
    try:
        with open(logp, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def cli_plan_off(argv=None):
    """命令行切回法魂本体：<exe> --plan-off（方案层里的「切回法魂本体.bat」调它）"""
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
    except Exception:
        pass
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
    except Exception:
        pass
    # 先把当前方案的进度存回它的槽、再把本体的档换回来 —— 以前只清 Plan=，
    # 结果"切回本体"玩到的还是上一个方案的档（作者实测 2026-10-23）。
    try:
        import gamelib as GL
        sw = GL.switch_to_body(log=lambda s: print("  · " + str(s)))
        if sw.get("restored"):
            print("已把法魂本体的存档换回来（%s）" % sw.get("live"))
    except Exception as e:
        print("换档没做（不影响切回本体）：%s" % e)
    try:
        import plan_layer as PL
        r = PL.clear_plan()
    except Exception:
        import traceback
        try:
            print("切回本体失败：" + traceback.format_exc(limit=4))
        except Exception:
            pass
        return 1
    try:
        print("已切回法魂本体（下一次启动就是纯法魂）" if r.get("changed")
              else "本来就没有挂载方案（ini 里没有 Plan= 行）")
    except Exception:
        pass
    return 0


def cli_paths(argv=None):
    """命令行把「这台机器上它认到的路径」全部打出来（换机器 / 报找不到文件时先跑这个）"""
    try:
        sys.path.insert(0, os.path.join(WORKSPACE or HERE, "investigation", "apply"))
    except Exception:
        pass
    rows = []

    def add(k, v):
        rows.append((k, v or "（没找到）"))

    add("工作区", WORKSPACE)
    add("exe / 脚本目录", HERE)
    try:
        import modpaths
        _mr = modpaths.find_mod_root(HERE)
        add("法魂 MOD 目录", _mr)
        add("法魂 regulation", os.path.join(_mr, "mod", "regulation.bin") if _mr else "")
        add("游戏目录", modpaths.find_game_dir(HERE))
    except Exception as e:
        add("路径解析", "出错：%s" % e)
    try:
        import plan_layer as PL
        add("法魂包根目录", PL.pack_root())
        add("YAFSML.ini", PL.ini_path())
        add("方案目录", PL.plans_root())
        add("当前挂载", PL.current_plan_line() or "（没挂方案 = 纯法魂本体）")
    except Exception as e:
        add("方案层", "不可用：%s" % e)
    try:
        import gamelib as GL
        add("存档目录", GL.live_dir())
        add("存档库", GL.bank_root())
    except Exception as e:
        add("存档", "不可用：%s" % e)
    try:
        import oodle
        add("Oodle DLL", oodle.find_dll())
    except Exception as e:
        add("Oodle", "不可用：%s" % e)
    try:
        for k, v in rows:
            print("%-16s %s" % (k, v))
    except Exception:
        pass
    return 0


def cli_play(argv):
    """命令行开局：<exe> --play <方案层目录 或 它的 mod 目录>

    为什么要有它：方案层目录里的「用这个方案启动.bat」以前只做「挂 Plan= → call 启动法魂.bat」，
    完全绕过了存档库 —— 从那里进游戏用的还是**当前**存档，不是这个方案自己的。
    现在 bat 改成调这里：换档（每个方案一份）→ 挂载 → 起游戏 → 等退出 → 进度存回它的槽。
    """
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "investigation", "apply"))
    except Exception:
        pass
    i = argv.index("--play")
    if i + 1 >= len(argv):
        try:
            print("用法：--play <方案层目录 或 它的 mod 目录>")
        except Exception:
            pass
        return 2
    raw = os.path.abspath(argv[i + 1])
    layer = os.path.dirname(raw) if (os.path.basename(raw).lower() == "mod"
                                     and os.path.isdir(raw)) else raw
    logp = _play_log_path(layer)
    # 层目录里也有 mod/ —— 先把真正的法魂包根发布出去（_main_impl 那一步可能认成层根）
    _pk = _pack_of_layer(layer)
    if _pk:
        publish_mod_root(_pk)

    def _say(msg):
        _play_say(logp, msg)

    _say("—— 用方案启动：" + os.path.basename(layer))
    try:
        import gamelib as gl
    except Exception:
        import traceback
        _say("[x] 存档模块加载失败：" + traceback.format_exc(limit=5))
        return 1

    root = [None]
    _no_ui = os.environ.get("RANDOMIZER_CLI_NO_UI") == "1"   # 自检用：不弹窗

    def _ui_root():
        if root[0] is None:
            import tkinter as _tk
            root[0] = _tk.Tk()
            root[0].withdraw()
        return root[0]

    def _ask(title, text):
        _say("[问] %s：%s" % (title, str(text).replace("\n", " ")))
        return False if _no_ui else messagebox.askyesno(title, text, parent=_ui_root())

    def _tell(title, text, kind="warning"):
        _say("[%s] %s：%s" % (kind, title, text))
        if _no_ui:
            return
        fn = messagebox.showerror if kind == "error" else messagebox.showwarning
        fn(title, text, parent=_ui_root())

    try:
        if not os.path.isdir(os.path.join(layer, "mod")):
            raise gl.GameError("这个方案还没有覆盖层（先在方案库里点一次「用这个方案玩」生成）：%s" % layer)
        # ① 没有存档槽 → 先问"用新角色开局"（别等关了游戏才问）
        allow_new = False
        try:
            has = bool(gl.bank_status(gl.plan_label(layer)).get("has"))
        except Exception:
            has = True
        if not has:
            if not _ask("这个方案还没有存档",
                        "「%s」还没有自己的存档。\n\n现在就用新角色开始吗？\n\n"
                        "（你现在的档会先留底，不会丢；选「否」就先不动）" % os.path.basename(layer)):
                _say("人选择不用新档 —— 不启动")
                return 0
            allow_new = True
        # ② 游戏在跑 → 先问，同意就自动关掉（作者要求：别让人先去手动退游戏）
        kill = False
        if gl.game_running():
            if not _ask("游戏正在运行",
                        "要用「%s」开局，得先把正在跑的《艾尔登法环》关掉。\n\n"
                        "现在自动关掉它并启动吗？\n\n"
                        "（先请它自己退出；实在不退才强制结束 —— 强杀会丢最近一小段进度）"
                        % os.path.basename(layer)):
                _say("人选择不关游戏 —— 不启动")
                return 0
            kill = True
        # ③ 换档 + 挂载 + 起游戏
        r = gl.launch(layer, allow_new_save=allow_new, kill_running=kill, log=_say)
    except gl.NeedsNewSave:
        _say("这个方案还没有存档，且没有确认开新档 —— 不启动")
        return 0
    except gl.GameError as e:
        _say("[x] " + str(e))
        try:
            _tell("不能启动", str(e))
        except Exception:
            pass
        return 1
    except Exception as e:
        import traceback
        _say("[x] 启动失败：" + traceback.format_exc(limit=6))
        try:
            _tell("启动失败", str(e), "error")
        except Exception:
            pass
        return 1

    if r.get("restored"):
        _what = "用它的存档开局"
    elif r.get("fresh"):
        _what = "新角色开局"
    else:
        _what = "沿用当前存档"
    _say("已启动（%s，存档文件 %s）—— 等游戏进程出现…" % (_what, r.get("save_name") or "?"))
    t0 = time.time()
    seen = False
    while time.time() - t0 < 180:
        if gl.game_running():
            seen = True
            break
        time.sleep(1.0)
    if not seen:
        _say("[x] 等了 3 分钟也没看到 eldenring.exe —— 可能没起来（看 yafsml\\log\\YAFSML.log）")
        return 3
    _say("游戏在跑 —— 等它退出（退出后这个方案的进度会自动存回它的槽）")
    while gl.game_running():
        time.sleep(2.0)
    time.sleep(2.0)                 # 让游戏把存档落完
    try:
        meta = gl.finish()
    except Exception as e:
        _say("[x] 回存失败：" + str(e))
        return 4
    if meta and meta.get("ok"):
        _say("游戏已退出 —— 进度已存回「%s」的槽（%s）" % (meta.get("label"), meta.get("saved", "")))
    else:
        _say("游戏已退出 —— 没有需要回存的进度")
    try:
        if root[0] is not None:
            root[0].destroy()
    except Exception:
        pass
    return 0


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
    try:
        return _main_impl()
    except BaseException:
        # 窗口版没有控制台：把崩溃写成一个文件，别让它毫无痕迹地退 1
        try:
            import traceback
            p = os.path.join(os.environ.get("TEMP", "."), "randgui_crash.txt")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("--- %s argv=%r\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                                     sys.argv, traceback.format_exc()))
        except Exception:
            pass
        raise


def _main_impl():
    _console_utf8()
    # 尽早发布 MOD 路径：写入管线在 import 时就会读取它（打包版尤其重要）
    try:
        publish_mod_root(find_mod_root())
    except Exception:
        pass
    if "--play" in sys.argv:
        return cli_play(sys.argv)
    if "--plan-off" in sys.argv:
        return cli_plan_off(sys.argv)
    if "--paths" in sys.argv:
        return cli_paths(sys.argv)
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
