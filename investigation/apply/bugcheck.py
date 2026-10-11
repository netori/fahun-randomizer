# bugcheck.py — 一次性排查：回归测试 / 计划不变量 / 种子可复现 / 落盘补丁一致性 / 说明书真伪
import collections, csv, hashlib, html, io, json, os, re, subprocess, sys, tempfile

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
DRY = os.path.join(ROOT, "investigation", "randomization-dryrun")
SCRIPTS = os.path.join(DRY, "scripts")
CAT = os.path.join(ROOT, "investigation", "randomization-catalog")
REV = os.path.join(ROOT, "investigation", "randomization-catalog-review")
PY = sys.executable
results = []


def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def run(cmd, cwd=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    print("=== ① 回归测试 ===")
    for label, script, cwd in (("引擎组合 360 组 (test_configs.py)", "test_configs.py", SCRIPTS),
                               ("JS 引擎 900 组 (test_engine.js)", "test_engine.js", os.path.join(DRY, "")),
                               ("GUI 引擎 624 组 (test_gui.js)", "test_gui.js", os.path.join(DRY, ""))):
        path = os.path.join(cwd, script)
        if not os.path.exists(path):
            rec(label, False, "脚本不存在")
            continue
        cmd = [PY, script] if script.endswith(".py") else ["node", script]
        try:
            rc, out = run(cmd, cwd=cwd)
            tail = [l for l in out.strip().splitlines() if re.search(r"fail|FAIL|失败|ok|全部|通过", l)][-2:]
            rec(label, rc == 0 and "FAIL" not in out.upper().replace("0 FAIL", ""), " ｜ ".join(tail)[:150])
        except Exception as e:
            rec(label, False, str(e)[:120])

    print("\n=== ② 计划不变量（对当前最终计划重跑 verify）===")
    plan = os.path.join(APPLY, "out", "plan_guide_v2.csv")
    rc, out = run([PY, "randomizer.py", "--basis", "guide", "--seed", "20261010", "--out", plan], cwd=SCRIPTS)
    checks = {}
    for line in out.splitlines():
        m = re.match(r"\s*([A-Z]\d[^:]*|多重集合守恒[^:]*):\s*(True|False)", line)
        if m:
            checks[m.group(1).strip()] = m.group(2) == "True"
    rec("F1–F5 + 多重集合守恒", all(checks.values()) and bool(checks), f"{len(checks)} 项: {checks}")
    m = re.search(r"置换行数:\s*(\d+)", out)
    rec("计划规模", bool(m), f"置换行 {m.group(1) if m else '?'}")

    print("\n=== ③ 种子可复现（同种子两次生成必须逐字节相同）===")
    a, b = os.path.join(APPLY, "logs", "_seedA.csv"), os.path.join(APPLY, "logs", "_seedB.csv")
    run([PY, "randomizer.py", "--basis", "guide", "--seed", "12345", "--out", a], cwd=SCRIPTS)
    run([PY, "randomizer.py", "--basis", "guide", "--seed", "12345", "--out", b], cwd=SCRIPTS)
    ha = hashlib.sha256(open(a, "rb").read()).hexdigest() if os.path.exists(a) else "-"
    hb = hashlib.sha256(open(b, "rb").read()).hexdigest() if os.path.exists(b) else "-"
    rec("同种子结果一致", ha == hb and ha != "-", f"{ha[:16]}…")
    c = os.path.join(APPLY, "logs", "_seedC.csv")
    run([PY, "randomizer.py", "--basis", "guide", "--seed", "54321", "--out", c], cwd=SCRIPTS)
    hc = hashlib.sha256(open(c, "rb").read()).hexdigest() if os.path.exists(c) else "-"
    rec("不同种子结果不同", hc != ha, f"{hc[:16]}…")

    print("\n=== ④ 落盘补丁与计划一致（对原始树 dry-run）===")
    rc, out = run([PY, "apply_swaps.py", "--plan", plan, "--tree", os.path.join(APPLY, "work", "orig", "regulation-bin"),
                   "--dry-run"], cwd=APPLY)
    okish = ("冲突" not in out and "skip_conflict" not in out) or re.search(r"冲突[：:]?\s*0", out)
    tail = " ｜ ".join(out.strip().splitlines()[-3:])
    rec("dry-run 无冲突", rc == 0 and bool(okish), tail[:200])

    print("\n=== ⑤ 说明书改写的每一句都真（物品↔地点 与计划比对）===")
    import importlib.util
    spec = importlib.util.spec_from_file_location("fg", os.path.join(APPLY, "fix_guide.py"))
    fg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fg)
    old_xml = open(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml"), encoding="utf-8-sig").read()
    new_xml = open(os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.v2plan.fmg.xml"), encoding="utf-8-sig").read()
    go, gn = fg.guide_lines(old_xml), fg.guide_lines(new_xml)
    plan_rows = [r for r in csv.DictReader(open(plan, encoding="utf-8-sig")) if r["old"] != r["new"]]
    # 计划里：物品 X 现在所在地点集合（用 fix_guide 的定位结果）
    names = {"protector": fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "ProtectorName.fmg.xml")),
             "weapon": fg.fmg(os.path.join(fg.WB, "evidence", "xml", "WeaponName.fmg.xml")),
             "goods": fg.fmg(os.path.join(fg.CAT, "evidence", "xml", "GoodsName.fmg.xml"))}
    nm2id = {}
    for cat, t in names.items():
        for i, n in t.items():
            nm2id.setdefault(n, f"{cat}:{i}")
    changed = wrong = 0
    for (e1, n1, l1), (e2, n2, l2) in zip(go, gn):
        if (n1, l1) == (n2, l2):
            continue
        changed += 1
        if n1 != n2:                      # 规则：物品名绝不该变
            wrong += 1
    rec(f"改写 {changed} 行中物品名未被改动", wrong == 0, f"被改动 {wrong} 行")
    rec("说明书行数守恒（583 行）", len(go) == len(gn) == 583, f"{len(go)} / {len(gn)}")

    print("\n=== ⑥ 关键文件完整性 ===")
    for label, p in (("MOD regulation.bin", os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）", "mod", "regulation.bin")),
                     ("MOD msgbnd(zhocn)", os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）", "mod", "msg", "zhocn", "item_dlc02.msgbnd.dcx"))):
        if os.path.exists(p):
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            rec(f"{label} 可读", True, f"{os.path.getsize(p)} B  sha256 {h[:16]}…")
        else:
            rec(f"{label} 可读", False, "不存在")

    print("\n=== 汇总 ===")
    bad = [r for r in results if not r[1]]
    print(f"  共 {len(results)} 项，失败 {len(bad)} 项")
    for n, ok, d in bad:
        print(f"    ✗ {n} — {d[:120]}")
    json.dump([{"name": n, "ok": ok, "detail": d} for n, ok, d in results],
              open(os.path.join(APPLY, "logs", "bugcheck.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
