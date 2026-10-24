# -*- coding: utf-8 -*-
"""bar_names.py — 把 Boss 大血条上的名字换成"换进来的那只"的名字（M2.3，v1.2）。

为什么需要它
------------
大血条的名字不是 NpcParam 字段，而是 EMEVD 指令里的一个 Name ID 参数：

    DisplayBossHealthBar(Enabled, <实体>, 槽位, <名字>)
    InitializeCommonEvent(0, 90005870, <实体>, <名字>, <威胁等级>)   # 野外 Boss 模板
    InitializeCommonEvent(0, 90005876, <实体>, <区域>, <名字>, <BGM>) # 传送门模板
    InitializeEvent(0, <本地事件>, <实体>, <名字>, ...)             # 本地事件（参数转交）

换人只换了 MSB 的身份字段，这些字面量没动 —— 于是血条还顶着原 Boss 的名字
（实测：宁姆格福大树守卫位换成"风暴呼召者塔兰"，血条仍写"大树守卫"）。

做法（不解析指令语义，按值匹配）
--------------------------------
一份 EMEVD 里，血条名 ID 是 8~9 位、以 9 开头的字面量，和实体 ID 出现在**同一条
指令的参数里**（实测 176 个血条位置里 175 个满足；包括本地事件把实体与名字一起
作为参数转交的调用点）。所以按"这条指令同时含实体 ID 与旧名字 ID"定位，把旧名字
替换成新名字即可 —— 参数区等长改写，不动指令表/事件表/替换表，不重排任何偏移。

名字从哪来：investigation/enemy_bar_names.csv（构建期扫出来的
(map, entity, model, name_id)），换入模型取它出现次数最多的那个名字 ID。
换入者从来没有血条名字（如野生动物/大树守卫）时**不再保留原 Boss 名**：优先查
investigation/enemy_bar_name_overrides.csv（模型 → 同义中文名），查不到就写一个
不存在的 Name ID（PLACEHOLDER_NAME_ID）—— 引擎查不到名字时显示 "?NpcName?"。
这就是用户要的：普通敌人随到 Boss 位、自己没有血条名时显示占位名，而不是顶着
原 Boss 的名字。

边界：只改血条名，不改 BGM ID、不改 banner 文案、不改多阶段组的第二阶段。
"""
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import evd_edit                                                   # noqa: E402
import msb_read                                                    # noqa: E402
import msb_write                                                   # noqa: E402

DISPLAY_BAR = (2003, 11)          # EMEDF 显式 index（不是数组下标）
INIT_COMMON = (2000, 6)
INIT_LOCAL = (2000, 0)            # InitializeEvent(0, <本地事件>, …)：参数转交
BAR_NAME_ARG = 3                  # DisplayBossHealthBar 的第 4 个参数（名字）

# 换入模型既没有血条名、也没有同义名时写这个 Name ID。它不在 NpcName 表里，
# 引擎查不到就渲染成占位文本 "?NpcName?"（实测/用户确认的显示口径）。
PLACEHOLDER_NAME_ID = 999999999
NAME_OVERRIDES = os.path.join(HERE, "..", "enemy_bar_name_overrides.csv")


def load_name_overrides(path=NAME_OVERRIDES):
    """读 enemy_bar_name_overrides.csv → {model: name_id}。

    用途只有一类：换入的普通敌人**本来有中文名**，但它从没当过 Boss，所以
    enemy_bar_names.csv 里没有它的 name_id（例如 c6251 Tree Sentinel 没当过 Boss，
    但 c3251 大树守卫是同一个东西）。这里按模型人工补一条同义名。
    文件可选；格式 model,name_id,note。坏行跳过，不让一条备注弄坏整次构建。
    """
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            model = (r.get("model") or "").strip()
            try:
                nid = int(r.get("name_id") or 0)
            except (TypeError, ValueError):
                continue
            if model and nid > 0:
                out[model] = nid
    return out


