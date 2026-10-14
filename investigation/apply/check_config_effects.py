#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐旋钮体检：每个配置项各跑一对（或几组）配置，看它**真的**有没有产生可测量的差异。

为什么不能只靠"跑通不报错"：本仓库已经踩过两次"开关看着在、其实不生效"的坑
（法祷护甲整块冻死、merge_shadow 在武器分支上是恒真死代码）。所以这里的判据是
**"结果真的变了，而且方向与说明书一致"**；测不出差异就如实报「无效果」，不粉饰。

用法：
    python check_config_effects.py            # 全部（纯引擎，约几分钟）
    python check_config_effects.py --fast      # 只跑关键项
"""
import argparse
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "investigation", "randomization-dryrun", "scripts"))

SEED = 20261010
BASE = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide", "shops": True,
        "merge_shadow": False, "sets": True, "density": 1.0, "coherence": 0.8}


def stats(plan, items):
    """把一份计划摊成体检要用的数字"""
    changed = [p for p in plan if p["old"] != p["new"]]
    dom = lambda k: (items.get(tuple(str(k).split(":"))) or {}).get("domain")
    arch = lambda k: (items.get(tuple(str(k).split(":"))) or {}).get("arch")
    is_caster = lambda k: dom(k) == "armor" and arch(k) in set(_R.CASTER_ARCH)
    s = {"planned": len(plan), "changed": len(changed),
         "shop": sum(1 for p in changed if p["source_table"] == "ShopLineupParam"),
         "mixed": sum(1 for p in changed if "mixed" in p["pool"] or p["pool"].startswith("joint:")),
         "buckets": len({p["pool"] for p in plan}),
         "caster_sets": len({p["unit"] for p in changed
                             if str(p["unit"]).startswith("set:") and is_caster(p["old"])}),
         "caster_parts": len({p["unit"] for p in changed
                              if not str(p["unit"]).startswith("set:") and is_caster(p["old"])})}
    for d in ("armor", "weapon", "rune", "goods"):
        s["dom_" + d] = sum(1 for p in changed if dom(p["old"]) == d)
    # 跨大类互换（护甲↔卢恩 这类）
    cross = 0
    for p in changed:
        if dom(p["old"]) != dom(p["new"]) and dom(p["old"]) and dom(p["new"]):
            cross += 1
    s["cross_domain"] = cross
    # 套装一致性：同一套装单元的每一行，新物品必须来自**同一套**
    bad = 0
    grp = collections.defaultdict(set)
    for p in changed:
        if p.get("role") != "set":
            continue
        code, base = _R.part_code_of(str(p["new"]).split(":")[1])
        grp[p["unit"]].add(base or str(p["new"]))
    for _u, bases in grp.items():
        if len(bases) > 1:
            bad += 1
    s["set_mixed_up"] = bad
    s["set_units"] = len(grp)
    return s


def fingerprint(plan):
    rows = sorted((p["unit"], str(p.get("source_table")), str(p.get("row_id")), str(p.get("slot")),
                   p["old"], p["new"]) for p in plan)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:16]


def run(cfg, items=None):
    items = items if items is not None else _R.load_world(cfg.get("shops", True), cfg.get("basis", "guide"))
    plan = _R.run(items, cfg, cfg.get("seed", SEED))[0]
    return plan, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    global _R
    import randomizer as _R

    rows = []
    known = []          # 已知空转/不适用项（不计入失败）

    def ck(name, ok, detail):
        rows.append((name, bool(ok), detail))
        print(f"  {'✓' if ok else '✗'} {name}　{detail}", flush=True)

    def ck_known(name, detail):
        """已知空转/不适用项：如实打印，但不计入失败（作者 2026-10-14 决定：界面已撤掉那个开关）"""
        known.append((name, detail))
        print(f"  ⚠ {name}　{detail}", flush=True)

    print("=== 逐旋钮体检（种子 %d）===" % SEED, flush=True)
    base_plan, base_items = run(dict(BASE))
    base = stats(base_plan, base_items)
    print(f"基线：计划 {base['planned']} 行 / 改动 {base['changed']}；桶 {base['buckets']}；"
          f"混池行 {base['mixed']}；商店行 {base['shop']}；法祷 整套 {base['caster_sets']} + 散件 {base['caster_parts']}",
          flush=True)

    # ① 随机项目：关掉某一项 → 那一项一件都不动；开着 → 确实在动
    for d, label in (("rune", "卢恩"), ("armor", "护甲"), ("weapon", "装备")):
        keep = [x for x in ("rune", "armor", "weapon") if x != d]
        pl, it = run(dict(BASE, domains=keep))
        s = stats(pl, it)
        ck(f"随机项目·取消{label}", s["dom_" + d] == 0 and base["dom_" + d] > 0,
           f"关掉后 {label} 改动 {s['dom_' + d]} 处（开着时 {base['dom_' + d]} 处）")

    # ② 商店开关
    pl, it = run(dict(BASE, shops=False))
    s = stats(pl, it)
    ck("商店·关闭", s["shop"] == 0 and base["shop"] > 0,
       f"关掉后商店改动 {s['shop']} 行（开着时 {base['shop']} 行）")

    # ③ 混合方式：全部混合（跨大类互换）vs 各自（不跨）
    pl, it = run(dict(BASE, cross_domain=False))
    s = stats(pl, it)
    ck("混合方式·各自随机", s["cross_domain"] == 0 and base["cross_domain"] > 0 and s["mixed"] == 0,
       f"各自：跨类 {s['cross_domain']} 处、混池行 {s['mixed']} 行（全部混合时跨类 {base['cross_domain']} 处）")
    # 两两混：卢恩+护甲 混合、武器独自
    pl2, it2 = run(dict(BASE, cross_domain=False, joins=[["rune", "armor"]]))
    s2 = stats(pl2, it2)
    cross_pairs = collections.Counter()
    for p in pl2:
        if p["old"] == p["new"]:
            continue
        do = (it2.get(tuple(str(p["old"]).split(":"))) or {}).get("domain")
        dn = (it2.get(tuple(str(p["new"]).split(":"))) or {}).get("domain")
        if do and dn and do != dn:
            cross_pairs[tuple(sorted((do, dn)))] += 1
    ck("混合方式·两两混（卢恩+护甲）", cross_pairs.get(("armor", "rune"), 0) > 0
       and cross_pairs.get(("rune", "weapon"), 0) == 0 and cross_pairs.get(("armor", "weapon"), 0) == 0,
       f"跨类组合 {dict(cross_pairs)}")

    # ④ 合理度：越低越放开 → 桶数变少、跨类/跨档更多
    prev = None
    ok_dir, detail = True, []
    for c in (1.0, 0.5, 0.0):
        pl, it = run(dict(BASE, coherence=c))
        s = stats(pl, it)
        detail.append(f"{int(c*100)}%→桶{s['buckets']}/跨类{s['cross_domain']}")
        if prev is not None and not (s["buckets"] <= prev[0] and s["cross_domain"] >= prev[1]):
            ok_dir = False
        prev = (s["buckets"], s["cross_domain"])
    ck("合理度·单调放开", ok_dir, "；".join(detail))

    # ⑤ 单独设合理度：每条各管一段
    pl, it = run(dict(BASE, coh_mixed=0.0))
    s = stats(pl, it)
    ck("单独合理度·混池", s["mixed"] > 0 and s["buckets"] < base["buckets"],
       f"混池 0%：桶 {base['buckets']} → {s['buckets']}（混池并档）")
    pl, it = run(dict(BASE, cross_domain=False, coh_domain={"rune": 0.0}))
    it_sep = it
    s = stats(pl, it_sep)
    pl_b, it_b = run(dict(BASE, cross_domain=False))
    s_b = stats(pl_b, it_b)
    ck("单独合理度·卢恩（各自随机时）", s["buckets"] < s_b["buckets"],
       f"卢恩 0%：桶 {s_b['buckets']} → {s['buckets']}")

    # ⑥ 改动比例
    prev = None
    ok_dir, detail = True, []
    for d in (1.0, 0.5, 0.25):
        pl, it = run(dict(BASE, density=d))
        s = stats(pl, it)
        detail.append(f"{int(d*100)}%→改动{s['changed']}")
        if prev is not None and s["changed"] >= prev:
            ok_dir = False
        prev = s["changed"]
    ck("改动比例·越低改得越少", ok_dir, "；".join(detail))

    # ⑦ 单独设比例：整套法祷
    prev = None
    ok_dir, detail = True, []
    for v in (1.0, 0.4, 0.0):
        pl, it = run(dict(BASE, rate_sets=v))
        s = stats(pl, it)
        detail.append(f"{int(v*100)}%→整套{s['caster_sets']}")
        if prev is not None and s["caster_sets"] >= prev:
            ok_dir = False
        prev = s["caster_sets"]
    ck("单独比例·整套法祷", ok_dir and prev == 0, "；".join(detail))

    # ⑧ 套装开关：开 = 每次整套换（同单元各行必须来自同一套）；关 = 按部位单件
    ck("法祷护甲整套一起换·开", base["set_mixed_up"] == 0 and base["set_units"] > 0,
       f"{base['set_units']} 个套装单元、拆散 {base['set_mixed_up']} 个")
    pl, it = run(dict(BASE, sets=False))
    s = stats(pl, it)
    ck("法祷护甲整套一起换·关", s["set_units"] == 0 and s["caster_parts"] > 0,
       f"关掉后套装单元 {s['set_units']} 个、法祷散件改动 {s['caster_parts']} 件")

    # ⑨ 幽影卢恩并入大师级（判据用**计划指纹**：池名集合看不出 build_pools 的差别，
    #    但"结果到底有没有变"必须用指纹才诚实）
    pl_off, _ = run(dict(BASE, cross_domain=False, merge_shadow=False))
    pl_on, _ = run(dict(BASE, cross_domain=False, merge_shadow=True))
    # build_pools 层面也看一眼：开关到底有没有合并池键
    _bp = _R.build_pools(base_items, dict(BASE, cross_domain=False, merge_shadow=False))
    _bp2 = _R.build_pools(base_items, dict(BASE, cross_domain=False, merge_shadow=True))
    _k_off = {k for k in _bp if k.startswith("rune")}
    _k_on = {k for k in _bp2 if k.startswith("rune")}
    ck_known("幽影卢恩与普通卢恩一起换（已知空转；界面 2026-10-14 已撤掉这个开关）",
             f"池键 {'变了' if _k_on != _k_off else '没变'}（{len(_k_off)}→{len(_k_on)} 个），"
             f"计划指纹 {'仍相同' if fingerprint(pl_on) == fingerprint(pl_off) else '不同'}："
             "档位系统里 大师=幽影 都是 3 档（规格 §2/Q3），按档位分桶时必然并到一起 ⇒ 改不了结果")

    # ⑩ 种子
    pl_a, _ = run(dict(BASE))
    pl_b, _ = run(dict(BASE, seed=SEED + 1))
    ck("随机种子", fingerprint(pl_a) == fingerprint(base_plan) and fingerprint(pl_b) != fingerprint(base_plan),
       f"同种子一致、换种子不同（{fingerprint(pl_b)}）")

    print("\n=== 汇总 ===")
    bad = [r for r in rows if not r[1]]
    print(f"  通过 {len(rows) - len(bad)} ｜ 无效果/异常 {len(bad)} ｜ 已知空转 {len(known)}")
    for name, _ok, detail in bad:
        print(f"    ✗ {name}　{detail}")
    for name, detail in known:
        print(f"    ⚠ {name}　{detail}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
