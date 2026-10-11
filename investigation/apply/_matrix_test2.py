# _matrix_test2.py — 修正口径后的矩阵测试
#  守恒：每个"单元"持有的物品集合（整体）在前后必须构成同一多重集合
#  法祷：只有"法祷护甲 ↔ 非法祷护甲/非护甲"才算违规（法祷之间互换是允许的）
import collections, importlib.util, itertools, os, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(APPLY)), "investigation", "randomization-dryrun", "scripts", "randomizer.py")
spec = importlib.util.spec_from_file_location("r", ENGINE)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
CASTER = set(getattr(r, "CASTER_ARCH", ()))
SEEDS = [20261010, 1, 42, 777, 123456, 987654321]
CONFIGS = [
    ("默认/100%", {"coherence": 1.0}),
    ("默认/75%", {"coherence": 0.75}),
    ("默认/50%", {"coherence": 0.5}),
    ("默认/0%", {"coherence": 0.0}),
    ("只卢恩/50%", {"domains": ["rune"], "coherence": 0.5}),
    ("只护甲/50%", {"domains": ["armor"], "coherence": 0.5}),
    ("只武器/50%", {"domains": ["weapon"], "coherence": 0.5}),
    ("卢恩+护甲/25%", {"domains": ["rune", "armor"], "coherence": 0.25}),
    ("密度30%", {"coherence": 0.5, "density": 0.3}),
    ("密度60%/0%", {"coherence": 0.0, "density": 0.6}),
    ("不拆套装", {"coherence": 0.5, "sets": False}),
    ("不含商店", {"coherence": 0.5, "shops": False}),
    ("幽影并入", {"coherence": 0.5, "merge_shadow": True}),
    ("基推荐表", {"coherence": 0.5, "basis": "xlsx"}),
    ("基两者合并", {"coherence": 0.5, "basis": "mix"}),
]
BASE = {"domains": ["rune", "armor", "weapon"], "joins": [], "basis": "guide", "shops": True,
        "merge_shadow": False, "sets": True, "density": 1.0}


def held(plan):
    """单元 → 它持有的物品集合（套装按 4 部件计）"""
    d = {}
    for p in plan:
        d.setdefault(str(p["unit"]), set()).add(p["new"])
    return collections.Counter(frozenset(v) for v in d.values())


def caster_violation(items, plan):
    """法祷护甲只能与"同流派法祷护甲"互换；换到别处即违规"""
    def kind(k):
        v = items.get(tuple(str(k).split(":")))
        if not v:
            return None
        if v.get("domain") == "armor" and v.get("arch") in CASTER:
            return ("caster", v.get("arch"))
        return ("other", None)
    n = 0
    for p in plan:
        if p["old"] == p["new"]:
            continue
        ko, kn = kind(p["old"]), kind(p["new"])
        if ko is None or kn is None:
            continue
        if ko[0] == "caster" or kn[0] == "caster":
            if ko != kn:
                n += 1
    return n


def frame_ok():
    """防回归：regulation 重压缩后的帧头必须与原版一致（否则游戏启动即崩）"""
    import erio, glob, importlib
    importlib.reload(erio)
    src = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup", "regulation.bin.orig_*")))[-1]
    raw = erio.regulation_decrypt(src)
    plain = erio.dcx_decompress(raw)
    out = erio.dcx_compress(plain, raw, 12)
    h = erio.dcx_parts(raw)
    got = out[h["payload_off"]:h["payload_off"] + 6]
    want = raw[h["payload_off"]:h["payload_off"] + 6]
    same_content = erio.dcx_decompress(out) == plain
    # 前 4 字节是 ZSTD 魔数；第 5 字节是帧头标志、第 6 字节是窗口描述符 —— 当初崩游戏就崩在这两个值
    return got[4:6] == want[4:6] and same_content, got.hex(" "), want.hex(" ")


def main():
    fails, rows = [], []
    for (cname, cov), seed in itertools.product(CONFIGS, SEEDS):
        cfg = dict(BASE); cfg.update(cov); cfg["seed"] = seed
        try:
            items = r.load_world(cfg["shops"], cfg["basis"])
            plan, pools, _s = r.run(items, cfg, seed)
            checks, info = r.verify(items, cfg, plan, pools)
            bad = [k for k, v in checks.items() if not v]
            # 守恒：把"池内单元持有"与"计划后单元持有"比较（用同一批单元 id）
            before_ids = {str(u["id"]) for m in pools.values() for u in m.get("units") or []}
            after_ids = {str(p["unit"]) for p in plan}
            cons = (len(before_ids) == len(after_ids))
            # 更强：把前后"单元 → 持有集合"多重集合比对（用池里的定义重建 before）
            before_held = collections.Counter()
            for m in pools.values():
                for u in m.get("units") or []:
                    if u.get("parts"):
                        before_held[frozenset(r.key_of(k) for k in u["parts"].values())] += 1
                    elif u.get("items"):
                        before_held[frozenset([r.key_of(u["items"][0])])] += 1
            cons = cons and (before_held == held(plan))
            cv = caster_violation(items, plan)
            n_move = sum(1 for p in plan if p["old"] != p["new"])
            # 复现性
            p2, _, _ = r.run(r.load_world(cfg["shops"], cfg["basis"]), cfg, seed)
            same = [(p["old"], p["new"]) for p in plan] == [(p["old"], p["new"]) for p in p2]
            if bad:
                fails.append((cname, seed, "校验: " + "；".join(bad)))
            if not cons:
                fails.append((cname, seed, "守恒不成立"))
            if not same:
                fails.append((cname, seed, "同种子不一致"))
            if cv:
                fails.append((cname, seed, f"法祷违规 {cv} 行"))
            rows.append((cname, seed, n_move, cv, len(checks) - len(bad), cons, same))
        except Exception as e:
            fails.append((cname, seed, f"异常 {type(e).__name__}: {e}"))
    print(f"\n  {len(CONFIGS)} 配置 × {len(SEEDS)} 种子 = {len(CONFIGS)*len(SEEDS)} 组")
    print(f"  {'配置':<14}{'种子':>12}{'移动':>7}{'法祷违规':>9}{'校验':>7}{'守恒':>6}{'复现':>6}")
    for name, seed, mv, cv, ok, cons, same in rows[:20]:
        print(f"  {name:<14}{seed:>12}{mv:>7}{cv:>9}{ok:>5}/6{'✓' if cons else '✗':>6}{'✓' if same else '✗':>6}")
    print(f"  …（共 {len(rows)} 行）")
    ncv = sum(1 for x in rows if x[3] > 0)
    ncons = sum(1 for x in rows if x[5])
    nsame = sum(1 for x in rows if x[6])
    nok = sum(1 for x in rows if x[4] == 6)
    ok_frame, got, want = frame_ok()
    print(f"\n  压缩帧校验（含帧参数）：重压缩 {got} ／ 原版 {want} → {'✓ 一致' if ok_frame else '✗ 不一致（会导致启动崩溃！）'}")
    if not ok_frame:
        fails.append(("压缩帧", [], f"帧头 {got} ≠ 原版 {want}"))
    print(f"\n  汇总（共 {len(rows)} 组）：")
    print(f"   6/6 校验通过      : {nok}/{len(rows)}")
    print(f"   守恒成立          : {ncons}/{len(rows)}")
    print(f"   同种子可复现      : {nsame}/{len(rows)}")
    print(f"   法祷零违规        : {len(rows)-ncv}/{len(rows)}")
    print(f"   失败项合计        : {len(fails)}")
    for f in fails[:8]:
        print(f"     ✗ {f[0]} / 种子 {f[1]}: {f[2]}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
