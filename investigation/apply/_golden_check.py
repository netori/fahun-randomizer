# _golden_check.py — 基准计划对照（检测引擎行为是否被无意改动）
#
#   用法：python investigation/apply/_golden_check.py
#
#   原理：用固定配置 + 固定种子重新生成一遍计划，与 golden/ 下的冻结基准逐行对比。
#     一致 → 引擎行为没变 ✓
#     有差异 → 打印差异摘要（说明这次改动改变了随机结果），并给出"有意/无意"的判断指引
#
#   只读：不写计划、不碰游戏文件。
import csv, glob, importlib.util, os, sys

WS = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(WS, "..", "randomization-dryrun", "golden")

# 生成基准时用的配置（必须与 PLAN_README.md 里记录的一致）
CFG = dict(domains=["rune", "armor", "weapon"], joins=[], basis="guide", shops=False,
           merge_shadow=False, sets=True, seed=20261012, coherence=0.8,
           density=1.0, cross_domain=True)


def load_engine():
    p = os.path.join(WS, "..", "randomization-dryrun", "scripts", "randomizer.py")
    spec = importlib.util.spec_from_file_location("r", os.path.abspath(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rowkey(x):
    """计划的"身份"：哪个格子的哪个槽位"""
    return (x.get("source_table", ""), str(x.get("row_id", "")), str(x.get("slot", "")), x.get("unit", ""))


def main():
    base = sorted(glob.glob(os.path.join(GOLDEN_DIR, "plan_*.csv")))
    if not base:
        print("  ✗ 没找到基准计划（golden/plan_*.csv）")
        return 1
    base = base[-1]
    print(f"  基准: {os.path.basename(base)}")
    gold = list(csv.DictReader(open(base, encoding="utf-8-sig")))

    r = load_engine()
    items = r.load_world(False, "guide")
    plan, _pools, _seed = r.run(items, CFG, CFG["seed"])
    print(f"  重新生成: {len(plan)} 行 ｜ 基准 {len(gold)} 行 ｜ 引擎版本 {r.ENGINE_VERSION}")

    dg = {rowkey(x): (x["old"], x["new"]) for x in gold}
    dp = {rowkey(x): (x["old"], x["new"]) for x in plan}

    only_gold = sorted(set(dg) - set(dp))
    only_plan = sorted(set(dp) - set(dg))
    diff = sorted(k for k in set(dg) & set(dp) if dg[k] != dp[k])

    print(f"\n  ═══ 对照结果 ═══")
    print(f"    仅基准有: {len(only_gold)} ｜ 仅新计划有: {len(only_plan)} ｜ 映射不同: {len(diff)}")
    if not (only_gold or only_plan or diff):
        print("    ✓ 完全一致 —— 引擎行为没有变化")
        return 0

    print("    ✗ 有差异 —— 这次改动**改变了随机结果**")
    for k in (diff + only_gold + only_plan)[:8]:
        print(f"      {k[0]} 行{k[1]} 槽{k[2]}: 基准 {dg.get(k)} → 新 {dp.get(k)}")
    print("\n    怎么判断：")
    print("      · 这次改动**本意**就是改随机行为 → 属正常，请更新基准（见 golden/PLAN_README.md）")
    print("      · 这次改动**不该**影响结果（重构/加字段/改文档）→ 这是回归 bug，请查")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
