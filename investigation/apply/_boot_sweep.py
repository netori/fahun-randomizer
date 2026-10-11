# _boot_sweep.py — 每一种配置：生成方案 → 写入 → 真启动游戏 → 判定 → 清理
#   判定标准：eldenring 进程内存 > 1200MB（真正加载完成）且随后 15 秒仍存活
import csv, importlib.util, os, shutil, subprocess, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
sys.path.insert(0, APPLY)
ENGINE = os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py")
spec = importlib.util.spec_from_file_location("r", ENGINE)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
import native_deploy as nd

MOD = nd.MOD
REG = os.path.join(MOD, "mod", "regulation.bin")
MSG = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
BAT = os.path.join(MOD, "启动法魂.bat")
OUT = os.path.join(APPLY, "out")
LOG = os.path.join(APPLY, "logs")
COLS = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
        "source_table", "row_id", "slot", "row_name"]

CONFIGS = [
    # (名称, 勾选, 混合?, 合理度, 改动比例)
    ("全部混合 80%",        ["rune", "armor", "weapon"], True,  0.8, 1.0),
    ("全部混合 100%",       ["rune", "armor", "weapon"], True,  1.0, 1.0),
    ("全部混合 0%",         ["rune", "armor", "weapon"], True,  0.0, 1.0),
    ("各自随机 80%",        ["rune", "armor", "weapon"], False, 0.8, 1.0),
    ("卢恩+护甲 50%",       ["rune", "armor"],           True,  0.5, 1.0),
    ("卢恩+装备 50%",       ["rune", "weapon"],          True,  0.5, 1.0),
    ("护甲+装备 50%",       ["armor", "weapon"],         True,  0.5, 1.0),
    ("只护甲 50%",          ["armor"],                   False, 0.5, 1.0),
    ("只卢恩 50%",          ["rune"],                    False, 0.5, 1.0),
    ("只装备 50%",          ["weapon"],                  False, 0.5, 1.0),
    ("全部混合 50% 密度40%", ["rune", "armor", "weapon"], True,  0.5, 0.4),
    ("全部混合 25% 不拆套装", ["rune", "armor", "weapon"], True,  0.25, 1.0),
    ("全部混合 50% 幽影并入", ["rune", "armor", "weapon"], True,  0.5, 1.0),
    ("全部混合 50% 不改说明书", ["rune", "armor", "weapon"], True, 0.5, 1.0),
]


def kill_game(wait=45):
    subprocess.run(["taskkill", "/F", "/IM", "eldenring.exe"], capture_output=True)
    time.sleep(wait)


def launch_and_watch(timeout=200, hold=20, log=print):
    """启动游戏并判定是否真正加载成功"""
    kill_game()
    subprocess.Popen(["cmd.exe", "/c", BAT], cwd=MOD, shell=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.time()
    best = 0
    seen = False
    while time.time() - t0 < timeout:
        time.sleep(3)
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process eldenring -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | "
             "Select-Object -First 1 | ForEach-Object { [int]($_.WorkingSet64/1MB) })"],
            capture_output=True, text=True)
        try:
            mb = int((ps.stdout or "0").strip() or 0)
        except ValueError:
            mb = 0
        if mb > 0:
            seen = True
            best = max(best, mb)
            if mb > 4500:
                # 再观察 hold 秒，确认稳定
                time.sleep(hold)
                ps2 = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-Process eldenring -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | "
                     "Select-Object -First 1 | ForEach-Object { [int]($_.WorkingSet64/1MB) })"],
                    capture_output=True, text=True)
                try:
                    mb2 = int((ps2.stdout or "0").strip() or 0)
                except ValueError:
                    mb2 = 0
                if mb2 > 4500:
                    return True, f"进入了游戏（{mb2} MB，{int(time.time()-t0)} 秒）"
                return False, f"加载后退出（峰值 {best} MB → 观察期 {mb2} MB）"
        elif seen:
            return False, f"启动后进程消失（峰值 {best} MB）"
    return False, f"超时未进入（峰值 {best} MB）"


def make_plan(name, doms, cross, coh, den, sets=True, shadow=False, seed=20261010):
    cfg = {"domains": list(doms), "joins": [], "basis": "guide", "shops": False,
           "merge_shadow": shadow, "sets": sets, "seed": seed, "coherence": coh,
           "density": den, "cross_domain": cross}
    items = r.load_world(False, "guide")
    plan, pools, _s = r.run(items, cfg, seed)
    path = os.path.join(OUT, "boot_" + name.replace(" ", "_").replace("%", "") + ".csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for p in sorted(plan, key=lambda x: (x["pool"], x["unit"], x["source_table"], x["row_id"], x["slot"])):
            w.writerow({k: p.get(k, "") for k in COLS})
    return path, cfg


def main():
    results = []
    print(f"  共 {len(CONFIGS)} 种配置，每种：写入 → 启动 → 判定\n", flush=True)
    for idx, (name, doms, cross, coh, den) in enumerate(CONFIGS, 1):
        sets = "不拆套装" not in name
        shadow = "幽影并入" in name
        sync_guide = "不改说明书" not in name
        print(f"  ── [{idx}/{len(CONFIGS)}] {name} ──", flush=True)
        try:
            plan_csv, cfg = make_plan(name, doms, cross, coh, den, sets, shadow)
            rec = nd.deploy(plan_csv, sync_guide=sync_guide, log=lambda s: None)
            ok_dep = bool(rec.get("verify"))
            ok, msg = launch_and_watch(log=print)
            results.append((name, ok_dep, ok, msg))
            print(f"     结果: {'成功进入 ✓' if ok else '失败 ✗'} ｜ {msg}", flush=True)
        except Exception as e:
            import traceback
            results.append((name, False, False, f"异常 {type(e).__name__}: {e}"))
            print("     异常:", traceback.format_exc(limit=2), flush=True)
        kill_game()
    # 收尾：恢复原始
    kill_game()
    shutil.copy2(nd.find_original("regulation.bin.orig_*"), REG)
    shutil.copy2(nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), MSG)
    print("\n  ══ 汇总 ══", flush=True)
    for name, ok_dep, ok, msg in results:
        print(f"   {'✓' if ok else '✗'} {name:<22} 写入{'正常' if ok_dep else '失败'} ｜ {msg}", flush=True)
    bad = [x for x in results if not x[2]]
    print(f"\n   成功 {len(results)-len(bad)}/{len(results)}；已恢复原始文件 ✓", flush=True)
    open(os.path.join(LOG, "boot_sweep.txt"), "w", encoding="utf-8").write(
        "\n".join(f"{name}\t{dep}\t{ok}\t{msg}" for name, dep, ok, msg in results))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
