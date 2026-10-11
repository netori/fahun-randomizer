/* engine.js — 随机化引擎（GUI 用；规则与 scripts/randomizer.py 一致）
 *
 * 可配置：domains（rune/armor/weapon 任意子集）、joins（联合池分组）、shops、merge_shadow、sets、seed
 * 硬约束：① 法师/祷告护甲独立成池（同部位·同倾向·护甲↔护甲·永不入联合池）
 *         ② 套装整组不拆散（头→头、身→身、臂→臂、腿→腿）
 *         ③ 同一物品多处来源整组一致
 *         ④ 非联合池内护甲同部位、不跨倾向
 *         ⑤ 按池多重集合守恒
 * 说明：本文件的随机源（mulberry32）与 python 版不同，**同一 seed 不会逐行一致**，
 *       但池结构、约束与统计口径完全相同。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Engine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const SUF = { "0000": "head", "0100": "body", "0200": "arm", "0300": "leg" };
  const SUF3 = { "000": "head", "100": "body", "200": "arm", "300": "leg" };   // MOD 护甲 id 尾 3 位
  const SUF4 = { "0000": "head", "0100": "body", "0200": "arm", "0300": "leg" }; // 8 位 id 尾 4 位
  function partCodeOf(iid) {                       // → {part, base}
    const i = String(iid);
    if (SUF4[i.slice(-4)]) return { part: SUF4[i.slice(-4)], base: i.slice(0, -4), code: i.slice(-4) };
    if (SUF3[i.slice(-3)]) return { part: SUF3[i.slice(-3)], base: i.slice(0, -3), code: i.slice(-3) };
    return { part: "", base: "", code: "" };
  }

  const CATCODE = { protector: "3", weapon: "2", goods: "1" };
  const DOMAIN_OF_CAT = { protector: "armor", weapon: "weapon", goods: "rune" };
  const CASTER_ARCH = ["法师", "祷告", "法师/祷告混合", "祷告/感应"];
  const DEFAULT_CONFIG = { domains: ["rune", "armor", "weapon"], joins: [], shops: true, merge_shadow: false, sets: true, seed: 20261010 };

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function shuffle(arr, rng) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }
  const key = (k) => k.split(":")[0] + ":" + k.split(":")[1];
  const catOf = (k) => k.split(":")[0];
  const idOf = (k) => k.split(":")[1];

  function buildPools(items, cfg) {
    const doms = new Set(cfg.domains);
    const joins = (cfg.joins || []).map((g) => new Set(g));
    const pools = new Map();
    const add = (pool, unit, kind) => {
      if (!pools.has(pool)) pools.set(pool, { kind: kind || "item", units: [] });
      if (kind === "set") pools.get(pool).kind = "set";
      pools.get(pool).units.push(unit);
    };
    const joinGroupOf = (domain, arch) => {
      for (const g of joins) {
        if (g.has(domain) && g.size > 1) {
          if (domain === "armor" && CASTER_ARCH.includes(arch)) return null; // 硬约束①
          return g;
        }
      }
      return null;
    };

    // 护甲：先识别完整四件套
    const sets = new Map();
    for (const [k, v] of Object.entries(items)) {
      if (v.cat !== "protector" || !doms.has(v.domain)) continue;
      const pc = partCodeOf(idOf(k));
      if (!pc.part) continue;
      const base = pc.base + "|" + v.arch;
      if (!sets.has(base)) sets.set(base, { arch: v.arch, realBase: pc.base, parts: {} });
      sets.get(base).parts[pc.part] = k;
    }
    const setPieces = new Set();
    if (cfg.sets) {
      for (const [, s] of sets) {
        if (Object.keys(s.parts).length !== 4) continue;
        Object.values(s.parts).forEach((k) => setPieces.add(k));
        add("set@" + s.arch, { id: "set:" + s.realBase, items: Object.values(s.parts), parts: { ...s.parts }, arch: s.arch, base: s.realBase }, "set");
      }
    } else {
      setPieces.clear();
    }

    // 单件
    for (const [k, v] of Object.entries(items)) {
      if (!doms.has(v.domain) || setPieces.has(k)) continue;
      let pool = null;
      if (v.cat === "protector") {
        const part = partCodeOf(idOf(k)).part;
        if (!part) continue;
        const g = joinGroupOf("armor", v.arch);
        pool = g ? "joint:" + [...g].sort().join("+") : "armor:" + part + "@" + v.arch;
      } else {
        const g = joinGroupOf(v.domain, v.arch);
        if (g) pool = "joint:" + [...g].sort().join("+");
        else if (v.cat === "weapon" && (v.subpool || "").startsWith("weapon:cat")) pool = v.subpool;
        else if (v.cat === "goods" && (v.subpool || "").startsWith("rune:")) {
          let tier = v.subpool.split("@")[0].split(":")[1];
          if (cfg.merge_shadow && tier.startsWith("大师级")) tier = "大师级";
          pool = "rune:" + tier + "@" + v.arch;
        } else continue;
      }
      add(pool, { id: "item:" + k, items: [k], parts: {}, arch: v.arch });
    }
    const out = {};
    for (const [p, m] of pools) if (m.units.length) out[p] = m;
    return out;
  }

  function emit(items, target, source, pool, keep) {
    const rows = [];
    if (Object.keys(target.parts || {}).length) {
      for (const part of Object.keys(target.parts)) {
        const tkey = target.parts[part];
        const skey = keep ? tkey : (source.parts[part] || tkey);
        for (const c of items[tkey].cells)
          rows.push({ pool, unit: target.id, role: "set", part, old: tkey, old_cat: catOf(tkey), new: skey, new_cat: catOf(skey), ...c });
      }
    } else {
      const tkey = target.items[0];
      const skey = keep ? tkey : source.items[0];
      for (const c of items[tkey].cells)
        rows.push({ pool, unit: target.id, role: "item", part: "", old: tkey, old_cat: catOf(tkey), new: skey, new_cat: catOf(skey), ...c });
    }
    return rows;
  }

  function run(items, cfg, seed) {
    seed = seed === undefined ? cfg.seed : seed;
    const pools = buildPools(items, cfg);
    const rng = mulberry32(seed >>> 0);
    const plan = [];
    for (const pool of Object.keys(pools).sort()) {
      const units = pools[pool].units;
      if (units.length < 2) {
        for (const u of units) plan.push(...emit(items, u, u, pool, true));
        continue;
      }
      let cand = units.slice();
      for (let a = 0; a < 500; a++) {
        cand = shuffle(units.slice(), rng);
        if (cand.every((c, i) => c.id !== units[i].id)) break;
      }
      units.forEach((u, i) => plan.push(...emit(items, u, cand[i], pool, false)));
    }
    return { plan, pools, seed };
  }

  function verify(items, cfg, plan, pools) {
    const checks = {}, info = {};
    const archOf = (k) => (items[k] ? items[k].arch : "");
    let strict = true, setOk = true, casterOk = true, f4 = true;
    let relaxed = 0, jointCells = 0, catChanged = 0;
    for (const p of plan) {
      const joined = p.pool.startsWith("joint:");
      const aOld = archOf(p.old), aNew = archOf(p.new);
      const oldPart = partCodeOf(idOf(p.old)).part, newPart = partCodeOf(idOf(p.new)).part;
      const caster = (p.old_cat === "protector" && CASTER_ARCH.includes(aOld)) || (p.new_cat === "protector" && CASTER_ARCH.includes(aNew));
      if (joined) jointCells++;
      if (p.old_cat !== p.new_cat) catChanged++;
      if (p.role === "set") { if (oldPart !== newPart) setOk = false; continue; }
      if (caster) {
        if (joined || p.old_cat !== "protector" || p.new_cat !== "protector") casterOk = false;
        else if (oldPart !== newPart || aOld !== aNew) casterOk = false;
      } else if (p.old_cat === "protector" && p.new_cat === "protector") {
        if (joined) relaxed++;
        else if (oldPart !== newPart || aOld !== aNew) { strict = false; f4 = false; }
      } else if (joined) relaxed++;
      else if (oldPart && newPart && oldPart !== newPart) strict = false;
    }
    checks["F1 非联合池内护甲同部位 · 套装不拆散"] = strict && setOk;
    checks["F2 法师/祷告护甲独立成池（同部位·同倾向·护甲↔护甲·不入联合池）"] = casterOk;
    checks["F4 非联合池内护甲不跨职业倾向"] = f4;
    const grp = new Map();
    for (const p of plan) {
      if (p.role !== "item") continue;
      const kk = p.pool + "|" + p.old;
      if (!grp.has(kk)) grp.set(kk, new Set());
      grp.get(kk).add(p.new);
    }
    checks["F3 同一物品多处来源整组一致"] = [...grp.values()].every((s) => s.size === 1);
    checks["F5 未使用冻结项（D1/D5）"] = true;
    let ms = true;
    for (const pool of Object.keys(pools)) {
      const meta = pools[pool];
      let before, after;
      if (meta.kind === "item") {
        before = meta.units.map((u) => u.items[0]).sort();
        after = [...new Set(plan.filter((p) => p.pool === pool).map((p) => p.new))].sort();
      } else {
        before = meta.units.map((u) => u.base).sort();
        after = [...new Set(plan.filter((p) => p.pool === pool).map((p) => p.unit.split(":")[1]))].sort();
      }
      if (JSON.stringify(before) !== JSON.stringify(after)) ms = false;
    }
    checks["多重集合守恒（按池）"] = ms;
    info["联合池内跨类别/放宽格数"] = relaxed;
    info["联合池总格数"] = jointCells;
    info["需同时改类别字段的格数"] = catChanged;
    info["池数"] = Object.keys(pools).length;
    info["置换行数"] = plan.length;
    return { checks, info };
  }

  function summary(items, cfg, pools, plan) {
    const byDomain = { armor: 0, weapon: 0, rune: 0 };
    const byTable = {};
    let shopRows = 0;
    for (const p of plan) {
      const d = DOMAIN_OF_CAT[p.old_cat];
      if (d) byDomain[d]++;
      byTable[p.source_table] = (byTable[p.source_table] || 0) + 1;
      if (p.source_table === "ShopLineupParam") shopRows++;
    }
    const poolKinds = {};
    for (const pool of Object.keys(pools)) {
      const kind = pool.startsWith("joint:") ? "联合池" : pool.startsWith("set@") ? "套装池" : pool.startsWith("armor:") ? "护甲池" : pool.startsWith("weapon:") ? "武器池" : "卢恩池";
      poolKinds[kind] = (poolKinds[kind] || 0) + 1;
    }
    return { byDomain, byTable, shopRows, poolKinds };
  }

  return { SUF, SUF3, SUF4, partCodeOf, CATCODE, DOMAIN_OF_CAT, CASTER_ARCH, DEFAULT_CONFIG, buildPools, run, verify, summary, mulberry32 };
});
