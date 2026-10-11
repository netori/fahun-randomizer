# fix_part_codes.py — ① 修「部位尾号」解析（MOD 护甲 id 有 6/7/8 位，尾 3 位才是部位码）
#                     ② 把推荐表交叉核对得到的映射写进 name_resolution_curated.json
# 幂等：重复运行不会重复插入。
import json, os, re

DRY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(DRY, "evidence", "name_resolution_curated.json")

SUF3_BLOCK_PY = '''
SUF3 = {"000": "head", "100": "body", "200": "arm", "300": "leg"}          # MOD 护甲 id 尾 3 位
SUF4 = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}      # 8 位 id 尾 4 位


def part_code_of(iid):
    """返回 (部位码, 套装基号)：兼容 6/7/8 位 id（例 5253000→head/5253、5230100→body/5230）"""
    i = str(iid)
    if i[-4:] in SUF4:
        return i[-4:], i[:-4]
    if i[-3:] in SUF3:
        return i[-3:], i[:-3]
    return "", ""


def part_of(iid):
    c, _ = part_code_of(iid)
    return SUF4.get(c) or SUF3.get(c) or ""
'''

SUF3_BLOCK_JS = '''
  const SUF3 = { "000": "head", "100": "body", "200": "arm", "300": "leg" };   // MOD 护甲 id 尾 3 位
  const SUF4 = { "0000": "head", "0100": "body", "0200": "arm", "0300": "leg" }; // 8 位 id 尾 4 位
  function partCodeOf(iid) {                       // → {part, base}
    const i = String(iid);
    if (SUF4[i.slice(-4)]) return { part: SUF4[i.slice(-4)], base: i.slice(0, -4), code: i.slice(-4) };
    if (SUF3[i.slice(-3)]) return { part: SUF3[i.slice(-3)], base: i.slice(0, -3), code: i.slice(-3) };
    return { part: "", base: "", code: "" };
  }
'''


def patch(path, subs, marker):
    p = os.path.join(DRY, path)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print(f"  {path}: 已是新版，跳过")
        return
    for a, b in subs:
        if a not in s:
            raise SystemExit(f"  未找到锚点（{path}）: {a[:60]!r}")
        s = s.replace(a, b)
    open(p, "w", encoding="utf-8").write(s)
    print(f"  {path}: 已修补")


