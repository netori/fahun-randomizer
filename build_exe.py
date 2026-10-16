#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_exe.py — 一条命令打出「玩家单独拿去也能用」的 exe

   ⚠️ 玩家侧前提：说明书那一步要用到游戏的 Oodle 压缩库（oo2core*.dll）。
      工具会自己找常见 Steam 安装位置、exe 旁的 oodle/ 或 game/ 目录；
      找不到时请让玩家把游戏 Game 目录里的 oo2core_*.dll 复制到 exe 旁边的 oodle/ 里。

   用法：
     python build_exe.py              # 同步资源 + 打包 + 隔离自检
     python build_exe.py --no-test    # 只打包

   它做三件事，顺序不能换：
     ① 同步 _assets/ —— 把当前源码里的运行时文件复制进去。
        ⚠️ 这一步最容易被忘：exe 运行时释放的是 _assets 里那份快照，
        改完源码不打这一步，发出去的还是旧代码（这个坑我们踩过）。
     ② 用 spec 打包（依赖桩 + hiddenimports + _assets 都在 spec 里）。
     ③ 隔离自检 —— 在一个**空目录**里跑新 exe 的
        --selftest / --planlib / --uicheck / --uitest 四道闸门。
        在开发目录里跑通不算数：开发目录里有整棵树，掩盖了"资源没打进去"的问题。
