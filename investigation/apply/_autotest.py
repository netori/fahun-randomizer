# _autotest.py — 自动测试台：装文件 → 启动游戏 → 观察是否静默退出
#   判据：启动后 ~70 秒内，是否出现**新的** eldenring 进程并持续存在（且日志推进到 title 之后）
import os, subprocess, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import native_deploy as nd

MOD = nd.MOD
REG = os.path.join(MOD, "mod", "regulation.bin")
MSG = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
LOG = r"F:\game\studygame\elden ring\THE_COVERAGE-随机开发\法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）\yafsml\log\YAFSML.log"
MODDIR = MOD          # yafsml 就在 MOD 目录里


def pids():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-Process eldenring -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','"],
                             capture_output=True, text=True, timeout=60)
        return [int(x) for x in out.stdout.strip().split(",") if x.strip().isdigit()]
    except Exception:
        return []


def log_lines():
    try:
        return sum(1 for _ in open(LOG, encoding="utf-8", errors="replace"))
    except Exception:
        return 0


def run(reg_src, msg_src=None, label=""):
    import shutil
    shutil.copy2(reg_src, REG)
    if msg_src:
        shutil.copy2(msg_src, MSG)
    before_pids, before_lines = pids(), log_lines()
    print(f"\n  === {label} ===")
    print(f"   装好：regulation {os.path.getsize(REG)} B | 说明书 {os.path.getsize(MSG)} B")
    print(f"   启动前：进程 {before_pids} | 日志 {before_lines} 行")
    # 绕过启动脚本的进程检查，直接调 YAFSML 注入
    yaf = os.path.join(MODDIR, "yafsml")
    er_root = r"F:\game\studygame\elden ring\ELDEN RING Tarnished Edition v1.17"
    subprocess.Popen([os.path.join(yaf, "YAFSML.exe"), "--game-path", er_root], cwd=yaf,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(75)
    after_pids, after_lines = pids(), log_lines()
    new_pids = [p for p in after_pids if p not in before_pids]
    print(f"   75 秒后：进程 {after_pids}（新增 {new_pids}）| 日志 {after_lines} 行（+{after_lines-before_lines}）")
    alive = bool(new_pids)
    print(f"   ★ 判定：{'游戏活着（能进）' if alive else '游戏不在了（静默退出/没起来）'}")
    return alive


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    ok_msg = os.path.join(APPLY, "backup", "works_in_game", "item_dlc02.msgbnd.dcx")
    if mode == "pilot":                      # 首测计划 + 我的原生写入
        subprocess.run([sys.executable, os.path.join(APPLY, "native_apply.py"),
                        "--plan", os.path.join(APPLY, "out", "plan_pilot.csv")], check=False,
                       cwd=APPLY, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return run(REG, ok_msg, "首测 36 格 + 我的原生写入")
    if mode == "full":                       # 完整 748 格 + 我的原生写入
        return run(os.path.join(APPLY, "backup", "broken_native", "regulation.bin"), ok_msg,
                   "完整 748 格 + 我的原生写入")
    if mode == "pristine":                   # 全原始（对照）
        return run(nd.find_original("regulation.bin.orig_*"), nd.find_original("item_dlc02.msgbnd.dcx.zhocn.orig_*"),
                   "全原始（对照）")
    if mode == "now":                        # 只看现在装了啥
        return run(REG, None, "当前 MOD 状态")
    print("用法: python _autotest.py [pilot|full|pristine|now]")
    return 2


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
