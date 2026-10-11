# _final_test.py — ① 更多种子的差异性与稳定性 ② 落盘演练（在副本上真打补丁并逐格核对）
import collections, importlib.util, itertools, os, random, shutil, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(APPLY))
sys.path.insert(0, APPLY)
spec = importlib.util.spec_from_file_location("r", os.path.join(WS, "investigation", "randomization-dryrun", "scripts", "randomizer.py"))
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
import erio, native_apply as na, param_patch as pp, native_deploy as nd   # noqa

SEEDS = [random.randrange(1, 2**31 - 1) for _ in range(20)] + [20261010, 1, 42, 777, 123456, 987654321]
CONFIGS = [
    ("默认/80%", {"coherence": 0.8}),
    ("默认/0%", {"coherence": 0.0}),
    ("只护甲/50%", {"domains": ["armor"], "coherence": 0.5}),
    ("只卢恩/25%", {"domains": ["rune"], "coherence": 0.25}),
    ("密度40%", {"coherence": 0.5, "density": 0.4}),
]
BASE = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide", "shops": True,
        "merge_shadow": False, "sets": True, "density": 1.0}


def sig(plan):
    return tuple(sorted((p["unit"], p["old"], p["new"]) for p in plan))


def main():
    print("  === ① 稳定性与差异性（26 种子 × 5 配置 = 130 组）===")
    fails = 0
    for cname, cov in CONFIGS:
        sigs = []
        for seed in SEEDS:
            cfg = dict(BASE); cfg.update(cov); cfg["seed"] = seed
            items = r.load_world(cfg["shops"], cfg["basis"])
            plan, pools, _ = r.run(items, cfg, seed)
            ch, _info = r.verify(items, cfg, plan, pools)
            bad = [k for k, v in ch.items() if not v]
            if bad:
                print(f"   ✗ {cname}/{seed}: {bad}"); fails += 1
            p2, _, _ = r.run(r.load_world(cfg["shops"], cfg["basis"]), cfg, seed)
            if sig(plan) != sig(p2):
                print(f"   ✗ {cname}/{seed}: 同种子不一致"); fails += 1
            sigs.append(sig(plan))
        uniq = len(set(sigs))
        print(f"   {cname:<12} 跑 {len(SEEDS)} 组 | 结果互不相同 {uniq}/{len(SEEDS)}" + (" ✓" if uniq == len(SEEDS) else " ✗"))

    print("\n  === ② 落盘演练（在副本上打补丁，逐格核对；不动 MOD）===")
    src = nd.find_original("regulation.bin.orig_*")
    for cname, cov in CONFIGS[:3]:
        seed = 20261010
        cfg = dict(BASE); cfg.update(cov); cfg["seed"] = seed
        items = r.load_world(cfg["shops"], cfg["basis"])
        plan, pools, _ = r.run(items, cfg, seed)
        # 写成计划 CSV
        csvp = os.path.join(APPLY, "out", f"plan_test_{cname.replace('/', '_')}.csv")
        cols = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
                "source_table", "row_id", "slot", "row_name"]
        import csv as _csv
        with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for p in sorted(plan, key=lambda x: (x["pool"], x["unit"], x["source_table"], x["row_id"], x["slot"])):
                w.writerow({k: p.get(k, "") for k in cols})
        # 在副本上打补丁
        tmp = os.path.join(APPLY, "logs", "_deploy_test.bin")
        shutil.copy2(src, tmp)
        rep = na.apply_native(csvp, source=tmp, out_path=tmp, verify=True, quiet=True)
        applied = sum(v["applied"] for v in rep["stats"].values())
        skipped = len(rep["skipped"])
        # 逐格核对：计划里的格子在新文件里必须等于计划值
        plain = erio.dcx_decompress(erio.regulation_decrypt(tmp))
        CATNUM = {"goods": 1, "weapon": 2, "protector": 3}
        okc = badc = 0
        for row in [x for x in plan if x["old"] != x["new"]]:
            tbl, rid, slot = row["source_table"], int(row["row_id"]), int(row["slot"] or 1)
            rows = na.find_row_table_in_plain(plain, tbl)
            if tbl.startswith("ItemLotParam"):
                o = pp.offset_of(tbl, rows, rid, "lotItemId", slot)
            else:
                o = pp.offset_of(tbl, rows, rid, "equipId")
            if o and pp.read_u32(plain, o) == int(row["new"].split(":")[1]):
                okc += 1
            else:
                badc += 1
        print(f"   {cname:<12} 计划 {len([x for x in plan if x['old']!=x['new']]):>4} 格 → 写入 {applied} 跳过 {skipped} | 回读核对 命中 {okc} 未中 {badc}" + (" ✓" if badc == 0 else " ✗"))
        if badc:
            fails += 1
    print(f"\n  失败合计: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
