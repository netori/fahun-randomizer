# -*- coding: utf-8 -*-
"""evd_add.py — 往 EMEVD 里**新增事件**（不只是删改指令）。

结构（evd_edit.py 已实测）：header 16B + 16×u64；events 48B/条；instructions 32B/条；
base args 区；然后 arg repl / event layers / linked / strings。所有 u64 偏移都是绝对偏移；
事件里的 ins_local_off 相对 instructions 起点；指令里的 args_local_off 相对 base args 起点。

做法：整表重建，事件顺序不变；事件 0 末尾追加 InitializeEvent 注册；新事件指令追加到
指令表末尾；新参数追加到 base args 区末尾，tail 整体后移。原有指令/事件记录逐字节保留，
所以不会动到 arg repl 的指令行号。
"""
import struct
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import evd_edit

EV_SIZE, INS_SIZE = evd_edit.EV_SIZE, evd_edit.INS_SIZE
INIT_CAT_IDX = (2000, 0)   # InitializeEvent(slot, event_id, ...)


class EvdAddError(Exception):
    pass


def _pack_event(eid, ins_count, ioff, arcnt, aoff, rest):
    return struct.pack("<QQqQqI", eid, ins_count, ioff, arcnt, aoff, rest) + b"\x00\x00\x00\x00"


def _pack_ins(cat, idx, size, aoff, layers=-1):
    return struct.pack("<IIQqq", cat, idx, size, aoff, layers)


def add_events(raw, specs, register=True):
    """specs: [{"event_id": int, "rest": 0|1, "instructions": [(cat, idx, bytes), ...]}]
    register=True 时把每个新事件注册进事件 0（$InitializeEvent(0, id)）。
    返回 (new_raw, info)。"""
    ev = evd_edit.Evd(raw)
    bad = [n for n, ok in ev.check_chain() if not ok]
    if bad:
        raise EvdAddError("EMEVD 不变量不成立：%s" % bad)
    if not specs:
        return raw, {"events": 0, "instructions": 0, "args": 0}
    existing_ids = {e["eid"] for e in ev.events}
    for s in specs:
        if int(s["event_id"]) in existing_ids:
            raise EvdAddError("事件 id 已存在：%s" % s["event_id"])
        existing_ids.add(int(s["event_id"]))
    # 事件 0 的注册指令（每条 12 字节参数）
    reg = []
    if register:
        for s in specs:
            args = struct.pack("<III", 0, int(s["event_id"]), 0)
            reg.append((INIT_CAT_IDX[0], INIT_CAT_IDX[1], args))
    # 先构造新事件块（按 specs 顺序）
    new_blocks = []
    for s in specs:
        recs = []
        for ins in s.get("instructions") or []:
            cat, idx, blob = ins[0], ins[1], ins[2]
            recs.append((int(cat), int(idx), bytes(blob)))
        new_blocks.append(recs)
    # 指令表与参数表
    ins_out = bytearray()
    args_out = bytearray()
    old_args_size = int(ev.hdr["base_arg_size"])
    args_out += ev.raw[ev.arg_base: ev.arg_base + old_args_size]
    ev_out = []
    cur_ins = 0
    def _emit(eid, recs, rest, arcnt, aoff):
        nonlocal cur_ins
        ioff = cur_ins * INS_SIZE
        for cat, idx, blob in recs:
            aoff_rel = len(args_out)
            args_out.extend(blob)
            ins_out.extend(_pack_ins(cat, idx, len(blob), aoff_rel, -1))
        ev_out.append(_pack_event(eid, len(recs), ioff, arcnt, aoff, rest))
        cur_ins += len(recs)
    for e in ev.events:
        eid = int(e["eid"])
        recs = []
        abs_ins = ev.ins_base + int(e["ioff"])
        for j in range(int(e["icnt"])):
            rec = abs_ins + j * INS_SIZE
            cat, idx = struct.unpack_from("<II", ev.raw, rec)
            size, aoff = struct.unpack_from("<Qq", ev.raw, rec + 8)
            layers = struct.unpack_from("<q", ev.raw, rec + 24)[0]
            blob = ev.raw[ev.arg_base + aoff: ev.arg_base + aoff + size]
            # 保留原指令的 args 绝对相对偏移（args 区未动），layers 也不动
            ins_out.extend(ev.raw[rec:rec + INS_SIZE])
        if eid == 0 and reg:
            for cat, idx, blob in reg:
                aoff_rel = len(args_out)
                args_out.extend(blob)
                ins_out.extend(_pack_ins(cat, idx, len(blob), aoff_rel, -1))
            recs_count = int(e["icnt"]) + len(reg)
        else:
            recs_count = int(e["icnt"])
        ioff = cur_ins * INS_SIZE
        ev_out.append(_pack_event(eid, recs_count, ioff, int(e["arcnt"]), int(e["aoff"]), int(e["rest"])))
        cur_ins += recs_count
    # 新事件追加
    for s, recs in zip(specs, new_blocks):
        _emit(int(s["event_id"]), recs, int(s.get("rest", 1)), int(s.get("arcnt", 0)), int(s.get("aoff", -1)))
    # 尾部（arg repl / layers / linked / strings）
    tail = ev.raw[ev.arg_base + old_args_size:]
    args_add = len(args_out) - old_args_size
    # 16 字节对齐参数区末尾（只补 padding，不改变任何已有偏移）
    pad = (-len(args_out)) % 16
    args_out.extend(b"\x00" * pad)
    header_end = 16 + 8 * len(evd_edit.FIELDS)
    events_offset = header_end
    instructions_offset = events_offset + EV_SIZE * len(ev_out)
    base_arg_offset = instructions_offset + INS_SIZE * (len(ins_out) // INS_SIZE)
    new_size = base_arg_offset + len(args_out) + len(tail)
    hdr = bytearray(16 + 8 * len(evd_edit.FIELDS))
    hdr[:16] = ev.raw[:16]
    struct.pack_into("<I", hdr, 12, new_size)
    vals = dict(ev.hdr)
    vals["events_count"] = len(ev_out)
    vals["events_offset"] = events_offset
    vals["instructions_count"] = len(ins_out) // INS_SIZE
    vals["instructions_offset"] = instructions_offset
    vals["base_arg_size"] = len(args_out)
    vals["base_arg_offset"] = base_arg_offset
    # unknown 区段在指令与参数之间；原文件通常是空的（offset == base_arg_offset）
    if int(ev.hdr["unknown_count"]) == 0:
        vals["unknown_offset"] = base_arg_offset
    else:
        vals["unknown_offset"] = int(ev.hdr["unknown_offset"]) + args_add  # 保守
    for name in ("event_layers_offset", "arg_repl_offset", "linked_offset", "strings_offset"):
        vals[name] = int(ev.hdr[name]) + args_add if int(ev.hdr[name]) else 0
    for i, name in enumerate(evd_edit.FIELDS):
        struct.pack_into("<Q", hdr, 16 + i * 8, int(vals[name]))
    out = bytes(hdr) + b"".join(ev_out) + bytes(ins_out) + bytes(args_out) + tail
    return out, {"events": len(specs), "instructions": sum(len(x) for x in new_blocks),
                 "args": len(args_out) - old_args_size, "raw": len(out)}


def selftest(raw):
    ev = evd_edit.Evd(raw)
    out, info = add_events(raw, [])
    if out != raw:
        raise EvdAddError("空改动不是逐字节原样：%d -> %d" % (len(raw), len(out)))
    return True
