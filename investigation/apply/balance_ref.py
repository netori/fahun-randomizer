# -*- coding: utf-8 -*-
"""法魂「血量口径」参考表生成器（一次性/版本升级时跑一次）。

输出 investigation/balance_ref.json：
  {
    "version": 1,
    "generated": "2026-10-23T...",
    "source": {"regulation": "<路径>", "sha256": "...", "npc_rows": 7830},
    "tier_hp":  {"7000": 2.6951, ...},        # 每个可用缩放档的 maxHpRate
    "tier_atk": {"7000": 1.6901, ...},        # physicsAttackPowerRate（只作记录）
    "npc_tier": {"<npc_row_id>": 7000, ...},  # 该行自己带的可用 spEffectID3
    "map_tier": {"m11_05_00_00": 7050, ...}   # 同地图标准档众数（0/缺行兜底）
  }

口径来源（参考 enemy_write._area_section / _area_tier_ok）：
- 行自己的 spEffectID3 在 SpEffectParam 里能当缩放档用 → 记自己的档；
- 否则写 0（无档），下游需要地图兜底时用 map_tier。

用法：
  python balance_ref.py                 # 从当前激活法魂包生成
  python balance_ref.py --reg <path>    # 指定 regulation.bin
  python balance_ref.py --out <path>
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import enemy_write as EW  # noqa: E402
import param_bin  # noqa: E402
import erio  # noqa: E402

INV = os.path.dirname(HERE)
OUT = os.path.join(INV, "balance_ref.json")
VERSION = 1


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(reg=None, places=None, out=OUT, log=print):
    if not reg:
        import plan_layer
        reg = os.path.join(plan_layer.mod_root(), "regulation.bin")
    if not os.path.isfile(reg):
        raise SystemExit("找不到 regulation.bin：%s" % reg)
    ref = build_from(erio.read_regulation(reg), places=places, log=None)
    ref["source"]["regulation"] = os.path.abspath(reg)
    ref["source"]["sha256"] = _sha256_file(reg)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ref, f, ensure_ascii=False, indent=1)
    log("[balance_ref] 已写 %s（%d 个 NPC 有档、%d 个档位、%d 张地图兜底）"
        % (out, len(ref["npc_tier"]), len(ref["tier_hp"]), len(ref["map_tier"])))
    return ref


def build_from(bnd, places=None, log=None):
    """从已读入的 regulation 生成参考表（写盘层/GUI 在内存里算，不落盘）。"""
    places = places or EW.PLACES_TABLE
    names = [n for n, _ in bnd.files]
    npc_name = EW.find_param_name(names, "NpcParam.param")
    sp_name = EW.find_param_name(names, "SpEffectParam.param")
    if not npc_name or not sp_name:
        raise SystemExit("基线里缺 NpcParam / SpEffectParam：%s" % reg)
    npc_pf = param_bin.ParamFile(bnd.get(npc_name))
    fbn = EW.FieldBook("NpcParam")
    sp_pf = param_bin.ParamFile(bnd.get(sp_name))
    sp_fb = EW.FieldBook("SpEffectParam")

    def rate(tier, field):
        try:
            p = sp_pf.payload(int(tier))
        except Exception:
            return 0.0
        return 0.0 if p is None else float(EW._f32(p, sp_fb.off(field)))

    npc_tier = {}
    tiers = set()
    for rid in sorted(npc_pf.ids):
        t = EW._npc_scale(npc_pf, fbn, rid)
        if t and EW._area_tier_ok(sp_pf, sp_fb, t):
            npc_tier[str(int(rid))] = int(t)
            tiers.add(int(t))
    map_modes = EW.load_area_map_modes(places, npc_pf, fbn)
    tiers.update(int(t) for t in map_modes.values())
    tier_hp, tier_atk = {}, {}
    for t in sorted(tiers):
        tier_hp[str(t)] = round(rate(t, "maxHpRate"), 6)
        tier_atk[str(t)] = round(rate(t, "physicsAttackPowerRate"), 6)
    ref = {
        "version": VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {"regulation": "", "sha256": "", "npc_rows": len(npc_pf.ids)},
        "tier_hp": tier_hp, "tier_atk": tier_atk,
        "npc_tier": npc_tier,
        "map_tier": {k: int(v) for k, v in sorted(map_modes.items())},
    }
    if callable(log):
        log("[balance_ref] %d 个 NPC 有档、%d 个档位、%d 张地图兜底"
            % (len(npc_tier), len(tier_hp), len(map_modes)))
    return ref


def main(argv):
    ap = argparse.ArgumentParser(description="生成法魂血量口径参考表")
    ap.add_argument("--reg", default=None)
    ap.add_argument("--places", default=None)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    build(a.reg, a.places, a.out)


if __name__ == "__main__":
    main(sys.argv[1:])
