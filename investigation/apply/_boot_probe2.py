# _boot_probe2.py — 第二轮细分：哪一类改动让游戏崩溃
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
COLS = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
        "source_table", "row_id", "slot", "row_name"]
DOMS = {"rune": ("goods",), "armor": ("protector",), "weapon": ("weapon",)}


def kill(wait=45):
    subprocess.run(["taskkill", "/F", "/IM", "eldenring.exe"], capture_output=True)
    time.sleep(wait)


def mem():
    ps = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
        "(Get-Process eldenring -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | "
        "Select-Object -First 1 | ForEach-Object { [int]($_.WorkingSet64/1MB) })"], capture_output=True, text=True)
    try:
        return int((ps.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def boot(tag, timeout=200, hold=20):
    kill()
    subprocess.Popen(["cmd.exe", "/c", BAT], cwd=MOD,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.time(); best = 0; seen = False
    while time.time() - t0 < timeout:
        time.sleep(4)
        m = mem()
        if m:
            seen = True; best = max(best, m)
            if m > 4500:
                t1 = time.time()
                while time.time() - t1 < hold:
                    time.sleep(5)
                    m2 = mem(); best = max(best, m2)
                    if m2 == 0:
                        print(f"   ✗ {tag}: 进入后退出（峰值 {best}MB）", flush=True); return False
                print(f"   ✓ {tag}: 稳定进入（{best}MB，{int(time.time()-t0)}s）", flush=True); return True
        elif seen:
            print(f"   ✗ {tag}: 加载中崩溃（峰值 {best}MB，{int(time.time()-t0)}s）", flush=True); return False
    print(f"   ✗ {tag}: 超时（峰值 {best}MB）", flush=True); return False


def pristine():
    shutil.copy2(nd.find_original("regulation.bin.orig_*"), REG)
    shutil.copy2(nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), MSG)


def gen(name, doms, cross=True, coh=0.5, seed=20261010):
    cfg = {"domains": list(doms), "joins": [], "basis": "guide", "shops": False, "merge_shadow": False,
           "sets": True, "seed": seed, "coherence": coh, "density": 1.0, "cross_domain": cross}
    items = r.load_world(False, "guide")
    plan, _p, _s = r.run(items, cfg, seed)
    path = os.path.join(APPLY, "out", f"bisect_{name}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
        for p in sorted(plan, key=lambda x: (x["pool"], x["unit"], x["source_table"], x["row_id"], x["slot"])):
            w.writerow({k: p.get(k, "") for k in COLS})
    return path


def filter_plan(src, dst, only_doms=None, only_table=None, limit=None, skip=None):
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    out = []
    for p in rows:
        if p["old"] == p["new"]:
            out.append(p); continue
        cat = p.get("new_cat") or ""
        if only_doms and cat not in [c for d in only_doms for c in DOMS[d]]:
            out.append(dict(p, new=p["old"], new_cat=p["old_cat"])); continue
        if only_table and p.get("source_table") not in only_table:
            out.append(dict(p, new=p["old"], new_cat=p["old_cat"])); continue
        out.append(p)
    if limit is not None:
        n = 0
        for i, p in enumerate(out):
            if p["old"] != p["new"]:
                n += 1
                if n > limit:
                    out[i] = dict(p, new=p["old"], new_cat=p["old_cat"])
    if skip:
        n = 0
        for i, p in enumerate(out):
            if p["old"] != p["new"]:
                n += 1
                if n <= skip:
                    out[i] = dict(p, new=p["old"], new_cat=p["old_cat"])
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
        for p in out:
            w.writerow({k: p.get(k, "") for k in COLS})
    return dst


def main():
    base = gen("base_全混合50", ["rune", "armor", "weapon"], True, 0.5)
    print(f"  基准计划: {base}\n", flush=True)
    tests = []

    def run_case(name, csv_path):
        pristine()
        nd.deploy(csv_path, sync_guide=False, log=lambda s: None)
        ok = boot(name)
        tests.append((name, ok))

    run_case("① 只改护甲", filter_plan(base, os.path.join(APPLY, "out", "bis_armor.csv"), only_doms=["armor"]))
    run_case("② 只改卢恩", filter_plan(base, os.path.join(APPLY, "out", "bis_rune.csv"), only_doms=["rune"]))
    run_case("③ 只改装备", filter_plan(base, os.path.join(APPLY, "out", "bis_weapon.csv"), only_doms=["weapon"]))
    run_case("④ 只改前 30 格", filter_plan(base, os.path.join(APPLY, "out", "bis_first30.csv"), limit=30))
    run_case("⑤ 只改后 30 格", filter_plan(base, os.path.join(APPLY, "out", "bis_last30.csv"), skip=436))

    kill(5)
    pristine()
    print("\n  ══ 第二轮结果 ══", flush=True)
    for name, ok in tests:
        print(f"   {'✓ 成功' if ok else '✗ 崩溃'}  {name}", flush=True)
    print("\n   已恢复原始文件 ✓", flush=True)
    with open(os.path.join(APPLY, "logs", "boot_bisect2.txt"), "w", encoding="utf-8") as f:
        for name, ok in tests:
            f.write(f"{name}\t{ok}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
