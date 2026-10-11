# test_configs.py — 配置矩阵测试：所有域组合 × 联合方式 × 多种子，逐一校验 F1~F5 与守恒
import itertools, json, os, sys
DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(DRY, "scripts"))
import randomizer as R

DOMS = ["rune", "armor", "weapon"]


def configs():
    out = []
    for r in range(1, 4):
        for combo in itertools.combinations(DOMS, r):
            out.append({"domains": list(combo), "joins": []})
            if r >= 2:                                     # 全部合成一个联合池
                out.append({"domains": list(combo), "joins": [list(combo)]})
            if r == 3:                                     # 两两联合
                for pair in itertools.combinations(DOMS, 2):
                    out.append({"domains": list(combo), "joins": [list(pair)]})
                out.append({"domains": list(combo), "joins": [["rune", "weapon"], ["armor"]]})
    return out


def main():
    worlds = {b: (R.load_world(True, b), R.load_world(False, b)) for b in ("guide", "xlsx", "mix")}
    results, fails = [], []
    for basis, (items_shops, items_noshop) in worlds.items():
      for cfg0 in configs():
        for shops in (True, False):
            for sets in (True, False):
                cfg = {**R.DEFAULT_CONFIG, **cfg0, "basis": basis, "shops": shops, "sets": sets}
                items = items_shops if shops else items_noshop
                for seed in (20261010, 7):
                    plan, pools, sd = R.run(items, cfg, seed)
                    ck, info = R.verify(items, cfg, plan, pools)
                    ok = all(ck.values())
                    if not ok:
                        fails.append({"cfg": cfg, "seed": seed, "checks": ck})
                    results.append({"basis": basis, "domains": cfg["domains"], "joins": cfg["joins"], "shops": shops, "sets": sets,
                                    "seed": seed, "pools": len(pools), "rows": len(plan), "ok": ok, "info": info,
                                    "joint_pools": sorted(p for p in pools if p.startswith("joint:")),
                                    "pool_sizes": {p: len(m["units"]) for p, m in pools.items()}})
    summary = {}
    for r in results:
        key = f"basis={r['basis']}|domains={','.join(r['domains'])}|joins={'+'.join(','.join(g) for g in r['joins']) or '-'}|shops={r['shops']}|sets={r['sets']}"
        summary.setdefault(key, {"runs": 0, "fails": 0, "pools": r["pools"], "rows": r["rows"], "joint_pools": r["joint_pools"]})
        summary[key]["runs"] += 1
        summary[key]["fails"] += 0 if r["ok"] else 1
    json.dump({"total_runs": len(results), "failure_count": len(fails), "fails": fails[:20],
               "summary": summary, "detail": results},
              open(os.path.join(DRY, "evidence", "config_matrix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== 配置矩阵：{len(results)} 次运行（{len(summary)} 种组合）===")
    print(f"  校验失败：{len(fails)} 次")
    for k, v in sorted(summary.items())[:40]:
        flag = "✅" if v["fails"] == 0 else "❌"
        jp = f" 联合池 {len(v['joint_pools'])} 个" if v["joint_pools"] else ""
        print(f"   {flag} {k:<74} 池 {v['pools']:>3} 行 {v['rows']:>4}{jp}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