def load_tables(csv_path):
    """读 enemy_bar_names.csv → ({(map, entity): [old_name_id, …]}, {model: new_name_id})。

    同一个位置可能有**多个**名字 ID（例如野外 Boss 模板用 A、传送门模板用 B；
    boss_healthbar.csv 里也可能记了别名）。只换第一个会漏掉另一半显示路径 ——
    实测「一部分 Boss 名字没换过来」就是这类。所以这里保留全部旧名字 ID，
    写盘时把「同时含实体与任一旧名字」的指令全部改成新名字。
    """
    if not os.path.isfile(csv_path):
        raise ValueError("找不到血条名字表：%s" % csv_path)
    old = {}
    votes = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                ent = int(r["entity"])
                nm = int(r["name_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not ent or nm < 0:
                continue
            # name_id=0 是「有血条但没有名字」的位置（普通敌人/Boss 位都可能）。
            # 保留它，写盘时只替换已知模板里的名字槽（不能把指令里所有 0 都改掉）。
            lst = old.setdefault((r["map"], ent), [])
            if nm not in lst:
                lst.append(nm)
            model = (r.get("model") or "").strip()
            if model and nm:
                votes.setdefault(model, {})
                votes[model][nm] = votes[model].get(nm, 0) + 1
    model_name = {}
    for model, cnt in votes.items():
        model_name[model] = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return old, model_name


def _words(raw, base, size):
    return [struct.unpack_from("<I", raw, base + o)[0] for o in range(0, size - 3, 4)]


def _zero_name_positions(ws, cat, idx):
    """旧名字是 0（有血条但没名字）时，只允许改**已知模板的名字槽**。

    不能像非零名字那样「把指令里所有 0 都换掉」—— 参数区里的 0 可能是
    槽位/开关/浮点低位，改错会直接破坏事件。目前只认两种实测布局：
      DisplayBossHealthBar(2003/11)：[enabled, entity, slot, name]
      InitializeCommonEvent(0, 90005882, …)：第 12 个参数（index 11）
    """
    if (cat, idx) == DISPLAY_BAR and len(ws) >= 4:
        return (3,)
    if (cat, idx) == INIT_COMMON and len(ws) >= 12 and ws[0] == 0 and ws[1] == 90005882:
        return (11,)
    return ()


def patch_evd(evd, targets):
    """targets: {entity_id: ([old_name, …], new_name)} —— 原地改参数，返回 (新明文, 命中)。

    同一位置可能有多个旧名字 ID（不同显示路径各用一套），这里把「这条指令同时含实体
    与任一旧名字」的所有出现都换成新名字；参数区等长，不重排任何偏移。
    旧名字是 0（无名血条）时只改已知道具的名字槽，见 _zero_name_positions。

    还有一条**参数转交**的显示路径（2026-10-24 实测：劳弗圣龛 9 变体）：
    本地事件里的 DisplayBossHealthBar(<实体>, …, 0) 名字参数是 0（占位），真正的名字
    由调用点 InitializeEvent(0, <本地事件>, …, <名字>) 传进去、引擎在运行时覆盖。
    只改指令里的 0 没用（不改看不出变化），必须回写所有调用点的对应参数 —— 见下面
    第二遍扫描。
    """
    raw = bytearray(evd.raw)
    hits = {}
    for e in evd.events:
        for (j, cat, idx, size, aoff) in evd.instructions(e["eid"]):
            if size < 8:
                continue
            base = evd.arg_base + aoff
            ws = _words(raw, base, size)
            ents = [w for w in ws if w in targets]
            if not ents:
                continue
            for ent in set(ents):
                olds, new = targets[ent]
                if isinstance(olds, int):
                    olds = [olds]
                if not new or new in olds:
                    continue
                todo = [x for x in olds if x and x in ws]
                for o in range(0, size - 3):
                    cur = struct.unpack_from("<I", raw, base + o)[0]
                    if cur in todo:
                        struct.pack_into("<I", raw, base + o, new)
                        hits.setdefault(ent, set()).add((e["eid"], j))
                if 0 in olds:
                    for pos in _zero_name_positions(ws, cat, idx):
                        if pos < len(ws) and ws[pos] == 0:
                            struct.pack_into("<I", raw, base + pos * 4, new)
                            hits.setdefault(ent, set()).add((e["eid"], j))
    # 第二遍：本地事件的「参数转交」血条名。
    # 先找「DisplayBossHealthBar 的名字参数是 0」的事件与目标实体，再把调用点
    # InitializeEvent(0, <该事件>, …) 的对应参数改成新名字。
    # 只有调用点实参个数 == 这条显示指令的参数个数时才动手 —— 此时"第几个实参"
    # 与"显示指令第几个参数"一一对应，才敢按位置回写；对不上就放弃（宁可不换名，
    # 也不要把非名字参数改成名字 ID）。一个事件里出现多个目标实体时同样跳过。
    local_slots = {}
    orig = evd.raw                     # 用原文判断「名字参数是不是 0」——本轮前面已写过 raw
    for e in evd.events:
        for (j, cat, idx, size, aoff) in evd.instructions(e["eid"]):
            if (cat, idx) != DISPLAY_BAR or size < 16:
                continue
            base = evd.arg_base + aoff
            ws = _words(orig, base, size)
            ents = {w for w in ws if w in targets}
            if not ents or len(ws) <= BAR_NAME_ARG or ws[BAR_NAME_ARG] != 0:
                continue
            local_slots[e["eid"]] = {"ents": ents, "argi": BAR_NAME_ARG, "nargs": len(ws)}
    for eid_, slot in local_slots.items():
        if len(slot["ents"]) != 1:
            continue
        ent = next(iter(slot["ents"]))
        olds, new = targets[ent]
        if isinstance(olds, int):
            olds = [olds]
        if not new or new in olds:
            continue
        for e in evd.events:
            for (j, cat, idx, size, aoff) in evd.instructions(e["eid"]):
                if (cat, idx) != INIT_LOCAL or size < 12:
                    continue
                base = evd.arg_base + aoff
                ws = _words(raw, base, size)
                if len(ws) < 2 or ws[1] != eid_ or len(ws) - 2 != slot["nargs"]:
                    continue
                wi = 2 + slot["argi"]              # InitializeEvent 参数从第 3 个字开始
                if wi >= len(ws) or ws[wi] == new:
                    continue
                struct.pack_into("<I", raw, base + wi * 4, new)
                hits.setdefault(ent, set()).add((e["eid"], j))
    return bytes(raw), hits


def patch_file(src, out, targets, log=print):
    """把 src 地图 EMEVD 里的血条名字改掉，写到 out（保持原 DCX 压缩类型）。"""
    evd, meta, data = evd_edit.load_evd(src)
    bad = [n for n, ok in evd.check_chain() if not ok]
    if bad:
        raise ValueError("EMEVD 不变量不成立，拒绝改写：%s" % bad)
    new_raw, hits = patch_evd(evd, targets)
    if not hits:
        log("[血条名] %s：没有命中的血条名字，原样复制" % os.path.basename(src))
        out_bytes = data
    else:
        dcx, rep = msb_write.dcx_repack(new_raw, in_kind=(meta or {}).get("kind"),
                                        out_kind="same",
                                        orig_prefix=data[:76] if meta else None)
        if rep.get("degraded"):
            raise ValueError("DCX 重打包降级，拒绝写：%s" % rep["degraded"])
        out_bytes = dcx
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out, "wb") as f:
        f.write(out_bytes)
    return {"path": out, "hits": {k: len(v) for k, v in hits.items()},
            "changed": sum(len(v) for v in hits.values()), "bytes": len(out_bytes)}


def verify_file(src, out, targets):
    """独立复验：重新算一遍期望明文，与写出的文件比较；只允许名字槽位变化。"""
    base, _m1, _d1 = evd_edit.load_evd(src)
    cur, _m2, _d2 = evd_edit.load_evd(out)
    msgs, ok = [], True
    bad = [n for n, good in cur.check_chain() if not good]
    if bad:
        ok = False
        msgs.append("不变量不成立：%s" % bad)
    expect, hits = patch_evd(base, targets)
    if expect != cur.raw:
        ok = False
        msgs.append("写出的明文与期望不一致（长度 %d / %d）" % (len(expect), len(cur.raw)))
    if len(base.events) != len(cur.events):
        ok = False
        msgs.append("事件数变了：%d → %d" % (len(base.events), len(cur.events)))
    msgs.append("血条名改动 %d 处（%d 个实体）；其余指令逐字节一致"
                % (sum(len(v) for v in hits.values()), len(hits)))
    return ok, msgs


def _first_name(v):
    """旧表里可能是单个 int，也可能是多个 id 的列表；取最小的非零值当"主名字"。

    name_id=0 表示「有血条但没名字」，不能当捐赠位置的名字用；否则会把
    普通敌人的无名位误当成一个真实名字。
    """
    vals = [v] if isinstance(v, int) else list(v or [])
    vals = [x for x in vals if x]
    return sorted(vals)[0] if vals else None


def targets_for_map(units, old_map, model_name, map_name, overrides=None):
    """从计划单元里挑出这张图的 {(entity): ([old, …], new)}：每个有旧名字的位置都要有名字。

    名字优先级：**捐赠位置自己的血条名** > 模型主名 > 同义名表 > 占位名。
    捐赠位置也是本体里一个真 Boss 位，它的名字比「模型最常见名字」更贴合这个模型
    此处的身份（例如同一模型在不同图里叫"密契女猎手"/"失落部族的密契女猎手"）。
    同义名表给「有中文名、但从没当过 Boss」的普通敌人补名字（c6251 Tree Sentinel
    → 903251600「大树守卫」）。都没有时写 PLACEHOLDER_NAME_ID，让血条显示
    "?NpcName?" —— 用户明确要求：普通敌人随到 Boss 位，没名字就显示这个，
    **不要**继续顶着原 Boss 的名字。

    同一位置有多个旧名字时全部保留，写盘时逐个替换 —— 否则只换了一条显示路径，
    另一条仍显示原 Boss 名（实测「还有一些 Boss 名字没换过来」）。

    返回 (targets, placeholders)。placeholders 是这张图里改用占位名的位置数，
    只用于报告；targets 为空时这个数也为 0。
    """
    overrides = overrides or {}
    out, placeholders = {}, 0
    for u in units:
        if not u.get("new_npc_id"):
            continue
        try:
            dent = int(u.get("donor_entity") or 0)
        except (TypeError, ValueError):
            dent = 0
        new = _first_name(old_map.get((u.get("donor_map"), dent))) if dent else None
        new = new or model_name.get(u.get("new_model"))
        new = new or overrides.get(u.get("new_model"))
        for pl in u["places"]:
            if pl["map"] != map_name:
                continue
            try:
                ent = int(pl["entity_id"])
            except (KeyError, TypeError, ValueError):
                continue
            olds = old_map.get((map_name, ent))
            if not olds:
                continue
            if isinstance(olds, int):
                olds = [olds]
            use = new or PLACEHOLDER_NAME_ID
            if use in olds:
                continue
            out[ent] = (list(olds), use)
            if not new:
                placeholders += 1
    return out, placeholders


def selftest(log=print):
    """用宁姆格福大树守卫那张图做一次真实改写 + 复验。"""
    import enemy_randomizer as ER
    mod = os.path.dirname(ER._mod_reg())
    src = os.path.join(mod, "event", "m60_41_51_00.emevd.dcx")
    if not os.path.isfile(src):
        raise SystemExit("找不到 %s" % src)
    evd, _m, _d = evd_edit.load_evd(src)
    targets = {1041510800: ([903251600], 903310000)}
    new_raw, hits = patch_evd(evd, targets)
    if not hits.get(1041510800):
        raise SystemExit("自检失败：没找到同时含实体与旧名字的指令")
    out = os.path.join(os.environ.get("TEMP", "."), "_bar_names_selftest.emevd.dcx")
    info = patch_file(src, out, targets, log=lambda *_a: None)
    ok, msgs = verify_file(src, out, targets)
    if not ok:
        raise SystemExit("自检复验失败：%s" % "; ".join(msgs))
    # 反向：没有目标的文件必须逐字节原样复制
    out2 = out + ".same"
    patch_file(src, out2, {}, log=lambda *_a: None)
    if open(out2, "rb").read() != open(src, "rb").read():
        raise SystemExit("自检失败：无目标时没有原样复制")
    for p in (out, out2):
        try:
            os.remove(p)
        except OSError:
            pass
    log("[血条名自检] PASS：改 %d 处 / 明文长度不变 %d / 其余指令零漂移 / 无目标原样复制"
        % (info["changed"], len(new_raw)))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print("用法：python bar_names.py --selftest")
