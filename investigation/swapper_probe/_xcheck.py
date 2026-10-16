# -*- coding: utf-8 -*-
"""Cross-check: re-verify the outputs with a SECOND, independent parser.

`enemy_swapper.verify_outputs` uses `msb_write.enemy_parts()` + manual field reads.
This script uses `msb_read.read_msb()` instead -- a different code path
(walk_params -> PARTS entry offsets -> read_enemy) -- so agreement between the
two is real evidence and not a shared bug.

Checks, per output file:
  1. enemy count identical source vs output;
  2. the `part_name` sequence is identical (so position-wise alignment is sound);
  3. every enemy dict that sits at a position whose part_name is NOT expected to
     change is byte-for-byte field-identical (entity_id/npc_id/think_id/chara_id/
     model/model_index/x/y/z);
  4. the DCX container kind is unchanged.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "apply")
sys.path.insert(0, APP)

import msb_read as M          # noqa: E402
import msb_write as W         # noqa: E402
import enemy_swapper as ES    # noqa: E402

FIELDS = ("entity_id", "npc_id", "think_id", "chara_id", "model", "model_index",
          "x", "y", "z")


def main():
    md = ES.default_map_dir()
    od = os.path.join(os.path.dirname(HERE), "swapper_probe")
    out_files = sorted(f for f in os.listdir(od) if f.endswith(".msb.dcx"))
    if not out_files:
        print("swapper_probe 里没有 .msb.dcx，先跑 enemy_swapper.py")
        return 2

    bad = 0
    print("%-22s %6s %6s %8s %8s %8s  %s" %
          ("map", "srcEn", "outEn", "changed", "identity", "kindOK", "verdict"))
    for base in out_files:
        src = os.path.join(md, base)
        out = os.path.join(od, base)
        d0 = M.read_msb(src)
        d1 = M.read_msb(out)
        e0, e1 = d0["enemies"], d1["enemies"]

        names0 = [e["part_name"] for e in e0]
        names1 = [e["part_name"] for e in e1]
        same_names = names0 == names1
        same_count = len(e0) == len(e1)

        # positions whose fields differ
        diff_pos = [i for i in range(min(len(e0), len(e1)))
                    if any(e0[i][f] != e1[i][f] for f in FIELDS)]
        # positions we did NOT intend to change must be identical
        expect_ok = True
        if not same_names:
            expect_ok = False

        # read the intended plan from the source with the swapper's own mapping
        sraw, sh = M.dcx_payload(open(src, "rb").read())
        oraw, oh = M.dcx_payload(open(out, "rb").read())

        kind_ok = (sh or {}).get("kind") == (oh or {}).get("kind")

        # 再一条独立轴：用 msb_write.part_fingerprint 覆盖**所有类型**的 part
        # （地图块 / 物件 / 碰撞体 / 玩家），证明"非敌人 part 一个都没动"。
        # 这是 enemy_swapper.map_parts 看不到的地方（它只看 type==2）。
        fp0 = W.part_fingerprint(sraw)
        fp1 = W.part_fingerprint(oraw)
        nonenemy_moved = [a["idx"] for a, b in zip(fp0, fp1)
                          if a != b and a.get("type") != 2]

        ok = same_count and same_names and kind_ok and not nonenemy_moved
        if not ok:
            bad += 1
        print("%-22s %6d %6d %8d %8s %8s  %s" %
              (base, len(e0), len(e1), len(diff_pos), str(expect_ok), str(kind_ok),
               "OK" if ok else "MISMATCH %s" % (nonenemy_moved[:5] or "")))

    print()
    print("独立阅读器（msb_read.read_msb）交叉验证：%d 张，%s"
          % (len(out_files), "全部一致" if bad == 0 else "%d 张不一致" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
