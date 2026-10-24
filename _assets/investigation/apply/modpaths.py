# -*- coding: utf-8 -*-
"""modpaths.py — 一处解析「法魂 MOD 目录 / 游戏目录」，别在别处写死。

为什么单独一支：换机器、换盘符、把整合包改个名，写死的路径就全废；而散落在
十几个模块里的路径解析，改一处漏一处。所有运行时模块（引擎 / 方案层 / 启动器）
都从这里取路径，规则只有这一份。

判据（实测）
------------
* 法魂整合包根目录：里面有 `mod\\regulation.bin`
* 游戏目录：里面有 `eldenring.exe`（即 ...\\Game），也接受它的上一层

查找顺序（全部相对「当前位置」，所以换到哪台机器都成立）
------------------------------------------------------
1. 环境变量 `CONVERGENCE_MOD_ROOT` / `CONVERGENCE_GAME_DIR`（界面/命令行解析后发布）
2. 起点目录本身，以及它的各级父目录（最多 7 层）
3. 这些目录的**同级目录**（最常见布局：随机器和法魂包并排放）
4. 打包版会把 exe 所在目录也当成起点

找不到就返回 None；必须要有路径的地方用 `require_*`，报错里写清三种解法。
"""
import os
import sys

MOD_ENV = "CONVERGENCE_MOD_ROOT"
GAME_ENV = "CONVERGENCE_GAME_DIR"
GAME_ENV_ALT = "ER_GAME_DIR"

_MAX_UP = 7            # 向上找几层
_MAX_SIBLINGS = 400    # 每层最多看多少个同级目录（大硬盘/网络盘上不卡）
_SKIP = {".git", ".svn", "node_modules", "__pycache__", "$RECYCLE.BIN", "System Volume Information"}

_CACHE = {}            # (env 值, 起点) → 结果（同一进程里只扫一次）


def _norm(p):
    return os.path.normpath(os.path.abspath(p))


def is_layer_root(d):
    """这个目录是不是一个方案层（法魂包/方案/层目录）。

    方案层里也有 mod/regulation.bin —— 光凭这一点分不出「包本体」和「覆盖层」，
    而双击方案层里的启动 bat 时工作目录正好是层根（2026-10-23 实测：整条启动
    因为把层当成包、找不到 yafsml/ 而断掉）。
    """
    if not d:
        return False
    try:
        return (os.path.isfile(os.path.join(d, "mod", "regulation.bin"))
                and os.path.basename(os.path.dirname(_norm(d))) == "方案")
    except OSError:
        return False


def is_mod_root(d):
    """这个目录是不是法魂整合包根目录（判据：mod\\regulation.bin 存在）"""
    if not d:
        return False
    try:
        if not os.path.isfile(os.path.join(d, "mod", "regulation.bin")):
            return False
    except OSError:
        return False
    return not is_layer_root(d)


def _as_game_dir(p):
    """把候选目录归一成「eldenring.exe 所在的那个 Game 目录」；不是就返回 None"""
    if not p:
        return None
    for c in (p, os.path.join(p, "Game")):
        try:
            if os.path.isfile(os.path.join(c, "eldenring.exe")):
                return _norm(c)
        except OSError:
            pass
    return None


def is_game_dir(d):
    return _as_game_dir(d) is not None


def _starts(start=None):
    out = []
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(_norm(sys.executable)))
    out.append(_norm(start or os.path.dirname(os.path.abspath(__file__))))
    return out


def _walk_up(start):
    cur = _norm(start)
    for _ in range(_MAX_UP):
        yield cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt


def _siblings(base):
    try:
        names = sorted(os.listdir(base))[:_MAX_SIBLINGS]
    except OSError:
        return
    for n in names:
        if n.startswith(".") or n in _SKIP:
            continue
        yield os.path.join(base, n)


def _candidates(start):
    seen, out = set(), []

    def add(p):
        if not p:
            return
        p = _norm(p)
        if p in seen:
            return
        seen.add(p)
        out.append(p)

    for s in _starts(start):
        for base in _walk_up(s):
            add(base)
            for sib in _siblings(base):
                add(sib)
    return out


def _mod_score(d):
    """多个候选时挑更像「当前这一份」的：名字带法魂/Convergence 优先，然后比 regulation 的修改时间"""
    name = os.path.basename(d)
    named = 1 if ("法魂" in name or "convergence" in name.lower()) else 0
    packed = 1 if os.path.isdir(os.path.join(d, "yafsml")) else 0   # 真·整合包（能挂载）优先
    try:
        mt = os.path.getmtime(os.path.join(d, "mod", "regulation.bin"))
    except OSError:
        mt = 0.0
    return (named, packed, mt)


