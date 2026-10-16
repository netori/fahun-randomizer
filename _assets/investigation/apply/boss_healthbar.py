# -*- coding: utf-8 -*-
"""从 EMEVD 的 .js 反编译版里抽出"有血条的 Boss"名单（只读游戏文件）

为什么可行：法魂自带 267 个事件脚本的 `.js` 反编译版，里面能直接搜到
`DisplayBossHealthBar(Enabled, <实体id>, <槽位>, <名字id>)`。
名字 id 在 NpcName*.fmg 的 9 亿号段里（例如 904750000 → “接肢”葛瑞克），
而 NpcParam 里 Boss 行的 nameId 基本是 0 —— 所以**Boss 的显示名只能从这里拿**。

────────────────────────────────────────────────────────────────────────────
v2 修了两个坑（都在 v1 里把 Boss 名搞错/搞丢）：

【坑 1 · FMG 区间记录】v1 复用的 `enemy_names.parse_fmg` 把一条区间记录
`[lo, hi]` 的文本**整段复制**给区间内每个 id。实测这是错的：区间记录的语义是
    id `lo + k` → 字符串槽 `slot + k`（每条 id 有自己的字符串）
证据（本文件 --explain-fmg 可复现）：
    GoodsName  slot=1102 lo=2950 hi=2971  '接肢的追忆'
      2950→'接肢的追忆' 2951→'碎星的追忆' 2952→'恶兆王的追忆' … 2971→'假龙之王的追忆'
    NpcName    slot=621? lo=902130000 hi=902130003 '“恶兆妖鬼”玛尔基特'
      902130000→'“恶兆妖鬼”玛尔基特'  902130002→'“恶兆王”蒙葛特'
    自检：区间长度之和恰好等于字符串槽数（GoodsName 4689≈4791、GoodsName_dlc01 1549=1549）。
    ⇒ 后果：蒙葛特 / 玛利喀斯 / 荷莱·露 / 背叛熔炉者斯卡德 / 塑灵者凯玛 / “米凯拉的王”拉塔恩
      这些 Boss 在 v1 名单里**名字是错的**（被区间里第一个名字盖住），看起来像"缺了"。

【坑 2 · 公共模板事件】法魂的**野外 Boss（m60_*/m61_* 大地图 + 部分洞窟）**不走本图
   的字面调用，而是 `InitializeCommonEvent(0, 90005870, <实体>, <名字id>, <BGM区域>)`
   去调 `common_func.emevd` 里的模板，模板体里写的是 `DisplayBossHealthBar(Enabled, X0_4, 0, X4_4)`
   —— 实体与名字都是**形参**。v1 直接把这些模板整条丢掉（占位符过滤），于是漏掉上百个野外 Boss。
   v2 会解析 `$Event(<id>, …, function(<形参>))` 定义 + 所有 `InitializeCommonEvent/InitializeEvent`
   调用点，按位代入。

产出：investigation/boss_healthbar.csv
      列：map,entity,slot,name_id,name,source,name_src,ref,note
      source ∈ {map_script, common, alias}
        map_script = 该地图脚本里的字面调用
        common     = 该地图脚本调 common_func 的 90005xxx 模板（参数在调用点）
        alias      = 该地图脚本自己定义的带参事件（参数在同文件调用点）
      name_src   = 名字取自哪个 FMG（NpcName/NpcName_dlc01/PlaceName/…）
      ref        = 证据（事件文件:行号，模板行会写成 "调用点 → 模板定义处"）
      note       = 空 / commented（该行在 .js 里是注释掉的）

只读：本脚本不写除 CSV 之外的任何文件，也不改 mod/event 下任何东西。
"""
import collections
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_randomizer as ER          # 复用它的 MOD 路径解析（别自己拼层级，容易差一层）
import enemy_names as EN               # 复用它的 FMG 底层原语（fmg_records / _u64 / _read_utf16）

