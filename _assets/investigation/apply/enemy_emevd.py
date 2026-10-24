# -*- coding: utf-8 -*-
"""方案乙：让「Boss 血条名字 / BGM」跟着新 Boss 走（只改 EMEVD 的 int 参数槽，不结构重写）。

背景（2026-10-17 审计 P2 / 用户要求）：
  * 血条名与 BGM 不在 NpcParam 里，而在 EMEVD 事件脚本的参数里 —— 方案甲（只改
    regulation+MSB）永远改不动它们；这就是「② 血条名/BGM/出场动画还是原 Boss 的」。
  * 参考实现是**重写事件**（19320 行 events.txt）。我们这条「乙」只做最小侵入：
    找到该地图事件脚本里「显示这条 Boss 血条」「设置这场 Boss BGM」的指令，
    把**名字 id 参数 / bgmBossConvParamId 参数**换成新 Boss 的 —— 指令结构与事件流一律不动。

可定位的依据（本机实测，2026-10-18）：
  * 法魂 `mod/event/` 带 268 个事件脚本的 `.dcx` 与 `.js` 反编译版（.js 只用于**定位**，不进游戏）；
  * 字面量 `DisplayBossHealthBar(Enabled, <实体>, <槽位>, <名字id>)` →
    二进制里是连续的 4 个 u32 `[enabled, 实体, 槽位, 名字id]`（实测 m10_00 等 30 图 71/71 命中）；
  * 公共模板 `InitializeCommonEvent(0, 90005870, <实体>, <名字id>, <BGM区域>)` →
    二进制里是连续的 `[90005870, 实体, 名字id, BGM区域]`（m12_01/02/03 实测 4/4 命中）；
  * BGM：模板体里 `SetBossBGM(X4_4, …)`（9005822/9005823/9005824/… 等 7 个模板）→
    调用点第二个实参就是 bgmBossConvParamId，二进制里是 `[事件id, 失败flag, bgm参数, …]`（实测唯一命中）。
    新 Boss 的 bgm 参数从"它原本作为 Boss 出场的那张图"的调用点反查（134 个 npc 有目录）。

范围与限制（如实写进报告 / 界面）：
  * **出场动画不改**：它由事件流本身决定（不是单个 int 参数），要做得重写事件（方案丙）。
  * 找不到目标的血条名/BGM 参数时**不猜**：该 part 保留原值，并在报告里计为 skipped。
  * 只写**方案层**里的 `event/*.emevd.dcx`；mod 本体/游戏 Data 一个字节都不动。
  * 输出与原文件同 DCX 压缩格式（KRAK 优先，失败降级 DFLT 并记录），落盘后自读回核对参数。

用法（供部署链调用；也可命令行自检）：
    python investigation\\apply\\enemy_emevd.py --selftest
"""
import collections
import csv
import glob
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import boss_healthbar as BH     # noqa: E402  只借它的 .js 解析（参数/事件扫描）
import msb_read as M            # noqa: E402
import msb_write as W           # noqa: E402

INV = os.path.dirname(HERE)
DCX_HEAD_LEN = 76               # 与 msb_write 的实测口径一致（EMEVD 的 DCX 头也是 0x4c 载荷起点）

#: 与好友 NPC/占位实体无关的普通 Boss 血条模板（实测 90005870 是野外 Boss 的主入口；
#: 其它模板也在 `.js` 里扫出来，不硬编码 —— 见 _name_templates）
BGM_TEMPLATE_HINT = "SetBossBGM(X4_4"


# ────────────────────────── 数据表 ──────────────────────────

def mod_root():
    import enemy_randomizer as ER
    return os.path.dirname(os.path.dirname(os.path.abspath(ER._mod_reg())))


def event_dir():
    return os.path.join(mod_root(), "mod", "event")


