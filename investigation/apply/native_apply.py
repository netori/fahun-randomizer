# native_apply.py — 全自研落盘：regulation.bin 就地打补丁（不依赖任何外部工具）
#
# 链路：AES-256-CBC 解密 → DCX(zstd) 解压 → BND4 明文 → 就地改 param 字段（尺寸不变）
#       → 用原头重新压成 DCX → 重新加密 → 写回
#
# 用法：python native_apply.py --plan <计划表> [--source <regulation.bin>] [--out <文件>] [--verify]
import argparse, csv, glob, hashlib, json, os, struct, sys, time

APPLY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APPLY))
sys.path.insert(0, APPLY)
import erio            # noqa
import param_patch as pp   # noqa

def _resolve_mod_root():
    """MOD 根目录（含 mod/regulation.bin 的那一层）。

    顺序：① 环境变量（界面解析并发布）→ ② exe 或脚本所在目录自己就是 MOD
         → ③ 同级的 法魂mod* → ④ 开发期默认路径。
    打包发给玩家走 ①②，在开发目录里走 ③④。
    """
    env = os.environ.get("CONVERGENCE_MOD_ROOT")
    if env and os.path.isdir(os.path.join(env, "mod")):
        return os.path.normpath(env)
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
    bases.append(os.path.dirname(ROOT))
    for base in bases:
        if os.path.isfile(os.path.join(base, "mod", "regulation.bin")):
            return os.path.normpath(base)
        cand = [d for d in glob.glob(os.path.join(base, "法魂mod*")) if os.path.isdir(os.path.join(d, "mod"))]
        if cand:
            return os.path.normpath(sorted(cand)[0])
    return os.path.normpath(os.path.join(os.path.dirname(ROOT), "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))


MOD = _resolve_mod_root()
TS = time.strftime("%Y%m%d_%H%M%S")

PROBE = {"ItemLotParam_map": 107020, "ItemLotParam_enemy": 340051304, "ShopLineupParam": 101550}


def bnd4_entries(plain: bytes):
    """解析 BND4 条目表（实测：flags|id|size u64|size u64|数据偏移 u32|序号 u32|名字偏移 u32）"""
    _u, _v, cnt, hsz = struct.unpack_from("<IiII", plain, 4)
    fmt = struct.unpack_from("<I", plain, hsz)[0]
    out = []
    for i in range(cnt):
        e = fmt + 0x24 * i
        size = struct.unpack_from("<Q", plain, e + 0x08)[0]
        data_off = struct.unpack_from("<I", plain, e + 0x18)[0]
        name_off = struct.unpack_from("<I", plain, e + 0x20)[0]
        j = name_off
        while j + 1 < len(plain) and plain[j:j + 2] != b"\0\0":
            j += 2
        out.append((plain[name_off:j].decode("utf-16-le", "replace"), data_off, size))
    return out


def file_start(plain: bytes, table: str) -> int:
    for name, off, _size in bnd4_entries(plain):
        if os.path.basename(name.replace("\\", "/")) == table + ".param":
            return off
    return 0


def find_row_table_in_plain(plain: bytes, table: str) -> dict:
    """行表里的偏移是"文件内相对偏移"，这里换算成明文绝对偏移"""
    base = file_start(plain, table)
    rows = pp.find_row_table(plain, PROBE[table] + base if False else PROBE[table])
    # 行表若在文件体里，探针 id 是全局唯一的小整数，能找到；但返回的 data 需加 base
    return {rid: base + d for rid, d in rows.items()} if base else rows


def plan_by_table(plan_path):
    out = {}
    for r in csv.DictReader(open(plan_path, encoding="utf-8-sig")):
        if r["old"] == r["new"]:
            continue
        out.setdefault(r["source_table"], []).append(r)
    return out


class PreconditionError(RuntimeError):
    """写前复核失败：目标格子的现状与计划不符 → 立即中止，绝不写半成品（硬约束 H12）"""


def check_preconditions(plan_path, source, quiet=True):
    """写前复核：计划里记的「旧物品（ID+类别）」必须与**当前**文件一致。

    目的：换过 MOD 版本、或上一次写入只做了一半时，不要照着旧计划继续写。
    旧版计划没有 preconditions 列时自动跳过（向后兼容）。
    """
    rows = list(csv.DictReader(open(plan_path, encoding="utf-8-sig")))
    if not rows or "preconditions" not in rows[0]:
        return {"checked": 0, "legacy": True, "bad": []}
    by_table = {}
    for r in rows:
        if r.get("old") != r.get("new"):
            by_table.setdefault(r["source_table"], []).append(r)
    plain = bytearray(erio.dcx_decompress(erio.regulation_decrypt(source)))
    bad, n = [], 0
    for table, rs in by_table.items():
        tbl = find_row_table_in_plain(bytes(plain), table)
        for r in rs:
            try:
                rid, slot = int(r["row_id"]), int(r["slot"] or 1)
                want_id = int(r["old"].split(":")[1])
            except (ValueError, KeyError, IndexError):
                continue
            if table.startswith("ItemLotParam"):
                oi = pp.offset_of(table, tbl, rid, "lotItemId", slot)
                oc = pp.offset_of(table, tbl, rid, "lotItemCategory", slot)
                if oi is None or oc is None:
                    continue
                got_id, got_cat = pp.read_u32(plain, oi), pp.read_u32(plain, oc)
                want_cat = pp.LOT_CAT.get(r.get("old_cat", ""))
            else:
                oi = pp.offset_of(table, tbl, rid, "equipId")
                ot = pp.offset_of(table, tbl, rid, "equipType")
                if oi is None or ot is None:
                    continue
                got_id, got_cat = pp.read_u32(plain, oi), pp.read_u8(plain, ot)
                want_cat = pp.SHOP_CAT.get(r.get("old_cat", ""))
            n += 1
            if got_id != want_id:
                bad.append(f"{table} 行{rid} 槽{slot}：文件里是 ID {got_id}，计划里是 {want_id}")
            elif want_cat is not None and got_cat is not None and got_cat != want_cat:
                bad.append(f"{table} 行{rid} 槽{slot}：类别不符（文件 {got_cat} / 计划 {want_cat}）")
    if bad:
        raise PreconditionError(
            f"写前复核未通过（{len(bad)}/{n} 条与当前文件不一致）—— 已中止，文件一个字节都没改。\n"
            f"最可能的原因：① 游戏文件不是本计划所基于的那一版（换过 MOD 版本？）"
            f"② 上一次写入是半途结束的。\n" + "\n".join(bad[:5])
        )
    return {"checked": n, "legacy": False, "bad": []}


def apply_native(plan_path, source=None, out_path=None, verify=True, quiet=False):
    source = source or os.path.join(MOD, "mod", "regulation.bin")
    out_path = out_path or source
    pre = check_preconditions(plan_path, source, quiet=quiet)   # ← 先复核，再动文件
    if not quiet and pre.get("checked"):
        print(f"  写前复核通过：{pre['checked']} 条与当前文件一致")
    by_table = plan_by_table(plan_path)
    plain = bytearray(erio.dcx_decompress(erio.regulation_decrypt(source)))
    before = bytes(plain)
    stats, skipped = {}, []
    for table, rs in by_table.items():
        rows = find_row_table_in_plain(bytes(plain), table)
        done = 0
        for r in rs:
            rid = int(r["row_id"])
            slot = int(r["slot"] or 1)
            oldid = int(r["old"].split(":")[1])
            newid = int(r["new"].split(":")[1])
            if table.startswith("ItemLotParam"):
                oi = pp.offset_of(table, rows, rid, "lotItemId", slot)
                oc = pp.offset_of(table, rows, rid, "lotItemCategory", slot)
                if oi is None or pp.read_u32(plain, oi) != oldid:
                    raise PreconditionError(f"写入中途发现不一致（{table} 行{rid} 槽{slot}）—— 已中止")
                pp.write_u32(plain, oi, newid)
                cat = pp.LOT_CAT.get(r.get("new_cat", ""))
                if cat:
                    pp.write_u32(plain, oc, cat)
            else:
                oi = pp.offset_of(table, rows, rid, "equipId")
                ot = pp.offset_of(table, rows, rid, "equipType")
                if oi is None or pp.read_u32(plain, oi) != oldid:
                    raise PreconditionError(f"写入中途发现不一致（{table} 行{rid} 槽{slot}）—— 已中止")
                pp.write_u32(plain, oi, newid)
                cat = pp.SHOP_CAT.get(r.get("new_cat", ""))
                if cat is not None:
                    pp.write_u8(plain, ot, cat)
            done += 1
        stats[table] = {"planned": len(rs), "applied": done}
    changed = sum(1 for i in range(len(plain)) if plain[i] != before[i])
    if not quiet:
        print(f"  计划：{ {k: v['applied'] for k, v in stats.items()} }")
        print(f"  明文改动字节 {changed} 处 | 跳过 {len(skipped)} 行")
        for s in skipped[:5]:
            print("   ✗", s)
    # 重新压 + 重新加密
    dcx = erio.dcx_compress(bytes(plain), getattr(erio_bnd_template(source), "dcx_template", None), 12)
    if out_path != source:
        erio.regulation_encrypt(dcx, out_path)
    else:
        bak = source + f".bak_{TS}"
        if not os.path.exists(bak):
            import shutil
            shutil.copy2(source, bak)
        erio.regulation_encrypt(dcx, out_path)
        if not quiet:
            print(f"  备份: {bak}")
    if verify:
        p2 = bytearray(erio.dcx_decompress(erio.regulation_decrypt(out_path)))
        same_elsewhere = sum(1 for i in range(len(p2)) if p2[i] != plain[i])
        if not quiet:
            print(f"  回读校验：与写入的明文差异 {same_elsewhere} 字节（应为 0）")
    return {"stats": stats, "changed_bytes": changed, "skipped": [list(s) for s in skipped], "out": out_path}


def erio_bnd_template(source):
    class T:
        pass
    t = T()
    t.dcx_template = erio.regulation_decrypt(source)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--source", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--report", default="")
    a = ap.parse_args()
    plan = a.plan if os.path.isabs(a.plan) else os.path.join(APPLY, a.plan)
    print(f"=== 全自研落盘（{os.path.basename(plan)}）===")
    rep = apply_native(plan, a.source or None, a.out or None)
    if a.report:
        json.dump(rep, open(os.path.join(APPLY, a.report) if not os.path.isabs(a.report) else a.report,
                            "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if not rep["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
