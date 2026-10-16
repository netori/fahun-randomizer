# -*- coding: utf-8 -*-
"""READ-ONLY 对比自检：择优配对到底把跳过率降了多少？

同一份"随机器会产出的那种"计划（全局池盲抽），两条路各跑一遍（dry-run，**不写任何 .msb.dcx**）：

    old = prefer_reachable=False   旧行为：首选目标模型不在该图 → 跳过并计数
    new = prefer_reachable=True    新行为：从该图可达行池挑替代行（同 cls / 体型接近）

  另外跑三个佐证：
    * 按类别分开看（普通→普通 / Boss→Boss），对齐上一版报告里 73.87% / 85.04% 那两个数
    * determinism_check：同输入跑两遍（prof 顺序倒置）逐 part 是否完全一致
    * 全量 634 张图 + 前 40 张图两种规模

用法：
    python investigation/swapper_probe/_probe_compare.py            # 40 张 + 全量
    python investigation/swapper_probe/_probe_compare.py 60         # 改成前 60 张
产物：`skip_rate_compare.json`（本目录），控制台也全部打印。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.dirname(HERE)
APP = os.path.join(INV, "apply")
if APP not in sys.path:
    sys.path.insert(0, APP)

import enemy_swapper as ES           # noqa: E402


def line(t=""):
    print(t)


def main():
    n_head = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    t0 = time.time()
    line("=== 择优配对：新旧跳过率对比（dry-run，不写任何地图文件）===")
    prof = ES.load_profiles(log=line)
    row_cls = ES.load_row_classes(log=line)

    out = {"maps_dir": ES.default_map_dir(), "head_maps": n_head,
           "blind_seed": ES.BLIND_SEED, "row_cls_rows": len(row_cls),
           "when": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ── 1. 前 n_head 张图（任意→任意）──
    blind = ES.global_blind_pairs(prof, n=400)
    line("")
    line("[A] 任意→任意：全局盲抽 %d 条关系 × 前 %d 张图" % (len(blind), n_head))
    out["any_head"] = ES.reach_compare(None, prof, blind, n_maps=n_head, log=line,
                                       row_cls=row_cls)

    # ── 2. 按类别分开抽（对齐上一版的 73.87% / 85.04%）──
    line("")
    line("[B] 按类别分组：从**该类别的池**里盲抽（普通→普通 / Boss→Boss）")
    out["normal_head"] = ES.reach_compare(None, prof, None, n_maps=n_head, log=line,
                                          row_cls=row_cls, kind="normal")
    out["boss_head"] = ES.reach_compare(None, prof, None, n_maps=n_head, log=line,
                                        row_cls=row_cls, kind="boss")

    # ── 3. 全量 634 张图 ──
    line("")
    line("[C] 全量：同一份盲抽计划 × 全部 634 张图")
    out["any_full"] = ES.reach_compare(None, prof, blind, n_maps=634, log=line,
                                       row_cls=row_cls)
    line("")
    line("[D] 确定性核对（全量）")
    out["determinism_full"] = ES.determinism_check(None, prof, blind, n_maps=634,
                                                   row_cls=row_cls, log=line)

    # ── 4. 另一条上游路：按图抽（旧行为下就是 0 跳过）──
    line("")
    line("[E] 上游按图抽（prefer_reachable=False，证明「池内配对」本身就够）")
    out["permap"] = ES._permap_experiment(ES.default_map_dir(), prof, 20, log=line)

    # ── 5. 副作用边界：替代行是不是真的都来自该图可达池 ──
    line("")
    line("[F] 边界核对：替代行必须来自该图可达池（不是全局池）")
    out["sub_bounds"] = sub_bounds_check(prof, row_cls, line)

    out["elapsed"] = round(time.time() - t0, 2)
    p = os.path.join(HERE, "skip_rate_compare.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    line("")
    line("[写入] %s（%.1fs）" % (p, out["elapsed"]))
    return 0


def sub_bounds_check(prof, row_cls, log=line, n_maps=12):
    """抽查若干张图：`_pick_substitute` 挑出来的替代行，其主模型**一定**在这张图的 MODEL 段里，
    且不依赖任何全局随机源（同样的参数再问一次，答案必须一模一样）。
    """
    import msb_read as M
    md = ES.default_map_dir()
    files = sorted(f for f in os.listdir(md) if f.endswith(".msb.dcx"))[:n_maps]
    bad_model = bad_repeat = asked = 0
    sample = []
    for fn in files:
        raw, _h = M.dcx_payload(open(os.path.join(md, fn), "rb").read())
        _parts, names, nmidx = ES.map_parts(raw)
        pool = ES.reachable_rows(raw, prof)
        keys = sorted({p["npc_id"] for p in ES.map_parts(raw)[0] if p["npc_id"] > 1})[:6]
        for src in keys:
            for dst in sorted(prof)[::900]:
                r1, t1, _c = ES._pick_substitute(pool, src, dst, map_name=fn,
                                                 row_cls=row_cls)
                r2, t2, _c2 = ES._pick_substitute(pool, src, dst, map_name=fn,
                                                  row_cls=row_cls)
                asked += 1
                if r1 != r2 or t1 != t2:
                    bad_repeat += 1
                if r1 is not None:
                    m = (prof.get(r1) or {}).get("model")
                    if m not in nmidx:
                        bad_model += 1
                    elif len(sample) < 5:
                        sample.append({"map": fn, "src": src, "preferred": dst,
                                       "picked": r1, "tier": t1, "model": m})
    res = {"maps": len(files), "asked": asked, "not_in_map_model": bad_model,
           "nondeterministic": bad_repeat, "sample": sample,
           "ok": not bad_model and not bad_repeat}
    if log:
        log("     问了 %d 组（源行 × 首选目标行）：主模型不在该图的 %d 个｜重复提问答案不同的 %d 个"
            " → %s" % (asked, bad_model, bad_repeat, "边界成立" if res["ok"] else "**有越界！**"))
        for s in sample:
            log("     例：%s 源 %d 首选 %d → 替代 %d（%s，模型 %s）"
                % (s["map"], s["src"], s["preferred"], s["picked"], s["tier"], s["model"]))
    return res


if __name__ == "__main__":
    sys.exit(main())