def main():
    print("=== ① 部位码解析修补 ===")
    # randomizer.py
    patch("scripts/randomizer.py", [
        ('SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}',
         'SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}' + SUF3_BLOCK_PY),
        ('''        if v["cat"] == "protector" and v["domain"] in doms and str(k[1])[-4:] in SUF:
            sets[(base_of(k), v["arch"])][SUF[str(k[1])[-4:]]] = k''',
         '''        if v["cat"] == "protector" and v["domain"] in doms and part_code_of(k[1]):
            code, sbase = part_code_of(k[1])
            sets[(sbase, v["arch"])][part_of(k[1])] = k'''),
        ('''        if v["cat"] == "protector":
            part = SUF.get(str(k[1])[-4:], "")
            if part not in ("head", "body", "arm", "leg"):
                continue''',
         '''        if v["cat"] == "protector":
            part = part_of(k[1])
            if part not in ("head", "body", "arm", "leg"):
                continue'''),
        ('''def base_of(k):
    return str(k[1])[:-4]''', '''def base_of(k):
    return part_code_of(k[1])[1] or str(k[1])'''),
        ('''        old_part, new_part = SUF.get(id_of(p["old"])[-4:], ""), SUF.get(id_of(p["new"])[-4:], "")''',
         '''        old_part, new_part = part_of(id_of(p["old"])), part_of(id_of(p["new"]))'''),
    ], marker="SUF3_BLOCK_MARKER" if False else "part_code_of")
    # engine.js
    patch("engine.js", [
        ('''  const SUF = { "0000": "head", "0100": "body", "0200": "arm", "0300": "leg" };''',
         '''  const SUF = { "0000": "head", "0100": "body", "0200": "arm", "0300": "leg" };''' + SUF3_BLOCK_JS),
        ('''      const tail = idOf(k).slice(-4);
      if (!SUF[tail]) continue;
      const base = idOf(k).slice(0, -4) + "|" + v.arch;
      if (!sets.has(base)) sets.set(base, { arch: v.arch, realBase: idOf(k).slice(0, -4), parts: {} });
      sets.get(base).parts[SUF[tail]] = k;''',
         '''      const pc = partCodeOf(idOf(k));
      if (!pc.part) continue;
      const base = pc.base + "|" + v.arch;
      if (!sets.has(base)) sets.set(base, { arch: v.arch, realBase: pc.base, parts: {} });
      sets.get(base).parts[pc.part] = k;'''),
        ('''      if (v.cat === "protector") {
        const part = SUF[idOf(k).slice(-4)];''',
         '''      if (v.cat === "protector") {
        const part = partCodeOf(idOf(k)).part;'''),
        ('''      const oldPart = SUF[idOf(p.old).slice(-4)] || "", newPart = SUF[idOf(p.new).slice(-4)] || "";''',
         '''      const oldPart = partCodeOf(idOf(p.old)).part, newPart = partCodeOf(idOf(p.new)).part;'''),
        ('''  return { SUF, CATCODE, DOMAIN_OF_CAT, CASTER_ARCH, DEFAULT_CONFIG, buildPools, run, verify, summary, mulberry32 };''',
         '''  return { SUF, SUF3, SUF4, partCodeOf, CATCODE, DOMAIN_OF_CAT, CASTER_ARCH, DEFAULT_CONFIG, buildPools, run, verify, summary, mulberry32 };'''),
    ], marker="partCodeOf")
    # parse_guide_full.py：部位判断也用新函数
    p = os.path.join(DRY, "scripts", "parse_guide_full.py")
    s = open(p, encoding="utf-8").read()
    if "SUF3 = " not in s:
        s = s.replace('SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}',
                      'SUF = {"0000": "head", "0100": "body", "0200": "arm", "0300": "leg"}' + SUF3_BLOCK_PY)
        s = s.replace('            part = SUF.get(r["matched_id"][-4:], "")',
                      '            part = part_of(r["matched_id"])')
        open(p, "w", encoding="utf-8").write(s)
        print("  scripts/parse_guide_full.py: 已修补")

    print("\n=== ② 交叉核对得到的映射写入 curated ===")
    d = json.load(open(CUR, encoding="utf-8"))
    E = d["entries"]
    add = {
        "铁斗笠": {"target": "铁笠帽", "reason": "推荐表『铁笠帽』地点=从萨米尔废墟的夏玻利利处获得，与说明书『夏玻利利占据尤拉身体后在其遗体上发现』同一事件", "evidence": "crosscheck"},
        "熔炉锤型盔": {"target": "熔炉槌形盔", "reason": "推荐表『熔炉槌形盔』地点=熔炉骑士泥盆亚掉落，与说明书同地点（锤型/槌形为异写）", "evidence": "crosscheck"},
        "灵火火炬": {"target": "灵火火把", "reason": "推荐表『灵火火把』=死之鸟掉落（利耶尼亚），与说明书『利耶尼亚死亡鸟』同指（火炬/火把异写）", "evidence": "crosscheck"},
        "猎犬钩爪": {"target": "猎犬弯爪", "reason": "推荐表『猎犬弯爪』地点=火山官邸-猎犬骑士，与说明书『火山官邸』吻合（钩爪/弯爪异写）", "evidence": "crosscheck"},
        "王室大剑": {"target": "王室巨剑", "reason": "推荐表『王室大剑』(冰霜巫师) 地点=三姊妹塔击败布莱泽；王室巨剑 4060000 即布莱泽的剑", "evidence": "crosscheck", "inference": True},
        "马雷家套装": {"expand_prefix": "玛雷家", "reason": "推荐表『玛雷家套装』；MOD 名称为 玛雷家面具/玛雷家长袍…（马/玛异写）", "evidence": "crosscheck"},
        "幼年狮子套装": {"expand_prefix": "年少狮子", "reason": "推荐表『年少狮子套装』(基本主义者) 地点=击败约定之王拉塔恩后在大赐福购买，与说明书『击败约定之王后可购买』同地", "evidence": "crosscheck"},
        "神鸟战士套装": {"expand_prefix": "神鸟", "reason": "推荐表『神鸟战士套装』(野兽宗徒) 地点=劳弗古遗迹内部，与说明书同地；MOD 件名为 神鸟头盔/神鸟战士铠甲…", "evidence": "crosscheck"},
        "神兽战士套装": {"expand_prefix": "神兽", "reason": "推荐表『神兽战士套装』(风暴呼召者)；MOD 件名为 神兽头盔/神兽战士铠甲…", "evidence": "crosscheck"},
        "老翁套装": {"expand_prefix": "老翁", "reason": "推荐表『老翁套装』(鲜血新锐) 地点=唤灵洞窟内拾取，与说明书同地；MOD 件名为 老翁面具…", "evidence": "crosscheck"},
        "熔炉树套装": {"expand_prefix": "熔炉树", "reason": "推荐表『熔炉树形套装』(野兽宗徒) 地点=深根底层小boss志留亚掉落，与说明书『击败熔炉骑士志留亚』同源", "evidence": "crosscheck"},
        "黑焰习武修士套装": {"expand_prefix": "黑焰习武修士", "reason": "推荐表『黑焰习武修士套装』(神皮庆典者) 地点=火山官邸艾格蕾教堂楼层底部牢房，与说明书『火山官邸』吻合", "evidence": "crosscheck"},
        "黑夜女巫套装": {"expand_prefix": "黑夜女巫", "reason": "推荐表『黑夜女巫套装』(诺克斯神谕官) 地点=黑夜神域指头刀宝箱旁；MOD 件名为 黑夜女巫双生冠/铠甲/手环/腿甲", "evidence": "crosscheck"},
        "诺克斯剑士套装": {"expand_prefix": "诺克斯剑士", "reason": "推荐表『诺克斯剑士套装』(诺克斯神谕官) 地点=瑟利亚结晶坑道隐藏墙后宝箱，与说明书『瑟利亚结晶坑道』同地", "evidence": "crosscheck"},
        "塑灵者套装": {"expand_prefix": "塑灵者", "reason": "推荐表『塑灵者套装』(密契者) 地点=击败凯玛后可在解指处购买，与说明书同地；MOD 件名为 塑灵者鹿角/披风/腕带/长裤", "evidence": "crosscheck"},
    }
    n = 0
    for k, v in add.items():
        if E.get(k) != v:
            E[k] = v
            n += 1
    d["crosscheck_note"] = "这 15 条由 crosscheck_rec_table.py 用《职业推荐道具表3.0》的同名/同地点证据确定（见 evidence/rec_table_crosscheck.json）"
    json.dump(d, open(CUR, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  curated 新增/更新 {n} 条，现有 {len(E)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
