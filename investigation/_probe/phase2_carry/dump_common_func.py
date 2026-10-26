
# -*- coding: utf-8 -*-
import sys, os, struct
sys.path.insert(0, r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod\investigation\apply')
import evd_edit

ev, meta, data = evd_edit.load_evd(r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）\mod\event\common_func.emevd.dcx')
print('events', len(ev.events))
for eid in (90005860, 90005870):
    e = ev.event(eid)
    if not e:
        print('missing', eid); continue
    print('=== event', eid, 'ins', e['icnt'], 'args', e['arcnt'])
    raw = ev.raw
    for (j, cat, idx, size, aoff) in ev.instructions(eid):
        off = ev.arg_base + aoff
        args = raw[off:off+size]
        if size == 4:
            a = struct.unpack('<I', args)[0]
            print(j, (cat, idx), 'sz4', a)
        elif size == 8:
            print(j, (cat, idx), 'sz8', struct.unpack('<II', args))
        elif size == 12:
            print(j, (cat, idx), 'sz12', struct.unpack('<III', args))
        elif size == 16:
            print(j, (cat, idx), 'sz16', struct.unpack('<IIIf', args))
        elif size == 24:
            print(j, (cat, idx), 'sz24', struct.unpack('<IIIfIf', args))
        else:
            print(j, (cat, idx), 'sz', size, args.hex())
