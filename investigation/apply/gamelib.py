#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gamelib —— 方案库直接启动游戏 + 每个方案一份独立存档

为什么要有这一层（需求：2026-10-23 作者「以后可以直接用随机器里的方案库启动，每一个方案
独立存档」）：

* 方案库本身只会「挂载」覆盖层（改 YAFSML.ini 的 Plan=），启动游戏还要人自己去双击 bat；
* 更麻烦的是存档：同一个角色档在方案 A 玩完、切到方案 B，B 会继承 A 的进度 ——
  「每个方案独立存档」要的就是切方案 = 换档，而不是共用一份。

所以这里做两件事，都只碰「文件」不碰游戏内存：

  ① 切换：启动前把目标方案的存档换进游戏的存档目录；没有就新建（旧档先入库存着）。
  ② 回存：游戏退出后，把这次玩出来的存档存回方案自己的槽。

存档库布局（放在法魂包里，和 方案/ 平级，删游戏本体也不会丢）：

    <法魂包>\\存档库\\
      <方案标签>\\ER0000.sl2          ← 这个方案的档
                  ER0000.sl2.bak
                  slot.json          ← 什么时候存的、多大、指纹
      _回收\\<时间戳>_<标签>_<原因>.sl2  ← **任何覆盖 / 删除之前都先在这里留一份**
      _active.json                   ← 这一次是用哪个方案启动的（退出后据此回存）

纪律（都是踩过的坑）：
* 游戏在跑时**绝不**动存档文件（会撞写坏档）—— 所有写入口先查 eldenring.exe。
* 覆盖 / 删除 live 存档之前**一律**先备份到 _回收\\，宁可多占 29 MB 也不赌一次手滑。
* 没有槽的方案第一次启动 = 换新档（开新角色）；旧档不会丢，在 _回收\\ 和原方案槽里。
* 不处理 Steam 云同步：云存档开着的话 Steam 可能在另一台机器/另一次启动把它盖回去，
  界面上要如实提示「玩这一套前先关掉 Elden Ring 的 Steam 云存档」。

命令行（排障用）：
    python gamelib.py --status
    python gamelib.py --selftest
    python gamelib.py --launch "<层目录>" [--new]
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SAVE_STEM = "ER0000"                              # 存档主名（后缀会变：见 save_names()）
SAVE_NAME = "ER0000.sl2"                          # 默认档名（YAFSML 没配替换时游戏读写的那个）
SAVE_FILES = ("ER0000.sl2", "ER0000.sl2.bak")     # 默认的一对（游戏自己也会读 .bak，换档必须成对换）
SEAMLESS_NAME = "ER0000.co2"                      # 无缝联机档的默认名（这一版不换它，只用于诊断）
BANK_DIRNAME = "存档库"
RECYCLE_DIRNAME = "_回收"
SLOT_META = "slot.json"
ACTIVE_STATE = "_active.json"
LAUNCH_BAT = "启动法魂.bat"
GAME_EXE = "eldenring.exe"
BODY_LABEL = "_法魂本体"                          # 没挂方案的档记在这个名下，不会被计划覆盖


class GameError(Exception):
    """启动 / 换档失败（消息直接给人看）"""


class NeedsNewSave(GameError):
    """这个方案还没有自己的存档：需要人确认「开新档」"""

    def __init__(self, label, outgoing, live_dir):
        self.label = label
        self.outgoing = outgoing
        self.live_dir = live_dir
        msg = ("方案「%s」还没有自己的存档。\n\n"
               "现在这份存档会先存进「%s」的槽里（不会丢），然后这个方案用一个新角色开始。"
               % (label, outgoing or BODY_LABEL))
        super().__init__(msg)


# ────────────────────────── 小工具 ──────────────────────────

def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha1(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _mkdir(p):
    os.makedirs(p, exist_ok=True)
    return p


def _copy(src, dst):
    """原子复制：先写 .tmp 再 replace，半截文件不会被游戏当成真档"""
    tmp = dst + ".gfswap.tmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _rm(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _ini_kv(pack=None):
    """读法魂包 `yafsml\\YAFSML.ini` 的全部 key=value（不分节；后面的覆盖前面的）。"""
    pack = pack or pack_root()
    p = os.path.join(pack, "yafsml", "YAFSML.ini")
    kv = {}
    if not os.path.isfile(p):
        return kv
    text = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(p, encoding=enc) as fh:
                text = fh.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue
        except Exception:
            return kv
    if text is None:
        return kv
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in ";#[" or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip().lower()] = v.strip()
    return kv