def load_boss_name_ids(path=None):
    """{npc_id: 血条名字 id}（boss_rows.csv 是 EMEVD 解包实测；同一 npc 取出现最多的非 0 值）"""
    p = path or os.path.join(INV, "boss_rows.csv")
    cnt = collections.defaultdict(collections.Counter)
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                nid = (r.get("npc_id") or "").strip()
                name = (r.get("name_id") or "").strip()
                if nid.isdigit() and name.isdigit() and int(name) > 0:
                    cnt[int(nid)][int(name)] += 1
    except Exception:
        return {}
    return {k: v.most_common(1)[0][0] for k, v in cnt.items()}


def load_entity_npc(path=None):
    """{(map, entity_id): npc_id}（map_enemies.csv；用于把 BGM 调用点的失败 flag 反查成 Boss 行）"""
    p = path or os.path.join(INV, "map_enemies.csv")
    out = {}
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                e = (r.get("entity_id") or "").strip()
                n = (r.get("npc_id") or "").strip()
                if e.isdigit() and n.lstrip("-").isdigit():
                    out[(r.get("map") or "", int(e))] = int(n)
    except Exception:
        return {}
    return out


def load_model_name_ids(path=None):
    """{模型: 血条名字 id}（boss_rows.csv 的模型级众数）。

    为什么要模型级兜底：计划里 Boss 目标行只有约 1/3 是 EMEVD 血条行，其余同行**没有**
    自己的 name_id → 换过去后血条名只能保留旧名（用户实测"部分 Boss 名字没换"）。
    同一模型的 Boss 通常共用一个血条名，用它兜底比"名字不动"正确得多。
    """
    p = path or os.path.join(INV, "boss_rows.csv")
    cnt = collections.defaultdict(collections.Counter)
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = (r.get("model") or "").strip()
                nid = (r.get("name_id") or "").strip()
                if m and nid.isdigit() and int(nid) > 0:
                    cnt[m][int(nid)] += 1
    except Exception:
        return {}
    # 只接受**唯一**名字的模型：一个模型对应多个血条名时（如玛利喀斯/野兽祭司这种多形态）
    # 拿众数会给出"另一个形态的名字"——用户实测过"名字错误"，宁可不动也别猜。
    return {k: next(iter(v)) for k, v in cnt.items() if len(v) == 1}


def expand_name_ids(name_ids):
    """给"没有自己血条名 id"的目标行补上**它模型**的 Boss 名字（只在模型确有名时补）"""
    import enemy_randomizer as ER
    rm = ER.load_row_models()
    mn = load_model_name_ids()
    out = dict(name_ids)
    for npc, model in rm.items():
        if npc not in out and model in mn:
            out[npc] = mn[model]
    return out


def expand_bgm_ids(bgm_ids):
    """给"没有自己 bgm 参数"的目标行补上**它模型**的 bgm 参数（模型级众数）"""
    import enemy_randomizer as ER
    rm = ER.load_row_models()
    by_model = collections.defaultdict(collections.Counter)
    for npc, bgm in bgm_ids.items():
        m = rm.get(npc)
        if m:
            by_model[m][bgm] += 1
    out = dict(bgm_ids)
    for npc, model in rm.items():
        if npc not in out and model in by_model and len(by_model[model]) == 1:
            out[npc] = next(iter(by_model[model]))      # 同模型多个 bgm ⇒ 不猜
    return out


# ────────────────────────── .js 定位数据 ──────────────────────────

def _event_bodies(text):
    """{事件id: 事件正文} —— BH.scan_js 只回结构，这里要正文找 SetBossBGM"""
    out = {}
    starts = list(BH.RE_EVENT.finditer(text))
    for i, m in enumerate(starts):
        a = m.start()
        b = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        out[int(m.group(1))] = (m.group(2), text[a:b])
    return out


