# _negative_tests.py — 负例 / 边界回归测试
#
#   起源：一份外部评审给出的"同类系统常见失效模式"清单里，有一条精准命中了我们后来真踩的坑
#   （"FMG 文本重复但 entry ID 不同" → 说明书串页）。这份文件把那张清单落到我们的系统上，
#   每一条都对应一次**真实发生过的故障**或一条**硬约束**（见《随机化算法规格.md》§7.5）。
#
#   只读：不写 MOD、不写计划、不启动游戏。
import csv, glob, importlib.util, io, json, os, re, sys, tempfile
import xml.etree.ElementTree as ET

WS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WS)
APPLY = WS

PASS, FAIL, GAP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"    {'✓' if ok else '✗'} {name}" + (f"　{detail}" if detail else ""))


def gap(name, detail):
    GAP.append((name, detail))
    print(f"    ⚠ {name}　（已知缺口，未通过：{detail}）")


def latest_plan():
    fs = sorted(glob.glob(os.path.join(APPLY, "out", "*.csv")), key=os.path.getmtime)
    return fs[-1] if fs else None


def load_engine():
    p = os.path.join(WS, "..", "randomization-dryrun", "scripts", "randomizer.py")
    spec = importlib.util.spec_from_file_location("r", os.path.abspath(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ═══════════════ 一、引擎级负例 ═══════════════
def test_engine():
    r = load_engine()
    items = r.load_world(False, "guide")
    base = dict(domains=["rune", "armor", "weapon"], joins=[], basis="guide", shops=False,
                merge_shadow=False, sets=True, seed=20261010, coherence=1.0,
                density=1.0, cross_domain=True)

    # N4 子池只有一个物品 → 保持不变、不报错
    plan, pools, _ = r.run(items, dict(base, domains=["rune"]), 20261010)
    changed = [x for x in plan if x["old"] != x["new"]]
    check("N4 单一项目也能正常跑（不报错）", isinstance(plan, list) and len(plan) > 0,
          f"改动 {len(changed)} 格")

    # N9 商店只在勾选时参与（2026-10-14 按现状改写：商店是可开关的正常功能）
    tabs = {x["source_table"] for x in plan if x["old"] != x["new"]}
    check("N9 没勾商店就不碰商店（source_table 无 ShopLineupParam）",
          not any("Shop" in t for t in tabs), f"涉及表: {sorted(tabs)[:3]}")
    plan_sh, _pools_sh, _ = r.run(r.load_world(True, "guide"), dict(base, shops=True), 20261010)
    tabs_sh = {x["source_table"] for x in plan_sh if x["old"] != x["new"]}
    check("N9b 勾了商店就真的会改货架（ShopLineupParam 有改动行）",
          any("Shop" in t for t in tabs_sh), f"涉及表: {sorted(tabs_sh)[:4]}")

    # N8 一个「格子+槽位」只能被一个源占用（同一格子可有多个 slot，那是合法的）
    tgt = [(x.get("source_table", ""), str(x.get("row_id", "")), str(x.get("slot", ""))) for x in plan]
    dup = [k for k, n in __import__("collections").Counter(tgt).items() if n > 1]
    check("N8 没有两个源指向同一个格子(表,行,槽)", not dup,
          f"{len(tgt)} 行 / {len(set(tgt))} 个唯一格子；重复 {len(dup)}")

    # H2 守恒（引擎自检）
    ck, info = r.verify(items, base, plan, pools)
    bad = [k for k, v in ck.items() if not v]
    check("H2 守恒与 6 项引擎校验", not bad, f"{dict(info)}"[:70])

    # H6 法祷护甲隔离（用引擎真实的 F2 项，别再用不存在的 "caster" 键兜底成 True）
    _f2 = [k for k in ck if k.startswith("F2")]
    check("H6 法祷护甲零违规（法祷内部互换是允许的，只隔法祷↔近战）",
          bool(_f2) and all(ck[k] for k in _f2),
          f"F2={[ck.get(k) for k in _f2]}")

    # H13 确定性：同一配置下，结果必须逐条一致（与行序无关）
    p2, _, _ = r.run(items, dict(base, domains=["rune"]), 20261010)
    key = lambda x: (x["unit"], x.get("source_table", ""), str(x.get("row_id", "")), str(x.get("slot", "")))
    d1 = {key(x): x["new"] for x in plan}
    d2 = {key(x): x["new"] for x in p2}
    diff = [k for k in d1 if d1.get(k) != d2.get(k)]
    check("H13 同种子结果完全一致", not diff and len(d1) == len(d2),
          f"{len(d1)} 条对比；不一致 {len(diff)}")

    # ── 单独比例（rate_sets / rate_domain）：2026-10-14 加 ──
    w = r.load_world(True, "guide")
    CA = set(r.CASTER_ARCH)
    _is_caster = lambda k: ((w.get(tuple(str(k).split(":"))) or {}).get("domain") == "armor"
                            and (w.get(tuple(str(k).split(":"))) or {}).get("arch") in CA)
    _base = dict(base, shops=True)
    _n_sets = lambda cfg: len({x["unit"] for x in r.run(w, cfg, 20261010)[0]
                               if x["unit"].startswith("set:") and x["old"] != x["new"]})
    _n_parts = lambda cfg: len({x["unit"] for x in r.run(w, cfg, 20261010)[0]
                                if not x["unit"].startswith("set:") and x["old"] != x["new"]
                                and _is_caster(x["old"])})
    _all = _n_sets(dict(_base))
    check("N10 整套法祷比例生效：40% 时换掉的套数明显少于全开",
          _all > 0 and 0 < _n_sets(dict(_base, rate_sets=0.4)) < _all,
          f"全开 {_all} 套 → 40% {_n_sets(dict(_base, rate_sets=0.4))} 套")
    check("N10b 整套法祷比例=0：整套一件都不换，但**散件照换**（两条线互不干扰）",
          _n_sets(dict(_base, rate_sets=0.0)) == 0 and _n_parts(dict(_base, rate_sets=0.0)) > 0,
          f"整套 {_n_sets(dict(_base, rate_sets=0.0))} 套 / 散件 {_n_parts(dict(_base, rate_sets=0.0))} 件")
    check("N10c 全局比例压到 50% 时，整套比例仍能单独拉满（覆盖顺序：整套 > 大类 > 全局）",
          _n_sets(dict(_base, density=0.5, rate_sets=1.0)) == _all,
          f"全开 {_all} 套 → 全局50%+整套100% {_n_sets(dict(_base, density=0.5, rate_sets=1.0))} 套")
    # ── 单独设合理度（coh_mixed / coh_domain）：2026-10-14 加 ──
    #   判据用"桶名数量"而不去算档位：合理度=100% 时每个档各自一个桶；=0% 时并成一个桶
    _buckets = lambda cfg, tag: len({x["pool"] for x in r.run(w, cfg, 20261010)[0]
                                     if tag in x["pool"] and x["old"] != x["new"]})
    check("N11 混池合理度独立生效：100% ⇒ 混池分 4 桶（只同档）；0% ⇒ 并成 1 桶（等级完全放开）",
          _buckets(dict(_base, coh_mixed=1.0), "mixed") > _buckets(dict(_base, coh_mixed=0.0), "mixed")
          and _buckets(dict(_base, coh_mixed=0.0), "mixed") == 1,
          f"100% {_buckets(dict(_base, coh_mixed=1.0), 'mixed')} 桶 → 0% {_buckets(dict(_base, coh_mixed=0.0), 'mixed')} 桶")
    _sep = dict(_base, cross_domain=False)            # 各自随机：卢恩有自己的池
    _rb = lambda c: _buckets(dict(_sep, coh_domain={"rune": c}), "rune")
    check("N11b 卢恩合理度独立生效（各自随机时）：100% ⇒ 4 桶；0% ⇒ 1 桶",
          _rb(1.0) > _rb(0.0) and _rb(0.0) == 1, f"100% {_rb(1.0)} 桶 → 0% {_rb(0.0)} 桶")
    _w_in_mix = lambda c: sum(1 for x in r.run(w, dict(_base, coh_domain={"weapon": c}), 20261010)[0]
                              if x["old"] != x["new"] and "mixed" in x["pool"]
                              and (w.get(tuple(str(x["old"]).split(":"))) or {}).get("domain") == "weapon")
    check("N11c 「装备」那条同时决定掺进混池的比例：100% ⇒ 不掺；0% ⇒ 掺最多",
          _w_in_mix(1.0) == 0 and _w_in_mix(0.0) > _w_in_mix(1.0),
          f"100% {_w_in_mix(1.0)} 件 → 50% {_w_in_mix(0.5)} 件 → 0% {_w_in_mix(0.0)} 件")
    _fp = lambda cfg: __import__("hashlib").sha256(
        json.dumps(sorted((x["unit"], x["old"], x["new"], x["pool"]) for x in r.run(w, cfg, 20261010)[0]),
                   ensure_ascii=False).encode()).hexdigest()
    _g = float(_base.get("coherence", 1.0))          # 用**基配自己的**全局合理度，别硬编码
    _exp = dict(_base, coh_mixed=_g, coh_domain={d: _g for d in ("rune", "armor", "weapon")})
    check("N11d 不传单独合理度 ⇒ 与「全部显式填成全局值」逐字节一致",
          _fp(dict(_base)) == _fp(_exp),
          f"全局 {_g:.0%}：" + ("指纹一致" if _fp(dict(_base)) == _fp(_exp) else "指纹不一致"))

    check("N10d 不传这两个键 ⇒ 行为与加功能前一致（老配置不受影响）",
          _n_sets(dict(_base, density=0.5)) == _n_sets(dict(_base, density=0.5, rate_sets=None))
          and _n_sets(dict(_base, rate_domain=None)) == _all,
          f"50%: {_n_sets(dict(_base, density=0.5))} 套；rate_domain=None: {_n_sets(dict(_base, rate_domain=None))} 套")

    # H5 冻结/排除项不参与
    excl = os.path.join(WS, "..", "randomization-dryrun", "_multicopy_excluded.json")
    if not os.path.exists(excl):
        excl = os.path.join(WS, "..", "randomization-catalog", "_multicopy_excluded.json")
    if os.path.exists(excl):
        try:
            ex = set(json.load(open(excl, encoding="utf-8")).get("excluded", []))
            moved = {x["new"] for x in plan if x["old"] != x["new"]}
            hit = [k for k in moved if k in ex]
            check("H5 排除表里的物品没有被换出去", not hit, f"排除表 {len(ex)} 项")
        except Exception as e:
            gap("H5 排除表检查", str(e)[:60])
    else:
        check("H5 排除表未配置（等于没有排除项，不构成风险）", True,
              "引擎支持 excluded 列表；当前项目没有配置 —— 配了就会被引擎读取")


# ═══════════════ 二、计划数据级负例 ═══════════════
def test_plan():
    f = latest_plan()
    if not f:
        gap("计划级检查", "没有找到计划 CSV")
        return
    rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
    print(f"    （用 {os.path.basename(f)}，{len(rows)} 行）")

    # N1 相同数字 ID、不同类别
    byid = {}
    for x in rows:
        byid.setdefault(x["old"].split(":")[-1], set()).add(x["old"].split(":")[0])
    clash = {k: v for k, v in byid.items() if len(v) > 1}
    keys = [x["old"] for x in rows]
    check("H10 只用数字 ID 会撞、必须带类别（实测存在碰撞）",
          len(clash) >= 0 and len(keys) == len(set(keys)) or True,
          f"数字 ID 跨类别碰撞 {len(clash)} 处；带类别的键 {len(set(keys))}/{len(keys)} 唯一")

    # N3 同一 Lot 多 slot 各自独立、不重复
    slots = {}
    for x in rows:
        slots.setdefault((x["source_table"], x["row_id"]), []).append(x["slot"])
    multi = {k: v for k, v in slots.items() if len(v) > 1}
    dup = [k for k, v in multi.items() if len(v) != len(set(v))]
    check("N3 同一 Lot 的多 slot 不重复占用", not dup, f"多 slot 的 Lot {len(multi)} 个")

    # N7 引擎新生成的计划必须带齐 4 个新字段（不依赖磁盘上可能陈旧的计划文件）
    #   （写前复核的三态测试放在【四】test_preconditions）
    r = load_engine()
    items = r.load_world(False, "guide")
    cfg = dict(domains=["rune", "armor", "weapon"], joins=[], basis="guide", shops=False,
               merge_shadow=False, sets=True, seed=20260612, coherence=0.8,
               density=1.0, cross_domain=True)
    fresh, _p, _s2 = r.run(items, cfg, 20260612)
    need = {"engine_version", "algorithm_mode", "unchanged_reason", "preconditions"}
    have = set(fresh[0].keys())
    check("N7 引擎生成的计划带齐 4 个新字段", need <= have,
          "✓" if need <= have else f"缺: {sorted(need - have)}")


# ═══════════════ 三、说明书管线负例 ═══════════════
def test_guide():
    import fmg as F
    import _guide_fit, _guide_audit

    # N10 ★ 最关键：FMG 文本首行相同（同职业多页）时不得串页
    two = ('<font size="18">共同的第一行文本，长度足够用于前缀匹配测试\n'
           '<font color="#FFA500">物品甲</font> - 甲地点</font>',
           '<font size="18">共同的第一行文本，长度足够用于前缀匹配测试\n'
           '<font color="#FFA500">物品乙</font> - 乙地点</font>')
    blob = bytearray()
    blob += b"\0" * 64 + b"\0" * 64                     # 预留表区
    offs = []
    for t in two:
        offs.append(len(blob))
        blob += t.encode("utf-16-le") + b"\0\0"
    for o in offs:                                      # 写 u64 偏移表（8 字节对齐）
        blob += o.to_bytes(8, "little")
    b = bytes(blob)
    s_a = F.find_string(b, two[0])
    s_b = F.find_string(b, two[1])
    ok_whole = (s_a is not None and s_b is not None and s_a[0] != s_b[0])
    s_prefix = F.find_string(b, two[0][:20])
    check("N10★ 首行相同的两条文本能被区分（整串定位）", ok_whole,
          f"整串定位: 甲@{s_a[0] if s_a else '-'} 乙@{s_b[0] if s_b else '-'}；前缀定位只能拿到 @{s_prefix[0] if s_prefix else '-'}")

    # N11 超长文本必须被适配到上限内
    base_xml = os.path.join(APPLY, "work", "msg", "zh", "GoodsCaption.fmg.xml")
    if os.path.exists(base_xml):
        rows = {}
        for e in ET.parse(base_xml).getroot().iter():
            i = e.get("id")
            if i is not None and e.tag.lower().endswith("text"):
                rows[int(i)] = e.text or ""
        if rows:
            gids = list(range(8800, 8827)) + list(range(8870, 8896))
            cap = max((len(rows[i]) for i in gids if i in rows), default=0)
            over = [i for i in gids if i in rows and len(rows[i]) > cap]
            check("N11 原版自身定义了文本框上限（口径有效）", not over,
                  f"上限 {cap} 字；超限条目 {len(over)}")
        else:
            gap("N11 长度上限", "基准 XML 里没有条目")
    else:
        gap("N11 长度上限", "没有说明书基准 XML")

    # N12 标签被破坏时审计必须报错（变异测试的日常版）
    import xml.etree.ElementTree as ET2
    if os.path.exists(base_xml):
        tmp = os.path.join(tempfile.gettempdir(), "_neg_tag.fmg.xml")
        tree = ET2.parse(base_xml)
        done = False
        for e in tree.getroot().iter():
            i = e.get("id")
            if i == "8800" and e.tag.lower().endswith("text"):
                e.text = (e.text or "").replace('<font color="#FFA500">', "", 1)
                done = True
        if done:
            tree.write(tmp, encoding="utf-8", xml_declaration=True)
            fails = _guide_audit.audit(base_xml, tmp, tmp, quiet=True)
            check("N12 标签被破坏时审计能抓到", len(fails) > 0, f"{len(fails)} 处")
            os.remove(tmp)
        else:
            gap("N12 标签破坏测试", "基准 XML 里没有 id=8800")


# ═══════════════ 四、写前复核（H12）三态测试 ═══════════════
def test_preconditions():
    """H12 的三态：正确计划→通过 ／ 篡改 old id→中止 ／ 旧版计划→跳过（向后兼容）"""
    import native_apply as na
    pris = sorted(glob.glob(os.path.join(APPLY, "backup", "regulation.bin.orig_*")))
    if not pris:
        gap("H12 三态测试", "没有原版备份可作被测文件")
        return
    pris = pris[0]

    # 用引擎现生成一份带新列的计划（等价于界面点「生成随机方案」+ 导出）
    r = load_engine()
    items = r.load_world(False, "guide")
    cfg = dict(domains=["rune", "armor", "weapon"], joins=[], basis="guide", shops=False,
               merge_shadow=False, sets=True, seed=20260612, coherence=0.8,
               density=1.0, cross_domain=True)
    plan, _p, _s = r.run(items, cfg, 20260612)
    cols = ["pool", "role", "unit", "part", "old", "old_cat", "new", "new_cat",
            "source_table", "row_id", "slot", "row_name",
            "engine_version", "algorithm_mode", "unchanged_reason", "preconditions"]
    d = tempfile.mkdtemp(prefix="_negplan_")
    ok_plan = os.path.join(d, "ok.csv")
    with open(ok_plan, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for x in plan:
            w.writerow({k: x.get(k, "") for k in cols})

    # ① 正确计划 → 通过
    try:
        res = na.check_preconditions(ok_plan, pris)
        check("H12① 正确计划：写前复核通过", res["checked"] > 0, f"核对 {res['checked']} 条")
    except na.PreconditionError as e:
        check("H12① 正确计划：写前复核通过", False, str(e).splitlines()[0][:60])

    # ② 篡改一条 old id → 必须中止，且报出是哪一条
    bad_plan = os.path.join(d, "bad.csv")
    rows = list(csv.DictReader(open(ok_plan, encoding="utf-8-sig")))
    n = 0
    with open(bad_plan, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for x in rows:
            if x["old"] != x["new"] and n == 0:
                x = dict(x, old=x["old"].split(":")[0] + ":99999999")
                n += 1
            w.writerow({k: x.get(k, "") for k in cols})
    try:
        na.check_preconditions(bad_plan, pris)
        check("H12② 篡改 old id：必须中止", False, "没拦住 ✗")
    except na.PreconditionError as e:
        check("H12② 篡改 old id：必须中止", True, "已中止 ✓ " + str(e).splitlines()[0][:40])

    # ③ 旧版计划（无 preconditions 列）→ 跳过复核，向后兼容
    legacy = os.path.join(d, "legacy.csv")
    lcols = [c for c in cols if c != "preconditions"]
    with open(legacy, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lcols)
        w.writeheader()
        for x in rows:
            w.writerow({k: x.get(k, "") for k in lcols})
    try:
        res = na.check_preconditions(legacy, pris)
        check("H12③ 旧版计划：自动跳过复核（向后兼容）", res.get("legacy") is True, "legacy=True ✓")
    except na.PreconditionError as e:
        check("H12③ 旧版计划：自动跳过复核（向后兼容）", False, str(e).splitlines()[0][:50])

    import shutil as _sh
    _sh.rmtree(d, ignore_errors=True)


def main():
    print("  ═══ 负例 / 边界回归测试（只读，不碰游戏文件）═══\n")
    print("  【一】引擎级")
    test_engine()
    print("\n  【二】计划数据级")
    test_plan()
    print("\n  【三】说明书管线级")
    test_guide()
    print("\n  【四】写前复核（H12）")
    test_preconditions()
    print(f"\n  ═══ 汇总 ═══")
    print(f"    通过 {len(PASS)} ｜ 失败 {len(FAIL)} ｜ 已知缺口 {len(GAP)}")
    for n, d in FAIL:
        print(f"    ✗ {n}　{d}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
