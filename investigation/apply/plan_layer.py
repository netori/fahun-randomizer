# -*- coding: utf-8 -*-
"""方案层（plan layer）：把一次随机的产物做成"覆盖层"，用 YAFSML 的 [mod] 列表挂载。

为什么这么做（本机实测的依据）：
* `yafsml\\YAFSML.ini` 的 `[mod]` 段原文：“扫描并覆盖游戏数据的模组目录；
  **后声明的模组覆盖先声明的模组中的同名文件**” → 加一行就是覆盖层。
* YAFSML 是**运行时注入**式加载器（`使用说明.md`：游戏目录里的文件一个都不会被改）。
* 关键体积：`regulation.bin` 只有 ~2.9 MB → 每个方案存一份完全可行；
  地图是按**文件**覆盖，所以方案层只放**改过的那几张**（每张 ~0.4 MB）。

于是：
    方案/<标签>/
      mod/regulation.bin                      ← 部署完的那份（物品+敌人一起）
      mod/map/MapStudio/<改过的>.msb.dcx       ← 只有二期真换敌人时才有
      mod/msg/zhocn/item_dlc02.msgbnd.dcx      ← 只有同步了说明书时才有
      用这个方案启动.bat / 切回法魂本体.bat / 方案信息.txt

切换 = 在 ini 的 [mod] 段里加/删一行 `Plan=...`；法魂本体（`Convergence=../mod`）**永不动**。

命令行：
    python plan_layer.py --export --label 20261016_2030_敌人全随     # 产出方案层
    python plan_layer.py --activate <方案目录>                        # 把该方案挂上去
    python plan_layer.py --deactivate                                 # 切回法魂本体
    python plan_layer.py --list                                       # 看现有方案与当前挂载
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER          # noqa: E402

PLAN_LINE = "Plan="
SECTION_MOD = "[mod]"


# ────────────────────────── 路径 ──────────────────────────

def mod_root():
    """法魂包的 mod 目录 —— 就是 regulation.bin 所在的那个目录。

    ⚠️ ER._mod_reg() 返回的是 `<法魂包>/mod/regulation.bin` 这个**文件**路径，
    所以只要 **一次** dirname。这里带自检，免得又差一层（本会话在这上面栽过两次）。
    """
    d = os.path.dirname(os.path.abspath(ER._mod_reg()))
    assert os.path.isfile(os.path.join(d, "regulation.bin")), f"mod_root 不对：{d}"
    return d


def pack_root():
    """法魂包根目录（yafsml/ 与 启动法魂.bat 所在处）"""
    d = os.path.dirname(mod_root())
    assert os.path.isdir(os.path.join(d, "yafsml")), f"pack_root 不对（没有 yafsml/）：{d}"
    return d


def ini_path():
    return os.path.join(pack_root(), "yafsml", "YAFSML.ini")


def plans_root():
    return os.path.join(pack_root(), "方案")


# ────────────────────────── ini 读写（保留注释，只动 [mod] 段）──────────────────────────

def _read_text(p):
    """按字节判编码，**并且记住有没有 BOM** —— 写回时要一模一样。

    （踩过：原文件没有 BOM，我却按 utf-8-sig 写回，多出 3 个字节 → 还原后不是逐字节一致。）
    同时按字节判行尾（CRLF/LF），写回时保持一致。
    """
    raw = open(p, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    for enc in (("utf-8-sig" if bom else "utf-8"), "utf-8", "gbk"):
        try:
            t = raw.decode(enc)
            eol = "\r\n" if b"\r\n" in raw[:4096] else "\n"
            return t, enc, bom, eol
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8", False, "\n"


def read_ini():
    """按**实际行尾**切分（CRLF 文件里若按 "\n" 切，行尾会变成 \r\r\n —— 踩过）。"""
    t, enc, bom, eol = _read_text(ini_path())
    return t.split(eol), (enc, bom, eol)


def write_ini(lines, meta):
    """写回时保持：编码、BOM 有无、行尾风格 —— 目标是"除了我们改的那行，逐字节不变"。"""
    enc, bom, eol = meta
    p = ini_path()
    bak = p + ".bak_planlayer_" + time.strftime("%Y%m%d_%H%M%S")
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    text = eol.join(lines)
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    elif enc == "gbk":
        data = text.encode("gbk", "replace")
    with open(p, "wb") as f:
        f.write(data)
    return bak


def current_plan_line():
    lines, _m = read_ini()
    for ln in lines:
        if ln.strip().startswith(PLAN_LINE):
            return ln.strip()[len(PLAN_LINE):]
    return None


def set_plan(rel_or_abs):
    """把 [mod] 段的 Plan=... 设成给定目录（相对 yafsml/ 或绝对路径）。

    规则：`Convergence=../mod` 必须是**第一层**（保持不动）；我们只在它**之后**加一行。
    已有的 Plan= 行会被换成新的（保证同时只有一个方案生效）。
    """
    lines, meta = read_ini()
    # 找 [mod] 段范围
    try:
        i = next(k for k, ln in enumerate(lines) if ln.strip().lower() == SECTION_MOD)
    except StopIteration:
        raise RuntimeError("YAFSML.ini 里找不到 [mod] 段，先手工确认模板是否被改过")
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith("["):
        j += 1
    seg = lines[i + 1:j]
    seg = [ln for ln in seg if not ln.strip().startswith(PLAN_LINE)]
    # 插在 Convergence 行之后（没有就追加到段尾）
    pos = None
    for k, ln in enumerate(seg):
        if ln.strip().lower().startswith("convergence="):
            pos = k + 1
    new_line = PLAN_LINE + rel_or_abs
    seg.insert(pos if pos is not None else len(seg), new_line)
    lines[i + 1:j] = seg
    bak = write_ini(lines, meta)
    return {"ini": ini_path(), "backup": bak, "plan": rel_or_abs,
            "rel": os.path.relpath(rel_or_abs, os.path.dirname(ini_path()))
            if os.path.isabs(rel_or_abs) else rel_or_abs}


def clear_plan():
    lines, meta = read_ini()
    out = [ln for ln in lines if not ln.strip().startswith(PLAN_LINE)]
    if len(out) == len(lines):
        return {"ini": ini_path(), "changed": False}
    bak = write_ini(out, meta)
    return {"ini": ini_path(), "backup": bak, "changed": True}


# ────────────────────────── 产出方案层 ──────────────────────────

def _sha(p, n=16):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:n] if os.path.isfile(p) else ""


def export_layer(label=None, extra_files=None, log=print):
    """把**当前已部署**的 mod 产物抄进一个方案层目录。

    extra_files：额外要进层的东西（二期换敌人的地图），给 [(源绝对路径, 层内相对路径), …]
    """
    mr, pr = mod_root(), plans_root()
    label = label or time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(pr, label)
    dest_mod = os.path.join(dest, "mod")
    os.makedirs(dest_mod, exist_ok=True)
    log(f"[方案层] 法魂包 = {pack_root()}")
    log(f"[方案层] 目录   = {dest}")

    got = []
    # ① regulation.bin（部署完的那份）
    src = os.path.join(mr, "regulation.bin")
    if not os.path.isfile(src):
        raise RuntimeError(f"找不到 {src}")
    shutil.copy2(src, os.path.join(dest_mod, "regulation.bin"))
    got.append(("regulation.bin", 1, _sha(src), os.path.getsize(src)))

    # ② 说明书（只有跟原始备份不同才放 —— 不然白占 16 MB）
    rel_msg = os.path.join("msg", "zhocn", "item_dlc02.msgbnd.dcx")
    cur_msg = os.path.join(mr, rel_msg)
    orig_msg = _newest_orig("item_dlc02.msgbnd.dcx")
    if os.path.isfile(cur_msg) and orig_msg:
        if _sha(cur_msg) != _sha(orig_msg):
            os.makedirs(os.path.dirname(os.path.join(dest_mod, rel_msg)), exist_ok=True)
            shutil.copy2(cur_msg, os.path.join(dest_mod, rel_msg))
            got.append((rel_msg, 1, _sha(cur_msg), os.path.getsize(cur_msg)))
            log(f"[方案层] 说明书与原始不同 → 已放入（{os.path.getsize(cur_msg)/1048576:.1f} MB）")
        else:
            log("[方案层] 说明书与原始一致 → 不放（省 16 MB）")

    # ③ 额外文件（二期：改动过的地图）
    n = 0
    for s, rel in (extra_files or []):
        if not os.path.isfile(s):
            log(f"[方案层] 跳过不存在的：{s}")
            continue
        t = os.path.join(dest_mod, rel)
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(s, t)
        got.append((rel, 1, _sha(s), os.path.getsize(s)))
        n += 1
    if n:
        log(f"[方案层] 额外文件 {n} 个（地图等）")

    total = sum(g[3] for g in got)
    log(f"[方案层] 共 {len(got)} 个文件、{total/1048576:.1f} MB")
    return {"dir": dest, "mod": dest_mod, "files": got, "bytes": total, "label": label}


def _newest_orig(name):
    """找 apply/backup 下最新的一份原始备份（说明书/regulation 都有约定命名）"""
    bak = os.path.join(HERE, "backup")
    if not os.path.isdir(bak):
        return None
    cand = sorted((os.path.join(bak, f) for f in os.listdir(bak)
                   if f.startswith(name + ".orig_")), reverse=True)
    return cand[0] if cand else None


# ────────────────────────── 两个 .bat ──────────────────────────

BAT_LAUNCH = """@echo off
chcp 65001 > nul
title 用法魂方案启动 - {label}
echo.
echo   方案：{label}
echo   挂载：{dest_mod}
echo   本体：{mod_root}   （永不动）
echo.
python "{py}" --activate "{dest}"
if errorlevel 1 (
    echo.
    echo   [x] 挂载失败，请把上面的报错发我。
    pause
    exit /b 1
)
echo   开始启动游戏（关掉游戏后，想切回本体就双击 切回法魂本体.bat）...
call "{launch_bat}"
"""

BAT_REVERT = """@echo off
chcp 65001 > nul
title 切回法魂本体
python "{py}" --deactivate
echo.
echo   已切回法魂本体（下一次启动就是纯法魂）。
pause
"""


def make_launchers(dest, label, log=print):
    py = os.path.join(HERE, "plan_layer.py")
    launch_bat = os.path.join(pack_root(), "启动法魂.bat")
    d1 = os.path.join(dest, "用这个方案启动.bat")
    d2 = os.path.join(dest, "切回法魂本体.bat")
    with open(d1, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(BAT_LAUNCH.format(label=label, dest_mod=os.path.join(dest, "mod"),
                                  dest=dest, py=py, mod_root=mod_root(),
                                  launch_bat=launch_bat))
    with open(d2, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(BAT_REVERT.format(py=py))
    log(f"[方案层] 启动器：{os.path.basename(d1)} / {os.path.basename(d2)}")
    return d1, d2


def write_info(dest, meta, log=print):
    p = os.path.join(dest, "方案信息.txt")
    with open(p, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("法魂随机 · 方案层\r\n")
        f.write("生成时间：%s\r\n\r\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        for k, v in (meta or {}).items():
            f.write("%s：%s\r\n" % (k, v))
        f.write("\r\n挂载方式：在 yafsml\\YAFSML.ini 的 [mod] 段里加一行\r\n")
        f.write("    Plan=../方案/%s\r\n" % os.path.basename(dest))
        f.write("（后声明的层覆盖先声明的 —— 法魂本体那行 Convergence=../mod 必须在前）\r\n")
    return p


# ────────────────────────── 命令行 ──────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="法魂随机的方案层工具")
    ap.add_argument("--export", action="store_true", help="把当前已部署的产物产出成方案层")
    ap.add_argument("--label", help="方案名（默认时间戳）")
    ap.add_argument("--activate", metavar="DIR", help="挂载某个方案目录")
    ap.add_argument("--deactivate", action="store_true", help="切回法魂本体")
    ap.add_argument("--list", action="store_true", help="列出方案与当前挂载")
    a = ap.parse_args(argv)

    if a.export:
        r = export_layer(a.label)
        make_launchers(r["dir"], r["label"])
        meta = {"标签": r["label"], "文件数": len(r["files"]),
                "体积(MB)": round(r["bytes"] / 1048576, 1)}
        write_info(r["dir"], meta)
        print("方案层已生成：", r["dir"])
        return 0

    if a.activate:
        d = os.path.abspath(a.activate)
        if not os.path.isdir(os.path.join(d, "mod")):
            print(f"[x] {d} 下面没有 mod\\ 目录，不像是方案层")
            return 2
        r = set_plan(d)
        print("已挂载：", r["plan"])
        print("  写进 ", r["ini"], "（备份 ", r["backup"], "）")
        print("  下一次启动游戏就生效；切回本体用 --deactivate")
        return 0

    if a.deactivate:
        r = clear_plan()
        if not r["changed"]:
            print("本来就没有挂载方案（ini 里没有 Plan= 行）")
            return 0
        print("已移除 Plan= 行（备份 ", r["backup"], "）→ 下一次启动就是纯法魂本体")
        return 0

    # 默认：列出
    print("法魂包：", pack_root())
    print("ini   ：", ini_path())
    cur = current_plan_line()
    print("当前挂载：", cur or "（没有，跑的是纯法魂本体）")
    pr = plans_root()
    if os.path.isdir(pr):
        ds = sorted(os.listdir(pr), reverse=True)
        print("现有方案（%d 个）：" % len(ds))
        for d in ds[:12]:
            p = os.path.join(pr, d)
            sz = sum(os.path.getsize(os.path.join(r, f)) for r, _s, fs in os.walk(p) for f in fs)
            print("   %-34s %6.1f MB" % (d, sz / 1048576))
    else:
        print("还没有方案目录（%s）" % pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
