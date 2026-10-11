# _boot_probe.py — 可靠的启动判定 + 二分定位
#   判据（实测校准）：>4500MB = 进入主菜单（成功）；≈3400MB 后进程消失 = 加载中崩溃
import os, shutil, subprocess, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import native_deploy as nd

MOD = nd.MOD
REG = os.path.join(MOD, "mod", "regulation.bin")
MSG = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
BAT = os.path.join(MOD, "启动法魂.bat")
GOOD = 4500      # MB：进入主菜单
GAP = 45         # 两次启动之间的冷却秒数


def kill(wait=GAP):
    subprocess.run(["taskkill", "/F", "/IM", "eldenring.exe"], capture_output=True)
    time.sleep(wait)


def mem():
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
        "(Get-Process eldenring -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | "
        "Select-Object -First 1 | ForEach-Object { [int]($_.WorkingSet64/1MB) })"],
        capture_output=True, text=True)
    try:
        return int((ps.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def boot(tag="", timeout=200, hold=20, log=print):
    kill()
    subprocess.Popen(["cmd.exe", "/c", BAT], cwd=MOD,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.time()
    best = 0
    seen = False
    while time.time() - t0 < timeout:
        time.sleep(4)
        m = mem()
        if m:
            seen = True
            best = max(best, m)
            if m > GOOD:
                t1 = time.time()
                while time.time() - t1 < hold:
                    time.sleep(5)
                    m2 = mem()
                    best = max(best, m2)
                    if m2 == 0:
                        log(f"   ✗ {tag}: 进入后又退出（峰值 {best}MB，{int(time.time()-t0)}s）")
                        return False, best
                log(f"   ✓ {tag}: 稳定进入游戏（{best}MB，{int(time.time()-t0)}s）")
                return True, best
        elif seen:
            log(f"   ✗ {tag}: 加载中崩溃（峰值 {best}MB，{int(time.time()-t0)}s）")
            return False, best
    log(f"   ✗ {tag}: 超时（峰值 {best}MB）")
    return False, best


def restore_pristine():
    shutil.copy2(nd.find_original("regulation.bin.orig_*"), REG)
    shutil.copy2(nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"), MSG)


def main():
    import glob
    log = print
    print("  ══ 二分定位（判据：>4500MB = 真进游戏）══\n", flush=True)
    results = []

    # 0) 对照：原始版
    restore_pristine()
    ok, m = boot("对照·原始版")
    results.append(("原始版（对照）", ok))

    # A) 只写 regulation（说明书原版）
    restore_pristine()
    rec = nd.deploy(os.path.join(APPLY, "out", "plan_seed1031721509.csv"), sync_guide=False, log=lambda s: None)
    ok, m = boot("只写物品数据")
    results.append(("只写物品数据（说明书原版）", ok))

    # B) 只写说明书（物品原版）
    restore_pristine()
    rec = nd.deploy(os.path.join(APPLY, "out", "plan_seed1031721509.csv"), sync_guide=True, log=lambda s: None)
    shutil.copy2(nd.find_original("regulation.bin.orig_*"), REG)     # 物品改回原版
    ok, m = boot("只写说明书")
    results.append(("只写说明书（物品原版）", ok))

    # C) 两个都写
    restore_pristine()
    rec = nd.deploy(os.path.join(APPLY, "out", "plan_seed1031721509.csv"), sync_guide=True, log=lambda s: None)
    ok, m = boot("两个都写")
    results.append(("两个都写", ok))

    kill(5)
    restore_pristine()
    print("\n  ══ 结果 ══", flush=True)
    for name, ok in results:
        print(f"   {'✓ 成功' if ok else '✗ 崩溃'}  {name}", flush=True)
    print("\n   已恢复原始文件 ✓", flush=True)
    open(os.path.join(APPLY, "logs", "boot_bisect.txt"), "w", encoding="utf-8").write(
        "\n".join(f"{name}\t{ok}" for name, ok in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