def find_mod_root(start=None):
    """找到法魂整合包根目录；找不到返回 None（不抛错，界面据此显示"没找到"）"""
    env = os.environ.get(MOD_ENV)
    if env and is_mod_root(env):
        return _norm(env)
    key = ("mod", env, _norm(start) if start else "")
    if key in _CACHE:
        return _CACHE[key]
    found = [c for c in _candidates(start) if is_mod_root(c)]
    val = max(found, key=_mod_score) if found else None
    _CACHE[key] = val
    return val


def require_mod_root(start=None):
    """必须要有 MOD 目录的地方用它：找不到就抛一个**能照着做**的错"""
    d = find_mod_root(start)
    if d:
        return d
    raise RuntimeError(
        "没找到法魂 MOD 目录（判据：目录里有 mod\\regulation.bin）。\n"
        "  怎么办（任选一条）：\n"
        "    ① 把随机器 / exe 放到法魂整合包**旁边**（同一层目录），再运行；\n"
        "    ② 在界面「本地文件」里点「指定 MOD 目录…」选法魂包根目录；\n"
        "    ③ 或者设环境变量 %s=<法魂包根目录>。\n"
        "  已经找过：起点目录及其上 %d 层、以及每层的同级目录。" % (MOD_ENV, _MAX_UP))


def mod_reg(start=None):
    """法魂本体的 regulation.bin 的完整路径"""
    return os.path.join(require_mod_root(start), "mod", "regulation.bin")


def find_game_dir(start=None):
    """找到游戏目录（含 eldenring.exe 的那个 Game）；找不到返回 None"""
    for env in (GAME_ENV, GAME_ENV_ALT):
        v = os.environ.get(env)
        g = _as_game_dir(v) if v else None
        if g:
            return g
    key = ("game", os.environ.get(GAME_ENV), os.environ.get(GAME_ENV_ALT),
           _norm(start) if start else "")
    if key in _CACHE:
        return _CACHE[key]
    val = None
    for c in _candidates(start):
        g = _as_game_dir(c)
        if g:
            val = g
            break
    _CACHE[key] = val
    return val


def require_game_dir(start=None):
    d = find_game_dir(start)
    if d:
        return d
    raise RuntimeError(
        "没找到游戏目录（判据：目录里有 eldenring.exe）。\n"
        "  怎么办（任选一条）：\n"
        "    ① 把随机器 / exe 放到游戏安装目录旁边再运行；\n"
        "    ② 设环境变量 %s=<...\\ELDEN RING\\Game>；\n"
        "    ③ 只用 oodle 时，也可以把 oo2core_*.dll 放到 exe 旁的 oodle\\ 里。" % GAME_ENV)


def find_ref_dir(env="ENEMY_REF_DIR"):
    """参考实现（thefifthmatt）的解包目录 —— 只在**重新生成数据表**的开发脚本里用。

    优先环境变量；否则在用户目录的 Downloads / 下载 里找名字带 Randomizer 的目录下
    的 diste 子目录。找不到返回 None（别把某台机器的下载路径写进代码）。
    """
    p = os.environ.get(env)
    if p and os.path.isdir(p):
        return p
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "Downloads"), os.path.join(home, "下载"), home):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for n in names:
            d = os.path.join(base, n)
            if not os.path.isdir(d) or "andomiz" not in n.lower():
                continue
            for dp, _dn, _fn in os.walk(d):
                if os.path.basename(dp).lower() == "diste":
                    return _norm(dp)
    return None


def require_ref_dir(env="ENEMY_REF_DIR"):
    d = find_ref_dir(env)
    if d:
        return d
    raise RuntimeError(
        "找不到参考实现解包目录（...\\randomizer\\diste）。\n"
        "  这是**重新生成数据表**时才需要的开发素材；设环境变量 %s 指到它即可，例如：\n"
        "    set %s=C:\\path\\Elden Ring Randomizer ...\\randomizer\\diste" % (env, env))


if __name__ == "__main__":
    print("MOD 根目录 :", find_mod_root() or "（没找到）")
    print("游戏目录   :", find_game_dir() or "（没找到）")
    print("参考实现   :", find_ref_dir() or "（没找到，重新生成数据表时才需要）")