def _scan_all(ev_dir):
    """扫全部 .js：返回 (per_map, name_templates, bgm_templates)。

    关键：血条名字模板（`DisplayBossHealthBar(Enabled, X0_4, …, X4_4)`）定义在
    `common_func.emevd.dcx.js` 里，而调用点在各地图脚本 —— 模板必须**全局**收集，
    只按单文件找会一条都匹配不上（自检时踩过：bgm 目录从 134 掉到 3）。
    """
    per_map = {}
    name_templates, bgm_templates = {}, {}
    files = sorted(glob.glob(os.path.join(ev_dir, "*.js")))
    for p in files:
        mid = os.path.basename(p).split(".")[0]
        try:
            text = BH.read_js(p)
            events, calls = BH.scan_js(text)
            bodies = _event_bodies(text)
        except Exception as e:                                     # noqa: BLE001
            per_map[mid] = {"error": str(e)}
            continue
        per_map[mid] = {"events": events, "calls": calls, "bodies": bodies}
        for eid, (params_txt, body) in bodies.items():
            params = [x.strip() for x in BH.split_args(params_txt) if x.strip()]
            if BGM_TEMPLATE_HINT in body:
                bgm_templates[eid] = params
            bars = [b for b in (events.get(eid) or {}).get("bars", [])
                    if b[1] == "Enabled" and not b[5]]
            if bars and any(BH.param_index(b[4], params) is not None for b in bars):
                name_templates[eid] = (params, bars, events.get(eid) or {})
    return per_map, name_templates, bgm_templates


def scan_map_js(fname, per_map, name_templates, bgm_templates):
    """一张地图的定位数据（per_map / 模板表来自 _scan_all 的全局扫描）。

    返回 ``{"literal": {实体: [(槽位, 名字id)]},
             "templated": {实体: [(事件id, 名字id)]},
             "bgm": {实体: (事件id, 失败flag, bgm参数)}}``
    """
    info = per_map.get(fname) or {}
    if "events" not in info:
        return {"literal": {}, "templated": {}, "bgm": {}}
    events, calls = info["events"], info["calls"]
    out = {"literal": collections.defaultdict(list),
           "templated": collections.defaultdict(list),
           "bgm": {}}
    # ① 字面量血条（事件体里直接写死实体与名字 id）
    for eid, e in events.items():
        if eid in name_templates:
            continue
        vars_ = e.get("vars") or {}
        for (_line, st, ent, slot, nid, commented) in e.get("bars", []):
            if st != "Enabled" or commented:
                continue
            v_ent, k_ent = BH.literal_or_param(ent, e["params"], vars_)
            v_nid, k_nid = BH.literal_or_param(nid, e["params"], vars_)
            v_slot, _k = BH.literal_or_param(slot, e["params"], vars_)
            if k_ent == "literal" and k_nid == "literal" and v_ent and v_nid:
                out["literal"][int(v_ent)].append((int(v_slot or 0), int(v_nid)))
    # ② 模板调用点（名字参数）
    for (_line, eid, args, commented) in calls:
        if commented or eid not in name_templates:
            continue
        params, bars, _e = name_templates[eid]
        a = [x.strip() for x in args]
        for (_bl, st, ent_tok, _slot_tok, nid_tok, body_commented) in bars:
            if st != "Enabled" or body_commented:
                continue
            ei, ni = BH.param_index(ent_tok, params), BH.param_index(nid_tok, params)
            if ei is None or ni is None or ei >= len(a) or ni >= len(a):
                continue
            if not a[ei].lstrip("-").isdigit() or not a[ni].lstrip("-").isdigit():
                continue
            if int(a[ei]) <= 0 or int(a[ni]) <= 0:
                continue
            # 记下"名字参数是模板的第几个实参"：二进制里参数是连续 u32（实测 90005882 的
            # 名字在 args[9]），所以补丁位置 = 指令起点 + 4*(1+ni)，不能假设永远是 args[1]。
            out["templated"][int(a[ei])].append((int(eid), int(ni), int(a[ni])))
    # ③ BGM 调用点（第 2 个实参 = bgmBossConvParamId；失败 flag 用来反查实体）
    for (_line, eid, args, commented) in calls:
        if commented or eid not in bgm_templates:
            continue
        a = [x.strip() for x in args]
        if len(a) < 2 or not a[0].lstrip("-").isdigit() or not a[1].lstrip("-").isdigit():
            continue
        out.setdefault("_bgm_calls", []).append((int(eid), int(a[0]), int(a[1])))
    return out