def save_names(pack=None):
    """游戏在**当前配置**下真正读写的存档文件名（主档 / 备份 / 无缝）。

    为什么必须读 ini：法魂包默认带 `replace_save_filename=.cnv`，YAFSML 会让游戏
    把 `ER0000.sl2` 换成 `ER0000.cnv` 来读写。以前这里只认死 `ER0000.sl2`，
    结果换档"成功"、游戏里还是原来那批角色 —— 独立存档根本没生效（2026-10-23 实测）。
    规则（见 ini 里的注释）：以点号开头 = 只替换扩展名（在 ER0000 后面接这一段）。
    """
    kv = _ini_kv(pack)

    def _map(val, default):
        val = (val or "").strip()
        if not val:
            return default
        if val.startswith("."):
            return SAVE_STEM + val
        return val

    main = _map(kv.get("replace_save_filename"), SAVE_NAME)
    return {"main": main, "bak": main + ".bak",
            "seamless": _map(kv.get("replace_seamless_coop_save_filename"), SEAMLESS_NAME),
            "ini": kv}


def _save_pair(pack=None):
    """(主档名, 备份名) —— 换档永远成对处理，游戏自己也会读 .bak。"""
    n = save_names(pack)
    return (n["main"], n["bak"])


# ────────────────────────── 路径 ──────────────────────────

def pack_root():
    """法魂包根目录（yafsml\\ 与 启动法魂.bat 所在处）—— 复用 plan_layer 的判据"""
    import plan_layer as PL
    return PL.pack_root()


def pack_of_layer(layer_dir):
    """从方案层目录往上找法魂包根（判据：那一层有 yafsml/）；找不到返回 ""。

    为什么需要：方案层里也有 mod/regulation.bin，而双击层里的启动 bat 时工作目录
    就是层根 —— 起点一旦被当成 MOD 根，pack_root() 就找不到 yafsml/、整条启动断掉
    （2026-10-23 实测）。所以开玩时优先按「层 → 包」反推，别只信环境变量。
    """
    cur = os.path.abspath(layer_dir or "")
    for _ in range(4):
        nxt = os.path.dirname(cur)
        if not nxt or nxt == cur:
            break
        cur = nxt
        if os.path.isdir(os.path.join(cur, "yafsml")):
            return cur
    return ""


def live_appdata():
    """%APPDATA%\\EldenRing；允许用环境变量 ER_SAVE_ROOT 指到别处（测试 / 便携环境）"""
    root = os.environ.get("ER_SAVE_ROOT") or os.path.join(
        os.environ.get("APPDATA") or "", "EldenRing")
    return root


def live_dir():
    """游戏真正会读的那个存档目录：%APPDATA%\\EldenRing\\<SteamID>\\（选 ER0000.sl2 最新的那个）

    一台机器上可能有多个 SteamID 目录（换号 / 离线号）；游戏读的是"当前登录账号"的那个，
    这里没有可靠办法知道是哪一个 —— 所以退一步按"最近写过的"选，并在状态里把路径显示出来，
    人一看就知道对不对。ER_SAVE_DIR 可以直接指定，避开猜。
    """
    forced = os.environ.get("ER_SAVE_DIR")
    if forced:
        return os.path.abspath(forced) if os.path.isdir(forced) else None
    root = live_appdata()
    if not os.path.isdir(root):
        return None
    try:
        main = save_names()["main"]
    except Exception:
        main = SAVE_NAME
    best, best_t = None, 0.0
    for name in os.listdir(root):
        d = os.path.join(root, name)
        f = os.path.join(d, main)
        if os.path.isfile(f):
            t = os.path.getmtime(f)
            if t > best_t:
                best, best_t = d, t
    return best


def live_files(d=None, pack=None):
    """live 目录里**当前配置那一对**存档（主档 + .bak）"""
    d = d or live_dir()
    if not d:
        return []
    return [os.path.join(d, n) for n in _save_pair(pack)
            if os.path.isfile(os.path.join(d, n))]


def current_label(pack=None):
    """当前挂的是哪个方案（YAFSML.ini 的 Plan=），没挂返回 None。
    层目录是 <层根>\\mod，所以标签取**层根的目录名**。"""
    import plan_layer as PL
    st = PL.plan_status()
    if not st.get("valid"):
        return None
    tgt = st["target"]                              # ...\<层根>\mod
    base = os.path.basename(os.path.dirname(tgt.rstrip("\\/")))
    return base or None


def current_layer(pack=None):
    import plan_layer as PL
    st = PL.plan_status()
    if not st.get("valid"):
        return None
    return os.path.dirname(st["target"].rstrip("\\/"))


def plan_label(layer_dir):
    p = os.path.abspath(layer_dir).rstrip("\\/")
    if os.path.basename(p).lower() == "mod" and os.path.isfile(os.path.join(p, "regulation.bin")):
        p = os.path.dirname(p)                     # 传进来的已经是数据根
    return os.path.basename(p)


# ────────────────────────── 存档库 ──────────────────────────

def bank_root(pack=None):
    return _mkdir(os.path.join(pack or pack_root(), BANK_DIRNAME))


def bank_dir(label, pack=None):
    return _mkdir(os.path.join(bank_root(pack), label))


