
# -*- coding: utf-8 -*-
import sys, os, struct
sys.path.insert(0, r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod\investigation\apply')
import msb_read, evd_edit, evd_add, msb_write, phase_carry

PACK = r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）'
base_ev = os.path.join(PACK, 'mod', 'event', 'm60_42_36_00.emevd.dcx')
edata = open(base_ev, 'rb').read()
eraw, ehdr = msb_read.dcx_payload(edata)
buf = bytearray(eraw)
old = struct.pack('<I', 903251600); new = struct.pack('<I', 905130000)
done = 0; i = buf.find(old)
while i != -1:
    if struct.pack('<I', 90005870) in bytes(buf[max(0, i-48):i+48]):
        buf[i:i+4] = new; done += 1
    i = buf.find(old, i+4)
print('bar patched', done)
raw2 = bytes(buf)

recipes = phase_carry.load_recipes()
fam = recipes['messmer']
evs = phase_carry.build_events(fam, 1042360800, 1042361982, 1042369100, 1042369101, 905130001)
mode = sys.argv[1] if len(sys.argv) > 1 else 'D'
if mode == 'D':
    evs['transition'] = [phase_carry.ins(*phase_carry.I_END_EVENT, phase_carry._u32(0))]
elif mode == 'E':
    evs['death'] = [phase_carry.ins(*phase_carry.I_END_EVENT, phase_carry._u32(0))]
print('mode', mode, 'init', len(evs['init']), 'trans', len(evs['transition']), 'death', len(evs['death']))
specs = [{'event_id': 1042369000, 'rest': 1, 'instructions': evs['init']},
         {'event_id': 1042369001, 'rest': 1, 'instructions': evs['transition']},
         {'event_id': 1042369002, 'rest': 1, 'instructions': evs['death']}]
out, meta = evd_add.add_events(raw2, specs, register=True)
dcx, rep = msb_write.dcx_repack(out, in_kind=(ehdr or {}).get('kind'), out_kind='same', orig_prefix=edata[:76])
print('repack degraded', rep.get('degraded'))
p = r'F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod\investigation\_tmp_var_%s.emevd.dcx' % mode
open(p, 'wb').write(dcx)
print('written', p, len(dcx))
