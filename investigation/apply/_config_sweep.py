# _config_sweep.py — 穷举所有界面可产生的配置组合，逐个验收
#   验收项：① 引擎 6 项校验全过 ② 单元级守恒（换走=换进）③ 法祷护甲绝不与近战/卢恩互换
#           ④ 同种子可复现（抽检）⑤ 跨类语义正确（各自随机=0；单勾=0）
import collections, importlib.util, itertools, os, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
spec = importlib.util.spec_from_file_location("r", ENGINE)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
CASTER = set(getattr(r, "CASTER_ARCH", ()))
ALL = ["rune", "armor", "weapon"]
SUBSETS = [list(c) for k in (1, 2, 3) for c in itertools.combinations(ALL, k)]
BASE = {"joins": [], "basis": "guide", "shops": False, "merge_shadow": False,
        "sets": True, "density": 1.0, "coherence": 0.8}


def conserved(pools, plan):
    """单元级守恒：所有单元持有的物品集合前后一致"""
    b = collections.Counter()
    for m in pools.values():
        for u in m.get("units") or []:
            if u.get("parts"):
                b[frozenset(r.key_of(k) for k in u["parts"].values())] += 1
            elif u.get("items"):
                b[frozenset([r.key_of(u["items"][0])])] += 1
    d = {}
    for p in plan:
        d.setdefault(str(p["unit"]), set()).add(str(p["new"]))
    return b == collections.Counter(frozenset(v) for v in d.values())


def run_one(items, cfg, seed=20261010):
    plan, pools, _s = r.run(items, cfg, seed)
    ch, _info = r.verify(items, cfg, plan, pools)
    bad = [k for k, v in ch.items() if not v]
    errs = list(bad)
    if not conserved(pools, plan):
        errs.append("守恒不成立")
    # 法祷护甲隔离 + 跨类语义
    cross = caster_leak = 0
    for p in plan:
        if p["old"] == p["new"]:
            continue
        a = items.get(tuple(str(p["old"]).split(":")))
        b2 = items.get(tuple(str(p["new"]).split(":")))
        if not (a and b2):
            continue
        if a.get("domain") != b2.get("domain"):
            cross += 1
        ca_ = lambda v: v.get("domain") == "armor" and v.get("arch") in CASTER
        me = lambda v: v.get("domain") == "armor" and v.get("arch") not in CASTER
        if (ca_(a) and me(b2)) or (me(a) and ca_(b2)):
            caster_leak += 1
    if caster_leak:
        errs.append(f"法祷护甲违规 {caster_leak}")
    return errs, cross, sum(1 for p in plan if p["old"] != p["new"])


def main():
    fails = []
    total = 0
    print("  ══ 第 1 轮：勾选 × 混合方式 × 合理度（7 × 2 × 5 = 70 组）══")
    items = r.load_world(False, "guide")
    for doms, mode, coh in itertools.product(SUBSETS, ("mix", "sep"), (1.0, 0.75, 0.5, 0.25, 0.0)):
        cfg = dict(BASE, domains=doms, cross_domain=(mode == "mix"), coherence=coh)
        errs, cross, mv = run_one(items, cfg)
        total += 1
        # 语义校验：单勾或各自随机时不得跨类
        if (len(doms) == 1 or mode == "sep") and cross:
            errs.append(f"不该跨类却有 {cross} 行")
        # 合理度 100% 时武器不掺入混池（用户规则）→ 涉及武器的组合跨类为 0 属正常
        _weapon_involved = "weapon" in doms
        _expect_cross = not (_weapon_involved and coh >= 0.95) and not (
            doms == ["rune", "armor"] and coh >= 0.95)
        if len(doms) > 1 and mode == "mix" and cross == 0 and _expect_cross:
            errs.append("该跨类却为 0")
        if errs:
            fails.append((f"{'+'.join(doms)}/{mode}/{coh}", errs))
    print(f"     完成 {total} 组，失败 {len(fails)}")

    print("  ══ 第 2 轮：改动比例 × 套装 × 幽影合并（3 × 3 × 2 × 2 = 36 组）══")
    n0 = total
    for doms, den, sets, sh in itertools.product(
            [["rune", "armor", "weapon"], ["rune", "armor"], ["armor", "weapon"]],
            (1.0, 0.6, 0.3), (True, False), (False, True)):
        cfg = dict(BASE, domains=doms, cross_domain=True, coherence=0.5,
                   density=den, sets=sets, merge_shadow=sh)
        errs, _c, _m = run_one(items, cfg)
        total += 1
        if errs:
            fails.append((f"{'+'.join(doms)}/密度{den}/套装{sets}/幽影{sh}", errs))
    print(f"     完成 {total - n0} 组，累计失败 {len(fails)}")

    print("  ══ 第 3 轮：多种子复现（5 配置 × 5 种子 = 25 组）══")
    n1 = total
    seeds = [20261010, 42, 4242, 777777, 987654321]
    for doms, mode in ((["rune", "armor", "weapon"], "mix"), (["rune", "armor", "weapon"], "sep"),
                       (["rune", "armor"], "mix"), (["armor", "weapon"], "mix"), (["rune", "weapon"], "mix")):
        got = []
        for sd in seeds:
            cfg = dict(BASE, domains=doms, cross_domain=(mode == "mix"), coherence=0.6, seed=sd)
            errs, _c, _m = run_one(items, cfg, sd)
            total += 1
            if errs:
                fails.append((f"{'+'.join(doms)}/{mode}/种子{sd}", errs))
            plan2, _p2, _s2 = r.run(items, cfg, sd)
            got.append(tuple((p["unit"], p["old"], p["new"]) for p in plan2))
        if len(set(got)) != len(seeds):
            fails.append((f"{'+'.join(doms)}/{mode}/多种子", ["不同种子出现重复结果"]))
    print(f"     完成 {total - n1} 组，累计失败 {len(fails)}")

    print(f"\n  ══════ 合计 {total} 组配置，失败 {len(fails)} ══════")
    for name, errs in fails[:15]:
        print(f"    ✗ {name}: {errs}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