def bank_status(label, pack=None):
    """这个方案的存档槽现状（没有槽就 has=False）"""
    main = _save_pair(pack)[0]
    d = os.path.join(bank_root(pack), label)
    f = os.path.join(d, main)
    if not os.path.isfile(f):
        return {"has": False, "dir": d, "at": 0, "size": 0, "files": [],
                "save_name": main}
    meta = {}
    mp = os.path.join(d, SLOT_META)
    if os.path.isfile(mp):
        try:
            meta = json.load(open(mp, encoding="utf-8"))
        except Exception:
            meta = {}
    return {"has": True, "dir": d, "at": meta.get("at") or os.path.getmtime(f),
            "size": os.path.getsize(f),
            "saved": meta.get("saved") or time.strftime("%Y-%m-%d %H:%M:%S",
                                                        time.localtime(os.path.getmtime(f))),
            "files": [os.path.basename(x) for x in live_files(d, pack=pack)]}


def bank_save(label, pack=None, note="", live=None):
    """把 live 存档存进方案槽（先留底旧槽 → 复制 → 写 meta）"""
    live = live or live_dir()
    main, bak = _save_pair(pack)
    files = live_files(live, pack=pack)
    if not files or not os.path.isfile(os.path.join(live or "", main)):
        raise GameError("找不到游戏存档（%s\\%s）—— 先正常启动一次游戏，让它自己建出来"
                        % (live or "存档目录不存在", main))
    d = bank_dir(label, pack)
    for n in (main, bak):                                     # 旧槽留底，别被覆盖掉
        old = os.path.join(d, n)
        if os.path.isfile(old):
            backup_file(old, "%s_旧槽" % label, pack)
    for src in files:
        _copy(src, os.path.join(d, os.path.basename(src)))
    meta = {"label": label, "saved": _now(), "at": time.time(),
            "size": os.path.getsize(os.path.join(d, main)),
            "sha1": _sha1(os.path.join(d, main)), "note": note}
    with open(os.path.join(d, SLOT_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def backup_file(src, tag, pack=None):
    """任何覆盖/删除前留底：<存档库>\\_回收\\<时间戳>_<tag>_<原名>"""
    rec = _mkdir(os.path.join(bank_root(pack), RECYCLE_DIRNAME))
    dst = os.path.join(rec, "%s_%s_%s" % (time.strftime("%Y%m%d-%H%M%S"), tag,
                                          os.path.basename(src)))
    shutil.copy2(src, dst)
    return dst


def backup_live(tag, pack=None, live=None):
    live = live or live_dir()
    out = []
    for f in live_files(live, pack=pack):
        out.append(backup_file(f, tag, pack))
    return out


def restore_to_live(label, pack=None, live=None):
    """把方案槽换进 live：槽里有的换进来，槽里没有的（比如 .bak）就把 live 的清掉。

    独立存档要求 live 和槽**一模一样** —— 留着别人的 .bak，游戏可能拿它回滚。
    """
    live = live or live_dir()
    if not live:
        raise GameError("找不到游戏存档目录（%%APPDATA%%\\EldenRing\\<SteamID>）")
    names = _save_pair(pack)
    d = os.path.join(bank_root(pack), label)
    if not os.path.isfile(os.path.join(d, names[0])):
        raise GameError("方案「%s」还没有存档槽" % label)
    for n in names:
        src = os.path.join(d, n)
        if os.path.isfile(src):
            _copy(src, os.path.join(live, n))
        else:
            _rm(os.path.join(live, n))
    return {"restored": True, "label": label, "live": live}


def clear_live(pack=None, live=None):
    """把 live 清空（开新档）。调用前必须已经 backup_live()"""
    live = live or live_dir()
    if not live:
        return False
    for n in _save_pair(pack):
        _rm(os.path.join(live, n))
    return True


# ────────────────────────── 游戏进程 ──────────────────────────

def _pid_is_gone(pid):
    """这个 pid 是不是「已经退出、只剩进程壳」（句柄没释放的僵尸）。

    实测（2026-10-23）：游戏退出后 tasklist 里仍留着 eldenring.exe 条目 ——
    线程数 / 句柄数 0、工作集 32 KB、WaitForSingleObject 立刻 signaled，
    连 taskkill /F 都报 Access is denied。以前只看 tasklist 里有没有名字，
    于是永远认为「游戏在跑」，启动被一直挡着（作者报的「杀不掉 / 说没进程」就是这个）。
    返回 True = 确认已退出；读不到（受保护 / 没权限）就当「还在跑」，宁可多问一句。
    """
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0      # 0 = signaled = 已退出
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


_CREATE_NO_WINDOW = 0x08000000        # subprocess 不弹黑框（窗口版程序里默认会闪一个控制台）


def _run_hidden(args, timeout=10):
    """跑一个控制台小程序但**不弹窗**（以前每 2 秒查一次进程 = 每 2 秒闪一个黑框）。"""
    kw = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kw["creationflags"] = _CREATE_NO_WINDOW
    return subprocess.run(args, **kw)


def _terminate_pid(pid):
    """强杀一个进程（ctypes，起进程不弹窗）。返回 True = 调用成功。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x0001, False, int(pid))         # PROCESS_TERMINATE
        if not h:
            return False
        try:
            return bool(k32.TerminateProcess(ctypes.c_void_p(h), 1))
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return False


def _enum_game_pids():
    """用 Toolhelp 快照枚举 eldenring.exe 进程（不走 tasklist）。

    为什么要换：窗口版程序里每次 `subprocess.run(["tasklist", ...])` 都会闪一个控制台
    窗口 —— 等游戏退出的那段时间每 2 秒闪一下，作者报「反复跳出终端」（2026-10-23）。
    返回 None = 快照不可用（调用方回退到 tasklist）；[] = 确实没有这个进程。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)     # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return None
        out = []
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(pe)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                if (pe.szExeFile or "").lower() == GAME_EXE.lower():
                    out.append(int(pe.th32ProcessID))
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(ctypes.c_void_p(snap))
        return out
    except Exception:
        return None


def _tasklist_pids():
    """tasklist 里挂着的 eldenring.exe（可能含僵尸壳）—— 只作快照不可用时的兜底"""
    try:
        r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq " + GAME_EXE, "/NH", "/FO", "CSV"])
        out = (r.stdout or b"").decode("mbcs", "replace")
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = [x.strip().strip('"') for x in line.replace('","', '|').split("|")]
        if len(parts) >= 2 and parts[0].lower() == GAME_EXE.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def _all_game_pids():
    p = _enum_game_pids()
    return _tasklist_pids() if p is None else p


def game_pids():
    """**真的还在跑**的 eldenring.exe 进程号（已退出的僵尸壳不算）"""
    return [p for p in _all_game_pids() if not _pid_is_gone(p)]


def zombie_pids():
    """还挂着、但其实已经退出的 eldenring.exe（只用于日志/诊断）"""
    return [p for p in _all_game_pids() if _pid_is_gone(p)]


def game_running():
    """eldenring.exe 真的在不在跑（Toolhelp 快照，僵尸壳不算，不弹窗）"""
    return bool(game_pids())


def kill_game(timeout=25, log=None):
    """把还在跑的游戏关掉（先请它自己退，等不到再强杀）。

    为什么不直接 /F：强杀会丢掉"最近一段还没写进存档的进度"。
    返回 True = 这次真的关掉了；False = 本来就没在跑。
    """
    say = log or (lambda *_a, **_k: None)
    pids = game_pids()
    _z = zombie_pids()
    if _z:
        say("发现 %d 个已退出的游戏残留进程（%s）—— 不影响启动，系统会自己收掉"
            % (len(_z), ",".join(str(x) for x in _z)))
    if not pids:
        return False
    for pid in pids:
        say("关闭游戏进程 pid=%s（先让它自己退，等 %d 秒）…" % (pid, timeout))
        try:
            _run_hidden(["taskkill", "/PID", str(pid)])
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not game_running():
            say("游戏已经退出")
            return True
        time.sleep(0.5)
    for pid in (game_pids() or pids):
        say("pid=%s 没有自己退，强制结束（这一小段进度可能没写进存档）" % pid)
        if not _terminate_pid(pid):
            try:
                _run_hidden(["taskkill", "/F", "/PID", str(pid)])
            except Exception:
                pass
    t0 = time.time()
    while time.time() - t0 < 10:
        if not game_running():
            say("游戏已强制结束")
            return True
        time.sleep(0.5)
    raise GameError("关不掉还在跑的游戏 —— 请手动关掉再试"
                    "（如果游戏是以管理员身份启动的，随机器也要用同样权限运行）")


def launch_bat(pack=None):
    """起法魂的启动 bat —— **隐藏窗口**跑：以前 os.startfile 会弹一个黑框。

    产物本身没变：bat 里还是 `start /min YAFSML.exe`，游戏窗口照常出。
    """
    bat = os.path.join(pack or pack_root(), LAUNCH_BAT)
    if not os.path.isfile(bat):
        raise GameError("找不到启动脚本：%s" % bat)
    kw = {"cwd": os.path.dirname(bat) or None,
          "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = _CREATE_NO_WINDOW
    subprocess.Popen(["cmd", "/c", os.path.basename(bat)], **kw)
    return bat


def write_state(label, pack=None, live=None):
    st = {"label": label, "started": _now(), "at": time.time(),
          "live": live or live_dir()}
    with open(os.path.join(bank_root(pack), ACTIVE_STATE), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    return st


def read_state(pack=None):
    p = os.path.join(bank_root(pack), ACTIVE_STATE)
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def clear_state(pack=None):
    _rm(os.path.join(bank_root(pack), ACTIVE_STATE))


# ────────────────────────── 对外主流程 ──────────────────────────

def migrate_legacy_saves(pack=None, log=None):
    """老存档改名迁移：YAFSML 让游戏读写 .cnv 时，把以前存的 .sl2 改名成 .cnv。

    为什么必须有这一步：v1.3.9 及以前只认 ER0000.sl2，玩家存档库里存的全是 .sl2；
    法魂包的 YAFSML.ini 一配 replace_save_filename=.cnv，游戏就只认 .cnv —— 于是
    「独立存档」表面上还在，实际游戏读到的是另一个文件（作者 2026-10-23 报的就是这个）。
    改名**不改内容**（存档文件格式一样，YAFSML 本身也只是改名），改之前一律先进 _回收。
    已经是新名字 / 没有老文件的目录原样跳过（幂等）。
    """
    pack = pack or pack_root()
    say = log or (lambda *_a, **_k: None)
    try:
        names = save_names(pack)
    except Exception:
        return []
    if names["main"] == SAVE_NAME:
        return []                                       # 没配改名：老逻辑就是对的
    olds = (SAVE_NAME, SAVE_NAME + ".bak")
    news = (names["main"], names["bak"])
    targets = []
    liv = live_dir()
    if liv:
        targets.append((liv, None))
    br = bank_root(pack)
    if os.path.isdir(br):
        for n in sorted(os.listdir(br)):
            d = os.path.join(br, n)
            if os.path.isdir(d) and n != RECYCLE_DIRNAME:
                targets.append((d, n))
    done = []
    for d, label in targets:
        if not os.path.isdir(d):
            continue
        if os.path.isfile(os.path.join(d, news[0])):
            continue                                    # 已经是新名字：迁过了
        if not os.path.isfile(os.path.join(d, olds[0])):
            continue
        for o, nw in zip(olds, news):
            src, dst = os.path.join(d, o), os.path.join(d, nw)
            if not os.path.isfile(src):
                continue
            try:
                backup_file(src, "改名迁移_%s" % (label or "live"), pack)
            except Exception:
                pass
            try:
                os.replace(src, dst)
            except Exception:
                shutil.copy2(src, dst)
                _rm(src)
            done.append(dst)
        if label:
            mp = os.path.join(d, SLOT_META)
            if os.path.isfile(mp):
                try:
                    m = json.load(open(mp, encoding="utf-8"))
                except Exception:
                    m = {}
                m["save_name"] = news[0]
                m["files"] = [news[0], news[1]]
                try:
                    with open(mp, "w", encoding="utf-8") as fp:
                        json.dump(m, fp, ensure_ascii=False, indent=1)
                except Exception:
                    pass
        say("存档改名迁移（%s）：%s → %s" % (label or "live", olds[0], news[0]))
    return done


def status(layer_dir=None, pack=None):
    """给界面用的一次性快照（只读，任何动作之前先调它）"""
    pack = pack or (pack_of_layer(layer_dir) if layer_dir else "") or pack_root()
    try:
        migrate_legacy_saves(pack)      # 老 .sl2 槽先改名成游戏实际读的那个（幂等）
    except Exception:
        pass
    label = plan_label(layer_dir) if layer_dir else None
    cur = current_label(pack)
    liv = live_dir()
    nm = save_names(pack)
    out = {"pack": pack, "running": game_running(), "live_dir": liv,
           "save_name": nm["main"], "seamless_name": nm["seamless"],
           "current": cur,
           "bank_root": os.path.join(pack, BANK_DIRNAME),
           "label": label,
           "bank": bank_status(label, pack) if label else None,
           "active_state": read_state(pack)}
    if liv:
        f = os.path.join(liv, nm["main"])
        out["live_at"] = os.path.getmtime(f) if os.path.isfile(f) else 0
        out["live_size"] = os.path.getsize(f) if os.path.isfile(f) else 0
    return out


_CUR_OVERRIDE = None       # 自检用：强制"当前挂的是哪个方案"（None = 读真的 YAFSML.ini）


def _cur_label(pack=None):
    return _CUR_OVERRIDE if _CUR_OVERRIDE is not None else current_label(pack)


def prepare_save(label, pack=None, allow_new_save=False, out=None, force=False):
    """换档那一半（**不挂载、不起游戏**）：回存上一个方案 → 换入本方案的档 / 开新档。

    单独摘出来是为了让自检只测这一段 —— 不碰真的 YAFSML.ini、不真起游戏。
    """
    pack = pack or pack_root()
    try:
        migrate_legacy_saves(pack)
    except Exception:
        pass
    out = out if out is not None else {}
    cur = _cur_label(pack)
    liv = live_dir()
    main = _save_pair(pack)[0]
    out.update({"label": label, "banked_from": None, "fresh": False,
                "restored": False, "live": liv, "save_name": main})
    has_live = bool(liv and live_files(liv, pack=pack))
    if force:
        pass                                    # 自检用：跳过"live 目录必须存在"的强要求

    # ① 上一个方案的进度先回存（换方案前那一次确实是在玩上一个方案）
    if cur and cur != label and has_live:
        bank_save(cur, pack=pack, note="切到 %s 之前" % label, live=liv)
        out["banked_from"] = cur

    if label == cur:
        # 已经挂着它：正常情况下档也就是它的。但 live 里要是**没有这一对**（上次清档后
        # 游戏没起来 / 被别的工具挪走），就把槽里的换回来 —— 否则游戏会当作没有存档。
        if has_live or not liv:
            return out
        if os.path.isfile(os.path.join(bank_dir(label, pack), main)):
            backup_live(label, pack=pack, live=liv)
            restore_to_live(label, pack=pack, live=liv)
            out["restored"] = True
        return out

    # ② 换档
    if not liv:
        raise GameError("找不到游戏存档目录（%%APPDATA%%\\EldenRing\\<SteamID>）。"
                        "先正常启动一次游戏，让游戏自己建出存档目录。")
    backup_live(label, pack=pack, live=liv)           # 删/覆盖前先留底
    has_bank = os.path.isfile(os.path.join(bank_dir(label, pack), main))
    if has_bank:
        restore_to_live(label, pack=pack, live=liv)
        out["restored"] = True
    else:
        if not allow_new_save:
            raise NeedsNewSave(label, cur, liv)
        # 旧档不是"上一个方案"的就是法魂本体的：先归到本体槽
        if not cur and has_live:
            bank_save(BODY_LABEL, pack=pack, note="第一次用方案库之前", live=liv)
        clear_live(pack=pack, live=liv)
        out["fresh"] = True
    return out


def launch(layer_dir, allow_new_save=False, pack=None, _force=False,
           kill_running=False, log=None):
    """用这个方案启动游戏。

    顺序：查进程（可选先关掉）→ 把**上一个方案**的进度回存 → 换入目标方案的档（没有就新档）
          → 挂载 → 起游戏。
    没有槽且 allow_new_save=False 时抛 NeedsNewSave，界面拿它去问人（不弹窗、不猜）。
    kill_running=True：游戏在跑就先请它退出（等不到再强杀）—— 调用方负责问过人。
    """
    pack = pack or pack_of_layer(layer_dir) or pack_root()
    try:
        migrate_legacy_saves(pack)
    except Exception:
        pass
    if not _force and game_running():
        if not kill_running:
            raise GameError("游戏正在运行 —— 先退出游戏再切方案（运行中换档会写坏存档）")
        kill_game(log=log)
    import plan_layer as PL
    ld = os.path.abspath(layer_dir)
    if not os.path.isdir(os.path.join(ld, "mod")):
        raise GameError("这个方案还没有覆盖层（先写入游戏一次）：%s" % ld)
    label = plan_label(ld)
    # 每次开玩都把层目录里的两个启动 bat 重写成「这台机器」的 exe 路径：
    # 方案层整个拷到别的电脑 / 别的位置时，bat 里旧路径就失效了。
    try:
        PL.make_launchers(ld, label, log=log)
    except Exception:
        pass
    out = {"layer": ld}
    prepare_save(label, pack=pack, allow_new_save=allow_new_save, out=out, force=_force)

    # ③ 挂载 + 起游戏
    PL.set_plan(ld)
    launch_bat(pack)
    write_state(label, pack=pack, live=out.get("live"))
    out["started"] = _now()
    return out


def finish(pack=None):
    """游戏退出后：把这次玩的存档存回它自己的槽（界面轮询进程结束时调）"""
    pack = pack or pack_root()
    try:
        migrate_legacy_saves(pack)
    except Exception:
        pass
    st = read_state(pack)
    if not st:
        return None
    if game_running():
        raise GameError("游戏还在运行，不能回存存档")
    label = st.get("label") or ""
    liv = live_dir()
    if not label:
        clear_state(pack)
        return None
    try:
        meta = bank_save(label, pack=pack, note="退出回存", live=liv)
    except GameError:
        meta = None
    clear_state(pack)
    return {"label": label, "saved": (meta or {}).get("saved", ""),
            "ok": bool(meta), "live": liv}


def recover(pack=None):
    """应用启动时调：上次游戏退出时程序没开着（或者被杀了），补一次回存"""
    pack = pack or pack_root()
    st = read_state(pack)
    if not st or game_running():
        return None
    return finish(pack)


def switch_to_body(pack=None, log=None):
    """切回法魂本体：把**当前方案**的进度存回它的槽 → 把本体的档换进游戏存档目录。

    以前 `--plan-off` 只清 ini 里的 `Plan=`、**不换档** —— 于是「切回本体」玩到的还是
    上一个方案的档（独立存档只做了一半，2026-10-23 作者实测时一起报了）。
    没挂方案、也没有启动记录时什么都不动（本来就是本体）。
    """
    pack = pack or pack_root()
    try:
        migrate_legacy_saves(pack)
    except Exception:
        pass
    say = log or (lambda *_a, **_k: None)
    liv = live_dir()
    out = {"live": liv, "banked": None, "restored": False}
    if not liv or game_running():
        return out
    cur = current_label(pack)
    st = read_state(pack)
    owner = (st or {}).get("label") or cur
    out["from"] = owner
    if not owner or owner == BODY_LABEL:
        return out                                  # 本来就是本体：不用换
    if live_files(liv, pack=pack):
        try:
            bank_save(owner, pack=pack, note="切回本体之前的回存", live=liv)
            out["banked"] = owner
            say("上一个方案「%s」的进度已存回它的槽" % owner)
        except GameError as e:
            say("回存上一个方案失败（不挡着切回本体）：%s" % e)
    backup_live("切回本体", pack=pack, live=liv)
    main = _save_pair(pack)[0]
    if os.path.isfile(os.path.join(bank_dir(BODY_LABEL, pack), main)):
        restore_to_live(BODY_LABEL, pack=pack, live=liv)
        out["restored"] = True
        say("已把「%s」的存档换回来" % BODY_LABEL)
    else:
        say("本体还没有存档槽 —— 当前存档原样留着（下次退出会存进本体槽）")
    clear_state(pack)
    return out


# ────────────────────────── 自检 ──────────────────────────

def selftest():
    import tempfile
    global _CUR_OVERRIDE
    ok = []
    base = tempfile.mkdtemp(prefix="_gfswap_")
    _CUR_OVERRIDE = ""                         # 别让真的 YAFSML.ini 干扰自检
    try:
        root = os.path.join(base, "appdata", "EldenRing", "111")
        os.makedirs(root)
        live = os.path.join(base, "appdata", "EldenRing", "111")
        os.environ["ER_SAVE_ROOT"] = os.path.join(base, "appdata", "EldenRing")
        os.environ["ER_SAVE_DIR"] = live
        open(os.path.join(live, SAVE_NAME), "wb").write(b"AAA")
        open(os.path.join(live, SAVE_NAME + ".bak"), "wb").write(b"AAA-BAK")
        pack = os.path.join(base, "pack")
        os.makedirs(os.path.join(pack, "yafsml"))
        open(os.path.join(pack, "yafsml", "YAFSML.ini"), "w", encoding="utf-8").close()

        assert live_dir() == live, "live_dir 没认出来"
        assert len(live_files(live, pack=pack)) == 2

        # ① 存槽：应该连 .bak 一起存，且留下 meta
        bank_save("方案A", pack=pack, live=live)
        st = bank_status("方案A", pack=pack)
        assert st["has"] and st["size"] == 3, st
        assert st["files"] == [SAVE_NAME, SAVE_NAME + ".bak"], st["files"]
        ok.append("存槽")

        # ② 换档：槽里的内容换回 live
        open(os.path.join(live, SAVE_NAME), "wb").write(b"BBB")
        restore_to_live("方案A", pack=pack, live=live)
        assert open(os.path.join(live, SAVE_NAME), "rb").read() == b"AAA"
        ok.append("换档")

        # ③ 删档前留底（_回收 可能还不存在，第一次备份才会建出来）
        def _nrec():
            d = os.path.join(pack, BANK_DIRNAME, RECYCLE_DIRNAME)
            return len(os.listdir(d)) if os.path.isdir(d) else 0
        n_ok = _nrec()
        backup_live("测试", pack=pack, live=live)
        n2 = _nrec()
        assert n2 > n_ok, (n_ok, n2)
        ok.append("留底")

        # ④ 清档：两个文件都要没，不给游戏留旧 .bak
        clear_live(pack=pack, live=live)
        assert not live_files(live, pack=pack), live_files(live, pack=pack)
        ok.append("清档")

        # ⑤ 没槽的新方案要人确认，不能默默开新档
        #    （只测换档那一半：prepare_save 不碰 YAFSML.ini、不真起游戏）
        os.makedirs(os.path.join(pack, "mod"))
        open(os.path.join(pack, "mod", "regulation.bin"), "wb").write(b"R")
        layer = os.path.join(pack, "方案", "方案B")
        os.makedirs(os.path.join(layer, "mod"))
        open(os.path.join(layer, "mod", "regulation.bin"), "wb").write(b"R")
        try:
            prepare_save(plan_label(layer), pack=pack, allow_new_save=False, force=True)
            raise AssertionError("没槽的方案应该抛 NeedsNewSave")
        except NeedsNewSave:
            ok.append("新档要确认")

        # ⑥ 允许新档时：旧档先进本体槽，live 清空
        open(os.path.join(live, SAVE_NAME), "wb").write(b"CCC")
        out = prepare_save(plan_label(layer), pack=pack, allow_new_save=True, force=True)
        assert out["fresh"] is True, out
        assert not live_files(live, pack=pack), "开新档后 live 应该没有档"
        assert bank_status(BODY_LABEL, pack=pack)["has"], "旧档没进本体槽"
        ok.append("开新档留旧")

        # ⑦ 关游戏：没在跑的时候应该什么都不做（不误杀；真在跑时这条跳过 —— 不能为了自检杀人的游戏）
        if not game_running():
            assert kill_game(timeout=1) is False, "没游戏在跑时 kill_game 应该返回 False"
            ok.append("没游戏不误杀")

        # ⑧ 僵尸壳不算「在跑」（2026-10-23：游戏退出后 tasklist 仍挂着名字，把启动一直挡住）
        assert _pid_is_gone(os.getpid()) is False, "活着的进程被当成僵尸"
        assert game_running() == bool(game_pids()), "game_running 与 game_pids 口径不一致"
        ok.append("僵尸壳不算在跑")

        # ⑨ 认 YAFSML 的存档改名（replace_save_filename=.cnv）—— 法魂包默认就这么配。
        #    以前只认死 ER0000.sl2：换档"成功"、游戏里还是原来那批角色（独立存档没生效）。
        p2 = os.path.join(base, "pack_cnv")
        os.makedirs(os.path.join(p2, "yafsml"))
        open(os.path.join(p2, "yafsml", "YAFSML.ini"), "w", encoding="utf-8").write(
            "[patch]\nreplace_save_filename=.cnv\nreplace_seamless_coop_save_filename=.cnv.co2\n")
        nm = save_names(p2)
        assert nm["main"] == "ER0000.cnv" and nm["bak"] == "ER0000.cnv.bak", nm
        live2 = os.path.join(base, "live_cnv")
        os.makedirs(live2)
        open(os.path.join(live2, "ER0000.cnv"), "wb").write(b"CNV")
        open(os.path.join(live2, "ER0000.cnv.bak"), "wb").write(b"CNV-BAK")
        assert len(live_files(live2, pack=p2)) == 2, live_files(live2, pack=p2)
        bank_save("方案C", pack=p2, live=live2)
        assert bank_status("方案C", pack=p2)["files"] == ["ER0000.cnv", "ER0000.cnv.bak"]
        open(os.path.join(live2, "ER0000.cnv"), "wb").write(b"XXX")
        restore_to_live("方案C", pack=p2, live=live2)
        assert open(os.path.join(live2, "ER0000.cnv"), "rb").read() == b"CNV"
        ok.append("认 .cnv 改名")

        # ⑩ 老存档（.sl2 时代存的）要自动改名成游戏现在读的 .cnv —— 不改玩家会"档还在但游戏看不到"
        p3 = os.path.join(base, "pack_mig")
        os.makedirs(os.path.join(p3, "yafsml"))
        open(os.path.join(p3, "yafsml", "YAFSML.ini"), "w", encoding="utf-8").write(
            "[patch]\nreplace_save_filename=.cnv\nreplace_seamless_coop_save_filename=.cnv.co2\n")
        open(os.path.join(live, SAVE_NAME), "wb").write(b"OLD-LIVE")
        open(os.path.join(live, SAVE_NAME + ".bak"), "wb").write(b"OLD-LIVE-BAK")
        sd = os.path.join(p3, BANK_DIRNAME, "方案D")
        os.makedirs(sd)
        open(os.path.join(sd, SAVE_NAME), "wb").write(b"OLD-SLOT")
        open(os.path.join(sd, SAVE_NAME + ".bak"), "wb").write(b"OLD-SLOT-BAK")
        with open(os.path.join(sd, SLOT_META), "w", encoding="utf-8") as fp:
            json.dump({"label": "方案D", "files": [SAVE_NAME]}, fp)
        got = migrate_legacy_saves(p3)
        assert os.path.isfile(os.path.join(live, "ER0000.cnv"))
        assert not os.path.isfile(os.path.join(live, SAVE_NAME))
        assert os.path.isfile(os.path.join(sd, "ER0000.cnv"))
        assert not os.path.isfile(os.path.join(sd, SAVE_NAME))
        assert open(os.path.join(sd, "ER0000.cnv"), "rb").read() == b"OLD-SLOT"
        assert migrate_legacy_saves(p3) == [], "迁移要幂等"
        ok.append("老 .sl2 槽自动改名")
    finally:
        _CUR_OVERRIDE = None
        shutil.rmtree(base, ignore_errors=True)
        os.environ.pop("ER_SAVE_DIR", None)
        os.environ.pop("ER_SAVE_ROOT", None)
    print("[gamelib 自检] PASS：" + " / ".join(ok))
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="方案库启动器 + 独立存档")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--launch", metavar="层目录")
    ap.add_argument("--new", action="store_true", help="没槽时允许开新档")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.launch:
        try:
            r = launch(a.launch, allow_new_save=a.new)
        except NeedsNewSave as e:
            print(str(e))
            return 2
        except GameError as e:
            print("启动失败：%s" % e)
            return 1
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(status(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