def build_map_data(ev_dir=None, log=None):
    """扫全部 .js → ({map: 定位数据}, {npc: bgm参数})"""
    ev = ev_dir or event_dir()
    ent2npc = load_entity_npc()
    per_map, name_templates, bgm_templates = _scan_all(ev)
    maps = {}
    bgm_npc = collections.defaultdict(collections.Counter)
    for mid in per_map:
        data = scan_map_js(mid, per_map, name_templates, bgm_templates)
        # BGM: 失败 flag → 实体 → npc（先精确，再试常见的 ±1e6 / +1e7 变体）
        for (eid, flag, bgm) in data.get("_bgm_calls") or []:
            npc, ent_id = ent2npc.get((mid, flag)), flag
            if npc is None:
                for cand in (flag + 1000000, flag - 1000000, flag + 10000000):
                    npc = ent2npc.get((mid, cand))
                    if npc is not None:
                        ent_id = cand
                        break
            if npc is not None:
                bgm_npc[npc][bgm] += 1
                data["bgm"].setdefault(ent_id, (eid, flag, bgm))
        maps[mid] = data
    out_bgm = {k: v.most_common(1)[0][0] for k, v in bgm_npc.items()}
    if log:
        log("[方案乙] 事件脚本 %d 个｜血条名字模板 %d 个｜BGM 模板 %d 个｜bgm 目录覆盖 %d 个 npc"
            % (len(maps), len(name_templates), len(bgm_templates), len(out_bgm)))
    return maps, out_bgm


# ────────────────────────── 补丁 ──────────────────────────

def collect_part_swaps(src_map_path, out_map_path):
    """对比改前/改后的同一张 MSB → [(entity_id, 旧npc, 新npc)]（同一实体去重）"""
    a = M.read_msb(src_map_path).get("enemies") or []
    b = M.read_msb(out_map_path).get("enemies") or []
    got = {}
    for x, y in zip(a, b):
        if x.get("npc_id") == y.get("npc_id"):
            continue
        try:
            ent = int(y.get("entity_id") or -1)
            old = int(x.get("npc_id") or -1)
            new = int(y.get("npc_id") or -1)
        except (TypeError, ValueError):
            continue
        if ent <= 0 or old <= 0 or new <= 0:
            continue
        got[(ent, old, new)] = True
    return sorted(got)


