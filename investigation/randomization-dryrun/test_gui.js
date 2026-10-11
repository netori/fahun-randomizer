/* test_gui.js — 用最小 DOM 桩在 node 里真跑 GUI.html 的脚本：
 *   ① 语法与加载路径（world.js / engine.js）
 *   ② 首次渲染 roll() 是否走通
 *   ③ 页面里的"自检"按钮逻辑（多配置 × 多种子）是否 0 失败
 * 运行：node test_gui.js
 */
const fs = require("fs"), path = require("path");
const DIR = __dirname;

// ---- 最小 DOM 桩 ----
const store = {};
const defaults = { "d-rune": true, "d-armor": true, "d-weapon": true, "o-shops": true, "o-sets": true,
                   "o-shadow": false, "o-seed": 20261010, "filter": "" };
function El(id) {
  if (store[id]) return store[id];
  const e = { id, value: defaults[id] !== undefined ? String(defaults[id]) : "",
              checked: !!defaults[id], style: {}, textContent: "", _html: "",
              querySelector: (sel) => El(id + "::" + sel),      // 子元素缓存，便于断言渲染结果
              appendChild() {}, click() {}, addEventListener(ev, fn) { (e._h = e._h || {})[ev] = fn; } };
  Object.defineProperty(e, "innerHTML", { set(v) { e._html = v; }, get() { return e._html; } });
  store[id] = e;
  return e;
}
global.document = {
  getElementById: El,
  querySelector: (sel) => {
    if (sel.indexOf("join") >= 0) return { value: "" };          // 默认：各自独立
    return { value: "" };
  },
  querySelectorAll: () => [],
  createElement: () => ({ style: {}, click() {}, set href(v) {}, set download(v) {} }),
};
global.Blob = function () {};
global.URL = { createObjectURL: () => "blob:x" };
global.alert = (m) => { console.log("  [alert]", m); };
global.window = global;

// ---- 载入 world.js / engine.js / GUI 内联脚本 ----
eval(fs.readFileSync(path.join(DIR, "world.js"), "utf8"));
global.Engine = require(path.join(DIR, "engine.js"));
const WB = WORLD.bases || { mix: { items: WORLD.items, items_noshop: WORLD.items_noshop } };
console.log("world.js 载入:", Object.keys(WB).join("/"), "| 物品数:", Object.keys(WB.mix.items).length, "| engine.js:", typeof Engine.run);

const html = fs.readFileSync(path.join(DIR, "GUI.html"), "utf8");
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
console.log("内联脚本块:", inline.length);
try {
  eval(inline[inline.length - 1]);
  console.log("✅ GUI 脚本执行无异常（首次 roll() 已渲染）");
} catch (e) {
  console.log("❌ GUI 脚本执行失败:", e.message);
  process.exit(1);
}

// ---- 检查渲染结果 ----
const stats = El("stats").innerHTML, checks = El("checks").innerHTML,
      pools = El("pool-table::tbody").innerHTML, swaps = El("swap-table::tbody").innerHTML;
console.log("  统计卡片渲染:", stats.length > 200 ? "✅" : "❌", "| 校验渲染:", checks.split("✅").length - 1, "项通过",
            "| 池表渲染:", (pools.match(/<tr>/g) || []).length, "行",
            "| 置换表:", (swaps.match(/<tr>/g) || []).length, "行");
if (checks.indexOf("❌") >= 0) { console.log("❌ 默认配置出现校验失败"); process.exit(1); }

// ---- 触发页面里的自检按钮 ----
const btn = El("selftest");
if (btn._h && btn._h.click) {
  console.time("  页面自检");
  btn._h.click();
  console.timeEnd("  页面自检");
  const out = El("selftest-out").innerHTML;
  console.log("  自检输出:", out.replace(/<[^>]+>/g, ""));
  process.exit(out.indexOf("❌") >= 0 ? 1 : 0);
} else {
  console.log("❌ 未找到自检按钮处理器");
  process.exit(1);
}