"""
import os
import shutil
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(WS, "_assets")
SPEC = "ConvergenceClassItemRandomizer.spec"

PIPELINE = ["erio.py", "param_layout.py", "param_patch.py", "fmg.py", "oodle.py",
            "native_apply.py", "native_deploy.py", "native_guide.py",
            "fix_guide.py", "_guide_rebuild.py", "_guide_fit.py", "_guide_audit.py",
            "planlib.py", "stale_cells.json",   # 陈旧格子清单：引擎 load_world 要读（缺了写前复核会中止写入）
            # 敌人随机（2026-10-16）+ 方案层：这几个是**运行时真的会被 import** 的，
            # 漏掉任何一个，打包版就会在"生成/写入"那一步炸（隔离自检不跑生成，抓不到）。
            "enemy_randomizer.py", "enemy_names.py", "enemy_types.py",
            "msb_read.py", "msb_write.py", "enemy_swapper.py", "plan_layer.py",
            "enemy_map_atlas.py", "boss_healthbar.py"]
ENGINE = "investigation/randomization-dryrun/scripts/randomizer.py"
DATA = ["investigation/randomization-catalog/bundles.json",
        "investigation/randomization-catalog/manifest.json",
        "investigation/randomization-catalog/evidence/lot_reward_index.json",
        "investigation/randomization-catalog/evidence/multicopy_exclude.json",
        "investigation/randomization-catalog-review/evidence/fixed_cells.json",
        "investigation/randomization-catalog-review/evidence/multicopy_exclude.json",
        "investigation/randomization-catalog-review/evidence/starter_set_freeze.json",
        "investigation/randomization-dryrun/evidence/shop_analysis.json",
        "investigation/randomization-dryrun/guide_candidate_draft.csv",
        "investigation/randomization-dryrun/class_candidate_draft.csv",
        # 敌人随机要用：它不只是名字表 —— 友好 NPC 的排除规则依赖它（缺了会把 NPC 也换掉）
        "investigation/enemy_table.csv",
        # 敌人随机的其余运行时数据（都是从法魂本体解包实测出来的表）
        "investigation/boss_rows.csv",        # 有血条 Boss ↔ NpcParam 行（228 个唯一行）
        "investigation/boss_healthbar.csv",   # 血条名单（Boss 显示名的权威来源）
        "investigation/row_models.csv",       # 行 → 地图上实际用的模型
        "investigation/enemy_type_map.csv",   # 模型 → 敌型（16 类）
        "investigation/map_enemies.csv",
        # 法魂新增行（原版 vs 法魂 的行级 diff 产物，786 行）——「只随机法魂敌人」的依据
        "investigation/convergence_new_rows.csv",
        # 参考实现（thefifthmatt）的人工标注转成我们自己的表：模型 → 档位/multi/打不死/真名
        "investigation/enemy_ref.csv",
        # 行级场地画像（来自 634 张图摆放台账）：npc_id → arena_min 等
        "investigation/row_arena.csv"] + [
        # Paramdex 的 ER paramdef（enemy_randomizer 运行时要读 XML 解析行表；
        # 以前漏了它 ⇒ exe 里"写入失败：读不到 Paramdex 定义：NpcParam"）
        os.path.join("tools", "witchybnd-3.0.1.0", "Assets", "Paramdex", "ER", "Defs", f)
        for f in sorted(os.listdir(os.path.join(WS, "tools", "witchybnd-3.0.1.0",
                                                "Assets", "Paramdex", "ER", "Defs")))
        if f.endswith(".xml")]      # 27780 条地图放置（真换敌人要用）
BASELINE = ["GoodsCaption.fmg.xml", "PlaceName.fmg.xml", "PlaceName_dlc01.fmg.xml", "PlaceName_dlc02.fmg.xml"]


def sync_assets():
    """把当前源码里的运行时文件同步进 _assets（保留形状，供打包与首运行释放）"""
    n = 0
    for f in PIPELINE:
        s = os.path.join(WS, "investigation", "apply", f)
        if os.path.exists(s):
            d = os.path.join(A, "investigation", "apply", f)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
        else:
            print(f"    ⚠ 缺 {f}")
    for rel in [ENGINE] + DATA:
        s = os.path.join(WS, rel)
        if os.path.exists(s):
            d = os.path.join(A, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
    for f in BASELINE:
        s = os.path.join(WS, "investigation", "apply", "work", "msg", "zh", f)
        if os.path.exists(s):
            d = os.path.join(A, "investigation", "apply", "work", "msg", "zh", f)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
    return n


def _dec(b):
    """子进程输出可能是 bytes（capture_output 的默认），解码再打印 —— 不解码就在这里炸"""
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    return b or ""


def main():
    if "--no-test" not in sys.argv:
        print("  ① 同步 _assets（把当前源码复制进去）…")
        n = sync_assets()
        print(f"     ✓ 同步 {n} 个文件")
    print("  ② 打包 …")
    # ⚠️ 必须清掉上次的构建缓存：PyInstaller 会复用 build_out 里的 datas 清单，
    #    于是打进 exe 的还是旧 _assets（这个坑我们踩过两次）。
    for d in ("build_out", "dist_out"):
        shutil.rmtree(os.path.join(WS, d), ignore_errors=True)
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "--distpath", "dist_out", "--workpath", "build_out", SPEC],
                       cwd=WS, capture_output=True)
    if r.returncode != 0:
        print("     ✗ 打包失败：")
        print("\n".join(_dec(r.stdout).splitlines()[-12:]))
        print("\n".join(_dec(r.stderr).splitlines()[-6:]))
        return 1
    exe = os.path.join(WS, "dist_out", "ConvergenceClassItemRandomizer.exe")
    print(f"     ✓ {os.path.getsize(exe)/1048576:.2f} MB")

    if "--no-test" in sys.argv:
        return 0
    print("  ③ 隔离自检（空目录，只放 exe）…")
    d = tempfile.mkdtemp(prefix="_iso_")
    shutil.copy2(exe, d)
    n_bad = 0
    try:
        # 四道闸门都要在**空目录**里过一遍：开发目录里有整棵树，会掩盖"资源没打进去"。
        # --uicheck / --uitest 会短暂开一个窗口（界面自检），属于预期。
        for flag, want in (("--selftest", "SELFTEST PASS"), ("--planlib", "PLANLIB PASS"),
                           ("--uicheck", "UICHECK PASS"), ("--uitest", "UITEST PASS")):
            try:
                r = subprocess.run([os.path.join(d, "ConvergenceClassItemRandomizer.exe"), flag],
                                   cwd=d, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired:
                print(f"     ✗ {flag} 超时（300 秒没结束）")
                n_bad += 1
                continue
            out = _dec(r.stdout) + _dec(r.stderr)
            ok = want in out
            print(f"     {'✓' if ok else '✗'} {flag}")
            if not ok:
                n_bad += 1
                print("\n".join(out.splitlines()[-14:]))
        return 0 if not n_bad else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
