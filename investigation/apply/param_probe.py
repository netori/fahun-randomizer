# param_probe.py — 用"已知改动"反推 ER PARAM 的二进制布局
#   原版 param：WitchyBND 解包目录里的 ItemLotParam_map.param
#   已改 param：从我自己的 reader 解出的（MOD 里已部署的）同名文件
#   两版逐字节 diff → 改动位置就是"某行某字段"的绝对偏移 → 反推布局
import os, struct, sys

APPLY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APPLY)
import erio
from bnd4_locate import entries

MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(APPLY)), "..",
                                    "法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）"))


def find_params(raw):
    """扫描明文里的 PARAM 魔数（数目与条目数一致），返回 [(offset, name_idx)]"""
    pos, i = [], 0
    while True:
        i = raw.find(b"PARAM", i)
        if i < 0:
            break
        pos.append(i)
        i += 5
    return pos


def main():
    reg = os.path.join(MOD, "mod", "regulation.bin")
    raw_new = erio.dcx_decompress(erio.regulation_decrypt(reg))
    ents = entries(raw_new)
    names = [n.replace("\\", "/").split("/")[-1] for n, _a, _b, _c in ents]
    pos = find_params(raw_new)
    print(f"  明文 {len(raw_new)} B | PARAM 块 {len(pos)} 个 | 条目名 {len(names)} 个")
    print(f"  第 0..3 块起点: {[hex(p) for p in pos[:4]]}")
    print(f"  条目名与块的点对应（前 4）: {list(zip(names[:4], [hex(p) for p in pos[:4]]))}")

    # 目标：ItemLotParam_map
    idx = names.index("ItemLotParam_map.param") if "ItemLotParam_map.param" in names else None
    print(f"  ItemLotParam_map.param 的块序号 = {idx}")
    if idx is None:
        return 1
    start = pos[idx]
    end = pos[idx + 1] if idx + 1 < len(pos) else len(raw_new)
    new_blob = raw_new[start:end]
    old_blob = open(os.path.join(APPLY, "work", "orig", "regulation-bin", "ItemLotParam_map.param"), "rb").read()
    print(f"  新版块 {len(new_blob)} B | 原版文件 {len(old_blob)} B")

    # 头部
    print("  新版块前 0x60:")
    for off in range(0, 0x60, 16):
        c = new_blob[off:off + 16]
        print(f"   {off:04x}  {c.hex(' ')}  {''.join(chr(x) if 32 <= x < 127 else '.' for x in c)}")
    print("  原版前 0x60:")
    for off in range(0, 0x60, 16):
        c = old_blob[off:off + 16]
        print(f"   {off:04x}  {c.hex(' ')}  {''.join(chr(x) if 32 <= x < 127 else '.' for x in c)}")

    # diff（只看公共长度）
    n = min(len(new_blob), len(old_blob))
    diff = [i for i in range(n) if new_blob[i] != old_blob[i]]
    print(f"\n  两版差异字节 {len(diff)} 个（含上下文合并）")
    if diff:
        groups, cur = [], [diff[0]]
        for i in diff[1:]:
            if i - cur[-1] <= 8:
                cur.append(i)
            else:
                groups.append((cur[0], cur[-1]))
                cur = [i]
        groups.append((cur[0], cur[-1]))
        print(f"  差异区间 {len(groups)} 段；前 12 段：")
        for a, b in groups[:12]:
            print(f"    {hex(a)}..{hex(b)}  原={old_blob[a:b+1].hex()}  新={new_blob[a:b+1].hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
