# pipeline_deploy.py — 一键部署：计划 → 打补丁 → 重打包 → 部署 regulation + 说明书，全程备份与校验
#
# 用法: python pipeline_deploy.py --plan out/plan_seed123.csv [--lang zh] [--yes] [--skip-guide]
#      [--dry-run]（只做到"重打包 + 校验"，不写进 MOD）
import argparse, hashlib, json, os, shutil, subprocess, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
MOD = os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）")
TOOL = os.path.join(APPLY, "tools", "witchybnd", "WitchyBND.exe")
CONPTY = os.path.join(ROOT, "investigation", "weapon-baseline", "logs", "_conpty_run.py")
PY = sys.executable
TS = time.strftime("%Y%m%d_%H%M%S")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(cmd, cwd=None, timeout=3600, quiet=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if not quiet and p.returncode != 0:
        print("   ! 命令失败:", " ".join(map(str, cmd))[:160])
        print("   ", (p.stdout or "")[-400:], (p.stderr or "")[-400:])
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def witchy(*args, cwd=None, timeout=1800):
    """经 ConPTY 调用 WitchyBND（直接跑会因无控制台而卡住）"""
    cmd = [PY, CONPTY, "--exe", TOOL, "--cwd", cwd or APPLY, "--raw-out",
           os.path.join(APPLY, "logs", f"witchy_{TS}.console.txt"), "--timeout", str(timeout),
           "--cols", "200", "--rows", "50", "--"] + list(args)
    return run(cmd, cwd=cwd, timeout=timeout + 120)


def step(msg):
    print(f"\n=== {msg} ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-guide", action="store_true")
    a = ap.parse_args()

    plan = a.plan if os.path.isabs(a.plan) else os.path.join(APPLY, a.plan)
    if not os.path.exists(plan):
        print("找不到计划文件:", plan); return 2
    print(f"计划: {plan}")
    print(f"MOD : {MOD}")

    # ── 0. 备份 ──
    step("0. 备份 MOD 现状")
    if not a.dry_run:
        for rel, tag in (("mod/regulation.bin", "regulation"), ("mod/msg/zhocn/item_dlc02.msgbnd.dcx", "msgbnd")):
            src = os.path.join(MOD, rel)
            if os.path.exists(src):
                bdir = os.path.join(APPLY, "backup")
                os.makedirs(bdir, exist_ok=True)
                shutil.copy2(src, os.path.join(bdir, f"{tag}.before_{TS}"))
                shutil.copy2(src, src + f".bak_{TS}")
                print(f"   {rel}: {os.path.getsize(src)} B  sha256 {sha(src)[:16]}…")

    # ── 1. 工作树 ──
    step("1. 复制原始树到工作目录")
    work = os.path.join(APPLY, "work", f"deploy_{TS}")
    shutil.copytree(os.path.join(APPLY, "work", "orig"), work)
    params = os.path.join(work, "regulation-bin")
    print(f"   {work}")

    # ── 2. 打补丁 ──
    step("2. 按计划打 XML 补丁")
    rc, out = run([PY, "apply_swaps.py", "--plan", plan, "--tree", work,
                   "--report", os.path.join(APPLY, "logs", f"deploy_apply_{TS}.json")], cwd=APPLY)
    print("   " + " ｜ ".join(out.strip().splitlines()[-3:])[:300])
    if rc != 0 or "冲突" in out.split("●")[-1][:200] and "冲突：0" not in out:
        print("   补丁有冲突，已中止"); return 3

    # ── 3. 逐个序列化被改的 param.xml ──
    step("3. XML → param（逐个序列化）")
    edited = []
    rep = os.path.join(APPLY, "logs", f"deploy_apply_{TS}.json")
    if os.path.exists(rep):
        r = json.load(open(rep, encoding="utf-8"))
        for k in ("ItemLotParam_map", "ItemLotParam_enemy", "ShopLineupParam"):
            if r.get(k, {}).get("changed", 0):
                edited.append(k)
    if not edited:
        edited = ["ItemLotParam_map", "ItemLotParam_enemy", "ShopLineupParam"]
    for t in edited:
        f = os.path.join(params, t + ".param.xml")
        rc, out = witchy(f, cwd=params, timeout=600)
        ok = "Deserializ" in out or os.path.exists(os.path.join(params, t + ".param"))
        print(f"   {t}: {'ok' if ok else '失败'}")

    # ── 4. 重打包 ──
    step("4. 重打包 regulation.bin")
    rc, out = witchy("-r", params, cwd=work, timeout=2400)
    newreg = os.path.join(work, "regulation.bin")
    print(f"   产物 {os.path.getsize(newreg) if os.path.exists(newreg) else 0} B")

    # ── 5. 校验：重新解包对比 ──
    step("5. 校验（重解包 vs 打过补丁的树）")
    vdir = os.path.join(APPLY, "work", f"verify_{TS}")
    shutil.copytree(work, vdir)
    shutil.rmtree(os.path.join(vdir, "regulation-bin"), ignore_errors=True)
    rc, out = witchy(os.path.join(vdir, "regulation.bin"), cwd=vdir, timeout=2400)
    rc, out = run([PY, "verify_tree.py", "--a", os.path.join(vdir, "regulation-bin"),
                   "--b", params, "--only", "param"], cwd=APPLY)
    print("   " + " ｜ ".join(out.strip().splitlines()[-3:])[:300])

    # ── 6. 说明书 ──
    if not a.skip_guide:
        step("6. 说明书（物品不变·地点变）")
        rc, out = run([PY, "fix_guide.py", "--plan", plan, "--lang", a.lang,
                       "--out", os.path.join(APPLY, "work", "msg", a.lang, f"GoodsCaption.{TS}.fmg.xml"),
                       "--report", os.path.join(APPLY, "logs", f"guide_{TS}.json")], cwd=APPLY)
        print("   " + " ｜ ".join(l for l in out.splitlines() if "统计" in l or "置换行" in l)[:220])

    if a.dry_run:
        print("\n[dry-run] 未写入 MOD。产物：", work)
        return 0

    # ── 7. 部署 ──
    step("7. 部署到 MOD")
    target = os.path.join(MOD, "mod", "regulation.bin")
    shutil.copy2(newreg, target)
    print(f"   regulation.bin → {os.path.getsize(target)} B  sha256 {sha(target)[:16]}…")
    if not a.skip_guide:
        gxml = os.path.join(APPLY, "work", "msg", a.lang, f"GoodsCaption.{TS}.fmg.xml")
        if os.path.exists(gxml):
            pkg = os.path.join(APPLY, "work", "msg", "pkg_" + TS)
            shutil.copytree(os.path.join(APPLY, "work", "msg", "zhpkg"), pkg)
            run([PY, CONPTY, "--exe", TOOL, "--cwd", os.path.join(pkg, "item_dlc02-msgbnd-dcx"),
                 "--raw-out", os.path.join(APPLY, "logs", f"gc_{TS}.txt"), "--timeout", "900",
                 "--cols", "200", "--rows", "50", "--", gxml], cwd=os.path.join(pkg, "item_dlc02-msgbnd-dcx"))
            fmg = gxml.replace(".fmg.xml", ".fmg")
            if os.path.exists(fmg):
                shutil.copy2(fmg, os.path.join(pkg, "item_dlc02-msgbnd-dcx", "GoodsCaption.fmg"))
                witchy("-r", os.path.join(pkg, "item_dlc02-msgbnd-dcx"), cwd=pkg, timeout=1800)
                mtarget = os.path.join(MOD, "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx")
                shutil.copy2(os.path.join(pkg, "item_dlc02.msgbnd.dcx"), mtarget)
                print(f"   说明书 → {os.path.getsize(mtarget)} B  sha256 {sha(mtarget)[:16]}…")

    receipt = {"timestamp": TS, "plan": plan, "work": work,
               "regulation": {"size": os.path.getsize(target), "sha256": sha(target)},
               "backups": [f"backup/regulation.before_{TS}", f"backup/msgbnd.before_{TS}"]}
    json.dump(receipt, open(os.path.join(APPLY, "backup", f"deploy_{TS}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n部署完成。回执：", os.path.join(APPLY, "backup", f"deploy_{TS}.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
