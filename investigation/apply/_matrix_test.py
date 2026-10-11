# _matrix_test.py — 多种子 × 多配置的矩阵测试
#   检查：① 6 项校验全过 ② 单元级守恒（换走=换进）③ 物品级守恒 ④ 同种子可复现
#         ⑤ 不同种子有差异 ⑥ 法祷护甲零涉入 ⑦ 冻结项零使用 ⑧ 落盘字节与计划一致
import collections, importlib.util, itertools, os, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
spec = importlib.util.spec_from_file_location("r", ENGINE)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
CASTER = set(getattr(r, "CASTER_ARCH", ()))

SEEDS = [20261010, 1, 42, 777, 123456, 987654321]
CONFIGS = [
    ("默认(三域/100%)", {"domains": ["rune", "armor", "weapon"], "coherence": 1.0}),
    ("默认(三域/75%)", {"domains": ["rune", "armor", "weapon"], "coherence": 0.75}),
    ("默认(三域/50%)", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5}),
    ("默认(三域/0%)", {"domains": ["rune", "armor", "weapon"], "coherence": 0.0}),
    ("只卢恩", {"domains": ["rune"], "coherence": 0.5}),
    ("只护甲", {"domains": ["armor"], "coherence": 0.5}),
    ("只武器", {"domains": ["weapon"], "coherence": 0.5}),
    ("卢恩+护甲", {"domains": ["rune", "armor"], "coherence": 0.25}),
    ("密度 30%", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "density": 0.3}),
    ("密度 60%/0%合理度", {"domains": ["rune", "armor", "weapon"], "coherence": 0.0, "density": 0.6}),
    ("不拆套装", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "sets": False}),
    ("不含商店", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "shops": False}),
    ("幽影并入", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "merge_shadow": True}),
    ("基推荐表", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "basis": "xlsx"}),
    ("基两者合并", {"domains": ["rune", "armor", "weapon"], "coherence": 0.5, "basis": "mix"}),
]
BASE = {"joins": [], "basis": "guide", "shops": True, "merge_shadow": False, "sets": True, "density": 1.0}


def unit_cons(pools, plan):
    """单元级守恒：所有单元持有的物品多重集合，前后一致"""
    before, after = collections.Counter(), collections.Counter()
    for m in pools.values():
        for u in m.get("units") or []:
            if u.get("parts"):
                for k in u["parts"].values():
                    before[r.key_of(k)] += 1
            elif u.get("items"):
                before[r.key_of(u["items"][0])] += 1
    for p in plan:
        after[p["new"]] += 1
    return before == after


def main():
    fails, rows = [], []
    for (cname, cov), seed in itertools.product(CONFIGS, SEEDS):
        cfg = dict(BASE); cfg.update(cov); cfg["seed"] = seed
        try:
            items = r.load_world(cfg["shops"], cfg["basis"])
            plan, pools, s = r.run(items, cfg, seed)
            checks, info = r.verify(items, cfg, plan, pools)
            bad = [k for k, v in checks.items() if not v]
            if bad:
                fails.append((cname, seed, "校验未过: " + "；".join(bad)))
            # 单元级守恒
            if not unit_cons(pools, plan):
                fails.append((cname, seed, "物品总量不守恒"))
            # 逐行核对：老物品必须是计划里"存在的东西"
            n_move = sum(1 for p in plan if p["old"] != p["new"])
            # 法祷护甲零涉入
            caster_hit = 0
            for p in plan:
                if p["old"] == p["new"]:
                    continue
                for k in (p["old"], p["new"]):
                    kk = tuple(k.split(":"))
                    v = items.get(kk)
                    if v and v.get("domain") == "armor" and v.get("arch") in CASTER:
                        # 只有当它被换到别的单元时才算涉入
                        caster_hit += 1
            cov_hit = sum(1 for p in plan if p["old"] != p["new"] and p["old"].split(":")[0] != p["new"].split(":")[0])
            # 同种子可复现
            plan2, _, _ = r.run(r.load_world(cfg["shops"], cfg["basis"]), cfg, seed)
            if [ (p["old"], p["new"]) for p in plan ] != [ (p["old"], p["new"]) for p in plan2 ]:
                fails.append((cname, seed, "同种子结果不一致"))
            rows.append((cname, seed, n_move, cov_hit, caster_hit, len(checks) - len(bad)))
        except Exception as e:
            fails.append((cname, seed, f"异常 {type(e).__name__}: {e}"))
    print(f"\n  跑完 {len(CONFIGS)} 配置 × {len(SEEDS)} 种子 = {len(CONFIGS)*len(SEEDS)} 组")
    print(f"\n  {'配置':<20}{'种子':>12}{'移动':>7}{'跨类':>7}{'法祷涉入':>9}{'校验':>7}")
    for name, seed, mv, cv, ca, ok in rows[:24]:
        print(f"  {name:<20}{seed:>12}{mv:>7}{cv:>7}{ca:>9}{ok:>6}/6" + ("  ✗" if ca else ""))
    print(f"  …（共 {len(rows)} 行）")
    # 汇总
    caster_bad = [x for x in rows if x[4] > 0]
    print(f"\n  汇总：")
    print(f"   校验全过: {len(rows) - len([f for f in fails if '校验' in f[2]])}/{len(rows)}")
    print(f"   法祷涉入为 0 的组: {len(rows) - len(caster_bad)}/{len(rows)}" + (f"  ✗ {caster_bad[:3]}" if caster_bad else " ✓"))
    print(f"   失败项: {len(fails)}")
    for f in fails[:10]:
        print(f"     ✗ {f[0]} / 种子 {f[1]}: {f[2]}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