def _find_all(raw, pat):
    out, i = [], 0
    while True:
        j = raw.find(pat, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def _patch_u32(raw, pos, new_val):
    struct.pack_into("<I", raw, pos, int(new_val))


def collect_changes(map_names, src_map_dir, out_map_dir):
    """{map 名: [(entity, 旧npc, 新npc)]} —— 从 MSB 改前/改后产物收集"哪些 Boss 摆位换了行"。"""
    got = {}
    for m in map_names:
        base = m if str(m).endswith(".msb.dcx") else str(m) + ".msb.dcx"
        sp = os.path.join(src_map_dir, base)
        op = os.path.join(out_map_dir, base)
        if not (os.path.isfile(sp) and os.path.isfile(op)):
            continue
        swaps = collect_part_swaps(sp, op)
        if swaps:
            got[base.split(".")[0]] = swaps
    return got


def patch_evd_bytes(raw, changes, mdata, name_ids, bgm_ids):
    """在一张图的 EMEVD 明文里改参数。返回 (new_raw, report)。

    changes: [(entity, 旧npc, 新npc)]；mdata: scan_map_js 的结果（按实体索引）；
    name_ids: {npc: 血条名 id}；bgm_ids: {npc: bgm 参数}
    """
    buf = bytearray(raw)
    rep = {"name": 0, "bgm": 0, "skipped": [], "partial": [], "writes": []}
    seen = set()
    for ent, old_npc, new_npc in changes:
        if ent in seen:
            continue
        seen.add(ent)
        new_name = name_ids.get(new_npc)
        new_bgm_val = bgm_ids.get(new_npc)
        got_name = got_bgm = False
        # ① 字面量 DisplayBossHealthBar
        for (slot, old_name) in (mdata.get("literal") or {}).get(ent, []):
            if not new_name:
                continue
            if new_name == old_name:
                got_name = True            # 新旧一样 = 本来就已经对，不算改动
                continue
            for en in (0, 1):
                pat = struct.pack("<4I", en, ent, slot, old_name)
                for pos in _find_all(bytes(buf), pat):
                    _patch_u32(buf, pos + 12, new_name)
                    rep["writes"].append([pos + 12, old_name, new_name, "name-literal"])
                    rep["name"] += 1
                    got_name = True
        # ② 模板调用点（InitializeCommonEvent + 名字参数；参数是连续 u32，按模板下标定位）
        for (eid, ni, old_name) in (mdata.get("templated") or {}).get(ent, []):
            if not new_name:
                continue
            if new_name == old_name:
                got_name = True
                continue
            for pos in _find_all(bytes(buf), struct.pack("<2I", eid, ent)):
                off = pos + 4 * (1 + ni)
                if off + 4 > len(buf):
                    continue
                if struct.unpack_from("<I", buf, off)[0] != old_name:
                    continue                    # 同 eid+ent 的其它调用，别误改
                _patch_u32(buf, off, new_name)
                rep["writes"].append([off, old_name, new_name, "name-templated"])
                rep["name"] += 1
                got_name = True
        # ③ BGM：失败 flag/payload 调用点（参数槽 2 = bgmBossConvParamId）
        bgm_hit = (mdata.get("bgm") or {}).get(ent)
        if bgm_hit and new_bgm_val:
            eid, flag, old_bgm_val = bgm_hit
            if new_bgm_val == old_bgm_val:
                got_bgm = True
            else:
                pat = struct.pack("<3I", eid, flag, old_bgm_val)
                for pos in _find_all(bytes(buf), pat):
                    _patch_u32(buf, pos + 8, new_bgm_val)
                    rep["writes"].append([pos + 8, old_bgm_val, new_bgm_val, "bgm"])
                    rep["bgm"] += 1
                    got_bgm = True
        if not got_name and not got_bgm:
            why = []
            if not new_name:
                why.append("目标行没有血条名 id")
            else:
                why.append("找不到该摆位的血条指令")
            if not new_bgm_val:
                why.append("目标行没有 bgm 参数")
            else:
                why.append("找不到该摆位的 BGM 调用点")
            rep["skipped"].append({"entity": ent, "old_npc": old_npc, "new_npc": new_npc,
                                   "why": "；".join(why)})
        elif not got_bgm:
            rep["partial"].append({"entity": ent, "old_npc": old_npc, "new_npc": new_npc,
                                   "why": ("目标行没有 bgm 参数" if not new_bgm_val
                                           else "找不到该摆位的 BGM 调用点")})
    return bytes(buf), rep


def repack_dcx(data, raw_new):
    """按原文件的 DCX 格式重新封装（KRAK 优先，失败降级 DFLT 并记录）"""
    h = None
    if data[:4] == b"DCX\0":
        import erio
        h = erio.dcx_parts(data)
    out, w = W.dcx_repack(raw_new, in_kind=(h or {}).get("kind"), out_kind="same",
                          orig_prefix=data[:DCX_HEAD_LEN])
    return out, w


def patch_layer_events(ev_src_dir, out_dir, changes_by_map, log=print):
    """把改动过的 EMEVD 写成方案层里的 ``event/*.emevd.dcx``。

    changes_by_map: {map 名: [(entity, 旧npc, 新npc), …]}（map 名不含 .msb.dcx）
    返回 ``{"files": [(out_path, 相对路径)…], "name": n, "bgm": n, "skipped": […] }``
    """
    maps, bgm_npc = build_map_data(ev_src_dir, log=log)
    name_ids = expand_name_ids(load_boss_name_ids())
    bgm_ids = expand_bgm_ids(bgm_npc)
    if log:
        log("[方案乙] 名字目录 %d 个 npc（含模型级兜底）｜bgm 目录 %d 个 npc"
            % (len(name_ids), len(bgm_ids)))
    os.makedirs(out_dir, exist_ok=True)
    files, rep = [], {"name": 0, "bgm": 0, "skipped": [], "partial": [],
                      "maps": 0, "degraded": []}
    for mid, changes in sorted(changes_by_map.items()):
        if not changes:
            continue
        p = os.path.join(ev_src_dir, mid + ".emevd.dcx")
        if not os.path.isfile(p):
            continue
        data = open(p, "rb").read()
        raw, _hdr = M.dcx_payload(data)
        new_raw, r = patch_evd_bytes(raw, changes, maps.get(mid) or {}, name_ids, bgm_ids)
        if new_raw == raw:
            rep["skipped"].extend([dict(s, map=mid) for s in r["skipped"]])
            rep["partial"].extend([dict(s, map=mid) for s in r["partial"]])
            continue
        out, w = repack_dcx(data, new_raw)
        if w.get("out_kind") != "KRAK" and (w.get("degraded") or []):
            rep["degraded"].append({"map": mid, "why": w["degraded"][0]})
        # 写前自读回校验：解开的明文必须就是 new_raw
        back, _ = M.dcx_payload(out)
        if back != new_raw:
            raise RuntimeError("EMEVD 重封装回读不一致：%s" % mid)
        dest = os.path.join(out_dir, mid + ".emevd.dcx")
        with open(dest, "wb") as f:
            f.write(out)
        files.append((dest, os.path.join("event", mid + ".emevd.dcx")))
        rep["name"] += r["name"]
        rep["bgm"] += r["bgm"]
        rep["skipped"].extend([dict(s, map=mid) for s in r["skipped"]])
        rep["partial"].extend([dict(s, map=mid) for s in r["partial"]])
        rep["maps"] += 1
    if log:
        log("[方案乙] 改事件脚本 %d 张｜血条名 %d 处｜BGM %d 处｜跳过 %d 个 part｜BGM 未跟随 %d 个"
            % (rep["maps"], rep["name"], rep["bgm"], len(rep["skipped"]),
               len(rep["partial"])))
        if rep["skipped"]:
            for s in rep["skipped"][:4]:
                log("[方案乙]   跳过：%s 实体%s（%s→%s）：%s"
                    % (s.get("map"), s.get("entity"), s.get("old_npc"),
                       s.get("new_npc"), s.get("why")))
        if rep["partial"]:
            s = rep["partial"][0]
            log("[方案乙]   BGM 没跟随：%d 个 part（例：%s 实体%s %s→%s：%s）"
                % (len(rep["partial"]), s.get("map"), s.get("entity"),
                   s.get("old_npc"), s.get("new_npc"), s.get("why")))
        if rep["degraded"]:
            log("[方案乙]   降级（KRAK 不可用，已用 DFLT）：%d 张" % len(rep["degraded"]))
    return {"files": files, "name": rep["name"], "bgm": rep["bgm"],
            "skipped": rep["skipped"], "partial": rep["partial"], "maps": rep["maps"],
            "degraded": rep["degraded"]}


# ────────────────────────── 自检 ──────────────────────────

def selftest():
    """离线自检（不写任何文件）：定位字面量/模板/BGM 参数槽，在内存里改一处再核对字节。"""
    t0 = time.time()
    maps, bgm_npc = build_map_data(log=print)
    name_ids = load_boss_name_ids()
    print("[1/4] 事件脚本 %d 个；血条名目录 %d 个 npc；bgm 目录 %d 个 npc"
          % (len(maps), len(name_ids), len(bgm_npc)))

    def _pick(literal):
        for mid, d in sorted(maps.items()):
            table = d["literal"] if literal else d["templated"]
            for ent, recs in table.items():
                if not ent or not recs:
                    continue
                old_name = recs[0][-1]
                new_npc = next((k for k, v in name_ids.items() if v != old_name), None)
                if new_npc:
                    return mid, ent, recs[0], new_npc
        return None

    # ① 字面量
    sample = _pick(True)
    assert sample, "找不到字面量血条样例"
    mid, ent, rec, new_npc = sample
    data = open(os.path.join(event_dir(), mid + ".emevd.dcx"), "rb").read()
    raw, _h = M.dcx_payload(data)
    new_raw, rep = patch_evd_bytes(raw, [(ent, 0, new_npc)], maps[mid], name_ids, bgm_npc)
    slot, old_name = rec
    new_name = name_ids[new_npc]
    assert new_raw != raw, "字面量样例没有产生任何改动"
    assert any(_find_all(new_raw, struct.pack("<4I", en, ent, slot, new_name))
               for en in (0, 1)), "字面量样例改完没找到新名字"
    out, w = repack_dcx(data, new_raw)
    back, _ = M.dcx_payload(out)
    assert back == new_raw, "EMEVD 重封装回读不一致"
    print("[2/4] 字面量：%s 实体 %s 名字 %s→%s｜DCX %d→%d B（%s）"
          % (mid, ent, old_name, new_name, len(data), len(out), w.get("out_kind")))

    # ② 模板调用点
    sample = _pick(False)
    assert sample, "找不到模板血条样例"
    mid, ent, rec, new_npc = sample
    eid, ni, old_name = rec
    data = open(os.path.join(event_dir(), mid + ".emevd.dcx"), "rb").read()
    raw, _h = M.dcx_payload(data)
    new_raw, rep = patch_evd_bytes(raw, [(ent, 0, new_npc)], maps[mid], name_ids, bgm_npc)
    new_name = name_ids[new_npc]
    hit = False
    for pos in _find_all(new_raw, struct.pack("<2I", eid, ent)):
        off = pos + 4 * (1 + ni)
        if off + 4 <= len(new_raw) and struct.unpack_from("<I", new_raw, off)[0] == new_name:
            hit = True
    assert hit, "模板样例改完没找到新名字（eid=%s ni=%s）" % (eid, ni)
    out, w = repack_dcx(data, new_raw)
    back, _ = M.dcx_payload(out)
    assert back == new_raw, "EMEVD 重封装回读不一致"
    print("[3/4] 模板：%s 实体 %s 事件 %s 参数位 %s 名字 %s→%s ✓"
          % (mid, ent, eid, ni, old_name, new_name))

    # ③ BGM 参数槽
    bgm_sample = None
    for mid, d in sorted(maps.items()):
        for ent, (eid, flag, bgm) in (d.get("bgm") or {}).items():
            target = next((k for k, v in bgm_npc.items() if v != bgm), None)
            if target:
                bgm_sample = (mid, ent, eid, flag, bgm, target)
                break
        if bgm_sample:
            break
    assert bgm_sample, "找不到 BGM 样例"
    mid, ent, eid, flag, bgm, target = bgm_sample
    data = open(os.path.join(event_dir(), mid + ".emevd.dcx"), "rb").read()
    raw, _h = M.dcx_payload(data)
    new_raw, _r = patch_evd_bytes(raw, [(ent, 0, target)], maps[mid], name_ids, bgm_npc)
    assert _find_all(new_raw, struct.pack("<3I", eid, flag, bgm_npc[target])), \
        "BGM 样例改完没找到新 bgm 参数"
    print("[4/4] BGM：%s 实体 %s 事件 %s 参数 %s→%s ✓"
          % (mid, ent, eid, bgm, bgm_npc[target]))
    print("SELFTEST PASS（%.1fs）" % (time.time() - t0))
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--selftest" in argv or not argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