# _mod_reg() = <MOD>/mod/regulation.bin → 往上两级就是 <MOD>
MOD = os.environ.get("CONVERGENCE_MOD_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(ER._mod_reg())))
EVENT_DIR = os.path.join(MOD, "mod", "event")
OUT = os.path.join(HERE, "..", "boss_healthbar.csv")

# 名字表：NpcName 系列是主表；PlaceName 系列做兜底（Boss 场地名，偶尔才是真名）
NAME_STEMS_PRIMARY = ("NpcName", "NpcName_dlc01", "NpcName_dlc02")
NAME_STEMS_FALLBACK = ("PlaceName", "PlaceName_dlc01", "PlaceName_dlc02")
GOODS_STEMS = ("GoodsName", "GoodsName_dlc01", "GoodsName_dlc02")

RE_PLACEHOLDER = re.compile(r"^X\d+_\d+$")
RE_EVENT = re.compile(r"\$Event\(\s*(\d+)\s*,\s*[A-Za-z_]+\s*,\s*function\s*\(([^)]*)\)")
RE_BAR = re.compile(r"DisplayBossHealthBar\(\s*([A-Za-z]+)\s*,")
RE_CALL = re.compile(r"(?P<name>\$?Initialize(?:Common)?Event)\(")
RE_ASSIGN = re.compile(r"(?:^|\s)(?:const|let|var)?\s*([A-Za-z_]\w*)\s*=\s*(\d+)\s*;?")
RE_TOP_CONST = re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(\d+)\s*;?\s*$", re.M)
SPAN_MAX = 4096                        # 区间展开上限（防脏记录把表撑爆）


# ── FMG ──────────────────────────────────────────────────────────────────
def parse_fmg_by_slot(data):
    """FMG → ``{真 id: 文本}``（**修正版**：区间 [lo,hi] → 字符串槽 [slot, slot+(hi-lo)]）

    与 ``enemy_names.parse_fmg`` 的差别只有一处，但很关键：区间里每个 id 拿**自己那一条**
    字符串，而不是整段共用第一条。自检见模块 docstring。
    """
    tab = EN._u32(data, EN.H_OFF_TABLE)
    n_str = EN._u32(data, EN.H_STR_COUNT)
    if not (EN.ID_TABLE <= tab <= len(data)) or n_str > 0x800000:
        return {}
    offs = []
    for i in range(n_str):
        p = tab + 8 * i
        offs.append(EN._u64(data, p) if p + 8 <= len(data) else 0)
    out = {}
    for slot, lo, hi, _t in EN.fmg_records(data):
        if not lo:
            continue
        if hi < lo or hi - lo > SPAN_MAX:
            hi = lo
        for k in range(hi - lo + 1):
            s = slot + k
            if s >= len(offs) or not offs[s]:
                continue
            txt = EN._read_utf16(data, offs[s])
            if txt:
                out.setdefault(lo + k, txt)
    return out


def load_fmg_tables(stems):
    """读 mod 的 msgbnd → ``{stem: {id: 文本}}``（只取要的 FMG）"""
    path = EN.find_msgbnd(EN.default_mod_dir())
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("找不到 msgbnd：%s" % path)
    want = set(stems)
    out = {}
    for internal, blob in EN.read_msgbnd_files(path):
        stem = os.path.basename(internal.replace("\\", "/"))[:-4]
        if stem in want:
            out[stem] = parse_fmg_by_slot(blob)
    return out


def make_name_resolver(tables):
    """名字 id → (文本, 来源 FMG)。NpcName 系列优先，PlaceName 兜底。"""
    def resolve(nid):
        for stem in NAME_STEMS_PRIMARY:
            t = tables.get(stem)
            if t and nid in t:
                return t[nid], stem
        for stem in NAME_STEMS_FALLBACK:
            t = tables.get(stem)
            if t and nid in t:
                return t[nid], stem
        return "", ""
    return resolve


# ── .js 解析 ─────────────────────────────────────────────────────────────
def read_js(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def split_args(s):
    """按逗号切参数，尊重括号/引号嵌套"""
    out, depth, cur, q = [], 0, [], ""
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = ""
            continue
        if ch in "\"'":
            q = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return out


def scan_js(text):
    """一个 .js → (事件表, 调用点表)

    事件表：``{事件id: {"params": [...], "bars": [(行号, 状态, 实体, 槽位, 名字id)],
                        "vars": {变量名: 字面量}}}``
    调用点表：``[(行号, 被调事件id, [实参…], 是否注释)]``
    """
    lines = text.splitlines()
    # 文件级常量（m31_81/m31_82 这类脚本把 BossEntityId / bossName 常量写在文件头，
    # 事件体里只引用名字 —— 不收集就会把实体认成"认不出"）
    top_consts = {m.group(1): int(m.group(2)) for m in RE_TOP_CONST.finditer(text)}
    # 事件块：把 $Event(...) 定义切成段落
    starts = list(RE_EVENT.finditer(text))
    offsets = []
    for i, m in enumerate(starts):
        a = m.start()
        b = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        offsets.append((m, text[a:b]))

    def lineno(pos):
        return text.count("\n", 0, pos) + 1

    events = {}
    for m, body in offsets:
        eid = int(m.group(1))
        params = [p.strip() for p in split_args(m.group(2)) if p.strip()]
        bars = []
        for bm in RE_BAR.finditer(body):
            # 找整条调用（到匹配的右括号）
            j = body.index("(", bm.start())
            depth, k = 0, j
            while k < len(body):
                if body[k] == "(":
                    depth += 1
                elif body[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            args = split_args(body[j + 1:k])
            if len(args) < 4:
                continue
            abs_line = lineno(m.start() + bm.start())
            raw_line = lines[abs_line - 1] if abs_line - 1 < len(lines) else ""
            bars.append((abs_line, args[0], args[1], args[2], args[3],
                         raw_line.strip().startswith("//")))
        vars_ = dict(top_consts)                 # 文件级常量先铺底
        for am in RE_ASSIGN.finditer(body):
            vars_.setdefault(am.group(1), int(am.group(2)))
        for name, val in top_consts.items():     # 文件级常量优先级更高（别被同名局部覆盖）
            vars_[name] = val
        events[eid] = {"params": params, "bars": bars, "vars": vars_}

    # 调用点（两种语法：InitializeEvent / InitializeCommonEvent，首个实参是层号）
    calls = []
    for cm in RE_CALL.finditer(text):
        j = text.index("(", cm.start())
        depth, k = 0, j
        while k < len(text):
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        args = split_args(text[j + 1:k])
        if len(args) < 2 or not args[1].isdigit():
            continue
        ln = lineno(cm.start())
        raw_line = lines[ln - 1] if ln - 1 < len(lines) else ""
        calls.append((ln, int(args[1]), args[2:], raw_line.strip().startswith("//")))
    return events, calls


def param_index(name, params):
    """形参/局部变量名 → 位置。X0_4→0 X4_4→1 …；具名形参按声明顺序。"""
    if RE_PLACEHOLDER.match(name):
        return int(name[1:].split("_")[0]) // 4
    if name in params:
        return params.index(name)
    return None


def literal_or_param(tok, params, vars_):
    """实参记号 → (值, 扮演的角色) 角色 ∈ {literal, param}；认不出返回 (None, None)"""
    t = tok.strip()
    if t.lstrip("-").isdigit():
        return int(t), "literal"
    if t in vars_:
        return vars_[t], "literal"
    if param_index(t, params) is not None:
        return param_index(t, params), "param"
    # X12_4 + 0 之类：只取整数字面量
    m = re.fullmatch(r"(\d+)\s*[+\-]\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (a + b if "+" in t else a - b), "literal"
    return None, None


# ── 主流程 ───────────────────────────────────────────────────────────────
def explain_fmg():
    """自检：打印区间记录 → 连续字符串槽的证据"""
    tables = load_fmg_tables(NAME_STEMS_PRIMARY + GOODS_STEMS)
    path = EN.find_msgbnd(EN.default_mod_dir())
    blobs = {os.path.basename(i.replace("\\", "/"))[:-4]: b for i, b in EN.read_msgbnd_files(path)}
    for stem, lo0, span in (("GoodsName", 2950, 24), ("NpcName", 902130000, 6),
                            ("NpcName_dlc01", 905220000, 3), ("GoodsName_dlc01", 2002900, 12)):
        print("\n### %s ###" % stem)
        for k in range(span):
            i = lo0 + k
            print("   %-12d %r" % (i, tables.get(stem, {}).get(i)))
        rec = [r for r in EN.fmg_records(blobs[stem]) if r[1] == lo0]
        if rec:
            s, lo, hi, t = rec[0]
            print("   ← 原始记录 slot=%d lo=%d hi=%d 首个文本=%r"
                  % (s, lo, hi, t))
    print("\n### 区间长度 vs 字符串槽数（应大致相等） ###")
    for stem in ("GoodsName", "GoodsName_dlc01", "NpcName", "NpcName_dlc01"):
        b = blobs.get(stem)
        if b is None:
            continue
        n_str = EN._u32(b, EN.H_STR_COUNT)
        span = 0
        for _s, lo, hi, t in EN.fmg_records(b):
            if t and lo and hi >= lo and hi - lo <= SPAN_MAX:
                span += hi - lo + 1
        print("   %-16s n_str=%-6d Σ(hi-lo+1)=%-6d" % (stem, n_str, span))
    return 0


def main():
    tables = load_fmg_tables(NAME_STEMS_PRIMARY + NAME_STEMS_FALLBACK + GOODS_STEMS)
    resolve = make_name_resolver(tables)
    for stem in NAME_STEMS_PRIMARY + NAME_STEMS_FALLBACK:
        print("  名字表 %-18s %d 条" % (stem, len(tables.get(stem, {}))))

    files = sorted(glob.glob(os.path.join(EVENT_DIR, "*.js")))
    per_file, total_bars, total_calls = {}, 0, 0
    for p in files:
        mid = os.path.basename(p).split(".")[0]
        ev, calls = scan_js(read_js(p))
        per_file[mid] = (ev, calls)
        total_bars += sum(len(e["bars"]) for e in ev.values())
        total_calls += len(calls)
    print("扫了 %d 个事件脚本｜DisplayBossHealthBar 调用 %d 处｜事件定义 %d｜跨/同文件调用点 %d"
          % (len(files), total_bars, sum(len(e) for e, _ in per_file.values()), total_calls))

    # 模板索引：哪些事件体内有血条、且实参是形参（跨文件可调）
    templates = {}          # eid -> (定义文件, params, [(bar行号,状态,实体tok,槽位,名字tok,注释)])
    for mid, (ev, _c) in per_file.items():
        for eid, e in ev.items():
            param_bars = [b for b in e["bars"] if b[1] == "Enabled"]
            if param_bars and any(
                    literal_or_param(b[2], e["params"], e["vars"])[1] == "param"
                    or literal_or_param(b[4], e["params"], e["vars"])[1] == "param"
                    for b in param_bars):
                templates[eid] = (mid, e["params"], param_bars,
                                  {b[0] for b in e["bars"] if b[5]})

    # 调用点索引：eid -> [(调用文件, 行号, 实参, 注释)]
    callers = collections.defaultdict(list)
    for mid, (_ev, calls) in per_file.items():
        for ln, eid, args, commented in calls:
            callers[eid].append((mid, ln, args, commented))

    rows = []
    unresolved = []
    tmpl_hits = collections.Counter()

    def emit(mapping, ent, slot, nid, source, ref, commented):
        if ent is None or nid is None:
            unresolved.append((mapping, None, None, ref, "实参认不出"))
            return
        if RE_PLACEHOLDER.match(str(ent)) or RE_PLACEHOLDER.match(str(nid)):
            unresolved.append((mapping, ent, nid, ref, "占位符"))
            return
        name, src = resolve(nid) if nid else ("", "")
        note = []
        if commented:
            note.append("commented")
        if mapping in ("common", "common_func") and source == "map_script":
            note.append("公共脚本里的字面量（非具体 Boss，模板自带的占位实体）")
        rows.append({"map": mapping, "entity": ent, "slot": slot, "name_id": nid,
                     "name": name, "source": source, "name_src": src, "ref": ref,
                     "note": "; ".join(note)})

    for mid, (ev, _c) in per_file.items():
        for eid, e in ev.items():
            bars = [b for b in e["bars"] if b[1] == "Enabled"]
            if not bars or eid not in templates:
                # 该事件体内的血条全都是字面量（或只有 Disabled）→ 就地成行
                for bar in bars:
                    ln, _st, ent, slot, nid, com = bar
                    v_ent, k_ent = literal_or_param(ent, e["params"], e["vars"])
                    v_nid, k_nid = literal_or_param(nid, e["params"], e["vars"])
                    v_slot, k_slot = literal_or_param(slot, e["params"], e["vars"])
                    if k_ent == "param" or k_nid == "param":
                        continue          # 在下面按调用点展开
                    emit(mid, v_ent, v_slot, v_nid, "map_script",
                         "%s.emevd.dcx.js:%d" % (mid, ln), com)

    # 模板 → 调用点展开
    for eid, (defmid, params, bars, _c) in sorted(templates.items()):
        sites = callers.get(eid, [])
        for src_map, ln, args, caller_commented in sites:
            for bar in bars:
                bline, _st, ent_tok, slot_tok, nid_tok, body_commented = bar

                def sub(tok):
                    v, kind = literal_or_param(tok, params, {})
                    if kind == "param" and v is not None:
                        return int(args[v]) if v < len(args) and args[v].lstrip("-").isdigit() else None
                    return v

                ent, nid, slot = sub(ent_tok), sub(nid_tok), sub(slot_tok)
                kind = "common" if eid >= 90000000 else "alias"
                ref = "%s:%d → %s:%d" % (src_map, ln, defmid, bline)
                emit(src_map, ent, slot, nid, kind, ref,
                     caller_commented or body_commented)
                tmpl_hits[eid] += 1

    # 去重（同 地图+实体+槽位+名字id 只留一条；注释行让位于非注释行）
    merged = {}
    keys = ("map", "entity", "slot", "name_id")
    for r in rows:
        k = tuple(r[x] for x in keys)
        old = merged.get(k)
        if old is None or (old["note"] and not r["note"]):
            merged[k] = r
    out = [merged[k] for k in sorted(merged, key=lambda t: (str(t[0]), int(t[1]), int(t[2]), int(t[3])))]

    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["map", "entity", "slot", "name_id", "name",
                                          "source", "name_src", "ref", "note"])
        w.writeheader()
        w.writerows(out)

    # ── 报告 ──
    print("\n=== 结果 ===")
    print("  → %s（%d 行）" % (os.path.abspath(OUT), len(out)))
    bysrc = collections.Counter(r["source"] for r in out)
    for s, c in sorted(bysrc.items()):
        print("     source=%-10s %d 行" % (s, c))
    named = [r for r in out if r["name"]]
    print("  有名字 %d 行｜唯一名字 %d 个｜唯一实体 %d 个｜覆盖地图 %d 张"
          % (len(named), len({r["name"] for r in named}),
             len({r["entity"] for r in out}), len({r["map"] for r in out})))
    print("  name_src:", dict(collections.Counter(r["name_src"] for r in named)))
    print("  注释行 %d 行（.js 里被 // 关掉、其实不会跑）"
          % sum(1 for r in out if r["note"]))
    print("  无名行 %d 行（名字 id 没在 FMG 里找到文本）" % (len(out) - len(named)))
    for r in [x for x in out if not x["name"] and x["name_id"]][:12]:
        print("     %-14s %-11d name_id=%-11d %s" % (r["map"], r["entity"], r["name_id"], r["ref"]))

    print("\n=== 模板调用展开情况 ===")
    for eid, (defmid, params, bars, _c) in sorted(templates.items()):
        print("   %-11d 定义在 %-14s 形参=%-38s 血条 %d 处 → 调用点 %d 个 / 展开 %d 行"
              % (eid, defmid, ",".join(params), len(bars),
                 len(callers.get(eid, [])), tmpl_hits[eid]))
    if unresolved:
        print("\n=== 认不出的实参（%d）===" % len(unresolved))
        for u in unresolved[:12]:
            print("   %s" % (u,))

    # ── 备选指令核查（"是不是另一条指令在开血条？"）──
    instr = collections.Counter()
    for p in files:
        t = read_js(p)
        for m in re.finditer(r"\b([A-Za-z]*(?:Boss|Banner|HealthBar)[A-Za-z]*)\(", t):
            instr[m.group(1)] += 1
    print("\n=== 备选指令核查（哪个指令带名字参数？）===")
    for k, v in instr.most_common():
        print("   %-38s x%-4d %s" % (k, v,
              "带名字 id（唯一的名字来源）" if k == "DisplayBossHealthBar"
              else "无名字参数" if k.endswith("Banner") else ""))

    # 缺口：名字表里存在、但没有任何血条调用引用。
    # 只报"新名字的首个 id"（同一名字的一串变体不刷屏），方便人肉核对。
    used = {r["name_id"] for r in out if r["name_id"]}
    allids = set()
    for stem in NAME_STEMS_PRIMARY:
        allids |= {i for i in tables.get(stem, {}) if i >= 900000000}
    heads = []
    for i in sorted(allids):
        txt = resolve(i)[0]
        if not txt or i in used:
            continue
        if resolve(i - 1)[0] != txt:
            heads.append((i, txt))
    print("\n=== 缺口：名字表里有、但没有任何血条调用引用（%d 个名字 / %d 个 id）==="
          % (len(heads), len([i for i in allids if i not in used and resolve(i)[0]])))
    for i, txt in heads:
        print("   %-12d %s" % (i, txt))
    return 0


if __name__ == "__main__":
    if "--explain-fmg" in sys.argv:
        sys.exit(explain_fmg())
    sys.exit(main())
