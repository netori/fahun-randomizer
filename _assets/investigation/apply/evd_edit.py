# -*- coding: utf-8 -*-
"""evd_edit.py — EMEVD 结构编辑（M2.2）：把野外 Boss 大血条从 "BGM 条件" 里解放出来。

为什么需要它
------------
野外 Boss 的大血条不是 NpcParam 字段，而是 EMEVD 模板给的。`common_func` 里
`$Event(90005870/90005871, ...)` 先等：

    CharacterAIState(X0_4, Combat) && FieldBattleBGMActive(X8_4) && !EventFlag(9000)

才 `DisplayBossHealthBar(...)`。X8_4 是"这个位置原本那只"的 threatLv；
玩家换人后只要引擎播的 BGM 等级对不上，大血条就永远不出现（BGM 也会换掉）。
参考实现（thefifthmatt）在 `diste/Base/events.txt:13208` 的 `Removes:` 里
第一条就删掉 `IfFieldBattleBgmActive` —— 这里做同一件事：把这两条模板里的
BGM 判定指令删掉，保留其余条件与全部动作。

容器格式（实测，非猜）
--------------------
```
header(16B + 16×u64)   : EVD\0, version@8, file_size@12,
                         events_count/off, instructions_count/off, unknown_count/off,
                         event_layers_count/off, arg_repl_count/off,
                         linked_count/off, base_arg_size/off, strings_size/off
events   @events_off   : 每条 48B  {event_id u64, ins_count u64, ins_local_off i64,
                                    argrepl_count u64, argrepl_local_off i64,
                                    on_rest u32, pad 4}
insns    @ins_off      : 每条 32B  {category u32, index u32, args_size u64,
                                    args_local_off i64, layers_local_off i64}
args     @base_arg_off : 全部事件共享的参数区（指令记录的 args_local_off 相对它）
tail                   : arg_repl / linked / strings 原样保留
```
不变量（本模块 selftest 逐条验）：events 末尾 == ins 起点；ins 末尾 == args 起点；
各事件指令块首尾相接、顺序与事件表一致；删 N 条指令 → 整表左移 32N 字节，
事件内局部偏移与 header 里后续区段的绝对偏移同步减 32N。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import enemy_randomizer as ER          # noqa: E402  （只用来定位 mod 根）
import msb_read                        # noqa: E402
import msb_write                       # noqa: E402

FIELDS = ["events_count", "events_offset", "instructions_count", "instructions_offset",
          "unknown_count", "unknown_offset", "event_layers_count", "event_layers_offset",
          "arg_repl_count", "arg_repl_offset", "linked_count", "linked_offset",
          "base_arg_size", "base_arg_offset", "strings_size", "strings_offset"]

EV_SIZE, INS_SIZE = 48, 32
IF_FIELD_BATTLE_BGM = (3, 33)          # EMEDF: Condition - Event[33] IF Field Battle BGM Active
# 野外 Boss 血条模板：870 单体 / 871 双体（872 只做 BGM 升温、873 是独立音乐模板，都不动）
DEFAULT_TEMPLATES = (90005870, 90005871)


class Evd(object):
    """一份 EMEVD 明文的解析 / 重建。只做结构层，不解释参数语义。"""

    def __init__(self, raw):
        if raw[:4] != b"EVD\x00":
            raise ValueError("不是 EMEVD：magic=%r" % raw[:4])
        self.raw = raw
        self.hdr = {}
        for i, name in enumerate(FIELDS):
            self.hdr[name] = struct.unpack_from("<Q", raw, 16 + i * 8)[0]
        self.events = []
        ev_off = self.hdr["events_offset"]
        for k in range(self.hdr["events_count"]):
            o = ev_off + k * EV_SIZE
            eid, icnt, ioff, arcnt, aoff, rest = struct.unpack_from("<QQqQqI", raw, o)
            self.events.append(dict(idx=k, eid=eid, icnt=icnt, ioff=ioff, arcnt=arcnt,
                                    aoff=aoff, rest=rest, pad=raw[o + 44:o + 48]))
        self.ins_base = self.hdr["instructions_offset"]
        self.arg_base = self.hdr["base_arg_offset"]
        self.blocks = sorted((self.ins_base + e["ioff"], e) for e in self.events if e["icnt"] > 0)
        self.total_ins = sum(e["icnt"] for e in self.events)

    # ── 读 ────────────────────────────────────────────────────────────
    def event(self, eid):
        for e in self.events:
            if e["eid"] == eid:
                return e
        return None

    def instructions(self, eid):
        """[(index, category, index_in_class, args_size, args_offset)]"""
        e = self.event(eid)
        if not e:
            return []
        out = []
        base = self.ins_base + e["ioff"]
        for j in range(e["icnt"]):
            cat, idx = struct.unpack_from("<II", self.raw, base + j * INS_SIZE)
            size, aoff = struct.unpack_from("<Qq", self.raw, base + j * INS_SIZE + 8)
            out.append((j, cat, idx, size, aoff))
        return out

    def find(self, eid, cat_idx):
        return [j for (j, cat, idx, _s, _a) in self.instructions(eid) if (cat, idx) == cat_idx]

    def check_chain(self):
        """返回 [(不变量名, 是否成立)]；全 True 才允许写盘。"""
        h = self.hdr
        got = [("events_end == instructions_offset",
                h["events_offset"] + EV_SIZE * h["events_count"] == h["instructions_offset"]),
               ("instructions_end == base_arg_offset",
                h["instructions_offset"] + INS_SIZE * h["instructions_count"] == h["base_arg_offset"]),
               ("sum(ins_count) == instructions_count",
                self.total_ins == h["instructions_count"]),
               ("first_block_at_instructions_offset",
                (not self.blocks) or self.blocks[0][0] == h["instructions_offset"])]
        prev, contig = None, True
        for abs_off, e in self.blocks:
            if prev is not None and abs_off != prev:
                contig = False
            prev = abs_off + INS_SIZE * e["icnt"]
        got.append(("instruction_blocks_contiguous", contig))
        got.append(("file_size_field == len(raw)", struct.unpack_from("<I", self.raw, 12)[0] == len(self.raw)))
        return got

    # ── 写 ────────────────────────────────────────────────────────────
    def assemble(self, drop=None):
        """drop: {event_id: {指令下标}}；返回新明文（不删任何东西时应逐字节等于 raw）。"""
        drop = drop or {}
        h = self.hdr
        ins = bytearray()
        new_off = {}
        removed = 0
        for abs_off, e in self.blocks:
            new_off[e["eid"]] = len(ins)
            gone = drop.get(e["eid"], ())
            for j in range(e["icnt"]):
                if j in gone:
                    removed += 1
                    continue
                ins += self.raw[abs_off + j * INS_SIZE: abs_off + (j + 1) * INS_SIZE]
        delta = removed * INS_SIZE
        ev = bytearray()
        for e in self.events:
            icnt = e["icnt"] - len(drop.get(e["eid"], ()))
            ev += struct.pack("<QQqQqI", e["eid"], icnt, new_off.get(e["eid"], 0),
                              e["arcnt"], e["aoff"], e["rest"]) + e["pad"]
        prefix = bytearray(self.raw[:16])
        struct.pack_into("<I", prefix, 12, len(self.raw) - delta)
        hdr = bytearray(16 + 8 * len(FIELDS))
        hdr[:16] = prefix
        h2 = dict(h)
        h2["instructions_count"] = h["instructions_count"] - removed
        for name in ("base_arg_offset", "unknown_offset", "event_layers_offset",
                     "arg_repl_offset", "linked_offset", "strings_offset"):
            h2[name] = h[name] - delta
        for i, name in enumerate(FIELDS):
            struct.pack_into("<Q", hdr, 16 + i * 8, h2[name])
        return bytes(hdr) + bytes(ev) + bytes(ins) + self.raw[self.arg_base:]

    def strip(self, cat_idx=IF_FIELD_BATTLE_BGM, events=DEFAULT_TEMPLATES):
        """删掉指定事件里所有 cat_idx 指令；返回 (新明文, {事件: 删了几条})。"""
        drop, info = {}, {}
        for eid in events:
            hits = self.find(eid, cat_idx)
            if hits:
                drop[eid] = set(hits)
                info[eid] = len(hits)
        if not drop:
            return self.raw, info
        return self.assemble(drop), info

    def neutralize(self, cat_idx=IF_FIELD_BATTLE_BGM, events=DEFAULT_TEMPLATES, group=15):
        """把 BGM 判定的"结果条件组"改成本事件不用的组：条件还在、结构不动、不再影响主组。

        为什么不用"删指令"：arg 替换表按**指令下标**索引（每条 32B 记录，首 u32 是指令号）。
        删掉一条指令会让该事件后续所有 arg 替换指错对象，X0_4/X4_4/X8_4 就不会被换进
        真正的 DisplayBossHealthBar —— 实机表现就是"大血条还是不出现"，而且结构校验
        全过、日志 0 ERROR，很难看出来。改条件组只动参数、不动结构，绕开这个坑。
        """
        h = self.hdr
        base_size = h["base_arg_size"]
        appended = bytearray()
        edits = []
        info = {}
        for e in self.events:
            if e["eid"] not in events:
                continue
            abs_ins = self.ins_base + e["ioff"]
            for j in range(e["icnt"]):
                rec = abs_ins + j * INS_SIZE
                cat, idx = struct.unpack_from("<II", self.raw, rec)
                if (cat, idx) != cat_idx:
                    continue
                size, aoff = struct.unpack_from("<Qq", self.raw, rec + 8)
                if size < 4:
                    raise ValueError("BGM 判定参数区太小：%d" % size)
                blob = bytearray(self.raw[self.arg_base + aoff: self.arg_base + aoff + size])
                struct.pack_into("<I", blob, 0, group)
                new_off = base_size + len(appended)
                appended += bytes(blob)
                edits.append((rec, size, new_off))
                info[e["eid"]] = info.get(e["eid"], 0) + 1
        if not edits:
            return self.raw, info
        add = len(appended)
        ins = bytearray(self.raw[self.ins_base: self.arg_base])
        for rec, size, new_off in edits:
            k = rec - self.ins_base
            struct.pack_into("<Qq", ins, k + 8, size, new_off)
        args = self.raw[self.arg_base: self.arg_base + base_size] + bytes(appended)
        tail = self.raw[self.arg_base + base_size:]
        prefix = bytearray(self.raw[:16])
        struct.pack_into("<I", prefix, 12, len(self.raw) + add)
        h2 = dict(h)
        h2["base_arg_size"] = base_size + add
        for name in ("arg_repl_offset", "linked_offset", "strings_offset"):
            h2[name] = h[name] + add
        hdr = bytearray(16 + 8 * len(FIELDS))
        hdr[:16] = prefix
        for i, name in enumerate(FIELDS):
            struct.pack_into("<Q", hdr, 16 + i * 8, h2[name])
        head_end = 16 + 8 * len(FIELDS)
        return (bytes(hdr) + self.raw[head_end: self.ins_base] + bytes(ins) + args + tail), info


# ── 对外：路径级操作 ──────────────────────────────────────────────────
def evd_dir(mod=None):
    mod = mod or os.path.dirname(ER._mod_reg())
    return os.path.join(mod, "event")


def load_evd(path):
    """读 .emevd 或 .emevd.dcx → (Evd, dcx_meta)。"""
    data = open(path, "rb").read()
    if data[:4] == b"DCX\x00":
        raw, meta = msb_read.dcx_payload(data)
    else:
        raw, meta = data, None
    return Evd(raw), meta, data


def patch_file(src, out, templates=DEFAULT_TEMPLATES, log=print):
    """把 src 里的模板 BGM 判定删掉，写到 out（保持原 DCX 压缩类型）。"""
    ev, meta, data = load_evd(src)
    bad = [n for n, ok in ev.check_chain() if not ok]
    if bad:
        raise ValueError("EMEVD 不变量不成立，拒绝改写：%s" % bad)
    new_raw, info = ev.neutralize(events=templates)
    if not info:
        log("[evd] %s：模板里没有 BGM 判定，原样复制" % os.path.basename(src))
        out_bytes = data
    else:
        dcx, rep = msb_write.dcx_repack(new_raw, in_kind=(meta or {}).get("kind"),
                                        out_kind="same",
                                        orig_prefix=data[:76] if meta else None)
        if rep.get("degraded"):
            raise ValueError("DCX 重打包降级，拒绝写：%s" % rep["degraded"])
        out_bytes = dcx
        log("[evd] %s：BGM 判定改条件组 %d（%s 共 %d 条），明文 %d → %d 字节，DCX %.1f KB"
            % (os.path.basename(src), 15, info, sum(info.values()), len(ev.raw), len(new_raw),
               len(dcx) / 1024.0))
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out, "wb") as f:
        f.write(out_bytes)
    return {"path": out, "neutralized": info, "raw_before": len(ev.raw),
            "raw_after": len(new_raw), "bytes": len(out_bytes)}


def verify_patch(src, out, templates=DEFAULT_TEMPLATES, group=15):
    """独立复验：读回写出的文件，逐事件逐条比对指令与参数。返回 (ok, 说明列表)。"""
    base, _m1, _d1 = load_evd(src)
    cur, _m2, _d2 = load_evd(out)
    msgs, ok = [], True
    chain_bad = [n for n, good in cur.check_chain() if not good]
    if chain_bad:
        ok = False
        msgs.append("不变量不成立：%s" % chain_bad)
    if len(cur.events) != len(base.events):
        ok = False
        msgs.append("事件数 %d ≠ %d" % (len(cur.events), len(base.events)))
    neutralized = 0
    for e in base.events:
        b = base.instructions(e["eid"])
        c = cur.instructions(e["eid"])
        if len(b) != len(c):
            ok = False
            msgs.append("事件 %d 指令数变了：%d → %d" % (e["eid"], len(b), len(c)))
            continue
        for x, y in zip(b, c):
            if (x[1], x[2], x[3]) != (y[1], y[2], y[3]):
                ok = False
                msgs.append("事件 %d 第 %d 条指令被动了" % (e["eid"], x[0]))
                break
            ab = base.raw[base.arg_base + x[4]: base.arg_base + x[4] + x[3]]
            ac = cur.raw[cur.arg_base + y[4]: cur.arg_base + y[4] + y[3]]
            if e["eid"] in templates and (x[1], x[2]) == IF_FIELD_BATTLE_BGM:
                neutralized += 1
                if len(ac) < 4 or struct.unpack_from("<I", ac, 0)[0] != group:
                    ok = False
                    msgs.append("事件 %d 第 %d 条 BGM 判定没改到组 %d" % (e["eid"], x[0], group))
                elif ab[4:] != ac[4:]:
                    ok = False
                    msgs.append("事件 %d 第 %d 条 BGM 判定的其它参数被动了" % (e["eid"], x[0]))
            elif ab != ac:
                ok = False
                msgs.append("事件 %d 第 %d 条指令的参数被动了" % (e["eid"], x[0]))
                break
    msgs.append("BGM 判定改条件组 %d（%d 条，模板 %s）；其余 %d 个事件逐条一致"
                % (group, neutralized, list(templates),
                   len(base.events) - len(set(templates))))
    return ok, msgs


def selftest(log=print):
    """四条：不变量 / 原样重建逐字节一致 / 删判定后其它指令零漂移 / DCX 往返。"""
    mod = os.path.dirname(ER._mod_reg())
    common = os.path.join(evd_dir(mod), "common_func.emevd.dcx")
    if not os.path.isfile(common):
        raise SystemExit("找不到 %s" % common)
    ok = []
    # ① common_func + 3 张图的 event：解析→原样重建必须逐字节一致
    maps = []
    ed = evd_dir(mod)
    for name in ("m10_00_00_00.emevd.dcx", "m60_41_51_00.emevd.dcx", "m61_44_45_00.emevd.dcx"):
        cand = os.path.join(ed, name)
        if os.path.isfile(cand):
            maps.append(cand)
    for p in [common] + maps:
        ev, _m, _d = load_evd(p)
        bad = [n for n, good in ev.check_chain() if not good]
        if bad:
            raise SystemExit("自检①：%s 不变量不成立 %s" % (os.path.basename(p), bad))
        if ev.assemble() != ev.raw:
            raise SystemExit("自检①：%s 原样重建不是逐字节一致" % os.path.basename(p))
    ok.append("原样重建逐字节一致（%d 份）" % (len(maps) + 1))
    # ② 中和 BGM 判定：只改条件组，指令条数/结构不变
    ev, _m, _d = load_evd(common)
    new_raw, info = ev.neutralize()
    if sum(info.values()) == 0:
        raise SystemExit("自检②：模板里没找到 BGM 判定")
    ev2 = Evd(new_raw)
    if ev2.check_chain() != ev.check_chain():
        raise SystemExit("自检②：中和后不变量变了")
    if len(new_raw) != len(ev.raw) + 12 * sum(info.values()):
        raise SystemExit("自检②：追加的参数区长度不对")
    for eid in info:
        hits = ev2.find(eid, IF_FIELD_BATTLE_BGM)
        if len(hits) != info[eid]:
            raise SystemExit("自检②：事件 %d BGM 判定数 %d ≠ %d" % (eid, len(hits), info[eid]))
        base_ins = ev2.ins_base + ev2.event(eid)["ioff"]
        for j in hits:
            size, aoff = struct.unpack_from("<Qq", ev2.raw, base_ins + j * INS_SIZE + 8)
            g = struct.unpack_from("<I", ev2.raw, ev2.arg_base + aoff)[0]
            if g != 15:
                raise SystemExit("自检②：事件 %d 第 %d 条 BGM 判定组 %d ≠ 15" % (eid, j, g))
    ok.append("中和 BGM 判定（改条件组 15）：%s" % info)
    # ③ 其它指令与参数零漂移（BGM 只允许组号那 4 字节变）
    moved = 0
    for e in ev.events:
        a = ev.instructions(e["eid"])
        b = ev2.instructions(e["eid"])
        if len(a) != len(b):
            raise SystemExit("自检③：事件 %d 指令数不对" % e["eid"])
        for x, y in zip(a, b):
            if (x[1], x[2], x[3]) != (y[1], y[2], y[3]):
                moved += 1
                continue
            ab = ev.raw[ev.arg_base + x[4]: ev.arg_base + x[4] + x[3]]
            ac = ev2.raw[ev2.arg_base + y[4]: ev2.arg_base + y[4] + y[3]]
            if e["eid"] in info and (x[1], x[2]) == IF_FIELD_BATTLE_BGM:
                if ab[4:] != ac[4:]:
                    moved += 1
            elif ab != ac:
                moved += 1
    if moved:
        raise SystemExit("自检③：%d 条指令/参数被动了" % moved)
    ok.append("其余指令与参数零漂移")
    # ④ DCX 往返
    data = open(common, "rb").read()
    _ev, meta, _d = load_evd(common)
    dcx, rep = msb_write.dcx_repack(new_raw, in_kind=(meta or {}).get("kind"),
                                    out_kind="same", orig_prefix=data[:76])
    back, _h = msb_read.dcx_payload(dcx)
    if back != new_raw or rep.get("degraded"):
        raise SystemExit("自检④：DCX 往返不一致 %s" % rep)
    ok.append("DCX 往返一致（%d → %d 字节）" % (len(new_raw), len(dcx)))
    log("[evd 自检] PASS：" + " / ".join(ok))
    return True


if __name__ == "__main__":
    selftest()
