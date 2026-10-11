/* test_engine.js — 用 node 测 GUI 引擎：配置矩阵 × 多种子，断言全部硬约束
 * 运行：node tests/test_engine.js   （或 node test_engine.js）
 */
const fs = require("fs");
const path = require("path");
const Engine = require("./engine.js");

const DRY = __dirname;
const world = JSON.parse(fs.readFileSync(path.join(DRY, "world.json"), "utf8"));

function configs() {
  const D = ["rune", "armor", "weapon"];
  const out = [];
  const combos = [["rune"], ["armor"], ["weapon"], ["rune", "armor"], ["rune", "weapon"], ["armor", "weapon"], D];
  for (const c of combos) {
    out.push({ domains: c, joins: [] });
    if (c.length >= 2) out.push({ domains: c, joins: [c.slice()] });
    if (c.length === 3) {
      out.push({ domains: c, joins: [["rune", "weapon"]] });
      out.push({ domains: c, joins: [["rune", "armor"]] });
      out.push({ domains: c, joins: [["armor", "weapon"]] });
      out.push({ domains: c, joins: [["rune", "weapon"], ["armor"]] });
    }
  }
  return out;
}

function checker(items, cfg, plan, pools) {
  const problems = [];
  // 1) 引擎自校验
  const { checks } = Engine.verify(items, cfg, plan, pools);
  for (const [k, v] of Object.entries(checks)) if (!v) problems.push("引擎校验失败: " + k);
  // 2) 额外独立检查：法师护甲绝不出现在联合池
  for (const p of plan) {
    const aOld = items[p.old] ? items[p.old].arch : "";
    const aNew = items[p.new] ? items[p.new].arch : "";
    const casterInvolved = (p.old_cat === "protector" && Engine.CASTER_ARCH.includes(aOld)) ||
                           (p.new_cat === "protector" && Engine.CASTER_ARCH.includes(aNew));
    if (casterInvolved) {
      if (p.pool.startsWith("joint:")) problems.push("法师护甲出现在联合池");
      if (p.old_cat !== "protector" || p.new_cat !== "protector") problems.push("法师护甲与非护甲互换");
      if (aOld !== aNew) problems.push("法师护甲跨倾向");
      const op = Engine.partCodeOf(p.old.split(":")[1]).part, np = Engine.partCodeOf(p.new.split(":")[1]).part;
      if (op !== np) problems.push("法师护甲跨部位");
    }
  }
  // 3) 套装：每个目标套的四件必须来自同一个源套
  for (const pool of Object.keys(pools)) {
    if (pools[pool].kind !== "set") continue;
    for (const u of pools[pool].units) {
      const bases = new Set(plan.filter((p) => p.unit === u.id).map((p) => p.new.split(":")[1].slice(0, -4)));
      if (bases.size > 1) problems.push("套装被拆散: " + u.id);
    }
  }
  // 4) 每个格子最多被写一次
  const seen = new Set();
  for (const p of plan) {
    const k = p.source_table + ":" + p.row_id + ":" + p.slot;
    if (seen.has(k)) problems.push("同一格子被写两次: " + k);
    seen.add(k);
  }
  return problems;
}

function main() {
  const seeds = [1, 7, 42, 20261010, 99999];
  let runs = 0, fail = 0;
  const bad = [];
  const BASE = world.bases || { xlsx: { items: world.items, items_noshop: world.items_noshop } };
  for (const basis of Object.keys(BASE)) for (const cfg0 of configs()) {
    for (const shops of [true, false]) {
      for (const sets of [true, false]) {
        for (const seed of seeds) {
          const cfg = Object.assign({}, Engine.DEFAULT_CONFIG, cfg0, { basis, shops, sets, seed });
          const items = shops ? BASE[basis].items : BASE[basis].items_noshop;
          const { plan, pools } = Engine.run(items, cfg, seed);
          runs++;
          const problems = checker(items, cfg, plan, pools);
          if (problems.length) {
            fail++;
            bad.push({ cfg: { domains: cfg.domains, joins: cfg.joins, shops, sets, seed }, problems: problems.slice(0, 4) });
          }
        }
      }
    }
  }
  console.log("=== JS 引擎测试 ===");
  console.log(`  运行次数: ${runs} | 失败: ${fail}`);
  for (const b of bad.slice(0, 8)) console.log("   ❌", JSON.stringify(b));
  // 抽样展示
  const basis0 = Object.keys(BASE)[0];
  const cfg = Object.assign({}, Engine.DEFAULT_CONFIG, { basis: basis0, shops: true, sets: true, seed: 20261010 });
  const { plan, pools } = Engine.run(BASE[basis0].items, cfg, 20261010);
  const { checks, info } = Engine.verify(BASE[basis0].items, cfg, plan, pools);
  console.log("\n  默认配置抽样：池", Object.keys(pools).length, "| 行", plan.length);
  console.log("  校验:", checks);
  console.log("  信息:", info);
  process.exit(fail ? 1 : 0);
}

main();
