# -*- coding: utf-8 -*-
"""按行决定"是否保留模型绑定字段"：凡是没有被外观替换覆盖到的行，一律退回安全模式。

背景（作者 2026-10-17 实测）：随机后某个"巨大蜘蛛蝎"——数值变了（说明 regulation 生效 ✓）、
但外观没变（说明那一处 placement 的 part 没被换 ✗）、而且怪僵住不动 ✗。
根因：**行是全局换的，part 是逐地图换的** —— 外观只覆盖 9,087/22,298 个 part，
其余 59% 的落点上，模型还是老的、行里的动作字段却是新的 ⇒ 半换 ⇒ 僵住。

修法：外观替换跑完后扫一遍产出的地图，收出"真的被换过的 npc_id"集合，
   apply_plan 时把这些行之外的**每一行**都按 keep_model_fields 处理（保留动作/判定框/特效…）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def changed_npc_ids(src_maps, out_maps, keep_names=None):
    """对比替换前后的地图，返回"模型或 think 真的被改过"的 npc_id 集合

    src_maps/out_maps: 两份 {map 文件名: 路径}
    """
    import msb_read as MR
    got = set()
    for name, out_path in out_maps.items():
        src_path = src_maps.get(name)
        if not src_path or not os.path.isfile(out_path):
            continue
        try:
            a = MR.read_msb(src_path).get("enemies") or []
            b = MR.read_msb(out_path).get("enemies") or []
        except Exception:                                              # noqa: BLE001
            continue
        for x, y in zip(a, b):
            if x.get("model") != y.get("model") or x.get("think_id") != y.get("think_id"):
                nid = y.get("npc_id") or x.get("npc_id")
                if nid and nid > 0:
                    got.add(int(nid))
    return got


def patch_apply_plan():
    """给 apply_plan 加 keep_model_rows（行集合），并保留原来的 keep_model_fields 开关"""
    p = os.path.join(HERE, "enemy_randomizer.py")
    import io
    s = io.open(p, encoding="utf-8").read()
    if "keep_model_rows" in s:
        print("  （apply_plan 已支持 keep_model_rows）")
        return
    old_sig = '''               keep_rune=False, keep_model_fields=False):'''
    new_sig = '''               keep_rune=False, keep_model_fields=False, keep_model_rows=None):'''
    assert s.count(old_sig) == 1
    s = s.replace(old_sig, new_sig, 1)
    old_keep = '''        _keep = SAFE_KEEP_FIELDS if keep_model_fields else (KEEP_FIELDS_KEEP_RUNE if keep_rune else KEEP_FIELDS)
        for k in _keep:'''
    new_keep = '''        _per_row = bool(keep_model_rows is not None and int(rid) in keep_model_rows)
        _keep = (SAFE_KEEP_FIELDS if (keep_model_fields or _per_row)
                 else (KEEP_FIELDS_KEEP_RUNE if keep_rune else KEEP_FIELDS))
        for k in _keep:'''
    assert s.count(old_keep) == 1
    s = s.replace(old_keep, new_keep, 1)
    # 校验函数也要知道"哪些行用了安全集"
    old_v = '''        for k in (SAFE_KEEP_FIELDS if keep_model_fields else (KEEP_FIELDS_KEEP_RUNE if keep_rune else KEEP_FIELDS)):'''
    new_v = '''        _per_row = bool(keep_model_rows is not None and int(r["row_id"]) in keep_model_rows)
        for k in (SAFE_KEEP_FIELDS if (keep_model_fields or _per_row)
                  else (KEEP_FIELDS_KEEP_RUNE if keep_rune else KEEP_FIELDS)):'''
    assert s.count(old_v) == 1, s.count(old_v)
    s = s.replace(old_v, new_v, 1)
    s = s.replace('''def _verify_plan_applied(plain, plan_rows, rows, off0, row_size, fmap, before_rows, keep_rune=False,
                         keep_model_fields=False):''',
                  '''def _verify_plan_applied(plain, plan_rows, rows, off0, row_size, fmap, before_rows, keep_rune=False,
                         keep_model_fields=False, keep_model_rows=None):''', 1)
    s = s.replace('''                                keep_rune=keep_rune, keep_model_fields=keep_model_fields)''',
                  '''                                keep_rune=keep_rune, keep_model_fields=keep_model_fields,
                                keep_model_rows=keep_model_rows)''', 1)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("  ✓ apply_plan 支持 keep_model_rows")


if __name__ == "__main__":
    patch_apply_plan()
